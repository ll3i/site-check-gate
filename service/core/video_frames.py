#!/usr/bin/env python3
"""
video_frames.py — mp4 → cv2 로 1fps 샘플링 (최대 24프레임, 640px 리사이즈) → 프레임 jpg 목록.

고속 샘플링: 영상 길이(초)와 무관하게 1초마다 1프레임씩 추출하며,
최대 24프레임으로 제한. 각 프레임은 640px 너비 기준으로 리사이즈하여 저장.
"""

from __future__ import annotations

import cv2
import os
from pathlib import Path
from typing import List


def extract_frames(
    video_path: str,
    out_dir: str,
    max_frames: int = 24,
    target_width: int = 640,
) -> List[str]:
    """mp4/video 파일을 1fps로 프레임 추출하여 jpg 목록으로 반환.

    Args:
        video_path: 입력 영상 파일 경로.
        out_dir: 프레임 jpg를 저장할 출력 디렉토리.
        max_frames: 최대 추출 프레임 수 (기본 24). 초과분은 버림.
        target_width: 리사이즈 목표 너비 (기본 640px). 높이는 비율에 맞춰 자동 계산.

    Returns:
        생성된 프레임 jpg 파일 경로 목록 ( 순서대로, 최대 max_frames 개).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"영상 열기 실패: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0  # 기본값

    frame_interval = max(1, round(fps))  # 1fps 샘플링 = fps 마다 1프레임

    os.makedirs(out_dir, exist_ok=True)

    frames: List[str] = []
    frame_idx = 0
    saved_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 1fps 샘플링: 프레임 인덱스를 fps로 나눈 나머지가 0일 때만 저장
        if frame_idx % frame_interval == 0 and saved_count < max_frames:
            # 640px 리사이즈 (너비 기준, 높이 비율 유지)
            h, w = frame.shape[:2]
            if w > 0:
                scale = target_width / w
                new_w = target_width
                new_h = max(1, int(h * scale))
                frame_resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            else:
                frame_resized = frame

            out_path = os.path.join(out_dir, f"frame_{saved_count:03d}.jpg")
            success = cv2.imwrite(out_path, frame_resized, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if success:
                frames.append(out_path)
                saved_count += 1

        frame_idx += 1

        # 최대 프레임 수 도달 시 조기 종료
        if saved_count >= max_frames:
            break

    cap.release()
    return frames


def extract_frames_with_info(
    video_path: str,
    out_dir: str,
    max_frames: int = 24,
    target_width: int = 640,
) -> List[dict]:
    """프레임 추출 + 메타데이터(타임스탬프, 해상도) 포함.

    Returns:
        [
            {"path": "...", "index": 0, "sec": 0.0, "width": 640, "height": 360},
            ...
        ]
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"영상 열기 실패: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0

    frame_interval = max(1, round(fps))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    os.makedirs(out_dir, exist_ok=True)

    result: List[dict] = []
    frame_idx = 0
    saved_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0 and saved_count < max_frames:
            h, w = frame.shape[:2]
            if w > 0:
                scale = target_width / w
                new_w = target_width
                new_h = max(1, int(h * scale))
                frame_resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            else:
                frame_resized = frame

            out_path = os.path.join(out_dir, f"frame_{saved_count:03d}.jpg")
            cv2.imwrite(out_path, frame_resized, [cv2.IMWRITE_JPEG_QUALITY, 90])

            sec = frame_idx / fps if fps > 0 else 0.0
            result.append({
                "path": out_path,
                "index": saved_count,
                "sec": round(sec, 2),
                "width": new_w,
                "height": new_h,
            })
            saved_count += 1

        frame_idx += 1

        if saved_count >= max_frames:
            break

    cap.release()
    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용: python video_frames.py <video_path> [out_dir]")
        sys.exit(1)

    vp = sys.argv[1]
    od = sys.argv[2] if len(sys.argv) > 2 else "frames_out"
    frames = extract_frames(vp, od)
    print(f"추출 완료: {len(frames)} 프레임")
    for f in frames:
        print(f"  {f}")
