#!/usr/bin/env python3
import re

# 구 free regex
OLD_FREE = re.compile(
    r'(?<![가-힣a-zA-Z_0-9])'
    r'([가-힣a-zA-Z]+(?:[\s·&]{1,3}[가-힣a-zA-Z]+)*?(?:法|법|법률)(?:施?行?令|規則)?)'
    r'(?![가-힣a-zA-Z_0-9])'
)

# 새 free regex (마지막 단어가 法/법/법률인 단어열 + 시행령/시행규칙 접미)
NEW_FREE = re.compile(
    r'(?<![가-힣a-zA-Z_0-9])'
    r'(?:[가-힣a-zA-Z]+[\s·&]+)*'          # 중간 단어들
    r'[가-힣a-zA-Z]*?(?:法|법|법률)'        # 마지막 단어 (法/법/법률)
    r'(?:施?行?令|規則)?'                   # 시행령/시행규칙 접미
    r'(?![가-힣a-zA-Z_0-9])'
)

ARTICLE = re.compile(
    r'제\s*(\d+)\s*조(?:\s*제\s*(\d+)\s*항|\s*의\s*(\d+))?'
)

def extract_test(text):
    results = []
    seen = set()
    # 블록 인용
    BLOCK = re.compile(
        r'「\s*([^\」]*?(?:法|법|법률)(?:施?行?令|規則)?)\s*」'
    )
    for bm in BLOCK.finditer(text):
        law_raw = bm.group(1).strip()
        after = text[bm.end():]
        am = ARTICLE.search(after)
        if not am:
            continue
        law_norm = re.sub(r'\s+', '', law_raw)
        art = int(am.group(1))
        para = int(am.group(2)) if am.group(2) else (int(am.group(3)) if am.group(3) else None)
        key = (law_norm, art, para)
        if key in seen:
            continue
        seen.add(key)
        abs_start = bm.start()
        abs_end = bm.end() + am.end()
        results.append({
            'raw': text[abs_start:abs_end],
            'start': abs_start,
            'end': abs_end,
            'law_name_raw': law_raw,
            'article': art,
            'paragraph': para,
        })
    # 프리 인용 (블록과 겹치면 스킵)
    for fm in NEW_FREE.finditer(text):
        law_raw = fm.group(0).strip()
        start = fm.start()
        # block 결과와 겹치는지 확인 (start < block_end and end > block_start)
        if any(s <= start < e for s, e in [(r['start'], r['end']) for r in results]):
            continue
        after = text[fm.end():]
        am = ARTICLE.search(after)
        if not am:
            continue
        law_norm = re.sub(r'\s+', '', law_raw)
        art = int(am.group(1))
        para = int(am.group(2)) if am.group(2) else (int(am.group(3)) if am.group(3) else None)
        key = (law_norm, art, para)
        if key in seen:
            continue
        seen.add(key)
        abs_start = start
        abs_end = fm.end() + am.end()
        results.append({
            'raw': text[abs_start:abs_end],
            'start': abs_start,
            'end': abs_end,
            'law_name_raw': law_raw,
            'article': art,
            'paragraph': para,
        })
    return results

if __name__ == '__main__':
    tests = [
        ("「근로기준법」 제11조를 근거로 하며 근로기준법 제11조도 같다.",
         "블록+프리 중복"),
        ("파견근로자 보호 등에 관한 법률 제6조의2를 인용한다.",
         "프리 다문화 법률 + 의M"),
        ("「노동조합 및 노동관계조정법」 제2조 제1항에 따라 판단한다.",
         "블록+다항"),
        ("「산업안전보건법」 제38조를 검토한다.",
         "블록 단일"),
        ("「중대재해 처벌 등에 관한 법률」 제4조를 인용한다.",
         "블록 중대재해법"),
        ("근로기준법 제11조를 근거로 한다.",
         "프리 단일 법제처"),
        ("원청이 직접 작업 지시를 하였다.",
         "법령 인용 없음"),
    ]
    for text, desc in tests:
        print(f'【{desc}】')
        print(f'  text: {text!r}')
        refs = extract_test(text)
        print(f'  extracted: {len(refs)}')
        for i, r in enumerate(refs):
            print(f'    [{i}] start={r["start"]} end={r["end"]} law={r["law_name_raw"]!r} art={r["article"]} para={r["paragraph"]} raw={r["raw"]!r}')
        print()
