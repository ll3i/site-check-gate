#!/usr/bin/env python3
"""
tests/parse_law_raw.py — 국가법령정보센터 raw 텍스트를 조문 단위로 분할.

raw 파일 구조 (5종 공통):
  1) [get_page_text] Title: ... (헤더, 1라인)
  2) URL: ...
  3) Source element: <body>
  4) ---
  5) 법령
  6) - 법령명   ← 법령명 (Header)
  7) (빈 줄)
  8) 법령명     ← 법령명 재표시
  9) [시행 YYYY. M. D.] [법률 제NNNNN호, ...]
  10) 본문목록열림본문 / 부칙목록열림부칙 / 별표목록열림별표
  11) 본문, 제정·개정이유, ... (네비게이션 메뉴)
  12) 조문 선택 (또는 조문선택)
  13) ~ 목차 (제1장 총칙 ~ 마지막 장, 각 조문명 목록)
  14) 화면내검색
  15) 새창 선택, 판례, 연혁, 위임행정규칙, 규제, 생활법령, 한눈보기
  16) 법령명 (약칭)  ← 약칭 표시 (파견법, 중대재해법 등에서)
  17) [시행 ...] [법률 ...]  ← 재표시
  18) 관할 부서 정보
  19) 제1장 총칙      ← 본문 시작 ★
  20) 제1조(목적) ...
   ...
  N) 부 칙 <...>     ← 부칙 시작 ★

중대재해처벌법 (serious_accidents_raw.txt) 은 더 단순:
  1) 법령명 (약칭)
  2) [시행 ...] [법률 ...]
  3) 출처: URL (확보일)
  4) (빈 줄)
  5) 제1장 총칙      ← 본문 시작 ★
"""

from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

RAW_DIR = Path(__file__).parent.parent / "assets" / "law" / "raw"
OUT_DIR = Path(__file__).parent.parent / "assets" / "law"

# ── 메타데이터 ────────────────────────────────────────────────────────────────

URL_RE = re.compile(r"^URL:\s*(\S+)", re.M)
HEADER_LAW_LINE = re.compile(r"^\s*-\s+(.+)$")
# [시행 YYYY. M. D.] [법률 제NNNNN호, ...]
META_RE = re.compile(
    r"^\[시행\s*([\d\s.]+)\]\s*\[(법률\s*제\d+호[^\]]*)\]"
)
# "법령명 ( 약칭: ... )" 첫 줄 패턴
LAW_WITH_ALIAS_RE = re.compile(r"^(.+?)\s*\(약칭:.*?\)?")


def _extract_metadata(lines: List[str]) -> Dict[str, str]:
    result: Dict[str, str] = {
        "법령명": "", "시행일": "", "법률번호": "",
        "출처URL": "", "확보일": "2026-09-13",
    }

    # 1) URL
    for line in lines:
        m = URL_RE.match(line)
        if m:
            result["출처URL"] = m.group(1)
            break

    # 2) 확보일: 본문 안에서 검색
    full = "\n".join(lines)
    m = re.search(r"확보일\s*(\d{4}-\d{2}-\d{2})", full)
    if m:
        result["확보일"] = m.group(1)

    # 3) 법령명
    # 3a) "- 법령명" 헤더 라인
    for line in lines:
        m = HEADER_LAW_LINE.match(line)
        if m:
            result["법령명"] = m.group(1).strip()
            break

    # 3b) 첫 줄이 "법령명 ( 약칭: ... )" 형태 → "약칭:" 앞까지 추출
    if not result["법령명"] and lines:
        candidate = lines[0].strip()
        # "약칭:" 앞부분만 취함 (괄호 포함 앞부분 모두 제거)
        m2 = re.search(r"\s*약칭:", candidate)
        if m2:
            result["법령명"] = candidate[:m2.start()].rstrip(" (").strip()
        else:
            result["법령명"] = candidate

    # 3c) fallback: 첫 [시행] 라인 바로 위 라인
    if not result["법령명"]:
        for i, line in enumerate(lines):
            if META_RE.match(line.strip()):
                if i >= 1 and lines[i - 1].strip():
                    c = lines[i - 1].strip()
                    c = re.sub(r"\s*\(약칭:.*?\)", "", c).strip()
                    if c and not c.startswith("법령") and not c.startswith("---"):
                        result["법령명"] = c
                        break

    # 4) 시행일 + 법률번호
    for line in lines:
        m = META_RE.match(line.strip())
        if m:
            result["시행일"] = m.group(1).strip()
            result["법률번호"] = m.group(2).strip()
            break

    return result


