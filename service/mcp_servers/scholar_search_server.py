#!/usr/bin/env python3
"""
scholar_search_server.py — MCP 서버: 논문 검색 (arXiv + Crossref).

Tools:
  search_papers(query, max_results=5):
    arXiv API (http://export.arxiv.org/api/query) 와
    Crossref works?query=<query> 에서 후보를 모아 반환한다.
    각 항목: title, authors, year, doi, abstract, source (arXiv / Crossref)

공통 설정:
  - 무키 공개 API (키 불필요)
  - User-Agent: mabc-2026-public/1.0 asdf4596@hanyang.ac.kr
  - 호출 간 0.5초 예의 지연
  - 결과에 source URL(역링크) 포함
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from _base import MCPServer, MCPError, JSON_RPC_INTERNAL_ERROR


# ── 공통 설정 ──────────────────────────────────────────────────────────────────

PROJECT_USER_AGENT = "mabc-2026-public/1.0 (contact: asdf4596@hanyang.ac.kr)"
ARXIV_API = "http://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works"
COURTESY_DELAY = 0.5  # 초, 호출 간 예의 지연


# ── 서버 정의 ───────────────────────────────────────────────────────────────────

class ScholarSearchServer(MCPServer):
    """논문 검색 MCP 서버 (arXiv + Crossref)."""

    SERVER_NAME = "scholar-search"
    SERVER_VERSION = "0.1.0"

    TOOL_SCHEMAS = [
        {
            "name": "search_papers",
            "description": (
                "arXiv API와 Crossref에서 논문을 검색한다. "
                "query 문자열로 검색, max_results로 결과 수를 제한한다. "
                "각 결과는 title, authors, year, doi, abstract, source(arXiv/Crossref), source_url을 포함한다."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "검색 쿼리",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "반환할 최대 결과 수 (기본 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    ]

    def handle_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        known = {s.get("name") for s in self.TOOL_SCHEMAS if isinstance(s, dict)}
        if name not in known:
            raise MCPError(JSON_RPC_METHOD_NOT_FOUND, f"지원하지 않는 도구: {name!r}")
        return self.search_papers(
            arguments.get("query", ""),
            arguments.get("max_results", 5),
        )

    def search_papers(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """query로 arXiv + Crossref에서 논문을 검색하고 결과를 합친다."""
        results: Dict[str, Dict[str, Any]] = {}  # doi 기준 중복 제거

        # 1) arXiv 검색
        arxiv_results = self._search_arxiv(query, max_results)
        for item in arxiv_results:
            doi = item.get("doi")
            if doi:
                results[doi] = item
            else:
                # arXiv ID가 없는 경우 임의 키
                key = item.get("source_url") or f"arxiv:{item.get('title','')[:20]}"
                if key not in results:
                    results[key] = item

        # 2) Crossref 검색
        crossref_results = self._search_crossref(query, max_results)
        for item in crossref_results:
            doi = item.get("doi")
            if doi and doi not in results:
                results[doi] = item
            elif not doi:
                key = item.get("source_url") or f"crossref:{item.get('title','')[:20]}"
                if key not in results:
                    results[key] = item

        # 합치기: 최대 max_results까지만
        merged = list(results.values())
        if len(merged) > max_results:
            merged = merged[:max_results]

        # source_url 포함 확인
        for item in merged:
            if "source_url" not in item:
                item["source_url"] = ""

        return merged

    # ── arXiv ──────────────────────────────────────────────────────────────────

    def _search_arxiv(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """arXiv API에서 논문 검색."""
        params = urllib.parse.urlencode({
            "search_query": f"all:{urllib.parse.quote(query)}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        })
        url = f"{ARXIV_API}?{params}"
        raw = self._fetch(url, cooldown=False)
        if raw is None:
            return []

        entries = self._parse_arxiv_xml(raw)
        results: List[Dict[str, Any]] = []
        for e in entries[:max_results]:
            item = {
                "title": e.get("title", ""),
                "authors": e.get("authors", []),
                "year": e.get("year"),
                "doi": e.get("doi"),
                "abstract": e.get("abstract", ""),
                "source": "arXiv",
                "source_url": e.get("arxiv_url", ""),
            }
            results.append(item)
        return results

    def _parse_arxiv_xml(self, xml: str) -> List[Dict[str, Any]]:
        """arXiv XML 응답을 파싱하여 항목 리스트로 변환."""
        import xml.etree.ElementTree as ET

        namespace = {"atom": "http://www.w3.org/2005/Atom",
                     "arxiv": "http://arxiv.org/schemas/atom"}

        root = ET.fromstring(xml)
        entries = root.findall("atom:entry", namespace)
        results: List[Dict[str, Any]] = []

        for entry in entries:
            title_el = entry.find("atom:title", namespace)
            title = title_el.text.strip() if title_el is not None and title_el.text else ""

            author_names: List[str] = []
            for author_el in entry.findall("atom:author", namespace):
                name_el = author_el.find("atom:name", namespace)
                if name_el is not None and name_el.text:
                    author_names.append(name_el.text.strip())

            abstract_el = entry.find("atom:summary", namespace)
            abstract = abstract_el.text.strip() if abstract_el is not None and abstract_el.text else ""

            url_el = entry.find("atom:link", namespace)
            arxiv_url = url_el.get("href", "") if url_el is not None else ""

            # DOI 추출 (링크 rel="doi" 또는 arXiv 주석)
            doi = None
            for link_el in entry.findall("atom:link", namespace):
                if link_el.get("rel") == "doi":
                    doi = link_el.get("href", "").strip()
                    break
            if not doi:
                # arXiv ID에서 DOI 변환 시도 (일부 저널)
                arxiv_id = self._extract_arxiv_id(arxiv_url)
                if arxiv_id:
                    # 일부 arXiv 논문은 DOI가 있음 — 링크에서 찾기
                    pass

            # year 추출 (published 날짜에서)
            published_el = entry.find("atom:published", namespace)
            year = None
            if published_el is not None and published_el.text:
                try:
                    year = int(published_el.text[:4])
                except (ValueError, IndexError):
                    year = None

            results.append({
                "title": title,
                "authors": author_names,
                "year": year,
                "doi": doi,
                "abstract": abstract,
                "source": "arXiv",
                "arxiv_url": arxiv_url,
            })

        return results

    def _extract_arxiv_id(self, url: str) -> Optional[str]:
        """arXiv URL에서 ID 추출."""
        if not url:
            return None
        m = re.search(r"/abs/(\d{4}\.\d{4,5})", url)
        if m:
            return m.group(1)
        return None

    # ── Crossref ────────────────────────────────────────────────────────────────

    def _search_crossref(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Crossref works?query API에서 논문 검색."""
        params = urllib.parse.urlencode({
            "query": query,
            "rows": max_results,
            "select": "title,author,issued,DOI,abstract,URL",
        })
        url = f"{CROSSREF_API}?{params}"
        raw = self._fetch(url, cooldown=False)
        if raw is None:
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        messages = data.get("message", {})
        items = messages.get("items", [])
        results: List[Dict[str, Any]] = []

        for item in items[:max_results]:
            title_list = item.get("title", [])
            title = title_list[0] if title_list else ""

            authors = []
            for author in item.get("author", []):
                given = author.get("given", "")
                family = author.get("family", "")
                name = f"{given} {family}".strip()
                if name:
                    authors.append(name)

            # year
            issued = item.get("issued", {})
            raw_date = issued.get("raw", "")
            year = None
            if raw_date:
                try:
                    year = int(raw_date[:4])
                except (ValueError, IndexError):
                    pass
            if year is None and "issued" in item:
                try:
                    year = int(item["issued"].get("date-parts", [[None]])[0][0])
                except (IndexError, TypeError, ValueError):
                    pass

            doi = item.get("DOI", "")
            abstract = ""
            abs_list = item.get("abstract", "")
            if isinstance(abs_list, str) and abs_list:
                # Crossref abstract는 때로 HTML 포함
                abstract = re.sub(r"<[^>]+>", "", abs_list).strip()
            elif isinstance(abs_list, list):
                abstract = abs_list[0] if abs_list else ""

            source_url = item.get("URL", "")

            results.append({
                "title": title,
                "authors": authors,
                "year": year,
                "doi": doi,
                "abstract": abstract,
                "source": "Crossref",
                "source_url": source_url,
            })

        return results

    # ── 공통 fetch (User-Agent, 지연, 오류 처리) ────────────────────────────────

    def _fetch(self, url: str, cooldown: bool = True) -> Optional[str]:
        """HTTP GET 요청 → 응답 본문 string 또는 None (오류)."""
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": PROJECT_USER_AGENT,
                "Accept": "application/json, application/xml, text/xml, */*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                # UTF-8 우선, 실패 시 latin-1
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")
                if cooldown:
                    time.sleep(COURTESY_DELAY)
                return text
        except urllib.error.HTTPError as e:
            # 404 등: 빈 결과 반환 (오류 로깅만)
            sys.stderr.write(f"[scholar_search] HTTP {e.code} for {url}\n")
            if cooldown:
                time.sleep(COURTESY_DELAY)
            return None
        except urllib.error.URLError as e:
            sys.stderr.write(f"[scholar_search] URL 오류: {e.reason}\n")
            if cooldown:
                time.sleep(COURTESY_DELAY)
            return None
        except Exception as e:
            sys.stderr.write(f"[scholar_search] 오류: {e}\n")
            if cooldown:
                time.sleep(COURTESY_DELAY)
            return None


# ── 메인 ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    server = ScholarSearchServer()
    server.run()


if __name__ == "__main__":
    main()
