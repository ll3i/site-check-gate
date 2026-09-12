#!/usr/bin/env python3
"""M8 변경 사항에 대한 집중 검증: (A)법령 인용 표지 추출 (B)⛔ 동작 (C)체크리스트 3분기."""
import re
import sys
import json
from pathlib import Path

# 운영체제에 안전한 임시 경로 (hermes-verify- 접두사)
tmp = Path(sys.executable).parent / "lib" / "tmp"
tmp = Path("/tmp") if Path("/tmp").is_dir() else Path.home() / "AppData" / "Local" / "Temp"
H = tmp / "hermes-verify_law_check.py"

H.write_text("#!/usr/bin/env python3\n# 임시 검증 스크립트 — M8변경사항 집중력 검증\n", encoding="utf-8")
print("검증 스크립트 준비 위치:", H)

# 실제 검증은 이 프로세스에서 직접 수행
sys.path.insert(0, str(Path(__file__).parent.parent))

from service.core.verify_law_refs import (
    extract_law_refs,
    verify_all_law_refs,
    lookup_article,
    _load_snapshot_meta,
)
from service.core.subcontract_check import check_subcontract, evaluate_item, SUBSECTION_ITEMS

errors = []

def check(cond, msg):
    if not cond:
        errors.append(msg)

# ── (A) 법령 인용 표지 추출 ──────────────────────────────────────────────────

print("\n=== (A) 법령 인용 표지 추출 ===")
cases = [
    ("법률 끝 자유 인용", "파견근로자 보호 등에 관한 법률 제6조의2를 인용한다.",
     1, None, 6, 2),
    ("한글 '법' 자유 인용", "근로기준법 제11조를 근거로 한다.",
     1, None, 11, None),
    ("블록+다항", "「노동조합 및 노동관계조정법」 제2조 제1항에 따라 판단한다.",
     1, "노동조합 및 노동관계조정법", 2, 1),
    ("블록 단일", "「산업안전보건법」 제38조를 검토한다.",
     1, "산업안전보건법", 38, None),
    ("블록 중대재해법", "「중대재해 처벌 등에 관한 법률」 제4조를 인용한다.",
     1, None, 4, None),
    ("중첩 중복", "「근로기준법」 제11조를 근거로 하며 근로기준법 제11조도 같다.",
     1, None, 11, None),
    ("법령 인용 없음", "원청이 직접 작업 지시를 하였다.",
     0, None, None, None),
    ("불완전 인용(조문 없음)", "「노동조합 및 노동관계조정법」에 대해 검토한다.",
     0, None, None, None),
]

for desc, text, expect_len, expect_name, expect_art, expect_para in cases:
    refs = extract_law_refs(text)
    check(len(refs) == expect_len,
          f"[{desc}] 기대 길이 {expect_len}, 실제 {len(refs)}: {[(r['law_name_raw'], r['article'], r.get('paragraph')) for r in refs]}")
    if expect_len == 1 and refs:
        r = refs[0]
        if expect_name and expect_name not in r["law_name_raw"]:
            check(False, f"[{desc}] 법령명 기대 '{expect_name}', 실제 '{r['law_name_raw']}'")
        check(r["article"] == expect_art,
              f"[{desc}] 조문 기대 {expect_art}, 실제 {r['article']}")
        if expect_para is not None:
            check(r.get("paragraph") == expect_para,
                  f"[{desc}] 항 기대 {expect_para}, 실제 {r.get('paragraph')}")
    print(f"  [{'OK' if len(refs)==expect_len else 'FAIL'}] {desc}: {len(refs)}건")

# ── (B) ⛔ 동작 ──────────────────────────────────────────────────────────────

print("\n=== (B) ⛔ 동작 (스냅샷 미보유) ===")
import service.core.verify_law_refs as vlr
vlr._load_snapshot_meta()
snap_meta = vlr._SNAPSHOT_LAW_NAMES
check(len(snap_meta) >= 4, f"스냅샷 메타데이터에 등록된 법령명 {len(snap_meta)}개 (기대 >= 4): {list(snap_meta.keys())[:8]}")

