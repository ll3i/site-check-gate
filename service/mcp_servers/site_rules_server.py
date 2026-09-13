#!/usr/bin/env python3
"""
site_rules_server.py — MCP site_rules 서버.

tool:
  - check_subcontract(text): 고용노동부 「근로자파견 판단기준」 에 따라
    문서 텍스트의 적법도급 5축·약 20개 세부 점검항목을 평가한다.
    service/core/subcontract_check.py 의 check_subcontract 함수를 재사용한다.

표준 라이브러리만 사용하며, 기존 판정 로직을 그대로 활용한다.
"""
import json
import sys
import os
from typing import Any, Dict
# 동일 패키지 내 베이스 import (절대 import + sys.path 확보)
import sys as _sys
import os as _os
_base_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _base_dir not in _sys.path:
    _sys.path.insert(0, _base_dir)
from service.mcp_servers._base import MCPServer, MCPError

# ── subcontract_check 재사용 ────────────────────────────────────────────────────
from service.core.subcontract_check import (
    check_subcontract,
    check_subcontract_json,
    evaluate_item,
    LABEL_FOUND_COMPLIANT,
    LABEL_FOUND_RISK,
    LABEL_NONEED,
)


# ── MCP 서버 정의 ───────────────────────────────────────────────────────────────

class SiteRulesServer(MCPServer):
    """site_rules MCP 서버 — 적법도급 체크리스트 점검"""

    SERVER_NAME = "site_rules"
    SERVER_VERSION = "1.0.0"

    TOOL_SCHEMAS = [
        {
            "name": "check_subcontract",
            "description": (
                "문서 텍스트(도급 계약서, 업무 규정, 공고문 등)를 입력받아 "
                "고용노동부 「근로자파견의 판단기준에 관한 지침」의 5축·약 20개 "
                "세부 점검항목에 대해 근거 문장 후보 기반 3분기 판정을 수행한다. "
                "service/core/subcontract_check.py 의 check_subcontract 재사용."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "점검할 문서 텍스트 (계약서, 규정, 공고문 등)",
                    },
                },
                "required": ["text"],
            },
        },
    ]

    # ── 도구 핸들러 ──────────────────────────────────────────────────────────

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "check_subcontract":
            return self._handle_check_subcontract(arguments)
        else:
            raise NotImplementedError(f"도구 '{name}' 미구현")

    def _handle_check_subcontract(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """적법도급 체크리스트 점검."""
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "text (str, nonempty)가 필요",
            )

        # 원본 check_subcontract 호출 (reuse)
        result = check_subcontract(text)

        # 라벨 개수로 요약
        summary = {
            "total": result.get("total_items", 0),
            "risk_count": 0,
            "compliant_count": 0,
            "noneed_count": 0,
        }
        for item in result.get("results", []):
            label = item.get("label")
            if label == LABEL_FOUND_RISK:
                summary["risk_count"] += 1
            elif label == LABEL_FOUND_COMPLIANT:
                summary["compliant_count"] += 1
            elif label == LABEL_NONEED:
                summary["noneed_count"] += 1

        # 축별 요약
        axis_summary: Dict[int, Dict[str, Any]] = {}
        for ax, data in result.get("axis_summary", {}).items():
            axis_summary[int(ax)] = data

        # 각 항목별로 근거 문장·판정 라벨·위험 키워드 등을 평탄화
        items_out: List[Dict[str, Any]] = []
        for item in result.get("results", []):
            items_out.append({
                "axis": item.get("axis"),
                "item": item.get("item"),
                "name": item.get("name"),
                "desc": item.get("desc"),
                "label": item.get("label"),
                "evidence_sentences": item.get("evidence_sentences", []),
                "matched_patterns": item.get("matched_patterns", []),
                "compliant_keywords_hit": item.get("compliant_keywords_hit", []),
                "risk_keywords_hit": item.get("risk_keywords_hit", []),
            })

        # 전체 위험도 신호: risk_count > 0 이면 경고
        has_risk_signal = summary["risk_count"] > 0

        return {
            "ok": True,
            "total_items": summary["total"],
            "summary": summary,
            "axis_summary": axis_summary,
            "items": items_out,
            "has_risk_signal": has_risk_signal,
            "text_length": result.get("text_length"),
        }


# ── CLI (stdio MCP 서버로 실행) ─────────────────────────────────────────────────

def main() -> None:
    server = SiteRulesServer()
    server.run()


if __name__ == "__main__":
    main()
