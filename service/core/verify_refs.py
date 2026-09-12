#!/usr/bin/env python3
"""
verify_refs.py — 파싱된 참고문헌 항목을 DOI/arXiv/Crossref/DataCite/arXiv API로 검증하고
JSON + Markdown 보고서를 생성한다.

사용법:
    python verify_refs.py work/refs.json [--json work/verify.json] [--md work/report.md]
        [--max 60] [--offline]

순수 표준 라이브러리만 사용 (urllib, json, re, difflib, xml.etree, time, sys, os).

판정 규칙(고정 문자열):
    ✅ 확인 / ⚠️ 부분일치 / ❌ 미확인 / ⛔ 확인불가 / ➖ 비대상
"""

import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET

# ── 상수 ──────────────────────────────────────────────────────────────────────
UA = "cite-check/1.0 (references verification)"   # 이메일 없는 User-Agent
DOI_HANDLE_BASE = "https://doi.org/api/handles"
CROSSREF_API = "https://api.crossref.org/works"
DATACITE_API = "https://api.datacite.org/dois"
ARXIV_API = "http://export.arxiv.org/api/query"
STATUS_MAP = {
    'verified':    '✅',
    'partial':     '⚠️',
    'unverified':  '❌',
    'unreachable': '⛔',
    'not_applicable': '➖',
}

# ── F4: 콘솔 출력 안전장치 ─────────────────────────────────────────────────────
def _safe_encode_for_console(text: str) -> str:
    """
    cp949(Code Page 949, 한국어 Windows 콘솔)에서 인코딩 불가능한 문자를
    ASCII 폴백 기호 또는 대체 문자로 치환한다.
    폴백 매핑:  ✅→[OK]  ⚠️→[WARN]  ❌→[X]  ⛔→[HOLD]  ➖→[SKIP]
    그 외 문자는 현재 콘솔 인코딩 기준으로 encode(errors='replace') 처리하여
    출력이 계속되게 한다. 파일 출력(UTF-8)에는 어떤 영향도 없다.
    """
    replacements = {
        '✅': '[OK]',
        '⚠️': '[WARN]',
        '❌': '[X]',
        '⛔': '[HOLD]',
        '➖': '[SKIP]',
    }
    result = text
    for emoji, ascii_fallback in replacements.items():
        result = result.replace(emoji, ascii_fallback)
    # 콘솔 인코딩 결정 (없으면 utf-8)
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        # 문자 단위 대체: 인코딩 불가능한 문자는 '?' 등으로 치환
        result = result.encode(encoding, errors='replace').decode(encoding)
    except (LookupError, UnicodeEncodeError, UnicodeDecodeError):
        # 인코딩을 알 수 없거나 처리 실패 시 ASCII 안전 버전으로 폴백
        result = result.encode('ascii', errors='replace').decode('ascii')
    return result

def safe_print(*args, **kwargs):
    """
    콘솔 출력 시 cp949 인코딩 실패를 방지하기 위해
    이모지를 ASCII 폴백으로 치환한 뒤 출력한다.
    파일 출력(UTF-8)에는 영향을 주지 않는다 — 파일 쓰기는 기존 코드 그대로.
    """
    text = ' '.join(str(a) for a in args)
    text = _safe_encode_for_console(text)
    print(text, **kwargs)

# ── HTTP 클라이언트 ────────────────────────────────────────────────────────────
def http_get(url, timeout=12, retries=1, sleep=0.35):
    """
    GET 요청. User-Agent 명시(이메일 없음).
    5xx/429 는 1회 재시도, 요청 간 sleep 대기.
    실패 시 (None, None) 반환.
    """
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                status_code = getattr(resp, 'status', None)
                if status_code == 200 or (status_code is None and resp.status == 200):
                    time.sleep(sleep)
                    return body, 200
                else:
                    return body, status_code
        except urllib.error.HTTPError as e:
            # 4xx/5xx 처리
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(sleep * 2)
                continue
            return str(e), e.code
        except (urllib.error.URLError, OSError, TimeoutError):
            if attempt < retries:
                time.sleep(sleep * 2)
                continue
            return None, None
    return None, None


def encode_url_param(params):
    """쿼리 파라미터 인코딩."""
    return urllib.parse.urlencode(params, safe=':')


# ── DOI 핸들 확인 ──────────────────────────────────────────────────────────────
def check_doi_handle(doi):
    """
    doi.org 핸들 API로 DOI 등록 여부 확인.
    responseCode == 1 이면 등록됨.
    반환: (registered: bool, handle_info: dict|None)
    """
    url = f"{DOI_HANDLE_BASE}/{urllib.parse.quote(doi, safe='')}"
    body, status = http_get(url, timeout=12)
    if status != 200 or body is None:
        return False, None
    try:
        data = json.loads(body)
        # 응답 구조: {"responseCode": 1, "handle": {...}}
        rc = data.get('responseCode')
        if rc == 1:
            # 등록된 핸들 중 URL 메타데이터 추출
            handles = data.get('handle', [])
            if isinstance(handles, dict):
                handles = [handles]
            urls = []
            for h in (handles if isinstance(handles, list) else []):
                values = h.get('values', [])
                if isinstance(values, list):
                    for v in values:
                        if v.get('data', {}).get('type') == 'URL':
                            urls.append(v.get('data', {}).get('value'))
            return True, {'urls': urls, 'payload': data}
        # rc != 1 (예: 100 Not Found) → 미등록
        return False, None
    except (json.JSONDecodeError, KeyError, TypeError):
        return False, None


