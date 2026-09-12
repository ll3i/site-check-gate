#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
photo_match.py — 사진 참조 문장과 YOLO 검출 결과를 solar-pro4로 대조.

함수:
    match_photo_claim(sentence: str, detections: List[Dict]) -> Dict[str, Any]

계약:
    - match_claims.py의 match_single_claim 호출 계약을 재사용하되,
      메타데이터 자리에 '검출된 객체: label(conf) 목록' 문자열을 넣는다.
    - system prompt는 본 모듈이 직접 작성. 고정 출력: JSON {verdict, quote, reason}.
    - quote는 검출 라벨 문자열 하나여야 함 (검출 라벨 집합 안에서만).
    - temperature=0.0.

코드 후처리 (프롬프트 아님):
    ① 뒷받침함인데 quote가 검출 라벨 집합에 정확히 없으면 → 판단 불가로 강등
    ② 뒷받침 안 함이면 quote 없어도 유지 + "무인용 거절" 태그
    ③ 검출 0건이면 API 호출 없이 판단 불가 반환

참고: match_claims.py의 match_single_claim(claim, metadata_title, metadata_abstract)를
      재활용한다. metadata_title은 빈 문자열, metadata_abstract에 검출 요약 문자열을 넣는다.
"""

from typing import Any, Dict, List, Optional

from service.core.match_claims import (
    VERDICT_SUPPORTED,
    VERDICT_NOT_SUPPORTED,
    VERDICT_CANNOT_JUDGE,
    TAG_NO_QUOTE_REJECTION,
    match_single_claim,
    normalize_text,
)
import service.core.match_claims as _mc

# ── 상수 ──────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 현장 사진 기반 안전 점검 인용 검증 도구입니다.

## 작업
사진 속 검출된 객체 목록과, 사진 참조 주장 문장을 대조하여 주장이 검출 결과로
뒷받침되는지 판단하세요.

## 입력 설명
- 주장 문장(claim): 현장 점검 문서에 적힌 사진 참조 문장. 위치명·조치·계획·행정 문구를 포함할 수 있습니다.
- 검출된 객체 목록: YOLO 객체 검출기가 사진에서 찾아낸 객체들의 라벨과 신뢰도.
  형식: "검출된 객체: label1(conf1), label2(conf2), ..."

## 판정 대상 한정 (중요)
주장 문장 전체를 검증하지 마세요. 오직 문장 중 '사진에 보이는 상태에 대한 서술' 부분만 판정 대상입니다.
- 위치명(예: "B동", "A동 1층"), 조치(예: "시정을 요구하였다"), 계획, 행정 문구는 문맥일 뿐 검증 대상이 아닙니다.
- 예: "B동 옥외 배관에서 부식이 확인되어 시정을 요구하였다" → 판정 대상은 "부식이 확인되어" (사진에 부식이 보이는가) 입니다. "B동"과 "시정을 요구하였다"는 검증하지 않습니다.

## 라벨-한국어 의미 대응 (허용된 판단)
검출 라벨은 영어입니다. 한국어 서술과 라벨의 다음 의미 대응은 허용된 판단입니다:
- corrosion = 부식
- crack = 균열
- cable_damage = 케이블 손상
- wall_damage = 벽체 손상
- weld_* = 용접 상태 (용접 불량, 용접 균열 등)
- cardboard / plastic / glass / metal / paper = 방치된 적재물·폐기물
- gauge / digit = 계기

위 대응 외의 임의 추측은 금지합니다. 검출 목록에 없는 한국어 상태를 영어 라벨로 유추하지 마세요.

## 판정 기준
1. 뒷받침함: 사진에 보이는 상태에 대한 서술과 일치하는 상태 라벨이 검출된 경우.
   - quote는 그 일치하는 검출 라벨 문자열이어야 합니다.
   - 예: 서술이 "부식이 확인되었다"이고 검출에 corrosion이 있으면 → 뒷받침함, quote: "corrosion"

2. 뒷받침 안 함: 사진에 보이는 상태에 대한 서술과 모순되는 검출이 있는 경우.
   - 예: 서술이 "적재물이 정리되어 양호하다"인데, 검출에 cardboard, plastic 등 폐기물/방치물 라벨이 다수 검출되면 → 뒷받침 안 함.
   - 예: 서술이 "부식이 없다"인데 corrosion이 검출되면 → 뒷받침 안 함.

3. 판단 불가: 다음 중 하나 이상인 경우.
   - 검출 결과가 0건인 경우.
   - 사진에 보이는 상태에 대한 서술의 내용을 이 도메인 검출 결과로는 알 수 없는 경우.
     (예: 서술이 "부식"을 언급했는데, 검출은 cleaning 도메인 결과로 cleaning 관련 라벨만 있는 경우 — 부식 여부를 이 검출로는 알 수 없음)

## 중요 규칙
1. 오직 검출된 객체 목록만 근거로 사용하세요. 검출 목록에 없는 객체를 지어내지 마세요.
2. quote는 반드시 검출 라벨 문자열 중 하나와 정확히 일치해야 합니다.
3. 출력은 반드시 다음 형식의 JSON 하나만 출력하세요:
   {"verdict": "뒷받침함" | "뒷받침 안 함" | "판단 불가",
    "quote": "검출 라벨 문자열 (비어있을 수 있음)",
    "reason": "판단 근거 (한국어)"}

## 예시 (이해 보조용 — 실제 판정은 검출 목록에 근거)
- 주장: "B동 옥외 배관에서 부식이 확인되어 시정을 요구하였다" / 검출: ["corrosion(0.84)"]
  → 판정 대상: "부식이 확인되어" → 뒷받침함, quote: "corrosion"
  (위치명 "B동"과 조치 "시정을 요구하였다"는 검증 대상이 아님)

- 주장: "A동 1층 하역장은 적재물이 정리되어 양호하다" / 검출: ["cardboard(0.72)", "plastic(0.68)"]
  → 서술 "정리되어 양호"와 모순: 폐기물 라벨 다수 검출 → 뒷받침 안 함

- 주장: "배관에 녹이 슬었다" / 검출: ["rust", "pipe"] → 뒷받침함, quote: "rust"
- 주장: "청소 상태가 양호하다" / 검출: ["rust", "leak"] → 뒷받침 안 함 (서술과 모순)
- 주장: "배관 부식이 심각하다" / 검출: ["clean", "mop"] → 판단 불가 (부식 정보 없음)

## 제한
- 검출 목록에 없는 수치·도메인 정보를 지어내지 마세요.
- 판정은 오직 검출된 객체 라벨 문자열과, 위에서 허용된 라벨-한국어 의미 대응에 근거하세요.
- 위치명·조치·계획·행정 문구는 검증하지 마세요.
"""

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def build_detection_metadata(detections: List[Dict[str, Any]]) -> str:
    """검출 결과 리스트를 '검출된 객체: label(conf) 목록' 문자열로 변환."""
    if not detections:
        return "검출된 객체: (없음)"
    parts = []
    for d in detections:
        label = d.get("label", "unknown")
        conf = d.get("conf", 0.0)
        parts.append(f"{label}({conf:.2f})")
    return "검출된 객체: " + ", ".join(parts)


