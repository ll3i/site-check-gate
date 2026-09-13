#!/usr/bin/env python3
"""
contest_brief_server.py — MCP contest_brief 서버.

tool:
  - analyze_notice(text): 공고문 텍스트에서 마감·D-day·제출요건·실격조건을 추출.
    prelim-extra/contest-brief/scripts/ 의 원본(extract_dates.py·dday.py·scan_rules.py)을
    역할·동작 유지로 호출하여 결과를 통합 반환한다.
    점검 지시서·발주 공고에도 동일 적용된다.

표준 라이브러리만 사용하며, 기존 스크립트 로직을 그대로 재사용한다.
"""
import json
import os
import sys
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

# 동일 패키지 내 베이스 import (절대 import + sys.path 확보)
import os as _os
import sys as _sys
_base_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _base_dir not in _sys.path:
    _sys.path.insert(0, _base_dir)
from service.mcp_servers._base import MCPServer, MCPError

# 스크립트 디렉토리
_SCRIPTS_DIR = os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "..", "..", "prelim-extra", "contest-brief", "scripts"
)
_SCRIPTS_DIR = os.path.abspath(_SCRIPTS_DIR)

_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))


def _run_script(script_name: str, argv: List[str], timeout: int = 30) -> tuple:
    """스크립트를 호출하고 (exit_code, stdout, stderr)를 반환."""
    script_path = os.path.join(_SCRIPTS_DIR, script_name)
    if not os.path.isfile(script_path):
        raise RuntimeError(f"스크립트 없음: {script_path}")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = _PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")

    p = subprocess.run(
        [sys.executable, script_path] + argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=_PROJECT_ROOT,
        env=env,
    )
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def _parse_json_output(stdout: str) -> Dict[str, Any]:
    """스크립트 stdout 을 JSON 으로 파싱."""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {}


# ── MCP 서버 정의 ───────────────────────────────────────────────────────────────

