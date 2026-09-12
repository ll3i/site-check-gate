#!/usr/bin/env python3
"""
parse_refs.py — 참고문헌 목록 텍스트를 항목별 구조(JSON)로 분해한다.

사용법:
    python parse_refs.py <txt> [--json work/refs.json] [--mode auto|numbered|paragraphs|lines]

순수 표준 라이브러리만 사용 (urllib, json, re, difflib, time, sys, os).

출력 필드 (항목 하나):
    id, raw, doi, arxiv, url, year, title, first_author, kind,
    confidence (0.0~1.0), notes []
"""

import re
import json
import sys
import os
import argparse


# ── 상수 ──────────────────────────────────────────────────────────────────────
# DOI: 10.접두어/슬러그  (끝 구두점 제거)
DOI_RE = re.compile(
    r'(?:doi:|https?://doi\.org/)?10\.\d{4,9}/[^\s"<>)]+',
    re.IGNORECASE,
)
# 끝에 붙는 마침표·쉼표·괄호·세미콜론 제거
DOI_TRAIL = re.compile(r'[.,;:)]+$')

# arXiv: arXiv:1706.03762 또는 arxiv.org/abs/1706.03762
ARXIV_ABS_RE = re.compile(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', re.IGNORECASE)
ARXIV_PREFIX_RE = re.compile(r'(?:arXiv|arxiv)[:\-]\s*(\d{4}\.\d{4,5}(?:v\d+)?)', re.IGNORECASE)

# URL (http/https) — doi.org 제외
URL_RE = re.compile(r'https?://(?!doi\.org)[^\s"<>)]+')

# 연도: 4자리 19xx/20xx, 또는 (2015) 형태
YEAR_BRACKET_RE = re.compile(r'\(?\b(19[5-9]\d|20[0-4]\d)\b\)?')
YEAR_STANDALONE_RE = re.compile(r'\b(19[5-9]\d|20[0-4]\d)\b')

# 제목 후보: 따옴표 안 / APA "(연도). 제목." / 가장 긴 문장형 조각
QUOTED_TITLE_RE = re.compile(r'''[""]([^""]+)[""]''', re.UNICODE)
APA_TITLE_RE = re.compile(r'\(\d{4}\)\s*\.\s*(.+)', re.UNICODE)

# 제1저자: 첫 쉼표 앞 영문 성 / 첫 2~5자 한글
FIRST_AUTHOR_EN_RE = re.compile(r'^\s*([A-Z][a-zà-ü]{1,})\s*,', re.UNICODE)
FIRST_AUTHOR_KO_RE = re.compile(r'^\s*([가-힣]{2,5})\s*[,\(·](\s*[가-힣]{2,5})', re.UNICODE)


# ── 작은 유틸 ──────────────────────────────────────────────────────────────────
def strip_trailing_punct(s: str) -> str:
    """문자열 끝의 인용·부호 구두점을 정리한다."""
    s = s.rstrip()
    # 맨 뒤가 문자/숫자가 아닐 때까지 제거
    while s and not s[-1].isalnum() and s[-1] not in '”’"\'\-–—':
        s = s[:-1]
    return s.strip()


def clean_doi(raw: str) -> str:
    """DOI 정규식에서 나온 값을 doi.org 표준 형태로 정리."""
    d = DOI_TRAIL.sub('', raw).strip()
    if d.lower().startswith('doi:'):
        d = d[4:]
    if d.lower().startswith('https://doi.org/'):
        d = d[len('https://doi.org/'):]
    return d.strip()


# ── 항목 파서 ──────────────────────────────────────────────────────────────────
def parse_item(text: str, idx: int) -> dict:
    """한 줄/문단에서 하나의 참고문헌 항목을 추출한다."""
    raw = text.strip()
    if not raw:
        return None

    item = {
        'id': idx,
        'raw': raw,
        'doi': None,
        'arxiv': None,
        'url': None,
        'year': None,
        'title': None,
        'first_author': None,
        'kind': None,
        'confidence': 0.5,       # 기본 자신감을 낮게 잡고 증거를 누적
        'notes': [],
    }

    notes = item['notes']

    # ── DOI ───────────────────────────────────────────────────────────────────
    doi_m = DOI_RE.search(raw)
    if doi_m:
        item['doi'] = clean_doi(doi_m.group(0))
        notes.append('DOI 발견')
        # DOI가 있으면 confidence 상향 (단, 가짜일 가능성 있으므로 0.7)
        item['confidence'] = max(item['confidence'], 0.7)

    # ── arXiv ─────────────────────────────────────────────────────────────────
    arxiv_abs = ARXIV_ABS_RE.search(raw)
    arxiv_pref = ARXIV_PREFIX_RE.search(raw)
    if arxiv_abs:
        item['arxiv'] = arxiv_abs.group(1)
        notes.append('arXiv ID 발견 (abs URL)')
        item['confidence'] = max(item['confidence'], 0.85)
    elif arxiv_pref:
        item['arxiv'] = arxiv_pref.group(1)
        notes.append('arXiv ID 발견 (접두어)')
        item['confidence'] = max(item['confidence'], 0.85)

    # ── URL ───────────────────────────────────────────────────────────────────
    url_m = URL_RE.search(raw)
    if url_m:
        item['url'] = url_m.group(0).rstrip('.,;:)]')
        notes.append('URL 발견')

    # ── 연도 ───────────────────────────────────────────────────────────────────
    yr_bracket = YEAR_BRACKET_RE.search(raw)
    yr_standalone = YEAR_STANDALONE_RE.search(raw)
    # 괄호 안 연도가 있으면 우선 사용
    if yr_bracket:
        item['year'] = yr_bracket.group(1)
        notes.append(f'연도 발견(괄호): {item["year"]}')
        item['confidence'] = max(item['confidence'], 0.65)
    elif yr_standalone:
        # 문단형에서 가장 앞쪽의 4자리 연도를 취함
        item['year'] = yr_standalone.group(1)
        notes.append(f'연도 발견: {item["year"]}')
        item['confidence'] = max(item['confidence'], 0.55)

    # ── 제목 ───────────────────────────────────────────────────────────────────
    # 1순위: 따옴표 제목
    quoted = QUOTED_TITLE_RE.findall(raw)
    if quoted:
        # 인용문 중 가장 긴 것 선택
        item['title'] = max(quoted, key=len).strip()
        notes.append('제목 발견(따옴표)')
        item['confidence'] = max(item['confidence'], 0.75)

    # 2순위: APA "(연도). 제목." 패턴
    if not item['title']:
        apa = APA_TITLE_RE.search(raw)
        if apa:
            title_from_apa = strip_trailing_punct(apa.group(1)).strip()
            # 너무 짧으면 무시
            if len(title_from_apa) >= 8:
                item['title'] = title_from_apa
                notes.append('제목 발견(APA 패턴)')
                item['confidence'] = max(item['confidence'], 0.65)

    # 3순위: 가장 긴 문장형 조각 (끝 구두점 이전, 15자 이상)
    if not item['title']:
        # DOI/arXiv/연도/저자 패턴을 제거한 나머지에서 가장 긴 조각
        cleaned = re.sub(r'\(?\d{4}\)?', '', raw)
        cleaned = DOI_RE.sub('', cleaned)
        cleaned = ARXIV_ABS_RE.sub('', cleaned)
        cleaned = ARXIV_PREFIX_RE.sub('', cleaned)
        cleaned = URL_RE.sub('', cleaned)
        # 문장 분리 (마침표· 세미콜론)
        fragments = re.split(r'[.;]\s*', cleaned)
        longest = max(
            [f.strip() for f in fragments if len(f.strip()) >= 10],
            key=len,
            default=None,
        )
        if longest:
            item['title'] = strip_trailing_punct(longest).strip()
            item['title'] = item['title'][:200]  # 과도한 길이 제한
            notes.append('제목 발견(가장 긴 조각)')
            item['confidence'] = max(item['confidence'], 0.45)

    # ── 제1저자 ────────────────────────────────────────────────────────────────
    # 영문 형식: "성, 이름" — 첫 줄 기준으로 앞쪽 성을 추출
    first_line = raw.split('\n')[0].strip()
    en_match = FIRST_AUTHOR_EN_RE.match(first_line)
    if en_match:
        item['first_author'] = en_match.group(1)
        notes.append(f'제1저자(영문) 추출: {item["first_author"]}')
        item['confidence'] = max(item['confidence'], 0.6)

    # 국문 형식: "김철수, 이영희" 형태에서 첫 인명
    ko_match = FIRST_AUTHOR_KO_RE.match(first_line)
    if ko_match:
        item['first_author'] = ko_match.group(1)
        notes.append(f'제1저자(국문) 추출: {item["first_author"]}')
        item['confidence'] = max(item['confidence'], 0.6)

    # 영문 저자명이 없지만 첫 단어가 대문자 시작이고 3~15자이면 추정
    if not item['first_author']:
        word = first_line.split()[0] if first_line.split() else ''
        if len(word) >= 3 and len(word) <= 15 and word[0].isupper() and word.isalpha():
            item['first_author'] = word
            notes.append(f'제1저자 추정: {item["first_author"]}')
            item['confidence'] = max(item['confidence'], 0.35)

    # ── 종류(kinds) ────────────────────────────────────────────────────────────
    lower = raw.lower()
    if any(w in lower for w in ['press', 'publisher', 'mit press', 'oup', 'springer', 'wiley', 'elsevier', 'academic', 'pub']):
        item['kind'] = 'book'
        notes.append('종류: 단행본(출판사 언급)')
    if any(w in lower for w in ['retrieved', '접속일', '접속', 'accessed', 'retrieved on']):
        item['kind'] = 'web'
        notes.append('종류: 웹(접속일 언급)')
    if any(w in lower for w in ['report', '보고서', 'technical report', 'tech report', 'working paper']):
        item['kind'] = 'report'
        notes.append('종류: 보고서')
    if any(w in lower for w in ['journal of', 'transact', 'review', 'proceedings', 'conference', 'annual', 'vol.', 'pp.', 'doi']):
        if item['kind'] is None:
            item['kind'] = 'article'
            notes.append('종류: 논문(저널/학회 언급)')
    if any(w in lower for w in ['arxiv', 'preprint']):
        if item['kind'] is None:
            item['kind'] = 'article'
            notes.append('종류: 논문(arXiv/preprint)')

    # DOI/arXiv만 있고 종류 단서 없으면 article 가정
    if item['kind'] is None:
        if item['doi'] or item['arxiv']:
            item['kind'] = 'article'
            notes.append('종류: article (DOI/arXiv 기반)')
        elif item['url']:
            item['kind'] = 'web'
            notes.append('종류: web (URL 기반)')

    # ── confidence 종합 ────────────────────────────────────────────────────────
    # 아무런 메타데이터도 못 잡았으면 낮게
    has_any_meta = bool(item['doi'] or item['arxiv'] or item['url'] or item['year'] or item['title'])
    if not has_any_meta:
        item['confidence'] = 0.2
        notes.append('메타데이터 거의 없음 — 낮은 신뢰도')
    elif item['confidence'] < 0.35:
        notes.append('부분 파편화 — 수동 확인 권장')

    return item


# ── 모드별 분리 ────────────────────────────────────────────────────────────────
def split_numbered(text: str) -> list:
    """번호형: "1. ...", "2) ...", "[1] ..." 등으로 시작하는 줄."""
    items = []
    # 번호 패턴: 선행 공백 + (숫자+구분자) + 공백/탭
    num_re = re.compile(
        r'^\s*(?:\d+[\.\)\:\]]|\[\d+\])\s+',
        re.MULTILINE,
    )
    # 번호로 시작하는 행을 분할
    for line in text.split('\n'):
        if num_re.match(line) and len(line.strip()) > 5:
            items.append(line.strip())
    return items


def split_paragraphs(text: str) -> list:
    """단락형: 빈 줄로 구분된 각 단락이 하나의 참고문헌."""
    items = []
    for para in re.split(r'\n\s*\n+', text):
        p = para.strip()
        if p and len(p) > 5:
            items.append(p)
    return items


def split_lines(text: str) -> list:
    """한 줄형: 각 줄이 하나의 참고문헌 (빈 줄 무시)."""
    items = []
    for line in text.split('\n'):
        if line.strip() and len(line.strip()) > 5:
            items.append(line.strip())
    return items


def split_auto(text: str) -> list:
    """자동 모드: 번호형 우선 시도 → 실패 시 단락형 → 줄형."""
    numbered = split_numbered(text)
    if numbered:
        return numbered
    paragraphs = split_paragraphs(text)
    if paragraphs:
        return paragraphs
    return split_lines(text)


# ── 머리말 무시 ────────────────────────────────────────────────────────────────
def trim_preamble(text: str) -> str:
    """첫 번호 항목(또는 첫 실질적 문단) 이전의 머리말/도입 줄을 제거."""
    lines = text.split('\n')
    # 가장 먼저 실질적 후보(길이 8+, 숫자+구분자 or DOI/arXiv 포함 or 따옴표 포함)가 나오는 지점부터 유지
    keep_from = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if len(s) < 8:
            continue
        if re.match(r'^\s*(?:\d+[\.\)\:\]]|\[\d+\])\s+', s):
            keep_from = i
            break
        if DOI_RE.search(s) or ARXIV_ABS_RE.search(s) or ARXIV_PREFIX_RE.search(s):
            keep_from = i
            break
    return '\n'.join(lines[keep_from:])


# ── 메인 ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='참고문헌 목록 텍스트 → 항목별 구조 JSON',
    )
    parser.add_argument('txt', help='입력 텍스트 파일 경로')
    parser.add_argument('--json', default='work/refs.json',
                        help='출력 JSON 경로 (기본: work/refs.json)')
    parser.add_argument('--mode', default='auto',
                        choices=['auto', 'numbered', 'paragraphs', 'lines'],
                        help='항목 분리 모드')
    args = parser.parse_args()

    # 입력 파일 확인
    if not os.path.isfile(args.txt):
        print(f"오류: 파일 없음 — {args.txt}", file=sys.stderr)
        sys.exit(2)

    with open(args.txt, encoding='utf-8') as f:
        raw_text = f.read()

    if not raw_text.strip():
        print("오류: 빈 입력 파일", file=sys.stderr)
        sys.exit(2)

    # 머리말 제거
    cleaned = trim_preamble(raw_text)

    # 모드별 분리
    if args.mode == 'numbered':
        items_text = split_numbered(cleaned)
    elif args.mode == 'paragraphs':
        items_text = split_paragraphs(cleaned)
    elif args.mode == 'lines':
        items_text = split_lines(cleaned)
    else:
        items_text = split_auto(cleaned)

    if not items_text:
        print("오류: 참고문헌 항목을 찾을 수 없음 (0건)", file=sys.stderr)
        sys.exit(3)

    items = []
    for idx, txt in enumerate(items_text, start=1):
        item = parse_item(txt, idx)
        if item:
            items.append(item)

    if not items:
        print("오류: 파싱 결과 0건", file=sys.stderr)
        sys.exit(3)

    # JSON 출력
    out_obj = {
        'meta': {
            'source': args.txt,
            'mode': args.mode,
            'count': len(items),
        },
        'items': items,
    }

    out_dir = os.path.dirname(args.json)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.json, 'w', encoding='utf-8') as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

    # 요약 출력
    print(f"파싱 완료: {len(items)}건")
    low_conf = [i for i in items if i['confidence'] < 0.5]
    if low_conf:
        print(f"주의: 신뢰도 낮은 항목 {len(low_conf)}건 — 수동 확인 권장")
        for i in low_conf:
            print(f"  [{i['id']}] confidence={i['confidence']:.2f} | "
                  f"title={i['title'][:40] if i['title'] else '(없음)'} | "
                  f"notes: {'; '.join(i['notes'])}")

    sys.exit(0)


if __name__ == '__main__':
    main()
