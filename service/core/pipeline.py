#!/usr/bin/env python3
"""
pipeline.py — 파싱→절분리→검증(M1)→표지·주장(⑥)→연결(⑦)→대조(⑧)→문서 게이트(PRD §5) 통합 실행.

입력: PDF/이미지/DOCX 파일 경로.
출력: 통합 결과 JSON.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 프로젝트 루트
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── 모듈 import ───────────────────────────────────────────────────────────────

from service.core.extract_refs import (
    extract_references_from_elements,
    load_docparse_json,
    extract_references_from_file,
    get_element_text,
    get_element_category,
    get_page as get_el_page,
    make_sort_key,
    is_heading_element,
    is_excluded_category,
    classify_element,
    split_by_number_mark,
    merge_lines_in_element,
    is_author_year_bib,
)
from service.core.extract_claims import (
    extract_claims_from_elements,
    get_text,
    get_page,
)
from service.core.link_check import check_links
from service.core.match_claims import (
    match_claims_batch,
    VERDICT_SUPPORTED,
    VERDICT_NOT_SUPPORTED,
    VERDICT_CANNOT_JUDGE,
)

# verify_refs는 수동 import (CLI 도구이므로)
from service.core import verify_refs
from service.core.parse_refs import parse_item

# ── 새 섹션 임포트 (M7d) ──────────────────────────────────────────────────────
from service.core.verify_law_refs import (
    extract_law_refs,
    lookup_article,
    verify_law_ref,
    verify_all_law_refs,
)
from service.core.subcontract_check import (
    check_subcontract,
    LABEL_FOUND_COMPLIANT,
    LABEL_FOUND_RISK,
    LABEL_NONEED,
)
from service.core.photo_claims import extract_photo_claims
from service.core.photo_detect import detect_objects
from service.core.photo_match import match_photo_claim


# ── 상수 ──────────────────────────────────────────────────────────────────────

# 문서 게이트 임계 (PRD §5)
GATE_UNVERIFIED_THRESHOLD = 0  # ❌ 0건
GATE_MISQUOTED_THRESHOLD = 0  # 🔴 0건
GATE_CANNOT_JUDGE_THRESHOLD = 3  # 판단 불가 > 임계 → 확인 필요

GATE_SUBMITTABLE = "제출 가능"
GATE_NEEDS_REVISION = "보완 필요"
GATE_NEEDS_CHECK = "확인 필요"

# 사진 판정 임계 (M7d)
PHOTO_UNMATCHED_THRESHOLD = 0   # 미매칭 1건 이상이면 확인 필요
PHOTO_NOT_SUPPORTED_THRESHOLD = 0  # 뒷받침 안 함 1건 이상이면 보완 필요
PHOTO_CANNOT_JUDGE_THRESHOLD = 3   # 판단 불가 > 임계 → 확인 필요
PHOTO_CRITICAL_THRESHOLD = 0        # 검출·대조 실패(⛔급) 1건 이상 → 확인 필요

# 본문 category 접두어
BODY_CATEGORY_PREFIXES = ['body', 'text', 'paragraph']


# ── 파이프라인 ────────────────────────────────────────────────────────────────

def run_pipeline(
    file_path: Optional[str] = None,
    api_key_env: str = "UPSTAGE_API_KEY",
    offline: bool = False,
    max_verify: int = 60,
    match_parallel: int = 4,
    match_use_cache: bool = True,
    photo_files: Optional[List[str]] = None,
    raw_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    전체 파이프라인 실행.

    ① Document Parse → elements (캐시 우선)  [raw_text 제공 시 건너뛰고 raw_text를 본문으로 사용]
    ② 절 분리 (E10): 본문 elements / 참고문헌 elements
    ③ 참고문헌 검증 (verify_refs.py): 실존 5단계
    ④ 인용 표지 추출 (extract_claims.py): 본문 주장 + 표지
    ⑤ 연결 검사 (link_check.py): 미인용 / 목록 누락
    ⑥ 주장-근거 대조 (match_claims.py): 3분기 + quote
    ⑦ 문서 게이트 (PRD §5): 제출가능/보완필요/확인필요
    ⑧ 통합 결과 JSON 반환

    M7d 게이트 통합 섹션:
      (a) 법령 — 본문에서 표지 추출+스냅샷 조회 → law_section
      (b) 적법도급 — 체크리스트 판정 → subcontract_section
      (c) 사진 — photo_files 있으면 문장·사진 매칭 후 도메인 라우팅 검출·대조 → photo_section
      (d) 게이트 종합 — 법령 ❌ 또는 사진 '뒷받침 안 함' 또는 체크리스트 위험 신호 시 '보완 필요' 이상,
          사진 미매칭·⛔ 과다 시 '확인 필요'. 결과 JSON에 law_section, subcontract_section,
          photo_section, gate 키 추가.
    """
    t0 = time.time()
    timeline: List[Dict[str, Any]] = []

    def log(step: str, msg: str):
        elapsed = time.time() - t0
        timeline.append({"step": step, "elapsed_sec": round(elapsed, 2), "msg": msg})

    result: Dict[str, Any] = {
        "meta": {
            "file": file_path or "(raw_text)",
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "steps": [],
        },
        "elements": None,
        "body_elements": None,
        "ref_elements": None,
        "refs_verified": None,
        "claims": None,
        "link_check": None,
        "match_results": None,
        "gate": None,
        "elapsed_sec": 0,
    }

    # ── ① Document Parse / 본문 확보 ──────────────────────────────────────────
    log("parse", "Document Parse 시작" if raw_text is None else "raw_text 경로 — Document Parse 건너뛰기")

    if raw_text is not None:
        # raw_text 경로: Document Parse 건너뛰고 본문을 raw_text로 사용
        if not isinstance(raw_text, str) or not raw_text.strip():
            log("parse", "raw_text가 비어 있음")
            result["gate"] = {
                "status": GATE_NEEDS_CHECK,
                "reason": "raw_text가 비어 있음",
            }
            result["elapsed_sec"] = round(time.time() - t0, 2)
            result["meta"]["steps"] = timeline
            return result
        body_text = raw_text
        # 합성 elements (절 분리·claim 추출이 downstream에서 요소를 요구하므로 최소 요소 구성)
        elements = []
        for i, line in enumerate(raw_text.split("\n"), 1):
            line = line.strip()
            if not line:
                continue
            elements.append({
                "text": line,
                "page": 1,
                "category": "body",
                "boundingBox": {"x": 0.1, "y": 0.1 * i, "width": 0.8, "height": 0.05},
            })
        log("parse", f"raw_text 본문 사용 (요소 {len(elements)}개 합성)")
    else:
        # 기존 Document Parse 경로
        if file_path is None:
            log("parse", "file_path 없음")
            result["gate"] = {
                "status": GATE_NEEDS_CHECK,
                "reason": "file_path 없음",
            }
            result["elapsed_sec"] = round(time.time() - t0, 2)
            result["meta"]["steps"] = timeline
            return result

        from service.core.docparse_client import _cache_key as dp_cache_key, _load_cache
        cache_key = dp_cache_key(file_path)
        cached = _load_cache(cache_key)

        if cached is not None:
            elements = cached.get('elements', [])
            log("parse", f"캐시 재사용 (요소 {len(elements)}개)")
        else:
            if offline:
                log("parse", "오프라인 모드 — Document Parse 건너뜀")
                result["gate"] = {
                    "status": GATE_NEEDS_CHECK,
                    "reason": "오프라인 모드 — 문서 판독 불가",
                }
                result["elapsed_sec"] = round(time.time() - t0, 2)
                result["meta"]["steps"] = timeline
                return result

            from service.core.docparse_client import call_document_parse
            try:
                dp_response = call_document_parse(file_path)
                elements = dp_response.get('elements', [])
                log("parse", f"Document Parse 완료 (요소 {len(elements)}개)")
            except Exception as e:
                log("parse", f"Document Parse 실패: {e}")
                result["gate"] = {
                    "status": GATE_NEEDS_CHECK,
                    "reason": f"문서 판독 실패: {e}",
                }
                result["elapsed_sec"] = round(time.time() - t0, 2)
                result["meta"]["steps"] = timeline
                return result

    if not elements:
        log("parse", "요소 없음")
        result["gate"] = {
            "status": GATE_NEEDS_CHECK,
            "reason": "Document Parse 결과 요소 없음",
        }
        result["elapsed_sec"] = round(time.time() - t0, 2)
        result["meta"]["steps"] = timeline
        return result

    result["elements"] = elements

    # ── ② 절 분리 (E10) ────────────────────────────────────────────────────
    log("separate", "절 분리 시작 (E10)")

    # 요소 정렬
    sorted_elements = sorted(elements, key=make_sort_key)

    body_elements: List[Dict[str, Any]] = []
    ref_elements: List[Dict[str, Any]] = []

    # raw_text 경로: 합성 요소는 헤딩 없이 바로 본문으로 분류 (E10 헤딩 전제 건너뜀)
    if raw_text is not None:
        for el in sorted_elements:
            text = get_element_text(el)
            if not text or not text.strip():
                continue
            cat = get_element_category(el)
            if is_excluded_category(el):
                continue
            etype = classify_element(text, cat)
            if etype in ('number_bib', 'author_year_bib'):
                ref_elements.append(el)
            else:
                body_elements.append(el)
        log("separate", f"raw_text 경로: 본문 element {len(body_elements)}개, 참고문헌 element {len(ref_elements)}개")
    else:
        # 기존 E10 경로: 헤딩 발견 전 요소 버림
        heading_found = False
        prev_accepted: Optional[Dict[str, Any]] = None
        prev_page: int = 0

        for el in sorted_elements:
            text = get_element_text(el)
            if not text or not text.strip():
                continue

            # 헤딩 찾기 전은 모두 버림
            if not heading_found:
                if is_heading_element(el):
                    heading_found = True
                continue

            # category 제외
            if is_excluded_category(el):
                continue

            page = get_el_page(el)
            cat = get_element_category(el)
            etype = classify_element(text, cat)

            if etype in ('number_bib', 'author_year_bib'):
                # 참고문헌 element
                ref_elements.append(el)
                prev_accepted = {'page': page}
                prev_page = page
            elif etype in ('body', 'other'):
                # 본문 element — E11b 예외 처리 후 본문으로 분류
                # (E11b: 직전 ref가 p에 있고 현재가 p+1 첫 본문성 element이며 표지 없음 → 병합)
                if (prev_accepted is not None
                        and page == prev_page + 1
                        and etype in ('body', 'other')
                        and not re.match(r'^\s*(\[\d+\]|\d+\.|\d+\))\s+', text)
                        and not is_author_year_bib(text)):
                    # 직전 ref에 병합
                    if prev_accepted.get('merged_to'):
                        prev_accepted['merged_to'] = prev_accepted['merged_to'] + ' ' + text
                    else:
                        prev_accepted['merged_to'] = text
                    prev_accepted['source_note'] = 'merged'
                    continue
                # 본문으로 분류
                body_elements.append(el)
            else:
                body_elements.append(el)

        log("separate", f"본문 element {len(body_elements)}개, 참고문헌 element {len(ref_elements)}개")

    result["body_elements"] = body_elements
    result["ref_elements"] = ref_elements

    # ── 본문 텍스트 조합 (M7d 섹션 공용) ─────────────────────────────────────
    body_texts = []
    for el in body_elements:
        text = get_text(el)
        if text:
            body_texts.append(text)
    body_text = '\n'.join(body_texts)

    # ── (a) 법령 섹션 ────────────────────────────────────────────────────────
    log("law", "법령 인용 표지 추출 시작")
    law_refs = extract_law_refs(body_text)
    law_verified_list = [verify_law_ref(r) for r in law_refs]
    law_section = {
        "extracted": len(law_refs),
        "items": law_verified_list,
        "counts": {
            "실존": sum(1 for v in law_verified_list if v.get("verdict") == "실존"),
            "해당조없음": sum(1 for v in law_verified_list if v.get("verdict") == "해당 조 없음"),
            "스냅샷미보유": sum(1 for v in law_verified_list if v.get("verdict") == "스냅샷 미보유"),
            "내용변동가능": sum(1 for v in law_verified_list if v.get("verdict") == "내용 변동 가능"),
        },
    }
    log("law", f"법령 표지 {len(law_refs)}건 추출 → 실존 {law_section['counts']['실존']}, "
                f"❌해당조없음 {law_section['counts']['해당조없음']}, ⛔스냅샷미보유 {law_section['counts']['스냅샷미보유']}")
    result["law_section"] = law_section

    # ── (b) 적법도급 섹션 ────────────────────────────────────────────────────
    log("subcontract", "적법도급 체크리스트 판정 시작")
    subcontract_result = check_subcontract(body_text)
    risk_count = subcontract_result.get("axis_summary", {}).get(1, {}).get("risk_count", 0)
    # 전체 축 합산 위험 신호
    total_risk = sum(s.get("risk_count", 0) for s in subcontract_result.get("axis_summary", {}).values())
    log("subcontract", f"적법도급 판정 완료: 총 {subcontract_result['total_items']}항목, 위험신호 {total_risk}건")
    result["subcontract_section"] = subcontract_result
    log("verify", "참고문헌 검증 시작 (M1)")

    # parse_refs로 항목 구조화
    refs_parsed = []
    for i, ref_el in enumerate(ref_elements, 1):
        text = get_element_text(ref_el)
        merged = merge_lines_in_element(text)
        if not merged.strip():
            continue
        item = parse_item(merged, i)
        if item:
            item['page'] = get_el_page(ref_el)
            item['source_note'] = ref_el.get('source_note', 'unknown')
            refs_parsed.append(item)

    log("verify", f"참고문헌 {len(refs_parsed)}건 파싱 완료")

    # 검증
    refs_verified = []
    for item in refs_parsed:
        v = verify_refs.verify_item(item, offline=offline)
        refs_verified.append(v)
        log("verify", f"  [{v['id']}] {v['status']}: {v.get('note', '')[:60]}")

    result["refs_verified"] = refs_verified

    # 집계
    counts: Dict[str, int] = {
        'verified': 0, 'partial': 0, 'unverified': 0,
        'unreachable': 0, 'not_applicable': 0,
    }
    for r in refs_verified:
        s = r.get('status', 'unverified')
        if s in counts:
            counts[s] += 1

    # ── ④ 인용 표지 추출 (extract_claims.py) ──────────────────────────────
    log("extract_claims", "본문 주장 추출 시작 (⑥)")

    claims = extract_claims_from_elements(body_elements, BODY_CATEGORY_PREFIXES)
    log("extract_claims", f"주장 {len(claims)}건 추출")
    result["claims"] = claims

    # ── ⑤ 연결 검사 (link_check.py) ────────────────────────────────────────
    log("link_check", "연결 검사 시작 (⑦)")

    # 본문 텍스트 조합
    body_texts = []
    for el in body_elements:
        text = get_text(el)
        if text:
            body_texts.append(text)
    body_text = '\n'.join(body_texts)

    # refs_parsed를 link_check용 ref_items로 변환
    ref_items = [{'id': r['id'], 'text': r['raw']} for r in refs_parsed]

    link_result = check_links(body_text, ref_items)
    log("link_check", (
        f"미인용 {link_result['summary']['uncited_count']}건, "
        f"목록 누락 {link_result['summary']['missing_count']}건"
    ))
    result["link_check"] = link_result

    # ── ⑥ 주장-근거 대조 (match_claims.py) ────────────────────────────────
    log("match", "주장-근거 대조 시작 (⑧)")

    # 각 주장에 대해 대응되는 문헌 메타데이터 찾기
    # refs_verified에서 matched된 메타데이터 사용
    ref_meta_map: Dict[int, Dict[str, str]] = {}
    for rv in refs_verified:
        if rv.get('matched'):
            ref_meta_map[rv['id']] = {
                'title': rv['matched'].get('title', '') or '',
                'abstract': rv['matched'].get('abstract', '') or '',
            }

    match_items = []
    for claim in claims:
        marker_type = claim.get('marker_type', '')
        marker_value = claim.get('marker_value', '')

        # 대응되는 ref 찾기
        matched_ref_id = None
        if marker_type == 'number':
            # 번호 표지로 매칭: refs_parsed에서 해당 번호 찾기
            for ref in ref_items:
                ref_text = ref.get('text', '')
                if f"[{marker_value}]" in ref_text or f"{marker_value}." in ref_text[:20]:
                    matched_ref_id = ref.get('id')
                    break
        elif marker_type == 'author_year':
            # 저자-연도로 매칭
            for ref in ref_items:
                ref_text = ref.get('text', '')
                if marker_value in ref_text:
                    matched_ref_id = ref.get('id')
                    break

        # 메타데이터
        meta_title = ''
        meta_abstract = ''
        if matched_ref_id and matched_ref_id in ref_meta_map:
            meta_title = ref_meta_map[matched_ref_id]['title']
            meta_abstract = ref_meta_map[matched_ref_id]['abstract']

        match_items.append({
            'claim': claim['claim'],
            'marker_type': marker_type,
            'marker_value': marker_value,
            'ref_id': matched_ref_id,
            'metadata_title': meta_title,
            'metadata_abstract': meta_abstract,
        })

    # 대조 실행
    match_results = match_claims_batch(
        match_items,
        use_cache=match_use_cache,
        max_parallel=match_parallel,
    )

    # 집계
    match_counts: Dict[str, int] = {
        VERDICT_SUPPORTED: 0,
        VERDICT_NOT_SUPPORTED: 0,
        VERDICT_CANNOT_JUDGE: 0,
    }
    for mr in match_results:
        v = mr.get('verdict', VERDICT_CANNOT_JUDGE)
        if v in match_counts:
            match_counts[v] += 1

    log("match", (
        f"대조 완료: 뒷받침함 {match_counts[VERDICT_SUPPORTED]}, "
        f"뒷받침 안 함 {match_counts[VERDICT_NOT_SUPPORTED]}, "
        f"판단 불가 {match_counts[VERDICT_CANNOT_JUDGE]}"
    ))
    result["match_results"] = match_results

    # ── (c) 사진 섹션 ────────────────────────────────────────────────────────
    photo_section: Dict[str, Any] = {
        "photo_files": photo_files if photo_files else [],
        "claims": [],
        "matches": [],
        "counts": {
            "총주장": 0,
            "매칭성공": 0,
            "매칭실패": 0,
            "뒷받침함": 0,
            "뒷받침안함": 0,
            "판단불가": 0,
            "도메인": {},
        },
    }
    if photo_files:
        log("photo", f"사진 섹션 시작 (파일 {len(photo_files)}개)")
        # 사진 참조 주장 추출
        photo_claims_list = extract_photo_claims(body_text, photo_files)
        photo_section["claims"] = photo_claims_list
        photo_section["counts"]["총주장"] = len(photo_claims_list)

        unmatched_photo_count = 0
        domain_counts: Dict[str, int] = {}

        for pc in photo_claims_list:
            pf = pc.get("photo_file")
            sentence = pc.get("sentence", "")
            # 매칭 실패 카운트
            if not pf:
                unmatched_photo_count += 1
                photo_section["counts"]["매칭실패"] += 1
                log("photo", f"  사진 참조 주장 매칭 실패: {pc.get('marker')} — {sentence[:80]}")
                continue

            # 도메인 라우팅
            lowered = sentence.lower()
            if any(k in lowered for k in ("부식", "부식", "균열", "손상", "용접", "crack", "damage", "corrosion", "weld")):
                domain = "defect"
            elif any(k in lowered for k in ("계기", "수치", "gauge", "digit", "압력", "온도", "rpm", "속도", "값", "측정", "게이지")):
                domain = "gauge"
            elif any(k in lowered for k in ("정리", "적재", "폐기물", "청소", "폐기", "방치", "폐기물", "쓰레기", "cleaning", "cardboard", "pile", "쓰레기")):
                domain = "cleaning"
            else:
                domain = "defect"  # 불명 → defect

            photo_section["counts"]["도메인"][domain] = photo_section["counts"]["도메인"].get(domain, 0) + 1

            try:
                detections = detect_objects(pf, domain)
            except Exception as e:
                log("photo", f"  검출 실패 ({domain}/{pf}): {e}")
                photo_section["matches"].append({
                    "sentence": sentence,
                    "marker": pc.get("marker"),
                    "photo_file": pf,
                    "verdict": "판단 불가",
                    "reason": f"객체 검출 실패: {e}",
                    "quote": "",
                })
                photo_section["counts"]["판단불가"] += 1
                continue

            try:
                match_res = match_photo_claim(sentence, detections, use_cache=match_use_cache)
            except Exception as e:
                log("photo", f"  대조 실패 ({domain}/{pf}): {e}")
                photo_section["matches"].append({
                    "sentence": sentence,
                    "marker": pc.get("marker"),
                    "photo_file": pf,
                    "verdict": "판단 불가",
                    "reason": f"대조 실패: {e}",
                    "quote": "",
                })
                photo_section["counts"]["판단불가"] += 1
                continue

            photo_section["matches"].append({
                "sentence": sentence,
                "marker": pc.get("marker"),
                "photo_file": pf,
                "domain": domain,
                "verdict": match_res.get("verdict", "판단 불가"),
                "quote": match_res.get("quote", ""),
                "reason": match_res.get("reason", ""),
                "detection_count": match_res.get("detection_count", 0),
            })

            v = match_res.get("verdict", "판단 불가")
            if v == "뒷받침함":
                photo_section["counts"]["뒷받침함"] += 1
            elif v == "뒷받침 안 함":
                photo_section["counts"]["뒷받침안함"] += 1
            else:
                photo_section["counts"]["판단불가"] += 1

        photo_section["counts"]["매칭성공"] = photo_section["counts"]["총주장"] - unmatched_photo_count
        log("photo", (
            f"사진 섹션 완료: 주장 {photo_section['counts']['총주장']}건, "
            f"매칭성공 {photo_section['counts']['매칭성공']}건, 매칭실패 {photo_section['counts']['매칭실패']}건, "
            f"뒷받침함 {photo_section['counts']['뒷받침함']}, 뒷받침안함 {photo_section['counts']['뒷받침안함']}, "
            f"판단불가 {photo_section['counts']['판단불가']}"
        ))
    else:
        log("photo", "사진 파일 없음 — 사진 섹션 건너뜀")
    result["photo_section"] = photo_section

    # ── (d) 게이트 종합 ─────────────────────────────────────────────────────
    log("gate", "문서 게이트 계산 (PRD §5)")

    # photo 섹션 집계 (M7d)
    photo_counts = photo_section.get("counts", {})
    photo_total = photo_counts.get("총주장", 0)
    photo_matched = photo_counts.get("매칭성공", 0)
    photo_unmatched = photo_counts.get("매칭실패", 0)
    photo_supported = photo_counts.get("뒷받침함", 0)
    photo_not_supported = photo_counts.get("뒷받침안함", 0)
    photo_cannot_judge = photo_counts.get("판단불가", 0)
    photo_domain_counts = photo_counts.get("도메인", {})

    # critical(⛔급): 검출 실패 + 대조 실패 건수 (matches 내 reason으로 판별)
    photo_critical = sum(
        1 for m in photo_section.get("matches", [])
        if m.get("reason", "").startswith("객체 검출 실패") or m.get("reason", "").startswith("대조 실패")
    )

    # 오인용(🔴) 집계: 실존 문헌에 대해 뒷받침 안 함으로 판정된 항목
    # refs_verified에서 verified/partial인 항목 ID 집합
    real_ref_ids = set()
    for rv in refs_verified:
        if rv.get('status') in ('verified', 'partial'):
            real_ref_ids.add(rv['id'])

    misquoted_count = sum(
        1 for mr in match_results
        if mr.get('verdict') == VERDICT_NOT_SUPPORTED
        and mr.get('ref_id') in real_ref_ids
    )

    # 판단 불가 개수
    cannot_judge_count = match_counts.get(VERDICT_CANNOT_JUDGE, 0)

    # 법령 ❌ (해당 조 없음) —게이트에 반영
    law_fail_count = law_section.get("counts", {}).get("해당조없음", 0)

    # 사진 '뒷받침 안 함' → 보완 필요 이상
    photo_not_supported = photo_section.get("counts", {}).get("뒷받침안함", 0)

    # 사진 미매칭 + ⛔(스냅샷미보유 등) 과다 → 확인 필요
    photo_unmatched = photo_section.get("counts", {}).get("매칭실패", 0)
    law_snapshot_missing = law_section.get("counts", {}).get("스냅샷미보유", 0)

    # 적법도급 위험 신호
    subcontract_risk = total_risk

    # 게이트 판정 (우선순위: 보완 필요 > 확인 필요 > 제출 가능)
    gate_status = GATE_SUBMITTABLE
    gate_reason = "모든 인용 실존 확인, 대조 완료"

    # 보완 필요 tier
    if law_fail_count > 0:
        gate_status = GATE_NEEDS_REVISION
        gate_reason = f"❌ 법령 인용 표지 중 '해당 조 없음' {law_fail_count}건 — 보완 필요"
    elif photo_not_supported > 0:
        gate_status = GATE_NEEDS_REVISION
        gate_reason = f"🔴 사진 대조 '뒷받침 안 함' {photo_not_supported}건 — 보완 필요"
    elif subcontract_risk > 0:
        gate_status = GATE_NEEDS_REVISION
        gate_reason = f"⚠️ 적법도급 체크리스트 위험 신호 {subcontract_risk}건 — 보완 필요"
    elif counts.get('unverified', 0) > GATE_UNVERIFIED_THRESHOLD:
        gate_status = GATE_NEEDS_REVISION
        gate_reason = f"❌ 미확인 {counts['unverified']}건 존재"
    elif misquoted_count > GATE_MISQUOTED_THRESHOLD:
        gate_status = GATE_NEEDS_REVISION
        gate_reason = f"🔴 오인용 {misquoted_count}건 존재"
    # 확인 필요 tier
    elif photo_critical > PHOTO_CRITICAL_THRESHOLD:
        gate_status = GATE_NEEDS_CHECK
        gate_reason = f"⛔ 사진 검출·대조 실패 {photo_critical}건 — 확인 필요"
    elif photo_unmatched > PHOTO_UNMATCHED_THRESHOLD:
        gate_status = GATE_NEEDS_CHECK
        gate_reason = f"사진 참조 미매칭 {photo_unmatched}건 — 촬영·구분 누락 의심, 확인 필요"
    elif photo_cannot_judge > PHOTO_CANNOT_JUDGE_THRESHOLD:
        gate_status = GATE_NEEDS_CHECK
        gate_reason = (
            f"사진 판단 불가 {photo_cannot_judge}건 "
            f"(임계 {PHOTO_CANNOT_JUDGE_THRESHOLD} 초과) — 확인 필요"
        )
    elif law_snapshot_missing > 0:
        gate_status = GATE_NEEDS_CHECK
        gate_reason = f"⛔ 법령 스냅샷 미보유 {law_snapshot_missing}건 — 확인 필요"
    elif cannot_judge_count > GATE_CANNOT_JUDGE_THRESHOLD:
        gate_status = GATE_NEEDS_CHECK
        gate_reason = (
            f"판단 불가 {cannot_judge_count}건 (임계 {GATE_CANNOT_JUDGE_THRESHOLD} 초과) "
            f"— 확인 필요"
        )
    else:
        gate_status = GATE_SUBMITTABLE
        gate_reason = "모든 인용 실존 확인, 대조 완료"

    gate = {
        "status": gate_status,
        "reason": gate_reason,
        "counts": {
            "실존": counts,
            "대조": match_counts,
            "미인용": link_result['summary']['uncited_count'],
            "목록누락": link_result['summary']['missing_count'],
            "오인용": misquoted_count,
            "판단불가": cannot_judge_count,
            "법령": law_section.get("counts", {}),
            "적법도급": {
                "총항목": subcontract_result.get("total_items", 0),
                "위험신호": total_risk,
            },
            "사진": photo_section.get("counts", {}),
        },
    }

    log("gate", f"문서 게이트: {gate_status} — {gate_reason}")
    result["gate"] = gate

    # ── 마무리 ──────────────────────────────────────────────────────────────
    result["elapsed_sec"] = round(time.time() - t0, 2)
    result["meta"]["steps"] = timeline

    return result


