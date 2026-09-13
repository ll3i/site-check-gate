#!/usr/bin/env python3
"""
pii_guard_server.py — MCP pii_guard 서버.

tool:
  - scan_pii(text): prelim-extra/pii-guard/scripts/scan_pii.py 의 핵심 로직을
    역할·동작 유지로 호출. 입력된 텍스트에서 개인정보·비밀키 등을 탐지하고
    마스킹값·위치만 반환한다. 원문 값은 절대 내보내지 않는다.

표준 라이브러리만 사용하며, scan_pii.py 의 함수들을 직접 import 해서 재사용한다.
"""
import json
import sys as _sys
import os as _os
from typing import Any, Dict, List

# service/ 디렉토리를 sys.path에 추가하여 service.mcp_servers._base 등 import 가능
_service_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _service_dir not in _sys.path:
    _sys.path.insert(0, _service_dir)

# 프로젝트 루트 / prelim-extra/pii-guard/scripts 를 sys.path에 추가
_proj_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
_scan_dir = _os.path.join(_proj_root, "prelim-extra", "pii-guard", "scripts")
if _scan_dir not in _sys.path:
    _sys.path.insert(0, _scan_dir)

from service.mcp_servers._base import MCPServer, MCPError

# ── scan_pii.py 재사용 (역할·동작 유지) ─────────────────────────────────────────
from scan_pii import (
    scan_lines,
    compute_risk,
    HIGH_RISK_TYPES,
    build_json_report,
)


# ── MCP 서버 정의 ───────────────────────────────────────────────────────────────

class PIIGuardServer(MCPServer):
    """pii_guard MCP 서버 — 텍스트 내 개인정보·비밀키 스캔."""

    SERVER_NAME = "pii_guard"
    SERVER_VERSION = "1.0.0"

    TOOL_SCHEMAS = [
        {
            "name": "scan_pii",
            "description": (
                "주어진 텍스트(이름·문서 본문 등)에서 개인정보·비밀키·인증토큰 등을 "
                "탐지한다. 탐지된 원문 값은 절대 반환하지 않고 마스킹된 값과 "
                "위치(줄·열)·유형·신뢰도만 보고한다. "
                "prelim-extra/pii-guard/scripts/scan_pii.py 의 핵심 로직을 재사용."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "스캔할 텍스트 (문서 본문, CSV 내용 등)",
                    },
                    "min_confidence": {
                        "type": "string",
                        "enum": ["info", "low", "medium", "high"],
                        "description": "필터링 기준 신뢰도 (기본: info)",
                        "default": "info",
                    },
                },
                "required": ["text"],
            },
        },
    ]

    # ── 도구 핸들러 ──────────────────────────────────────────────────────────

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "scan_pii":
            return self._handle_scan_pii(arguments)
        else:
            raise NotImplementedError(f"도구 '{name}' 미구현")

    def _handle_scan_pii(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """텍스트 스캔 → 탐지 결과 (마스킹값·위치만) 반환."""
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "text (str, nonempty)가 필요",
            )

        min_confidence = args.get("min_confidence", "info")
        if not isinstance(min_confidence, str) or min_confidence not in (
            "info", "low", "medium", "high",
        ):
            min_confidence = "info"

        # ── in-memory 스캔: 임시 텍스트 파일을 만들지 않고 scan_lines 직접 호출 ──
        # scan_pii의 read_file_lines/process_file은 실제 파일 경로가 필요하므로,
        # 메모리에서 라인 리스트를 만든 뒤 scan_lines를 직접 호출한다.

        lines = [(i, ln) for i, ln in enumerate(text.splitlines(), 1)]
        findings = scan_lines(lines, csv_headers=None)

        # 신뢰도 필터링
        if min_confidence != "info":
            conf_rank = {"info": 0, "low": 1, "medium": 2, "high": 3}
            cut = conf_rank.get(min_confidence, 0)
            if cut > 0:
                findings = [
                    f for f in findings
                    if conf_rank.get(f["confidence"], 0) >= cut
                ]

        # 위험도 판정
        fake_file = {
            "path": "<in-memory>",
            "count": len(findings),
            "findings": findings,
        }
        all_files = [fake_file]
        risk = compute_risk(all_files)

        # JSON 리포트 재구성 (고수준 요약 + findings 상세)
        # 찾는 이가 클라이언트에 바로 보여주기 좋은 형태로 정리
        type_counts: Dict[str, int] = {}
        for f in findings:
            t = f.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        high_risk = [f for f in findings if f.get("type") in HIGH_RISK_TYPES]
        has_high_confidence_high_risk = any(
            f.get("confidence") == "high" and f.get("type") in HIGH_RISK_TYPES
            for f in findings
        )

        return {
            "ok": True,
            "scan_type": "pii_guard",
            "risk": risk,
            "total_findings": len(findings),
            "type_counts": type_counts,
            "high_risk_count": len(high_risk),
            "high_confidence_high_risk": has_high_confidence_high_risk,
            "min_confidence": min_confidence,
            "findings": [
                {
                    "type": f.get("type"),
                    "line": f.get("line"),
                    "col": f.get("col"),
                    "matched_length": f.get("matched"),
                    "confidence": f.get("confidence"),
                    "validated": f.get("validated"),
                    "masked": f.get("masked"),
                    "context": f.get("context"),
                    "meta": f.get("meta"),
                }
                for f in findings
            ],
            "note": (
                "원문 값은 보고되지 않으며, 마스킹값과 위치만 표시됩니다. "
                "본 결과는 자동 탐지 결과이며 법적 확정 진단이 아닙니다."
            ),
        }


# ── CLI (stdio MCP 서버로 실행) ─────────────────────────────────────────────────

def main() -> None:
    server = PIIGuardServer()
    server.run()


if __name__ == "__main__":
    main()
