#!/usr/bin/env python3
"""
link_check.py — 본문 표지 집합 vs 참고문헌 항목 집합 대조 → 미인용 / 목록 누락. 결정론.
"""

import json
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

# ── 상수 ──────────────────────────────────────────────────────────────────────

# 본문에서 인용 표지 추출 패턴
NUMBER_MARK_RE = re.compile(r'\[(\d+)\]')
AUTHOR_YEAR_MARK_RE = re.compile(
    r'\(([^)]{1,40}),?\s*(\d{4})\)'
    r'|'
    r'([A-Za-z가-힣][^.]{1,40})\s+\((\d{4})\)'
)

# 참고문헌 항목의 표지 추출 패턴 (참고문헌 텍스트에서)
REF_NUMBER_MARK_RE = re.compile(r'^\s*\[(\d+)\]\s*', re.MULTILINE)
REF_NUMBERED_MARK_RE = re.compile(r'^\s*(\d+)\.\s*', re.MULTILINE)
REF_AUTHOR_YEAR_START_RE = re.compile(
    r'^\s*([A-Za-z가-힣][^)]{0,40})\s*[,]?\s*(\d{4})'
)


# ── 본문 인용 표지 추출 ──────────────────────────────────────────────────────

def extract_body_markers(text: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    본문 텍스트에서 인용 표지([n], (저자, 연도))를 추출.
    
    반환: {
        'number': [{'value': '1', 'raw': '[1]', 'spans': [(s,e),...]}, ...],
        'author_year': [{'value': '홍길동, 2021', 'raw': '(홍길동, 2021)', 'spans': [...]}, ...],
    }
    """
    number_markers: List[Dict[str, Any]] = []
    author_year_markers: List[Dict[str, Any]] = []

    for m in AUTHOR_YEAR_MARK_RE.finditer(text):
        # 패턴1: (저자, Year) — group(1)=저자, group(2)=연도
        if m.group(1) is not None and m.group(1).strip():
            author = m.group(1).strip().rstrip(',')
            year = m.group(2)
        else:
            # 패턴2: Author (Year) — group(3)=저자, group(4)=연도
            author = m.group(3).strip()
            year = m.group(4)
        author_year_markers.append({
            'value': f"{author}, {year}",
            'raw': m.group(0),
            'spans': [(m.start(), m.end())],
        })

    for m in AUTHOR_YEAR_MARK_RE.finditer(text):
        # 패턴1: (저자, Year) — group(1)=저자, group(2)=연도
        if m.group(1) is not None and m.group(1).strip():
            author = m.group(1).strip().rstrip(',')
            year = m.group(2)
        else:
            # 패턴2: Author (Year) — group(3)=저자, group(4)=연도
            author = m.group(3).strip()
            for m in AUTHOR_YEAR_MARK_RE.finditer(text):
                # 패턴1: (저자, Year) — group(1)=저자, group(2)=연도
                if m.group(1) is not None and m.group(1).strip():
                    author = m.group(1).strip().rstrip(',')
                    year = m.group(2)
                else:
                    # 패턴2: Author (Year) — group(3)=저자, group(4)=연도
                    author = m.group(3).strip()
                    year = m.group(4)
                author_year_markers.append({
                    'value': f"{author}, {year}",
                    'raw': m.group(0),
                    'spans': [(m.start(), m.end())],
                })

    return {
        'number': number_markers,
        'author_year': author_year_markers,
    }


# ── 참고문헌 항목 표지 추출 ──────────────────────────────────────────────────

def extract_ref_markers(ref_text: str) -> Optional[Dict[str, Any]]:
    """
    참고문헌 항목 하나의 텍스트에서 표지 정보 추출.
    
    반환: {
        'type': 'number' | 'author_year' | None,
        'value': 표지 값 (예: '1' 또는 '홍길동, 2021'),
        'raw': 표지 원문,
    }
    표지가 없으면 None.
    """
    # 번호 표지 ([n] 또는 n.)
    m = REF_NUMBER_MARK_RE.search(ref_text)
    if m:
        return {
            'type': 'number',
            'value': m.group(1),
            'raw': m.group(0),
        }

    m = REF_NUMBERED_MARK_RE.search(ref_text)
    if m:
        return {
            'type': 'number',
            'value': m.group(1),
            'raw': m.group(0),
        }

    # 저자-연도 표지 (첫 줄이 저자로 시작하고 연도 괄호 있음)
    first_line = ref_text.split('\n')[0].strip()
    m = REF_AUTHOR_YEAR_START_RE.match(first_line)
    if m:
        return {
            'type': 'author_year',
            'value': f"{m.group(1)}, {m.group(2)}",
            'raw': m.group(0),
        }

    return None


# ── 연결 검사 메인 ────────────────────────────────────────────────────────────

def check_links(
    body_text: str,
    ref_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    본문 인용 표지 집합 vs 참고문헌 항목 집합 대조.
    
    ref_items: [{'text': ..., 'id': ...}, ...] 또는 [{'text': ...}, ...]
    
    반환: {
        'body_number_markers': [값의 리스트],
        'body_author_year_markers': [값의 리스트],
        'ref_number_markers': [값의 리스트],
        'ref_author_year_markers': [값의 리스트],
        'uncited': [{'type': ..., 'value': ..., 'ref_id': ...}, ...],  # 목록에는 있는데 본문에 없음
        'missing_from_refs': [{'type': ..., 'value': ..., 'body_span': ...}, ...],  # 본문에는 있는데 목록에 없음
        'summary': {
            'body_numbers': int,
            'body_author_years': int,
            'ref_numbers': int,
            'ref_author_years': int,
            'uncited_count': int,
            'missing_count': int,
        },
    }
    """
    # 본문 표지 추출
    body = extract_body_markers(body_text)
    body_numbers = {m['value']: m for m in body['number']}
    body_author_years = {m['value']: m for m in body['author_year']}

    # 참고문헌 표지 추출
    ref_numbers: Dict[str, Dict[str, Any]] = {}
    ref_author_years: Dict[str, Dict[str, Any]] = {}
    ref_id_map: Dict[str, Any] = {}  # value -> ref item

    for ref in ref_items:
        ref_id = ref.get('id', '')
        ref_text = ref.get('text', '')
        marker = extract_ref_markers(ref_text)

        if marker is None:
            continue

        if marker['type'] == 'number':
            ref_numbers[marker['value']] = marker
            ref_id_map[marker['value']] = ref
        elif marker['type'] == 'author_year':
            ref_author_years[marker['value']] = marker
            ref_id_map[marker['value']] = ref

    # 미인용: ref에는 있으나 body에 없음
    uncited: List[Dict[str, Any]] = []
    for val, marker in ref_numbers.items():
        if val not in body_numbers:
            ref_id = ref_id_map.get(val, {}).get('id', '')
            uncited.append({
                'type': 'number',
                'value': val,
                'ref_id': ref_id,
                'ref_text': ref_id_map.get(val, {}).get('text', '')[:200],
            })

    for val, marker in ref_author_years.items():
        if val not in body_author_years:
            ref_id = ref_id_map.get(val, {}).get('id', '')
            uncited.append({
                'type': 'author_year',
                'value': val,
                'ref_id': ref_id,
                'ref_text': ref_id_map.get(val, {}).get('text', '')[:200],
            })

    # 목록 누락: body에는 있으나 ref에 없음
    missing: List[Dict[str, Any]] = []
    for val, marker in body_numbers.items():
        if val not in ref_numbers:
            missing.append({
                'type': 'number',
                'value': val,
                'raw': marker['raw'],
                'spans': marker['spans'],
            })

    for val, marker in body_author_years.items():
        if val not in ref_author_years:
            missing.append({
                'type': 'author_year',
                'value': val,
                'raw': marker['raw'],
                'spans': marker['spans'],
            })

    return {
        'body_number_markers': list(body_numbers.keys()),
        'body_author_year_markers': list(body_author_years.keys()),
        'ref_number_markers': list(ref_numbers.keys()),
        'ref_author_year_markers': list(ref_author_years.keys()),
        'uncited': uncited,
        'missing_from_refs': missing,
        'summary': {
            'body_numbers': len(body_numbers),
            'body_author_years': len(body_author_years),
            'ref_numbers': len(ref_numbers),
            'ref_author_years': len(ref_author_years),
            'uncited_count': len(uncited),
            'missing_count': len(missing),
        },
    }


# ── 파일 입출력 ───────────────────────────────────────────────────────────────

def load_refs(path: str) -> List[Dict[str, Any]]:
    """참고문헌 JSON 파일에서 항목 리스트 로드."""
    with open(path, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    if 'items' in payload:
        return payload['items']
    if isinstance(payload, list):
        return payload
    return []


def load_body_text(path: str) -> str:
    """텍스트 파일에서 본문 로드."""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("사용법: python link_check.py <body_text.txt|docparse.json> <refs.json>",
              file=sys.stderr)
        sys.exit(2)

    body_path = sys.argv[1]
    refs_path = sys.argv[2]

    # 본문: 텍스트 파일 또는 docparse JSON
    if body_path.endswith('.json'):
        elements = load_elements(body_path)
        # 본문 element만 필터링
        body_category_prefixes = ['body', 'text', 'paragraph']
        body_texts = []
        for el in elements:
            cat = str(el.get('category', '')).lower()
            if any(cat.startswith(p) for p in body_category_prefixes):
                text = el.get('text', el.get('content', ''))
                if text:
                    body_texts.append(text)
        body_text = '\n'.join(body_texts)
    else:
        body_text = load_body_text(body_path)

    refs = load_refs(refs_path)

    result = check_links(body_text, refs)

    print(f"본문 번호 표지: {result['body_number_markers']}")
    print(f"본문 저자-연도 표지: {result['body_author_year_markers']}")
    print(f"참고문헌 번호 표지: {result['ref_number_markers']}")
    print(f"참고문헌 저자-연도 표지: {result['ref_author_year_markers']}")
    print(f"\n미인용: {result['summary']['uncited_count']}건")
    for u in result['uncited']:
        print(f"  - [{u['type']}] {u['value']} (ref_id={u['ref_id']})")
    print(f"\n목록 누락: {result['summary']['missing_count']}건")
    for m in result['missing_from_refs']:
        print(f"  - [{m['type']}] {m['value']} (raw={m['raw']})")