# ── 출력 ──────────────────────────────────────────────────────────────────────

def print_summary(result: Dict[str, Any]):
    """파이프라인 결과를 사람이 읽기 쉽게 출력."""
    gate = result.get("gate", {})
    status = gate.get("status", "?")

    print("\n" + "=" * 60)
    print(f"문서 게이트: {status}")
    print(f"  사유: {gate.get('reason', '')}")
    print("=" * 60)

    print("\n■ 실존 검증 집계:")
    for sym, cnt in {
        '✅ 확인': sum(1 for r in result["refs_verified"] if r.get('status') == 'verified'),
        '⚠️ 부분일치': sum(1 for r in result["refs_verified"] if r.get('status') == 'partial'),
        '❌ 미확인': sum(1 for r in result["refs_verified"] if r.get('status') == 'unverified'),
        '⛔ 확인불가': sum(1 for r in result["refs_verified"] if r.get('status') == 'unreachable'),
        '➖ 비대상': sum(1 for r in result["refs_verified"] if r.get('status') == 'not_applicable'),
    }.items():
        print(f"  {sym}: {cnt}건")

    print("\n■ 연결 검사:")
    lc = result.get("link_check", {})
    print(f"  미인용: {lc.get('summary', {}).get('uncited_count', 0)}건")
    print(f"  목록 누락: {lc.get('summary', {}).get('missing_count', 0)}건")

    print("\n■ 주장-근거 대조:")
    for sym, cnt in {
        '뒷받침함': sum(1 for r in result["match_results"] if r.get('verdict') == '뒷받침함'),
        '뒷받침 안 함': sum(1 for r in result["match_results"] if r.get('verdict') == '뒷받침 안 함'),
        '판단 불가': sum(1 for r in result["match_results"] if r.get('verdict') == '판단 불가'),
    }.items():
        print(f"  {sym}: {cnt}건")

    # 🔴 오인용 상세
    misquoted = []
    real_ids = set()
    for rv in result.get("refs_verified", []):
        if rv.get('status') in ('verified', 'partial'):
            real_ids.add(rv['id'])

    for mr in result.get("match_results", []):
        if mr.get('verdict') == '뒷받침 안 함' and mr.get('ref_id') in real_ids:
            misquoted.append(mr)

    if misquoted:
        print("\n🔴 오인용 검출:")
        for i, mq in enumerate(misquoted, 1):
            print(f"  [{i}] 주장: {mq.get('claim', '')[:120]}...")
            print(f"      quote: {mq.get('quote', '')[:120]}...")
            print(f"      근거: {mq.get('reason', '')[:120]}...")

    # 무인용 거절 태그
    no_quote_reject = []
    for mr in result.get("match_results", []):
        if '무인용 거절' in mr.get('tags', []):
            no_quote_reject.append(mr)

    if no_quote_reject:
        print("\n■ 무인용 거절 태그:")
        for i, nqr in enumerate(no_quote_reject, 1):
            print(f"  [{i}] 주장: {nqr.get('claim', '')[:120]}...")
            print(f"      판정: {nqr.get('verdict')}")
            print(f"      근거: {nqr.get('reason', '')[:120]}...")

    # ── (a) 법령 섹션 ────────────────────────────────────────────────────────
    ls = result.get("law_section", {})
    if ls:
        print("\n■ 법령 인용 표지:")
        print(f"  추출: {ls.get('extracted', 0)}건")
        lc = ls.get("counts", {})
        for sym, cnt in [
            ("✅ 실존", lc.get("실존", 0)),
            ("❌ 해당 조 없음", lc.get("해당조없음", 0)),
            ("⛔ 스냅샷 미보유", lc.get("스냅샷미보유", 0)),
            ("⚠️ 내용 변동 가능", lc.get("내용변동가능", 0)),
        ]:
            if cnt:
                print(f"  {sym}: {cnt}건")
        for item in ls.get("items", []):
            icon = item.get("status_icon", "?")
            art = item.get("article")
            para = item.get("paragraph")
            art_str = f"제{art}조"
            if para:
                art_str += f" 제{para}항"
            print(f"    {icon} {item.get('law_name_raw','')} {art_str} — {item.get('verdict','?')}")
            note = item.get("note", "")
            if note:
                print(f"       └ {note[:100]}")

    # ── (b) 적법도급 섹션 ────────────────────────────────────────────────────
    ss = result.get("subcontract_section", {})
    if ss:
        print("\n■ 적법도급 체크리스트:")
        print(f"  총 항목: {ss.get('total_items', 0)}건")
        risk_total = sum(s.get("risk_count", 0) for s in ss.get("axis_summary", {}).values())
        compliant_total = sum(s.get("compliant_count", 0) for s in ss.get("axis_summary", {}).values())
        noneed_total = sum(s.get("noneed_count", 0) for s in ss.get("axis_summary", {}).values())
        print(f"  위험 신호: {risk_total}건 / 적법 방향: {compliant_total}건 / 근거 없음: {noneed_total}건")
        for r in ss.get("results", []):
            label = r.get("label", "?")
            axis = r.get("axis")
            item_no = r.get("item")
            name = r.get("name", "")
            print(f"    [축 {axis}·항목 {item_no}] {name}: {label}")
            if r.get("evidence_sentences"):
                for es in r["evidence_sentences"][:2]:
                    print(f"       근거: {es[:100]}")
            if r.get("risk_keywords_hit"):
                print(f"       위험키워드: {', '.join(r['risk_keywords_hit'])}")
            if r.get("compliant_keywords_hit"):
                print(f"       적법키워드: {', '.join(r['compliant_keywords_hit'])}")

    # ── (c) 사진 섹션 ────────────────────────────────────────────────────────
    ps = result.get("photo_section", {})
    if ps:
        print("\n■ 사진 섹션:")
        print(f"  업로드 사진: {len(ps.get('photo_files', []))}개")
        pc = ps.get("counts", {})
        print(f"  총 주장: {pc.get('총주장', 0)}건")
        print(f"  매칭 성공: {pc.get('매칭성공', 0)}건 / 매칭 실패: {pc.get('매칭실패', 0)}건")
        print(f"  뒷받침함: {pc.get('뒷받침함', 0)}건 / 뒷받침 안 함: {pc.get('뒷받침안함', 0)}건 / 판단 불가: {pc.get('판단불가', 0)}건")
        dom = pc.get("도메인", {})
        if dom:
            print(f"  도메인 라우팅: {', '.join(f'{k}={v}' for k, v in dom.items())}")
        for m in ps.get("matches", []):
            v = m.get("verdict", "?")
            icon = {"뒷받침함": "✅", "뒷받침 안 함": "❌", "판단 불가": "⛔"}.get(v, "?")
            print(f"    {icon} [{m.get('domain','?')}] {m.get('marker','')} {m.get('photo_file','') or '미매칭'}")
            print(f"       문장: {m.get('sentence','')[:100]}")
            print(f"       판정: {v} / quote: {m.get('quote','') or '-'}")
            reason = m.get("reason", "")
            if reason:
                print(f"       사유: {reason[:100]}")

    print(f"\n⏱ 총 소요 시간: {result.get('elapsed_sec', 0)}초")


