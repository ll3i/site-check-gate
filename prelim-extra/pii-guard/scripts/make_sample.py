#!/usr/bin/env python3
"""
pii-guard / make_sample.py
합성 시연 데이터 생성 (고정 시드 42, 완전 오프라인, 표준 라이브러리만 사용)

출력: work/sample_roster.csv, work/sample_notes.md, work/sample_config.env

원칙: 완성된 예시 값·직원·이메일·카드·키의 실제 문자열 형태를 소스 코드 안에
하드코딩하지 않고, 알고리즘과 문자열 결합으로 실행 시점에만 생성한다.
첫 줄에 "합성 데이터(실존 아님)"을 표기한다.
"""

import os
import csv
import random
import argparse
from datetime import date

RANDOM = random.Random(42)

# ── 이름 풀 (더미, 실존인물과 무관한 조합) ──────────────────────────────────
FIRST_NAMES = [
    "서", "김", "이", "박", "최", "정", "강", "조", "윤", "장",
]
LAST_NAMES = [
    "민우", "지현", "도윤", "서연", "하늘", "예은", "준혁", "수아",
    "태윤", "하린", "은서", "도현", "채원", "우진", "소율", "연서",
]

def make_name(rng):
    return rng.choice(FIRST_NAMES) + rng.choice(LAST_NAMES)

def make_phone_mobile(rng):
    prefix = rng.choice(["010", "011", "016", "017", "018", "019"])
    n1 = rng.randint(0, 9999)
    n2 = rng.randint(0, 9999)
    return f"{prefix}-{n1:04d}-{n2:04d}"

def make_phone_landline(rng):
    area = rng.choice([2, 3, 3, 4])  # 02, 031, 032, 031 등 빈도
    if area == 2:
        num1 = 2
    else:
        num1 = rng.randint(30, 50)
    n2 = rng.randint(100, 999)
    n3 = rng.randint(1000, 9999)
    return f"{num1:02d}-{n2:03d}-{n3:04d}"

# ── 주민등록번호 (검증번호 맞는 가상 조합) ──────────────────────────────────
_DIGIT = "0123456789"

def _luhn10(digits):
    """주민번호 10자리 체크섬 계산. 가중치 2,3,4,5,6,7,8,9,2,3,4,5 (12자리 중 앞10자리)."""
    w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    s = sum(int(digits[i]) * w[i] for i in range(10))
    return ((11 - (s % 11)) % 11) % 10

def make_resident(rng):
    """생년월일 유효 + 검증번호가 맞는 13자리 주민번호(######-#######)."""
    y2 = rng.randint(80, 99)          # 1980~1999년생 위주
    mm = rng.randint(1, 12)
    dd = rng.randint(1, 28)           # 월마다 다를 수 있지만 단순화
    body = f"{y2:02d}{mm:02d}{dd:02d}"
    # 나머지 7자리는 자릿수만 채움 (검증번호 계산용 앞10자리를 확보해야 함)
    suffix7 = "".join(rng.choice(_DIGIT) for _ in range(7))
    d10 = body + suffix7             # 17자리 중 앞 10자리로 체크섬 계산
    chk = _luhn10(d10)
    full = body + suffix7[:6] + str(chk)
    return f"{full[:6]}-{full[6:]}"

# ── Luhn 통과 신용카드 (15~19자리) ────────────────────────────────────────
def luhn_check(digits):
    s, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if (i % 2) == parity:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return s % 10 == 0

def make_credit_card(rng, length=16):
    """Luhn을 만족하는 숫자열 생성 (첫 15자리 임의, 16번째가 체크 디지트)."""
    while True:
        digits = [rng.randint(0, 9) for _ in range(length - 1)]
        s, parity = 0, length % 2
        for i, d in enumerate(digits):
            if (i % 2) == parity:
                d2 = d * 2
                if d2 > 9:
                    d2 -= 9
                s += d2
            else:
                s += d
        check = (10 - (s % 10)) % 10
        digits.append(check)
        if luhn_check("".join(map(str, digits))):
            return "".join(map(str, digits))

