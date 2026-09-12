#!/usr/bin/env python3
"""
pii-guard / scan_pii.py
개인정보·비밀키 노출 점검 스크립트 (완전 오프라인, 표준 라이브러리만 사용)

원칙: 탐지된 원문 값을 대화·보고서에 그대로 출력하지 않고 마스킹값·위치만 보고한다.
"""

import re
import json
import os
import sys
import html as _html
import zipfile
import argparse
from datetime import date
from collections import OrderedDict

# ══════════════════════════════════════════════════════════════════════════════
# 1. 인코딩
# ══════════════════════════════════════════════════════════════════════════════

_DECODE_CHAINS = [
    ("utf-8-sig", "strict"),
    ("utf-8",     "strict"),
    ("cp949",     "strict"),
    ("euc-kr",    "strict"),
    ("latin-1",   "replace"),
]

def read_text_file(path):
    for enc, errors in _DECODE_CHAINS:
        try:
            with open(path, "rb") as f:
                raw = f.read()
            return raw.decode(enc, errors), enc, None
        except (UnicodeDecodeError, LookupError):
            continue
    return "", "unknown", "디코딩 불가"

# ══════════════════════════════════════════════════════════════════════════════
# 2. 문서 텍스트 추출 (docx / hwpx / pptx / xlsx = zip+XML)
# ══════════════════════════════════════════════════════════════════════════════

def _strip_tags(xml_bytes):
    text = xml_bytes.decode("utf-8", "replace")
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)

