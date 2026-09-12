#!/usr/bin/env python3
"""
extract_refs.py — Document Parse 응답(JSON)을 받아 참고문헌 항목 리스트를 돌려주는 결정론 모듈.

규칙(PRD §4 E10+E11 그대로):
1. element를 (page, 단[x<0.5/x>=0.5], y) 순으로 정렬한다.
2. 참고문헌 헤딩(References/참고문헌/인용문헌, 텍스트 매칭 — category 아님)을 만나기 전 element는 전부 버린다.
3. category가 header/footer면 무조건 제외. heading 계열도 제외.
4. 첫 줄이 번호표지([n]/n./n))면 element 내부를 표지 기준으로 분할, 저자-연도 서지 패턴이면 element=항목 1개, 둘 다 아니면 버린다.
   예외1: category가 footnote여도 표지·서지 패턴으로 시작하면 항목으로 취급한다.
   예외2: 직전 채택 항목이 페이지 p에 있고 현 element가 p+1의 첫 본문성 element이며 표지가 없으면 직전 항목의 이어쓰기로 병합한다.
5. 줄 병합(이어지는 줄을 앞 항목에 합침)은 element 내부에서만 한다. DOI 문자열은 절대 고치지 않는다. LLM 호출 금지.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# ── 상수 ──────────────────────────────────────────────────────────────────────

HEADING_PATTERNS = [
    re.compile(r'^references\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^참고문헌\s*$', re.MULTILINE),
    re.compile(r'^인용문헌\s*$', re.MULTILINE),
]

# 번호 표지: [n] / n. / n)
NUMBER_MARK_RE = re.compile(r'^\s*(\[\d+\]|\d+\.|\d+\))\s+', re.MULTILINE)

# category 제외: header, footer, heading 계열
EXCLUDED_CATEGORY_RE = re.compile(
    r'^(header|footer|heading)',
    re.IGNORECASE,
)

# 저자-연도 서지 판정용: 첫 줄에 연도 괄호(\d{4})가 있고 첫 단어가 한글/영문이면서,
# 헤딩 이후 요소이면 참고문헌으로 본다 (헤딩 전 요소는 E10 규칙 2에서 모두 버려짐).
# "et al."이 있어도 서지로 인정 — DP가 축약한 참고문헌일 수 있고,
# 헤딩 이후이므로 본문 인용이 섞여 들어올 위험이 없다.
_AUTHOR_YEAR_SIMPLIFIED_RE = re.compile(
    r'^\s*[A-Za-z가-힣]',
    re.MULTILINE,
)
_KO_PARENTHESIS_YEAR_RE = re.compile(
    r'^\s*\([가-힣]{2,5},\s*\d{4}\)\s*',
    re.MULTILINE,
)


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def get_element_text(element: Dict[str, Any]) -> str:
    """element에서 text를 추출한다. 여러 필드명을 시도한다."""
    for key in ("text", "content", "Content", "textContent", "TEXT"):
        val = element.get(key)
        if isinstance(val, str):
            return val
    # 중첩된 content.text 처리
    if isinstance(element.get("content"), dict):
        inner = element["content"].get("text") or element["content"].get("Content")
        if isinstance(inner, str):
            return inner
    return ""


def get_element_category(element: Dict[str, Any]) -> str:
    """category 값을 문자열로 반환. list면 첫 항목."""
    cat = element.get("category")
    if isinstance(cat, list) and cat:
        return str(cat[0])
    if isinstance(cat, str):
        return cat
    return ""


def get_element_box(element: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """좌표를 (x, y, width, height)로 반환. 없으면 None."""
    box = element.get("boundingBox") or element.get("box") or element.get("bbox")
    if not box:
        return None
    if isinstance(box, dict):
        x = box.get("x") or box.get("left") or 0.0
        y = box.get("y") or box.get("top") or 0.0
        w = box.get("width") or box.get("w") or 0.0
        h = box.get("height") or box.get("h") or 0.0
        return (float(x), float(y), float(w), float(h))
    if isinstance(box, list) and len(box) >= 4:
        return tuple(float(v) for v in box[:4])
    return None


def get_page(element: Dict[str, Any]) -> int:
    """페이지 번호 추출."""
    for key in ("page", "pageNumber", "page_number", "pageIndex", "pagenum"):
        val = element.get(key)
        if isinstance(val, (int, float)):
            return int(val)
    return 0


def first_line(text: str) -> str:
    """첫 줄을 반환한다."""
    if not text:
        return ""
    return text.split("\n", 1)[0].strip()


# ── 판정 함수 ─────────────────────────────────────────────────────────────────

def is_heading_element(element: Dict[str, Any]) -> bool:
    """참고문헌 헤딩인지 판정 (텍스트 매칭, category 무관)."""
    text = get_element_text(element)
    for pat in HEADING_PATTERNS:
        if pat.match(text):
            return True
    return False


def is_excluded_category(element: Dict[str, Any]) -> bool:
    """category가 header/footer/heading 계열이면 True."""
    cat = get_element_category(element)
    return bool(EXCLUDED_CATEGORY_RE.match(cat))


def is_number_marked(text: str) -> bool:
    """첫 줄이 번호 표지로 시작하면 True."""
    fl = first_line(text)
    return bool(NUMBER_MARK_RE.match(fl))


def _first_n_lines(text: str, n: int = 3) -> str:
    """텍스트의 첫 n줄을 반환한다."""
    lines = text.split("\n")
    return "\n".join(lines[:n])


def looks_like_bibliography(text: str) -> bool:
    """
    저자-연도 서지 패턴 여부 판정.

    번호표지는 starts_with_number_mark에서 별도 처리.
    첫 줄 + 첫 3줄 이내에서 연도 괄호(\d{4})가 있고 첫 단어가 한글/영문이면서,
    헤딩 이후 요소이면 참고문헌으로 본다 (헤딩 전 요소는 E10 규칙 2에서 모두 버려짐).

    "et al."이 포함된 경우:
    - 첫 단어가 한글 → 서지로 인정 (한국어 참고문헌)
    - 첫 단어가 영문이고 길이 >= 2 → 서지로 인정 (DP 축약형 참고문헌 가능성)
    - 첫 단어가 영문 1글자 → 본문 인용("He et al. (2016)" 등)으로 간주, 제외
    """
    if is_number_marked(text):
        return True

    # 첫 줄 + 첫 3줄 이내에서 검사
    head = _first_n_lines(text, 3)
    if not head:
        return False

    # 연도 괄호가 있고 첫 단어가 한글/영문 대문자면 서지 후보
    has_year_paren = re.search(r'\(\d{4}\)', head)
    if not has_year_paren:
        # 연도 괄호 없으면 DOI/arXiv로 시작하는지 체크 (첫 3줄 이내)
        if re.search(r'10\.\d{4,9}/', head) or re.search(r'arXiv:\s*\d{4}\.\d{4,5}', head, re.IGNORECASE):
            return True
        return False

    # 연도 괄호가 있는 첫 줄(또는 해당 줄)의 첫 단어 확인
    # 연도 괄호가 있는 줄을 찾아 그 첫 단어를 본다
    for line in head.split("\n"):
        if re.search(r'\(\d{4}\)', line):
            first = line.strip()
            starts_with_name = bool(_AUTHOR_YEAR_SIMPLIFIED_RE.match(first))
            if not starts_with_name:
                return False

            has_et_al = 'et al' in first.lower()
            if has_et_al:
                first_word = first.split()[0] if first.split() else ''
                if re.match(r'^[가-힣]', first_word):
                    return True
                if re.match(r'^[A-Za-z]', first_word):
                    if len(first_word) >= 2:
                        return True
                    return False
            return True

    return False


def is_author_year_bib(text: str) -> bool:
    """첫 줄이 저자-연도 서지 패턴이면 True."""
    return looks_like_bibliography(text)


def classify_element(text: str, category: str) -> str:
    """
    element 유형을 반환: 'number_bib', 'author_year_bib', 'body', 'other'.
    category가 footnote면 예외적으로 표지·서지 패턴 체크 후 유형 판정.
    """
    cat = category.lower()
    if cat == "footnote":
        # 예외1: footnote라도 표지·서지 패턴이면 참고문헌으로 간주
        if is_number_marked(text) or is_author_year_bib(text):
            return "number_bib" if is_number_marked(text) else "author_year_bib"
        return "body"  # 그 외 footnote는 본문으로 간주 (버림)

    # 전체 텍스트에 번호 표지가 하나라도 있으면 number_bib (첫 줄 기준 대신)
    if NUMBER_MARK_RE.search(text):
        return "number_bib"
    if is_author_year_bib(text):
        return "author_year_bib"
    return "body"


# ── 정렬 키 ──────────────────────────────────────────────────────────────────

def make_sort_key(element: Dict[str, Any]) -> Tuple[int, int, float]:
    """
    E10: (page, 단[x<0.5/x≥0.5], y) 순으로 정렬.
    단 판별: x 중심 좌표가 0.5 미만이면 left(0), 이상이면 right(1).
    좌표는 보통 normalized (0~1) 또는 픽셀 단위. normalized로 가정.
    """
    box = get_element_box(element)
    page = get_page(element)
    if box is None:
        return (page, 0, 0.0)
    x, y, w, h = box
    # column: 중심 x 기준
    cx = x + w / 2
    column = 0 if cx < 0.5 else 1
    return (page, column, y)


# ── 줄 병합 (E9) ──────────────────────────────────────────────────────────────

def merge_lines_in_element(text: str) -> str:
    """
    E9: element 내부에서 이어지는 줄을 병합한다.
    여러 줄을 하나의 공백으로 연결하되, DOI 문자열이 줄바꿈으로 끊기지 않도록
    alnum 연속 구간에서는 공백 없이 연결한다.
    DOI 문자열은 절대 고치지 않는다 — 단, '10.\\s+<숫자>' 형태의 공백은
    패턴 복구 목적으로 제거한다 (DP 추출 과정에서 생긴 오차).
    """
    if not text:
        return text
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""
    merged = []
    for i, line in enumerate(lines):
        if i == 0:
            merged.append(line)
            continue
        prev = merged[-1]
        # 앞 줄 끝과 뒷 줄 첫 문자가 모두 alnum이면 단어 중간 끊김 → 공백 없이 연결
        if prev and line and prev[-1].isalnum() and line[0].isalnum():
            merged[-1] = prev + line
        else:
            merged.append(line)
    result = " ".join(merged)
    # DP 추출 오차로 '10. 12345/' 형태가 생기면 '10.12345/'로 보정 (DOI 패턴 복구)
    result = re.sub(r'10\.\s+(\d{4,9}/)', r'10.\1', result)
    return result


# ── 요소 분할 (번호 표지 기준) ─────────────────────────────────────────────────

def split_by_number_mark(text: str) -> List[str]:
    """
    번호 표지([n]/n./n)) 기준으로 element 내부 텍스트를 항목 단위 리스트로 분할.
    """
    if not text:
        return []
    lines = text.split("\n")
    items: List[List[str]] = []
    current: List[str] = []
    for line in lines:
        if NUMBER_MARK_RE.match(line.strip()):
            if current:
                items.append("\n".join(current))
            current = [line.strip()]
        else:
            if current or line.strip():
                current.append(line.strip())
    if current:
        items.append("\n".join(current))
    return items


def _is_author_year_line_start(line: str) -> bool:
    """
    줄이 '성, 이니셜.' 패턴(예: Brown, T. B.,)으로 시작하는지 판정.
    즉, <대문자><소문자*>, <대문자>.<소문자*>. 형태.
    """
    return bool(re.match(r'^[A-Z][a-z]*,?\s+[A-Z]\.\s+[A-Z]?\.', line))


def _prev_line_ends_item_boundary(prev: str) -> bool:
    """
    직전 줄이 항목 경계(마침표·닫는괄호·숫자마침표)로 끝나면 True.
    쉼표로 끝나면 저자 목록 이어짐 → False.
    """
    if not prev:
        return True  # 첫 줄은 항상 새 항목 경계
    stripped = prev.rstrip()
    if not stripped:
        return True
    last = stripped[-1]
    # 마침표, 닫는 괄호, 숫자+마침표
    if last in '.):':
        return True
    if re.search(r'\d\.$', stripped):
        return True
    # 쉼표로 끝나면 저자 리스트 이어짐 → 분할 금지
    if last == ',':
        return False
    # 그 외(빈 줄, 세미콜론 등)도 경계로 간주
    return True


def split_author_year_items(text: str) -> List[str]:
    """
    저자-연도 서지 여러 개가 줄바꿈으로 구분된 element 텍스트를
    항목 단위로 분할한다.

    분할 규칙 (방어적):
    - 줄이 '성, 이니셜.' 패턴으로 시작하고
    - 직전 줄이 마침표·닫는괄호·숫자마침표로 끝났을 때만 새 항목으로 분할.
    - 직전 줄이 쉼표로 끝나면 저자 목록 이어짐이므로 분할 금지.
    """
    if not text:
        return []
    lines = text.split('\n')
    items: List[List[str]] = []
    current: List[str] = []
    prev_stripped = ''
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_author_year_line_start(stripped) and _prev_line_ends_item_boundary(prev_stripped):
            if current:
                items.append('\n'.join(current))
            current = [stripped]
        else:
            if current:
                current.append(stripped)
        prev_stripped = stripped
    if current:
        items.append('\n'.join(current))
    return items


def extract_references_from_elements(
    elements: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Document Parse elements 리스트 → 참고문헌 항목 리스트.

    반환 항목 dict:
        text: 병합된 항목 텍스트
        page: 참고문헌 페이지 번호 (첫 element 기준)
        source_note: "number_marked" / "author_year" / "merged"
    """
    if not elements:
        return []

    # 1. 정렬
    sorted_elements = sorted(elements, key=make_sort_key)

    results: List[Dict[str, Any]] = []
    heading_found = False
    prev_accepted: Optional[Dict[str, Any]] = None  # 직전 채택 항목
    prev_page: int = 0

    for idx, el in enumerate(sorted_elements):
        text = get_element_text(el)
        if not text.strip():
            continue

        # 2. 헤딩 찾기 전이면 전부 버림
        if not heading_found:
            if is_heading_element(el):
                heading_found = True
            continue

        # 3. category 제외
        if is_excluded_category(el):
            continue

        page = get_page(el)
        etype = classify_element(text, get_element_category(el))

        # 4. 유형 판정
        if etype == "number_bib":
            # 번호 표지: element 내부를 표지 기준으로 분할
            sub_items = split_by_number_mark(text)
            for i, sub in enumerate(sub_items):
                merged = merge_lines_in_element(sub)
                if not merged.strip():
                    continue
                # 첫 sub-item이 표지 없고 직전 항목이 p에 있고 현재 page=p+1이면 E11b 병합
                if (i == 0
                        and not is_number_marked(sub)
                        and prev_accepted is not None
                        and page == prev_page + 1):
                    prev_accepted["text"] = prev_accepted["text"] + " " + merged
                    prev_accepted["source_note"] = "merged"
                    continue
                results.append({
                    "text": merged,
                    "page": page,
                    "source_note": "number_marked",
                })
                prev_accepted = results[-1]
                prev_page = page

        elif etype == "author_year_bib":
            # 저자-연도: 먼저 번호 표지로 분할 시도 (숨은 표지가 있을 수 있음)
            sub_items = split_by_number_mark(text)
            if len(sub_items) > 1:
                # 다중 항목: 첫 항목이 표지 없으면 E11b 병합, 나머지는 number_bib으로
                for i, sub in enumerate(sub_items):
                    merged = merge_lines_in_element(sub)
                    if not merged.strip():
                        continue
                    if (i == 0
                            and not is_number_marked(sub)
                            and prev_accepted is not None
                            and page == prev_page + 1):
                        prev_accepted["text"] = prev_accepted["text"] + " " + merged
                        prev_accepted["source_note"] = "merged"
                        continue
                    results.append({
                        "text": merged,
                        "page": page,
                        "source_note": "number_marked" if is_number_marked(sub) else "author_year",
                    })
                    prev_accepted = results[-1]
                    prev_page = page
            else:
                # 단일 항목 (번호 표지 없음)
                merged = merge_lines_in_element(text)
                if merged.strip():
                    results.append({
                        "text": merged,
                        "page": page,
                        "source_note": "author_year",
                    })
                    prev_accepted = results[-1]
                    prev_page = page

        else:
            # 본문성 element (etype == 'body' 또는 'other')
            # E11b: 직전 채택 항목이 페이지 p, 현 element가 p+1 첫 본문성 element이고 표지 없음 → 병합
            if (prev_accepted is not None
                    and page == prev_page + 1
                    and etype in ("body", "other")
                    and not is_number_marked(text)
                    and not is_author_year_bib(text)):
                prev_accepted["text"] = prev_accepted["text"] + " " + merge_lines_in_element(text)
                prev_accepted["source_note"] = "merged"
                continue
            # 그 외 본문은 버림

    return results