def save_result(result: Dict[str, Any], output_path: str):
    """결과를 JSON 파일로 저장."""
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


# ── 메인 ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='MABC cite-check 파이프라인')
    parser.add_argument('file', help='입력 파일 경로 (PDF/이미지/DOCX)')
    parser.add_argument('--output', '-o', default='work/pipeline_result.json',
                        help='출력 JSON 경로')
    parser.add_argument('--offline', action='store_true', help='오프라인 모드')
    parser.add_argument('--max-verify', type=int, default=60,
                        help='최대 검증 건수')
    parser.add_argument('--match-parallel', type=int, default=4,
                        help='주장 대조 병렬 수')
    parser.add_argument('--no-match-cache', action='store_true',
                        help='대조 캐시 사용 안 함')
    parser.add_argument('--photos', '-p', default=None,
                        help='사진 파일 경로 (쉼표 구분 또는 JSON 배열 문자열)')
    args = parser.parse_args()

    # 사진 목록 파싱
    photo_files = None
    if args.photos:
        raw_photos = args.photos.strip()
        # JSON 배열 형태면 json.loads
        if raw_photos.startswith('['):
            import json
            parsed = json.loads(raw_photos)
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                photo_files = parsed
            else:
                print("오류: --photos JSON 배열은 문자열 리스트여야 함", file=sys.stderr)
                sys.exit(2)
        else:
            # 쉼표 구분
            photo_files = [p.strip() for p in raw_photos.split(',') if p.strip()]
            if not all(os.path.isfile(p) for p in photo_files):
                missing = [p for p in photo_files if not os.path.isfile(p)]
                print(f"오류: 사진 파일 없음: {missing}", file=sys.stderr)
                sys.exit(2)

    print(f"파이프라인 시작: {args.file}")
    print(f"  오프라인={args.offline}, 병렬={args.match_parallel}, "
          f"캐시={'사용' if not args.no_match_cache else '미사용'}"
          + (f", 사진={len(photo_files)}개" if photo_files else ""))

    result = run_pipeline(
        file_path=args.file,
        offline=args.offline,
        max_verify=args.max_verify,
        match_parallel=args.match_parallel,
        match_use_cache=not args.no_match_cache,
        photo_files=photo_files,
    )

    save_result(result, args.output)
    print(f"\n결과 저장: {args.output}")
    print_summary(result)

    # 종료 코드
    gate_status = result.get("gate", {}).get("status", "")
    if gate_status == GATE_NEEDS_REVISION:
        sys.exit(1)
    elif gate_status == GATE_NEEDS_CHECK:
        sys.exit(2)
    else:
        sys.exit(0)
