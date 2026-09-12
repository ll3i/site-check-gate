#!/usr/bin/env python3
"""
analyze.py — 공모전 공고 브리핑 오케스트레이터.

동작:
1) 입력 확보: <file> 없거나 --sample → 내장 샘플
2) doc_to_text 로 평문 추출 → work/notice.txt
3) extract_dates 로 날짜 정규화 → dates[]
4) dday 로 D-day/영업일 계산 (date 목록 전달)
5) scan_rules 로 실격·규격·배점·문의처 추출
6) work/analysis.json 생성 + 사람이 읽는 요약 3~5줄

종료코드:
  0 정상 (no_dates 포함)
  2 입력 없음/변환 실패
  3 기타 스크립트 실패
"""
import sys
sys.dont_write_bytecode = True
import argparse
import datetime
import json
import os
import re
import subprocess
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(_HERE)


def _script(name):
    return os.path.join(_HERE, name)


def _workdir(wd):
    os.makedirs(wd, exist_ok=True)
    return wd


def _run_py(script, argv, ok_codes=(0,)):
    p = subprocess.run(
        [sys.executable, script] + argv,
        capture_output=True, text=True, timeout=120,
        cwd=PROJECT,
    )
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    # JSON 오류 출력 감지
    if p.returncode != 0:
        try:
            j = json.loads(out)
            if "error" in j and "exit_code" in j:
                return j["exit_code"], j.get("error") or (err or "오류")
        except Exception:
            pass
        return p.returncode, (err or out or "알 수 없는 오류")
    return p.returncode, out


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _notice_txt_path(workdir):
    return os.path.join(workdir, "notice.txt")


def _analysis_json_path(workdir):
    return os.path.join(workdir, "analysis.json")


def _sample_notice_path():
    return os.path.join(PROJECT, "assets", "samples", "sample_notice.md")


def _is_notice_like(text):
    """공고문 특징 키워드 있는지(느슨한판정)."""
    keys = ["공모", "접수", "마감", "제출", "심사", "배점", "시상", "지원", "자격", "주최"]
    hit = sum(1 for k in keys if k in text)
    return hit >= 2


def _extract_competition_name(text):
    """공고 앞머리 대회명 후보 추출."""
    for line in text.split("\n")[:15]:
        s = line.strip()
        if re.search(r"(대회|공모|아이디어톤|해커톤|경진|챌린지|톤|컵|페어|포럼|컨퍼런스)", s):
            cand = re.sub(r"^[#\-\*·\s]+", "", s).strip()
            cand = re.sub(r"[:：].*$", "", cand).strip()
            if len(cand) >= 3 and len(cand) <= 80:
                return cand
    return None


def _today_iso():
    return datetime.date.today().isoformat()


