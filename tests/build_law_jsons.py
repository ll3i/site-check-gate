#!/usr/bin/env python3
"""
M8 법령 스냅샷 — iframe 본문 기반 JSON 저장 스크립트
브라우저에서 확보한 5개 법률 본문 텍스트를 파싱해 assets/law/에 JSON 저장한다.
"""

import json
import os
import re
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAW_DIR = os.path.join(ROOT, "assets", "law")
os.makedirs(LAW_DIR, exist_ok=True)

TODAY = date.today().isoformat()

# 원천 텍스트 파일 목록 (tests/ 디렉토리 내 raw 텍스트)
LAW_FILES = {
    "노동조합 및 노동관계조정법": os.path.join(HERE, "노동조합 및 노동관계조정법.txt"),
    "파견근로자 보호 등에 관한 법률": os.path.join(HERE, "파견근로자 보호 등에 관한 법률.txt"),
    "산업안전보건법": os.path.join(HERE, "산업안전보건법.txt"),
    "근로기준법": os.path.join(HERE, "근로기준법.txt"),
    "중대재해 처벌 등에 관한 법률": os.path.join(HERE, "중대재해 처벌 등에 관한 법률.txt"),
}

# 출처 URL
SOURCE_URLS = {
    "노동조합 및 노동관계조정법": "https://www.law.go.kr/법령/노동조합및노동관계조정법",
    "파견근로자 보호 등에 관한 법률": "https://www.law.go.kr/법령/파견근로자보호등에관한법률",
    "산업안전보건법": "https://www.law.go.kr/법령/산업안전보건법",
    "근로기준법": "https://www.law.go.kr/법령/근로기준법",
    "중대재해 처벌 등에 관한 법률": "https://www.law.go.kr/법령/중대재해처벌법",
}


def parse_articles(raw_text: str) -> list[dict]:
    """브라우저 iframe 본문 텍스트에서 조문 배열을 추출한다."""
    lines = raw_text.split("\n")
    articles = []
    current = None  # type: dict | None
    body = []  # 현재 조문의 본문 라인들

    def flush():
        if current is not None and body:
            cur_body = "\n".join(body).strip()
            if cur_body:
                current["항"] = [cur_body]
                articles.append(current)

    for line in lines:
        s = line.strip()
        if not s:
            continue

        # 조문 헤더 인라인 패턴: "제n조(제목) ..." 또는 "제n조(제목)"
        inline = re.match(r"^(제\d+조(?:의\d+)?)\s*\(([^)]*)\)\s*(.+)", s)
        if inline:
            flush()
            current = {"조": inline.group(1), "제목": inline.group(2), "항": []}
            body = [inline.group(3)] if inline.group(3) else []
            continue

        # 조문 헤더 단독 패턴
        alone = re.match(r"^(제\d+조(?:의\d+)?)\s*$", s)
        if alone:
            flush()
            current = {"조": alone.group(1), "제목": "", "항": []}
            body = []
            continue

        # 장(章) 제목 → 현재 조문 종료 처리
        if re.match(r"^제\d+장\s", s):
            flush()
            current = None
            body = []
            continue

        # 부 칙 처리
        if s.startswith("부      칙") or s.startswith("부칙"):
            flush()
            current = None
            body = []
            continue

        # 개정 이력 등
        if re.match(r"^\[(개정|신설|삭제|전부개정|일부개정|시행).*\]", s):
            if current is not None:
                body.append(s)
            continue

        # 조문 본문
        if current is not None:
            body.append(s)

    flush()
    return articles


def build_json(law_name: str, raw_text: str) -> dict:
    시행_match = re.search(r"\[시행\s+(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})\s*\]", raw_text)
    시행일 = 시행_match.group(1).replace(" ", "") if 시행_match else "미확인"

    law_no_match = re.search(r"\[법률\s+제(\d+)호", raw_text)
    법률번호 = f"법률 제{law_no_match.group(1)}호" if law_no_match else ""

    articles = parse_articles(raw_text)

    # 폐지된 조문(예: 제40조 삭제)은 본문에서 "삭제"로 시작하는 경우가 있음.
    # 제목이 "삭제"인 조문은 제외하거나 본문 없이 남긴다.

    return {
        "법령명": law_name,
        "시행일": 시행일,
        "법률번호": 법률번호,
        "조문": articles,
        "출처URL": SOURCE_URLS[law_name],
        "확보일": TODAY,
    }


def main():
    results = []
    for law_name, raw_path in LAW_FILES.items():
        if not os.path.exists(raw_path):
            print(f"[경고] {law_name}: 원천 텍스트 파일이 없습니다 (raw_path={raw_path})")
            continue
        with open(raw_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        data = build_json(law_name, raw_text)

        # 파일명 생성
        safe_name = re.sub(r"[^a-zA-Z0-9가-힣]", "_", law_name).replace("__", "_")
        out_path = os.path.join(LAW_DIR, f"{safe_name}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        results.append((law_name, len(data["조문"]), out_path, data["시행일"], data["법률번호"]))
        print(f"저장: {os.path.basename(out_path)} | 조문 {len(data['조문'])}개 | 시행 {data['시행일']} | {data['법률번호']}")

    # 요약 보고
    print()
    print("=" * 70)
    print("M8 법령 스냅샷 수집 결과")
    print("=" * 70)
    print(f"확보일: {TODAY}")
    print(f"저장 위치: {LAW_DIR}")
    print()
    print(f"{'법령명':<30} {'조문 수':<8} {'파일'}")
    print("-" * 90)
    total = 0
    for name, cnt, path, _, _ in results:
        rel = os.path.relpath(path, ROOT)
        print(f"{name:<30} {cnt:<8} {rel}")
        total += cnt
    print("-" * 90)
    print(f"{'합계':<30} {total:<8}")
    print()

    # 파일 목록
    print("파일 목록:")
    for fname in sorted(os.listdir(LAW_DIR)):
        fpath = os.path.join(LAW_DIR, fname)
        size = os.path.getsize(fpath)
        print(f"  {fname} ({size:,} bytes)")


if __name__ == "__main__":
    main()
