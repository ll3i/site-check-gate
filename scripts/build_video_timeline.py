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
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
CONF_THRESHOLD = 0.35


def _run_domain(image_path: str, domain: str) -> List[Dict[str, Any]]:
    """각 프레임을 열 표준편차(std>5)로 콘텐츠 x범위 크롭한 뒤 검출.

    박스 좌표는 x0 를 더해 원본 프레임 기준으로 역변환한다
    (프런트가 video 위에 그대로 겹치므로 필수).
    """
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"  [warn] 프레임 읽기 실패: {image_path}", file=sys.stderr)
        return []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    col_std = np.std(gray, axis=0)

    mask = col_std > 5.0
    cols = np.where(mask)[0]

    if len(cols) == 0:
        # 콘텐츠 없음 → 원본으로 검출
        try:
            dets = detect_objects(image_path, domain)
        except Exception as exc:
            print(f"  [warn] {domain} 검출 실패 ({image_path}): {exc}", file=sys.stderr)
            return []
        return [d for d in dets if d.get("conf", 0.0) >= CONF_THRESHOLD]

    x0 = int(cols[0])
    x1 = int(cols[-1]) + 1
    cropped = frame[:, x0:x1]

    tmp_path = f"{image_path}.crop.jpg"
    cv2.imwrite(tmp_path, cropped, [cv2.IMWRITE_JPEG_QUALITY, 90])

    try:
        dets = detect_objects(tmp_path, domain)
    except Exception as exc:
        print(f"  [warn] {domain} 검출 실패 ({tmp_path}): {exc}", file=sys.stderr)
        dets = []
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    adjusted: List[Dict[str, Any]] = []
    for d in dets:
        if d.get("conf", 0.0) < CONF_THRESHOLD:
            continue
        box = d.get("box", [0, 0, 0, 0])
        adjusted.append({
            "label": d["label"],
            "conf": d["conf"],
            "box": [box[0] + x0, box[1], box[2] + x0, box[3]],
        })
    return adjusted


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
    print("1fps 샘플링 → 원본 해상도 프레임 추출 중...")

    # 기존 프레임 디렉터리 삭제 (재사용 금지 — 임시 디렉터리만 사용)
    for old_dir in [ROOT / "assets" / "vision" / "_debug_frames",
                    ROOT / "assets" / "vision" / "_timeline_frames"]:
        if old_dir.is_dir():
            print(f"기존 디렉터리 삭제: {old_dir}")
            shutil.rmtree(old_dir, ignore_errors=True)

    # tempdir 생성 (종료 시 정리)
    tmp_dir = tempfile.mkdtemp(prefix="timeline_frames_")
    print(f"임시 디렉터리: {tmp_dir}")

    cap = cv2.VideoCapture(str(VIDEO_PATH))
    if not cap.isOpened():
        print(f"오류: 영상 열기 실패: {VIDEO_PATH}", file=sys.stderr)
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0.0
    print(f"영상 정보: {fps:.2f}fps, {total_frames} 프레임, {duration:.1f}초")

    frames_info: List[Dict[str, Any]] = []
    frame_idx = 0
    saved_count = 0
    max_frames = 40

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # CAP_PROP_POS_MSEC 기준으로 결정
        current_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        if current_ms < 0:
            current_ms = frame_idx / fps * 1000.0 if fps > 0 else 0.0
        sec = current_ms / 1000.0

        # 1초마다 1프레임 (첫 프레임 포함, 0초부터)
        if abs(sec - round(sec)) < 0.01 and saved_count < max_frames:
            # 원본 해상도 그대로 저장
            out_path = os.path.join(tmp_dir, f"frame_{saved_count:03d}.jpg")
            cv2.imwrite(out_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            frames_info.append({
                "path": out_path,
                "index": saved_count,
                "sec": round(sec, 2),
                "width": frame.shape[1],
                "height": frame.shape[0],
            })
            saved_count += 1
            print(f"  추출: t={sec:.1f}s, {frame.shape[1]}x{frame.shape[0]} → {out_path}")

        frame_idx += 1

        if saved_count >= max_frames:
            break

    cap.release()

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

    # 저장
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

    # 라벨 분포
    from collections import Counter
    label_counter = Counter()
    for e in events:
        for d in e["detections"]:
            label_counter[d["label"]] += 1
    print("\n라벨 분포:")
    for label, count in label_counter.most_common():
        print(f"  {label}: {count}")

    # 프레임 임시 파일 정리
    print("\n프레임 임시 파일 정리 중...")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"임시 디렉터리 삭제: {tmp_dir}")

    # 실측 데이터임을 표시하기 위해 exit 코드에 위험 이벤트 존재 여부 반영
    if has_risk:
        print("\n✓ 실측 확인: 위험 이벤트 1개 이상 존재")
    else:
        print("\n⚠ 실측 확인: 위험 이벤트 없음 (smoke 테스트 통과 여부 별도 확인 필요)")


if __name__ == "__main__":
    main()
