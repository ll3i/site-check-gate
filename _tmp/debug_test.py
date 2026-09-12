#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from service.core.verify_law_refs import extract_law_refs
from service.core.subcontract_check import check_subcontract

print("=== test_duplicate_블록_and_free_통합 ===")
text = "「근로기준법」 제11조를 근거로 하며 근로기준법 제11조도 같다."
refs = extract_law_refs(text)
print(f"len={len(refs)}")
for i, r in enumerate(refs):
    print(f"  {i}: start={r['start']} end={r['end']} name={r['law_name_raw']} art={r['article']} raw={r['raw']!r}")
print()

print("=== test_free_인용_법 ===")
text = "파견근로자 보호 등에 관한 법률 제6조의2를 인용한다."
refs = extract_law_refs(text)
print(f"len={len(refs)}")
for i, r in enumerate(refs):
    print(f"  {i}: name={r['law_name_raw']!r} art={r['article']} raw={r['raw']!r}")
print()

print("=== test_noneed_when_no_evidence_for_control ===")
text = "일반적 현황만 적혀 있고 근태 관련 내용은 없다."
out = check_subcontract(text)
for r in out['results']:
    if r['axis'] == 1 and r['item'] == 3:
        print(f"축1-3 label={r['label']} ev_len={len(r['evidence_sentences'])}")
        for s in r['evidence_sentences']:
            print(f"  ev: {s!r}")
        print(f"  matched_patterns: {r['matched_patterns']!r}")