def extract_doc_text(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except (zipfile.BadZipFile, OSError):
        return None, f"손상되었거나 zip이 아님: {path}"
    main_xml = None
    for c in ["word/document.xml", "ppt/presentation.xml", "xl/workbook.xml",
              "document.xml"]:
        if c in names:
            main_xml = c
            break
    if main_xml is None:
        for n in names:
            if n.endswith(".xml") and "document" in n.lower():
                main_xml = n
                break
    if main_xml is None:
        for n in names:
            if n.endswith(".xml"):
                main_xml = n
                break
    if main_xml is None:
        return "", "문서 XML을 찾을 수 없음"
    try:
        with zipfile.ZipFile(path) as z:
            raw = z.read(main_xml)
        return _strip_tags(raw), None
    except Exception as e:
        return None, f"XML 읽기 실패: {e}"

def is_binary(path):
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(512)
    except OSError:
        return True

# ══════════════════════════════════════════════════════════════════════════════
# 3. 검증 함수
# ══════════════════════════════════════════════════════════════════════════════

def resident_checksum(d10):
    w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    s = sum(int(d10[i]) * w[i] for i in range(10))
    return ((11 - (s % 11)) % 11) % 10

def valid_date(y, m, d):
    if y < 1900 or m < 1 or m > 12 or d < 1 or d > 31:
        return False
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False

def validate_resident(full):
    m = re.match(r"^(\d{6})-(\d{7})$", full)
    if not m:
        return ("invalid-date", "형식 불일치")
    y2 = int(m.group(1)[:2])
    body = m.group(1)[2:] + m.group(2)
    mm, dd = int(body[:2]), int(body[2:4])
    gender = int(full[7])
    cy = 2000 + y2 if y2 < 50 else 1900 + y2
    if not valid_date(cy, mm, dd):
        return ("invalid-date", f"날짜 무효({cy:04d}-{mm:02d}-{dd:02d})")
    if cy >= 2020 and mm >= 10 and gender in (9, 0):
        return ("form-only", "2020.10 이후 발급 — 검증번호 없음")
    chk = resident_checksum(body)
    expected = int(full[12])
    if chk == expected:
        return ("valid", "검증 통과")
    return ("form-only", f"검증번호 불일치(예상 {chk}, 실제 {expected})")

def luhn(digits):
    if not digits.isdigit():
        return False
    s, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if (i % 2) == parity:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return s % 10 == 0

def validate_business(full):
    m = re.match(r"^(\d{3})-(\d{2})-(\d{5})$", full)
    if not m:
        return False
    nums = [int(c) for c in m.group(1) + m.group(2) + m.group(3)]
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(nums[i] * w[i] for i in range(9))
    return (s % 10) == ((nums[8] * 5) // 10)

def validate_passport(fmt):
    return bool(re.match(r"^[A-Z]\d{3}[A-Z0-9]\d{4}$", fmt))

def validate_fax_or_landline(raw):
    return bool(re.match(r"^(02|\d{2,3})-\d{3,4}-\d{4}$", raw))

def is_reserved_ip(ip):
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return False
    a, b = int(parts[0]), int(parts[1])
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    if a == 127:
        return True
    if a == 0:
        return True
    return False

# ══════════════════════════════════════════════════════════════════════════════
# 4. 마스킹 함수
# ══════════════════════════════════════════════════════════════════════════════

def mask_resident(v):
    return v[:7] + "-*******"

def mask_mobile(v):
    p = v.split("-")
    if len(p) == 3:
        return f"{p[0]}-****-****"
    return v[:4] + "-****-****"

def mask_landline(v):
    p = v.split("-")
    if len(p) >= 3:
        return f"{p[0]}-****-{p[-1]}"
    return "****-****"

def mask_email(v):
    at = v.find("@")
    if at > 2:
        return v[:2] + "***@" + v[at+1:]
    return "***@***.***"

def mask_credit_card(v):
    d = re.sub(r"[\s-]", "", v)
    last4 = d[-4:] if len(d) >= 4 else d
    return f"**** **** **** {last4}"

def mask_business(v):
    return v[:3] + "-**-" + v[-4:]

def mask_license(v):
    return v[:2] + "-**-******-**"

def mask_account(v):
    return "***-****" + (v[-2:] if len(v) >= 2 else "")

def mask_passport(v):
    return v[0] + "***" + v[-2:]

def mask_ipv4(v):
    p = v.split(".")
    return ".".join(p[:2] + "**" if i < 3 else p for i, p in enumerate(p))

def mask_student_id(v):
    if len(v) >= 4:
        return v[:2] + "***" + v[-2:]
    return "***"

def mask_birth(v):
    return v[:4] + "-**-**"

def mask_name(v):
    return v[0] + "*" if len(v) >= 2 else "*"

def mask_address(v):
    return v[:2] + "**~"

def mask_vehicle(v):
    return v[:2] + "가***"

def mask_api_key(v):
    return v[:4] + "…[REDACTED]"

def mask_conn_str(v):
    m = re.match(r"^([a-z]+)://[^@]+@(.*)$", v, re.IGNORECASE)
    if m:
        return f"{m.group(1)}://[REDACTED]@{m.group(2)}"
    return v[:20] + "…[REDACTED]"

def mask_jwt(v):
    p = v.split(".")
    if len(p) >= 3:
        return p[0][:20] + "…" + p[-1][:8]
    return v[:16] + "…[REDACTED]"

def mask_secret(v):
    return v[:4] + "…[REDACTED]"

def mask_info(v):
    return v[:8] + "…"

# ══════════════════════════════════════════════════════════════════════════════
# 5. 탐지 규칙
# ══════════════════════════════════════════════════════════════════════════════

# ── 문맥 키워드 ───────────────────────────────────────────────────────────────

LINE_KW = {
    "account": [
        "계좌", "은행", "예금주", "입금", "송금", "통장", "계좌번호",
        "은행명", "대구은행", "신한은행", "우리은행", "국민은행",
        "KEB하나은행", "기업은행", "농협은행", "SC제일은행", "입급",
    ],
    "passport": [
        "여권", "passport", "여권번호", "여권 발급", "passport no",
    ],
    "student_id": [
        "학번", "사번", "사원번호", "수험번호", "직원번호", "학생번호",
    ],
    "birth": [
        "생년월일", "생일", "출생", "태어남", "출생일", "생년월일:",
    ],
    "name": [
        "이름", "성명", "담당자", "참석자", "예금주", "문의",
        "작성자", "발언자", "발표자", "보고자",
        "홍길동", "김철수", "이영희", "박민수", "최지호",
        "이름:", "성명:",
    ],
    "honorific": [
        "님", "씨", "과장", "대리", "주무관", "팀장", "실장",
        "대표", "사장", "부장", "차장", "수석", "연구원",
        "교수", "선생님", "의사", "변호사", "검사",
    ],
    "address": [
        "주소", "거주", "주소지", "자택", "주소:", "거주지",
        "현주소", "본적", "소재지", "주소 ",
    ],
}

# ── 규칙 리스트 (priority 1 = 최우선; 숫자가 작을수록 먼저 검출) ──────────────

RULES = [
    # ─ 비밀키 · 접속문자열 (priority 1) ──────────────────────────────────────
    {
        "type": "openai_api_key",
        "pattern": re.compile(r"\b(sk-[A-Za-z0-9]{20,})\b"),
        "confidence": "high", "priority": 1,
        "check": lambda m: len(m.group(1)) >= 22,
        "mask": mask_api_key,
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "aws_access_key",
        "pattern": re.compile(r"\b((?:AKIA|ASIA)[A-Za-z0-9]{16,})\b"),
        "confidence": "high", "priority": 1,
        "check": lambda m: len(m.group(1)) >= 20,
        "mask": mask_api_key,
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "github_token",
        "pattern": re.compile(
            r"\b(ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|"
            r"ghu_[A-Za-z0-9]{30,}|ghs_[A-Za-z0-9]{30,}|ghr_[A-Za-z0-9]{30,})\b"
        ),
        "confidence": "high", "priority": 1,
        "check": lambda m: len(m.group(1)) >= 33,
        "mask": mask_api_key,
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "google_api_key",
        "pattern": re.compile(r"\b(Aiza[A-Za-z0-9_-]{35,})\b"),
        "confidence": "high", "priority": 1,
        "check": lambda m: len(m.group(1)) >= 35,
        "mask": mask_api_key,
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "slack_token",
        "pattern": re.compile(r"\b(xox[baprs]-[A-Za-z0-9\-]{10,})\b"),
        "confidence": "high", "priority": 1,
        "check": lambda m: len(m.group(1)) >= 12,
        "mask": mask_api_key,
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "jwt",
        "pattern": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+=*\b"),
        "confidence": "high", "priority": 1,
        "check": lambda m: m.group(0).count(".") >= 2,
        "mask": mask_jwt,
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "private_key",
        "pattern": re.compile(
            r"-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH|ENCRYPTED|PKCS8|PEM)?\s*PRIVATE\s+KEY-----"
        ),
        "confidence": "high", "priority": 1,
        "check": lambda m: True,
        "mask": lambda v: "-----BEGIN [PRIVATE KEY REDACTED]-----",
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "connection_string",
        "pattern": re.compile(
            r"\b([a-z]+://[^@\s]+:[^@\s]+@[a-zA-Z0-9.\_-]+(?::\d+)?(?:/[^\s]*)?)\b",
            re.IGNORECASE,
        ),
        "confidence": "high", "priority": 1,
        "check": lambda m: True,
        "mask": mask_conn_str,
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "bearer_token",
        "pattern": re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b"),
        "confidence": "medium", "priority": 1,
        "check": lambda m: len(m.group(0)) > 20,
        "mask": lambda v: "Bearer …[REDACTED]",
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "generic_secret",
        "pattern": re.compile(
            r"(?i)\b((?:api[_ ]?key|secret|token|password|passwd|pwd|auth)[=:]\s*)([A-Za-z0-9_\-\.!@#$%^&*+=]{8,})\b"
        ),
        "confidence": "medium", "priority": 1,
        "check": lambda m: len(m.group(2)) >= 8,
        "mask": lambda v: v.rstrip()[:4] + "…[REDACTED]",
        "ctx": False, "ctx_kw": None,
    },

    # ─ 고유식별정보 (priority 2) ──────────────────────────────────────────────
    {
        "type": "resident_number",
        "pattern": re.compile(r"\b(\d{6}-\d{7})\b"),
        "confidence": "high", "priority": 2,
        "check": lambda m: validate_resident(m.group(1))[0] in ("valid", "form-only"),
        "mask": mask_resident,
        "ctx": False, "ctx_kw": None,
        "meta": lambda m: validate_resident(m.group(1)),
    },
    {
        "type": "credit_card",
        "pattern": re.compile(
            r"\b(\d{4}[\s-]?\d{4,6}[\s-]?\d{4,7}[\s-]?\d{1,})\b"
        ),
        "confidence": "high", "priority": 2,
        "check": lambda m: luhn(re.sub(r"[\s-]", "", m.group(1))),
        "mask": mask_credit_card,
        "ctx": False, "ctx_kw": None,
        "post": "credit_card_context",
    },
    {
        "type": "business_number",
        "pattern": re.compile(r"\b(\d{3}-\d{2}-\d{5})\b"),
        "confidence": "high", "priority": 2,
        "check": lambda m: validate_business(m.group(1)),
        "mask": mask_business,
        "ctx": False, "ctx_kw": None,
        "meta": lambda m: (validate_business(m.group(1)), "체크섬 검증"),
    },
    {
        "type": "license",
        "pattern": re.compile(r"\b(\d{2}-\d{2}-\d{6}-\d{2})\b"),
        "confidence": "high", "priority": 2,
        "check": lambda m: True,
        "mask": mask_license,
        "ctx": False, "ctx_kw": None,
    },

    # ─ 이메일 (priority 3) ────────────────────────────────────────────────────
    {
        "type": "email",
        "pattern": re.compile(r"\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b"),
        "confidence": "high", "priority": 3,
        "check": lambda m: "@" in m.group(1) and "." in m.group(1).split("@")[1],
        "mask": mask_email,
        "ctx": False, "ctx_kw": None,
    },

    # ─ 전화 (priority 4) ──────────────────────────────────────────────────────
    {
        "type": "mobile_phone",
        "pattern": re.compile(r"\b(01[0-9]-\d{3,4}-\d{4})\b"),
        "confidence": "high", "priority": 4,
        "check": lambda m: validate_fax_or_landline(m.group(1)) and m.group(1).startswith("01"),
        "mask": mask_mobile,
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "landline_phone",
        "pattern": re.compile(r"\b((?:02|\d{2,3})-\d{3,4}-\d{4})\b"),
        "confidence": "high", "priority": 4,
        "check": lambda m: re.match(r"^(?!01)", m.group(1)) and validate_fax_or_landline(m.group(1)),
        "mask": mask_landline,
        "ctx": False, "ctx_kw": None,
    },
    {
        "type": "toll_free",
        "pattern": re.compile(r"\b(15\d{2}-\d{4})\b"),
        "confidence": "medium", "priority": 4,
        "check": lambda m: True,
        "mask": lambda v: "15**-" + v[-4:],
        "ctx": False, "ctx_kw": None,
    },

    # ─ IPv4 (priority 5, info) ────────────────────────────────────────────────
    {
        "type": "ipv4",
        "pattern": re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"),
        "confidence": "info", "priority": 5,
        "check": lambda m: (
            all(0 <= int(p) <= 255 for p in m.group(1).split("."))
            and not any(
                len(p) > 1 and p[0] == "0" and p != "0"
                for p in m.group(1).split(".")
            )
        ),
        "mask": mask_ipv4,
        "ctx": False, "ctx_kw": None,
        "meta": lambda m: ("사설/루프백" if is_reserved_ip(m.group(1)) else "일반"),
    },

    # ─ 문맥 기반 (priority 6) ─────────────────────────────────────────────────

    # 계좌번호: 같은 줄에 계좌·은행·입금 등 키워드가 있으면 탐지
    {
        "type": "account_number",
        "pattern": re.compile(r"\b(\d{3,5}-\d{2,6}-\d{2,6})\b"),
        "confidence": "medium", "priority": 6,
        "check": None,            # 문맥으로 대체 검증
        "mask": mask_account,
        "ctx": True, "ctx_kw": "account",
        "exclude_overlapping": {"mobile_phone", "landline_phone"},
    },

    # 여권번호 (신형): 같은 줄 여권 키워드가 있으면
    {
        "type": "passport_new",
        "pattern": re.compile(r"\b([A-Z]\d{3}[A-Z0-9]\d{4})\b"),
        "confidence": "medium", "priority": 6,
        "check": None,
        "mask": mask_passport,
        "ctx": True, "ctx_kw": "passport",
    },

    # 학번/사번: CSV 헤더 열 이름 또는 같은 줄 키워드
    {
        "type": "student_id",
        "pattern": re.compile(r"\b(\d{5,10})\b"),
        "confidence": "medium", "priority": 6,
        "check": None,
        "mask": mask_student_id,
        "ctx": True, "ctx_kw": "student_id",
        "exclude_overlapping": {"resident_number", "credit_card"},
    },

    # 생년월일 8자리(YYYYMMDD) 또는 YYYY-MM-DD
    {
        "type": "birth_date",
        "pattern": re.compile(r"\b(\d{4}[-/]\d{2}[-/]\d{2})\b"),
        "confidence": "medium", "priority": 6,
        "check": lambda m: valid_date(
            *map(int, re.split(r"[-/]", m.group(1)))
        ),
        "mask": mask_birth,
        "ctx": True, "ctx_kw": "birth",
    },

    # 이름: 성씨+1~3자 (문맥 키워드 or CSV 헤더 '이름/성명' 또는 호칭 동반)
    {
        "type": "name",
        "pattern": re.compile(r"\b([가-힣A-Za-z]\\S{1,3})"),
        "confidence": "low", "priority": 6,
        "check": None,
        "mask": mask_name,
        "ctx": True, "ctx_kw": ["name", "honorific"],
        "exclude_overlapping": {"resident_number", "email", "business_number",
                                "credit_card", "license"},
    },

    # 주소: 시·도 + 시군구 + 로/길 + 번지 형태
    {
        "type": "address",
        "pattern": re.compile(
            r"\b([가-힣A-Za-z]+(?:[시|도])\s*[가-힣A-Za-z]+(?:\s*[로|길]\s*\d+)"
            r"|[가-힣A-Za-z]+구\s*[가-힣A-Za-z]+로\s*\d+|"
            r"[가-힣A-Za-z]+시\s*[가-힣A-Za-z]+구\s*[가-힣A-Za-z]+로\s*\d+"
            r"|[가-힣A-Za-z]+로\s*\d+[ -~]*[가-힣A-Za-z]+)\b"
        ),
        "confidence": "medium", "priority": 6,
        "check": None,
        "mask": mask_address,
        "ctx": True, "ctx_kw": "address",
        "exclude_overlapping": {"resident_number", "business_number"},
    },

    # 차량번호
    {
        "type": "vehicle_plate",
        "pattern": re.compile(r"\b(\d{2}[가-힣]\d{4})\b"),
        "confidence": "medium", "priority": 6,
        "check": None,
        "mask": mask_vehicle,
        "ctx": False, "ctx_kw": None,
    },
]

# ══════════════════════════════════════════════════════════════════════════════
# 6. 문맥 판단 헬퍼
# ══════════════════════════════════════════════════════════════════════════════

def context_ok(line, kw_list):
    """line 안에 kw_list의 단어가 하나라도 있으면 문맥 충족."""
    for kw in kw_list:
        if kw in line:
            return True
    return False

def csv_header_context(header_cells, kw_list):
    """CSV 헤더 열 이름 중 하나라도 kw_list에 있으면 True."""
    for cell in header_cells:
        cell_lower = cell.strip().lower()
        for kw in kw_list:
            if kw.lower() in cell_lower:
                return True
    return False

# ══════════════════════════════════════════════════════════════════════════════
# 7. 라인 스캔 (우선순위 + 겹침 배제)
# ══════════════════════════════════════════════════════════════════════════════

def scan_lines(lines, csv_headers=None):
    """
    lines: [(line_idx, text), ...]  (1-based idx)
    csv_headers: 열 이름 리스트 (없으면 None)
    반환: findings = [dict(...)]
    """
    findings = []
    for ln_idx, line in lines:
        # 문맥 키워드 미리 계산
        ctx_words = {kw for kw_group in LINE_KW.values() for kw in kw_group if kw in line}
        for rule in sorted(RULES, key=lambda r: r["priority"]):
            for m in rule["pattern"].finditer(line):
                matched_text = m.group(1) if m.lastindex else m.group(0)

                # 1) 검증 실패 → 스킵 (또는 보류)
                if rule.get("check") is not None and not rule["check"](m):
                    continue

                # 2) 문맥 필요 규칙
                if rule.get("ctx"):
                    ctx_list = rule["ctx_kw"] if isinstance(rule["ctx_kw"], list) else [rule["ctx_kw"]]
                    if not context_ok(line, ctx_list):
                        continue
                    # CSV 헤더를 문맥으로도 사용 (학번·이름 등)
                    if csv_headers and csv_header_context(csv_headers, ctx_list):
                        pass  # 문맥 충족
                    else:
                        # 줄 문맥은 위에서 체크했고, csv_headers도 함께 체크함
                        pass

                # 3) 우선순위 겹침 배제 — 이미 보고된 구간과 겹치면 스킵
                span = (m.start(), m.end())
                if any(prev_span[0] <= span[1] and span[0] <= prev_span[1]
                       for prev_span in [(f["start"], f["end"]) for f in findings]):
                    continue

                # 4) credit_card_context: 카드 문맥 없으면 길이가 15 미만이면 medium으로 강등
                confidence = rule["confidence"]
                if rule.get("post") == "credit_card_context":
                    if len(re.sub(r"[\s-]", "", matched_text)) < 15:
                        # 카드 문맥 키워드
                        card_kw = ["카드", "credit", "card", "결제", "pay", "카드번호"]
                        if not context_ok(line, card_kw):
                            confidence = "medium"

                # 5) 메타(전거 결과) 계산
                meta = rule.get("meta")
                meta_result = None
                if meta is not None:
                    meta_result = meta(m)
                    # 주민번호: validate_resident 결과 중 'invalid-date'면 스킵
                    if rule["type"] == "resident_number":
                        status, _ = meta_result
                        if status == "invalid-date":
                            continue
                        if status == "form-only":
                            confidence = "medium"

                # 마스킹
                masked = rule["mask"](matched_text)

                conf_level = confidence

                finding = OrderedDict([
                    ("type", rule["type"]),
                    ("line", ln_idx),
                    ("col", m.start() + 1),
                    ("matched", len(matched_text)),
                    ("confidence", conf_level),
                    ("validated", rule.get("check") is not None and rule["check"](m)),
                    ("masked", masked),
                    ("context", line[:120]),
                    ("start", m.start()),
                    ("end", m.end()),
                ])
                # meta 필드가 있으면 추가
                if meta_result is not None:
                    finding["meta"] = meta_result
                findings.append(finding)
    return findings

# ══════════════════════════════════════════════════════════════════════════════
# 8. 메인 처리: 파일 → 텍스트 → 라인 스캔 → 집계
# ══════════════════════════════════════════════════════════════════════════════

def read_file_lines(path):
    """
    반환: (lines: [(idx, text)], encoding, error_or_None, is_doc, masked_path_or_None, skip_reason_or_None)
    is_doc=True면 마스킹본은 .txt로 생성.
    """
    ext = os.path.splitext(path)[1].lower()

    doc_exts = {".docx", ".hwpx", ".pptx", ".xlsx"}

    if ext in doc_exts:
        # 문서 파일
        txt, err = extract_doc_text(path)
        if txt is None:
            return [], "utf-8", err, True, None, err
        # 마스킹본은 .txt로
        base = os.path.splitext(os.path.basename(path))[0]
        masked_path = None
        return [(i, ln) for i, ln in enumerate(txt.splitlines(), 1)], "utf-8", None, True, masked_path, None

    # 텍스트 파일
    if is_binary(path):
        return [], "utf-8", "바이너리 파일(NUL 바이트 포함) — 텍스트 추출 불가", False, None, "바이너리 파일(NUL 바이트 포함) — 텍스트 추출 불가"

    size = os.path.getsize(path)
    if size > 5 * 1024 * 1024:
        return [], "utf-8", f"5MB 초과({size} 바이트) — 분할 검사 권장", False, None, f"5MB 초과({size} 바이트) — 분할 검사 권장"

    txt, enc, err = read_text_file(path)
    if err:
        return [], enc, err, False, None, err

    lines = [(i, l) for i, l in enumerate(txt.splitlines(), 1)]
    return lines, enc, None, False, None, None

def process_file(path, flags):
    """
    파일 처리 결과 dict:
    {
        "path": ...,
        "encoding": ...,
        "count": int,
        "findings": [...],
        "masked_path": str|None,
        "error": str|None,
    }
    """
    ext = os.path.splitext(path)[1].lower()
    doc_exts = {".docx", ".hwpx", ".pptx", ".xlsx"}

    lines, enc, err, is_doc, _, skip = read_file_lines(path)
    if err:
        return {
            "path": path,
            "encoding": enc,
            "count": 0,
            "findings": [],
            "masked_path": None,
            "error": err,
        }

    # CSV 헤더 추출
    csv_headers = None
    if ext in {".csv", ".tsv"}:
        if lines:
            first = lines[0][1]
            sep = "," if ext == ".csv" else "\t"
            csv_headers = [c.strip() for c in first.split(sep)]

    # 스캔
    findings = scan_lines(lines, csv_headers)

    if flags.get("no_names"):
        findings = [f for f in findings if f["type"] != "name"]

    # 신뢰도 필터
    min_conf = flags.get("min_confidence", "info")
    conf_rank = {"info": 0, "low": 1, "medium": 2, "high": 3}
    cut = conf_rank.get(min_conf, 0)
    if cut > 0:
        findings = [f for f in findings if conf_rank.get(f["confidence"], 0) >= cut]

    return {
        "path": path,
        "encoding": enc,
        "count": len(findings),
        "findings": findings,
        "masked_path": None,
        "error": None,
    }

def produce_masked_file(path, findings, masked_dir):
    """
    원본 파일을 읽어서 findings 위치 기준으로 마스킹한 사본을 masked_dir에 생성.
    문서는 .txt로 저장.
    반환: masked_path
    """
    ext = os.path.splitext(path)[1].lower()
    doc_exts = {".docx", ".hwpx", ".pptx", ".xlsx"}
    basename = os.path.basename(path)

    if ext in doc_exts:
        # 문서는 텍스트를 추출해서 .txt로 마스킹본 생성
        txt, _ = extract_doc_text(path)
        masked_text = apply_mask_to_text(txt, findings)
        masked_name = basename.rsplit(".", 1)[0] + ".masked.txt"
        out_path = os.path.join(masked_dir, masked_name)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(masked_text)
        return out_path

    # 일반 텍스트: 원본 그대로 읽어서 마스킹
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    masked_text = apply_mask_to_text(raw, findings)
    masked_name = basename.rsplit(".", 1)[0] + ".masked" + ext
    out_path = os.path.join(masked_dir, masked_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(masked_text)
    return out_path

def apply_mask_to_text(text, findings):
    """
    findings를 end 기준 내림차순 정렬해서 오른쪽부터 마스킹 적용.
    겹치는 마스킹 구간은 나중에 적용된 것이 우선(짧은 마스킹이 덮을 수 있음).
    """
    # 겹치지 않게 정렬된 findings를 기준으로 텍스트 치환
    # 가장 간단한 방법: 각 finding의 start:end 범위를 마스킹 문자열로 치환
    # 다중 치환 시 위치 어긋남을 막으려면 뒤에서부터 치환
    sorted_f = sorted(findings, key=lambda f: f["start"], reverse=True)
    result = text
    for f in sorted_f:
        s, e = f["start"], f["end"]
        result = result[:s] + f["masked"] + result[e:]
    return result

# ══════════════════════════════════════════════════════════════════════════════
# 9. 위험도 판정
# ══════════════════════════════════════════════════════════════════════════════

HIGH_RISK_TYPES = {
    "resident_number", "credit_card", "license",
    "openai_api_key", "aws_access_key", "github_token",
    "google_api_key", "slack_token", "jwt", "private_key",
    "connection_string",
}

def compute_risk(all_files):
    """모든 파일 findings를 종합해 위험도 반환."""
    has_high_unique = False
    has_high_other = False
    has_medium = False
    has_low = False
    has_info = False

    for f in all_files:
        for finding in f["findings"]:
            t = finding["type"]
            c = finding["confidence"]
            if t in HIGH_RISK_TYPES and c == "high":
                has_high_unique = True
            elif c == "high":
                has_high_other = True
            elif c == "medium":
                has_medium = True
            elif c == "low":
                has_low = True
            elif c == "info":
                has_info = True

    if has_high_unique:
        return "HIGH"
    if has_high_other or has_medium:
        return "MEDIUM"
    if has_low or has_info:
        return "LOW"
    return "NONE"

# ══════════════════════════════════════════════════════════════════════════════
# 10. 보고서 생성 (JSON + Markdown)
# ══════════════════════════════════════════════════════════════════════════════

LEGAL_NOTE = (
    "본 점검 결과는 개인정보 보호법 제24조(주민등록번호 처리의 제한), "
    "제24조의2(주민등록번호 대체수단 제공 의무), 제29조(안전조치 의무)의 "
    "취지를 참고한 자동 탐지 결과이며, 법률적 확정 진단이 아닙니다. "
    "노출이 확인된 경우 해당 정보의 취급 중단·마스킹·삭제 등 즉시 조치가 필요합니다."
)

LIMIT_NOTE = (
    "한계: ① 이름·주소 등 문맥 기반 탐지는 키워드 존재 여부에 의존하므로 "
    "문맥어가 없는 경우 누락될 수 있습니다. ② 이미지·스캔 PDF는 OCR을 지원하지 않아 "
    "텍스트 추출이 불가능합니다. ③ 합성·더미 데이터는 실제 개인정보로 오인될 수 있습니다. "
    "④ 이 스크립트는 값을 '읽어 보고 패턴·구문·체크섬으로 추정'하는 도구이며, "
    "어떤 값이 실제 개인정보인지는 최종 판단하지 않습니다."
)

def build_json_report(when, all_files, risk):
    return OrderedDict([
        ("when", when),
        ("risk", risk),
        ("total", sum(f["count"] for f in all_files)),
        ("legal_note", LEGAL_NOTE),
        ("limit_note", LIMIT_NOTE),
        ("files", all_files),
    ])

def build_md_report(when, all_files, risk, target, flags):
    lines = []

    lines.append("# 개인정보·비밀키 노출 점검 보고서")
    lines.append("")
    lines.append(f"- **점검 시각**: {when}")
    lines.append(f"- **대상**: {target}")
    lines.append(f"- **위험도**: {risk}")
    lines.append(f"- **탐지 건수**: {sum(f['count'] for f in all_files)}")
    lines.append(f"- **처리 파일 수**: {len(all_files)}")
    lines.append(
        "- **원칙**: 탐지된 원문 값은 보고하지 않으며, 마스킹된 값과 위치(줄·열)만 표시합니다."
    )
    lines.append("")

    # ─ 요약 줄 ──────────────────────────────────────────────────────────────
    lines.append("## 1. 요약")
    lines.append("")

    if risk == "HIGH":
        lines.append(
            "> ⚠️ **HIGH 위험**: 고유식별정보(주민등록번호·운전면허·신용카드) 또는 "
            "비밀키·접속문자열이 1건 이상 탐지되었습니다. **파일을 공유·업로드하기 전 "
            "마스킹이 필요합니다.**"
        )
    elif risk == "MEDIUM":
        lines.append(
            "> 주의: 전화·이메일 등 HIGH 신뢰도의 연락처 정보 또는 medium 신뢰도의 "
            "정보가 탐지되었습니다. 공유 전 마스킹 여부를 검토하십시오."
        )
    elif risk == "LOW":
        lines.append(
            "> 낮은 신뢰도의 정보만 탐지되었습니다. 문맥에 따라 재확인이 필요할 수 있습니다."
        )
    else:
        lines.append(
            "> 탐지된 항목이 없습니다. 단, 이름·주소 등 문맥 기반 항목은 누락될 수 있습니다."
        )
    lines.append("")

    # ─ 유형별 표 ────────────────────────────────────────────────────────────
    lines.append("## 2. 유형별 탐지 집계")
    lines.append("")

    # 집계: type → {files: [], count, max_confidence, example_masked}
    agg = OrderedDict()
    for f in all_files:
        for finding in f["findings"]:
            t = finding["type"]
            if t not in agg:
                agg[t] = {
                    "files": set(),
                    "count": 0,
                    "max_confidence": finding["confidence"],
                    "example_masked": finding["masked"],
                }
            agg[t]["files"].add(os.path.basename(f["path"]))
            agg[t]["count"] += 1
            if {"info": 0, "low": 1, "medium": 2, "high": 3}.get(
                finding["confidence"], 0
            ) > {"info": 0, "low": 1, "medium": 2, "high": 3}.get(
                agg[t]["max_confidence"], 0
            ):
                agg[t]["max_confidence"] = finding["confidence"]
                agg[t]["example_masked"] = finding["masked"]

    lines.append("| 유형 | 파일 수 | 건수 | 최고 신뢰도 | 마스킹 예시 |")
    lines.append("|------|--------|------|------------|------------|")
    for t, a in agg.items():
        lines.append(
            f"| {t} | {len(a['files'])} | {a['count']} | {a['max_confidence']} | `{a['example_masked']}` |"
        )
    lines.append("")

    # ─ 위치별 상세 (상위 40건) ──────────────────────────────────────────────
    lines.append("## 3. 위치별 상세 (상위 40건)")
    lines.append("")
    lines.append("탐지된 항목 중 신뢰도 높은 순서로 최대 40건을 표시합니다. "
                  "전체 목록은 JSON 보고서를 참조하십시오.")
    lines.append("")

    # 신뢰도 순 정렬 + 상위 40
    conf_rank = {"high": 3, "medium": 2, "low": 1, "info": 0}
    sorted_findings = []
    for f in all_files:
        for fnd in f["findings"]:
            sorted_findings.append((f["path"], fnd))
    sorted_findings.sort(
        key=lambda x: (-conf_rank.get(x[1]["confidence"], 0), x[0], x[1]["line"])
    )
    top40 = sorted_findings[:40]

    if not top40:
        lines.append("탐지 항목이 없습니다.")
        lines.append("")
    else:
        lines.append("| # | 파일 | 줄 | 유형 | 신뢰도 | 검증 | 마스킹된 문맥 |")
        lines.append("|---|------|----|------|--------|------|---------------|")
        for i, (fpath, fnd) in enumerate(top40, 1):
            ctx = fnd["context"]
            if len(ctx) > 60:
                ctx = ctx[:60] + "…"
            lines.append(
                f"| {i} | {os.path.basename(fpath)} | {fnd['line']} | {fnd['type']} | "
                f"{fnd['confidence']} | {'예' if fnd['validated'] else '아니오'} | `{fnd['masked']}…` |"
            )
        lines.append("")

    # ─ 권고 조치 ────────────────────────────────────────────────────────────
    lines.append("## 4. 권고 조치")
    lines.append("")
    if risk == "HIGH":
        lines.append("1. **즉시 조치**: 주민번호·운전면허·카드번호·비밀키·접속문자열이 포함된 파일을 공유·전송·업로드를 중단하십시오.")
        lines.append("2. **마스킹본 사용**: 생성된 `work/masked/` 디렉터리의 마스킹본(`.masked.*`)을 대신 사용하십시오.")
        lines.append("3. **원본 처리**: 원본 파일에서 해당 값을 삭제하거나 마스킹한 후 보관하십시오.")
        lines.append("4. **접근 제한**: 이미 공유되었다면 접근 권한을 회수하고 관련자에게 마스킹본으로 대체를 요청하십시오.")
    elif risk == "MEDIUM":
        lines.append("1. 전화·이메일 등 연락처 정보의 공유 필요성을 검토하십시오.")
        lines.append("2. 필요한 경우 마스킹본(`.masked.*`)을 사용하십시오.")
    elif risk == "LOW":
        lines.append("1. 낮은 신뢰도의 항목은 문맥에 따라 재확인하십시오.")
        lines.append("2. 이름·주소 등은 실제 개인정보일 수 있으므로 주의하십시오.")
    else:
        lines.append("1. 탐지된 항목이 없습니다. 다만 이름·주소 등은 문맥 기반 탐지로 누락될 수 있으므로 중요 문서인 경우 수동 확인을 권장합니다.")
    lines.append("")

    # ─ 법적 근거 ────────────────────────────────────────────────────────────
    lines.append("## 5. 법적 근거 (참고)")
    lines.append("")
    lines.append("- **개인정보 보호법 제24조(주민등록번호 처리의 제한)**: 주민등록번호를 처리하는 경우 법령상 근거 또는 정보주체의 동의가 필요하며, 처리 시 안전조치를 해야 합니다.")
    lines.append("- **개인정보 보호법 제24조의2(주민등록번호 대체수단 제공 의무)**: 주민등록번호 수집을 최소화하는 대체수단을 제공해야 합니다.")
    lines.append("- **개인정보 보호법 제29조(안전조치 의무)**: 개인정보를 처리할 때는 기술적·관리적·물리적 안전조치를 해야 합니다.")
    lines.append("")
    lines.append(LEGAL_NOTE)
    lines.append("")
    lines.append(LIMIT_NOTE)
    lines.append("")

    return "\n".join(lines)

# ══════════════════════════════════════════════════════════════════════════════
# 11. CLI 진입점
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="개인정보·비밀키 노출 점검 (pii-guard)"
    )
    parser.add_argument(
        "files", nargs="*",
        help="검사할 파일 경로들"
    )
    parser.add_argument(
        "--text", default=None,
        help="붙여넣은 텍스트(파일 대신)"
    )
    parser.add_argument(
        "--json", default="work/pii.json",
        help="JSON 보고서 출력 경로 (기본: work/pii.json)"
    )
    parser.add_argument(
        "--md", default="work/report.md",
        help="Markdown 보고서 출력 경로 (기본: work/report.md)"
    )
    parser.add_argument(
        "--masked-dir", default="work/masked",
        help="마스킹본 저장 디렉터리 (기본: work/masked)"
    )
    parser.add_argument(
        "--no-names", action="store_true",
        help="이름 탐지 제외"
    )
    parser.add_argument(
        "--min-confidence", default="info",
        choices=["info", "low", "medium", "high"],
        help="보고할 최소 신뢰도 (기본: info)"
    )
    args = parser.parse_args()

    flags = {
        "no_names": args.no_names,
        "min_confidence": args.min_confidence,
    }

    os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
    os.makedirs(args.masked_dir, exist_ok=True)

    now = date.today().strftime("%Y-%m-%d %H:%M:%S")

    all_files = []
    target_desc = []

    # 텍스트 모드
    if args.text:
        lines = [(i, l) for i, l in enumerate(args.text.splitlines(), 1)]
        csv_headers = None
        ext = ".txt"
        findings = scan_lines(lines, csv_headers)
        if flags["no_names"]:
            findings = [f for f in findings if f["type"] != "name"]
        conf_rank = {"info": 0, "low": 1, "medium": 2, "high": 3}
        cut = conf_rank.get(args.min_confidence, 0)
        if cut > 0:
            findings = [f for f in findings if conf_rank.get(f["confidence"], 0) >= cut]

        entry = OrderedDict([
            ("path", "<붙여넣기 텍스트>"),
            ("encoding", "utf-8"),
            ("count", len(findings)),
            ("findings", findings),
            ("masked_path", None),
            ("error", None),
        ])
        all_files.append(entry)
        target_desc.append("붙여넣기 텍스트")
    else:
        # 파일 모드
        for fp in args.files:
            if not os.path.exists(fp):
                all_files.append(OrderedDict([
                    ("path", fp),
                    ("encoding", "unknown"),
                    ("count", 0),
                    ("findings", []),
                    ("masked_path", None),
                    ("error", f"파일을 찾을 수 없음: {fp}"),
                ]))
                target_desc.append(os.path.basename(fp) + "(없음)")
                continue

            size = os.path.getsize(fp)
            if size > 5 * 1024 * 1024:
                all_files.append(OrderedDict([
                    ("path", fp),
                    ("encoding", "unknown"),
                    ("count", 0),
                    ("findings", []),
                    ("masked_path", None),
                    ("error", f"5MB 초과({size} 바이트) — 분할 검사 권장"),
                ]))
                target_desc.append(os.path.basename(fp) + "(5MB 초과)")
                continue

            ext = os.path.splitext(fp)[1].lower()

            # 문서가 아니면 텍스트로 읽기
            if ext in {".docx", ".hwpx", ".pptx", ".xlsx"}:
                txt, err = extract_doc_text(fp)
                if txt is None:
                    all_files.append(OrderedDict([
                        ("path", fp),
                        ("encoding", "utf-8"),
                        ("count", 0),
                        ("findings", []),
                        ("masked_path", None),
                        ("error", err),
                    ]))
                    target_desc.append(os.path.basename(fp))
                    continue
                lines = [(i, l) for i, l in enumerate(txt.splitlines(), 1)]
                # 마스킹본 경로 미리 계산
                masked_path = os.path.join(
                    args.masked_dir,
                    os.path.basename(fp).rsplit(".", 1)[0] + ".masked.txt",
                )
            elif is_binary(fp):
                all_files.append(OrderedDict([
                    ("path", fp),
                    ("encoding", "utf-8"),
                    ("count", 0),
                    ("findings", []),
                    ("masked_path", None),
                    ("error", "바이너리 파일(NUL 바이트 포함) — 텍스트 추출 불가"),
                ]))
                target_desc.append(os.path.basename(fp))
                continue
            else:
                txt, enc, err = read_text_file(fp)
                if err:
                    all_files.append(OrderedDict([
                        ("path", fp),
                        ("encoding", enc),
                        ("count", 0),
                        ("findings", []),
                        ("masked_path", None),
                        ("error", err),
                    ]))
                    target_desc.append(os.path.basename(fp))
                    continue
                lines = [(i, l) for i, l in enumerate(txt.splitlines(), 1)]
                # 마스킹본 경로
                masked_path = os.path.join(
                    args.masked_dir,
                    os.path.basename(fp).rsplit(".", 1)[0] + ".masked" + ext,
                )

            # CSV 헤더
            csv_headers = None
            if ext in {".csv", ".tsv"} and lines:
                first = lines[0][1]
                sep = "," if ext == ".csv" else "\t"
                csv_headers = [c.strip() for c in first.split(sep)]

            findings = scan_lines(lines, csv_headers)

            if flags["no_names"]:
                findings = [f for f in findings if f["type"] != "name"]

            conf_rank = {"info": 0, "low": 1, "medium": 2, "high": 3}
            cut = conf_rank.get(args.min_confidence, 0)
            if cut > 0:
                findings = [f for f in findings if conf_rank.get(f["confidence"], 0) >= cut]

            # 마스킹본 생성
            if findings:
                # 텍스트 다시 읽어서 마스킹 적용
                if ext in {".docx", ".hwpx", ".pptx", ".xlsx"}:
                    # 문서는 다시 추출
                    txt_doc, _ = extract_doc_text(fp)
                    masked_text = apply_mask_to_text(txt_doc, findings)
                    with open(masked_path, "w", encoding="utf-8") as mf:
                        mf.write(masked_text)
                else:
                    with open(fp, "r", encoding="utf-8", errors="replace") as rf:
                        raw = rf.read()
                    masked_text = apply_mask_to_text(raw, findings)
                    with open(masked_path, "w", encoding="utf-8") as mf:
                        mf.write(masked_text)

            entry = OrderedDict([
                ("path", fp),
                ("encoding", enc if ext not in {".docx", ".hwpx", ".pptx", ".xlsx"} else "utf-8"),
                ("count", len(findings)),
                ("findings", findings),
                ("masked_path", masked_path if findings else None),
                ("error", None),
            ])
            all_files.append(entry)
            target_desc.append(os.path.basename(fp))

    risk = compute_risk(all_files)

    # JSON
    json_obj = build_json_report(now, all_files, risk)
    with open(args.json, "w", encoding="utf-8") as jf:
        json.dump(json_obj, jf, ensure_ascii=False, indent=2)

    # Markdown
    md = build_md_report(now, all_files, risk, ", ".join(target_desc), flags)
    with open(args.md, "w", encoding="utf-8") as mf:
        mf.write(md)

    # 화면 요약 (위험도·유형별 표·조치)
    print("# 개인정보·비밀키 노출 점검 결과")
    print("")
    print(f"위험도: {risk}")
    print(f"탐지 건수: {sum(f['count'] for f in all_files)}")
    print(f"처리 파일 수: {len(all_files)}")
    print("")

    # 유형별 표
    agg = OrderedDict()
    for f in all_files:
        for finding in f["findings"]:
            t = finding["type"]
            if t not in agg:
                agg[t] = {"count": 0, "max": finding["confidence"], "example": finding["masked"]}
            agg[t]["count"] += 1
            r = {"info": 0, "low": 1, "medium": 2, "high": 3}
            if r.get(finding["confidence"], 0) > r.get(agg[t]["max"], 0):
                agg[t]["max"] = finding["confidence"]
                agg[t]["example"] = finding["masked"]

    if agg:
        print("유형별 집계:")
        print(f"  {'유형':<20} {'건수':>5}  {'최고신뢰도':<10}  {'마스킹 예시'}")
        for t, a in agg.items():
            print(f"  {t:<20} {a['count']:>5}  {a['max']:<10}  {a['example']}")
        print("")
    else:
        print("탐지 항목 없음.")
        print("")

    # 권고 조치
    if risk == "HIGH":
        print("[주의] HIGH 위험: 고유식별정보 또는 비밀키/접속문자열이 탐지되었습니다.")
        print("  → 마스킹본(work/masked/)을 사용하고, 원본 공유를 중단하십시오.")
    elif risk == "MEDIUM":
        print("[주의] MEDIUM 위험: 연락처 정보 등이 탐지되었습니다.")
        print("  → 필요 시 마스킹본을 사용하십시오.")
    elif risk == "LOW":
        print("[참고] LOW 위험: 낮은 신뢰도의 정보만 탐지되었습니다.")
    else:
        print("[참고] 탐지 없음. 단, 문맥 기반 항목은 누락될 수 있습니다.")
    print("")

    # 종료 코드
    if any(f.get("error") for f in all_files):
        sys.exit(2)
    if sum(f["count"] for f in all_files) > 0:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
