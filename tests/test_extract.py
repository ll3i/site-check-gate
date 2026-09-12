#!/usr/bin/env python3
"""
test_extract.py — extract_refs.py 결정론 모듈 자동 검증 (표준 라이브러리 unittest).

캐시된 Document Parse 응답을 사용하여 테스트한다 (실행 시 네트워크 불필요).
캐시가 없으면 테스트가 건너뛰어지거나 실패한다.

검수 기준 (PRD M2):
| fixture | 항목 | DOI | arXiv | 본문 오염 |
| 1단 번호형 | 6/6 | 4/4 | 1/1 | 0 |
| 2단 대괄호형 | 4/4 | 2/2 | 1/1 | 0 |
| APA 저자-연도형 | 5/5 | 3/3 | 1/1 | 0 |
| 2페이지 | 7/7 | 4/4 | 1/1 | 0 |
"""

import json
import os
import re
import sys
import unittest
from pathlib import Path

# 프로젝트 루트 경로
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from service.core.extract_refs import extract_references_from_file


FIXTURES_DIR = ROOT / "tests" / "fixtures"
CACHE_DIR = FIXTURES_DIR / "cache"


def find_cache_for_fixture(fixture_name: str) -> Path:
    """fixture PDF에 대응하는 캐시 JSON 파일을 찾는다 (내용 해시 기준).

    캐시가 없으면 PDF를 다시 Document Parse해야 한다.
    """
    import hashlib
    pdf_path = FIXTURES_DIR / fixture_name
    if not pdf_path.exists():
        return None
    raw = pdf_path.read_bytes()
    key = hashlib.sha256(raw).hexdigest()[:16]
    cache_path = CACHE_DIR / f"{key}.json"
    return cache_path if cache_path.exists() else None