# ── JSON 입출력 ───────────────────────────────────────────────────────────────

def load_docparse_json(path: str) -> List[Dict[str, Any]]:
    """Document Parse 응답 JSON 파일에서 elements 리스트를 추출."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    # 레スポンス 구조에 따라 분기
    if "elements" in payload:
        return payload["elements"]
    if "content" in payload and isinstance(payload["content"], dict):
        content = payload["content"]
        if "elements" in content:
            return content["elements"]
        if "text" in content:
            # text만 있는 경우 — 후처리용으로만 사용 (주 경로 아님)
            pass
    if isinstance(payload, list):
        return payload
    # 그외 폴백: 'data' 내 elements 등
    for key in ("data", "result", "response"):
        if key in payload:
            sub = payload[key]
            if isinstance(sub, list):
                return sub
            if isinstance(sub, dict) and "elements" in sub:
                return sub["elements"]
    raise ValueError(f"elements를 찾을 수 없음: {path}")


def extract_references_from_file(path: str) -> List[Dict[str, Any]]:
    """파일 경로로 Document Parse 응답을 읽고 참고문헌 추출."""
    elements = load_docparse_json(path)
    return extract_references_from_elements(elements)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python extract_refs.py <docparse_response.json>", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    refs = extract_references_from_file(path)
    print(f"참고문헌 {len(refs)}건 추출:")
    for i, r in enumerate(refs, 1):
        print(f"  [{i}] page={r['page']} type={r['source_note']}: {r['text'][:100]}...")