def get_label_set(detections: List[Dict[str, Any]]) -> set:
    """검출 라벨 문자열 집합을 반환."""
    return {d.get("label", "unknown") for d in detections}


def _extract_quote_from_response(response: Optional[str], label_set: set) -> str:
    """응답에서 quote 추출 시도. label_set에 속한 라벨만 허용."""
    if not response:
        return ""
    import json
    import re
    quote = ""
    # JSON 블록 탐색
    m = re.search(r'"quote"\s*:\s*"([^"]*)"', response)
    if m:
        candidate = m.group(1).strip()
        # 정규화 후 label_set에 속하는지 확인
        norm_candidate = normalize_text(candidate)
        for label in label_set:
            if normalize_text(label) == norm_candidate:
                quote = label
                break
        # 정확히 일치하지 않으면 빈 문자열
        if not quote:
            # 라벨 이름이 normalize 후 일치 시도
            for label in label_set:
                if normalize_text(label) == normalize_text(candidate):
                    quote = label
                    break
    return quote


# ── 메인 함수 ─────────────────────────────────────────────────────────────────

def match_photo_claim(
    sentence: str,
    detections: List[Dict[str, Any]],
    use_cache: bool = True,
) -> Dict[str, Any]:
    """사진 참조 문장과 YOLO 검출 결과를 solar-pro4로 대조.

    Args:
        sentence: 사진 참조 주장 문장.
        detections: [{label, conf, box}, ...] 형태 검출 결과 리스트.
        use_cache: match_claims.py 캐시 사용 여부.

    Returns:
        {
            'claim': 문장,
            'verdict': "뒷받침함" | "뒷받침 안 함" | "판단 불가",
            'quote': 검출 라벨 문자열 (또는 ''),
            'reason': 판단 근거,
            'metadata_title': '',
            'metadata_abstract': 검출 메타데이터 문자열,
            'quote_exists': bool (코드 후처리 검사용),
            'post_processed': bool,
            'tags': [태그...],
            'raw_response': API 응답 원문 (또는 ''),
            'detection_count': int,
            'label_set': set,
        }
    """
    label_set = get_label_set(detections)
    detection_count = len(detections)
    metadata_abstract = build_detection_metadata(detections)
    metadata_title = ""

    result: Dict[str, Any] = {
        'claim': sentence,
        'verdict': VERDICT_CANNOT_JUDGE,
        'quote': '',
        'reason': '',
        'metadata_title': metadata_title,
        'metadata_abstract': metadata_abstract,
        'quote_exists': False,
        'post_processed': False,
        'tags': [],
        'raw_response': '',
        'detection_count': detection_count,
        'label_set': list(label_set),
    }

    # ── ③ 검출 0건 → API 호출 없이 판단 불가 ────────────────────────────────
    if detection_count == 0:
        result['verdict'] = VERDICT_CANNOT_JUDGE
        result['reason'] = "검출 결과가 없어 판단할 수 없습니다."
        result['post_processed'] = True
        return result

    # ── match_single_claim 호출 (match_claims.py 계약 재사용) ────────────────
    # metadata_title은 비어 있고, metadata_abstract에 검출 요약 문자열.
    # photo_match의 SYSTEM_PROMPT를 match_claims에 주입한 뒤 호출하고 복원한다.
    # 또한 quote_exists_in_metadata도 photo_match 방식(라벨 집합 비교)으로
    # 임시 교체하여 match_claims 후처리(PRD §6 3번)가 photo_match 기준으로
    # 작동하도록 한다.
    _orig_sp = _mc.SYSTEM_PROMPT
    _orig_quote_exists = _mc.quote_exists_in_metadata
    _mc.SYSTEM_PROMPT = SYSTEM_PROMPT
    # photo_match 방식 quote 실존 검사: 정규화 후 label_set과 비교
    def _photo_quote_exists(quote: str, metadata_title: str, metadata_abstract: str) -> bool:
        if not quote:
            return False
        norm_quote = normalize_text(quote)
        for label in label_set:
            if normalize_text(label) == norm_quote:
                return True
        return False
    _mc.quote_exists_in_metadata = _photo_quote_exists
    try:
        mc_result = match_single_claim(
            claim=sentence,
            metadata_title=metadata_title,
            metadata_abstract=metadata_abstract,
            use_cache=use_cache,
        )
    finally:
        _mc.SYSTEM_PROMPT = _orig_sp
        _mc.quote_exists_in_metadata = _orig_quote_exists

    # match_single_claim 결과를 photo_match 결과 형식으로 전이
    result['verdict'] = mc_result.get('verdict', VERDICT_CANNOT_JUDGE)
    result['quote'] = mc_result.get('quote', '')
    result['reason'] = mc_result.get('reason', '')
    result['raw_response'] = mc_result.get('raw_response', '')
    result['quote_exists'] = mc_result.get('quote_exists', False)
    result['post_processed'] = mc_result.get('post_processed', False)
    result['tags'] = mc_result.get('tags', [])

    # ── photo_match 전용 quote 검증 ──────────────────────────────────────────
    # match_claims.py의 quote_exists_in_metadata는 메타텍스트 내 substring 검사라
    # 검출 라벨 집합에 quote가 있는지 확인하는 데 직접 쓰기에 부적합.
    # 여기서는 검출 라벨 문자열 집합 기준으로 quote 실재 여부를 판정한다.
    raw_quote = result['quote']
    quote_valid = False
    if raw_quote:
        norm_quote = normalize_text(raw_quote)
        for label in label_set:
            if normalize_text(label) == norm_quote:
                quote_valid = True
                result['quote'] = label  # 정규화된 원래 라벨로 확정
                break

    result['quote_exists'] = quote_valid

    # ── ① 뒷받침함 + quote ∉ label_set → 판단 불가 강등 ────────────────────
    if result['verdict'] == VERDICT_SUPPORTED and not quote_valid:
        result['verdict'] = VERDICT_CANNOT_JUDGE
        result['quote'] = ''          # 무효 quotes은 비운다
        result['post_processed'] = True
        result['reason'] = (
            f"[강등] quote '{raw_quote}'가 검출 라벨 집합에 없어 "
            f"'{VERDICT_CANNOT_JUDGE}'로 강등. "
            f"원본 판정: {VERDICT_SUPPORTED}"
        )

    # ── ② 뒷받침 안 함 + quote 없음 → 유지 + 무인용 태그 ────────────────────
    if result['verdict'] == VERDICT_NOT_SUPPORTED and not result['quote']:
        if TAG_NO_QUOTE_REJECTION not in result['tags']:
            result['tags'].append(TAG_NO_QUOTE_REJECTION)
        result['post_processed'] = True
        if result['reason']:
            result['reason'] = f"[무인용 거절] {result['reason']}"
        else:
            result['reason'] = (
                "[무인용 거절] 근거 라벨 없이 거절됨 — 확인 필요 큐로 이동"
            )

    return result