# ── 본문 영역 탐지 ────────────────────────────────────────────────────────────

ARTICLE_HEAD_RE = re.compile(r"^(제\d+조(?:의\d+)?)\s*\(")
ARTICLE_DELETE_RE = re.compile(r"^(제\d+조(?:의\d+)?)\s*삭제")
PARA_RE = re.compile(r"^[\u2460-\u2473]")
GORI_RE = re.compile(r"^(\d+)\.\s+")
CHAPTER_RE = re.compile(r"^제\d+장\s")
ADDENDUM_RE = re.compile(r"^부\s*칙")


def _find_body_range(lines: List[str]) -> Tuple[int, int]:
    """본문 시작 인덱스, 부칙 시작 인덱스를 반환."""
    n = len(lines)

    # 1) "화면내검색" 위치
    screen_pos = -1
    for i, line in enumerate(lines):
        if line.strip() == "화면내검색":
            screen_pos = i
            break

    search_from = screen_pos + 1 if screen_pos >= 0 else 0

    # 2) 본문 시작: 화면내검색 이후 첫 "제1장 총칙" + 조문 머리 확인
    body_start = -1
    for i in range(search_from, n):
        s = lines[i].strip()
        if s.startswith("제1장 총칙"):
            j = i + 1
            while j < n and lines[j].strip() == "":
                j += 1
            if j < n and (ARTICLE_HEAD_RE.match(lines[j].strip()) or
                           ARTICLE_DELETE_RE.match(lines[j].strip())):
                body_start = i
                break

    # 3) 제1장 총칙이 없으면 첫 조문 머리 찾기
    if body_start < 0:
        for i in range(search_from, n):
            if (ARTICLE_HEAD_RE.match(lines[i].strip()) or
                ARTICLE_DELETE_RE.match(lines[i].strip())):
                body_start = i
                break

    if body_start < 0:
        body_start = search_from

    # 4) 부칙 시작
    addendum_start = n
    for i in range(body_start, n):
        if ADDENDUM_RE.match(lines[i].strip()):
            addendum_start = i
            break

    return body_start, addendum_start


# ── 조문 파싱 ─────────────────────────────────────────────────────────────────

