#!/usr/bin/env python3
"""프로세스: 4개 fixture PDF를 Document Parse로 처리해 캐시에 저장 (파일당 1회)."""

import os
import sys
from pathlib import Path

# 프로젝트 루트
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from service.core.docparse_client import call_document_parse, CACHE_DIR

FIXTURES = [
    "fixture_1col.pdf",
    "fixture_2col_bracket.pdf",
    "fixture_apa.pdf",
    "fixture_2page.pdf",
]

for name in FIXTURES:
    pdf_path = ROOT / "tests" / "fixtures" / name
    if not pdf_path.exists():
        print(f"⚠️  없음: {pdf_path}")
        continue

    print(f"📄 처리 중: {name} → {pdf_path}")
    try:
        result = call_document_parse(str(pdf_path))
        elements = result.get("elements", result.get("content", {}).get("elements", []))
        print(f"   요소 {len(elements)}개, 캐시 저장 완료")
    except Exception as e:
        print(f"   ❌ 오류: {e}")

print("✅ 모든 fixture 처리 완료")
