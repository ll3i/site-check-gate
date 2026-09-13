#!/usr/bin/env python3
"""
wayback_server.py — MCP 서버: archive.org Wayback Machine 스냅샷 검색.

Tools:
  find_snapshot(url):
    archive.org availability API에 질의하여 가장 가까운/최신 스냅샷 URL과 시각을 반환.

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
from typing import Any, Dict, Optional

from _base import MCPServer, MCPError, JSON_RPC_METHOD_NOT_FOUND, JSON_RPC_INTERNAL_ERROR


# ── 공통 설정 ──────────────────────────────────────────────────────────────────

PROJECT_USER_AGENT = "mabc-2026-public/1.0 (contact: asdf4596@hanyang.ac.kr)"
WAYBACK_AVAIL_API = "https://archive.org/wayback/available"
COURTESY_DELAY = 0.5  # 초


class WaybackServer(MCPServer):
    """archive.org Wayback Machine 스냅샷 검색 MCP 서버."""

    SERVER_NAME = "wayback-check"
    SERVER_VERSION = "0.1.0"

    TOOL_SCHEMAS = [
        {
            "name": "find_snapshot",
            "description": (
                "archive.org Wayback Machine availability API로 "
                "주어진 URL의 가장 가까운/최신 스냅샷 URL과 포획 시각을 반환한다."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "스냅샷을 찾을 URL",
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
        return self.find_snapshot(arguments.get("url", ""))

    def find_snapshot(self, url: str) -> Dict[str, Any]:
        """archive.org availability API로 스냅샷 검색."""
        url = url.strip()
        if not url:
            return {
                "url": "",
                "snapshot_url": None,
                "timestamp": None,
                "available": False,
                "error": "URL이 입력되지 않았습니다.",
            }

        params = urllib.parse.urlencode({"url": url})
        api_url = f"{WAYBACK_AVAIL_API}?{params}"
        raw = self._fetch(api_url)
        if raw is None:
            return {
                "url": url,
                "snapshot_url": None,
                "timestamp": None,
                "available": False,
                "error": "availability API 호출 실패",
                "source_url": api_url,
            }

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {
                "url": url,
                "snapshot_url": None,
                "timestamp": None,
                "available": False,
                "error": "응답이 JSON이 아닙니다.",
                "source_url": api_url,
            }

        # availability API 응답 예시:
        # {"url": "http://example.com", "archived_snapshots": {"closest": {"available": true, "url": "...", "timestamp": "...", "status": "200", "closest": {"available": true, "url": "http://web.archive.org/web/20200101000000/http://example.com", "timestamp": "20200101000000", "status": "200"}}}}
        archived = data.get("archived_snapshots", {})
        if not isinstance(archived, dict):
            return {
                "url": url,
                "snapshot_url": None,
                "timestamp": None,
                "available": False,
                "error": "archived_snapshots 구조가 이상함",
                "source_url": api_url,
            }

        closest = archived.get("closest", {})
        if not isinstance(closest, dict):
            return {
                "url": url,
                "snapshot_url": None,
                "timestamp": None,
                "available": False,
                "error": "closest 스냅샷 정보 없음",
                "source_url": api_url,
            }

        available = closest.get("available", False)
        snapshot_url = closest.get("url", "")
        timestamp = closest.get("timestamp", "")
        status_code = closest.get("status", "")

        return {
            "url": url,
            "snapshot_url": snapshot_url if available else None,
            "timestamp": timestamp if available else None,
            "available": available,
            "status_code": status_code if available else None,
            "source_url": api_url,
            "error": None,
        }

    # ── fetch ───────────────────────────────────────────────────────────────────

    def _fetch(self, url: str) -> Optional[str]:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": PROJECT_USER_AGENT,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")
                time.sleep(COURTESY_DELAY)
                return text
        except urllib.error.HTTPError as e:
            sys.stderr.write(f"[wayback] HTTP {e.code} for {url}\n")
            time.sleep(COURTESY_DELAY)
            return None
        except urllib.error.URLError as e:
            sys.stderr.write(f"[wayback] URL 오류: {e.reason}\n")
            time.sleep(COURTESY_DELAY)
            return None
        except Exception as e:
            sys.stderr.write(f"[wayback] 오류: {e}\n")
            time.sleep(COURTESY_DELAY)
            return None


def main() -> None:
    server = WaybackServer()
    server.run()


if __name__ == "__main__":
    main()
