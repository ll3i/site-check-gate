#!/usr/bin/env python3
"""
scan_rules.py — 공고 텍스트에서 실격·유의 문장, 규격 수치, 배점 라인, 문의처 추출.

- risk_lines: 실격/제외/불가/무효/취소/환수/박탈/금지/불이익/반려/미준수/위반/표절/도용/중복/허위/부정/유의/주의/엄수 키워드 포함 라인
- spec_lines: 쪽수/용량/자 수/분/부수/인원/파일형식/파일명 규칙 등 규격 수치
- score_lines: n점/n% 배점 + 배점 키워드 뒤 20줄 안 표 숫자 셀
- score_sum_check: 표 셀 점수 합계
- contacts: 이메일/전화번호/URL

오탐 방지: 목록 번호 "1. 2. 3.", 버전 "v1.2" 등은 점수 배점으로 보지 않음.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import json
import os
import re
import sys


# ---------- detector helpers ----------
def _spec_numbers_in_line(line, context_window):
    """쪽에서 '10쪽', '500자', '20MB', '3분', '1부', '3인' 등 규격 후보."""
    specs = []
    # 용량 MB/KB/GB
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(MB|KB|GB|mb|kb|gb)", line):
        specs.append({"type": "용량", "value": f"{m.group(1)} {m.group(2)}"})
    # 쪽/장
    for m in re.finditer(r"(\d+)\s*(쪽|장|페이지|매)", line):
        specs.append({"type": "분량(쪽/장)", "value": m.group(1)})
    # 자
    for m in re.finditer(r"(\d+)\s*자", line):
        specs.append({"type": "분량(자)", "value": m.group(1)})
    # 분/초
    for m in re.finditer(r"(\d+)\s*(분|분 이내|초|초 이내)", line):
        specs.append({"type": "분량(시간)", "value": m.group(1) + "분"})
    # 부
    for m in re.finditer(r"(\d+)\s*부", line):
        specs.append({"type": "부수", "value": m.group(1)})
    # 인/명 (팀 인원)
    for m in re.finditer(r"(\d+)\s*(인|명)\s*(이내|이하|까지)?", line):
        specs.append({"type": "인원", "value": m.group(1) if m.group(1) else ""})
    # 파일형식
    ftypes = ["HWP", "PDF", "DOCX", "PPTX", "MP4", "ZIP", "PNG", "JPG", "MP3"]
    for ft in ftypes:
        if re.search(rf"\b{ft}\b", line, re.IGNORECASE):
            specs.append({"type": "파일형식", "value": ft})
    # 파일명 규칙
    m = re.search(r"파일명\s*(규칙|형식|안내|지정|예시)[:：\s]*(.+)", line)
    if m:
        specs.append({"type": "파일명 규칙", "value": m.group(2).strip()[:120]})
    # "이내"/"이하"/"미만" 문구
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(쪽|자|분|MB|KB|GB|부|인|장)\s*(이내|이하|미만)", line):
        specs.append({"type": "규격(제한)", "value": m.group(0)})
    return specs


def _is_score_line(line):
    """배점 라인 판단: n점 / n% 포함 + 문맥이 심사 기준 관련."""
    low = line.lower()
    # "n점" or "n%"
    if not re.search(r"(\d+(?:\.\d+)?)\s*(점|%)", line):
        return False, []
    # 목록 번호/버전/점수 퍼센트 오탐 방지
    # "v1.2" "10.5%" 등: 퍼센트면 배점 가능성 있음
    nums = re.findall(r"(\d+(?:\.\d+)?)\s*(점|%)", line)
    points = [float(n) for n, _ in nums]
    # 목록 번호 걸러내기: "1. 2. 3."처럼 단독 숫자에 점만 있고 뒤가 '점/%'가 아니면
    # 여기서 이미 점/퍼센트만 뽑으므로 목록 번호는 안 걸림.
    return True, points


def _score_cells_in_context(lines, start_idx, window=20):
    """배점 키워드 라인 뒤 윈도우 안의 표 데이터 행 셀만 수집.

    - '|' 로 시작하는 표 행만 대상. 헤더/구분선은 제외.
    - 셀에서 숫자(정수/소수)를 추출하되 'n점'의 '점'은 단위, 'n%'는 weights 로 분리.
    - 표 바깥(plain-text)의 숫자는 주워 담지 않음.
    """
    cells = []
    weights = []
    end = min(len(lines), start_idx + window)
    for i in range(start_idx, end):
        line = lines[i]
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        # 헤더/구분선 감지 → 건너뛰기
        # 구분선row (예: |---|---|) 만 건너뛴다. 헤더행/데이터행은 셀 단위 스캔.
        is_sep = False
        for p in parts:
            if re.match(r"^[-:]+$", p.strip()):
                is_sep = True
                break
        if is_sep:
            continue
        # 데이터 행: 각 셀에서 숫자 + 단위 추출
        for p in parts:
            p2 = p.strip()
            m = re.match(r"^(\d+(?:\.\d+)?)\s*(점|%)?\s*$", p2)
            if m:
                v = float(m.group(1))
                unit = m.group(2)
                if unit == "%":
                    weights.append(v)
                else:
                    cells.append(v)
    return cells, weights


def _extract_contacts(text):
    emails = re.findall(r"[\w.\-+]+@[\w.\-]+\.\w+", text)
    phones = re.findall(r"(0\d{1,2}-\d{3,4}-\d{4})", text)
    # URL
    urls = re.findall(r"https?://[^\s,;)]+", text)
    # 중복 제거
    return {
        "emails": sorted(set(emails)),
        "phones": sorted(set(phones)),
        "urls": sorted(set(urls)),
    }


RISK_KEYWORDS = [
    "실격", "제외", "불가", "무효", "취소", "환수", "박탈", "금지",
    "불이익", "반려", "미준수", "위반", "표절", "도용", "중복",
    "허위", "부정", "유의", "주의", "엄수",
]


def _is_risk_line(line):
    for kw in RISK_KEYWORDS:
        if kw in line:
            return True, [kw]
    return False, []


def _classify_risk(line, keywords):
    low = line.lower()
    cats = []
    if any(k in line for k in ["실격", "제외", "불가", "무효", "취소", "반려", "미준수", "위반", "부정", "허위"]):
        cats.append("실격/심사 제외")
    if "감점" in line:
        cats.append("감점")
    if any(k in line for k in ["환수", "박탈"]):
        cats.append("무효/환수/박탈")
    if any(k in line for k in ["금지", "도용", "표절", "중복"]):
        cats.append("금지/제한")
    if any(k in line for k in ["유의", "주의", "엄수"]):
        cats.append("유의/주의/엄수")
    if not cats:
        cats.append("기타/문의")
    # 중복 제거 유지
    return cats


def main():
    ap = argparse.ArgumentParser(
        description="공고 텍스트에서 실격·규격·배점·문의처 스캔"
    )
    ap.add_argument("txt", help="입력 텍스트 (파일 경로 또는 직접 텍스트)")
    ap.add_argument("--json", action="store_true", help="JSON 출력(기본: 표 형태)")
    args = ap.parse_args()

    if os.path.isfile(args.txt):
        with open(args.txt, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        text = args.txt

    lines = text.split("\n")

    risk_lines = []
    spec_lines = []
    score_lines = []
    contacts = _extract_contacts(text)

    for i, line in enumerate(lines, start=1):
        s = line.strip()
        if not s:
            continue

        # risk
        is_risk, kws = _is_risk_line(s)
        if is_risk:
            cats = _classify_risk(s, kws)
            risk_lines.append({"line_no": i, "text": s, "keywords": kws, "categories": cats})

        # spec
        specs = _spec_numbers_in_line(s, lines[max(0, i-10):i+10])
        if specs:
            spec_lines.append({"line_no": i, "text": s, "specs": specs})

        # score
        is_score, points = _is_score_line(s)
        if is_score:
            cells, weights = _score_cells_in_context(lines, i - 1, window=20)
            score_lines.append({"line_no": i, "text": s, "points": points, "cells_in_window": cells, "weights_in_window": weights})

    # score_sum_check: 표 형태 점수 셀 합계
    # 표 데이터 행(|로 시작)은 각 행의 배점(points)만 합산해 중복을 피한다.
    # 일반 배점 소개 라인은 cells_in_window(표 셀) 합산을 시도하나,
    # 윈도우 범위 문제로 비어 있을 수 있어 기여가 없을 수 있다.
    sum_of_table_points = 0
    looks_like_100 = False
    for sl in score_lines:
        text = sl.get("text", "")
        if text.lstrip().startswith("|"):
            for v in sl.get("points", []):
                sum_of_table_points += v
        else:
            for v in sl.get("cells_in_window", []):
                sum_of_table_points += v
    if 95 <= sum_of_table_points <= 105:
        looks_like_100 = True

    out = {
        "risk_lines": risk_lines,
        "spec_lines": spec_lines,
        "score_lines": score_lines,
        "score_sum_check": {
            "sum_of_table_points": round(sum_of_table_points, 2),
            "looks_like_100": looks_like_100,
        },
        "contacts": contacts,
    }

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(0)

    print("=== 실격·유의 라인 ===")
    for r in risk_lines:
        print(f"[L{r['line_no']}] {r['text']}  (키워드: {','.join(r['keywords'])})")
    if not risk_lines:
        print(" (없음)")

    print("\n=== 규격 수치 라인 ===")
    for r in spec_lines:
        print(f"[L{r['line_no']}] {r['text']}  → {r['specs']}")
    if not spec_lines:
        print(" (없음)")

    print("\n=== 배점 라인 ===")
    for r in score_lines:
        print(f"[L{r['line_no']}] {r['text']}  → 점: {r['points']}, 표 셀 윈도우: {r['cells_in_window']}")
    if not score_lines:
        print(" (없음)")

    print("\n=== 배점 합계 검증 ===")
    print(f"표 셀 점수 합계: {round(sum_of_table_points, 2)} → {'합계 100으로 보임 ✓' if looks_like_100 else '합계 100 아님 — 공고 확인 필요'}")

    print("\n=== 문의처 ===")
    print(f"이메일: {contacts['emails']}")
    print(f"전화: {contacts['phones']}")
    print(f"URL: {contacts['urls']}")

    sys.exit(0)


if __name__ == "__main__":
    main()