def load_ground_truth(fixture_name: str) -> dict:
    """ground_*.json 파일을 로드."""
    gt_path = FIXTURES_DIR / f"ground_{fixture_name}"
    if gt_path.exists():
        with open(gt_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def extract_dois(text: str) -> list:
    """텍스트에서 DOI 식별자 추출. 10.xxxx/xxxxx 형태."""
    pattern = re.compile(r'10\.\d{4,9}/[^\s"<>)]+', re.IGNORECASE)
    return pattern.findall(text)


def extract_arxiv_ids(text: str) -> list:
    """텍스트에서 arXiv ID 추출. 'arXiv: xxxx.xxxxx' 형태."""
    pattern = re.compile(r'arXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)', re.IGNORECASE)
    return pattern.findall(text)


def has_korean(text: str) -> bool:
    """한글 포함 여부."""
    return bool(re.search(r'[가-힣]', text))


def count_body_contamination(refs_texts: list, body_text: str) -> int:
    """
    본문 오염 검사: 참고문헌 항목 텍스트에 본문 문장이 포함되어 있는지 확인.
    현재는 간단히: 각 참고문헌 항목에 본문에서 온 문장이 포함되어 있으면 오염으로 간주.
    구체적으로는 '본 연구는', '이 연구는', '최근 연구에서는' 등 본문 시작 패턴이
    참고문헌 항목 텍스트에 포함되어 있는지 확인.
    """
    contamination = 0
    body_markers = ["이 연구는", "본 연구에서는", "최근 연구에서는", "이 논문은"]
    for ref_text in refs_texts:
        for marker in body_markers:
            if marker in ref_text:
                contamination += 1
                break
    return contamination


class TestExtractRefs(unittest.TestCase):
    """extract_refs.py 결정론 모듈 검증."""

    @classmethod
    def setUpClass(cls):
        """캐시 디렉토리가 있고 파일이 있는지 확인."""
        cls.cache_available = CACHE_DIR.exists() and any(CACHE_DIR.iterdir())
        cls.fixture_names = [
            "fixture_1col.pdf",
            "fixture_2col_bracket.pdf",
            "fixture_apa.pdf",
            "fixture_2page.pdf",
        ]

    def test_cache_exists(self):
        """캐시 디렉토리가 존재하고 파일이 있어야 한다."""
        if not self.cache_available:
            self.skipTest("캐시가 없습니다. 먼저 Document Parse API로 fixture를 처리하세요.")

    def test_fixture_1col(self):
        """1단 번호형: 항목 6/6, DOI 4/4, arXiv 1/1, 한국어 1/1, 본문 오염 0."""
        self._test_fixture("fixture_1col.pdf", expected_count=6, expected_dois=4, 
                           expected_arxivs=1, expected_korean=1, expected_contamination=0)

    def test_fixture_2col_bracket(self):
        """2단 대괄호형: 항목 4/4, DOI 2/2, arXiv 1/1, 본문 오염 0."""
        self._test_fixture("fixture_2col_bracket.pdf", expected_count=4, expected_dois=2,
                           expected_arxivs=1, expected_korean=0, expected_contamination=0)

    def test_fixture_apa(self):
        """APA 저자-연도형: 항목 5/5, DOI 3/3, arXiv 1/1, 한국어 1/1, 본문 오염 0."""
        self._test_fixture("fixture_apa.pdf", expected_count=5, expected_dois=3,
                           expected_arxivs=1, expected_korean=1, expected_contamination=0)

    def test_fixture_2page(self):
        """2페이지: 항목 7/7, DOI 4/4, arXiv 1/1, 한국어 1/1, 본문 오염 0."""
        self._test_fixture("fixture_2page.pdf", expected_count=7, expected_dois=4,
                           expected_arxivs=1, expected_korean=1, expected_contamination=0)

    def _test_fixture(self, fixture_name, expected_count, expected_dois, 
                      expected_arxivs, expected_korean, expected_contamination):
        """개별 fixture 테스트."""
        if not self.cache_available:
            self.skipTest("캐시가 없습니다.")

        cache_path = find_cache_for_fixture(fixture_name)
        if cache_path is None:
            self.fail(f"캐시 파일을 찾을 수 없음: {fixture_name}")

        # ground truth 로드
        gt = load_ground_truth(fixture_name.replace(".pdf", ""))
        
        # extract_refs 실행
        refs = extract_references_from_file(str(cache_path))
        
        # 항목 수 검증
        self.assertEqual(len(refs), expected_count,
                         f"항목 수 불일치: 기대 {expected_count}, 실제 {len(refs)}")

        # DOI 추출 및 검증
        all_text = " ".join(r["text"] for r in refs)
        found_dois = extract_dois(all_text)
        # 중복 제거 (동일 DOI가 여러 항목에 걸쳐 나타날 수 있음)
        unique_dois = list(dict.fromkeys(found_dois))
        self.assertEqual(len(unique_dois), expected_dois,
                         f"DOI 수 불일치: 기대 {expected_dois}, 실제 {len(unique_dois)}. "
                         f"발견: {unique_dois}")

        # ground truth의 DOI와 비교
        if gt.get("expected_dois"):
            gt_dois_set = set(gt["expected_dois"])
            found_dois_set = set(unique_dois)
            # ground truth DOI가 모두 발견되었는지 확인
            missing = gt_dois_set - found_dois_set
            self.assertEqual(len(missing), 0,
                             f"ground truth DOI 누락: {missing}")

        # arXiv 검증
        found_arxivs = extract_arxiv_ids(all_text)
        unique_arxivs = list(dict.fromkeys(found_arxivs))
        self.assertEqual(len(unique_arxivs), expected_arxivs,
                         f"arXiv 수 불일치: 기대 {expected_arxivs}, 실제 {len(unique_arxivs)}. "
                         f"발견: {unique_arxivs}")

        if gt.get("expected_arxivs"):
            gt_arxivs_set = set(gt["expected_arxivs"])
            found_arxivs_set = set(unique_arxivs)
            missing_arxivs = gt_arxivs_set - found_arxivs_set
            self.assertEqual(len(missing_arxivs), 0,
                             f"ground truth arXiv 누락: {missing_arxivs}")

        # 한국어 항목 수 검증
        korean_count = sum(1 for r in refs if has_korean(r["text"]))
        self.assertEqual(korean_count, expected_korean,
                         f"한국어 항목 수 불일치: 기대 {expected_korean}, 실제 {korean_count}")

        if gt.get("expected_korean_count") is not None:
            self.assertEqual(korean_count, gt["expected_korean_count"],
                             f"ground truth 한국어 항목 수 불일치")

        # 본문 오염 검증
        contamination = count_body_contamination([r["text"] for r in refs], "")
        self.assertEqual(contamination, expected_contamination,
                         f"본문 오염: 기대 0, 실제 {contamination}")

        # 추가로: 본문 내용이 참고문헌에 섞여 있는지 확인
        # (본문 마커가 참고문헌 텍스트에 없는지)
        body_markers = ["이 연구는", "본 연구에서는", "최근 연구에서는", "이 논문은"]
        for ref in refs:
            for marker in body_markers:
                self.assertNotIn(marker, ref["text"][:100],
                                 f"본문 마커 '{marker}'이 참고문헌 항목 첫머리에 발견됨: {ref['text'][:100]}...")


class TestExtractRefsEdgeCases(unittest.TestCase):
    """경계 사례 테스트."""

    def test_empty_elements(self):
        """빈 elements → 빈 결과."""
        from service.core.extract_refs import extract_references_from_elements
        result = extract_references_from_elements([])
        self.assertEqual(result, [])

    def test_no_heading(self):
        """참고문헌 헤딩이 없으면 모든 element가 버려져야 한다."""
        from service.core.extract_refs import extract_references_from_elements
        elements = [
            {"text": "Some body text", "page": 1, "category": "body",
             "boundingBox": [0.1, 0.1, 0.5, 0.1]},
            {"text": "More body text", "page": 1, "category": "body",
             "boundingBox": [0.1, 0.2, 0.5, 0.1]},
        ]
        result = extract_references_from_elements(elements)
        self.assertEqual(result, [])

    def test_header_excluded(self):
        """header/footer category는 제외되어야 한다."""
        from service.core.extract_refs import extract_references_from_elements
        elements = [
            {"text": "References", "page": 1, "category": "heading",
             "boundingBox": [0.1, 0.1, 0.5, 0.1]},
            {"text": "1. Test DOI: 10.1234/test", "page": 1, "category": "body",
             "boundingBox": [0.1, 0.2, 0.5, 0.1]},
            {"text": "Header text", "page": 1, "category": "header",
             "boundingBox": [0.1, 0.05, 0.5, 0.05]},
            {"text": "Footer text", "page": 1, "category": "footer",
             "boundingBox": [0.1, 0.95, 0.5, 0.05]},
        ]
        result = extract_references_from_elements(elements)
        # header/footer는 제외되고, References 헤딩 후 body 요소만 남음
        self.assertEqual(len(result), 1)
        self.assertIn("10.1234/test", result[0]["text"])

    def test_footnote_exception(self):
        """category가 footnote여도 표지·서지 패턴으로 시작하면 항목으로 취급."""
        from service.core.extract_refs import extract_references_from_elements
        elements = [
            {"text": "References", "page": 1, "category": "heading",
             "boundingBox": [0.1, 0.1, 0.5, 0.1]},
            {"text": "1. Test Ref DOI: 10.1234/test", "page": 1, "category": "footnote",
             "boundingBox": [0.1, 0.2, 0.5, 0.1]},
        ]
        result = extract_references_from_elements(elements)
        self.assertEqual(len(result), 1)
        self.assertIn("10.1234/test", result[0]["text"])

    def test_author_year_bib(self):
        """저자-연도 서지 패턴은 element 1개 = 항목 1개로 처리."""
        from service.core.extract_refs import extract_references_from_elements
        elements = [
            {"text": "References", "page": 1, "category": "heading",
             "boundingBox": [0.1, 0.1, 0.5, 0.1]},
            {"text": "Smith, J. (2016). A Great Study. DOI: 10.1234/test", 
             "page": 1, "category": "body",
             "boundingBox": [0.1, 0.2, 0.5, 0.1]},
        ]
        result = extract_references_from_elements(elements)
        self.assertEqual(len(result), 1)
        self.assertIn("10.1234/test", result[0]["text"])

    def test_merged_across_page(self):
        """E11b: 직전 항목이 p에 있고 현 element가 p+1 첫 본문성 element이면 병합."""
        from service.core.extract_refs import extract_references_from_elements
        elements = [
            {"text": "References", "page": 1, "category": "heading",
             "boundingBox": [0.1, 0.1, 0.5, 0.1]},
            {"text": "1. First item DOI: 10.1234/test", "page": 1, "category": "body",
             "boundingBox": [0.1, 0.2, 0.5, 0.1]},
            {"text": "Continuation text on page 2", "page": 2, "category": "body",
             "boundingBox": [0.1, 0.1, 0.5, 0.1]},
        ]
        result = extract_references_from_elements(elements)
        self.assertEqual(len(result), 1)
        self.assertIn("10.1234/test", result[0]["text"])
        self.assertIn("Continuation", result[0]["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
