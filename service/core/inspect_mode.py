#!/usr/bin/env python3
"""
inspect_mode.py — 사진 단독 안전 점검 엔진 (M9 §1).

입력: photo_files 목록 (문서 없음).
처리:
  ① 각 사진에 photo_detect 를 defect 와 cleaning 두 도메인으로 실행.
     gauge 는 파일명·선택 옵션에 '계기'가 있을 때만 실행.
     conf < 0.45 는 버린다 (교차 도메인 오탐 억제).
  ② 검출 라벨 → 위험 분류·법령 연결 테이블 (결정론, LABEL_MAP 상수).
     각 항목의 법령 조문은 verify_law_refs 스냅샷에서 실제 조문 발췌를 붙인다.
     조문 없으면 연결하지 않는다 (지어내기 금지).
  ③ 사진별 결과: {photo, detections[], risk_level, law_refs[{법령,조,발췌}], action}.
  ④ 종합: 위험 n·주의 m·양호 k, 전체 판정.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from service.core.photo_detect import detect_objects
from service.core.verify_law_refs import lookup_article

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

CONF_MIN = 0.45
"""conf 하한. 이 미만은 교차 도메인 오탐 억제를 위해 버린다."""

LABELS_RISK = frozenset({
    "corrosion", "crack", "wall_damage", "weld_defect", "weld_bad",
    "cable_damage",
})
"""위험 등급으로 분류할 검출 라벨 집합."""

LABELS_CAUTION = frozenset({
    "cardboard", "plastic", "glass", "metal", "paper",
})
"""주의 등급으로 분류할 검출 라벨 집합."""

# 법령 연결은 결정론 테이블 + verify_law_refs 스냅샷 조회로 확정한다.
# 테이블에는 법령명(스냅샷 등록명)과 조 번호를 저장하고,
# 실제 조문 본문은 lookup_article 로mbert exacerbations(여기서) 가져온다.
# 판정: 조문 확보가 안 되어 있으면(아래 조회 결과가 verdict!='실존' 이면)
#       해당 법령 연결은 결과에 넣지 않는다 — 지어내기 금지.
LABEL_MAP: Dict[str, Dict[str, Any]] = {
    # --- 위험 계통 ---
    "corrosion":   {"risk": "위험", "category": "시설 결함(부식)",      "law": ("산업안전보건법", 38)},
    "crack":       {"risk": "위험", "category": "시설 결함(균열)",      "law": ("산업안전보건법", 38)},
    "wall_damage": {"risk": "위험", "category": "시설 결함(벽체 손상)",  "law": ("산업안전보건법", 38)},
    "weld_defect": {"risk": "위험", "category": "시설 결함(용접 불량)",  "law": ("산업안전보건법", 38)},
    "weld_bad":    {"risk": "위험", "category": "시설 결함(용접 불량)",  "law": ("산업안전보건법", 38)},
    "cable_damage":{"risk": "위험", "category": "전기 위험(케이블 손상)","law": ("산업안전보건법", 38)},
    # --- 주의 계통 (방치 적재물·폐기물) ---
    "cardboard": {"risk": "주의", "category": "통로·적치 위험(방치물)", "law": ("산업안전보건법", 38)},
    "plastic":   {"risk": "주의", "category": "통로·적치 위험(방치물)", "law": ("산업안전보건법", 38)},
    "glass":     {"risk": "주의", "category": "통로·적치 위험(방치물)", "law": ("산업안전보건법", 38)},
    "metal":     {"risk": "주의", "category": "통로·적치 위험(방치물)", "law": ("산업안전보건법", 38)},
    "paper":     {"risk": "주의", "category": "통로·적치 위험(방치물)", "law": ("산업안전보건법", 38)},
}

# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def inspect_photos(
    photo_files: List[str],
    gauge: bool = False,
) -> Dict[str, Any]:
    """사진 여러 장을 사진 단독 점검한다.

    Args:
        photo_files: 사진 파일 경로 목록.
        gauge: True 면 파일명과 무관하게 gauge 도메인을 추가 실행한다.
               파일명에 '계기'가 포함되면 자동 추가된다.

    Returns:
        {
            "photos": [사진별 결과 ...],
            "summary": {
                "위험": n, "주의": m, "양호": k,
                "판정": "조치 필요" | "주의" | "양호",
            },
        }
    """
    if not photo_files:
        return {"photos": [], "summary": {"위험": 0, "주의": 0, "양호": 0, "판정": "양호"}}

    per_photo: List[Dict[str, Any]] = []
    counts = {"위험": 0, "주의": 0, "양호": 0}

    for pf in photo_files:
        r = _inspect_one(pf, gauge=gauge)
        per_photo.append(r)
        counts[r["risk_level"]] += 1

    verdict = _aggregate_verdict(counts)
    return {"photos": per_photo, "summary": {**counts, "판정": verdict}}


def inspect_one(photo_file: str, gauge: bool = False) -> Dict[str, Any]:
    """단일 사진 점검 결과를 반환한다 (종합 없는 버전)."""
    return _inspect_one(photo_file, gauge=gauge)


# ---------------------------------------------------------------------------
# 내부 구현
# ---------------------------------------------------------------------------

def _inspect_one(photo_file: str, gauge: bool = False) -> Dict[str, Any]:
    basename = os.path.basename(photo_file)

    # ① 도메인별 검출 (conf 필터링 포함)
    defect_dets = _run_domain(photo_file, "defect")
    cleaning_dets = _run_domain(photo_file, "cleaning")

    gauge_run = gauge or ("계기" in basename)
    gauge_dets = _run_domain(photo_file, "gauge") if gauge_run else []

    # 라벨별로 분류 (LABEL_MAP 기준)
    labeled: List[Dict[str, Any]] = []
    law_keys: set = set()  # (법령명, 조) 중복 제거

    for det in defect_dets + cleaning_dets + gauge_dets:
        label = det["label"]
        entry = LABEL_MAP.get(label)
        if entry is None:
            # LABEL_MAP에 없는 라벨은 점검 결과에는 포함하되 법령 연결은 하지 않는다
            labeled.append({"det": det, "entry": None})
            continue
        labeled.append({"det": det, "entry": entry})
        law_keys.add(entry["law"])

    # ② 법령 조문 발췌 (실제 스냅샷 원문)
    law_refs = _build_law_refs(law_keys)

    # ③ 위험도 판정
    risk_level = _classify_risk(labeled)

    # ④ 권고 액션
    action = _build_action(risk_level, labeled)

    # 검출 목록은 클라이언트 표시용 평문 dict 로 반환
    detections = [_normalize_det(d["det"]) for d in labeled]

    # ④ annotated 경로 생성 (박스 주석 이미지)
    demo_dir = Path(__file__).resolve().parent.parent.parent / "assets" / "vision" / "demo_photos"
    annotated_path: Optional[str] = None
    try:
        from service.core.annotate import annotate_image_with_risk_badge
        if demo_dir.is_dir():
            src_photo = demo_dir / basename
            if src_photo.is_file():
                annotated_filename = f"annotated_{basename}"
                annotated_path = str(demo_dir / annotated_filename)
                annotate_image_with_risk_badge(
                    str(src_photo),
                    detections,
                    annotated_path,
                    risk_level=risk_level,
                )
    except Exception:
        pass  # annotated 생성 실패해도 결과에는 영향 없음

    # detections의 box는 이미 _normalize_det에서 포함

    return {
        "photo": basename,
        "photo_path": photo_file,
        "detections": detections,
        "risk_level": risk_level,
        "law_refs": law_refs,
        "action": action,
        "annotated": annotated_path,
        "gauge_run": gauge_run,
    }


def _run_domain(image_path: str, domain: str) -> List[Dict[str, Any]]:
    """도메인 검출 후 conf >= CONF_MIN 필터링된 결과를 반환."""
    try:
        dets = detect_objects(image_path, domain)
    except Exception:
        return []
    return [d for d in dets if d.get("conf", 0.0) >= CONF_MIN]


def _build_law_refs(law_keys: set) -> List[Dict[str, Any]]:
    """(법령명, 조) 집합 → 조문 발췌가 확보된 것만 리스트로 반환."""
    refs: List[Dict[str, Any]] = []
    seen: set = set()
    for law_name, article in sorted(law_keys):
        k = (law_name, article)
        if k in seen:
            continue
        seen.add(k)
        res = lookup_article(law_name, article)
        # 조문 발췌가 실제로 확보된 경우만 포함 (verdict == '실존' 이고 article_body 존재)
        body = res.get("article_body")
        verdict = res.get("verdict", "")
        if verdict == "실존" and body:
            refs.append({
                "법령": law_name,
                "조": f"제{article}조",
                "발췌": _emit_article_body(body),
            })
        # 조문 미보유·해당 조 없음이면 연결하지 않음 (지어내기 금지)
    return refs


def _emit_article_body(body: Any) -> str:
    """lookup_article 이 돌려준 본문을 평문 문자열로 정규화."""
    if isinstance(body, str):
        return body.strip()
    if isinstance(body, dict):
        parts: List[str] = []
        title = body.get("제목")
        if title:
            parts.append(f"({title}) ")
        paragraphs = body.get("항")
        if isinstance(paragraphs, list):
            for i, para in enumerate(paragraphs, 1):
                if isinstance(para, dict):
                    txt = para.get("본문") or para.get("text") or ""
                elif isinstance(para, str):
                    txt = para
                else:
                    txt = ""
                if txt:
                    parts.append(f"{i}항: {txt} ")
        elif isinstance(paragraphs, str) and paragraphs.strip():
            parts.append(paragraphs.strip())
        return "".join(parts).strip()
    return str(body)


def _classify_risk(labeled: List[Dict[str, Any]]) -> str:
    """사진 단위 위험도: 위험 > 주의 > 양호 우선순위."""
    has_risk = False
    has_caution = False
    for item in labeled:
        entry = item["entry"]
        if entry is None:
            continue
        if entry["risk"] == "위험":
            has_risk = True
        elif entry["risk"] == "주의":
            has_caution = True
    if has_risk:
        return "위험"
    if has_caution:
        return "주의"
    return "양호"


def _build_action(risk_level: str, labeled: List[Dict[str, Any]]) -> str:
    """위험도 + 검출 내용에 기반한 한 줄 권고."""
    if risk_level == "위험":
        cats = set()
        for item in labeled:
            if item["entry"]:
                cats.add(item["entry"]["category"])
        cat_list = ", ".join(sorted(cats))
        return f"[{risk_level}] {cat_list} — 즉시 안전조치 및 보수·정비 필요 (산업안전보건법 제38조 참조)."
    if risk_level == "주의":
        cats = set()
        for item in labeled:
            if item["entry"]:
                cats.add(item["entry"]["category"])
        cat_list = ", ".join(sorted(cats))
        return f"[{risk_level}] {cat_list} — 통로 확보·정리정돈 등 개선 권고 (산업안전보건법 제38조 참조)."
    return "[양호] 검출된 위험·주의 요소 없음. 정기 점검 유지."


def _aggregate_verdict(counts: Dict[str, int]) -> str:
    if counts.get("위험", 0) >= 1:
        return "조치 필요"
    if counts.get("주의", 0) >= 1:
        return "주의"
    return "양호"


def _normalize_det(det: Dict[str, Any]) -> Dict[str, Any]:
    """검출 dict 를 클라이언트 표시용 평면 형태로 정리."""
    return {
        "label": det.get("label", ""),
        "conf": det.get("conf", 0.0),
        "box": det.get("box", [0, 0, 0, 0]),
    }


# ---------------------------------------------------------------------------
# CLI (디버깅용)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    ROOT = Path(__file__).resolve().parent.parent
    DEMO_DIR = ROOT / "assets" / "vision" / "demo_photos"

    demo_files = [
        str(DEMO_DIR / "r1_l3_pipe.jpg"),
        str(DEMO_DIR / "r1_l2_loading.jpg"),
        str(DEMO_DIR / "r1_l1_electrical.jpg"),
    ]

    print("=" * 70)
    print("M9 inspect_mode 데모 (demo_photos 3장)")
    print("=" * 70)

    result = inspect_photos(demo_files)
    print(json.dumps(result, ensure_ascii=False, indent=2))
