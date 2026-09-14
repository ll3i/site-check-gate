#!/usr/bin/env python3
"""
tests/test_inspect.py — M9 사진 기반 안전 점검 엔진 회귀 테스트.

계약:
  - 검출(YOLO)은 캐시/mock 으로 대체한다 (실 추론을 일으키지 않는다).
  - inspect_mode 의 결정론 로직(라벨 분류·위험도·법령 연결·조문 발췌·종합 판정)을 검증.
  - draft_report 의 근거 태그·후처리 강등·verify_law_refs 재검증(❌0)을 검증.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

# 프로젝트 루트를 sys.path에 넣어 service 임포트가 가능하게 한다.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.core.inspect_mode import (
    inspect_one,
    inspect_photos,
    CONF_MIN,
    LABELS_RISK,
    LABELS_CAUTION,
    LABEL_MAP,
)
from service.core.draft_report import generate_draft
from service.core.verify_law_refs import verify_all_law_refs


# ---------------------------------------------------------------------------
# fixture: mock detect_objects  반환값
# ---------------------------------------------------------------------------

def _make_detections(
    labels: List[str],
    confs: List[float],
    boxes: List[List[int]] | None = None,
) -> List[Dict[str, Any]]:
    if boxes is None:
        boxes = [[0, 0, 100, 100] for _ in labels]
    return [
        {"label": lb, "conf": round(cn, 4), "box": bx}
        for lb, cn, bx in zip(labels, confs, boxes)
    ]


MOCK_DEFECT_HIGH = _make_detections(["corrosion", "corrosion", "crack"], [0.84, 0.81, 0.58])
MOCK_CLEANING_CAUTION = _make_detections(["cardboard", "cardboard"], [0.59, 0.47])
MOCK_ELECTRICAL_RISK = _make_detections(["cable_damage", "paper"], [0.5965, 0.4903])
MOCK_NONE = []
MOCK_BELOW_CONF = _make_detections(["corrosion"], [0.40])  # conf < CONF_MIN → 폐기되어야 함


def _mock_detect_objects(image_path: str, domain: str) -> List[Dict[str, Any]]:
    """도메인별 mock 반환.

    사진 파일명 기반 라우팅으로 각 테스트 케이스에 맞는 mock 을 돌려준다.
    실제 경로 의존을 피하기 위해 파일명 키로 분기한다.
    """
    name = Path(image_path).name
    if name == "r1_l3_pipe.jpg":
        if domain == "defect":
            return MOCK_DEFECT_HIGH
        if domain == "cleaning":
            return MOCK_NONE
        if domain == "gauge":
            return MOCK_NONE
    elif name == "r1_l2_loading.jpg":
        if domain == "defect":
            return MOCK_NONE
        if domain == "cleaning":
            return MOCK_CLEANING_CAUTION
        if domain == "gauge":
            return MOCK_NONE
    elif name == "r1_l1_electrical.jpg":
        if domain == "defect":
            return MOCK_ELECTRICAL_RISK
        if domain == "cleaning":
            return MOCK_NONE
        if domain == "gauge":
            return MOCK_NONE
    elif name == "no_risk.jpg":
        return MOCK_NONE
    elif name == "mixed_conf.jpg":
        if domain == "defect":
            return MOCK_BELOW_CONF + MOCK_DEFECT_HIGH
        if domain == "cleaning":
            return MOCK_NONE
        if domain == "gauge":
            return MOCK_NONE
    else:
        return MOCK_NONE
    return MOCK_NONE


# ---------------------------------------------------------------------------
# inspect_mode 결정론 검증
# ---------------------------------------------------------------------------

class TestInspectModeConstants:
    def test_conf_min(self):
        assert CONF_MIN == 0.45

    def test_label_map_risk_keys(self):
        for lb in LABELS_RISK:
            assert lb in LABEL_MAP
            assert LABEL_MAP[lb]["risk"] == "위험"

    def test_label_map_caution_keys(self):
        for lb in LABELS_CAUTION:
            assert lb in LABEL_MAP
            assert LABEL_MAP[lb]["risk"] == "주의"

    def test_label_map_law(self):
        for lb, entry in LABEL_MAP.items():
            assert "law" in entry
            law = entry["law"]
            # law은 (법령명, 조) 튜플이거나 None(보호구 착용 등 참고 검출)
            if law is not None:
                law_name, article = law
                assert isinstance(law_name, str)
                assert isinstance(article, int)


class TestInspectOnePhoto:
    def _run(self, name: str, gauge: bool = False) -> Dict[str, Any]:
        path = str(Path("assets/vision/demo_photos") / name)
        with patch("service.core.inspect_mode.detect_objects", side_effect=_mock_detect_objects):
            return inspect_one(path, gauge=gauge)

    def test_pipe_corrosion_risk(self):
        r = self._run("r1_l3_pipe.jpg")
        assert r["photo"] == "r1_l3_pipe.jpg"
        assert r["risk_level"] == "위험"
        labels = {d["label"] for d in r["detections"]}
        assert "corrosion" in labels
        assert "crack" in labels
        assert len(r["detections"]) == 3
        assert r["gauge_run"] is False

    def test_loading_caution(self):
        r = self._run("r1_l2_loading.jpg")
        assert r["risk_level"] == "주의"
        labels = {d["label"] for d in r["detections"]}
        assert labels == {"cardboard"}
        assert len(r["detections"]) == 2

    def test_electrical_risk(self):
        r = self._run("r1_l1_electrical.jpg")
        assert r["risk_level"] == "위험"
        labels = {d["label"] for d in r["detections"]}
        assert "cable_damage" in labels
        assert "paper" in labels
        assert len(r["detections"]) == 2

    def test_below_conf_filtered(self):
        r = self._run("mixed_conf.jpg")
        # 0.40 conf는 버려야 하고 0.84/0.81/0.58만 남아야 함
        confs = [d["conf"] for d in r["detections"]]
        assert all(c >= CONF_MIN for c in confs)
        assert not any(c < CONF_MIN for c in confs)
        assert len(r["detections"]) == 3

    def test_no_detections_is_ok(self):
        r = self._run("no_risk.jpg")
        assert r["risk_level"] == "양호"
        assert r["detections"] == []

    def test_law_refs_present(self):
        r = self._run("r1_l3_pipe.jpg")
        assert r["law_refs"]
        first = r["law_refs"][0]
        assert first["법령"] == "산업안전보건법"
        assert first["조"] == "제38조"
        assert first["발췌"]
        assert "제38조(안전조치)" in first["발췌"]

    def test_law_refs_no_ghost(self):
        """LABEL_MAP에 없는 라벨은 법령 연결하지 않음(지어내기 금지)."""
        r = self._run("r1_l3_pipe.jpg")
        for ref in r["law_refs"]:
            assert ref["법령"] == "산업안전보건법"


class TestInspectPhotosSummary:
    def test_summary_counts_and_verdict(self):
        paths = [
            str(Path("assets/vision/demo_photos") / n)
            for n in ["r1_l3_pipe.jpg", "r1_l2_loading.jpg", "r1_l1_electrical.jpg"]
        ]
        with patch("service.core.inspect_mode.detect_objects", side_effect=_mock_detect_objects):
            result = inspect_photos(paths)

        assert result["summary"]["위험"] == 2
        assert result["summary"]["주의"] == 1
        assert result["summary"]["양호"] == 0
        assert result["summary"]["판정"] == "조치 필요"

    def test_verdict_caution_only(self):
        paths = [str(Path("assets/vision/demo_photos") / "r1_l2_loading.jpg")]
        with patch("service.core.inspect_mode.detect_objects", side_effect=_mock_detect_objects):
            result = inspect_photos(paths)
        assert result["summary"]["판정"] == "주의"

    def test_verdict_ok(self):
        paths = [str(Path("assets/vision/demo_photos") / "no_risk.jpg")]
        with patch("service.core.inspect_mode.detect_objects", side_effect=_mock_detect_objects):
            result = inspect_photos(paths)
        assert result["summary"]["판정"] == "양호"

    def test_photos_list_structure(self):
        paths = [str(Path("assets/vision/demo_photos") / "r1_l3_pipe.jpg")]
        with patch("service.core.inspect_mode.detect_objects", side_effect=_mock_detect_objects):
            result = inspect_photos(paths)
        assert len(result["photos"]) == 1
        ph = result["photos"][0]
        for key in ("photo", "detections", "risk_level", "law_refs", "action"):
            assert key in ph


# ---------------------------------------------------------------------------
# draft_report 계약 검증
# ---------------------------------------------------------------------------

class TestDraftReportContract:
    @pytest.fixture
    def inspect_result(self):
        paths = [
            str(Path("assets/vision/demo_photos") / n)
            for n in ["r1_l3_pipe.jpg", "r1_l2_loading.jpg", "r1_l1_electrical.jpg"]
        ]
        with patch("service.core.inspect_mode.detect_objects", side_effect=_mock_detect_objects):
            return inspect_photos(paths)

    def test_all_sentences_have_evidence_tags(self, inspect_result):
        md = generate_draft(inspect_result)
        # 사진 블록마다 근거 태그 라인이 존재해야 함
        photo_blocks = re.split(r"\n## 사진 \d+\.", md)
        # 첫 분할은 헤더 부분이므로 제외
        for block in photo_blocks[1:]:
            assert re.search(r"\*\*근거 태그:\*\*", block), "사진 블록에 근거 태그 행이 없음"

    def test_law_refs_excerpt_included(self, inspect_result):
        md = generate_draft(inspect_result)
        assert "제38조(안전조치)" in md
        assert "산업안전보건법 제38조" in md

    def test_no_demotion_for_normal_draft(self, inspect_result):
        md = generate_draft(inspect_result)
        # 정상 초안은 강등 블록이 없어야 함
        assert "(확인 필요)" not in md

    def test_demotion_for_fake_tag(self, inspect_result):
        # 초안에 실제 결과에 없는 태그가 들어가면 강등되어야 함
        fake_md = (
            "# 사진 1. r1_l3_pipe.jpg\n\n"
            "**근거 태그:** [사진1:corrosion 0.84] [산안법제38조] [사진1:ghost 0.99]\n"
        )
        processed = generate_draft.__wrapped__(fake_md) if hasattr(generate_draft, "__wrapped__") else None
        if processed is None:
            # generate_draft가 비공개 진입점이 없으므로, 직접 _postprocess_tags를 본다
            from service.core.draft_report import _postprocess_tags
            processed = _postprocess_tags(fake_md, inspect_result)
        assert "(확인 필요)" in processed

    def test_verify_law_refs_no_false_article(self, inspect_result):
        md = generate_draft(inspect_result)
        refs = verify_all_law_refs(md)
        bad = [r for r in refs if r.get("verdict") == "해당 조 없음"]
        assert not bad, f"법령 ❌ 존재: {bad}"


class TestDraftReportStructure:
    def test_header_and_summary(self):
        paths = [str(Path("assets/vision/demo_photos") / "r1_l3_pipe.jpg")]
        with patch("service.core.inspect_mode.detect_objects", side_effect=_mock_detect_objects):
            result = inspect_photos(paths)
        md = generate_draft(result)
        assert md.startswith("# 현장 안전 점검 보고서 (초안)")
        assert "**종합 판정:**" in md
        assert "## 종합 현황" in md

    def test_recommendation_includes_law(self):
        paths = [str(Path("assets/vision/demo_photos") / "r1_l3_pipe.jpg")]
        with patch("service.core.inspect_mode.detect_objects", side_effect=_mock_detect_objects):
            result = inspect_photos(paths)
        md = generate_draft(result)
        assert "산업안전보건법 제38조" in md


# ---------------------------------------------------------------------------
# CLI 빠른 확인 (옵션)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
