#!/usr/bin/env python3
"""
extract_claims.py — Document Parse 본문 element에서 인용 표지([n], (저자, 연도))를 찾고,
표지가 붙은 문장 하나를 주장 문장으로 잘라낸다. 결정론, LLM 금지.

문장 분리는 결정론 규칙. 한 문장에 표지 여러 개면 표지별로 각각 1건.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 상수 ──────────────────────────────────────────────────────────────────────

# 인용 표지 패턴
NUMBER_MARK_RE = re.compile(r'\[(\d+)\]')
AUTHOR_YEAR_MARK_RE = re.compile(
    r'\(([^)]{1,40}),?\s*(\d{4})\)'
    r'|'
    r'([A-Za-z가-힣][^.]{1,40})\s+\((\d{4})\)'
)

# 문장 분리 경계 (결정론)
# 문장 종료: . ! ? 뒤에 공백 또는 줄바꿈, 또는 문자열 끝
SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+(?=\S|$)')

# 한국어 문장 종료 보조 (。주식회사 등딴
Korean_END_RE = re.compile(r'(?<=[。!])\s+(?=\S|$)')


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def get_text(element: Dict[str, Any]) -> str:
    """element에서 text 추출 (여러 필드명 시도)."""
    for key in ("text", "content", "Content", "textContent", "TEXT"):
        val = element.get(key)
        if isinstance(val, str):
            return val
    if isinstance(element.get("content"), dict):
        inner = element["content"].get("text") or element["content"].get("Content")
        if isinstance(inner, str):
            return inner
    return ""


def get_page(element: Dict[str, Any]) -> int:
    """페이지 번호."""
    for key in ("page", "pageNumber", "page_number", "pageIndex", "pagenum"):
        val = element.get(key)
        if isinstance(val, (int, float)):
            return int(val)
    return 0


# ── 문장 분리 (결정론) ────────────────────────────────────────────────────────

def split_sentences(text: str) -> List[str]:
    """
    결정론 문장 분리.
    - . ! ? 또는 。 뒤에 공백이 오고 다음 문자가 비공백이면 경계.
    - 줄바꿈도 경계로 취급.
    - 약어(etc., e.g., i.e., Mr., Dr. 등)는 경계로 치지 않도록 방어.
    - 별첨호 앞뒤 공백은 경계로 보지 않음.
    - 번호 표지·저자-연도 표지가 걸쳐 있어도 문장 경계는 텍스트 기준.
    """
    if not text:
        return []

    # 먼저 줄 단위로 나누고, 각 줄을 문장 분리
    raw_lines = text.split('\n')
    sentences: List[str] = []
    buf = ""

    for line in raw_lines:
        if not line.strip():
            # 빈 줄은 문장 경계로
            if buf.strip():
                sentences.append(buf.strip())
                buf = ""
            continue

        # 현재 버퍼+이 줄을 합쳐서 문장 분리
        chunk = (buf + ' ' + line.strip()) if buf else line.strip()
        buf = ""

        # 문장 경계 찾기
        # 우선순위: 줄바꿈 > 문장 종료 문자
        # 먼저 .!?/。 기준으로 분할 (단, 약어 보호)
        parts = split_sentences_in_chunk(chunk)
        sentences.extend(parts)

    # 남은 버퍼
    if buf.strip():
        sentences.append(buf.strip())

    return sentences


def split_sentences_in_chunk(chunk: str) -> List[str]:
    """
    한 덩어리(줄 또는 버퍼)에서 문장 분리.
    약어 보호: 대문자로 시작하고 마침표로 끝나는 1~2글자 단어(Mr., Dr., etc.)는 경계로 보지 않음.
    """
    if not chunk.strip():
        return []

    # 약어 패턴: 대문자 1~2자 + 마침표, 또는 알려진 약어
    ABBR_RE = re.compile(
        r'\b([A-Z]{1,2}\.[A-Z]{1,2}\.|[A-Z]{1,2}\.|[a-z]\.[a-z]\.|etc\.|e\.g\.|i\.e\.|et al\.)'
    )

    # protected 구간 마킹
    protected_positions: List[Tuple[int, int]] = []
    for m in ABBR_RE.finditer(chunk):
        protected_positions.append((m.start(), m.end()))

    # 문장 종료 패턴: . ! ? 또는 。 뒤에 공백이 오고 다음 문자가 비공백
    # 단, protected 구간 내 마침표는 제외
    result: List[str] = []
    last_end = 0

    for m in re.finditer(r'[.!?。]', chunk):
        pos = m.end()
        # protected 구간에 포함되면 스킵
        if any(start <= m.start() < end for start, end in protected_positions):
            continue

        # 뒤에 공백이 오고 다음 비공백이 있는지 확인
        rest = chunk[pos:]
        if rest.startswith(' ') or rest.startswith('\t'):
            # 공백 후 다음 문자 확인
            after_space = rest.lstrip()
            if after_space and after_space[0] not in ' \t\n\r':
                # 문장 경계
                sentence = chunk[last_end:pos].strip()
                if sentence:
                    result.append(sentence)
                last_end = pos
                continue

        # 줄바꿈 경계
        if '\n' in chunk[last_end:pos]:
            parts = chunk[last_end:pos].split('\n')
            for p in parts[:-1]:
                if p.strip():
                    result.append(p.strip())
            last_end = pos

    # 마지막 문장
    last = chunk[last_end:].strip()
    if last:
        result.append(last)

    # 빈 문자열 정리
    return [s for s in result if s]


# ── 인용 표지 추출 ────────────────────────────────────────────────────────────

def find_claim_markers(sentence: str) -> List[Dict[str, Any]]:
    """
    한 문장에서 인용 표지([n], (저자, 연도))를 찾는다.
    반환: [{'type': 'number'|'author_year', 'value': ..., 'span': (start, end)}, ...]
    """
    markers: List[Dict[str, Any]] = []

    for m in NUMBER_MARK_RE.finditer(sentence):
        markers.append({
            'type': 'number',
            'value': m.group(1),
            'span': (m.start(), m.end()),
            'raw': m.group(0),
        })

    # 저자-연도 표지: ... (Author, Year) 또는 Author (Year) 형태
    for m in AUTHOR_YEAR_MARK_RE.finditer(sentence):
        # 패턴1: (저자, Year) — group(1)=저자, group(2)=연도
        if m.group(1) is not None and m.group(1).strip():
            author = m.group(1).strip().rstrip(',')
            year = m.group(2)
        else:
            # 패턴2: Author (Year) — group(3)=저자, group(4)=연도
            author = m.group(3).strip()
            year = m.group(4)
        markers.append({
            'type': 'author_year',
            'value': f"{author}, {year}",
            'span': (m.start(), m.end()),
            'raw': m.group(0),
        })

    # 위치 순으로 정렬
    markers.sort(key=lambda x: x['span'][0])
    return markers


def extract_claims_from_text(text: str, page: int = 0) -> List[Dict[str, Any]]:
    """
    본문 텍스트에서 인용 표지가 붙은 주장 문장을 추출.
    
    반환: [
        {
            'claim': 주장 문장 텍스트,
            'marker_type': 'number' | 'author_year',
            'marker_value': 표지 값,
            'marker_raw': 표지 원문,
            'page': 페이지,
        },
        ...
    ]
    한 문장에 표지가 여러 개면 표지별로 각각 1건.
    """
    if not text:
        return []

    sentences = split_sentences(text)
    results: List[Dict[str, Any]] = []

    for sent in sentences:
        markers = find_claim_markers(sent)
        if not markers:
            continue
        for m in markers:
            results.append({
                'claim': sent.strip(),
                'marker_type': m['type'],
                'marker_value': m['value'],
                'marker_raw': m['raw'],
                'page': page,
            })

    return results


# ── element 리스트 처리 ───────────────────────────────────────────────────────

def extract_claims_from_elements(
    elements: List[Dict[str, Any]],
    body_category_prefixes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Document Parse elements 리스트에서 본문 element만 골라
    인용 표지가 붙은 주장 문장을 추출.

    body_category_prefixes: 본문으로 간주할 category 접두어 목록.
    기본값은 ['body', 'text', 'paragraph'].
    """
    if body_category_prefixes is None:
        body_category_prefixes = ['body', 'text', 'paragraph']

    results: List[Dict[str, Any]] = []

    for el in elements:
        cat = el.get('category', '')
        cat_str = str(cat).lower() if cat else ''

        # 본문 category 여부 확인
        is_body = any(cat_str.startswith(p) for p in body_category_prefixes)
        if not is_body:
            continue

        text = get_text(el)
        if not text or not text.strip():
            continue

        page = get_page(el)
        claims = extract_claims_from_text(text, page)
        results.extend(claims)

    return results