# ── Crossref 조회 ──────────────────────────────────────────────────────────────
def crossref_works_by_doi(doi):
    """
    Crossref works/{doi} 엔드포인트.
    반환: message dict 또는 실패 시 None
    """
    url = f"{CROSSREF_API}/{urllib.parse.quote(doi, safe='')}"
    body, status = http_get(url, timeout=12)
    if status != 200 or body is None:
        return None
    try:
        data = json.loads(body)
        # Crossref 응답: {"message": {...}}
        msg = data.get('message', {})
        return msg
    except (json.JSONDecodeError, AttributeError):
        return None


def crossref_search(query_type, query_value, rows=5):
    """
    Crossref works?query.{type}={value}&rows=N
    query_type: 'title' 또는 'bibliographic'
    반환: message dict 또는 None
    """
    params = {f'query.{query_type}': query_value, 'rows': rows, 'select': 'DOI,title,author,issued,container-title,URL'}
    url = f"{CROSSREF_API}?{encode_url_param(params)}"
    body, status = http_get(url, timeout=12)
    if status != 200 or body is None:
        return None
    try:
        data = json.loads(body)
        return data.get('message', {})
    except (json.JSONDecodeError, AttributeError):
        return None


# ── DataCite 조회 ──────────────────────────────────────────────────────────────
def datacite_doi(doi):
    """
    DataCite API: GET /dois/{doi}
    반환: dict 또는 None
    """
    url = f"{DATACITE_API}/{urllib.parse.quote(doi, safe='')}"
    body, status = http_get(url, timeout=12)
    if status != 200 or body is None:
        return None
    try:
        data = json.loads(body)
        return data.get('data', data)
    except (json.JSONDecodeError, AttributeError):
        return None


# ── arXiv 조회 ────────────────────────────────────────────────────────────────
def arxiv_by_id(arxiv_id):
    """
    arXiv API: id_list={arxiv_id}
    반환: list of dicts (title, authors, published, summary, id, pdf_url) 또는 None
    """
    params = {'id_list': arxiv_id, 'max_results': 1}
    url = f"{ARXIV_API}?{encode_url_param(params)}"
    body, status = http_get(url, timeout=12)
    if status != 200 or body is None:
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None

    ns = {'atom': 'http://www.w3.org/2005/Atom',
          'arxiv': 'http://arxiv.org/schemas/atom'}
    entries = root.findall('atom:entry', ns)
    results = []
    for entry in entries:
        title_el = entry.find('atom:title', ns)
        title = ''.join(title_el.itertext()).strip() if title_el is not None else None

        authors = []
        for a in entry.findall('atom:author', ns):
            name = a.find('atom:name', ns)
            if name is not None:
                authors.append(''.join(name.itertext()).strip())
        first_author = authors[0] if authors else None

        published_el = entry.find('atom:published', ns)
        published = published_el.text[:4] if published_el is not None else None  # YYYY

        summary_el = entry.find('atom:summary', ns)
        summary = ''.join(summary_el.itertext()).strip() if summary_el is not None else None

        # PDF URL
        pdf_url = None
        for link in entry.findall('atom:link', ns):
            if link.get('title') == 'pdf' or 'pdf' in (link.get('title') or '').lower():
                pdf_url = link.get('href')
                break
        if not pdf_url:
            pdf_url = f"https://arxiv.org/abs/{arxiv_id}"

        results.append({
            'title': title,
            'authors': authors,
            'first_author': first_author,
            'year': published,
            'summary': summary,
            'id': arxiv_id,
            'url': pdf_url,
        })
    return results


def arxiv_search_by_title(title, max_results=5):
    """
    arXiv API search_query=ti:"제목"
    반환: list of dicts 또는 None
    """
    safe_title = re.sub(r'[^A-Za-z0-9\s]', '', title).strip()
    # 따옴표로 감싸서 검색
    quoted = f'ti:"{safe_title}"'
    params = {'search_query': quoted, 'max_results': max_results}
    url = f"{ARXIV_API}?{encode_url_param(params)}"
    body, status = http_get(url, timeout=12)
    if status != 200 or body is None:
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    entries = root.findall('atom:entry', ns)
    results = []
    for entry in entries:
        title_el = entry.find('atom:title', ns)
        title = ''.join(title_el.itertext()).strip() if title_el is not None else None
        authors = []
        for a in entry.findall('atom:author', ns):
            name = a.find('atom:name', ns)
            if name is not None:
                authors.append(''.join(name.itertext()).strip())
        first_author = authors[0] if authors else None
        published_el = entry.find('atom:published', ns)
        published = published_el.text[:4] if published_el is not None else None
        arxiv_id = None
        for id_el in entry.findall('atom:id', ns):
            aid = ''.join(id_el.itertext()).strip()
            m = re.search(r'/abs/(\d{4}\.\d{4,5})', aid)
            if m:
                arxiv_id = m.group(1)
                break
        results.append({
            'title': title,
            'authors': authors,
            'first_author': first_author,
            'year': published,
            'id': arxiv_id,
            'url': f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
        })
    return results