def _parse_articles(lines: List[str], start: int, end: int) -> List[Dict[str, Any]]:
    articles: List[Dict[str, Any]] = []
    idx = start
    current: Dict[str, Any] | None = None
    current_start: int | None = None  # full_text 추적용 시작 인덱스

    while idx < end:
        stripped = lines[idx].strip()
        if stripped == "":
            idx += 1
            continue

        m = ARTICLE_HEAD_RE.match(stripped)
        if m:
            if current is not None:
                # 이전 조문 저장 (full_text 구성)
                articles.append(_finalize_article(current, lines, current_start, idx))
            jo = m.group(1)
            rest = stripped[m.end():]
            title_end = rest.find(")")
            if title_end >= 0:
                title = rest[:title_end].strip()
                remainder = rest[title_end + 1:].strip()
            else:
                title = rest.strip()
                remainder = ""
            paras: List[str] = []
            if remainder:
                paras.append(remainder)
            current = {"조": jo, "제목": title, "항": paras}
            current_start = idx
            idx += 1
            continue

        m2 = ARTICLE_DELETE_RE.match(stripped)
        if m2:
            if current is not None:
                articles.append(_finalize_article(current, lines, current_start, idx))
            current = {"조": m2.group(1), "제목": "(삭제)", "항": []}
            current_start = idx
            idx += 1
            continue

        # [전문개정 ...], [시행일: ...] 등 → 스킵
        if stripped.startswith("[") and stripped.endswith("]"):
            idx += 1
            continue

        # 장/절 제목 → 스킵
        if CHAPTER_RE.match(stripped):
            idx += 1
            continue

        if ADDENDUM_RE.match(stripped):
            break

        if current is not None:
            if PARA_RE.match(stripped):
                text = stripped[2:].strip()
                if text:
                    current["항"].append(text)
                idx += 1
                continue
            gm = GORI_RE.match(stripped)
            if gm:
                text = stripped[gm.end():].strip()
                if text:
                    current["항"].append(text)
                idx += 1
                continue
            if stripped:
                if current["항"]:
                    current["항"][-1] = current["항"][-1] + " " + stripped
                else:
                    current["항"].append(stripped)
                idx += 1
                continue
        idx += 1

    if current is not None:
        articles.append(_finalize_article(current, lines, current_start, end))
    return articles


def _finalize_article(
    current: Dict[str, Any],
    lines: List[str],
    start_idx: int | None,
    end_idx: int,
) -> Dict[str, Any]:
    """조문 dict에 full_text 필드를 추가하여 반환."""
    result = {
        "조": current["조"],
        "제목": current["제목"],
        "항": current["항"],
    }
    # full_text: 조문 시작 라인부터 end_idx 직전까지 전체 원문
    if start_idx is not None and start_idx < end_idx:
        full_lines = []
        for i in range(start_idx, end_idx):
            s = lines[i].strip()
            if s:  # 빈 줄 제외 (필요 시 포함하려면 이 조건 제거)
                full_lines.append(lines[i].rstrip())
        result["full_text"] = "\n".join(full_lines)
    else:
        result["full_text"] = ""
    return result


def _parse_addendum(lines: List[str], start: int) -> List[str]:
    result: List[str] = []
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if s:
            result.append(s)
    return result


# ── 메인 ──────────────────────────────────────────────────────────────────────

def parse_raw_text(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    meta = _extract_metadata(lines)
    body_start, addendum_start = _find_body_range(lines)
    articles = _parse_articles(lines, body_start, addendum_start)
    addendum = _parse_addendum(lines, addendum_start)
    return {
        "법령명": meta["법령명"],
        "시행일": meta["시행일"],
        "법률번호": meta["법률번호"],
        "출처URL": meta["출처URL"],
        "확보일": meta["확보일"],
        "조문": articles,
        "부칙": addendum,
    }


def parse_and_save_all() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = sorted(RAW_DIR.glob("*_raw.txt"))
    if not raw_files:
        print(f"오류: {RAW_DIR} 에 *_raw.txt 파일이 없음", file=sys.stderr)
        sys.exit(1)
    for raw_path in raw_files:
        text = raw_path.read_text(encoding="utf-8")
        data = parse_raw_text(text)
        stem = raw_path.stem
        out_name = stem[:-4] + ".json" if stem.endswith("_raw") else stem + ".json"
        out_path = OUT_DIR / out_name
        out_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"파싱 완료: {raw_path.name} → {out_path.name} "
              f"(법령명: {data['법령명']}, 시행일: {data['시행일']}, "
              f"법률번호: {data['법률번호']}, 조문 {len(data['조문'])}건, "
              f"부칙 {len(data['부칙'])}줄)")
        # 샘플 출력: 첫 조문의 full_text 길이
        if data["조문"]:
            first = data["조문"][0]
            ft_len = len(first.get("full_text", ""))
            print(f"  └ 제{first['조']} ({first['제목']}) full_text: {ft_len}자")


if __name__ == "__main__":
    parse_and_save_all()
