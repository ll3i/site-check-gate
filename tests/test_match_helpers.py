#!/usr/bin/env python3
"""
tests/test_match_helpers.py — 문자열 대조기 + 인용 표지 단위 테스트 (네트워크 불필요).

회귀 케이스(test_match.py)의 자매 모듈. 문자열 대조기, ellips 분할,
normalize_text 동작을 오프라인에서 검증한다.
"""

import json
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from service.core.match_claims import (
    normalize_text,
    split_ellipsis,
    quote_exists_in_metadata,
)


class TestNormalizeText(unittest.TestCase):
    """normalize_text 단위 — 대소문자, 공백, 따옴표, 구두점."""

    def test_lowercase(self):
        self.assertEqual(normalize_text("Hello World"), "hello world")

    def test_whitespace_fold(self):
        self.assertEqual(normalize_text("a   b\t\nc"), "a b c")

    def test_quote_unify_double_to_single(self):
        # 다양한 따옴표가 아포스트로피로 통일되고 양끝 구두점 제거
        variants = [
            ('"hello"', "hello"),
            ('"Hello," said.', "hello said"),
            ("'hello'", "hello"),
            ('"test"', "test"),
        ]
        for raw, expected in variants:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_text(raw), expected)

    def test_strip_edge_punct(self):
        self.assertEqual(normalize_text("test."), "test")
        self.assertEqual(normalize_text("(test)"), "test")
        self.assertEqual(normalize_text("test!"), "test")

    def test_ellipsis_stripped(self):
        self.assertEqual(normalize_text("…middle…"), "middle")


class TestSplitEllipsis(unittest.TestCase):
    """ellipsis 분할 단위: ...와 …"""

    def test_period_triple(self):
        parts = split_ellipsis("…start…middle…end…")
        self.assertIn("start", parts)
        self.assertIn("middle", parts)
        self.assertIn("end", parts)
        # 빈 조각은 제거
        self.assertEqual(len(parts), 3)

    def test_ellipsis_char(self):
        parts = split_ellipsis("한…두…세…")
        self.assertIn("한", parts)
        self.assertIn("두", parts)
        self.assertIn("세", parts)

    def test_no_ellipsis(self):
        parts = split_ellipsis("no ellipsis here at all")
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0], "no ellipsis here at all")

    def test_leading_trailing(self):
        parts = split_ellipsis("...front...back...")
        self.assertIn("front", parts)
        self.assertIn("back", parts)


class TestQuoteExists(unittest.TestCase):
    """quote 실재 검사 단위 — 메타데이터 substring 검출 + 15자 필터."""

    # Transformer 초록 (arXiv 1706.03762 — 실제 초록 기반)
    META_TITLE = "Attention Is All You Need"
    META_ABSTRACT = (
        "We propose a new network architecture, the Transformer, based solely on "
        "attention mechanisms, dispensing with recurrence and convolutions entirely. "
        "The Transformer uses self-attention to compute representations of its input "
        "and output without resorting to sequence-aligned RNNs or convolution."
    )

    def test_real_quote_present(self):
        # 초록에 실재하는 구절 (normalize 후 substring 매칭)
        self.assertTrue(
            quote_exists_in_metadata(
                "the transformer, based solely on attention mechanisms",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )

    def test_real_quote_with_ellipsis_split(self):
        # ...로 이어진 구절이 metadata에 실재하는지 확인 (분할 후)
        self.assertTrue(
            quote_exists_in_metadata(
                "We propose a new network...dispensing with recurrence and convolutions entirely",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )

    def test_short_quote_excluded(self):
        # 15자 미만 구절만 매칭 → 분할 없이 n-gram 매칭으로 실재 검출
        # "attention mechanisms"는 초록에 실재하고 길이 18자 → True
        self.assertTrue(
            quote_exists_in_metadata(
                "attention mechanisms",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )
        # 정말 짧은 구절(< 15자)이면서 실재하지 않으면 False
        self.assertFalse(
            quote_exists_in_metadata(
                "xyz short text",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )

    def test_quote_not_in_metadata(self):
        # 추상문에 없는 내용 → False
        self.assertFalse(
            quote_exists_in_metadata(
                "The Transformer uses exactly 8 attention heads",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )

    def test_empty_quote(self):
        self.assertFalse(quote_exists_in_metadata("", self.META_TITLE, self.META_ABSTRACT))

    def test_case_and_punct_normalized(self):
        # 대소문자·구두점 무시 substring 검출 — 초록에 실재하는 구절
        self.assertTrue(
            quote_exists_in_metadata(
                "ATTENTION MECHANISMS",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )


class TestKoreanText(unittest.TestCase):
    """한국어 텍스트에서도 대조기 작동 확인."""

    def test_korean_normalize(self):
        self.assertEqual(normalize_text("안녕, 세계!"), "안녕 세계")

    def test_korean_quote(self):
        meta_title = "한국 자연어 처리 모델 연구"
        meta_abstract = (
            "본 연구에서는 한국어 문장 분류를 위한 트랜스포머 기반 모델을 제안하고, "
            "실험을 통해 성능 향상을 입증하였다. 또한 대규모 말뭉치를 사용한 사전학습의 효과를 분석하였다."
        )
        self.assertTrue(
            quote_exists_in_metadata(
                "한국어 문장 분류를 위한 트랜스포머 기반 모델",
                meta_title,
                meta_abstract,
            )
        )
        self.assertFalse(
            quote_exists_in_metadata(
                "BLEU 점수 28.4를 달성",
                meta_title,
                meta_abstract,
            )
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