def format_credit_card(digs):
    """16자리: 4-4-4-4 형태. 15자리면 4-6-5 등."""
    n = len(digs)
    if n == 16:
        return f"{digs[:4]} {digs[4:8]} {digs[8:12]} {digs[12:]}"
    if n == 15:
        return f"{digs[:4]} {digs[4:10]} {digs[10:]}"
    return " ".join(digs[i:i+4] for i in range(0, n, 4))

# ── 사업자등록번호 (체크섬 맞는 조합) ──────────────────────────────────────
def make_business(rng):
    """###-##-##### 형태, 체크섬 통과."""
    while True:
        a = rng.randint(100, 999)
        b = rng.randint(10, 99)
        c = rng.randint(10000, 99999)
        nums = [int(ch) for ch in f"{a}{b}{c}"]
        w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
        s = sum(nums[i] * w[i] for i in range(9))
        chk = s % 10
        ninth_mult_tens = (nums[8] * 5) // 10
        if chk == ninth_mult_tens:
            return f"{a:03d}-{b:02d}-{c:05d}"

# ── 계좌번호 (문맥용으로, 은행명+계좌) ──────────────────────────────────────
def make_account(rng):
    """3-2-2 또는 3-3-3 등 계좌 형태. 문맥 키워드(계좌·은행)와 함께 사용됨."""
    bank = rng.choice(["신한은행", "우리은행", "국민은행", "하나은행"])
    n1 = rng.randint(100, 999)
    n2 = rng.randint(10, 99)
    n3 = rng.randint(100000, 999999)
    return bank, f"{n1:03d}-{n2:02d}-{n3:06d}"

# ── 여권번호 (신형: 영문1+숫자3+영숫자1+숫자4) ─────────────────────────────
def make_passport(rng):
    letter = rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")
    n3 = rng.randint(100, 999)
    mid = rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789")
    tail = rng.randint(1000, 9999)
    return f"{letter}{n3:03d}{mid}{tail:04d}"

# ── 학번 (10자리) ──────────────────────────────────────────────────────────
def make_student_id(rng):
    return f"{rng.randint(2015, 2025)}{rng.randint(10000, 99999):05d}"

# ── 생년월일 ───────────────────────────────────────────────────────────────
def make_birth_date(rng):
    y = rng.randint(1990, 2005)
    m = rng.randint(1, 12)
    d = rng.randint(1, 28)
    return f"{y:04d}-{m:02d}-{d:02d}"

# ── 주소 (서울 도로명 주소, 합성) ──────────────────────────────────────────
ROAD_NAMES = [
    "테헤란로", "강남대로", "반포대로", "봉은사로", "도산대로",
    "압구정로", "학동로", "사평대로", "양재대로", "올림픽로",
    "성북구", "종로구", "마포구", "영등포구", "관악구",
]
STREET_NUMS = range(1, 500)
def make_address(rng):
    gu = rng.choice(["서울"] + [""] * 5)   # 대부분 서울
    road = rng.choice(ROAD_NAMES)
    num = rng.choice(STREET_NUMS)
    build = rng.randint(1, 30)
    return f"{gu} {road} {num} {build}번지"

# ── API 키·토큰 (합성 형태, 실제 키와 무관) ────────────────────────────────
def make_openai_key(rng):
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    body = "".join(rng.choice(chars) for _ in range(40))
    return f"sk-{body}"

def make_aws_key(rng):
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    body = "".join(rng.choice(chars) for _ in range(16))
    prefix = rng.choice(["AKIA", "ASIA"])
    return f"{prefix}{body}"

def make_github_token(rng):
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    body = "".join(rng.choice(chars) for _ in range(36))
    return f"ghp_{body}"

def make_database_url(rng):
    user = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(6))
    pw = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789!@#$%") for _ in range(8))
    host = f"{rng.randint(10,192)}.{rng.randint(0,255)}.{rng.randint(0,255)}.{rng.randint(1,254)}"
    port = rng.choice([5432, 3306, 1433, 27017])
    db = rng.choice(["prod_db", "analytics", "user_records", "survey_data"])
    return f"postgres://{user}:{pw}@{host}:{port}/{db}"

def make_password(rng):
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*"
    return "".join(rng.choice(chars) for _ in range(rng.randint(9, 14)))