# 등록된 법령 + 조문 비어있음 → ⛔
for law, art, para, desc in [
    ("노동조합 및 노동관계조정법", 2, 1, "등록 법령 블록+항"),
    ("산업안전보건법", 38, None, "등록 법령 블록"),
    ("중대재해 처벌 등에 관한 법률", 4, None, "등록 법령 중대재해법"),
    ("근로기준법", 999, None, "등록 법령 환각 조"),
    ("존재하지 않는 가상의 법률", 1, None, "미등록 법령"),
]:
    res = lookup_article(law, art, para)
    check(res["verdict"] == "스냅샷 미보유",
          f"[{desc}] verdict 기대 '스냅샷 미보유', 실제 '{res['verdict']}' (icon={res['status_icon']})")
    print(f"  [{'OK' if res['verdict']=='스냅샷 미보유' else 'FAIL'}] {desc}: {res['status_icon']} {res['verdict']}")

# verify_all_law_refs 전체가 ⛔
synthetic = (
    "「노동조합 및 노동관계조정법」 제2조 제1항에 따라…\n"
    "「산업안전보건법」 제38조에 따라…\n"
    "「중대재해 처벌 등에 관한 법률」 제4조를 인용…\n"
    "「근로기준법」 제999조를 근거로…\n"
)
res_list = verify_all_law_refs(synthetic)
check(len(res_list) >= 4, f"합성 문서에서 최소 4개 추출 (실제 {len(res_list)})")
for r in res_list:
    check(r["verdict"] == "스냅샷 미보유",
          f"합성 문서 인용 '{r['law_name_raw']}' 제{r['article']}조 → verdict '{r['verdict']}' (기대 '스냅샷 미보유')")
print(f"  [{'OK' if all(r['verdict']=='스냅샷 미보유' for r in res_list) else 'FAIL'}] 합성 문서 전건 ⛔: {len(res_list)}건")

# ── (C) 적법도급 체크리스트 3분기 ────────────────────────────────────────────

print("\n=== (C) 적법도급 체크리스트 3분기 판정 ===")

def run_check(text):
    return check_subcontract(text)["results"]

# 위험 신호
res = run_check("원청 직원이 수급인 근로자에게 직접 작업 지시를 하였다.")
item = next(r for r in res if r["item"]==1 and r["axis"]==1)
check(item["label"] == "근거 있음-위험 신호",
      f"원청 직접 지시 → 기대 '위험 신호', 실제 '{item['label']}'")
check(item["evidence_sentences"], "위험 신호 항목에 근거 문장 있어야 함")
print(f"  [{'OK' if item['label']=='근거 있음-위험 신호' else 'FAIL'}] 원청 직접 지시 → 위험 신호")

# 적법 방향 (자체 장비)
res = run_check("당사는 자체 장비를 보유하고 작업한다.")
item = next(r for r in res if r["item"]==1 and r["axis"]==5)
check(item["label"] == "근거 있음-적법 방향",
      f"자체 장비 → 기대 '적법 방향', 실제 '{item['label']}'")
print(f"  [{'OK' if item['label']=='근거 있음-적법 방향' else 'FAIL'}] 자체 장비 → 적법 방향")

# 적법 방향 (별도 법인)
res = run_check("별도 법인격을 가진 전문 업체이다.")
item = next(r for r in res if r["item"]==2 and r["axis"]==5)
check(item["label"] == "근거 있음-적법 방향",
      f"별도 법인 → 기대 '적법 방향', 실제 '{item['label']}'")
print(f"  [{'OK' if item['label']=='근거 있음-적법 방향' else 'FAIL'}] 별도 법인 → 적법 방향")

# 적법 방향 (계약 목적 확정)
res = run_check("계약 목적은 '물류센터 피킹 서비스 결과물 납품'으로 확정되어 있다.")
item = next(r for r in res if r["item"]==1 and r["axis"]==4)
check(item["label"] == "근거 있음-적법 방향",
      f"계약 목적 확정 → 기대 '적법 방향', 실제 '{item['label']}'")
print(f"  [{'OK' if item['label']=='근거 있음-적법 방향' else 'FAIL'}] 계약 목적 확정 → 적법 방향")