# ── 파일 입출력 ───────────────────────────────────────────────────────────────

def load_elements(path: str) -> List[Dict[str, Any]]:
    """Document Parse 응답 JSON 파일에서 elements 추출."""
    with open(path, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    if 'elements' in payload:
        return payload['elements']
    if 'content' in payload and isinstance(payload['content'], dict):
        content = payload['content']
        if 'elements' in content:
            return content['elements']
    if isinstance(payload, list):
        return payload
    for key in ('data', 'result', 'response'):
        if key in payload:
            sub = payload[key]
            if isinstance(sub, list):
                return sub
            if isinstance(sub, dict) and 'elements' in sub:
                return sub['elements']
    raise ValueError(f"elements를 찾을 수 없음: {path}")


def extract_claims_from_file(path: str) -> List[Dict[str, Any]]:
    """Document Parse 응답 JSON 파일에서 본문 주장 추출."""
    elements = load_elements(path)
    return extract_claims_from_elements(elements)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("사용법: python extract_claims.py <docparse_response.json>", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    claims = extract_claims_from_file(path)
    print(f"본문 주장 {len(claims)}건:")
    for i, c in enumerate(claims, 1):
        print(f"  [{i}] ({c['marker_type']}) {c['marker_raw']} → {c['claim'][:120]}...")