# ── CLI / 검증 ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import json
    import sys
    import os

    # 경로 설정
    BASE = os.path.dirname(os.path.abspath(__file__))
    PHOTO_DIR = os.path.join(BASE, '..', '..', 'assets', 'vision', 'demo_photos')
    sys.path.insert(0, os.path.join(BASE, '..'))

    from service.core.photo_detect import detect_objects

    img_path = os.path.join(PHOTO_DIR, 'R1_L3_B동_옥외_배관.jpg')

    # 케이스 (a)
    sentence_a = 'B동 옥외 배관에서 부식이 확인되어 시정을 요구하였다'
    print("=" * 70)
    print("케이스 (a)")
    print(f"문장: {sentence_a}")
    print(f"이미지: {img_path}")
    print("-" * 70)

    detections_a = detect_objects(img_path, 'defect')
    print(f"defect 검출 결과 ({len(detections_a)}건):")
    for d in detections_a:
        print(f"  label={d['label']}, conf={d['conf']}, box={d['box']}")

    result_a = match_photo_claim(sentence_a, detections_a, use_cache=False)
    print()
    print("판정 결과:")
    print(json.dumps(result_a, ensure_ascii=False, indent=2))
    print()
    print(f"  verdict       : {result_a['verdict']}")
    print(f"  quote         : '{result_a['quote']}'")
    print(f"  reason        : {result_a['reason']}")
    print(f"  post_processed: {result_a['post_processed']}")
    print(f"  quote_exists  : {result_a['quote_exists']}")
    print(f"  tags          : {result_a['tags']}")
    print(f"  강등 여부     : {'예 (뒷받침함→판단 불가)' if result_a['post_processed'] and result_a['verdict'] == VERDICT_CANNOT_JUDGE else '아니오'}")

    # 케이스 (b)
    print()
    print("=" * 70)
    print("케이스 (b)")
    sentence_b = 'A동 1층 하역장은 적재물이 정리되어 양호하다'
    print(f"문장: {sentence_b}")
    print(f"이미지: {img_path}")
    print("-" * 70)

    detections_b = detect_objects(img_path, 'cleaning')
    print(f"cleaning 검출 결과 ({len(detections_b)}건):")
    for d in detections_b:
        print(f"  label={d['label']}, conf={d['conf']}, box={d['box']}")

    result_b = match_photo_claim(sentence_b, detections_b, use_cache=False)
    print()
    print("판정 결과:")
    print(json.dumps(result_b, ensure_ascii=False, indent=2))
    print()
    print(f"  verdict       : {result_b['verdict']}")
    print(f"  quote         : '{result_b['quote']}'")
    print(f"  reason        : {result_b['reason']}")
    print(f"  post_processed: {result_b['post_processed']}")
    print(f"  quote_exists  : {result_b['quote_exists']}")
    print(f"  tags          : {result_b['tags']}")
    print(f"  강등 여부     : {'예 (뒷받침함→판단 불가)' if result_b['post_processed'] and result_b['verdict'] == VERDICT_CANNOT_JUDGE else '아니오'}")

    print()
    print("=" * 70)
    print("요약")
    print("=" * 70)
    print(f"케이스 (a) 결함 검출: verdict={result_a['verdict']}, quote='{result_a['quote']}', "
          f"강등={'예' if result_a['post_processed'] and result_a['verdict'] == VERDICT_CANNOT_JUDGE else '아니오'}")
    print(f"케이스 (b) 청소 검출: verdict={result_b['verdict']}, quote='{result_b['quote']}', "
          f"강등={'예' if result_b['post_processed'] and result_b['verdict'] == VERDICT_CANNOT_JUDGE else '아니오'}")
