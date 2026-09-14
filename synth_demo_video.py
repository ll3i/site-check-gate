#!/usr/bin/env python3
"""
mp4 합성 스크립트: demo_photos 3장을 각 1.33초씩 → 4초 mp4
"""

import cv2
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEMO_DIR = ROOT / "assets" / "vision" / "demo_photos"

photos = [
    DEMO_DIR / "r1_l3_pipe.jpg",
    DEMO_DIR / "r1_l2_loading.jpg",
    DEMO_DIR / "r1_l1_electrical.jpg",
]

FPS = 30
DURATION_PER_PHOTO = 1.33  # 초
frame_duration = int(FPS * DURATION_PER_PHOTO)  # 약 40프레임

output_path = ROOT / "tests" / "fixtures" / "cache" / "demo_video_synthesized.mp4"

# 640px 너비 기준
TARGET_WIDTH = 640

# 비디오 라이터 초기화
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out = None

for photo_path in photos:
    img = cv2.imread(str(photo_path))
    if img is None:
        print(f"경고: {photo_path} 읽기 실패, 건너뜀")
        continue
    h, w = img.shape[:2]
    scale = TARGET_WIDTH / w
    new_w = TARGET_WIDTH
    new_h = max(1, int(h * scale))
    resized = cv2.resize(img, (new_w, new_h))

    if out is None:
        out = cv2.VideoWriter(str(output_path), fourcc, FPS, (new_w, new_h))

    for _ in range(frame_duration):
        out.write(resized)

if out:
    out.release()
    print(f"mp4 합성 완료: {output_path}")
    print(f"총 프레임: {frame_duration * 3}")
    print(f"길이: {frame_duration * 3 / FPS:.2f}초")
else:
    print("오류: 비디오 라이터 초기화 실패")
