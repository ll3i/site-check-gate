#!/usr/bin/env python3
"""
extract_dates.py — 한국어 공고 날짜·시각 정규화.

지원 형식 예시:
  2026년 8월 31일(월) 오후 6시
  2026. 8. 31.(월) 18:00
  26. 8. 3.
  2026-08-31 23:59
  9/7(월)
  8월 31일 자정
  8. 31.(월)
  2026.09.04(금) 17시
  8월31일

연도 없음 → 올해 추정(단, 8개월 이상 과거면 내년). weekday_mismatch 감지.
시간만 있는 표기는 날짜 후보에 넣지 않되, 문맥상 마감일의 시간일 경우 연결.
오탐 방지: 3.5점, 10.5MB, v1.2, 1. 2. 3.(목록 번호)는 날짜로 보지 않음.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

# 요일 한글 매핑
_KR_WEEKDAY = {
    "월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6,
}

# 요일 영어 약칭 → 숫자
_EN_WEEKDAY = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def _weekday_from_text(text):
    m = re.search(r"\((\s*[월화수목금토일]\s*)\)", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"[(\s]([월화수목금토일])[)\s]", text)
    if m:
        return m.group(1)
    # 영어 약칭 (Mon 등)
    m = re.search(r"\b([A-Za-z]{1,3})\b", text.lower())
    if m:
        w = _EN_WEEKDAY.get(m.group(1).lower())
        if w is not None:
            return "월화수목금토일"[w]
    # JJ: 숫자로 된 요일(1=월…7=일)? 공고에서 드물어 제외
    return None


def _infer_year(line_no_year, today_year, today_month_day):
    """연도 생략된 날짜의 연도 추정. 8개월 이상 과거면 내년."""
    # month/day 파싱 시도
    md = re.search(r"(?<!\d)(\d{1,2})[./\- ](?:월|\.|\-)\s*(\d{1,2})(?:[.)\s]|$)", line_no_year)
    # simpler: 이미 두 숫자만 있는 경우
    nums = re.findall(r"\d{1,2}", line_no_year)
    # 날짜 패턴에서 month/day
    m2 = re.search(r"(?:^|[^\d])(\d{1,2})[./ ](?:월|-|\.)?\s*(\d{1,2})(?:[.)\s]|$)", line_no_year)
    # OR "8. 31." style
    m3 = re.search(r"(\d{1,2})[.\s](\d{1,2})[.\s]", line_no_year)
    month = day = None
    for m in (m2, m3):
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            break
    if month is None:
        # maybe "8월 31일"
        m4 = re.search(r"(\d{1,2})월\s*(\d{1,2})일", line_no_year)
        if m4:
            month, day = int(m4.group(1)), int(m4.group(2))
    if month is None:
        return None

    if month < 1 or month > 12 or day < 1 or day > 31:
        return None

    # 오늘 날짜와 비교
    today_md = (today_month_day[0], today_month_day[1])
    date_this_year = datetime.date(today_year, month, day)
    days_diff = (date_this_year - datetime.date(today_year, *today_md)).days
    # 8개월 = 약 240일 이상을 과거로 보면 내년
    if days_diff < -240:  # 8개월 이상 과거
        return today_year + 1
    return today_year


def _parse_datetime_from_text(raw, flat, iso_date):
    """시간 정보 추출: 오후/오전 X시, HH:MM, HH시, 자정, 24:00 등.

    날짜 조각(raw)에 시간이 붙어 있을 수도 있고, 동일 줄 평탄화(flat)에서만
    보일 수도 있으므로 둘 다 순서로 확인한다.
    """
    t = raw
    hour = minute = 0
    time_str = None

    # 24시간 HH:MM
    m = re.search(r"(\d{1,2}):(\d{2})\s*(?:시)?", t)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour == 24:
            hour = 0
        time_str = f"{iso_date}T{hour:02d}:{minute:02d}"
    else:
        # HH시
        m = re.search(r"(\d{1,2})\s*시\b", t)
        if m:
            hour = int(m.group(1))
            if hour == 24:
                hour = 0
            time_str = f"{iso_date}T{hour:02d}:00"

    # 오전/오후
    lower = t
    pm = re.search(r"오후\s*(\d{1,2})\s*시", lower)
    am = re.search(r"오전\s*(\d{1,2})\s*시", lower)
    if pm:
        h = int(pm.group(1))
        hour = (h % 12) + 12
        if hour == 24:
            hour = 0
        time_str = f"{iso_date}T{hour:02d}:00"
    elif am:
        h = int(am.group(1))
        hour = h % 12
        time_str = f"{iso_date}T{hour:02d}:00"

    # 자정 = 24:00 (당일 마감 시각 관행상 iso_datetime 은 23:59 로 표기)
    if re.search(r"자정\b", t) or re.search(r"자정\b", flat):
        time_str = f"{iso_date}T24:00"
        hour, minute = 24, 0

    return hour, minute, time_str


def _classify_kind(raw, kinds_from_context, weekday_in_text):
    """문맥 키워드 기반 유형 분류. 우선순위: 제출마감 > 결선·시상 > 발표 > 설명/교육 > 시작 > 행사 > 미분류."""
    r = raw
    low = r.lower()

    # 제출마감 신호
    if re.search(r"\b(마감|접수 마감|제출 마감|접수 마감일|제출 마감일|접수종료|제출기한|제출 기한|마감일|마감 기한|마감 시|마감시간|오후 6시|18:00|23:59|자정)\b", r):
        return "제출마감"

    # 결선·시상
    if re.search(r"\b(결선|시상|시상식|대상|시상 식|시상일|시상 일자)\b", r):
        return "결선·시상"

    # 발표
    if re.search(r"\b(발표|결과 발표|합격 발표|예비심사 결과|서류 심사 결과|발표일)\b", r):
        return "발표"

    # 설명회/교육
    if re.search(r"\b(설명|교육|워크숍|세미나|오리엔테이션|O[ T]?T|사전 설명|설명회|참가 안내|오픈 설명)\b", r):
        return "설명회·교육"

    # 시작
    if re.search(r"\b(시작|접수 시작|접수 시작일|시작일|공모 시작|모집 시작|접수 개시|접수개시)\b", r):
        return "시작"

    # 행사
    if re.search(r"\b(행사|개막|페스티벌|컵|데이|포럼|콘퍼런스|컨퍼런스|전시회|박람회|해커톤|아이디어톤|대회|올림피아드|캠프)\b", r):
        return "행사"

    return "미분류"


def _extract_dates(text, today=None):
    if today is None:
        today = datetime.date.today()
    today_year = today.year
    today_md = (today.month, today.day)

    results = []

    lines = text.split("\n")
    for line_no, line in enumerate(lines, start=1):
        # 날짜 후보를 찾기 위한 정규식
        # 1) 2026년 8월 31일(월) 오후 6시, 2026. 8. 31.(월) 18:00, 2026-08-31 23:59, 2026.09.04(금) 17시
        pat1 = re.compile(
            r"(?<!\d)(?:(\d{4})[년.\-\s]*)?"
            r"(\d{1,2})[.\-\s]*월\s*"
            r"(\d{1,2})일"
            r"(?:\(([월화수목금토일])\))?", re.IGNORECASE
        )
        # 2) 26. 8. 3. / 8. 31. / 9/7(월) / 8. 31.(월)
        pat2 = re.compile(
            r"(?<!\d)(?:(\d{2,4})[.\-\s]*)?"
            r"(\d{1,2})[.\-\/ ]\s*"
            r"(\d{1,2})(?:일)?"
            r"(?:\(([월화수목금토일])\))?"
        )
        # 3) ISO-ish: 2026-08-31 23:59
        pat_iso = re.compile(
            r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{1,2}:\d{2}))?"
        )

        # combined scanner: walk through line with all patterns
        found = []

        def _add(pat, group_year_idx, group_month_idx, group_day_idx, group_weekday_idx):
            for m in pat.finditer(line):
                raw = m.group(0)
                # skip false positives: 점수와 용량, 버전, 목록 번호
                # "3.5점", "10.5MB", "v1.2" 등은 걸러지도록 문맥 체크
                after = line[m.end():m.end()+16].strip()
                before = line[max(0, m.start()-16):m.start()].strip()
                flat = (before + " " + raw + " " + after).replace("\n", " ")
                # 3.5점 / 10.5MB / v1.2 / 1. 2. 3.
                if re.search(r"\d+(\.\d+)?[점MBKBGB]|\bv?\d+(\.\d+)?\b", flat) and not re.search(r"(월|일|년|시|분|초|오전|오후|자정)", flat):
                    # 점수/버전 유사 → 날짜 아님
                    # 단, "3.5점"처럼 점이 소수면 숫자 개수가 1개뿐 → 추가 확인
                    nums_only = re.findall(r"\d+(?:\.\d+)?", raw)
                    if len(nums_only) <= 2 and re.search(r"[점MBKBGBbw%]", flat):
                        # 점수/용량/퍼센트 닮은 것은 날짜 후보에서 제외
                        continue
                    if re.match(r"^\d+(\.\d+)?$", raw) and re.search(r"\b(v|V)\d", before + flat):
                        continue
                    # 목록 번호 "1. 2. 3." → raw가 단일 숫자+점이고 앞뒤에 다른 숫자들
                    if re.match(r"^\d{1,2}\.\s*$", raw) and re.search(r"\d{1,2}\.\s+\d{1,2}\.\s+\d{1,2}", line):
                        continue

                year_s = m.group(group_year_idx) if group_year_idx is not None else None
                if year_s is not None and len(year_s) == 2:
                    year_s = str(2000 + int(year_s))
                month = int(m.group(group_month_idx))
                day = int(m.group(group_day_idx))
                wtext = m.group(group_weekday_idx) if group_weekday_idx is not None else None

                if month < 1 or month > 12 or day < 1 or day > 31:
                    continue

                year = int(year_s) if year_s else None
                if year is None:
                    year = _infer_year(line, today_year, today_md)
                if year is None:
                    continue

                try:
                    iso_date = datetime.date(year, month, day).isoformat()
                except ValueError:
                    continue

                hour, minute, time_str = _parse_datetime_from_text(raw, flat, iso_date)

                wd_actual = _KR_WEEKDAY.get(
                    datetime.date(year, month, day).strftime("%A")[:1].translate(
                        str.maketrans("ABCDEFG", "월화수목금토일")
                    )
                ) if False else None
                # 실제 요일
                wd_num = datetime.date(year, month, day).weekday()
                wd_actual_name = "월화수목금토일"[wd_num]
                wd_in_text = wtext
                wd_mismatch = False
                if wd_in_text:
                    if wd_in_text not in _KR_WEEKDAY:
                        wd_mismatch = True
                    elif _KR_WEEKDAY[wd_in_text] != wd_num:
                        wd_mismatch = True

                kinds = _classify_kind(raw, [], wd_in_text)
                # range_role 판단: line에 '~' 또는 '부터/까지'가 있으면
                range_role = None
                if " ~ " in raw or "∼" in raw:
                    range_role = "범위표기"
                elif re.search(r"(부터|~|~까지|까지)\s*$", line[m.start():]):
                    pass

                results.append({
                    "raw": raw,
                    "iso_date": iso_date,
                    "time": time_str,
                    "iso_datetime": time_str,
                    "year_inferred": (year_s is None),
                    "weekday": wd_actual_name,
                    "weekday_in_text": wd_in_text,
                    "weekday_mismatch": wd_mismatch,
                    "kind": kinds,
                    "kinds": [kinds],
                    "range_role": range_role,
                    "context": line.strip(),
                    "line_no": line_no,
                })

        _add(pat1, 1, 2, 3, 4)
        _add(pat2, 1, 2, 3, 4)
        _add(pat_iso, None, 2, 3, None)

    if not results:
        return []

    # 중복 제거: 동일 line + 동일 iso_date + 동일 time → 첫 번째 유지
    seen = set()
    uniq = []
    for r in results:
        key = (r["line_no"], r["iso_date"], r["time"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def _weekday_num_from_name(name):
    return _KR_WEEKDAY.get(name)


def main():
    ap = argparse.ArgumentParser(
        description="공고 텍스트에서 날짜·시각 정규화 (한국어 패턴)"
    )
    ap.add_argument("txt", help="입력 텍스트 (파일 경로 또는 직접 텍스트)")
    ap.add_argument("--today", "-t", help="기준일 YYYY-MM-DD (생략 시 오늘)")
    ap.add_argument("--json", action="store_true", help="JSON 출력(기본: 표 형태)")
    args = ap.parse_args()

    today = None
    if args.today:
        try:
            y, m, d = [int(x) for x in args.today.split("-")]
            today = datetime.date(y, m, d)
        except Exception:
            print(json.dumps({"error": f"잘못된 --today 값: {args.today}", "exit_code": 2}))
            sys.exit(2)

    # txt가 존재하는 파일이면 읽기, 아니면 직접 텍스트
    if os.path.isfile(args.txt):
        with open(args.txt, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        text = args.txt

    dates = _extract_dates(text, today)

    if not dates:
        print(json.dumps({"error": "날짜를 0건 찾았습니다.", "exit_code": 3}))
        sys.exit(3)

    if args.json:
        out = {
            "count": len(dates),
            "dates": dates,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(0)

    # 사람이 읽는 표
    print(f"[{len(dates)}건]  기준일: {today.isoformat()}")
    print("-" * 90)
    for d in dates:
        yinf = " (연도 추정)" if d["year_inferred"] else ""
        wmm = ""
        if d["weekday_mismatch"]:
            wmm = f"⚠ 공고 '{d['weekday_in_text']}' vs 실제 '{d['weekday']}' 불일치"
        print(
            f"[L{d['line_no']}] {d['raw']} → {d['iso_date']} {d['time'] or ''}"
            f" {d['weekday'] or '?'}요일{yinf}  종류: {d['kind']}"
            f"  {wmm}"
        )
        if d["context"]:
            ctx = d["context"][:80]
            print(f"        문맥: {ctx}")
    sys.exit(0)


if __name__ == "__main__":
    main()