# ── IPv4 (사설 IP 중 일부) ─────────────────────────────────────────────────
def make_private_ip(rng):
    a = rng.choice([10, 172, 192, 127])
    if a == 10:
        b = rng.randint(0, 255)
    elif a == 172:
        b = rng.randint(16, 31)
    elif a == 192:
        b = 168
    else:
        b = 0
    c = rng.randint(0, 255)
    d = rng.randint(1, 254)
    return f"{a}.{b}.{c}.{d}"

# ── 파일 생성 ──────────────────────────────────────────────────────────────

def write_roster(out_dir, rng):
    path = os.path.join(out_dir, "sample_roster.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["이름", "주민등록번호", "휴대전화", "이메일", "주소", "학번"])
        for _ in range(6):
            name = make_name(rng)
            resident = make_resident(rng)
            phone = make_phone_mobile(rng)
            email = f"user{rng.randint(1,99)}@example.com"
            addr = make_address(rng)
            sid = make_student_id(rng)
            w.writerow([name, resident, phone, email, addr, sid])
    print(f"생성: {path}")
    return path

def write_notes(out_dir, rng):
    path = os.path.join(out_dir, "sample_notes.md")
    lines = []
    lines.append("합성 데이터(실존 아님) — 점검 시연을 위한 합성 회의록입니다.")
    lines.append("")
    lines.append("# 회의 메모 — 2026년 3월 정기 회의")
    lines.append("")
    lines.append("## 참석자")
    lines.append("")
    attendees = []
    for _ in range(4):
        name = make_name(rng)
        phone = make_phone_landline(rng)
        attendees.append((name, phone))
        lines.append(f"- {name}({phone}) — {rng.choice(['과장','대리','주무관','팀장'])})")
    lines.append("")
    lines.append("## 논의 안건")
    lines.append("")
    lines.append("1. 다음 달 행사 예산 승인")
    lines.append("   - 담당자:" + attendees[0][0] + f" 유선전화 {attendees[0][1]}")
    lines.append("   - 입금 계좌: " + make_account(rng)[0] + " " + make_account(rng)[1])
    lines.append("")
    lines.append("2. 참가자 확인용 카드결제 샘플")
    lines.append("   - 카드번호(예시): " + format_credit_card(make_credit_card(rng)))
    lines.append("")
    lines.append("3. 업체 계약 진행")
    lines.append("   - 사업자등록번호: " + make_business(rng))
    lines.append("")
    lines.append("4. 참가자 여권 정보 수집")
    lines.append("   - 여권번호(신형): " + make_passport(rng))
    lines.append("")
    lines.append("5. 내부 네트워크")
    lines.append(f"   - 서버 IP: {make_private_ip(rng)}")
    lines.append("")
    lines.append("6. 참가자 기본 정보")
    lines.append(f"   - 이름: {make_name(rng)}(님)")
    lines.append(f"   - 생년월일: {make_birth_date(rng)}")
    lines.append("")
    lines.append("---")
    lines.append("합성 데이터(실존 아님)")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"생성: {path}")
    return path

def write_config(out_dir, rng):
    path = os.path.join(out_dir, "sample_config.env")
    lines = []
    lines.append("# 합성 데이터(실존 아님) — 점검 시연을 위한 합성 설정 파일입니다.")
    lines.append("")
    lines.append(f"OPENAI_API_KEY={make_openai_key(rng)}")
    lines.append(f"AWS_ACCESS_KEY_ID={make_aws_key(rng)}")
    lines.append(f"GITHUB_TOKEN={make_github_token(rng)}")
    lines.append(f"DATABASE_URL={make_database_url(rng)}")
    lines.append(f"DB_PASSWORD={make_password(rng)}")
    lines.append("")
    lines.append("# 합성 데이터(실존 아님)")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"생성: {path}")
    return path

# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="pii-guard 합성 시연 데이터 생성 (고정 시드 42)"
    )
    parser.add_argument(
        "--out", default="work",
        help="출력 디렉터리 (기본: work)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="시드 (기본: 42)",
    )
    args = parser.parse_args()

    out = args.out
    os.makedirs(out, exist_ok=True)

    rng = random.Random(args.seed)

    write_roster(out, rng)
    write_notes(out, rng)
    write_config(out, rng)

    print(f"완료: {out}/sample_roster.csv, sample_notes.md, sample_config.env")

if __name__ == "__main__":
    main()
