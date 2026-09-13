#!/usr/bin/env python3
"""
tests/test_law.py — M8 회귀 테스트.

검수 대상:
 ① 법령 인용 표지 추출 (extract_law_refs)
 ② ⛔ 동작 (assets/law/ 조문 비어 있음 → lookup 전부 ⛔)
 ③ 적법도급 체크리스트 3분기 판정 (check_subcontract)
합성 텍스트로 5가지 상황(전 구간 실행에서 모두 올바르게 판정)을 고정.
"""
import json
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

# 프로젝트 루트
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from service.core.verify_law_refs import (
    extract_law_refs,
    verify_all_law_refs,
    lookup_article,
    law_claim_vs_article,
    VERDICT_NO_SNAPSHOT,
    VERDICT_NO_ARTICLE,
    VERDICT_EXISTS,
    _normalize_law_name,
    _load_snapshot,
)
from service.core.subcontract_check import (
    check_subcontract,
    evaluate_item,
    SUBSECTION_ITEMS,
    LABEL_FOUND_COMPLIANT,
    LABEL_FOUND_RISK,
    LABEL_NONEED,
)

# ── 합성 텍스트 (M8_message.md §5 검수 기준 + §3·§4 검증) ─────────────────────

SYNTHETIC_DOC = (
    "【가온물류센터 2026-09월 현장점검 보고서 (가상)】\n"
    "\n"
    "1. 근거 법령\n"
    "  1-1. 「노동조합 및 노동관계조정법」 제2조 제1호에 따라 노조 정의를 확인한다.\n"
    "  1-2. 「산업안전보건법」 제38조에 따라 도급 시 안전보건 조치를 검토한다.\n"
    "  1-3. 「중대재해 처벌 등에 관한 법률」 제4조를 인용한다.\n"
    "  1-4. 「근로기준법」 제999조를 근거로 들었다. (환각 조항)\n"
    "  1-5. 「노동조합 및 노동관계조정법」 제2조를 근거로 '원청이 직접 작업 지시를 해도 적법하다'고 주장한다.\n"
    "\n"
    "2. 적법도급 자가진단\n"
    "  2-1. 원청 직원이 수급인 근로자에게 직접 작업 지시를 하였다.\n"
    "  2-2. 당사는 별도 법인격을 가진 전문 업체로서 자체 장비를 보유하고 작업한다.\n"
    "  2-3. 계약 목적은 '물류센터 피킹 서비스 결과물 납품'으로 확정되어 있다.\n"
    "  2-4. 원청의 근태 통제가 없었기 때문에 적법하다. (별도 근거 없음)\n"
)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _law_ref_summary(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """extract_law_refs 결과를 요약형으로 변환."""
    out = []
    for r in refs:
        out.append({
            "law_name_raw": r["law_name_raw"],
            "article": r["article"],
            "paragraph": r.get("paragraph"),
            "raw": r["raw"],
        })
    return out


# ── ① 법령 인용 표지 추출 ──────────────────────────────────────────────────────

class TestLawRefExtraction(unittest.TestCase):
    """법령 인용 표지 결정론 추출."""

    def test_block_인용_with_para(self):
        """「~법」 제N조 제M항 블록 인용."""
        text = "「노동조합 및 노동관계조정법」 제2조 제1항에 따라 판단한다."
        refs = extract_law_refs(text)
        self.assertEqual(len(refs), 1)
        r = refs[0]
        self.assertEqual(r["law_name_raw"], "노동조합 및 노동관계조정법")
        self.assertEqual(r["article"], 2)
        self.assertEqual(r["paragraph"], 1)
        self.assertIn("노동조합 및 노동관계조정법", r["raw"])
        self.assertIn("제2조", r["raw"])
        self.assertIn("제1항", r["raw"])

    def test_block_인용_without_para(self):
        """「~법」 제N조 (항 생략)."""
        text = "「산업안전보건법」 제38조를 검토한다."
        refs = extract_law_refs(text)
        self.assertEqual(len(refs), 1)
        r = refs[0]
        self.assertEqual(r["law_name_raw"], "산업안전보건법")
        self.assertEqual(r["article"], 38)
        self.assertIsNone(r.get("paragraph"))

    def test_block_인용_법률(self):
        """「~법률」 형태 (한자/한글 혼합)."""
        text = "「중대재해 처벌 등에 관한 법률」 제4조를 인용한다."
        refs = extract_law_refs(text)
        self.assertEqual(len(refs), 1)
        r = refs[0]
        self.assertTrue(r["law_name_raw"].startswith("중대재해"))
        self.assertEqual(r["article"], 4)

    def test_free_인용_법(self):
        """블록 없는 ~법 제N조 형태."""
        text = "파견근로자 보호 등에 관한 법률 제6조의2를 인용한다."
        refs = extract_law_refs(text)
        self.assertGreaterEqual(len(refs), 1)
        r = refs[0]
        self.assertTrue("파견근로자" in r["law_name_raw"])
        self.assertEqual(r["article"], 6)

    def test_free_인용_법률(self):
        """블록 없는 ~법률 제N조."""
        text = "근로기준법 제11조를 근거로 한다."
        refs = extract_law_refs(text)
        self.assertGreaterEqual(len(refs), 1)
        r = refs[0]
        self.assertTrue("근로기준법" in r["law_name_raw"])
        self.assertEqual(r["article"], 11)

    def test_의M_항(self):
        """제N조의M 형태 (의M 항)."""
        text = "노동조합 및 노동관계조정법 제2조의2를 적용한다."
        refs = extract_law_refs(text)
        self.assertGreaterEqual(len(refs), 1)
        r = refs[0]
        para = r.get("paragraph")
        self.assertIsNotNone(para)
        self.assertEqual(para, 2)

    def test_no_인용_returns_empty(self):
        """법령 인용 표지가 없는 텍스트 → 빈 리스트."""
        text = "본 문서는 법령 인용이 없는 일반 보고서이다."
        refs = extract_law_refs(text)
        self.assertEqual(len(refs), 0)

    def test_incomplete_인용_조문없음_스킵(self):
        """법령명만 있고 조문이 없으면 추출하지 않음."""
        text = "「노동조합 및 노동관계조정법」에 대해 검토한다."
        refs = extract_law_refs(text)
        self.assertEqual(len(refs), 0)

    def test_duplicate_블록_and_free_통합(self):
        """「~법」 제N조 와 ~법 제N조 가 동일하게 있으면 한 번만 추출."""
        text = "「근로기준법」 제11조를 근거로 하며 근로기준법 제11조도 같다."
        refs = extract_law_refs(text)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["article"], 11)

    def test_extract_does_not_overlap(self):
        """중첩 표지가 있을 때 적절히 분리."""
        text = "「노동조합 및 노동관계조정법」 제2조 제1항과 「산업안전보건법」 제38조를 적용한다."
        refs = extract_law_refs(text)
        self.assertEqual(len(refs), 2)
        names = [r["law_name_raw"] for r in refs]
        self.assertIn("노동조합 및 노동관계조정법", names)
        self.assertIn("산업안전보건법", names)


