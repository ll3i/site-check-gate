#!/usr/bin/env python3
"""
photo_inspect_server.py — MCP photo_inspect 서버.

tool:
  - detect_objects(image_path, domain): service/core/photo_detect.py 의
    detect_objects 를 재사용하여 YOLO 객체 검출 결과를 반환한다.

 ultralytics 가 설치되지 않은 환경에서도 서버 자체는 정상 기동하며,
 tools/call 시점에 명확한 오류 JSON 을 반환한다 (서버 크래시 없음).
"""

import json
import sys
import os
from typing import Any, Dict, List

# 동일 패키지 내 베이스 import (절대 import + sys.path 확보)
import sys as _sys
import os as _os
_base_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _base_dir not in _sys.path:
    _sys.path.insert(0, _base_dir)

from service.mcp_servers._base import MCPServer, MCPError

# ── photo_detect 재사용 ──────────────────────────────────────────────────────────
from service.core.photo_detect import detect_objects


# ── MCP 서버 정의 ───────────────────────────────────────────────────────────────

class PhotoInspectServer(MCPServer):
    """photo_inspect MCP 서버 — YOLO 객체 검출 (판정 없음)."""

    SERVER_NAME = "photo_inspect"
    SERVER_VERSION = "1.0.0"

    TOOL_SCHEMAS = [
        {
            "name": "detect_objects",
            "description": (
                "이미지 파일에서 YOLO 객체 검출을 수행한다. "
                "service/core/photo_detect.py 의 detect_objects 를 재사용. "
                "domain은 'defect' | 'gauge' | 'cleaning' 중 하나여야 한다. "
                "ultralytics가 설치되지 않았으면 명확한 오류 JSON을 반환한다."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "추론할 이미지 파일 경로",
                    },
                    "domain": {
                        "type": "string",
                        "description": (
                            "가중치 도메인: 'defect' | 'gauge' | 'cleaning'. "
                            "미지정 또는 허용되지 않은 도메인이면 오류."
                        ),
                    },
                },
                "required": ["image_path", "domain"],
            },
        },
    ]

    # ── 도구 핸들러 ──────────────────────────────────────────────────────────

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "detect_objects":
            return self._handle_detect_objects(arguments)
        else:
            known = {s.get("name") for s in self.TOOL_SCHEMAS if isinstance(s, dict)}
            raise MCPError(
                MCPError.JSON_RPC_METHOD_NOT_FOUND,
                f"지원하지 않는 도구: {name!r}. 사용 가능: {sorted(known)}",
            )

    def _handle_detect_objects(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """detect_objects 도구 호출 핸들러.

        ultralytics 미설치 환경에서도 서버 자체는 살아있으며,
        이 핸들러에서 ImportError 를 잡아 명확한 오류 JSON을 반환한다.
        """
        image_path = args.get("image_path")
        domain = args.get("domain")

        if not isinstance(image_path, str) or not image_path.strip():
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "image_path (str, nonempty)가 필요",
            )
        if not isinstance(domain, str) or not domain.strip():
            raise MCPError(
                MCPError.JSON_RPC_INVALID_PARAMS,
                "domain (str, nonempty)가 필요. 'defect' | 'gauge' | 'cleaning'",
            )

        # photo_detect.detect_objects 호출 — 내부에서 domain 검증, 경로 검증,
        # ultralytics 지연 임포트를 수행한다.
        try:
            result = detect_objects(image_path.strip(), domain.strip())
        except ImportError as exc:
            # ultralytics 미설치 → 명확한 오류 JSON 반환 (서버는 살아있음)
            return {
                "ok": False,
                "error": {
                    "type": "ImportError",
                    "message": str(exc),
                    "detail": (
                        "비전 모듈(ultralytics)이 설치되지 않았습니다. "
                        "pip install ultralytics 로 설치한 후 다시 시도하세요."
                    ),
                },
                "detections": [],
            }
        except ValueError as exc:
            return {
                "ok": False,
                "error": {
                    "type": "ValueError",
                    "message": str(exc),
                },
                "detections": [],
            }
        except FileNotFoundError as exc:
            return {
                "ok": False,
                "error": {
                    "type": "FileNotFoundError",
                    "message": str(exc),
                },
                "detections": [],
            }
        except Exception as exc:
            # 예상치 못한 오류도 서버가 죽지 않고 오류 JSON 반환
            return {
                "ok": False,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                "detections": [],
            }

        return {
            "ok": True,
            "image_path": image_path.strip(),
            "domain": domain.strip(),
            "detections": result,
        }


# ── CLI (stdio MCP 서버로 실행) ─────────────────────────────────────────────────

def main() -> None:
    server = PhotoInspectServer()
    server.run()


if __name__ == "__main__":
    main()
