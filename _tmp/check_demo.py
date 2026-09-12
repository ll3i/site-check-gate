#!/usr/bin/env python3
"""합성 시연 문서 5상황 판정 검증."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from service.core.verify_law_refs import verify_all_law_refs, extract_law_refs, lookup_article, law_claim_vs_article
from service.core.subcontract_check import check_subcontract

import _tmp.demo_text as demo

print("=== ① 법령 인용 표지 추출 ===")
refs = extract_law_refs(demo.DEMO_TEXT)
for r in refs:
    art = f"제{r['article']}조"
    if r.get('paragraph'):
        art += f" 제{r['paragraph']}항"
    print(f"  추출: {r['law_name_raw']} {art}  raw='{r['raw']}'")
print()

print("=== ② 법령 인용 조회 (⛔ 확인 필요 — 스냅샷 조문 비어 있음) ===")
res = verify_all_law_refs(demo.DEMO_TEXT)
for r in res:
    art = f"제{r['article']}조"
    if r.get('paragraph'):
        art += f" 제{r['paragraph']}항"
    icon = r.get('status_icon')
    verdict = r.get('verdict')
    print(f"  {icon} {verdict} | {r['law_name_raw']} {art}")
    print(f"     note: {r['note']}")
    # 실존 조항(노동조합법 제2조, 산업안전보건법 제38조, 중대재해법 제4조)도
    # 현재 스냅샷 조문이 비어 있으므로 ⛔. 미등록/환각(근로기준법 제999조)도 ⛔.
    # 지금은 모두 ⛔가 정상 동작.
print()

print("=== ③ 법령판 오인용 대조 (주장 vs 조문 본문) ===")
# '원청이 직접 작업 지시를 해도 적법하다' vs 제2조(정의)
jo2 = lookup_article("노동조합 및 노동관계조정법", 2)
print(f"  lookup 제2조: verdict={jo2.get('verdict')}, body={jo2.get('article_body')}")
if jo2.get('article_body'):
    c = law_claim_vs_article("원청이 직접 작업 지시를 해도 적법하다", jo2['article_body'])
    print(f"  대조 결과: verdict={c['verdict']}, quote_exists={c['quote_exists']}")
    print(f"  quote: '{c.get('quote','')}'")
else:
    c = law_claim_vs_article("원청이 직접 작업 지시를 해도 적법하다", None)
    print(f"  대조 결과: verdict={c['verdict']} (조문 본문 없음 → 판단 불가)")
    print(f"  quote_exists={c['quote_exists']}")
    print("  → 현재 스냅샷에 조문이 없으므로 오인용 여부는 LLM/본문 확보 후 판정 대상.")
    print("  → 다만 주장 문장이 '제2조(정의)에 근거한다'고 하나 제2조가 정의 조항임을 감안하면")
    print("     조문 본문이 확보되면 법령판 오인용(🔴)으로 판정될 가능성이 높다.")
print()

print("=== ④ 적법도급 체크리스트 3분기 판정 ===")
out = check_subcontract(demo.DEMO_TEXT)
print(f"총 항목: {out['total_items']}")
for r in out['results']:
    print(f"  축{r['axis']}-{r['item']} [{r['label']}] {r['name']}")
    if r['evidence_sentences']:
        for s in r['evidence_sentences'][:2]:
            print(f"     └ 근거 문장: {s[:90]}")
    if r['risk_keywords_hit']:
        print(f"     └ 위험 키워드: {r['risk_keywords_hit']}")
    if r['compliant_keywords_hit']:
        print(f"     └ 적법 키워드: {r['compliant_keywords_hit']}")
print()

print("=== ⑤ 5상황 판정 요약 ===")
print(" ① 실존 조항 정상 인용 2건: 노동조합법 제2조(1-1), 산업안전보건법 제38조(1-2) → 추출·⛔ 확인 (스냅샷 미보유)")
print(" ② 존재하지 않는 조항 인용 1건: 근로기준법 제999조(1-4) → 추출·⛔ (미등록 법령 → ⛔)")
print(" ③ 실존하나 무관한 조항 인용 1건: 노동조합법 제2조(1-5) 근거 '원청 직접 지시 적법' 주장")
print("    → 조문 본문 없으므로 판단 불가(현재). 추후 조문 확보 시 법령판 오인용(🔴) 판정 가능.")
print(" ④ 지휘·명령 위험 신호 문장 1건: '원청 직원이 직접 작업 지시'(2-1) → 근거 있음-위험 신호")
print(" ⑤ 근거 없는 적법 주장 1건: '원청 근태 통제 없었음' 적법 주장(2-4) → 근거 없음-확인 필요")
