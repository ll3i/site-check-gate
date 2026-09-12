#!/usr/bin/env python3
"""
dday.py — D-day, 남은 영업일(주말+관공서 공휴일 제외), 경고 계산.

입력: ISO date(... ) 또는 --from-json (analysis.json 경로).
출력: {today, results[{target, target_time, weekday, dday, dday_label, business_days_left, holidays_between[], past, warnings[]}]}
"""
import sys
sys.dont_write_bytecode = True
import argparse
import datetime
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
HOLIDAYS_PATH = os.path.join(_HERE, "..", "references", "holidays_kr_2026_2027.json")


def _load_holidays():
    try:
        with open(HOLIDAYS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()
    hs = set()
    for y in ("2026", "2027"):
        for item in data.get(y, []):
            try:
                d = datetime.date.fromisoformat(item["date"])
                hs.add(d)
            except Exception:
                pass
    return hs


_KR_WEEKDAY = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
_NUM2KR = "월화수목금토일"


def _in_range(start, end, target):
    if start is None or end is None:
        return False
    return start <= target <= end


def _business_days_between(start, end, holidays):
    """남은 영업일: 오늘 제외, 마감일 포함. 주말·휴일 제외."""
    if end < start:
        return 0
    count = 0
    d = start + datetime.timedelta(days=1)  # 오늘 제외
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            count += 1
        d += datetime.timedelta(days=1)
    return count


def _holidays_between(start, end, holidays):
    out = []
    d = start + datetime.timedelta(days=1)
    while d <= end:
        if d in holidays:
            out.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return out


def _weekday_of(iso):
    d = datetime.date.fromisoformat(iso)
    return _NUM2KR[d.weekday()]


def _compute_dday(target_iso, target_time, today, holidays):
    t = datetime.date.fromisoformat(target_iso)
    dday = (t - today).days
    past = dday < 0
    wd = _weekday_of(target_iso)

    # D-day 라벨
    if past:
        label = f"마감 ({abs(dday)}일 경과)"
    elif dday == 0:
        label = "D-Day (오늘 마감)"
    elif dday == 1:
        label = "D-1 (내일 마감)"
    else:
        label = f"D-{dday}"

    bd = _business_days_between(today, t, holidays)
    hb = _holidays_between(today, t, holidays)

    warnings = []
    if past:
        warnings.append("마감이 지났습니다.")
    elif dday <= 3:
        warnings.append(f"D-{dday} 이내 — 즉시 준비 필요.")
    if t.weekday() >= 5:
        wdname = _NUM2KR[t.weekday()]
        warnings.append(f"마감일이 {wdname}요일(주말)입니다. 접수 시스템 운영 여부 확인 필요.")
    for h in hb:
        warnings.append(f"마감 전까지 공휴일: {h}.")
    if target_time:
        # 자정 처리 경고
        if target_time.endswith("T23:59") or "자정" in target_time:
            warnings.append("마감 시각이 자정/23:59 — 당일 업로드분 인정 여부 확인.")

    return {
        "target": target_iso,
        "target_time": target_time,
        "weekday": wd,
        "dday": dday,
        "dday_label": label,
        "business_days_left": bd,
        "holidays_between": hb,
        "past": past,
        "warnings": warnings,
    }


def _parse_json_input(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    dates = data.get("input", {}).get("dates") or data.get("dates") or []
    return dates


def main():
    ap = argparse.ArgumentParser(
        description="D-day·남은 영업일 계산 (공휴일 제외, 주말 제외)"
    )
    ap.add_argument("iso_dates", nargs="*", help="계산할 ISO 날짜들 (YYYY-MM-DD)")
    ap.add_argument("--from-json", "-j", help="JSON 파일에서 날짜 읽기")
    ap.add_argument("--today", "-t", help="기준일 YYYY-MM-DD")
    args = ap.parse_args()

    today = None
    if args.today:
        try:
            y, m, d = [int(x) for x in args.today.split("-")]
            today = datetime.date(y, m, d)
        except Exception:
            print(json.dumps({"error": f"잘못된 --today: {args.today}", "exit_code": 2}))
            sys.exit(2)
    if today is None:
        today = datetime.date.today()

    holidays = _load_holidays()

    dates = []
    if args.from_json:
        if not os.path.isfile(args.from_json):
            print(json.dumps({"error": f"파일 없음: {args.from_json}", "exit_code": 2}))
            sys.exit(2)
        dates = _parse_json_input(args.from_json)
        if not dates:
            print(json.dumps({"error": "날짜를 0건 찾았습니다.", "exit_code": 2}))
            sys.exit(2)
    else:
        if not args.iso_dates:
            print(json.dumps({"error": "ISO 날짜 또는 --from-json 필요", "exit_code": 2}))
            sys.exit(2)
        dates = args.iso_dates

    results = []
    for item in dates:
        if isinstance(item, dict):
            iso = item.get("iso_date")
            time_ = item.get("time")
        else:
            iso = item
            time_ = None
        if not iso:
            continue
        try:
            r = _compute_dday(iso, time_ or "", today, holidays)
            results.append(r)
        except Exception as e:
            results.append({"target": iso, "error": str(e)})

    out = {
        "today": today.isoformat(),
        "results": results,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
