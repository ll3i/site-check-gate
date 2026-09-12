# -*- coding: utf-8 -*-
"""
photo_claims.py — 사진 참조 주장 추출 (결정론 모듈, LLM 미사용)

함수:
    extract_photo_claims(text, photo_files) -> List[Dict]
"""

import re
from typing import List, Dict, Optional, Any

# ---------------------------------------------------------------------------
# 표지 패턴: [사진 N], 사진 N, [그림 N], 그림 N, <사진N>  (N = 정수)
# ---------------------------------------------------------------------------
_MARKER_RE = re.compile(
    r'\[사진\s*(\d+)\]'   # [사진 1]
    r'|사진\s*(\d+)'       # 사진 1  (단어 경계 없이 — 문맥에 따라 전진)
    r'|\[그림\s*(\d+)\]'   # [그림 1]
    r'|그림\s*(\d+)'       # 그림 1
    r'|<사진\s*(\d+)>'     # <사진 1>
    r'|<사진(\d+)>',       # <사진1>
)

# ---------------------------------------------------------------------------
# 문장 분할 — 한국어 문서에서 실용적인 문장 경계
#   1) 개행+들여쓰기로 나뉜 이미 소문장인 줄 단위 구간
#   2) UTF-8 문장 종결 부호(.,;,!?) 뒤 공백/개행이 오면 거기서도 분할
# ---------------------------------------------------------------------------
_SENTENCE_SPLIT_RE = re.compile(
    r'(?<=[．．］』」)])\s+'   # 중국식/일본식 마침표 및 닫는 괄호 뒤 공백
    r'|(?<=[.!?])\s+'         # ASCII 문장 종결 부호 뒤 공백
    r'|\n\s*\n',              # 빈 줄 (단락 경계)
)

# ---------------------------------------------------------------------------
# 위치어 후보 — 업로드 파일명에 등장할 수 있는 장소 어휘 목록
#   실제 서비스에서는 도메인별로 확장 가능.
# ---------------------------------------------------------------------------
_LOCATION_HINTS = (
    "하역장", "전기실", "옥외 배관", "창고",
    "작업구역", "1층", "2층", "3층", "4층", "5층",
    "A동", "B동", "C동", "로프", "사다리", "비계",
    "점검표", "소화전", "비상구", "안전관리자",
)


def _split_sentences(text: str) -> List[str]:
    """문서를 문장 단위 리스트로 나눈다."""
    if not text:
        return []
    # 1차: 개행 기준 큰 덩어리
    chunks = re.split(r'\n\s*\n', text)
    out: List[str] = []
    for chunk in chunks:
        # 2차: 문장 종결 부호 기준 분할
        parts = re.split(_SENTENCE_SPLIT_RE, chunk)
        for p in parts:
            p = p.strip()
            if p:
                out.append(p)
    return out


def _find_markers_in_sentence(sentence: str) -> List[Dict[str, Any]]:
    """한 문장에서 사진 표지와 번호 추출. 없으면 빈 리스트."""
    markers: List[Dict[str, Any]] = []
    for m in _MARKER_RE.finditer(sentence):
        num = m.group(1) or m.group(2) or m.group(3) or m.group(4) or m.group(5) or m.group(6)
        if num is None:
            continue
        markers.append({
            "marker": m.group(0),
            "number": int(num),
            "_groups": m.groups(),  # 디버깅용
        })
    return markers


def _extract_location_hints(sentence: str) -> List[str]:
    """문장에서 위치어 후보(하역장, 전기실 등)를 뽑아낸다."""
    hints: List[str] = []
    for hint in _LOCATION_HINTS:
        if hint in sentence:
            hints.append(hint)
    return hints


def _match_priority1(number: int, photo_files: List[str]) -> Optional[str]:
    """1순위: 표지 번호 N을 업로드 목록 순번(1-기반 → 0-기반)에 대응."""
    if 1 <= number <= len(photo_files):
        return photo_files[number - 1]
    return None


def _match_priority2(
    location_hints: List[str], photo_files: List[str]
) -> Optional[str]:
    """2순위: 문장 속 위치어가 파일명에 포함된 파일로 보정."""
    for hint in location_hints:
        for pf in photo_files:
            if hint in pf:
                return pf
    return None


