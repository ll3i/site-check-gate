#!/usr/bin/env python3
"""
cite_core_server.py — MCP cite_core 서버.

tools:
  - verify_references(text): 참고문헌 텍스트 → 예선 파이프( parse → verify ) 판정 결과
  - match_claim(claim, title, abstract): 주장-메타데이터(⑧) 판정

표준 라이브러리만 사용하며, 기존 service/core 파이프라인(parse_refs + verify_refs +
match_claims)을 재사용한다. verify_references는 오프라인(API 호출 없음) 경로만 사용하고,
match_claim은 solar-pro4 호출이 필요하므로 API 키 없으면 graceful하게 실패한다.
"""
import json
import sys
import os
import argparse
from typing import Any, Dict, List

# 동일 패키지 내 베이스 import (절대 import + sys.path 확보)
import sys as _sys
import os as _os
_base_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _base_dir not in _sys.path:
    _sys.path.insert(0, _base_dir)
from service.mcp_servers._base import MCPServer, MCPError

# ── 기존 파이프라인 모듈 (동일 프로젝트) ───────────────────────────────────────

# parse_refs: 참고문헌 텍스트 → 항목별 구조
from service.core.parse_refs import (
    parse_item,
    split_auto,
    trim_preamble,
    DOI_RE,
    ARXIV_ABS_RE,
    ARXIV_PREFIX_RE,
)

# verify_refs: 항목별 검증 파이프라인 (오프라인 버전 — API 호출 없음)
from service.core.verify_refs import (
    verify_item,
    STATUS_MAP,
    build_corrected_bib,
    normalize_text,
    title_similarity,
)

# match_claims: 주장-근거 대조 (solar-pro4)
from service.core.match_claims import (
    match_single_claim,
    VERDICT_SUPPORTED,
    VERDICT_NOT_SUPPORTED,
    VERDICT_CANNOT_JUDGE,
    quote_exists_in_metadata,
    normalize_text as mc_normalize,
)


# ── MCP 서버 정의 ───────────────────────────────────────────────────────────────

