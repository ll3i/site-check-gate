#!/usr/bin/env python3
"""
retraction_check_server.py — MCP 서버: 논문 철회 여부 확인 (Crossref).

Tools:
  check_retraction(doi):
    Crossref works/{doi} API에서 update-to, retraction 관련 필드를 확인하여
    철회(retraction) 여부를 판별한다.

공통 설정:
  - 무키 공개 API (Crossref는 무키로도 제한적 사용 가능)
  - User-Agent: mabc-2026-public/1.0 asdf4596@hanyang.ac.kr
  - 호출 간 0.5초 예의 지연
  - 결과에 source URL 포함
"""

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from _base import MCPServer, MCPError, JSON_RPC_METHOD_NOT_FOUND, JSON_RPC_INTERNAL_ERROR


# ── 공통 설정 ──────────────────────────────────────────────────────────────────

PROJECT_USER_AGENT = "mabc-2026-public/1.0 (contact: asdf4596@hanyang.ac.kr)"
CROSSREF_WORK_URL = "https://api.crossref.org/works"
COURTESY_DELAY = 0.5  # 초


class RetractionCheckServer(MCPServer):
    """논문 철회 여부 확인 MCP 서버 (Crossref)."""

    SERVER_NAME = "retraction-check"
    SERVER_VERSION = "0.1.0"

    TOOL_SCHEMAS = [
        {
            "name": "check_retraction",
            "description": (
                "Crossref API로 DOI 논문의 철회(retraction) 여부를 확인한다. "
                "update-to 필드에 retraction 타입이 있는지 검사한다."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "doi": {
                        "type": "string",
                        "description": "확인할 DOI (예: 10.1000/xyz123)",
                    },
                },
                "required": ["doi"],
            },
        },
    ]

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        known = {s.get("name") for s in self.TOOL_SCHEMAS if isinstance(s, dict)}
        if name not in known:
            raise MCPError(JSON_RPC_METHOD_NOT_FOUND, f"지원하지 않는 도구: {name!r}")
        return self.check_retraction(arguments.get("doi", ""))

    def check_retraction(self, doi: str) -> Dict[str, Any]:
        """DOI 논문의 철회 여부를 Crossref API로 확인한다."""
        doi = doi.strip()
        if not doi:
            return {
                "doi": "",
                "retracted": False,
                "error": "DOI가 입력되지 않았습니다.",
                "source_url": "",
            }

        url = f"{CROSSREF_WORK_URL}/{urllib.request.quote(doi, safe='')}"
        raw = self._fetch(url, cooldown=True)
        if raw is None:
            return {
                "doi": doi,
                "retracted": False,
                "error": "Crossref API 호출 실패",
                "source_url": url,
            }

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {
                "doi": doi,
                "retracted": False,
                "error": "응답이 JSON이 아닙니다.",
                "source_url": url,
            }

        message = data.get("message", {})

        # 철회 여부 판별
        is_retracted = False
        retraction_reason = ""
        retraction_date = None
        update_to_info = None

        # Crossref Retraction Watch 데이터:
        # message["update-to"] 리스트 안에 type="retraction" 항목이 있는지 확인
        update_to_list = message.get("update-to", [])
        if isinstance(update_to_list, list):
            for update_to in update_to_list:
                update_type = update_to.get("type", "").lower()
                if "retraction" in update_type or "withdrawal" in update_type:
                    is_retracted = True
                    update_to_info = update_to
                    # retraction 쪽 metadata 찾기
                    retraction_meta = update_to.get("mr:record", {})
                    if isinstance(retraction_meta, dict):
                        # retraction 날짜
                        rd = retraction_meta.get("issued", {})
                        if isinstance(rd, dict):
                            date_parts = rd.get("date-parts", [])
                            if date_parts and date_parts[0]:
                                retraction_date = date_parts[0][0]
                        # 사유
                        retraction_reason = retraction_meta.get("URL", "")
                    break

        # Crossref의 것은 "is-retracted" 플래그도 있을 수 있음 (실험적)
        if message.get("is-retracted"):
            is_retracted = True

        # source_url
        source_url = message.get("URL", url)

        return {
            "doi": doi,
            "retracted": is_retracted,
            "retraction_reason": retraction_reason,
            "retraction_date": retraction_date,
            "update_to": update_to_info,
            "source_url": source_url,
            "error": None,
        }

    # ── fetch ───────────────────────────────────────────────────────────────────

    def _fetch(self, url: str, cooldown: bool = True) -> Optional[str]:
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
                if cooldown:
                    time.sleep(COURTESY_DELAY)
                return text
        except urllib.error.HTTPError as e:
            sys.stderr.write(f"[retraction_check] HTTP {e.code} for {url}\n")
            if cooldown:
                time.sleep(COURTESY_DELAY)
            return None
        except urllib.error.URLError as e:
            sys.stderr.write(f"[retraction_check] URL 오류: {e.reason}\n")
            if cooldown:
                time.sleep(COURTESY_DELAY)
            return None
        except Exception as e:
            sys.stderr.write(f"[retraction_check] 오류: {e}\n")
            if cooldown:
                time.sleep(COURTESY_DELAY)
            return None


def main() -> None:
    server = RetractionCheckServer()
    server.run()


if __name__ == "__main__":
    main()
