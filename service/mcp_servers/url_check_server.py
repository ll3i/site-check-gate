#!/usr/bin/env python3
"""
url_check_server.py — MCP 서버: URL 상태 확인 (HEAD/GET, 리다이렉트 체인).

Tools:
  check_url(url):
    주어진 URL에 HEAD 요청 후 필요시 GET으로 follow하여
    상태코드, 리다이렉트 체인, 최종 URL을 반환한다.

공통 설정:
  - User-Agent: mabc-2026-public/1.0 asdf4596@hanyang.ac.kr
  - 호출 간 0.5초 예의 지연
  - 결과에 source URL(검사 대상) 포함
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from _base import MCPServer, MCPError, JSON_RPC_METHOD_NOT_FOUND, JSON_RPC_INTERNAL_ERROR


# ── 공통 설정 ──────────────────────────────────────────────────────────────────

PROJECT_USER_AGENT = "mabc-2026-public/1.0 (contact: asdf4596@hanyang.ac.kr)"
COURTESY_DELAY = 0.5  # 초


class URLCheckServer(MCPServer):
    """URL 상태 확인 MCP 서버."""

    SERVER_NAME = "url-check"
    SERVER_VERSION = "0.1.0"

    TOOL_SCHEMAS = [
        {
            "name": "check_url",
            "description": (
                "URL에 HEAD 요청을 보내고, 리다이렉트가 있으면 따라가며 "
                "상태코드, 리다이렉트 체인, 최종 URL을 반환한다."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "확인할 URL",
                    },
                },
                "required": ["url"],
            },
        },
    ]

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        known = {s.get("name") for s in self.TOOL_SCHEMAS if isinstance(s, dict)}
        if name not in known:
            raise MCPError(JSON_RPC_METHOD_NOT_FOUND, f"지원하지 않는 도구: {name!r}")
        return self.check_url(arguments.get("url", ""))

    def check_url(self, url: str) -> Dict[str, Any]:
        """URL 검사: HEAD → 리다이렉트 추적 → 최종 정보 반환."""
        url = url.strip()
        if not url:
            return {
                "url": "",
                "status_code": None,
                "redirect_chain": [],
                "final_url": "",
                "error": "URL이 입력되지 않았습니다.",
            }

        # HEAD 요청으로 시작 (리다이렉트 무follow)
        head_result = self._head_request(url)
        if head_result is None:
            return {
                "url": url,
                "status_code": None,
                "redirect_chain": [],
                "final_url": url,
                "error": "HEAD 요청 실패 (서버 unreachable 또는 오류)",
            }

        status_code = head_result.get("status_code")
        redirect_url = head_result.get("redirect_url")
        redirect_chain: List[Dict[str, Any]] = []

        # HEAD가 리다이렉트를 반환하면 그 체인을 따라감
        current_url = url
        if redirect_url:
            redirect_chain.append({
                "from": current_url,
                "to": redirect_url,
                "status_code": status_code,
            })
            current_url = redirect_url

        # GET으로 최종 URL에 접근 (리다이렉트 follow=True)
        get_result = self._get_follow(url, max_redirects=10)
        if get_result is None:
            return {
                "url": url,
                "status_code": status_code,
                "redirect_chain": redirect_chain,
                "final_url": current_url,
                "error": "GET 최종 요청 실패",
            }

        # GET에서 추적된 리다이렉트 체인 추가
        get_chain = get_result.get("redirect_chain", [])
        # 중복 제거: 이미 redirect_chain에 있는 from→to가 get_chain에 있으면 스킵
        existing_pairs = {(e["from"], e["to"]) for e in redirect_chain}
        for step in get_chain:
            pair = (step.get("from", ""), step.get("to", ""))
            if pair not in existing_pairs:
                redirect_chain.append(step)
                existing_pairs.add(pair)

        # 최종 상태코드 (GET 결과)
        final_status = get_result.get("status_code")
        if final_status is not None:
            status_code = final_status

        final_url = get_result.get("final_url", current_url)
        error = get_result.get("error")

        return {
            "url": url,
            "status_code": status_code,
            "redirect_chain": redirect_chain,
            "final_url": final_url,
            "error": error,
            "content_type": get_result.get("content_type"),
            "content_length": get_result.get("content_length"),
        }

    # ── HEAD 요청 (리다이렉트 무follow) ────────────────────────────────────────

    def _head_request(self, url: str) -> Optional[Dict[str, Any]]:
        """HEAD 요청 → 상태코드, 리다이렉트 위치 반환."""
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={
                "User-Agent": PROJECT_USER_AGENT,
                "Accept": "*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return {
                    "status_code": resp.status,
                    "redirect_url": None,
                }
        except urllib.error.HTTPError as e:
            location = e.headers.get("Location", "")
            return {
                "status_code": e.code,
                "redirect_url": location if location else None,
            }
        except urllib.error.URLError as e:
            sys.stderr.write(f"[url_check] HEAD URL 오류: {e.reason}\n")
            return None
        except Exception as e:
            sys.stderr.write(f"[url_check] HEAD 오류: {e}\n")
            return None

    # ── GET 요청 (리다이렉트 follow) ──────────────────────────────────────────

    def _get_follow(self, url: str, max_redirects: int = 10) -> Optional[Dict[str, Any]]:
        """GET 요청, 리다이렉트 최대 max_redirects번까지 따라감."""
        redirect_chain: List[Dict[str, Any]] = []
        current_url = url
        last_status = None
        content_type = None
        content_length = None
        error = None

        for _ in range(max_redirects + 1):
            req = urllib.request.Request(
                current_url,
                method="GET",
                headers={
                    "User-Agent": PROJECT_USER_AGENT,
                    "Accept": "*/*",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    last_status = resp.status
                    content_type = resp.headers.get("Content-Type", "")
                    content_length = resp.headers.get("Content-Length")
                    final_url = resp.url  # 최종 URL (urllib이 추적 후 반환)

                    # urllib은 기본적으로 301/302/303/307/308을 자동 follow
                    # 우리가 별도로 추적한 체인만 사용
                    return {
                        "status_code": last_status,
                        "final_url": final_url,
                        "redirect_chain": redirect_chain,
                        "content_type": content_type,
                        "content_length": content_length,
                        "error": None,
                    }

            except urllib.error.HTTPError as e:
                last_status = e.code
                location = e.headers.get("Location", "")
                if location and e.code in (301, 302, 303, 307, 308):
                    redirect_chain.append({
                        "from": current_url,
                        "to": location,
                        "status_code": e.code,
                    })
                    current_url = urllib.parse.urljoin(current_url, location)
                    time.sleep(COURTESY_DELAY)
                    continue
                else:
                    # 리다이렉트가 아닌 오류
                    return {
                        "status_code": last_status,
                        "final_url": current_url,
                        "redirect_chain": redirect_chain,
                        "content_type": e.headers.get("Content-Type", ""),
                        "content_length": e.headers.get("Content-Length"),
                        "error": f"HTTP 오류 {e.code}",
                    }
            except urllib.error.URLError as e:
                error = f"연결 오류: {e.reason}"
                sys.stderr.write(f"[url_check] GET URL 오류: {e.reason}\n")
                break
            except Exception as e:
                error = f"오류: {e}"
                sys.stderr.write(f"[url_check] GET 오류: {e}\n")
                break

        return {
            "status_code": last_status,
            "final_url": current_url,
            "redirect_chain": redirect_chain,
            "content_type": content_type,
            "content_length": content_length,
            "error": error,
        }


def main() -> None:
    server = URLCheckServer()
    server.run()


if __name__ == "__main__":
    main()
