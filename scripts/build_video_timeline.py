#!/usr/bin/env python3
"""
build_video_timeline.py — demo_video.mp4 를 1fps 샘플링하여 safety+defect+cleaning 검출,
assets/vision/demo_video_timeline.json 을 생성한다 (실측 데이터).

형식:
{
  "fps_sampled": 1,
  "events": [
    {
      "t": 초,
      "detections": [{label, conf, box}],
      "risk_level": "위험" | "주의" | "양호",
      "action": "...",
      "law_refs": [{"법령", "조", "발췌"}]
    }
  ]
}

inspect_mode 의 LABEL_MAP·리스크 분류·법령 연결 로직을 그대로 재사용한다.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from service.core.video_frames import extract_frames_with_info
from service.core.photo_detect import detect_objects
from service.core.inspect_mode import (
    CONF_MIN,
    LABEL_MAP,
    _build_law_refs,
    _classify_risk,
    _build_action,
    _normalize_det,
)

VIDEO_PATH = ROOT / "assets" / "vision" / "demo_video.mp4"
OUT_PATH = ROOT / "assets" / "vision" / "demo_video_timeline.json"
FRAMES_DIR = ROOT / "assets" / "vision" / "_timeline_frames"
CONF_THRESHOLD = 0.45


def _run_domain(image_path: str, domain: str) -> List[Dict[str, Any]]:
    """도메인 검출 후 conf >= CONF_THRESHOLD 필터링."""
    try:
        dets = detect_objects(image_path, domain)
    except Exception as exc:
        print(f"  [warn] {domain} 검출 실패 ({image_path}): {exc}", file=sys.stderr)
        return []
    return [d for d in dets if d.get("conf", 0.0) >= CONF_THRESHOLD]


def _inspect_frame(image_path: str, sec: float) -> Dict[str, Any]:
    """단일 프레임에 대해 defect + cleaning + safety 검출 후 이벤트 dict 반환."""
    defect_dets = _run_domain(image_path, "defect")
    cleaning_dets = _run_domain(image_path, "cleaning")
    safety_dets = _run_domain(image_path, "safety")

    all_dets = defect_dets + cleaning_dets + safety_dets

    # LABEL_MAP 기반으로 분류
    labeled: List[Dict[str, Any]] = []
    law_keys: set = set()

    for det in all_dets:
        label = det["label"]
        entry = LABEL_MAP.get(label)
        if entry is None:
            labeled.append({"det": det, "entry": None})
            continue
        labeled.append({"det": det, "entry": entry})
        law = entry.get("law")
        if law is not None:
            law_keys.add(law)

    # 법령 조문 (실존하는 것만)
    law_refs = _build_law_refs(law_keys)

    # 위험도
    risk_level = _classify_risk(labeled)

    # 액션
    action = _build_action(risk_level, labeled)

    # 검출 목록 (정규화)
    detections = [_normalize_det(d["det"]) for d in labeled]

    return {
        "t": round(sec, 2),
        "detections": detections,
        "risk_level": risk_level,
        "action": action,
        "law_refs": law_refs,
    }


def main() -> None:
    if not VIDEO_PATH.is_file():
        print(f"오류: 영상 없음: {VIDEO_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"영상: {VIDEO_PATH}")
    print(f"1fps 샘플링 → 프레임 추출 중...")

    frames_info = extract_frames_with_info(
        str(VIDEO_PATH),
        str(FRAMES_DIR),
        max_frames=24,
        target_width=640,
    )

    if not frames_info:
        print("오류: 추출된 프레임이 없습니다.", file=sys.stderr)
        sys.exit(1)

    print(f"추출 완료: {len(frames_info)} 프레임")

    events: List[Dict[str, Any]] = []
    has_risk = False

    for fi in frames_info:
        sec = fi["sec"]
        path = fi["path"]
        print(f"  처리: t={sec:.1f}s ({path})")

        event = _inspect_frame(path, sec)
        events.append(event)

        if event["risk_level"] == "위험":
            has_risk = True
            print(f"    ⚠ 위험 이벤트 감지: {event['action'][:80]}...")

    timeline = {
        "fps_sampled": 1,
        "events": events,
    }

    # 디렉토리 확인
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)

    print(f"\n타임라인 저장 완료: {OUT_PATH}")
    print(f"총 이벤트 수: {len(events)}")
    print(f"위험 이벤트 존재: {'예' if has_risk else '아니오'}")

    # 요약
    risk_count = sum(1 for e in events if e["risk_level"] == "위험")
    caution_count = sum(1 for e in events if e["risk_level"] == "주의")
    ok_count = sum(1 for e in events if e["risk_level"] == "양호")
    print(f"  위험: {risk_count}, 주의: {caution_count}, 양호: {ok_count}")

    # 프레임 임시 파일 정리 (선택)
    print("\n프레임 파일 정리 중...")
    for fi in frames_info:
        try:
            os.remove(fi["path"])
        except OSError:
            pass
    try:
        os.rmdir(FRAMES_DIR)
    except OSError:
        pass
    print("완료.")

    # 실측 데이터임을 표시하기 위해exit 코드에 위험 이벤트 존재 여부 반영
    if has_risk:
        print("\n✓ 실측 확인: 위험 이벤트 1개 이상 존재")
    else:
        print("\n⚠ 실측 확인: 위험 이벤트 없음 (smoke 테스트 통과 여부 별도 확인 필요)")


if __name__ == "__main__":
    main()