# 근거 없음 (부정 문장이 근거 후보에서 제외되는지)
res = run_check("일반적 현황만 적혀 있고 근태 관련 내용은 없다.")
item = next(r for r in res if r["item"]==3 and r["axis"]==1)
check(item["label"] == "근거 없음-확인 필요",
      f"부정 문장('근태 관련 내용은 없다') → 기대 '근거 없음', 실제 '{item['label']}' (근거 문장 수={len(item['evidence_sentences'])})")
print(f"  [{'OK' if item['label']=='근거 없음-확인 필요' else 'FAIL'}] 부정 문장 → 근거 없음 (근거 문장 {len(item['evidence_sentences'])}개)")

# 근거 없는 문장들 → 모두 확인 필요
res = run_check("아무 근거가 없는 문장들이다.")
check(all(r["label"] == "근거 없음-확인 필요" for r in res),
      f"근거 없는 문서 → 전 항목 '근거 없음' (실제: {set(r['label'] for r in res)})")
print(f"  [{'OK' if all(r['label']=='근거 없음-확인 필요' for r in res) else 'FAIL'}] 근거 없는 문서 → 전 항목 확인 필요")

# 합성 시연 문서 5상황
demo = (
    "【가온물류센터 현장점검 보고서(가상)】\n"
    "1. 근거 법령\n"
    "  1-1. 「노동조합 및 노동관계조정법」 제2조 제1호…\n"
    "  1-2. 「산업안전보건법」 제38조…\n"
    "  1-3. 「중대재해 처벌 등에 관한 법률」 제4조…\n"
    "  1-4. 「근로기준법」 제999조(환각)…\n"
    "  1-5. 「노동조합 및 노동관계조정법」 제2조 근거 '원청 직접 지시 적법' 주장…\n"
    "2. 적법도급 자가진단\n"
    "  2-1. 원청 직원이 직접 작업 지시를 하였다.\n"
    "  2-2. 당사는 별도 법인 전문 업체로 자체 장비 보유.\n"
    "  2-3. 계약 목적 '물류센터 피킹 결과물 납품' 확정.\n"
    "  2-4. 원청 근태 통제 없었음(근거 없음).\n"
)
print("\n  --- 합성 시연 문서 5상황 ---")
law_refs = verify_all_law_refs(demo)
check(len(law_refs) >= 4, f"법령 인용 표지 최소 4건 추출 (실제 {len(law_refs)})")
print(f"    법령 인용 표지: {len(law_refs)}건 추출")
for r in law_refs:
    print(f"      {r['status_icon']} {r['law_name_raw']} 제{r['article']}조 → {r['verdict']}")
check(all(r["verdict"] == "스냅샷 미보유" for r in law_refs),
      "전건 ⛔ 확인 필요")

checklist = run_check(demo)
risk = [r for r in checklist if r["label"] == "근거 있음-위험 신호"]
noneed = [r for r in checklist if r["label"] == "근거 없음-확인 필요"]
print(f"    위험 신호 항목: {len(risk)}개 {[(r['axis'], r['item'], r['name']) for r in risk]}")
print(f"    근거 없음 항목: {len(noneed)}개 {[(r['axis'], r['item'], r['name']) for r in noneed]}")
check(len(risk) >= 1, "위험 신호 항목 최소 1개 (지휘·명령)")
check(len(noneed) >= 1, "근거 없음 항목 최소 1개 (근거 없는 적법 주장)")
risk_names = {r["name"] for r in risk}
check("작업 지시·명령의 원청 직접성" in risk_names,
      f"위험 신호 항목에 '작업 지시·명령의 원청 직접성' 포함돼야 함 (실제: {risk_names})")

# ── 결과 ─────────────────────────────────────────────────────────────────────

print("\n" + "="*60)
if errors:
    print(f"❌ 검증 실패: {len(errors)}건")
    for e in errors:
        print(f"   - {e}")
    sys.exit(1)
else:
    print("✅ 모든 검증 통과 (ad-hoc 집중 검증)")
    sys.exit(0)
