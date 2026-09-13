#!/usr/bin/env python3
"""
doc_parse_server.py — MCP 서버: 문서 파싱 (Upstage Document Parse API).

Tools:
  parse_document(file_path):
    service.core.docparse_client.call_document_parse을 재사용하여
    파일을 Upstage Document Parse API로 전송하고 응답 JSON을 반환한다.
    API 키는 환경변수 UPSTAGE_API_KEY → ~/.upstage/.env 폴백.

공통 설정:
  - User-Agent: mabc-2026-public/1.0 asdf4596@hanyang.ac.kr
  - 호출 간 0.5초 예의 지연 (API 호출 전)
  - 결과에 source URL(API 엔드포인트) 포함
"""

import json
import sys
import time
from typing import Any, Dict, Optional

from _base import MCPServer, MCPError, JSON_RPC_METHOD_NOT_FOUND, JSON_RPC_INTERNAL_ERROR

# 레포 루트를 sys.path에 추가 (service.core 등 절대 임포트용)
import sys as _sys
import os as _os
_repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _repo_root not in _sys.path:
    _sys.path.insert(0, _repo_root)

from service.core.docparse_client import call_document_parse, API_URL


# ── 공통 설정 ──────────────────────────────────────────────────────────────────

PROJECT_USER_AGENT = "mabc-2026-public/1.0 (contact: asdf4596@hanyang.ac.kr)"
COURTESY_DELAY = 0.5  # 초


class DocParseServer(MCPServer):
    """문서 파싱 MCP 서버 (Upstage Document Parse API)."""

    SERVER_NAME = "doc-parse"
    SERVER_VERSION = "0.1.0"

    TOOL_SCHEMAS = [
        {
            "name": "parse_document",
            "description": (
                "파일을 Upstage Document Parse API로 전송하여 파싱한다. "
                "API 키는 환경변수 UPSTAGE_API_KEY → ~/.upstage/.env 순으로 로드한다. "
                "동일한 파일은 캐시되어 재호출되지 않는다."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "파싱할 파일 경로",
                    },
                },
                "required": ["file_path"],
            },
        },
    ]

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        known = {s.get("name") for s in self.TOOL_SCHEMAS if isinstance(s, dict)}
        if name not in known:
            raise MCPError(JSON_RPC_METHOD_NOT_FOUND, f"지원하지 않는 도구: {name!r}")
        return self.parse_document(arguments.get("file_path", ""))

    def parse_document(self, file_path: str) -> Dict[str, Any]:
        """파일 파싱: call_document_parse 재사용."""
        file_path = file_path.strip()
        if not file_path:
            return {
                "file_path": "",
                "parsed": False,
                "error": "파일 경로가 입력되지 않았습니다.",
                "source_url": API_URL,
            }

        # 예의 지연
        time.sleep(COURTESY_DELAY)

        try:
            result = call_document_parse(file_path)
        except EnvironmentError as e:
            return {
                "file_path": file_path,
                "parsed": False,
                "error": f"API 키 없음: {e}",
                "source_url": API_URL,
            }
        except RuntimeError as e:
            return {
                "file_path": file_path,
                "parsed": False,
                "error": f"API 오류: {e}",
                "source_url": API_URL,
            }
        except FileNotFoundError:
            return {
                "file_path": file_path,
                "parsed": False,
                "error": f"파일을 찾을 수 없음: {file_path}",
                "source_url": API_URL,
            }
        except Exception as e:
            return {
                "file_path": file_path,
                "parsed": False,
                "error": f"예상치 못한 오류: {type(e).__name__}: {e}",
                "source_url": API_URL,
            }

        return {
            "file_path": file_path,
            "parsed": True,
            "result": result,
            "source_url": API_URL,
            "error": None,
        }


def main() -> None:
    server = DocParseServer()
    server.run()


if __name__ == "__main__":
    main()
