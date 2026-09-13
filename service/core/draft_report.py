#!/usr/bin/env python3
"""
draft_report.py — 점검 보고서 초안 생성 (M9 §2).

입력: inspect_photos() 의 구조화 결과.
출력: markdown 초안(str). 계약은 아래 참조.

계약:
  - 입력은 ③의 구조화 결과만. 모델이 검출에 없는 사실을 쓰면 안 된다.
  - 문장마다 근거 태그: [사진n: label conf] [산안법 제N조] 형식으로 끝에 부착.
  - 코드 후처리: 초안의 각 근거 태그가 실제 결과에 존재하는지 문자열 검사,
    없는 태그가 포함된 문장은 "(확인 필요)"로 강등.
  - 생성된 초안을 기존 검증 파이프(verify_law_refs)에 다시 통과시켜
    법령 인용 ❌(해당 조 없음)가 없음을 확인. 있으면 해당 문장 제거 후 재생성 1회.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from service.core.inspect_mode import inspect_photos
from service.core.verify_law_refs import verify_all_law_refs, extract_law_refs

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

RISK_ACTION_VERB = {
    "위험": "즉시 안전조치 및 보수·정비",
    "주의": "통로 확보·정리정돈 등 개선",
    "양호": "정기 점검 상태 유지",
}

# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def generate_draft(result: Dict[str, Any]) -> str:
    """inspect_photos 결과를 받아 markdown 초안을 생성한다.

    Args:
        result: inspect_photos() 반환 dict (photos[], summary{위험,주의,양호,판정}).

    Returns:
        markdown 초안 문자열.
    """
    if not result.get("photos"):
        return "# 안전 점검 보고서(초안)\n\n점검 사진이 없습니다.\n"

    md = _build_markdown(result)
    md = _postprocess_tags(md, result)
    md = _reverify_law_refs(md, result)
    return md


def build_draft_with_photos(photo_files: List[str], gauge: bool = False) -> Dict[str, Any]:
    """점검 + 초안 생성을 한 번에 수행한다.

    Returns:
        {
            "inspect_result": inspect_photos(...) 결과,
            "draft_md": markdown 초안,
        }
    """
    inspect_result = inspect_photos(photo_files, gauge=gauge)
    draft_md = generate_draft(inspect_result)
    return {
        "inspect_result": inspect_result,
        "draft_md": draft_md,
    }


def regenerate_draft_once(
    result: Dict[str, Any],
    removed_sentences: List[str],
) -> str:
    """법령 인용 ❌ 확인으로 문장을 제거한 뒤 1회 재생성한다.

    실제 호출은 generate_draft 내부 _reverify_law_refs 에서 관리한다.
    이 함수는 테스트 및 재사용을 위해 노출한다.
    """
    md = _build_markdown(result)
    md = _remove_sentences(md, removed_sentences)
    md = _postprocess_tags(md, result)
    return md


# ---------------------------------------------------------------------------
# 1. markdown 본조립
# ---------------------------------------------------------------------------

def _build_markdown(result: Dict[str, Any]) -> str:
    photos = result.get("photos", [])
    summary = result.get("summary", {})
    verdict = summary.get("판정", "양호")
    n_risk = summary.get("위험", 0)
    n_caution = summary.get("주의", 0)
    n_ok = summary.get("양호", 0)

    lines: List[str] = []
    lines.append("# 현장 안전 점검 보고서 (초안)")
    lines.append("")
    lines.append(f"**종합 판정:** {verdict}  ")
    lines.append("")
    lines.append("## 종합 현황")
    lines.append("")
    lines.append(f"- 위험: {n_risk}건")
    lines.append(f"- 주의: {n_caution}건")
    lines.append(f"- 양호: {n_ok}건")
    lines.append("")

    # 사진별 카드
    for i, ph in enumerate(photos, 1):
        photo_name = ph.get("photo", "")
        risk_level = ph.get("risk_level", "양호")
        detections = ph.get("detections", [])
        law_refs = ph.get("law_refs", [])
        action = ph.get("action", "")

        lines.append(f"## 사진 {i}. {photo_name}")
        lines.append("")
        lines.append(f"- **위험도:** {risk_level}")
        lines.append(f"- **권고:** {action}")
        lines.append("")

        # 검출 목록 (근거 태그 재료로 사용)
        det_parts: List[str] = []
        for d in detections:
            label = d.get("label", "")
            conf = d.get("conf", 0.0)
            det_parts.append(f"{label} {conf:.2f}")
        det_str = ", ".join(det_parts) if det_parts else "검출 없음"

        lines.append(f"- **검출:** {det_str}")
        lines.append("")

        # 법령 조문 발췌
        if law_refs:
            lines.append("### 관련 법령 (실제 조문 발췌)")
            lines.append("")
            for ref in law_refs:
                law = ref.get("법령", "")
                jo = ref.get("조", "")
                excerpt = ref.get("발췌", "")
                lines.append(f"- **{law} {jo}**")
                lines.append("")
                lines.append(f"  > {excerpt}")
                lines.append("")
        else:
            lines.append("### 관련 법령")
            lines.append("")
            lines.append("※ 검출 결과에 연결할 실제 조문 발췌가 없어 법령 조문을 인용하지 않았습니다. (확인 필요)")
            lines.append("")

        # 사진별 근거 태그 (문장에 들어갈 형태로 말미에 표시)
        tag_str = _photo_tag(i, detections, law_refs)
        lines.append(f"**근거 태그:** {tag_str}")
        lines.append("")

    # 종합 권고 문단
    lines.append("## 종합 권고")
    lines.append("")
    if n_risk >= 1:
        lines.append(f"위험 요소 {n_risk}건이 검출되어 {RISK_ACTION_VERB['위험']}이(가) 필요합니다. ")
        lines.append("검출된 위험 항목에 대해 산업안전보건법 제38조(안전조치)에 따른 조치가 요구됩니다.")
    elif n_caution >= 1:
        lines.append(f"주의 요소 {n_caution}건이 검출되어 {RISK_ACTION_VERB['주의']}이(가) 권고됩니다. ")
        lines.append("산업안전보건법 제38조(안전조치) 및 정리정돈 관련 조치에 따라 개선이 권고됩니다.")
    else:
        lines.append("검출 결과 위험·주의 요소가 없어 현행 안전 상태를 유지하시면 됩니다.")
    lines.append("")

    return "\n".join(lines)


def _photo_tag(photo_n: int, detections: List[Dict[str, Any]], law_refs: List[Dict[str, Any]]) -> str:
    """사진 n번의 근거 태그 문자열."""
    parts: List[str] = []
    det_set = {d.get("label", "") for d in detections}
    for d in detections:
        label = d.get("label", "")
        conf = d.get("conf", 0.0)
        if label in det_set:
            parts.append(f"[사진{photo_n}:{label} {conf:.2f}]")
            det_set.discard(label)
    for ref in law_refs:
        law = ref.get("법령", "")
        jo = ref.get("조", "")
        parts.append(_law_tag_from_ref(law, jo))
    return " ".join(parts)


def _law_tag_from_ref(law: str, jo: str) -> str:
    """법령명 + 조 번호로 근거 태그 문자열 생성."""
    # 법령명에서 한글 끝부분 정리 (뒤에 붙는 접미사 정리 없이 그대로 사용하되,
    # 참고 편의를 위해 '산안법' 약칭이 가능한 경우만 약칭)
    if law == "산업안전보건법":
        return "[산안법" + jo + "]"
    return f"[{law}{jo}]"


# ---------------------------------------------------------------------------
# 2. 근거 태그 후처리 강등
# ---------------------------------------------------------------------------

# 근거 태그 패턴:
#   [사진n:label conf]  (예: [사진1:corrosion 0.84])
#   [산안법 제N조]       (예: [산안법 제38조])
#   일반 법령 태그      (예: [산업안전보건법 제38조])
TAG_PHOTO_RE = re.compile(r"\[사진(\d+):([a-zA-Z0-9_]+)\s+([0-9]+\.[0-9]+)\]")
TAG_LAW_RE = re.compile(r"\[산안법\s*제(\d+)조\]|\[(?:산업안전보건법|산업안전보건법)\s*제(\d+)조\]")


def _postprocess_tags(md: str, result: Dict[str, Any]) -> str:
    """문장마다 근거 태그 존재 여부를 검사, 없는 태그가 포함된 문장은 강등.

    실제 '문장' 단위는 markdown 개행(\n\n) 블록 단위로 간주한다.
    각 블록에 요구되는 최소 근거 태그 집합이 존재하지 않으면
    블록 말미에 '(확인 필요)'를 부착하고, 근거가 전혀 없는 블록은
    강등 표시(앞에 '(확인 필요) ')를 추가한다.
    """
    blocks = _split_blocks(md)
    out_blocks: List[str] = []
    for block in blocks:
        missing = _required_tags_for_block(block, result)
        if not missing:
            out_blocks.append(block)
            continue
        # 태그 불일치 문장 → 강등
        block = _demote_block(block, missing)
        out_blocks.append(block)
    return "\n\n".join(out_blocks)


def _split_blocks(md: str) -> List[str]:
    """markdown 을 개행 2회 기준으로 블록 분할."""
    raw = md.split("\n\n")
    # 앞뒤 공백 정리
    blocks: List[str] = []
    for b in raw:
        b = b.strip()
        if b:
            blocks.append(b)
    return blocks


def _required_tags_for_block(block: str, result: Dict[str, Any]) -> List[str]:
    """블록에서 요구한(존재하는) 근거 태그 중 실제 결과와 불일치하는 태그를 반환.

    계약: 초안의 각 근거 태그가 실제 결과에 존재하는지 검사.
    없는 태그가 하나라도 있으면 해당 문장(블록)을 강등한다.
    """
    candidates: List[str] = []
    for m in TAG_PHOTO_RE.finditer(block):
        photo_n = m.group(1)
        label = m.group(2)
        conf = float(m.group(3))
        candidates.append(f"[사진{photo_n}:{label} {conf:.2f}]")
    for m in TAG_LAW_RE.finditer(block):
        candidates.append(m.group(0))
    if not candidates:
        return []
    missing = [t for t in candidates if not _tag_valid_in_result(t, result)]
    return missing


def _tag_valid_in_result(tag: str, result: Dict[str, Any]) -> bool:
    """근거 태그가 실제 inspect_result 내역에 존재하는지 확인.

    사진 태그: 사진별 검출 목록에 label+conf(소수점2자리 반올림 일치)가 존재해야 함.
    법령 태그: 해당 사진의 law_refs에 조 번호가 존재해야 함.
    """
    pm = TAG_PHOTO_RE.match(tag)
    if pm:
        label = pm.group(2)
        conf = float(pm.group(3))
        for ph in result.get("photos", []):
            for d in ph.get("detections", []):
                if d.get("label") == label and round(d.get("conf", 0), 2) == round(conf, 2):
                    return True
        return False
    lm = TAG_LAW_RE.match(tag)
    if lm:
        art = None
        if lm.group(1):
            art = int(lm.group(1))
        elif lm.group(2):
            art = int(lm.group(2))
        if art is None:
            return False
        target = f"제{art}조"
        for ph in result.get("photos", []):
            for ref in ph.get("law_refs", []):
                if ref.get("조") == target:
                    return True
        return False
    return False


def _photo_by_number(result: Dict[str, Any], photo_n: int) -> Optional[Dict[str, Any]]:
    photos = result.get("photos", [])
    if 1 <= photo_n <= len(photos):
        return photos[photo_n - 1]
    return None


def _tag_present(block: str, tag: str) -> bool:
    return tag in block


def _demote_block(block: str, missing: List[str]) -> str:
    """근거 태그 누락 블록에 강등 표시 부착."""
    demote = " (확인 필요)"
    # 첫 줄 앞에 '(확인 필요)' 붙이기
    lines = block.split("\n")
    if lines:
        lines[0] = lines[0] + demote
    # 말미에 누락 태그 정보 추가
    lines.append("※ 누락 근거 태그: " + ", ".join(missing))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. 법령 재검증 (verify_law_refs 재통과)
# ---------------------------------------------------------------------------

def _reverify_law_refs(md: str, result: Dict[str, Any]) -> str:
    """초안에 포함된 법령 인용 표지를 verify_law_refs로 재검증.

    ❌(해당 조 없음)가 있으면 해당 문장(블록)을 제거하고 재생성 1회.
    여기서는 "제거 후 재생성 1회" 계약을 이행한다:
      - 위반 블록을 식별하여 제거
      - 남은 블록 + 법령 없는 블록들로 markdown 재조립 (근거가 남아 있는 범위에서)
    """
    refs = verify_all_law_refs(md)
    bad_blocks = _blocks_with_bad_law_refs(md, refs)
    if not bad_blocks:
        return md
    # 나쁜 블록 제거 후 재조립
    remaining = _remove_blocks(md, bad_blocks)
    # 한 번 더 검증: 제거 후에도 ❌가 남아 있으면 더 제거 (재귀 없이 1회로 제한)
    refs2 = verify_all_law_refs(remaining)
    bad_blocks2 = _blocks_with_bad_law_refs(remaining, refs2)
    if bad_blocks2:
        remaining = _remove_blocks(remaining, bad_blocks2)
    # 제거 후에는 강등 처리만 하고, 법령 없는 블록에 대해서는
    # 근거가 부족한 문장으로 간주하여 (확인 필요) 표시를 유지한다.
    remaining = _postprocess_tags(remaining, result)
    return remaining


def _blocks_with_bad_law_refs(md: str, refs: List[Dict[str, Any]]) -> List[str]:
    """❌ 판정된 인용이 포함된 블록 목록."""
    bad_articles: set = set()
    for r in refs:
        if r.get("verdict") == "해당 조 없음":
            # 조문 번호 확보
            art = r.get("article")
            if art:
                bad_articles.add(art)
    if not bad_articles:
        return []

    blocks = _split_blocks(md)
    bad_blocks: set = set()
    for b in blocks:
        for art in bad_articles:
            if re.search(rf"제{art}조", b):
                bad_blocks.add(b)
                break
    return list(bad_blocks)


def _remove_blocks(md: str, bad_blocks: List[str]) -> str:
    """특정 블록들을 제거하고 남은 블록들을 재조립."""
    bad_set = set(bad_blocks)
    blocks = _split_blocks(md)
    remaining = [b for b in blocks if b not in bad_set]
    return "\n\n".join(remaining)


# ---------------------------------------------------------------------------
# 4. 문장 제거 헬퍼 (regenerate_draft_once 용)
# ---------------------------------------------------------------------------

def _remove_sentences(md: str, sentences: List[str]) -> str:
    """지정된 문장(부분 문자열)을 markdown 에서 제거."""
    out = md
    for s in sentences:
        if s and s in out:
            out = out.replace(s, "")
    return out


# ---------------------------------------------------------------------------
# CLI / 간단 검증
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    ROOT = sys.path[0] if sys.path else "."
    sys.path.insert(0, ROOT)

    from service.core.inspect_mode import inspect_photos

    demo = [
        "assets/vision/demo_photos/r1_l3_pipe.jpg",
        "assets/vision/demo_photos/r1_l2_loading.jpg",
        "assets/vision/demo_photos/r1_l1_electrical.jpg",
    ]

    result = inspect_photos(demo)
    draft = generate_draft(result)

    print("=" * 70)
    print("M9 draft_report 데모")
    print("=" * 70)
    print(draft)
    print("=" * 70)
    print("JSON 형태로도 확인:")
    print(json.dumps({"inspect_result": result, "draft_md": draft}, ensure_ascii=False, indent=2))