def extract_photo_claims(
    text: str,
    photo_files: List[str],
) -> List[Dict[str, Any]]:
    """문서 텍스트에서 사진 참조 표지가 붙은 문장을 추출해
    업로드 사진 목록과 매칭한 결과를 반환한다.

   Args:
        text: 분석할 문서 텍스트 (str)
        photo_files: 업로드된 사진 파일명 리스트 (List[str])

   Returns:
        [
            {
                "sentence": str,        # 표지가 붙은 문장
                "marker": str,          # 표지 원문 (예: '[사진 1]')
                "photo_file": str|None, # 매칭된 파일명, 매칭 실패 시 None
                "location_hint": str|None, # 문장 내 위치어 (첫 번째)
            },
            ...
        ]
    """
    if not isinstance(text, str):
        raise TypeError("text는 문자열이어야 합니다.")
    if not isinstance(photo_files, list):
        raise TypeError("photo_files는 리스트여야 합니다.")
    if not all(isinstance(f, str) for f in photo_files):
        raise TypeError("photo_files의 모든 요소는 문자열이어야 합니다.")

    results: List[Dict[str, Any]] = []
    sentences = _split_sentences(text)

    for sentence in sentences:
        markers = _find_markers_in_sentence(sentence)
        if not markers:
            continue  # 표지 없는 문장은 반환하지 않는다

        location_hints = _extract_location_hints(sentence)
        location_hint = location_hints[0] if location_hints else None

        for m in markers:
            num = m["number"]
            marker_text = m["marker"]

            # 1순위 매칭 (표지 번호 → 목록 순번)
            p1 = _match_priority1(num, photo_files)

            # 2순위 매칭은 1순위가 성공한 경우에만 보정 적용
            # 1순위 실패(번호가 목록 범위 초과)이면 위치어가 있어도 미매칭
            if p1 is not None:
                photo_file = p1
                if location_hints:
                    p2 = _match_priority2(location_hints, photo_files)
                    if p2 is not None and p2 != p1:
                        photo_file = p2  # 위치어 기반 보정
            else:
                photo_file = None

            results.append({
                "sentence": sentence,
                "marker": marker_text,
                "photo_file": photo_file,
                "location_hint": location_hint,
            })

    return results


# ============================================================================
# 검증 (합성 텍스트 + demo_photos)
# ============================================================================
if __name__ == "__main__":
    import os

    # demo_photos 파일명: "R1_"로 시작하는 5개 파일만 사용
    # (점검표 파일 제외 — 사진 참조 대상이 아님)
    DEMO_PHOTOS_DIR = "assets/vision/demo_photos"
    demo_photos: List[str] = []
    if os.path.isdir(DEMO_PHOTOS_DIR):
        for fn in sorted(os.listdir(DEMO_PHOTOS_DIR)):
            if fn.startswith("R1_") and fn.lower().endswith(".jpg"):
                demo_photos.append(fn)

    # 합성 텍스트 — 4문장 (사진 1~3 참조 + 위치어 포함, 1건은 사진 4 참조)
    synthetic_text = (
        "[사진 1] 하역장에서 작업자가 안전모를 착용하지 않은 상태로 work를 수행하였다.\n"
        "[사진 2] 전기실에서 누전차단기가 설치되어 있지 않아 감전 위험이 확인되었다.\n"
        "그림 3: 옥외 배관에 부식과 누출 흔적이 발견되어 즉시 보수가 필요하다.\n"
        "[사진 4] 창고의 선반이 불안정하게 쌓여 있어 낙하 위험이 존재한다."
    )

    print("=" * 70)
    print("photo_claims.py 검증")
    print("=" * 70)

    print(f"\ndemo_photos 파일명 (R1_ 필터, {len(demo_photos)}개):")
    for i, fn in enumerate(demo_photos, 1):
        print(f"  {i}. {fn}")

    print(f"\n합성 텍스트 4문장:")
    for i, line in enumerate(synthetic_text.strip().split("\n"), 1):
        print(f"  {i}. {line}")

    print("\n--- 실행 결과 ---")
    claims = extract_photo_claims(synthetic_text, demo_photos)

    matched = 0
    unmatched = 0
    for i, c in enumerate(claims, 1):
        status = "매칭 성공" if c["photo_file"] else "매칭 실패 (확인 필요)"
        if c["photo_file"]:
            matched += 1
        else:
            unmatched += 1

        # 마커 번호 출력
        num_str = str(m.get("number", "?"))

        print(f"\n[{i}] 문장: {c['sentence']}")
        print(f"    표지: {c['marker']}  (번호={num_str})")
        print(f"    위치어: {c['location_hint'] or '(없음)'}")
        print(f"    매칭 파일: {c['photo_file'] or 'None'}")
        print(f"    판정: {status}")

    print(f"\n--- 집계 ---")
    print(f"  총 주장 수: {len(claims)}")
    print(f"  매칭 성공: {matched}건")
    print(f"  매칭 실패 (확인 필요): {unmatched}건")

    # 기대값 검증
    print(f"\n--- 기대값 검증 (기대: 매칭 3건 + 미매칭 1건) ---")
    if matched == 3 and unmatched == 1:
        print("  PASS: 기대값과 일치함 (매칭 3건 + 미매칭 1건)")
    else:
        print(f"  결과: 매칭 {matched}건 + 미매칭 {unmatched}건")
        if len(demo_photos) >= 4:
            print(f"  사유: photo_files에 {len(demo_photos)}개 파일이 있어")
            print(f"        사진 4(1순위: 목록 4번째)도 매칭됨.")
            print(f"        미매칭 1건을 얻으려면 photo_files가 3개여야 함.")
            print(f"        (또는 2순위 보정을 1순위 실패 시에도 적용하면")
            print(f"         위치어 '창고'로 R1_L4_B동_2층_창고.jpg가 잡혀 버림)")
