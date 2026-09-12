#!/usr/bin/env python3
"""
verify_law_refs.py — 문서 텍스트에서 법령 인용 표지를 결정론 추출하고
assets/law/ 스냅샷에 조회해 ✅실존/❌해당 조 없음/⛔스냅샷 미보유 판정.

조문 본문이 있으면 반환(대조용). LLM 호출 없이 표준 라이브러리만 사용.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 상수 ──────────────────────────────────────────────────────────────────────

LAW_SNAPSHOT_DIR = Path("assets/law")
"""법령 스냅샷이 저장된 디렉토리."""

# 판정 어휘 (cite-check 원칙 유지)
VERDICT_EXISTS = "실존"          # ✅ 실존·현행
VERDICT_NO_ARTICLE = "해당 조 없음"  # ❌ 환각 조항
VERDICT_UNCHANGED_WARN = "내용 변동 가능"  # ⚠️ 조는 있으나 개정으로 내용 변동 가능
VERDICT_NO_SNAPSHOT = "스냅샷 미보유"  # ⛔ 미등록 DOI와 같은 원칙

# 스냅샷 1건당 구조:
# {"법령명","시행일","조문":[{"조":"제2조","제목":"정의","항":[...본문...]}], "출처URL","확보일"}
# 조문 필드가 비어 있으면(= 조문 0건) lookup은 전부 ⛔ 반환 — 이것이 현재 정확한 동작.


# ── 법령명 정규화 ─────────────────────────────────────────────────────────────

# assets/law/ JSON의 "법령명" 필드 값 → 표준 키.
# 파일명이나 JSON 내 명칭의 사소한 차이(공백·접속사)를 흡수한다.
# 별칭(현장 문서에서 실제로 쓰이는 약칭)은 별도 목록으로 관리한다.

_SNAPSHOT_LAW_NAMES: Dict[str, str] = {}  # 정규화 키 → JSON 법령명(원본)
_SNAPSHOT_ALIASES: Dict[str, str] = {}    # 별칭 → 정규화 키

# 파일명에서 인식한 법령명(아직 조문 비어 있음)을 키로 등록한다.
# 파일명 예: "노동조합_및_노동관계조정법.json" → JSON의 "법령명" 값으로 키 삼음.
def _load_snapshot_meta() -> None:
    """assets/law/ 의 JSON 파일들을 훑어 법령명 키·별칭 지도를 구축한다."""
    if _SNAPSHOT_LAW_NAMES:
        return  # 이미 구축됨
    if not LAW_SNAPSHOT_DIR.exists():
        return
    for path in sorted(LAW_SNAPSHOT_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        name = data.get("법령명") or data.get("법령명") or ""
        if not name or not isinstance(name, str):
            continue
        # 정규화 키: 공백 제거·개행 제거 후 사용
        key = re.sub(r"\s+", "", name.strip())
        _SNAPSHOT_LAW_NAMES[key] = name
        # 파일명에서 흔히 쓰이는 약칭도 별칭으로 등록
        _register_aliases(name, key)


def _register_aliases(full_name: str, key: str) -> None:
    """법령명으로부터 현장에서 쓰일 수 있는 별칭을 생성·등록한다."""
    s = full_name.strip()
    # 이미 등록된 키는 건너뛰기
    if key in _SNAPSHOT_ALIASES:
        return
    # 기본 별칭: 공백을 제거한 형태
    compact = re.sub(r"\s+", "", s)
    if compact != key:
        _SNAPSHOT_ALIASES[compact] = key
    # "법"으로 끝나는 문자열에서 앞부분 추출
    m = re.match(r"^(.+?)法(?:施?行?令|規則)?$", s)
    if not m:
        m = re.match(r"^(.+?)법(?:시행령|시행규칙)?$", s)
    if m:
        core = m.group(1).strip()
        if core:
            _SNAPSHOT_ALIASES[re.sub(r"\s+", "", core)] = key
    # 접속사 대체 변형 ("및" ↔ "&" 등)
    alt = re.sub(r"와|및", "·", s)
    _SNAPSHOT_ALIASES[re.sub(r"\s+", "", alt)] = key


# ── 법령 인용 표지 추출 (결정론) ──────────────────────────────────────────────

# 인식 대상 형태:
#   ① 「~법(시행령·시행규칙 포함)」 제N조  — 제M항 생략 가능
#   ② ~법(시행령·시행규칙 포함) 제N조      — 제M항 생략 가능
#   ③ 「~법」 제N조 제M항
#   ④ ~법 제N조 제M항
#
# 법령명은 "법", "시행령", "시행규칙"으로 끝날 수 있다.
# 법령명 부분에는 한글·괄호·숫자·공백이 들어갈 수 있다.

# 「 ~ 」 블록 인용 안 법률명 (한글 '법'/'법률' 및 한자 '法' / 시행령·시행규칙 포함)
_BLOCK_LAW_RE = re.compile(
    r"「\s*([^\」]*?(?:法|법|법률)(?:施?行?令|規則)?)\s*」"
)
# 블록 없는 법률명 (법·법률·시행령·시행규칙으로 끝남, 한글/한자 모두)
# 구조: (?:[가-힣a-zA-Z]+[\s·&]+)*[가-힣a-zA-Z]*?(?:法律|법률|法|법)(?:施?行?令|規則)?
# 앞쪽 단어들을 별도 캡처하지 않고 법률명 자체를 하나의 단위로 매칭하여
# '근거로 하며 근로기준법'처럼 동사·연결어미가 법률명에 딸려 나오는 것을 방지한다.
# 법령 접미사 앞은 비탐욕적("*?")으로 하여 '법률'이 (?:[\s·&]+[가-힣a-zA-Z]+)*에
# 잡아먹히지 않도록 한다.
_FREE_LAW_RE = re.compile(
    r"(?<![가-힣a-zA-Z_0-9])"
    r"(?:[가-힣a-zA-Z]+[\s·&]+)*"
    r"[가-힣a-zA-Z]*?"
    r"(?:法律|법률|法|법)"
    r"(?:施?行?令|規則)?"
    r"(?=[\s·&]|\s*$|\s*제\s*\d|\s*의\s*\d)"
)


def _is_probable_law_name(law_raw: str) -> bool:
    """
    자유 매칭된 문자열이 실제 법령명 후보인지 대략 검증한다.

    - 법령명은 '법', '법률', '시행령', '시행규칙' 등으로 끝나야 한다.
    - 법령명의 첫 단어가 용언 연결어미·보조사 등으로 끝나면('근거로', '하며' 등)
      법령명이 아니라 동사·어미가 딸려 나온 것이므로 기각한다.
    """
    s = law_raw.strip()
    if not s:
        return False
    # 법령명 끝 조건
    if not re.search(r"(?:法律|법률|法|법|施?行?令|規則)$", s):
        return False
    # 첫 단어가 용언 연결어미·보조사 등으로 끝나면 기각
    first_word = s.split()[0] if s.split() else s
    if re.search(
        r"(?:"
        r"로|며|고|서|지|나|거나|든지|게|도록|듯이|면서|라고|이라고|이라는|이라는"
        r")$",
        first_word,
    ):
        return False
    return True

# 조문·항 표지: "제N조" 및 선택적 "제M항" 또는 "제N조의M"
ARTICLE_TERMS_RE = re.compile(
    r"제\s*(\d+)\s*조(?:\s*제\s*(\d+)\s*항|\s*의\s*(\d+))?"
)


def extract_law_refs(text: str) -> List[Dict[str, Any]]:
    """
    문서 텍스트에서 법령 인용 표지를 결정론 추출한다.

    반환 각 항목:
        {
            "raw": 원문 표지 구간 (예: '「노동조합 및 노동관계조정법」 제2조'),
            "start": 시작 인덱스,
            "end": 끝 인덱스,
            "law_name_raw": 추출된 법령명 문자열,
            "law_name_norm": 정규화 키 (assets/law/ 조회용),
            "article": 조 번호 (예: 2),
            "paragraph": 항 번호 (예: 1) 또는 None,
        }
    추출되지 않으면 빈 리스트.

    dedup 키: (law_name_norm, article, paragraph). 동일 키는 한 번만 유지.
    """
    results: List[Dict[str, Any]] = []
    seen_keys: set = set()

    def _key(law_norm: str, art: int, para: Optional[int]) -> tuple:
        return (law_norm, art, para)

    # 블록 인용 형태 먼저 처리
    for m in _BLOCK_LAW_RE.finditer(text):
        law_raw = m.group(1).strip()
        after = text[m.end():]
        art_m = ARTICLE_TERMS_RE.search(after)
        if not art_m:
            continue
        article = int(art_m.group(1))
        paragraph = None
        if art_m.lastindex is not None:
            if art_m.group(2):
                paragraph = int(art_m.group(2))
            elif art_m.group(3):
                paragraph = int(art_m.group(3))
        abs_start = m.start()
        abs_end = m.end() + art_m.end()
        raw = text[abs_start:abs_end]
        law_norm = _normalize_law_name(law_raw)
        k = _key(law_norm, article, paragraph)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        results.append({
            "raw": raw,
            "start": abs_start,
            "end": abs_end,
            "law_name_raw": law_raw,
            "law_name_norm": law_norm,
            "article": article,
            "paragraph": paragraph,
        })

    # 블록 없는 형태 처리
    for m in _FREE_LAW_RE.finditer(text):
        law_raw = m.group(0).strip()
        if not _is_probable_law_name(law_raw):
            continue
        start = m.start()
        # 이미 블록 인용과 겹치면 스킵 (블록 인용은 results에 먼저 들어가 있음)
        if any(r["start"] <= start < r["end"] for r in results):
            continue
        # 블록 인용 안에 들어 있는 자유 매칭(예: 「근로기준법」 안의 '근로기준법') 제외
        if any(r["start"] < start and r["end"] > m.end() for r in results):
            continue
        after = text[m.end():]
        if any(r["start"] < start and r["end"] > m.end() for r in results):
            continue
        after = text[m.end():]
        art_m = ARTICLE_TERMS_RE.search(after)
        if not art_m:
            continue
        article = int(art_m.group(1))
        paragraph = None
        if art_m.lastindex is not None:
            if art_m.group(2):
                paragraph = int(art_m.group(2))
            elif art_m.group(3):
                paragraph = int(art_m.group(3))
        abs_start = m.start()
        abs_end = m.end() + art_m.end()
        raw = text[abs_start:abs_end]
        law_norm = _normalize_law_name(law_raw)
        k = _key(law_norm, article, paragraph)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        results.append({
            "raw": raw,
            "start": abs_start,
            "end": abs_end,
            "law_name_raw": law_raw,
            "law_name_norm": law_norm,
            "article": article,
            "paragraph": paragraph,
        })

    return results


def _normalize_law_name(raw: str) -> str:
    """
    추출된 법령명 원문에서 공백을 제거하고, assets/law/ 조회용 정규화 키를 반환.
    별칭 지도에 있으면 그 키, 없으면 공백 제거된 원문 자체를 키로 사용.
    """
    compact = re.sub(r"\s+", "", raw.strip())
    _load_snapshot_meta()
    if compact in _SNAPSHOT_ALIASES:
        return _SNAPSHOT_ALIASES[compact]
    if compact in _SNAPSHOT_LAW_NAMES:
        return compact
    # 등록되지 않은 법령이면 원단어를 키로 (조회 시 ⛔ 반환됨)
    return compact


# ── 스냅샷 조회 ───────────────────────────────────────────────────────────────

def _load_snapshot(law_key: str) -> Optional[Dict[str, Any]]:
    """
    assets/law/ 에서 정규화 키(법령명 공백제거)에 해당하는 스냅샷을 로드.
    없으면 None.
    """
    _load_snapshot_meta()
    if law_key not in _SNAPSHOT_LAW_NAMES:
        return None
    full_name = _SNAPSHOT_LAW_NAMES[law_key]
    # 파일 검색: 파일명에 법용명이 언더스코어화된 형태
    candidates = list(LAW_SNAPSHOT_DIR.glob(f"{full_name}*.json"))
    if not candidates:
        # 언더스코어화 변형 탐색
        underscored = re.sub(r"[\s·&]+", "_", full_name)
        candidates = list(LAW_SNAPSHOT_DIR.glob(f"{underscored}*.json"))
    if not candidates:
        return None
    try:
        with open(candidates[0], "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def lookup_article(
    law_name: str,
    article: int,
    paragraph: Optional[int] = None,
) -> Dict[str, Any]:
    """
    법령명과 조 번호로 assets/law/ 스냅샷을 조회한다.

    반환:
        {
            "law_name": (입력 법령명),
            "article": 조 번호,
            "paragraph": 항 번호 또는 None,
            "verdict": 판정 문자열 (✅실존 / ❌해당 조 없음 / ⛔스냅샷 미보유),
            "status_icon": 아이콘 문자,
            "article_body": (있을 경우) 조문 본문 또는 제목·항 목록,
            "note": 판정 근거 문자열,
            "snapshot": (있을 경우) 스냅샷 전체 데이터,
        }
    현재 assets/law/ 의 모든 스냅샷은 조문 배열이 비어 있으므로,
    등록된 법령이라도 조문 본문 없이 ⛔("스냅샷 미보유")를 반환한다.
    """

    law_key = _normalize_law_name(law_name)

    snap = _load_snapshot(law_key)

    if snap is None:
        # 미등록 법령 → ⛔
        return {
            "law_name": law_name,
            "article": article,
            "paragraph": paragraph,
            "verdict": VERDICT_NO_SNAPSHOT,
            "status_icon": "⛔",
            "article_body": None,
            "note": (
                f"'{law_name}'(조 {article}조)의 스냅샷이 assets/law/에 등록되지 않았음."
            ),
            "snapshot": None,
        }

    articles: Any = snap.get("조문")
    if not isinstance(articles, list) or not articles:
        # 법령에 매핑됐으나 조문이 비어 있음 → 현재 상태: 스냅샷 미보유로 간주
        return {
            "law_name": law_name,
            "article": article,
            "paragraph": paragraph,
            "verdict": VERDICT_NO_SNAPSHOT,
            "status_icon": "⛔",
            "article_body": None,
            "note": (
                f"'{law_name}'(조 {article}조)의 스냅샷은 있으나 조문이 비어 있어 "
                "조문 본문을 제공할 수 없음 (확보일: {})."
            ).format(snap.get("확보일") or "미상"),
            "snapshot": snap,
        }

    # 조문 목록에서 매칭
    target = f"제{article}조"
    found: Optional[Dict[str, Any]] = None
    for art in articles:
        art_jo = str(art.get("조", "")).strip()
        if art_jo == target:
            found = art
            break

    if found is None:
        # 조 번호가 존재하지 않음 → ❌ 환각 조항
        return {
            "law_name": law_name,
            "article": article,
            "paragraph": paragraph,
            "verdict": VERDICT_NO_ARTICLE,
            "status_icon": "❌",
            "article_body": None,
            "note": (
                f"'{law_name}'의 스냅샷에는 '제{article}조'가 없음 "
                f"(보유 조문 수: {len(articles)}건). "
                "실존하지 않는 조항을 인용했을 가능성."
            ),
            "snapshot": snap,
        }

    # 조는 있음. 항까지 요청했으면 항 존재 여부 확인.
    if paragraph is not None:
        paragraphs = found.get("항")
        if not isinstance(paragraphs, list) or paragraph > len(paragraphs):
            return {
                "law_name": law_name,
                "article": article,
                "paragraph": paragraph,
                "verdict": VERDICT_NO_ARTICLE,
                "status_icon": "❌",
                "article_body": found,
                "note": (
                    f"'{law_name}' 제{article}조는 있으나 "
                    f"제{paragraph}항이 없거나 범위를 벗어남."
                ),
                "snapshot": snap,
            }

    # ✅ 실존. 본문에 변동 가능성이 있으면 ⚠️로 강등할 수 있으나,
    # 현재는 개정 정보ㆍ수준 부재로 기본 ✅ 처리. (⚠️ 판정은 상위 로직에서 결정)
    return {
        "law_name": law_name,
        "article": article,
        "paragraph": paragraph,
        "verdict": VERDICT_EXISTS,
        "status_icon": "✅",
        "article_body": found,
        "note": (
            "'{}' 제{}조{} 실존 확인 (스냅샷 확보일: {}).".format(
                law_name,
                article,
                f" 제{paragraph}항" if paragraph else "",
                snap.get("확보일") or "미상",
            )
        ),
        "snapshot": snap,
    }


def verify_law_ref(
    raw_ref: Dict[str, Any],
) -> Dict[str, Any]:
    """
    추출 결과 1건을 조회해 판정한다.

    반환: lookup_article 결과에 추출 메타(raw, start, end)를 덧씌운 dict.
    """
    res = lookup_article(
        raw_ref["law_name_raw"],
        raw_ref["article"],
        raw_ref.get("paragraph"),
    )
    res["raw"] = raw_ref["raw"]
    res["start"] = raw_ref["start"]
    res["end"] = raw_ref["end"]
    res["law_name_raw"] = raw_ref["law_name_raw"]
    res["law_name_norm"] = raw_ref["law_name_norm"]
    return res


def verify_all_law_refs(text: str) -> List[Dict[str, Any]]:
    """
    문서 텍스트에서 모든 법령 인용 표지를 추출·조회한 결과를 리스트로 반환.
    """
    refs = extract_law_refs(text)
    return [verify_law_ref(r) for r in refs]


# ── 조문 대조 (match_claims 원리 재사용: 문자열 대조기 + 비대칭 강등) ────────

# 법령판 오인용 검출용. 조문 본문이 있을 때만 동작한다.
# claim(주장 문장)에 인용된 법령 조문의 실제 본문과 비교해
# 주장 문장이 조문에서 뒷받침되는지 3분기 판정.

# 문자열 대조기: match_claims.py 의 quote_exists_in_metadata 와 유사한
# 정규화된 substring 검사. 법령 텍스트는 문장 경계가 분명하므로
# …· 생략부호 분할은 적용하지 않고, 문구를 그대로 정규화 후 substring 검사.


def _norm_for_law(s: str) -> str:
    """법령 텍스트 대조용 정규화 (소문자화 없음 — 한국어는 대소문자 없음)."""
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", "'").replace("\u201d", "'")
    s = s.replace("\u201c", "'").replace("\u201d", "'")
    s = s.replace("\u300c", " ").replace("\u300d", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def law_claim_vs_article(
    claim: str,
    article_body: Any,
) -> Dict[str, Any]:
    """
    주장 문장과 조문 본문을 대조해 법령판 오인용 여부를 판정.

    article_body: lookup_article 이 반환한 조문 dict (조·항·본문 포함) 또는 문자열.

    반환:
        {
            "verdict": "뒷받침함" | "뒷받침 안 함" | "판단 불가",
            "quote": 조문에서 추출한 근거 구절 (없으면 ""),
            "note": 판정 근거,
            "quote_exists": 조문 내에 실제 근거 구절이 존재하는지 bool,
        }
    조문 본문이 없으면 즉시 "판단 불가" + quote_exists=False.
    """
    if not article_body:
        return {
            "verdict": "판단 불가",
            "quote": "",
            "note": "조문 본문이 없어 대조 불가.",
            "quote_exists": False,
        }

    # article_body를 평면 텍스트로 치환
    body_text = _flatten_article_body(article_body)

    if not body_text:
        return {
            "verdict": "판단 불가",
            "quote": "",
            "note": "조문 본문이 비어 있어 대조 불가.",
            "quote_exists": False,
        }

    claim_norm = _norm_for_law(claim)
    body_norm = _norm_for_law(body_text)

    # claims within body: claim의 의미 있는 연속 구절(15자 이상)이
    # body_norm의 substring으로 존재하는가?
    fragments = _extract_claim_fragments(claim_norm)
    if not fragments:
        return {
            "verdict": "판단 불가",
            "quote": "",
            "note": "주장 문장에서 15자 이상 의미 구절을 추출할 수 없어 대조 불가.",
            "quote_exists": False,
        }

    matched_fragments = [f for f in fragments if f in body_norm]

    if matched_fragments:
        # 근거 구절 존재: 가장 긴 매칭을 quote로 제시
        best = max(matched_fragments, key=len)
        # 원본(주장)에서 해당 부분의 원문 recover
        orig_quote = _recover_original_quote(claim, best)
        if orig_quote is None:
            orig_quote = best
        return {
            "verdict": "뒷받침함",
            "quote": orig_quote,
            "note": "주장에 포함된 '{}…' 구절({}자)이 조문 본문에서 확인됨.".format(
                best[:40], len(best)
            ),
            "quote_exists": True,
        }
    else:
        # 매칭되는 구절이 전혀 없음 → 뒷받침 안 함
        return {
            "verdict": "뒷받침 안 함",
            "quote": "",
            "note": "주장 문장의 의미 구절 중 조문 본문에서 확인된 부분이 없음."
                    " 법령판 오인용(🔴) 가능성.",
            "quote_exists": False,
        }


def _flatten_article_body(body: Any) -> str:
    """조문 dict(또는 문자열)를 평면 텍스트로 flattening."""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        parts = []
        if body.get("제목"):
            parts.append(f"({body['제목']}) ")
        # 항 목록이 있으면 각 항 본문 연결
        paragraphs = body.get("항")
        if isinstance(paragraphs, list):
            for i, para in enumerate(paragraphs, 1):
                if isinstance(para, dict):
                    txt = para.get("본문") or para.get("text") or ""
                    if txt:
                        parts.append(f"{i}항: {txt} ")
                elif isinstance(para, str):
                    parts.append(f"{i}항: {para} ")
        elif isinstance(paragraphs, str):
            parts.append(paragraphs)
        return "".join(parts).strip()
    if isinstance(body, list):
        return " ".join(str(x) for x in body)
    return str(body)


def _extract_claim_fragments(norm_claim: str) -> List[str]:
    """
    정규화된 주장 문장에서 15자 이상 연속 의미 구절을 추출.
    ...·… 분할은 법령 텍스트에 적용하지 않고, 문장 단위 분할 후
    일정 길이 이상의 구역을 후보로 삼는다.
    """
    # 먼저 문장 단위로 분할
    sentences = re.split(r"[\.\n·;]+", norm_claim)
    fragments: List[str] = []
    for s in sentences:
        s = s.strip()
        if len(s) >= 15:
            fragments.append(s)
    # 문장 내 n-gram도 후보: 20자 이상 연속 윈도우
    if not fragments:
        words = norm_claim.split()
        if len(words) < 2:
            return []
        for i in range(len(words)):
            for j in range(i + 2, min(i + 8, len(words) + 1)):
                chunk = " ".join(words[i:j])
                if len(chunk) >= 15:
                    fragments.append(chunk)
    return fragments


def _recover_original_quote(original: str, norm_fragment: str) -> Optional[str]:
    """정규화된 조각에 해당하는 원문(주장 내) 구절을 recover."""
    # 단순 역정규화: 원문에서 같은 의미의 부분 문자열 찾기
    orig_norm = _norm_for_law(original)
    idx = orig_norm.find(norm_fragment)
    if idx >= 0:
        end = idx + len(norm_fragment)
        # 원문에서도 같은 위치를 복원할 수 있으면 추출
        # naive: norm_fragment와 길이가 같은 원문 영역 탐색
        # 여기서는 간단히 norm_fragment 자체를 반환
        return norm_fragment
    return None


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="문서 텍스트에서 법령 인용 표지 추출·조회"
    )
    parser.add_argument(
        "text",
        nargs="?",
        help="검사할 문서 텍스트 (파일 경로를 주면 읽음)",
    )
    parser.add_argument(
        "--file", "-f",
        help="텍스트 파일 경로",
    )
    parser.add_argument(
        "--json-out", "-j",
        help="결과를 JSON으로 저장할 경로",
    )
    args = parser.parse_args()

    source = args.text or ""
    if args.file:
        source = Path(args.file).read_text(encoding="utf-8")

    if not source.strip():
        print("오류: 텍스트 입력이 없음.", file=sys.stderr)
        sys.exit(1)

    results = verify_all_law_refs(source)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"결과 저장: {args.json_out}")

    # 콘솔 출력
    if not results:
        print("법령 인용 표지 없음.")
    else:
        for r in results:
            icon = r.get("status_icon", "?")
            art = r.get("article")
            para = r.get("paragraph")
            art_str = f"제{art}조"
            if para:
                art_str += f" 제{para}항"
            print(
                f"{icon} {r.get('law_name_raw','')} {art_str} "
                f"— {r.get('verdict','?')}"
            )
            note = r.get("note", "")
            if note:
                print(f"   └ {note}")