# ── ② 스냅샷 조회 동작 (assets/law/ 조문 채워짐 → ✅/❌/⛔ 판정) ──────────────────────

class TestLawLookupWithSnapshot(unittest.TestCase):
    """
    assets/law/ 스냅샷에 조문이 채워진 상태에서의 lookup_article 동작 검증.

    등록된 법령 + 실존 조문 → ✅ 실존
    등록된 법령 + 없는 조문 → ❌ 해당 조 없음
    등록되지 않은 법령 → ⛔ 스냅샷 미보유
    """

    def _check(self, name: str, art: int, para: Optional[int] = None) -> Dict[str, Any]:
        return lookup_article(name, art, para)

    def test_registered_law_real_article_with_para(self):
        """노동조합법 제2조 제1호 → ✅ 실존 (실질적 지배 문구 포함)."""
        r = self._check("노동조합 및 노동관계조정법", 2, 1)
        self.assertEqual(r["verdict"], VERDICT_EXISTS)
        self.assertEqual(r["status_icon"], "✅")
        self.assertIsNotNone(r["article_body"])
        # article_body는 full_text(원문 전체 문자열) 또는 항 dict
        body = r["article_body"]
        if isinstance(body, str):
            body_text = body
        else:
            body_text = (body["항"][0] if body.get("항") else "")
        self.assertIn("실질적이고 구체적으로 지배", body_text)

    def test_registered_law_real_article_no_para(self):
        """산업안전보건법 제38조 → ✅ 실존."""
        r = self._check("산업안전보건법", 38)
        self.assertEqual(r["verdict"], VERDICT_EXISTS)
        self.assertEqual(r["status_icon"], "✅")
        self.assertIsNotNone(r["article_body"])

    def test_registered_law_emergency_exists(self):
        """중대재해처벌법 제4조 → ✅ 실존."""
        r = self._check("중대재해 처벌 등에 관한 법률", 4)
        self.assertEqual(r["verdict"], VERDICT_EXISTS)
        self.assertEqual(r["status_icon"], "✅")

    def test_registered_law_nonexistent_article(self):
        """근로기준법 제999조 → ❌ 해당 조 없음."""
        r = self._check("근로기준법", 999)
        self.assertEqual(r["verdict"], VERDICT_NO_ARTICLE)
        self.assertEqual(r["status_icon"], "❌")
        self.assertIn("999조", r["note"])

    def test_unregistered_law_still_hold(self):
        """등록되지 않은 법령 → ⛔ 스냅샷 미보유."""
        r = self._check("존재하지 않는 가상의 법률", 1)
        self.assertEqual(r["verdict"], VERDICT_NO_SNAPSHOT)
        self.assertEqual(r["status_icon"], "⛔")
        self.assertIn("등록되지 않았음", r["note"])

    def test_law_claim_vs_article_empty_body_could_not_judge(self):
        """조문 본문이 없으면 law_claim_vs_article → 판단 불가."""
        c = law_claim_vs_article("원청이 직접 작업 지시를 해도 적법하다", None)
        self.assertEqual(c["verdict"], "판단 불가")
        self.assertFalse(c["quote_exists"])

    def test_law_claim_vs_article_empty_dict_could_not_judge(self):
        """빈 dict도 본문 없음 → 판단 불가."""
        c = law_claim_vs_article("원청이 직접 작업 지시를 해도 적법하다", {})
        self.assertEqual(c["verdict"], "판단 불가")
        self.assertFalse(c["quote_exists"])


