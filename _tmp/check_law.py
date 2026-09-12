#!/usr/bin/env python3
"""verify_law_refs + subcontract_check 빠른 검증."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from service.core.verify_law_refs import verify_all_law_refs, law_claim_vs_article
from service.core.subcontract_check import check_subcontract, LABEL_FOUND_RISK, LABEL_FOUND_COMPLIANT, LABEL_NONEED

sample = (
    "「노동조합 및 노동관계조정법」 제2조 제1항에 따라...\n"
    "파견근로자 보호 등에 관한 법률 제6조의2를 인용한다.\n"
    "산업안전보건법 제38조.\n"
    "존재하지 않는 법률 제999조 (환각).\n"
    "「중대재해 처벌 등에 관한 법률」 제4조를 인용.\n"
)

print("=== 법령 인용 표지 추출·조회 ===")
res = verify_all_law_refs(sample)
for r in res:
    art = f"제{r['article']}조"
    if r.get('paragraph'):
        art += f" 제{r['paragraph']}항"
    print(f"{r.get('status_icon')} {r['verdict']:12s} | {r['law_name_raw']} {art}")
    print(f"   note: {r['note']}")
print()

print("=== 법령판 오인용 대조 (조문 본문 없음 → 판단 불가) ===")
for r in res:
    if r.get('article_body'):
        c = law_claim_vs_article("원청이 직접 작업 지시를 하였다", r['article_body'])
        print(f"대조: {r['law_name_raw']} 제{r['article']}조 → {c['verdict']} (quote_exists={c['quote_exists']})")
    else:
        c = law_claim_vs_article("원청이 직접 작업 지시를 하였다", None)
        print(f"대조: {r['law_name_raw']} 조문 없음 → {c['verdict']} (quote_exists={c['quote_exists']})")
print()

print("=== 적법도급 체크리스트 3분기 판정 ===")
doc = (
    "가. 원청 직원이 수급인 근로자에게 직접 작업 지시를 하였고,\n"
    "나. 원청 근로자와 같은 라인에서 혼재 작업하며,\n"
    "다. 원청이 출퇴근 시간을 확인·통제하였다.\n"
    "라. 수급인이 자체 장비를 보유하고 있으며,\n"
    "마. 별도 법인격을 가진 전문 업체이다.\n"
    "바. 계약 목적은 '물류센터 피킹 서비스 결과물 납품'으로 확정되어 있다.\n"
    "사. 원청이 근로자를 직접 채용하였다.\n"
)
out = check_subcontract(doc)
print(f"총 항목: {out['total_items']}")
for r in out['results']:
    print(f"축{r['axis']}-{r['item']} [{r['label']}] {r['name']}")
    if r['evidence_sentences']:
        for s in r['evidence_sentences'][:2]:
            print(f"   └ 근거 문장: {s[:80]}")
    if r['risk_keywords_hit']:
        print(f"   └ 위험 키워드: {r['risk_keywords_hit']}")
print()
print("축 요약:")
for ax, s in out['axis_summary'].items():
    print(f"  축{ax}: 총{s['item_count']} 적법{s['compliant_count']} 위험{s['risk_count']} 확인필요{s['noneed_count']}")
