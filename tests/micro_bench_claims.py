#!/usr/bin/env python3
"""
micro_bench_claims.py — 문자열 대조기(unit) + 인용 표지 추출(unit) 마이크로벤치.
API 호출 없이 결정론 함수만 테스트한다.
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

from service.core.extract_claims import (
    split_sentences,
    find_claim_markers,
    extract_claims_from_text,
)

# ── normalize_text 벤치마크 ──────────────────────────────────────────────────


class BenchNormalizeText(unittest.TestCase):
    """소문자화·공백 접기·따옴표 통일·양끝 구두점 제거."""

    CASES = [
        # (입력, 기대 출력 — 양끝 구두점 제거 + 따옴표 통일)
        ("Hello World", "hello world"),
        ("  foo   bar\t\nbaz  ", "foo bar baz"),
        ('"Hello," said John.', "hello,' said john"),
        ('"Attention is All You Need"', "attention is all you need"),
        ("「한국어」 문장. ", "한국어 문장"),
        ("(test)", "test"),
        ("end.", "end"),
        ("start...", "start"),
        ("…middle…", "middle"),
    ]

    def test_table(self):
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                got = normalize_text(raw)
                self.assertEqual(
                    got, expected,
                    f"normalize_text({raw!r}) = {got!r}, 기대 {expected!r}"
                )


# ── split_ellipsis 벤치마크 ──────────────────────────────────────────────────


class BenchSplitEllipsis(unittest.TestCase):
    """...·… 분할 테스트."""

    CASES = [
        # (입력, 기대 최소 포함 문자열 집합)
        ("...start...middle...end...", {"start", "middle", "end"}),
        ("…한…두…세…", {"한", "두", "세"}),
        ("no split here", {"no split here"}),
        ("", set()),
        ("...", set()),
        ("앞...뒤", {"앞", "뒤"}),
        ("a…b…c", {"a", "b", "c"}),
    ]

    def test_table(self):
        for raw, expected_parts in self.CASES:
            with self.subTest(raw=raw):
                parts = split_ellipsis(raw)
                got_set = set(parts)
                self.assertEqual(
                    got_set, expected_parts,
                    f"split_ellipsis({raw!r}) = {parts!r}, 기대 포함집합 {expected_parts!r}"
                )


# ── quote_exists_in_metadata 벤치마크 ──────────────────────────────────────


class BenchQuoteExists(unittest.TestCase):
    """문자열 대조기: 15자 필터, substring 검출."""

    META_TITLE = "Attention Is All You Need"
    META_ABSTRACT = (
        "We propose a new network architecture, the Transformer, based solely on "
        "attention mechanisms, dispensing with recurrence and convolutions entirely."
    )

    def test_real_quote_present(self):
        # 초록에 실제로 존재하는 구절
        self.assertTrue(
            quote_exists_in_metadata(
                "the transformer, based solely on attention mechanisms",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )

    def test_real_quote_with_ellipsis(self):
        # ...로 이어진 구절이 metadata에 실재하는지 (분할 후)
        self.assertTrue(
            quote_exists_in_metadata(
                "We propose a new network...dispensing with recurrence entirely",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )

    def test_short_excluded(self):
        # 15자 미만 구절만 매칭 → 제외하는 케이스
        self.assertFalse(
            quote_exists_in_metadata(
                "short text",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )

    def test_short_but_with_long_part(self):
        # 짧은 부분 + 긴 부분 혼합: 긴 부분이 실재하면 True
        self.assertTrue(
            quote_exists_in_metadata(
                "short...the transformer, based solely on attention mechanisms",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )

    def test_not_present(self):
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
                "new network architecture the Transformer",
                self.META_TITLE,
                self.META_ABSTRACT,
            )
        )


# ── 인용 표지 추출 벤치마크 ──────────────────────────────────────────────────


class BenchExtractClaims(unittest.TestCase):
    """extract_claims의 결정론 함수 단위 테스트."""

    def test_split_sentences_basic(self):
        text = "첫 문장이다. 두 번째 문장이다! 세 번째 문장? 네 번째다."
        sents = split_sentences(text)
        self.assertGreaterEqual(len(sents), 4)
        self.assertTrue(any("첫 문장" in s for s in sents))
        self.assertTrue(any("두 번째" in s for s in sents))

    def test_split_sentences_korean(self):
        text = "이것은 첫 문장이다. 저것은 두 번째 문장이다. 마지막이다."
        sents = split_sentences(text)
        self.assertGreaterEqual(len(sents), 3)

    def test_split_sentences_with_linebreak(self):
        text = "첫 문장이다.\n두 번째 문장이다.\n세 번째."
        sents = split_sentences(text)
        self.assertGreaterEqual(len(sents), 3)

    def test_find_number_marker(self):
        sent = "트랜스포머를 제안한다 [1]."
        markers = find_claim_markers(sent)
        self.assertTrue(any(m['type'] == 'number' and m['value'] == '1' for m in markers))

    def test_find_author_year_marker(self):
        sent = "Vaswani et al. (2017)은 트랜스포머를 제안하였다."
        markers = find_claim_markers(sent)
        self.assertTrue(
            any(m['type'] == 'author_year' and '2017' in m['value'] for m in markers)
        )

    def test_multiple_markers_single_sentence(self):
        sent = "트랜스포머 [1]와 BERT [2]를 비교한다."
        markers = find_claim_markers(sent)
        self.assertEqual(len(markers), 2)
        values = {m['value'] for m in markers}
        self.assertIn('1', values)
        self.assertIn('2', values)

    def test_extract_claims_from_text(self):
        text = (
            "트랜스포머를 제안한다 [1]. "
            "BERT는 사전학습에 효과적이다 [2]. "
            "추가로 He et al. (2016)도 언급된다."
        )
        claims = extract_claims_from_text(text, page=1)
        self.assertGreaterEqual(len(claims), 3)

        # 표지 유형별 분류 확인
        number_claims = [c for c in claims if c['marker_type'] == 'number']
        author_year_claims = [c for c in claims if c['marker_type'] == 'author_year']
        self.assertGreaterEqual(len(number_claims), 2)  # [1], [2]
        self.assertGreaterEqual(len(author_year_claims), 1)  # (He et al., 2016)

    def test_no_marker_returns_empty(self):
        text = "이것은 인용이 없는 문장이다. 단지 본문일 뿐이다."
        claims = extract_claims_from_text(text, page=1)
        self.assertEqual(claims, [])


# ── 파이프라인 통합 테스트 (오프라인) ──────────────────────────────────────


class BenchPipelineOffline(unittest.TestCase):
    """extract_claims → link_check 연결 검사까지 오프라인 검증."""

    def test_link_check_basic(self):
        """본문 + 참고문헌 대조."""
        from service.core.link_check import check_links

        body = (
            "트랜스포머를 제안한다 [1]. "
            "BERT는 사전학습에 효과적이다 [2]."
        )
        refs = [
            {"id": "1", "text": "1. Vaswani et al. (2017). Attention is all you need."},
            {"id": "2", "text": "2. Devlin et al. (2019). BERT: Pre-training of deep bidirectional transformers."},
            {"id": "3", "text": "3. Brown et al. (2020). Language models are few-shot learners."},
        ]

        result = check_links(body, refs)

        self.assertEqual(result['summary']['body_numbers'], 2)
        self.assertEqual(result['summary']['ref_numbers'], 3)
        self.assertEqual(result['summary']['uncited_count'], 1)  # [3]은 본문에 없음
        self.assertEqual(result['summary']['missing_count'], 0)

        self.assertEqual(result['body_number_markers'], ['1', '2'])
        self.assertEqual(result['ref_number_markers'], ['1', '2', '3'])

    def test_link_check_missing_from_refs(self):
        """목록 누락: 본문에는 [4]가 있으나 참고문헌에 없음."""
        from service.core.link_check import check_links

        body = "트랜스포머를 제안한다 [1]. [4]도 언급된다."
        refs = [
            {"id": "1", "text": "1. Vaswani et al. (2017). Attention is all you need."},
        ]

        result = check_links(body, refs)
        self.assertEqual(result['summary']['missing_count'], 1)
        self.assertEqual(result['missing_from_refs'][0]['value'], '4')

    def test_link_check_author_year(self):
        """저자-연도 표지 연결 검사."""
        from service.core.link_check import check_links

        body = "Vaswani et al. (2017)은 트랜스포머를 제안했다."
        refs = [
            {"id": "1", "text": "Vaswani, A., et al. (2017). Attention is all you need."},
        ]

        result = check_links(body, refs)
        self.assertEqual(result['summary']['body_author_years'], 1)
        self.assertEqual(result['summary']['ref_author_years'], 1)
        self.assertEqual(result['summary']['uncited_count'], 0)
        self.assertEqual(result['summary']['missing_count'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
