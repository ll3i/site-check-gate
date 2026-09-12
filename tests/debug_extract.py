#!/usr/bin/env python3
import sys, json, hashlib, re
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))

from service.core.extract_refs import (
    load_docparse_json,
    extract_references_from_elements,
    get_element_text,
    get_element_category,
    get_element_box,
    get_page,
    make_sort_key,
    is_heading_element,
    is_excluded_category,
    is_number_marked,
    is_author_year_bib,
    classify_element,
    split_by_number_mark,
    merge_lines_in_element,
)

def find_cache(name):
    pdf = Path('tests/fixtures') / name
    stat = pdf.stat()
    raw = f'{pdf}:{stat.st_size}:{stat.st_mtime}'
    key = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return Path('tests/fixtures/cache') / f'{key}.json'

for fixture in ['fixture_1col.pdf', 'fixture_2col_bracket.pdf', 'fixture_apa.pdf', 'fixture_2page.pdf']:
    cp = find_cache(fixture)
    print(f'\n===== {fixture} =====')
    elements = load_docparse_json(str(cp))
    print(f'총 elements: {len(elements)}')
    print('\n--- 정렬 전 요소 카테고리/텍스트/좌표 ---')
    for i, el in enumerate(elements):
        cat = get_element_category(el)
        text = get_element_text(el)
        box = get_element_box(el)
        page = get_page(el)
        sk = make_sort_key(el)
        marked = is_number_marked(text)
        ayb = is_author_year_bib(text)
        heading = is_heading_element(el)
        excluded = is_excluded_category(el)
        etype = classify_element(text, cat)
        t_preview = (text[:70].replace('\n', ' ') if text else '(no text)')
        print(f'  [{i:2d}] page={page} col={sk[1]} y={sk[2]:.4f} cat={cat!r} '
              f'head={heading} excl={excluded} num={marked} ayb={ayb} type={etype} box={box} | {t_preview!r}')
    print('\n--- 추출 결과 ---')
    refs = extract_references_from_elements(elements)
    print(f'추출 항목 수: {len(refs)}')
    for i, r in enumerate(refs):
        print(f'  [{i}] page={r["page"]} type={r["source_note"]} text={r["text"][:120]!r}')