class CiteCoreServer(MCPServer):
    """cite_core MCP 서버 — 참고문헌 검증(verify_references) + 주장 대조(match_claim)."""

    SERVER_NAME = "cite_core"
    SERVER_VERSION = "1.0.0"

    TOOL_SCHEMAS = [
        {
            "name": "verify_references",
            "description": (
                "참고문헌 텍스트(목록 문단/줄)를 파싱한 뒤, 각 항목을 "
                "DOI/arXiv/Crossref/DataCite 기준으로 검증하여 "
                "예선 cite-check 파이프 판정(JSON)을 반환한다. "
                "외부 API 호출 없이 파싱+오프라인 판정만 수행한다."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "참고문헌 목록 텍스트 (한 개 이상의 참고문헌 항목 포함)",
                    },
                },
                "required": ["text"],
            },
        },
        {
            "name": "match_claim",
            "description": (
                "주장 문장(claim)과 문헌 메타데이터(제목, 초록)를 받아 "
                "solar-pro4(temperature=0)로 3분기 판정(뒷받침함/뒷받침 안 함/판단 불가)을 수행한다. "
                "UPSTAGE_API_KEY가 없으면 gracefully 실패한다."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "claim": {
                        "type": "string",
                        "description": "검증할 주장 문장",
                    },
                    "title": {
                        "type": "string",
                        "description": "문헌 제목 (메타데이터)",
                    },
                    "abstract": {
                        "type": "string",
                        "description": "문헌 초록 (메타데이터)",
                    },
                },
                "required": ["claim", "title", "abstract"],
            },
        },
    ]

    # ── 도구 핸들러 ──────────────────────────────────────────────────────────

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "verify_references":
            return self._handle_verify_references(arguments)
        elif name == "match_claim":
            return self._handle_match_claim(arguments)
        else:
            raise NotImplementedError(f"도구 '{name}' 미구현")

    # ── verify_references ─────────────────────────────────────────────────────

    def _handle_verify_references(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """참고문헌 텍스트 → 예선 파이프( parse → verify ) 판정 결과.

        parse_refs.split_auto 로 항목 분리 → parse_item 로 구조화 →
        verify_item(offline=True) 로 판정 → 집계 report 반환.
        """
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "text (str, nonempty)가 필요",
            )

        # 1) 파싱 (split_auto + parse_item)
        cleaned = trim_preamble(text)
        items_text = split_auto(cleaned)
        parsed_items = []
        for idx, txt in enumerate(items_text, start=1):
            item = parse_item(txt, idx)
            if item:
                parsed_items.append(item)

        if not parsed_items:
            return {
                "ok": False,
                "count": 0,
                "items": [],
                "note": "참고문헌 항목을 찾을 수 없음",
            }

        # 2) 항목별 검증 (오프라인 — API 호출 없음)
        verified = []
        for item in parsed_items:
            result = verify_item(item, offline=True)
            result["parsed"] = {
                "id": item["id"],
                "raw": item["raw"],
                "doi": item.get("doi"),
                "arxiv": item.get("arxiv"),
                "url": item.get("url"),
                "year": item.get("year"),
                "title": item.get("title"),
                "first_author": item.get("first_author"),
                "kind": item.get("kind"),
                "confidence": item.get("confidence"),
                "notes": item.get("notes", []),
            }
            # 상태 아이콘 매핑
            status_icon = STATUS_MAP.get(result["status"], "?")
            result["status_icon"] = status_icon
            # 교정 서지 (✅/⚠️ 항목)
            if result["status"] in ("verified", "partial"):
                result["corrected_bib"] = build_corrected_bib(item, result.get("matched"))
            else:
                result["corrected_bib"] = None
            verified.append(result)

        # 3) 집계
        status_counts: Dict[str, int] = {}
        for v in verified:
            key = v["status"]
            status_counts[key] = status_counts.get(key, 0) + 1

        return {
            "ok": True,
            "count": len(verified),
            "items": verified,
            "status_counts": status_counts,
            "note": "오프라인 파이크 — 외부 API 호출 없음 (parse_refs + verify_refs) ",
        }

    # ── match_claim ───────────────────────────────────────────────────────────

    def _handle_match_claim(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """주장-메타데이터(⑧) 판정.

        match_claims.match_single_claim 을 호출. API 키 없으면 graceful 실패.
        """
        claim = args.get("claim")
        title = args.get("title")
        abstract = args.get("abstract")
        if not isinstance(claim, str) or not claim.strip():
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "claim (str, nonempty)가 필요",
            )
        if not isinstance(title, str):
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "title (str)이 필요",
            )
        if not isinstance(abstract, str):
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "abstract (str)이 필요",
            )

        # solar-pro4 호출 (API 키 없으면 graceful 실패)
        result = match_single_claim(
            claim=claim,
            metadata_title=title,
            metadata_abstract=abstract,
            use_cache=True,
        )

        # 결과가 기본 판정(판단 불가)이고 API 호출이 실패했는지 체크
        if result["verdict"] == VERDICT_CANNOT_JUDGE and not result.get("raw_response"):
            return {
                "ok": False,
                "verdict": VERDICT_CANNOT_JUDGE,
                "quote": "",
                "reason": "solar-pro4 호출 실패 (UPSTAGE_API_KEY 미설정 또는 네트워크 오류)",
                "quote_exists": False,
                "post_processed": False,
                "tags": result.get("tags", []),
            }

        return {
            "ok": True,
            "verdict": result["verdict"],
            "quote": result["quote"],
            "reason": result["reason"],
            "quote_exists": result["quote_exists"],
            "post_processed": result.get("post_processed", False),
            "tags": result.get("tags", []),
        }


# ── CLI (stdio MCP 서버로 실행) ─────────────────────────────────────────────────

def main() -> None:
    server = CiteCoreServer()
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        # 디버깅용: stdin 없이 한 번 테스트
        _debug_once(server)
    else:
        server.run()


def _debug_once(server: CiteCoreServer) -> None:
    """개발 테스트용: subprocess 없이 직접 요청/응답을 확인."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
    }
    resp = server.dispatch(req)
    print("initialize 응답:", json.dumps(resp, ensure_ascii=False, indent=2))

    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
    }
    resp = server.dispatch(req)
    print("tools/list 응답:", json.dumps(resp, ensure_ascii=False, indent=2)[:500])

    # verify_references 테스트 (오프라인이므로 API 키 불필요)
    sample_text = (
        "Goodfellow, I., Bengio, Y., & Courville, A. (2016). Deep Learning. "
        "MIT Press. https://www.deeplearningbook.org/\n"
        "Vaswani, A., et al. (2017). Attention is All You Need. "
        "Advances in Neural Information Processing Systems, 30. "
        "https://arxiv.org/abs/1706.03762"
    )
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "verify_references",
            "arguments": {"text": sample_text},
        },
    }
    resp = server.dispatch(req)
    print("verify_references 응답:", json.dumps(resp, ensure_ascii=False, indent=2)[:800])

    # match_claim 테스트 (API 키 없으면 실패 예상)
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "match_claim",
            "arguments": {
                "claim": "Deep learning is a subset of machine learning based on artificial neural networks.",
                "title": "Deep Learning",
                "abstract": "This book provides a comprehensive overview of deep learning.",
            },
        },
    }
    resp = server.dispatch(req)
    print("match_claim 응답:", json.dumps(resp, ensure_ascii=False, indent=2)[:500])


if __name__ == "__main__":
    main()