def main():
    ap = argparse.ArgumentParser(
        description="공모전 공고 브리핑 오케스트레이터"
    )
    ap.add_argument("file", nargs="?", default=None, help="공고 파일 경로")
    ap.add_argument("--sample", "-s", action="store_true", help="내장 샘플 사용")
    ap.add_argument("--today", "-t", help="기준일 YYYY-MM-DD (생략 시 오늘)")
    ap.add_argument("--workdir", "-w", default="work", help="작업 디렉토리 (기본: work)")
    args = ap.parse_args()

    work = _workdir(args.workdir)

    # ---- 입력 확보 ----
    source_text = None
    source_kind = None
    source_label = None

    if args.sample or (args.file is None and not args.sample):
        # 둘 다 없으면 --sample 로 시연
        if args.file is None and not args.sample:
            # 인자 없이 호출 시 사용법을 안내하고 샘플로 진행 (DoD 1)
            print("사용법: python scripts/analyze.py <파일> [--today YYYY-MM-DD] [--workdir work]")
            print("       python scripts/analyze.py --sample [--today YYYY-MM-DD]")
            print("       공고 텍스트가 없으면 내장 샘플로 시연합니다.")
            args.sample = True
        sample_path = _sample_notice_path()
        if not os.path.isfile(sample_path):
            print(json.dumps({"status": "error", "message": "샘플 파일 없음", "exit_code": 2}))
            sys.exit(2)
        with open(sample_path, "r", encoding="utf-8") as f:
            source_text = f.read()
        source_kind = "sample"
        source_label = os.path.basename(sample_path)
    elif args.file:
        # 파일 경로: doc_to_text 로 추출
        ext = os.path.splitext(args.file)[1].lower()
        plain, code, err_msg = None, None, None
        if ext in (".txt", ".md", ".markdown", ".htm", ".html"):
            # 직접 읽기
            if not os.path.isfile(args.file):
                print(json.dumps({"status": "error", "message": f"파일 없음: {args.file}", "exit_code": 2}))
                sys.exit(2)
            with open(args.file, "r", encoding="utf-8", errors="replace") as f:
                source_text = f.read()
            source_kind = "text"
            source_label = os.path.basename(args.file)
        else:
            # doc_to_text 실행
            rc, out = _run_py(_script("doc_to_text.py"), [args.file])
            if rc != 0:
                # JSON 오류 메시지면 그대로
                print(json.dumps({"status": "error", "message": out, "exit_code": rc}))
                sys.exit(2 if rc == 2 else 3)
            source_text = out
            source_kind = ext.lstrip(".")
            source_label = os.path.basename(args.file)

    if source_text is None or not source_text.strip():
        print(json.dumps({"status": "error", "message": "빈 공고문입니다. 내용을 확인하세요.", "exit_code": 2}))
        sys.exit(2)

    # ---- 공고문 여부 확인 ----
    notice_like = _is_notice_like(source_text)
    warnings = []
    if not notice_like:
        warnings.append("공고문 특징 키워드 거의 없음 — 공모전 공고인지 확인 권장")

    # ---- 개인정보 마스킹 (선택) ----
    masked = source_text
    masked = re.sub(r"\b\d{6}[-]\d{7}\b", "******-*******", masked)
    masked = re.sub(r"\b\d{3}[-]\d{4}[-]\d{4}\b", "***-****-****", masked)

    # ---- work/notice.txt 저장 ----
    nt_path = _notice_txt_path(work)
    with open(nt_path, "w", encoding="utf-8") as f:
        f.write(masked)

    # ---- extract_dates ----
    today = args.today or _today_iso()
    rc, dates_out = _run_py(_script("extract_dates.py"), [nt_path, "--json", "--today", today])
    if rc != 0:
        # 날짜 0건(exit 3)은 정상(임시로 empty)
        dates = []
        if rc == 3:
            try:
                j = json.loads(dates_out)
                if "error" in j:
                    warnings.append(f"날짜 추출: {j['error']}")
                    dates = []
            except Exception:
                warnings.append("날짜 추출 실패")
    else:
        try:
            jd = json.loads(dates_out)
            dates = jd.get("dates", [])
        except Exception:
            dates = []
            warnings.append("날짜 추출 결과 파싱 실패")

    primary_deadline = None
    date_flags = {
        "weekday_mismatch": any(d.get("weekday_mismatch") for d in dates),
        "year_inferred": any(d.get("year_inferred") for d in dates),
        "past_deadline": False,
        "holiday_or_weekend": False,
    }

    # 제출마감 중 가장 이른 것을 primary_deadline 로
    submit_dates = [d for d in dates if d.get("kind") == "제출마감"]
    if submit_dates:
        submit_sorted = sorted(submit_dates, key=lambda d: d["iso_date"])
        primary_deadline = submit_sorted[0]
    elif dates:
        # 제출일 마감이 없으면 가장 이른 날짜를 primary 후보로
        sorted_all = sorted(dates, key=lambda d: d["iso_date"])
        primary_deadline = sorted_all[0]

    # past_deadline/ holiday_or_weekend 플래그는 dday 결과로 보강을 나중에

    # ---- dday (날짜 목록 전달) ----
    # 임시 JSON 파일 만들어 전달
    dates_json_path = os.path.join(work, "dates.json")
    _save_json(dates_json_path, {"dates": dates})
    rc, dday_out = _run_py(_script("dday.py"), ["--from-json", dates_json_path, "--today", today])
    dday_results = []
    if rc == 0:
        try:
            jd2 = json.loads(dday_out)
            dday_results = jd2.get("results", [])
            for r in dday_results:
                if r.get("past"):
                    date_flags["past_deadline"] = True
                if r.get("weekday") in ("토", "일"):
                    date_flags["holiday_or_weekend"] = True
        except Exception:
            pass
    elif rc == 2:
        # 날짜 없음
        date_flags["past_deadline"] = False

    # ---- scan_rules ----
    rc, scan_out = _run_py(_script("scan_rules.py"), [nt_path, "--json"])
    scan = {}
    if rc == 0:
        try:
            scan = json.loads(scan_out)
        except Exception:
            scan = {}
    else:
        warnings.append(f"규격/실격 스캔 실패 (exit {rc})")

    # ---- schedule 구성 ----
    schedule = []
    for d in dates:
        dd = None
        for r in dday_results:
            if r.get("target") == d["iso_date"]:
                dd = r
                break
        sched_item = {
            "raw": d["raw"],
            "iso_date": d["iso_date"],
            "time": d.get("time"),
            "weekday": d.get("weekday"),
            "weekday_in_text": d.get("weekday_in_text"),
            "kind": d.get("kind"),
            "dday_label": dd.get("dday_label") if dd else "계산 불가",
            "dday": dd.get("dday") if dd else None,
            "business_days_left": dd.get("business_days_left") if dd else None,
            "holidays_between": dd.get("holidays_between") if dd else [],
            "warnings": dd.get("warnings", []) if dd else [],
            "line_no": d.get("line_no"),
            "context": d.get("context"),
        }
        schedule.append(sched_item)

    # ---- primary_deadline 보강 ----
    primary_iso = primary_deadline.get("iso_date") if primary_deadline else None
    primary_time = primary_deadline.get("time") if primary_deadline else None

    # ---- 분석.json ----
    analysis = {
        "status": "ok" if (dates or notice_like) else "no_dates",
        "today": today,
        "input": {
            "source": source_label,
            "kind": source_kind,
            "lines": len(masked.split("\n")),
        },
        "warnings": warnings,
        "schedule": schedule,
        "primary_deadline": {
            "iso_date": primary_iso,
            "time": primary_time,
            "raw": primary_deadline.get("raw") if primary_deadline else None,
            "kind": primary_deadline.get("kind") if primary_deadline else None,
            "line_no": primary_deadline.get("line_no") if primary_deadline else None,
        },
        "date_flags": date_flags,
        "rules": scan,
    }
    _save_json(_analysis_json_path(work), analysis)

    # ---- 사람이 읽는 요약 3~5줄 ----
    comp_name = _extract_competition_name(masked) or "(대회명 미확인)"
    print(f"\n=== {comp_name} 공고 분석 요약 ===")
    print(f"입력: {source_label} ({source_kind}) / {len(masked.split(chr(10)))}줄")
    if dates:
        print(f"추출 날짜: {len(dates)}건")
        for d in dates[:6]:
            yinf = " (연도 추정)" if d.get("year_inferred") else ""
            wmm = " ⚠요일불일치" if d.get("weekday_mismatch") else ""
            print(
                f"  [L{d['line_no']}] {d['raw']} → {d['iso_date']} {d.get('time') or ''} "
                f"{d['weekday']}요일{yinf} · {d['kind']}{wmm}"
            )
        if len(dates) > 6:
            print(f"  ... 외 {len(dates)-6}건")
    else:
        print("추출 날짜: 0건 — 일정표를 '공고에 없음'으로 표기")

    if primary_iso:
        print(f"가장 이른 제출마감(primary): {primary_iso} {primary_time or ''}")

    if date_flags["weekday_mismatch"]:
        print("⚠ 요일 불일치 감지 — 표에 '주최 측 확인' 경고 포함")
    if date_flags["year_inferred"]:
        print("⚠ 연도 추정 날짜 포함 — '(연도 추정)' 표기")
    if date_flags["past_deadline"]:
        print("⚠ 마감 경과")
    if date_flags["holiday_or_weekend"]:
        print("⚠ 마감일이 주말/공휴일 가능성")

    sc = analysis["rules"]
    if sc.get("risk_lines"):
        print(f"\n실격·유의 라인: {len(sc['risk_lines'])}건")
        for r in sc["risk_lines"][:8]:
            print(f"  [L{r['line_no']}] {r['text'][:90]}")
        if len(sc["risk_lines"]) > 8:
            print(f"  ... 외 {len(sc['risk_lines'])-8}건")
    else:
        print("실격·유의 라인: 0건")

    if sc.get("spec_lines"):
        print(f"\n규격 수치 라인: {len(sc['spec_lines'])}건")
        for r in sc["spec_lines"][:6]:
            print(f"  [L{r['line_no']}] {r['text'][:80]} → {r['specs']}")

    if sc.get("score_lines"):
        ssc = sc["score_sum_check"]
        print(f"\n배점 라인: {len(sc['score_lines'])}건, 표 셀 합계 ≈ {ssc['sum_of_table_points']} → {'100 일치 ✓' if ssc['looks_like_100'] else '공고 확인 필요'}")

    if sc.get("contacts"):
        print(f"\n문의처: 이메일 {sc['contacts']['emails']}, 전화 {sc['contacts']['phones']}, URL {sc['contacts']['urls']}")

    if warnings:
        print(f"\n⚠ 경고: {'; '.join(warnings)}")

    print(f"\n결과 저장: {work}/notice.txt, {work}/analysis.json")
    sys.exit(0)


if __name__ == "__main__":
    main()
