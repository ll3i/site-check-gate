#!/usr/bin/env python3
"""
_mcp_base.py — stdio JSON-RPC 2.0 MCP 서버 베이스.

서브클래스는 다음만 구현한다:
  - TOOL_SCHEMAS: list[dict] — tools/list 응답용 도구 목록
  - handle_tool(name, args): 도구 호출 핸들러

그 외 initialize / tools/list / tools/call / notifications 는
모두 베이스가 처리한다. 표준 라이브러리만 사용한다.
"""
import json
import sys
import os
from typing import Any, Callable, Dict, List, Optional


class MCPError(Exception):
    """MCP 프로토콜 오류 (코드 + 메시지)."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d


# JSON-RPC 2.0 오류 코드 (발생한 오류는 Base가 자동 변환하지 않고 그대로 전달)
JSON_RPC_PARSE_ERROR = -32700
JSON_RPC_INVALID_REQUEST = -32600
JSON_RPC_METHOD_NOT_FOUND = -32601
JSON_RPC_INVALID_PARAMS = -32602
JSON_RPC_INTERNAL_ERROR = -32603

# MCP 프로토콜 오류 코드 (MCP 2024-11 초기 스펙 기준)
MCP_INVALID_PARAMS = -32602


class MCPServer:
    """stdio JSON-RPC 2.0 MCP 서버 베이스.

    서브클래스는:
      - TOOL_SCHEMAS (list[dict]) — tools/list 응답
      - handle_tool(name: str, args: dict) -> Any — 도구 호출
      - server_info() -> dict (선택) — initialize 응답의 serverInfo
      - protocol_version() -> str (선택) — default "2024-11-05"
    """

    TOOL_SCHEMAS: List[Dict[str, Any]] = []
    PROTOCOL_VERSION = "2024-11-05"
    SERVER_NAME = "base-mcp-server"
    SERVER_VERSION = "0.1.0"

    def protocol_version(self) -> str:
        return getattr(self, "PROTOCOL_VERSION", "2024-11-05")

    def server_info(self) -> Dict[str, str]:
        return {
            "name": getattr(self, "SERVER_NAME", "base-mcp-server"),
            "version": getattr(self, "SERVER_VERSION", "0.1.0"),
        }

    # ── 프로토콜 디스패치 ────────────────────────────────────────────────────

    def dispatch(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """단일 JSON-RPC 2.0 요청을 처리하고 응답을 반환한다 (Notification이면 None).

        request 예시:
          {"jsonrpc": "2.0", "id": 1, "method": "tools/call", ...}
        """
        # 버전 확인
        if not isinstance(request, dict):
            raise MCPError(JSON_RPC_PARSE_ERROR, "Request must be a JSON object")

        req_jsonrpc = request.get("jsonrpc")
        if req_jsonrpc != "2.0":
            raise MCPError(
                JSON_RPC_INVALID_REQUEST,
                f"jsonrpc 필드 값이 '2.0'이 아님: {req_jsonrpc!r}",
            )

        method = request.get("method")
        if not isinstance(method, str) or not method:
            raise MCPError(
                JSON_RPC_INVALID_REQUEST,
                "method 필드가 없거나 문자열이 아님",
            )

        # 필수/선택 필드 유효성
        if "id" in request and not isinstance(request["id"], (str, int, float, type(None))):
            raise MCPError(
                JSON_RPC_INVALID_REQUEST,
                "id 필드는 문자열·숫자·Null이어야 함",
            )

        params = request.get("params")
        if params is not None and not isinstance(params, dict):
            raise MCPError(
                JSON_RPC_INVALID_PARAMS,
                "params는 object여야 함",
            )

        # method 라우팅
        if method == "initialize":
            return self.handle_initialize(request)
        elif method == "initialized":
            # 클라이언트가 보내는 notification — 응답은 없음
            return None
        elif method == "tools/list":
            return self.handle_tools_list(request)
        elif method == "tools/call":
            return self.handle_tools_call(request)
        elif method.startswith("notifications/"):
            # 모든 notification은 무응답
            return None
        else:
            raise MCPError(
                JSON_RPC_METHOD_NOT_FOUND,
                f"지원하지 않는 method: {method!r}",
            )

    # ── 개별 핸들러 ──────────────────────────────────────────────────────────

    def handle_initialize(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """initialize 요청 처리 → serverInfo, protocolVersion, capabilities 반환.

        params (선택):
          - protocolVersion (str): 클라이언트가 지원하는 버전
          - capabilities (object, 선택): 클라이언트 기능
          - clientInfo (object, 선택)
        """
        _ = request.get("params")
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "protocolVersion": self.protocol_version(),
                "serverInfo": self.server_info(),
                "capabilities": {
                    "tools": {
                        "listChanged": False,
                    },
                },
            },
        }

    def handle_tools_list(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """tools/list 요청 → TOOL_SCHEMAS 반환."""
        _ = request.get("params")
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "tools": list(self.TOOL_SCHEMAS),
            },
        }

    def handle_tools_call(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """tools/call 요청 → handle_tool(name, args) 호출 후 결과 반환.

        params:
          - name (str, 필수)
          - arguments (object, 필수)
        """
        params = request.get("params")
        if not isinstance(params, dict):
            raise MCPError(
                MCP_INVALID_PARAMS,
                "tools/call의 params는 object여야 함",
            )

        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise MCPError(
                MCP_INVALID_PARAMS,
                "params.name (str)이 필요",
            )

        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            raise MCPError(
                MCP_INVALID_PARAMS,
                "params.arguments (object)가 필요",
            )

        # 핸들러 호출
        try:
            result = self.handle_tool(name, arguments)
        except MCPError:
            raise
        except Exception as exc:
            raise MCPError(
                JSON_RPC_INTERNAL_ERROR,
                f"도구 '{name}' 실행 중 오류: {exc!s}",
                data={"error_type": type(exc).__name__},
            ) from exc

        # 응답이 이미 {"jsonrpc", "id"...} 형태면 그대로 반환,
        # 아니면 content 블록으로 래핑 (텍스트 내용)
        if isinstance(result, dict) and "jsonrpc" in result:
            return result

        # 일반 결과를 MCP content 블록으로 변환
        content_text = self._serialize_result(result)
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": content_text,
                    },
                ],
            },
        }

    # ── 결과 직렬화 ──────────────────────────────────────────────────────────

    def _serialize_result(self, result: Any) -> str:
        """핸들러 반환값을 텍스트로 직렬화한다.

        - str이면 그대로
        - dict/list 등 JSON 직렬화 가능이면 JSON
        - 그 외는 str() 폴백
        """
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(result)

    # ── 핸들러 오버라이드 지점 ───────────────────────────────────────────────

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """도구 호출 핸들러. 서브클래스에서 오버라이드한다.

        name이 TOOL_SCHEMAS에 없으면 NotImplementedError를 내며,
        베이스가 이를 MCP 오류로 변환한다.
        """
        known = {s.get("name") for s in self.TOOL_SCHEMAS if isinstance(s, dict)}
        if name not in known:
            raise MCPError(
                JSON_RPC_METHOD_NOT_FOUND,
                f"지원하지 않는 도구: {name!r}. "
                f"사용 가능: {sorted(known)}",
            )
        raise NotImplementedError(f"도구 '{name}'의 핸들러가 구현되지 않았습니다")

    # ── stdio 루프 ───────────────────────────────────────────────────────────

    def run(self) -> None:
        """stdio JSON-RPC 2.0 서버 메인 루프.

        stdin에서 줄 단위 JSON을 읽고, 처리 후 stdout에 응답을 쓴다.
        stderr는 로그 용도로만 사용.
        """
        # stdin/stdout을 항상 UTF-8로 설정 (Windows 기본 인코딩 문제 방지)
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            request: Dict[str, Any]
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                # 파싱 오류 → JSON-RPC 오류로 응답
                sys.stderr.write(f"[MCP] JSON 파싱 오류: {exc}\n")
                sys.stderr.flush()
                _write_response({
                    "jsonrpc": "2.0",
                    "id": None,  # 파싱 실패 시 id를 알 수 없음
                    "error": {
                        "code": JSON_RPC_PARSE_ERROR,
                        "message": f"JSON 파싱 실패: {exc!s}",
                    },
                })
                continue

            try:
                response = self.dispatch(request)
            except MCPError as exc:
                sys.stderr.write(f"[MCP] 오류 ({exc.code}): {exc.message}\n")
                sys.stderr.flush()
                id_val = request.get("id") if isinstance(request, dict) else None
                _write_response({
                    "jsonrpc": "2.0",
                    "id": id_val,
                    "error": exc.to_dict(),
                })
            else:
                if response is not None:
                    _write_response(response)
                # Notification (response is None) → 무응답

    def shutdown(self) -> None:
        """clean shutdown hook. 서브클래스에서 오버라이드 가능."""
        pass


# ── 응답 쓰기 헬퍼 ─────────────────────────────────────────────────────────────

def _write_response(response: Dict[str, Any]) -> None:
    """응답 dict 하나를 한 줄 JSON으로 stdout에 쓴다."""
    payload = json.dumps(response, ensure_ascii=False)
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()
