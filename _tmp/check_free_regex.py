#!/usr/bin/env python3
import re

# 새 Free 법명+조문 결합 regex
_FREE_LAW_WITH_ARTICLE = re.compile(
    r"(?<![가-힣a-zA-Z_0-9])"
    r"([가-힣a-zA-Z]+(?:[\s·&]+(?![가-힣a-zA-Z]*?(?:法|법|法律))[가-힣a-zA-Z]+)*?"
    r"[가-힣a-zA-Z]*?(?:法|법|法律))"
    r"(?:施?行?令|規則)?"
    r"\s*"
    r"제\s*(\d+)\s*조"
    r"(?:\s*제\s*(\d+)\s*항|\s*의\s*(\d+))?"
    r"(?![가-힣a-zA-Z_0-9])"
)

tests = [
    ("「근로기준법」 제11조를 근거로 하며 근로기준법 제11조도 같다.",
     "블록+프리 중복 상황"),
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
     "법령 인용 없음 (매칭 없어야 함)"),
]

for text, desc in tests:
    print(f"【{desc}】")
    print(f"  text: {text!r}")
    for m in _FREE_LAW_WITH_ARTICLE.finditer(text):
        law = m.group(1)
        art = int(m.group(2))
        para = m.group(3) or m.group(4)
        para = int(para) if para else None
        print(f"    law={law!r} art={art} para={para} span=({m.start()},{m.end()})")
    print()
