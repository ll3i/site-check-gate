#!/usr/bin/env python3
"""
M8 §1: 국가법령정보센터 법령 스냅샷 수집 스크립트
대상: 노동조합 및 노동관계조정법, 파견근로자 보호 등에 관한 법률,
      산업안전보건법, 근로기준법, 중대재해처벌법
"""

import json
import re
import os
import urllib.request
import urllib.error
from datetime import date

LAW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "law")
os.makedirs(LAW_DIR, exist_ok=True)

COLLECT_DATE = date.today().isoformat()

# 법령별 기초 정보
LAWS = {
    "노동조합및노동관계조정법": {
        "name": "노동조합 및 노동관계조정법",
        "lsiSeq": "0000000254",
        "url": "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=0000000254&chrClsCD=010102",
    },
    "파견근로자보호등에관한법률": {
        "name": "파견근로자 보호 등에 관한 법률",
        "lsiSeq": "0000001499",
        "url": "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=0000001499&chrClsCD=010102",
    },
    "산업안전보건법": {
        "name": "산업안전보건법",
        "lsiSeq": "0000001501",
        "url": "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=0000001501&chrClsCD=010102",
    },
    "근로기준법": {
        "name": "근로기준법",
        "lsiSeq": "0000001500",
        "url": "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=0000001500&chrClsCD=010102",
    },
    "중대재해처벌법": {
        "name": "중대재해 처벌 등에 관한 법률",
        "lsiSeq": "0000002320",
        "url": "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=0000002320&chrClsCD=010102",
    },
}


def fetch_law_content(url: str) -> str:
    """law.go.kr 페이지에서 본문 HTML을 가져온다."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  HTTP 오류 {e.code}: {url}")
        return ""
    except urllib.error.URLError as e:
        print(f"  URL 오류: {e.reason}")
        return ""
    except Exception as e:
        print(f"  오류: {e}")
        return ""


def parse_articles(html: str) -> list:
    """
    law.go.kr HTML에서 조문 목록을 추출한다.
    실제 조문 내용이 없으면 빈 리스트를 반환한다.
    """
    articles = []
    # law.go.kr의 조문 내용은 <div id="lawContent"> 또는 유사 구조에 있다.
    # iframe 내부에 있는 경우가 많아 HTML만으로는 조문을 가져오기 어려울 수 있다.

    # 조문 제목 패턴: "제1조(목적)", "제2조(정의)" 등
    article_pattern = re.compile(r'제(\d+조(?:의\d+)?)\s*\(([^)]*)\)')
    
    # 본문에서 조문 발췌 시도
    # lawContent 영역의 텍스트 추출
    law_content_match = re.search(r'id=["\']lawContent["\'][^>]*>(.+?)</div>', html, re.DOTALL)
    if law_content_match:
        content_html = law_content_match.group(1)
        # HTML 태그 제거
        text = re.sub(r'<[^>]+>', ' ', content_html)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 조문 파싱
        for match in article_pattern.finditer(text):
            jo_num = match.group(1)
            jo_title = match.group(2)
            articles.append({
                "조문번호": jo_num,
                "조문명": jo_title,
                "내용": "",  # 실제 내용은 iframe에서 가져와야 함
            })
    
    return articles


def extract_enforcement_date(html: str) -> str:
    """시행일을 추출한다."""
    # 법령명 옆의 시행일 정보: [시행 YYYY. M. D.] [법률 제NNNNN호, YYYY. M. D., 일부개정]
    match = re.search(r'\[시행\s+(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})\]', html)
    if match:
        return match.group(1).replace(" ", "")
    return "미상"


def extract_law_number(html: str) -> str:
    """법률 번호를 추출한다."""
    match = re.search(r'\[법률\s+제(\d+)호', html)
    if match:
        return f"법률 제{match.group(1)}호"
    return "미상"


def build_law_json(law_key: str, law_info: dict, html: str) -> dict:
    """법령 JSON 객체를 생성한다."""
    return {
        "법령명": law_info["name"],
        "시행일": extract_enforcement_date(html),
        "법률번호": extract_law_number(html),
        "조문": parse_articles(html),
        "출처URL": law_info["url"],
        "확보일": COLLECT_DATE,
    }


def main():
    print("=" * 60)
    print("M8 §1 — 법령 스냅샷 수집")
    print("=" * 60)
    print(f"확보일: {COLLECT_DATE}")
    print(f"저장 디렉토리: {LAW_DIR}")
    print()

    results = []

    for law_key, law_info in LAWS.items():
        print(f"처리 중: {law_info['name']} ...")
        
        html = fetch_law_content(law_info["url"])
        if not html:
            print(f"  → 웹 fetching 실패, '미확보' 처리")
            law_json = {
                "법령명": law_info["name"],
                "시행일": "미상",
                "법률번호": "미상",
                "조문": [],
                "출처URL": law_info["url"],
                "확보일": COLLECT_DATE,
                "비고": "웹에서 조문 확보 불가 — 미확보",
            }
        else:
            articles = parse_articles(html)
            if not articles:
                print(f"  → 조문 파싱 결과 없음 (iframe 등 동적 로딩 가능성), 조문 없이 저장")
            
            law_json = build_law_json(law_key, law_info, html)
            if not articles:
                law_json["비고"] = "조문 본문 미확보 (HTML에서 iframe 외 영역만 파싱됨)"
        
        # 파일명 생성
        safe_name = re.sub(r'[^\w]', '_', law_info['name'])
        filename = f"{safe_name}.json"
        filepath = os.path.join(LAW_DIR, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(law_json, f, ensure_ascii=False, indent=2)
        
        article_count = len(law_json.get("조문", []))
        note = law_json.get("비고", "")
        print(f"  → 저장 완료: {filename} ({article_count}개 조문)" + (f" [{note}]" if note else ""))
        print()
        
        results.append({
            "법령명": law_info["name"],
            "파일명": filename,
            "조문수": article_count,
            "파일경로": filepath,
            "확보상태": "미확보" if not articles else "일부확보" if note else "확보",
        })

    # 최종 보고
    print("=" * 60)
    print("수집 완료 보고")
    print("=" * 60)
    print()
    print(f"{'법령명':<40} {'조문 수':<10} {'파일명':<50} {'상태'}")
    print("-" * 110)
    total_articles = 0
    for r in results:
        total_articles += r["조문수"]
        print(f"{r['법령명']:<40} {r['조문수']:<10} {r['파일명']:<50} {r['확보상태']}")
    print("-" * 110)
    print(f"{'합계':<40} {total_articles:<10}")
    print()
    print("파일 목록:")
    for f in sorted(os.listdir(LAW_DIR)):
        fpath = os.path.join(LAW_DIR, f)
        size = os.path.getsize(fpath)
        print(f"  {f} ({size:,} bytes)")
    print()
    print(f"총 {len(results)}개 법령, 총 {total_articles}개 조문 (미확보 포함)")


if __name__ == "__main__":
    main()
