#!/usr/bin/env python3
"""
law_registry_server.py — MCP law_registry 서버.

tools:
  - lookup_article(law_name, article, paragraph?): 법령 스냅샷(assets/law/) 조회
  - search_articles(keyword): 법령명 키워드 검색 → 매칭된 법령 목록

기존 service/core/verify_law_refs.py 의 snapshot 조회 로직을 재사용한다.
MCP 서버는 외부 호출을 하지 않고 assets/law/ 내 JSON 스냅샷만 조회한다.
"""
import json
import sys
import os
from typing import Any, Dict, List, Optional
# 동일 패키지 내 베이스 import (절대 import + sys.path 확보)
import sys as _sys
import os as _os
_base_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _base_dir not in _sys.path:
    _sys.path.insert(0, _base_dir)
from service.mcp_servers._base import MCPServer, MCPError

# ── verify_law_refs 재사용 ──────────────────────────────────────────────────────
# 동일 프로젝트 service/core 의 verify_law_refs 를 import
from service.core.verify_law_refs import (
    lookup_article as _lookup_article,
    extract_law_refs,
    _load_snapshot_meta,
    _SNAPSHOT_LAW_NAMES,
    _SNAPSHOT_ALIASES,
    LAW_SNAPSHOT_DIR,
)


# ── MCP 서버 정의 ───────────────────────────────────────────────────────────────

class LawRegistryServer(MCPServer):
    """law_registry MCP 서버 — 법령 스냅샷 조회·검색."""

    SERVER_NAME = "law_registry"
    SERVER_VERSION = "1.0.0"

    TOOL_SCHEMAS = [
        {
            "name": "lookup_article",
            "description": (
                "법령명과 조 번호로 assets/law/ 스냅샷을 조회한다. "
                "실존·해당 조 없음·스냅샷 미보유 중 하나로 판정한다. "
                "service/core/verify_law_refs.py 의 snapshot 조회 재사용."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "law_name": {
                        "type": "string",
                        "description": "법령명 (예: '근로기준법', '노동조합 및 노동관계조정법')",
                    },
                    "article": {
                        "type": "integer",
                        "description": "조 번호 (예: 2)",
                    },
                    "paragraph": {
                        "type": "integer",
                        "description": "항 번호 (선택, 예: 1)",
                    },
                },
                "required": ["law_name", "article"],
            },
        },
        {
            "name": "search_articles",
            "description": (
                "법령명 키워드(부분 일치)로 assets/law/ 스냅샷을 검색한다. "
                "키워드가 법령명·별칭에 포함된 법령을 반환한다."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "검색 키워드 (부분 일치)",
                    },
                },
                "required": ["keyword"],
            },
        },
    ]

    # ── 도구 핸들러 ──────────────────────────────────────────────────────────

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "lookup_article":
            return self._handle_lookup_article(arguments)
        elif name == "search_articles":
            return self._handle_search_articles(arguments)
        else:
            raise NotImplementedError(f"도구 '{name}' 미구현")

    # ── lookup_article ────────────────────────────────────────────────────────

    def _handle_lookup_article(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """법령명 + 조 번호로 스냅샷 조회."""
        law_name = args.get("law_name")
        article = args.get("article")
        paragraph = args.get("paragraph", None)

        if not isinstance(law_name, str) or not law_name.strip():
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "law_name (str, nonempty)가 필요",
            )
        if not isinstance(article, int) or article < 1:
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "article (int, >=1)가 필요",
            )
        if paragraph is not None and (
            not isinstance(paragraph, int) or paragraph < 1
        ):
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "paragraph (int, >=1)가 필요 (있는 경우)",
            )

        result = _lookup_article(law_name, article, paragraph)
        return {
            "ok": True,
            "law_name": result.get("law_name"),
            "article": result.get("article"),
            "paragraph": result.get("paragraph"),
            "verdict": result.get("verdict"),
            "status_icon": result.get("status_icon"),
            "article_body": result.get("article_body"),
            "note": result.get("note"),
            "snapshot_available": result.get("snapshot") is not None,
        }

    # ── search_articles ───────────────────────────────────────────────────────

    def _handle_search_articles(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """법령명 키워드 검색."""
        keyword = args.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip():
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "keyword (str, nonempty)가 필요",
            )

        _load_snapshot_meta()

        kw = keyword.strip()
        results: List[Dict[str, Any]] = []

        # 1) 정규화 키(명칭) 검색
        for key, original_name in sorted(_SNAPSHOT_LAW_NAMES.items()):
            if kw in key or kw in original_name:
                results.append({
                    "matched_field": "법령명",
                    "law_name": original_name,
                    "normalized_key": key,
                })

        # 2) 별칭 검색
        for alias, key in sorted(_SNAPSHOT_ALIASES.items()):
            if kw in alias:
                original_name = _SNAPSHOT_LAW_NAMES.get(key, alias)
                if not any(r["normalized_key"] == key for r in results):
                    results.append({
                        "matched_field": "별칭",
                        "law_name": original_name,
                        "normalized_key": key,
                        "alias": alias,
                    })

        # 중복 제거 (normalized_key 기준)
        seen_keys: set = set()
        deduped: List[Dict[str, Any]] = []
        for r in results:
            if r["normalized_key"] not in seen_keys:
                seen_keys.add(r["normalized_key"])
                deduped.append(r)

        return {
            "ok": True,
            "keyword": keyword,
            "count": len(deduped),
            "results": deduped,
        }


# ── CLI (stdio MCP 서버로 실행) ─────────────────────────────────────────────────

def main() -> None:
    server = LawRegistryServer()
    server.run()


if __name__ == "__main__":
    main()
