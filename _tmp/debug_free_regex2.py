#!/usr/bin/env python3
"""추가 디버깅: free law regex가 왜 '파견근로자 보호 등에 관한 법률'을 못 잡는지 분석."""
import re

FREE_LAW_RE_OLD = re.compile(
    r'(?<![가-힣a-zA-Z_0-9])'
    r'([가-힣a-zA-Z]+(?:[\s·&]{1,3}[가-힣a-zA-Z]+)*?(?:法|법|법률)(?:施?行?令|規則)?)'
    r'(?![가-힣a-zA-Z_0-9])'
)

# 개선 시도: 법/법률 앞에 \s* 허용, 마지막 단어는 '법률'까지 포함
FREE_LAW_RE_NEW = re.compile(
    r'(?<![가-힣a-zA-Z_0-9])'
    r'([가-힣a-zA-Z]+(?:[\s·&]{1,3}[가-힣a-zA-Z]+)*?\s*(?:法|법|법률)\s*(?:施?行?令|規則)?)'
    r'(?![가-힣a-zA-Z_0-9])'
)

test_cases = [
    "파견근로자 보호 등에 관한 법률 제6조의2를 인용한다.",
    "「근로기준법」 제11조를 근거로 하며 근로기준법 제11조도 같다.",
    "「노동조합 및 노동관계조정법」 제2조 제1항",
    "「산업안전보건법」 제38조",
    "「중대재해 처벌 등에 관한 법률」 제4조",
    "근로기준법 제11조를 근거로 한다.",
    "원청이 직접 작업 지시를 하였다.",
]

print("=== OLD FREE_LAW_RE ===")
for t in test_cases:
    m = FREE_LAW_RE_OLD.search(t)
    print(f"text: {t!r}")
    print(f"  match: {m.group(0) if m else None!r}")
    if m:
        print(f"  law_name: {m.group(1)!r}")
    print()

print("=== NEW FREE_LAW_RE ===")
for t in test_cases:
    m = FREE_LAW_RE_NEW.search(t)
    print(f"text: {t!r}")
    print(f"  match: {m.group(0) if m else None!r}")
    if m:
        print(f"  law_name: {m.group(1)!r}")
    print()