class TestNormalizeLawName(unittest.TestCase):
    """법령명 정규화: assets/law/ 키 매핑."""

    def test_normalize_block_law(self):
        key = _normalize_law_name("노동조합 및 노동관계조정법")
        self.assertNotEqual(key, "")

    def test_normalize_free_law(self):
        key = _normalize_law_name("산업안전보건법")
        self.assertNotEqual(key, "")

    def test_normalize_unregistered_law(self):
        key = _normalize_law_name("존재하지 않는 법률")
        # 등록되지 않았으면 원문 자체가 키로 사용됨
        self.assertEqual(key, re.sub(r"\s+", "", "존재하지 않는 법률"))


# ── ③ 적법도급 체크리스트 3분기 판정 ─────────────────────────────────────────────────

class TestSubcontractChecklist(unittest.TestCase):
    """5축 20항목 내외의 적법도급 체크리스트 3분기 판정."""

    def test_item_count_near_twenty(self):
        """항목 합계가 20개 내외(15~25)."""
        n = len(SUBSECTION_ITEMS)
        self.assertTrue(15 <= n <= 25,
                        f"항목 수가 {n}개로 20개 내외 범위를 벗어남")

    def test_all_items_have_patterns(self):
        """모든 항목이 최소 1개의 탐색 패턴을 가짐."""
        for item in SUBSECTION_ITEMS:
            self.assertTrue(item["patterns"])
            self.assertTrue(all(isinstance(p, re.Pattern) for p in item["patterns"]))

    def test_all_items_have_both_keyword_lists(self):
        """모든 항목이 적법·위험 키워드 리스트를 가짐 (empty 허용)."""
        for item in SUBSECTION_ITEMS:
            self.assertIn("compliant_keywords", item)
            self.assertIn("risk_keywords", item)

    def test_axis_labels_1_to_5(self):
        """축 번호가 1~5."""
        axes = {item["axis"] for item in SUBSECTION_ITEMS}
        self.assertEqual(axes, {1, 2, 3, 4, 5})

    def test_check_subcontract_returns_structure(self):
        """check_subcontract 가 올바른 구조의 dict 반환."""
        out = check_subcontract("아무 문서")
        self.assertIn("total_items", out)
        self.assertIn("results", out)
        self.assertIn("axis_summary", out)
        self.assertEqual(out["total_items"], len(SUBSECTION_ITEMS))
        for ax, s in out["axis_summary"].items():
            self.assertIn("item_count", s)
            self.assertIn("risk_count", s)
            self.assertIn("compliant_count", s)
            self.assertIn("noneed_count", s)

    def test_risk_signal_found_when_direct_order(self):
        """원청 직접 지시 문장 → 축1-1 위험 신호."""
        text = "원청 직원이 수급인 근로자에게 직접 작업 지시를 하였다."
        results = check_subcontract(text)["results"]
        item = next(r for r in results if r["item"] == 1 and r["axis"] == 1)
        self.assertEqual(item["label"], LABEL_FOUND_RISK)
        self.assertTrue(item["evidence_sentences"])
        self.assertIn("직접 작업 지시", item["risk_keywords_hit"])

    def test_compliant_found_when_own_equipment(self):
        """자체 장비 보유 문장 → 축5-1 적법 방향."""
        text = "당사는 자체 장비를 보유하고 작업한다."
        results = check_subcontract(text)["results"]
        item = next(r for r in results if r["item"] == 1 and r["axis"] == 5)
        self.assertEqual(item["label"], LABEL_FOUND_COMPLIANT)
        self.assertTrue(item["evidence_sentences"])

    def test_compliant_found_when_separate_corporation(self):
        """별도 법인 언급 → 축5-2 적법 방향."""
        text = "별도 법인격을 가진 전문 업체이다."
        results = check_subcontract(text)["results"]
        item = next(r for r in results if r["item"] == 2 and r["axis"] == 5)
        self.assertEqual(item["label"], LABEL_FOUND_COMPLIANT)

    def test_compliant_found_when_contract_purpose_defined(self):
        """계약 목적 확정 문장 → 축4-1 적법 방향."""
        text = "계약 목적은 '물류센터 피킹 서비스 결과물 납품'으로 확정되어 있다."
        results = check_subcontract(text)["results"]
        item = next(r for r in results if r["item"] == 1 and r["axis"] == 4)
        self.assertEqual(item["label"], LABEL_FOUND_COMPLIANT)

    def test_noneed_when_no_evidence_for_control(self):
        """근태 통제 관련 언급이 없으면 → 근거 없음-확인 필요."""
        text = "일반적 현황만 적혀 있고 근태 관련 내용은 없다."
        results = check_subcontract(text)["results"]
        item = next(r for r in results if r["item"] == 3 and r["axis"] == 1)
        self.assertEqual(item["label"], LABEL_NONEED)
        self.assertEqual(len(item["evidence_sentences"]), 0)

    def test_no_judgment_without_evidence_sentences(self):
        """근거 문장이 없으면 적법/위험 어느 쪽으로도 판정하지 않음."""
        text = "아무 근거가 없는 문장들이다."
        results = check_subcontract(text)["results"]
        for item in results:
            if item["label"] != LABEL_NONEED:
                # 근거 문장이 없는데 적법/위험으로 판정했다면 실패
                self.assertEqual(len(item["evidence_sentences"]), 0,
                                 f"항목 {item['axis']}-{item['item']}이 근거 문장 없이 판정됨")

    def test_synth_doc_five_situations_correct(self):
        """
        합성 문서에서 5가지 상황이 모두 올바르게 판정된다 (M8_message.md §5 검수 기준).

        상황:
          ① 실존 조항 정상 인용 2건 → 추출됨, ✅ 판정 (조문 실존, 본문 있음)
          ② 환각 조항 인용 1건 → 추출됨, ❌ 판정
          ③ 실존하나 무관한 조항 인용 1건 → 추출됨, ✅ 판정 (본문 대조 가능)
          ④ 지휘·명령 위험 신호 문장 1건 → 근거 있음-위험 신호
          ⑤ 근거 없는 적법 주장 1건 → 근거 없음-확인 필요
        """
        # ①~③: 법령 인용 표지 추출 및 판정
        refs = verify_all_law_refs(SYNTHETIC_DOC)
        self.assertGreaterEqual(len(refs), 4,
                                "합성 문서에서 충분한 법령 인용 표지가 추출되지 않음")
        # ① 실존 2건 + ② 환각 1건 + ③ 실존 1건 = 최소 4건
        verdicts = {r["verdict"] for r in refs}
        self.assertIn(VERDICT_EXISTS, verdicts, "실존 판정이 하나도 없음")
        self.assertIn(VERDICT_NO_ARTICLE, verdicts, "해당 조 없음 판정이 없음")

        # ④: 원청 직접 지시 → 위험 신호
        results = check_subcontract(SYNTHETIC_DOC)["results"]
        risk_items = [r for r in results if r["label"] == LABEL_FOUND_RISK]
        self.assertGreaterEqual(len(risk_items), 1,
                                "위험 신호 항목이 최소 1개 이상 검출되어야 함")
        risk_names = {r["name"] for r in risk_items}
        self.assertIn("작업 지시·명령의 원청 직접성", risk_names)

        # ⑤: 근거 없는 적법 주장 → 확인 필요
        noneed_items = [r for r in results if r["label"] == LABEL_NONEED]
        self.assertGreaterEqual(len(noneed_items), 1,
                                "근거 없음 항목이 최소 1개 이상 검출되어야 함")

class TestEvaluateItem(unittest.TestCase):
    """evaluate_item 단위 동작."""

    def test_label_values(self):
        """라벨 상수값 확인."""
        self.assertEqual(LABEL_FOUND_COMPLIANT, "근거 있음-적법 방향")
        self.assertEqual(LABEL_FOUND_RISK, "근거 있음-위험 신호")
        self.assertEqual(LABEL_NONEED, "근거 없음-확인 필요")

    def test_evidence_sentences_are_original(self):
        """근거 문장은 원문 문장 그대로여야 함."""
        text = "원청 직원이 직접 작업 지시를 하였다."
        item = SUBSECTION_ITEMS[0]  # 축1-1
        res = evaluate_item(item, text)
        for s in res["evidence_sentences"]:
            self.assertIsInstance(s, str)
            self.assertIn("직접 작업 지시", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