# ── 유사도 계산 ────────────────────────────────────────────────────────────────
def normalize_text(s):
    """비교용 정규화: 소문자화, 구두점 제거, 공백 정리."""
    if s is None:
        return ''
    s = s.lower()
    s = re.sub(r'[^\w\s]', '', s)   # 구두점 제거
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def title_similarity(a, b):
    """
    difflib ratio 기반 유사도.
    한쪽이 다른 쪽의 접두어면 0.9 보정.
    """
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return 0.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    # 접두어 보정: 한쪽이 다른 쪽의 시작 부분과 일치하면
    if len(na) >= 5 and nb.startswith(na[:len(na)//2 + 1]):
        ratio = max(ratio, 0.9)
    elif len(nb) >= 5 and na.startswith(nb[:len(nb)//2 + 1]):
        ratio = max(ratio, 0.9)
    return round(ratio, 4)


def author_match(input_author, source_author):
    """제1저자 일치 여부 (정규화 후). 입력 저자가 None이면 비교 생략(감점 없음)."""
    if input_author is None:
        return True  # 저자 비교 생략 → 감점 없음
    if not source_author:
        return False
    ia = normalize_text(input_author)
    sa = normalize_text(source_author)
    # 영문: 성만 일치하면 OK
    if ia == sa:
        return True
    # 부분 일치 체크
    return ia in sa or sa in ia


def year_match(input_year, source_year):
    """연도 근접도. 차수로 반환, None이면 불일치."""
    if not input_year or not source_year:
        return None
    try:
        iy = int(input_year)
        sy = int(source_year)
    except (ValueError, TypeError):
        return None
    return abs(iy - sy)


# ── 보정 서지 생성 ──────────────────────────────────────────────────────────────
def build_corrected_bib(item, matched):
    """
    ✅/⚠️ 항목의 교정 서지를 소스 메타데이터 그대로 구성.
    matched: {source, doi/arxiv/title/authors/year/container/url}
    """
    if matched is None:
        return None

    source = matched.get('source', '')
    parts = []

    if source == 'crossref':
        data = matched.get('data', {})
        doi = data.get('DOI')
        title = data.get('title', [None])[0]
        authors = data.get('author', [])
        author_str = ', '.join(
            (a.get('family', '') + (', ' + a.get('given', '') if a.get('given') else ''))
            for a in authors
        )
        year = data.get('issued', {}).get('date-parts', [[None]])[0][0]
        container = data.get('container-title', [None])[0]
        url = data.get('URL')

        parts.append(f"DOI: {doi}" if doi else "")

        if author_str:
            parts.append(f"저자: {author_str}")
        if title:
            parts.append(f"제목: {title}")
        if year:
            parts.append(f"연도: {year}")
        if container:
            parts.append(f"출처: {container}")
        if url:
            parts.append(f"URL: {url}")

    elif source == 'datacite':
        data = matched.get('data', {})
        doi = data.get('doi')
        title = data.get('title')
        creators = data.get('creators', [])
        author_str = ', '.join((c.get('name', '') or '') for c in creators)
        year = data.get('publicationYear')
        publisher = data.get('publisher')
        url = data.get('url', {}).get('value') if isinstance(data.get('url'), dict) else data.get('url')

        parts.append(f"DOI: {doi}" if doi else "")
        if author_str:
            parts.append(f"저자: {author_str}")
        if title:
            parts.append(f"제목: {title}")
        if year:
            parts.append(f"연도: {year}")
        if publisher:
            parts.append(f"출판사: {publisher}")
        if url:
            parts.append(f"URL: {url}")

    elif source == 'arxiv':
        data = matched.get('data', {})
        arxiv_id = data.get('id')
        title = data.get('title')
        author_str = data.get('first_author') or (', '.join(data.get('authors', [])) if data.get('authors') else '')
        year = data.get('year')
        url = data.get('url')

        parts.append(f"arXiv: {arxiv_id}" if arxiv_id else "")
        if author_str:
            parts.append(f"저자: {author_str}")
        if title:
            parts.append(f"제목: {title}")
        if year:
            parts.append(f"연도: {year}")
        if url:
            parts.append(f"URL: {url}")

    return ' | '.join(p for p in parts if p) if parts else None


# ── 주요 검증 로직 ─────────────────────────────────────────────────────────────
def verify_item(item, offline=False):
    """
    단일 항목 검증.
    반환: result dict (id, raw, status, evidence, matched, title_similarity, diffs, candidates, note)
    """
    result = {
        'id': item['id'],
        'raw': item['raw'],
        'status': None,
        'evidence': [],
        'matched': None,
        'title_similarity': None,
        'diffs': [],
        'candidates': [],
        'note': '',
        '_offline': offline,
    }

    doi = item.get('doi')
    arxiv_id = item.get('arxiv')
    kind = item.get('kind', 'article')
    title = item.get('title')
    input_author = item.get('first_author')
    input_year = item.get('year')

    # F3 수정: 오프라인 모드면 즉시 ⛔ 반환 (모든 외부 호출 차단)
    if offline:
        result['status'] = 'unreachable'
        result['evidence'].append("오프라인 모드 — 외부 호출 차단됨")
        result['note'] = "오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨."
        return result

    # ── 케이스 1: DOI 있음 ────────────────────────────────────────────────────
    if doi:
        # (a) doi.org 핸들 확인
        registered, handle_info = check_doi_handle(doi)
        result['evidence'].append(f"DOI 핸들 확인: {'등록됨(responseCode 1)' if registered else '미등록'}")

        if not registered:
            # F3 수정: 오프라인 모드면 즉시 ⛔ 반환 (외부 호출 차단)
            if offline:
                result['status'] = 'unreachable'
                result['evidence'].append("오프라인 모드 — 외부 호출 차단됨")
                result['note'] = f"DOI {doi} 는 오프라인 모드로 확인불가."
                return result
            # DOI 미등록 → ❌ 또는 제목·저자로 실존 확인 시도
            result['note'] = f"DOI {doi} 는 doi.org 에 미등록."
            # Crossref / DataCite 에서 제목·저자로 검색
            candidates = []
            cr = crossref_search('title', title or '', rows=5) if title else None
            if cr:
                for row in cr.get('items', [])[:5]:
                    candidates.append({'source': 'crossref', 'data': row})

            # F1 수정: DOI 미등록 + 검색 후보 없음 → ❌ 미확인 (조기 return 복원하되 status 명시)
            if not candidates:
                result['status'] = 'unverified'
                result['evidence'].append("Crossref 제목 검색: 결과 없음")
                result['evidence'].append("arXiv 제목 검색: 미수행 (DOI 기반 검증 중)")
                _note = "DOI 미등록" + (": " + build_unverified_note(item) if build_unverified_note(item) else "")
                result['note'] = _note if _note else f"DOI {doi} 는 doi.org 에 미등록."
                return result

            # 제목 유사도로 최적 후보 선택
            best = pick_best_candidate(item, candidates)
            if best and title_similarity(title, best.get('title', '')) >= 0.72:
                result['status'] = 'partial'
                result['matched'] = {'source': best['source'], 'data': best['data']}
                result['title_similarity'] = title_similarity(title, best['title'])
                result['candidates'] = candidates[:3]
                result['note'] += " 제목 유사도 {:.2f}. 교정 DOI 제시.".format(result['title_similarity'])
                return result
            else:
                result['candidates'] = candidates[:3]
                # F1 수정: 유사도 < 0.72 → ❌ 미확인, candidates는 참고용으로 유지
                result['status'] = 'unverified'
                result['note'] = "DOI 미등록, 검색 후보 있으나 제목 유사도 낮음. " + build_unverified_note(item)
                return result

        # ── DOI 등록됨 → Crossref / DataCite 서지 조회 ─────────────────────────
        cr_msg = crossref_works_by_doi(doi)
        dc_data = None
        if cr_msg is None:
            # F3 수정: 오프라인 모드면 즉시 ⛔ 반환
            if offline:
                result['status'] = 'unreachable'
                result['evidence'].append("오프라인 모드 — Crossref 조회 차단됨")
                result['note'] = f"DOI {doi} 는 오프라인 모드로 확인불가."
                return result
            dc_data = datacite_doi(doi)

        if cr_msg:
            source = 'crossref'
            matched = {
                'source': 'crossref',
                'data': cr_msg,
                'doi': cr_msg.get('DOI'),
                'title': (cr_msg.get('title') or [None])[0],
                'authors': cr_msg.get('author', []),
                'first_author': (cr_msg.get('author') or [{}])[0].get('family') if cr_msg.get('author') else None,
                'year': (cr_msg.get('issued') or {}).get('date-parts', [[None]])[0][0],
                'container': (cr_msg.get('container-title') or [None])[0],
                'url': cr_msg.get('URL'),
            }
        elif dc_data:
            source = 'datacite'
            matched = {
                'source': 'datacite',
                'data': dc_data,
                'doi': dc_data.get('doi'),
                'title': dc_data.get('title'),
                'authors': dc_data.get('creators', []),
                'first_author': (dc_data.get('creators') or [{}])[0].get('name') if dc_data.get('creators') else None,
                'year': dc_data.get('publicationYear'),
                'container': dc_data.get('container-title') or dc_data.get('publisher'),
                'url': dc_data.get('url', {}).get('value') if isinstance(dc_data.get('url'), dict) else dc_data.get('url'),
            }
        else:
            # 핸들 등록됨 but 서지 API에서 없음 → ⚠️ (DOI가 다른 문헌을 가리킴 가능성)
            result['note'] = f"DOI {doi} 는 등록되어 있으나 Crossref/DataCite 서지 조회에서 매칭 없음."
            result['status'] = 'partial'
            result['evidence'].append("DOI 등록 확인, 서지 매칭 없음")
            return result

        # ── DOI 서지 대조 ──────────────────────────────────────────────────────
        # 'matched'가 설정된 경우(DOI 등록됨 + 서지 조회 성공)에만 실행
        if matched:
            source_title = matched.get('title')
            source_author = matched.get('first_author')
            source_year = matched.get('year')
            sim = title_similarity(title, source_title) if title and source_title else 0.0
            result['title_similarity'] = sim
            result['evidence'].append(f"Crossref 제목 유사도: {sim:.2f}")
            if source_author:
                result['evidence'].append(f"교차 저자: 입력 '{input_author}' vs 소스 '{source_author}'")
            if source_year:
                yr_diff = year_match(input_year, source_year)
                if yr_diff is not None:
                    result['evidence'].append(f"연도 차이: 입력 {input_year} vs 소스 {source_year} (차 {yr_diff})")

            # 판정
            diffs = []
            if sim < 0.85:
                diffs.append(f"제목 유사도 {sim:.2f} (기준 0.85 미만)")
            if source_author and not author_match(input_author, source_author):
                diffs.append(f"제1저자 불일치: 입력 '{input_author}' vs 소스 '{source_author}'")
            if yr_diff is not None and yr_diff > 1:
                diffs.append(f"연도 차이 {yr_diff}년 (기준 ≤1)")

            if sim >= 0.85 and (yr_diff is None or yr_diff <= 1) and (not source_author or author_match(input_author, source_author)):
                result['status'] = 'verified'
                result['matched'] = matched
                result['diffs'] = diffs
                result['note'] = f"확인 완료: DOI 실존 + 제목 유사도 {sim:.2f} + 연도차 {yr_diff if yr_diff else 0}년"
                return result
            else:
                result['status'] = 'partial'
                result['matched'] = matched
                result['diffs'] = diffs
                result['candidates'] = []
                result['note'] = "부분일치: " + "; ".join(diffs) if diffs else "부분일치"
                return result
        # matched가 없으면(이미 반환되지 않았으면) 여기서 계속 진행 → 케이스3 fallback

    # ── 케이스 2: arXiv ID 있음 ────────────────────────────────────────────────
    if arxiv_id and not doi:
        arxiv_results = arxiv_by_id(arxiv_id)
        if arxiv_results:
            result['evidence'].append(f"arXiv {arxiv_id} 실존 확인")
            src = arxiv_results[0]
            source_title = src.get('title')
            source_author = src.get('first_author')
            source_year = src.get('year')

            sim = title_similarity(title, source_title) if title and source_title else 0.0
            result['title_similarity'] = sim
            result['evidence'].append(f"arXiv 제목 유사도: {sim:.2f}")

            diffs = []
            if sim < 0.85:
                diffs.append(f"제목 유사도 {sim:.2f} (기준 0.85 미만)")
            if source_author and not author_match(input_author, source_author):
                diffs.append(f"제1저자 불일치: 입력 '{input_author}' vs 소스 '{source_author}'")
            if source_year:
                yr_diff = year_match(input_year, source_year)
                if yr_diff is not None and yr_diff > 1:
                    diffs.append(f"연도 차이 {yr_diff}년")

            if sim >= 0.85 and (not source_author or author_match(input_author, source_author)) and (yr_diff is None or yr_diff <= 1):
                result['status'] = 'verified'
                result['matched'] = {
                    'source': 'arxiv',
                    'data': src,
                    'arxiv': arxiv_id,
                    'title': source_title,
                    'authors': src.get('authors'),
                    'first_author': source_author,
                    'year': source_year,
                    'url': src.get('url'),
                }
                result['diffs'] = diffs
                result['note'] = f"✅ 확인: arXiv {arxiv_id} 실존, 제목 유사도 {sim:.2f}"
                return result
            else:
                result['status'] = 'partial'
                result['matched'] = {
                    'source': 'arxiv',
                    'data': src,
                    'arxiv': arxiv_id,
                    'title': source_title,
                    'first_author': source_author,
                    'year': source_year,
                    'url': src.get('url'),
                }
                result['diffs'] = diffs
                result['note'] = "부분일치: " + "; ".join(diffs) if diffs else "부분일치"
                return result
        else:
            # arXiv 조회 실패 → 오프라인 또는 네트워크 문제
            if offline:
                result['status'] = 'unreachable'
                result['note'] = f"arXiv {arxiv_id} 검증 실패(오프라인 모드)."
                return result
            # 네트워크 문제로 볼 수도 있지만, ID가 실존하지 않을 수도 있음
            result['evidence'].append(f"arXiv {arxiv_id} 조회 실패 (네트워크)")
            result['status'] = 'unreachable'
            result['note'] = f"arXiv {arxiv_id} 검증 실패. 네트워크 문제 또는 존재하지 않는 ID."
            return result

    # ── 케이스 3 앞: 웹(kind=='web')이고 doi/arxiv 없음 → 조기 비대상 return ──
    if kind == 'web' and not doi and not arxiv_id:
        result['status'] = 'not_applicable'
        result['evidence'].append(f"kind=web, DOI/arXiv 없음 — 비대상(➖)")
        result['note'] = "웹 문헌(kind=web)은 DOI/arXiv 대상 아님. URL 기반 별도 확인 권장."
        return result

    # ── 케이스 3: 둘 다 없음 → 검색 기반 ────────────────────────────────────────
    if not doi and not arxiv_id:
        candidates = []
        if title:
            # Crossref 제목 검색
            cr = crossref_search('title', title, rows=5)
            if cr:
                for row in cr.get('items', [])[:5]:
                    if row.get('DOI'):
                        candidates.append({'source': 'crossref', 'data': row})

            # 영문 + 비단행본이면 arXiv 제목 검색
            if kind != 'book' and re.search(r'[A-Za-z]', title or ''):
                arxiv_cand = arxiv_search_by_title(title, max_results=5)
                if arxiv_cand:
                    for a in arxiv_cand:
                        candidates.append({'source': 'arxiv', 'data': a})

        # Crossref bibliographic 검색 (raw 전체)
        if not candidates:
            cr_bib = crossref_search('bibliographic', item.get('raw', ''), rows=5)
            if cr_bib:
                for row in cr_bib.get('items', [])[:5]:
                    if row.get('DOI'):
                        candidates.append({'source': 'crossref', 'data': row})

        if not candidates:
            # F5 수정: 단행본은 ISBN/단행본 전용 경로가 없으므로 모든 소스 미발견 시 ❌ 대신 ⛔
            if kind == 'book':
                result['status'] = 'unreachable'
                result['evidence'].append("Crossref 제목 검색: 결과 없음")
                result['evidence'].append("DataCite/OpenLibrary 단행본 검색: 수행 안 함 (M4 캐시 재생 예정)")
                result['note'] = "단행본(kind=book) — Crossref 미색인으로 확인불가. ISBN/OpenLibrary 경로 필요."
            else:
                result['status'] = 'unverified'
                result['evidence'].append("Crossref 제목 검색: 결과 없음")
                result['evidence'].append("arXiv 제목 검색: 결과 없음" if kind != 'book' and re.search(r'[A-Za-z]', title or '') else "")
                _note = build_unverified_note(item)
                # DOI가 있었지만 미등록인 경우 → 비고에 'DOI 미등록' 명시
                if doi:
                    _note = "DOI 미등록" + (": " + _note if _note else " — 가짜 단정 아님, 생성된 참고문헌 가능성")
                result['note'] = _note
            return result

        # 후보 합집합 → 최적 선택
        best = pick_best_candidate(item, candidates)
        if best:
            sim = title_similarity(title, best.get('title', '')) if title and best.get('title') else 0.0
            result['title_similarity'] = sim
            result['evidence'].append(f"{best['source']} 제목 유사도: {sim:.2f}")
            result['candidates'] = [{'source': c['source'], 'title': (c['data'].get('title') or c['data'].get('title', [None])[0])} for c in candidates[:3]]
            result['matched'] = {'source': best['source'], 'data': best['data']}
            # 판정: 검색 기반이면 짧은 제목은 저자 일치 필요
            is_short_title = title and len(title.split()) <= 2
            src_author = best.get('first_author')
            if is_short_title and src_author and not author_match(input_author, src_author):
                result['status'] = 'partial'
                result['note'] = f"검색 기반: 짧은 제목(2단어 이하) — 저자 일치 필요. 입력 '{input_author}' vs 소스 '{src_author}'."
            elif sim >= 0.85:
                result['status'] = 'verified'
                result['note'] = f"✅ 확인(검색 기반): 제목 유사도 {sim:.2f}, 출처 {best['source']}."
            elif sim >= 0.72:
                result['status'] = 'partial'
                result['note'] = f"⚠️ 부분일치(검색 기반): 제목 유사도 {sim:.2f}, 출처 {best['source']}."
            else:
                result['status'] = 'unverified'
                result['note'] = f"검색 결과 있으나 유사도 {sim:.2f} 낮음."
            return result
        else:
            result['status'] = 'unverified'
            result['note'] = build_unverified_note(item)
            return result

    # ── 케이스 4: 웹/URL만 있음 → 비대상 ───────────────────────────────────────
    if item.get('url') and not doi and not arxiv_id:
        result['status'] = 'not_applicable'
        result['evidence'].append(f"URL: {item['url']} — DOI 대상 아님 (비대상)")
        result['note'] = "웹페이지·소프트웨어 문서 등 DOI 대상 아님. URL 응답 코드만 확인."
        return result

    # fallback — status가 None이면 ❌ 미확인으로 보정
    if result['status'] is None:
        result['status'] = 'unverified'
        existing = result.get('note') or ''
        result['note'] = (existing + " 검증 경로에서 근거 미발견") if existing else "검증 경로에서 근거 미발견"
    return result


def pick_best_candidate(item, candidates):
    """후보 중 (✅가능 여부, 제1저자 일치, 연도 근접, 유사도) 순으로 최적 선택."""
    title = item.get('title')
    input_author = item.get('first_author')
    input_year = item.get('year')

    scored = []
    for c in candidates:
        data = c['data']
        source = c['source']

        # 제목 추출
        if source == 'crossref':
            src_title = (data.get('title') or [None])[0]
            src_author = (data.get('author') or [{}])[0].get('family') if data.get('author') else None
            src_year = (data.get('issued') or {}).get('date-parts', [[None]])[0][0]
        elif source == 'arxiv':
            src_title = data.get('title')
            src_author = data.get('first_author')
            src_year = data.get('year')
        else:
            continue

        if not src_title:
            continue

        sim = title_similarity(title, src_title) if title else 0.0

        author_ok = True
        if src_author and input_author:
            author_ok = author_match(input_author, src_author)

        yr_diff = year_match(input_year, src_year) if input_year and src_year else None

        # 점수: ✅가능 = 유사도 높고 저자/연도 일치
        score = sim
        if not author_ok:
            score -= 0.2
        if yr_diff is not None and yr_diff > 1:
            score -= 0.1
        scored.append((score, c, src_title, src_author, src_year))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0]
    return {
        'source': best[1]['source'],
        'data': best[1]['data'],
        'title': best[2],
        'first_author': best[3],
        'year': best[4],
    }


def build_unverified_note(item):
    """❌ 미확인 항목의 비고 문구."""
    kind = item.get('kind', '')
    has_doi = bool(item.get('doi'))
    has_arxiv = bool(item.get('arxiv'))
    notes = []

    if item.get('title') and len(item['title'].split()) <= 2:
        notes.append("짧은 제목 — 저자 일치 확인 필요했으나 근거 없음")

    if kind == 'book':
        notes.append("단행본 — ISBN 확인 권장")
    elif kind == 'report':
        notes.append("보고서 — 출처 기관 확인 권장")
    elif re.search(r'[가-힣]', item.get('title') or ''):
        notes.append("국문 문헌 — KCI/RISS/DBpia 수동 확인 권장")
    elif has_doi and item.get('doi'):
        notes.append(f"DOI {item['doi']} 미등록 — 가짜 단정 아님, 생성된 참고문헌 가능성")
    else:
        notes.append("근거 없음 — 생성된 참고문헌 가능성·인용 보류")

    return "; ".join(notes) if notes else "어떤 소스에서도 근거 없음. 가짜 단정 아님."


# ── 보고서 생성 ────────────────────────────────────────────────────────────────
def build_report(results, truncated=False):
    """Markdown 보고서 문자열."""
    lines = []
    lines.append("# 참고문헌 검증 보고서")
    lines.append("")
    lines.append(f"**검증 시각**: {time.strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"**검증 대상**: {len(results)}건" + (" (일부 생략됨)" if truncated else ""))
    lines.append("")

    # 집계
    summary_map = {
        'verified': '✅',
        'partial': '⚠️',
        'unverified': '❌',
        'unreachable': '⛔',
        'not_applicable': '➖',
    }
    counts = {'✅': 0, '⚠️': 0, '❌': 0, '⛔': 0, '➖': 0}
    for r in results:
        s = r.get('status')
        sym = summary_map.get(s, '?')
        if sym in counts:
            counts[sym] += 1
    lines.append("## 집계")
    lines.append("")
    lines.append(f"- 총 항목: {len(results)}건")
    for sym, cnt in counts.items():
        lines.append(f"- {sym} {cnt}건")
    lines.append("")

    # 소스·판정 기준
    lines.append("## 소스 및 판정 기준")
    lines.append("")
    lines.append("- **DOI 실존 확인**: `https://doi.org/api/handles/{DOI}` (responseCode 1)")
    lines.append("- **서지 대조**: Crossref `api.crossref.org/works/{DOI}` → 없으면 DataCite `api.datacite.org/dois/{DOI}`")
    lines.append("- **arXiv 검증**: `export.arxiv.org/api/query?id_list=`")
    lines.append("- **검색 기반**: Crossref `works?query.title=` 및 `works?query.bibliographic=`, 영문·비단행본이면 arXiv `search_query=ti:\"제목\"`")
    lines.append("- **유사도**: `difflib.SequenceMatcher` ratio (소문자·구두점 제거), 접두어면 0.9 보정")
    lines.append("- **판정 기준**: ✅ = 앵커 확인 + 유사도 ≥0.85 + 연도차 ≤1 + 저자 불일치 없음 / ⚠️ = 실존하나 차이 있음 / ❌ = 근거 없음 / ⛔ = 네트워크 오류 / ➖ = 비대상")
    lines.append("")

    # 표
    lines.append("## 항목별 결과")
    lines.append("")
    lines.append("| # | 상태 | 입력 요약 | 근거 | 차이점 | 비고 |")
    lines.append("|---|------|-----------|------|--------|------|")

    summary_map = {
        'verified': '✅ 확인',
        'partial': '⚠️ 부분일치',
        'unverified': '❌ 미확인',
        'unreachable': '⛔ 확인불가',
        'not_applicable': '➖ 비대상',
    }

    for r in results:
        idx = r['id']
        status_sym = summary_map.get(r.get('status'), '?')
        raw_summary = r.get('raw', '')[:80] + ('…' if len(r.get('raw', '')) > 80 else '')

        evidence = '; '.join(r.get('evidence', [])) or '—'

        diffs = r.get('diffs', [])
        diff_str = '; '.join(diffs) if diffs else '—'

        note = r.get('note', '') or '—'

        lines.append(f"| {idx} | {status_sym} | {raw_summary} | {evidence} | {diff_str} | {note} |")

    lines.append("")

    # 교정 서지
    corrected = [r for r in results if r.get('status') in ('verified', 'partial') and r.get('matched')]
    if corrected:
        lines.append("## 교정 서지 (소스 메타데이터 그대로)")
        lines.append("")
        for r in corrected:
            idx = r['id']
            matched = r.get('matched')
            if matched:
                bib = build_corrected_bib(r, matched)
                if bib:
                    lines.append(f"**[{idx}]** {bib}")
                    # 원문
                    lines.append(f"  _입력_: {r['raw'][:200]}")
                    lines.append("")
        lines.append("")

    # 후속 조치
    lines.append("## 후속 조치")
    lines.append("")
    action_needed = [r for r in results if r.get('status') in ('partial', 'unverified')]
    if action_needed:
        lines.append("다음 항목은 추가 확인이 필요합니다:")
        lines.append("")
        for r in action_needed:
            idx = r['id']
            status_sym = summary_map.get(r.get('status'), '?')
            lines.append(f"- **[{idx}]** {status_sym}: {r.get('note', '') or '확인 필요'}")
        lines.append("")
    else:
        lines.append("추가 확인이 필요한 항목이 없습니다.")
        lines.append("")

    # 한계
    lines.append("## 한계")
    lines.append("")
    lines.append("- 국문 학술지는 Crossref 미색인 가능성이 높아 영어 메타데이터만으로는 유사도가 낮게 나올 수 있음.")
    lines.append("- 단행본·보고서는 색인이 불완전할 수 있음.")
    lines.append("- 자동 검증은 참고용이며, 최종 판단은 사람이 수기로 해야 함.")
    lines.append('- "❌ 미확인"을 "가짜"라고 단정하지 않음. 생성된 참고문헌일 가능성·인용 보류를 시사할 뿐임.')
    lines.append("- DOI가 등록되었지만 서지 API에서 매칭되지 않는 경우 ⚠️로 표시하며, 오기재 가능성을 함께 알림.")
    lines.append("")

    return '\n'.join(lines)


# ── 메인 ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='참고문헌 검증 (DOI/arXiv/Crossref/DataCite)')
    parser.add_argument('input_json', help='parse_refs.py 출력 JSON 경로 (work/refs.json)')
    parser.add_argument('--json', default='work/verify.json', help='출력 JSON 경로')
    parser.add_argument('--md', default='work/report.md', help='출력 Markdown 경로')
    parser.add_argument('--max', type=int, default=60, help='최대 검증 건수 (기본 60)')
    parser.add_argument('--offline', action='store_true', help='오프라인 모드 (모든 항목 ⛔)')
    args = parser.parse_args()

    # 입력 JSON 확인
    if not os.path.isfile(args.input_json):
        print(f"오류: 입력 파일 없음 — {args.input_json}", file=sys.stderr)
        sys.exit(2)

    with open(args.input_json, encoding='utf-8') as f:
        try:
            payload = json.load(f)
        except json.JSONDecodeError as e:
            print(f"오류: JSON 파싱 실패 — {e}", file=sys.stderr)
            sys.exit(2)

    items = payload.get('items', [])
    if not items:
        print("오류: 항목 없음", file=sys.stderr)
        sys.exit(2)

    # 네트워크 확인 (오프라인 아닐 때)
    if not args.offline:
        test_url = "https://api.crossref.org/works?rows=1"
        body, status = http_get(test_url, timeout=12)
        if status != 200 or body is None:
            print("⚠️ 네트워크 확인 실패: api.crossref.org 응답 없음.")
            print("   --offline 으로 형식만 시연하거나, 네트워크를 확인한 후 다시 실행하세요.")
            print("   (조치: curl -s https://api.crossref.org/works?rows=1)")
            # 오프라인처럼 처리하지는 않고, 각 항목이 ⛔가 되도록 진행
            # 각 verify_item 에 오프라인 플래그를 전달하지는 않고, HTTP 실패 시 ⛔ 처리
            pass

    results = []
    truncated = False
    max_items = args.max
    total = len(items)

    if total > max_items:
        print(f"⚠️ 항목 {total}건 > 최대 {max_items}건. 처음 {max_items}건만 검증합니다.")
        print(f"   나머지 {total - max_items}건은 나눠서 재실행하세요.")
        truncated = True
        items = items[:max_items]

    print(f"검증 시작: {len(items)}건 (오프라인={args.offline})")
    for item in items:
        result = verify_item(item, offline=args.offline)
        results.append(result)
        safe_print(f"  [{result['id']}] status={result['status']} note={result.get('note','')[:60]}")
        time.sleep(0.35)  # 요청 간 대기

    # JSON 출력
    out_dir = os.path.dirname(args.json)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    out_obj = {
        'meta': {
            'when': time.strftime('%Y-%m-%d %H:%M:%S'),
            'count': len(results),
            'truncated': truncated,
            'offline': args.offline,
        },
        'results': results,
    }
    with open(args.json, 'w', encoding='utf-8') as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

    # Markdown 보고서
    md = build_report(results, truncated=truncated)
    md_dir = os.path.dirname(args.md)
    if md_dir:
        os.makedirs(md_dir, exist_ok=True)
    with open(args.md, 'w', encoding='utf-8') as f:
        f.write(md)

    safe_print(f"\n결과 JSON: {args.json}")
    safe_print(f"보고서 Markdown: {args.md}")

    # 집계 요약 출력 + F2: 불변식 검사 (집계 합 = 총 건수)
    counts = {'✅': 0, '⚠️': 0, '❌': 0, '⛔': 0, '➖': 0}
    for r in results:
        s = r.get('status')
        sym = {
            'verified': '✅',
            'partial': '⚠️',
            'unverified': '❌',
            'unreachable': '⛔',
            'not_applicable': '➖',
        }.get(s, '?')
        if sym in counts:
            counts[sym] += 1

    sum_counts = sum(counts.values())
    if sum_counts != len(results):
        safe_print(f"\n⚠️ 오류: 집계 합({sum_counts}) ≠ 총 건수({len(results)}). 데이터 무결성 위반!")
    else:
        safe_print(f"\n집계 (불변식 OK: 합={sum_counts} = 총 {len(results)}건):")
    for sym, cnt in counts.items():
        safe_print(f"  {sym} {cnt}건")

    sys.exit(0)


if __name__ == '__main__':
    main()