class ContestBriefServer(MCPServer):
    """contest_brief MCP 서버 — 공고문 분석 (마감·D-day·제출요건·실격조건)"""

    SERVER_NAME = "contest_brief"
    SERVER_VERSION = "1.0.0"

    TOOL_SCHEMAS = [
        {
            "name": "analyze_notice",
            "description": (
                "공고문 텍스트(점검 지시서·발주 공고·공모전 공고 등)를 입력받아 "
                "마감일·D-day·제출요건·실격조건을 추출한다. "
                "prelim-extra/contest-brief/scripts/ 의 extract_dates.py·dday.py·scan_rules.py 를 "
                "원본 역할 그대로 호출하여 결과를 통합 반환한다."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "분석할 공고문 텍스트 (점검 지시서, 발주 공고, 공모전 공고 등)",
                    },
                },
                "required": ["text"],
            },
        },
    ]

    # ── 도구 핸들러 ──────────────────────────────────────────────────────────

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "analyze_notice":
            return self._handle_analyze_notice(arguments)
        else:
            raise NotImplementedError(f"도구 '{name}' 미구현")

    def _handle_analyze_notice(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """공고문 텍스트 분석."""
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "text (str, nonempty)가 필요",
            )

        # 임시 파일로 텍스트 저장 (스크립트들이 파일 경로를 받으므로)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as f:
            f.write(text)
            tmp_path = f.name

        try:
            today = subprocess.run(
                [sys.executable, "-c", "import datetime; print(datetime.date.today().isoformat())"],
                capture_output=True, text=True, timeout=5
            ).stdout.strip()

            # 1) extract_dates
            rc, dates_out, _ = _run_script("extract_dates.py", [
                tmp_path, "--json", "--today", today
            ])
            dates = []
            if rc == 0:
                jd = _parse_json_output(dates_out)
                dates = jd.get("dates", [])
            elif rc == 3:
                # 날짜 0건 — 정상 케이스
                dates = []

            # 2) dday (날짜 목록 전달)
            dday_results = []
            if dates:
                import tempfile as _tmp
                with _tmp.NamedTemporaryFile(
                    mode="w", suffix=".json", encoding="utf-8", delete=False
                ) as jf:
                    json.dump({"dates": dates}, jf)
                    dates_json_path = jf.name
                try:
                    rc2, dday_out, _ = _run_script("dday.py", [
                        "--from-json", dates_json_path, "--today", today
                    ])
                    if rc2 == 0:
                        jd2 = _parse_json_output(dday_out)
                        dday_results = jd2.get("results", [])
                finally:
                    try:
                        os.unlink(dates_json_path)
                    except OSError:
                        pass

            # 3) scan_rules
            rc3, scan_out, _ = _run_script("scan_rules.py", [tmp_path, "--json"])
            scan = {}
            if rc3 == 0:
                scan = _parse_json_output(scan_out)

            # primary_deadline 결정
            primary_deadline = None
            submit_dates = [d for d in dates if d.get("kind") == "제출마감"]
            if submit_dates:
                submit_sorted = sorted(submit_dates, key=lambda d: d["iso_date"])
                primary_deadline = submit_sorted[0]
            elif dates:
                sorted_all = sorted(dates, key=lambda d: d["iso_date"])
                primary_deadline = sorted_all[0]

            # dday 결과와 dates 매칭
            schedule = []
            for d in dates:
                dd = None
                for r in dday_results:
                    if r.get("target") == d.get("iso_date"):
                        dd = r
                        break
                schedule.append({
                    "raw": d.get("raw"),
                    "iso_date": d.get("iso_date"),
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
                })

            # primary_deadline 보강
            primary_iso = primary_deadline.get("iso_date") if primary_deadline else None
            primary_time = primary_deadline.get("time") if primary_deadline else None

            # 날짜 플래그
            date_flags = {
                "weekday_mismatch": any(d.get("weekday_mismatch") for d in dates),
                "year_inferred": any(d.get("year_inferred") for d in dates),
                "past_deadline": any(r.get("past") for r in dday_results),
                "holiday_or_weekend": any(
                    r.get("weekday") in ("토", "일") for r in dday_results
                ),
            }

            # 실격·유의 라인 요약
            risk_lines = scan.get("risk_lines", [])
            risk_summary = {
                "count": len(risk_lines),
                "lines": [
                    {
                        "line_no": r.get("line_no"),
                        "text": r.get("text"),
                        "keywords": r.get("keywords"),
                        "categories": r.get("categories"),
                    }
                    for r in risk_lines[:20]
                ],
            }

            # 규격 수치 요약
            spec_lines = scan.get("spec_lines", [])
            spec_summary = {
                "count": len(spec_lines),
                "lines": [
                    {
                        "line_no": r.get("line_no"),
                        "text": r.get("text"),
                        "specs": r.get("specs"),
                    }
                    for r in spec_lines[:20]
                ],
            }

            # 배점 요약
            score_lines = scan.get("score_lines", [])
            score_summary = {
                "count": len(score_lines),
                "lines": [
                    {
                        "line_no": r.get("line_no"),
                        "text": r.get("text"),
                        "points": r.get("points"),
                    }
                    for r in score_lines[:20]
                ],
                "score_sum_check": scan.get("score_sum_check", {}),
            }

            # 문의처
            contacts = scan.get("contacts", {})

            return {
                "ok": True,
                "text_length": len(text),
                "today": today,
                "date_count": len(dates),
                "primary_deadline": {
                    "iso_date": primary_iso,
                    "time": primary_time,
                    "raw": primary_deadline.get("raw") if primary_deadline else None,
                    "kind": primary_deadline.get("kind") if primary_deadline else None,
                    "line_no": primary_deadline.get("line_no") if primary_deadline else None,
                },
                "schedule": schedule,
                "date_flags": date_flags,
                "risk": risk_summary,
                "specs": spec_summary,
                "scores": score_summary,
                "contacts": contacts,
            }

        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── CLI (stdio MCP 서버로 실행) ─────────────────────────────────────────────────

def main() -> None:
    server = ContestBriefServer()
    server.run()


if __name__ == "__main__":
    main()
