#!/usr/bin/env python3
"""
annotate.py — 이미지 + detections → PIL 로 박스·라벨 칩을 그린 주석본 jpg 저장.

위험 라벨(corrosion, crack, wall_damage, weld_defect, weld_bad, cable_damage)은 빨강 박스,
그 외(주의·기타)는 흰 반투명 박스로 그린다.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from PIL import Image, ImageDraw, ImageFont


# 위험 라벨 집합 — 빨강 박스로 표시
RISK_LABELS = frozenset({
    "corrosion", "crack", "wall_damage", "weld_defect", "weld_bad", "cable_damage",
})


def annotate_image(
    image_path: str,
    detections: List[Dict[str, Any]],
    out_path: str,
    font_size: int = 14,
) -> str:
    """이미지 위에 검출 박스와 라벨 칩을 그려 저장.

    Args:
        image_path: 원본 이미지 파일 경로.
        detections: 검출 리스트 (label, conf, box 포함).
        out_path: 주석본 저장 경로.
        font_size: 라벨 칩 폰트 크기.

    Returns:
        저장된 파일 경로.
    """
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    for det in detections:
        label = det.get("label", "")
        conf = det.get("conf", 0.0)
        box = det.get("box", [0, 0, 0, 0])
        if len(box) != 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in box]

        is_risk = label in RISK_LABELS

        if is_risk:
            # 위험: 빨강 박스 (두꺼운 선)
            box_color = (255, 0, 0)
            box_width = 3
            chip_bg = (255, 200, 200)  # 연한 빨강 배경
            chip_text_color = (0, 0, 0)
            chip_border = (200, 0, 0)
        else:
            # 주의/기타: 흰색 반투명 박스
            box_color = (255, 255, 255)
            box_width = 2
            chip_bg = (255, 255, 255)
            chip_text_color = (0, 0, 0)
            chip_border = (180, 180, 180)

        # 박스 그리기
        draw.rectangle([x1, y1, x2, y2], outline=box_color, width=box_width)

        # 라벨 칩 텍스트
        label_text = f"{label} {conf:.0%}"

        # 칩 크기 측정
        bbox = draw.textbbox((0, 0), label_text, font=font)
        chip_w = bbox[2] - bbox[0] + 12
        chip_h = bbox[3] - bbox[1] + 8

        # 칩을 박스 상단 왼쪽에 배치 (박스 밖이면 박스 내부 상단)
        chip_x = x1
        chip_y = max(0, y1 - chip_h - 4)

        # 칩 배경 그리기
        draw.rectangle([chip_x, chip_y, chip_x + chip_w, chip_y + chip_h], fill=chip_bg, outline=chip_border, width=1)

        # 텍스트 그리기
        draw.text((chip_x + 6, chip_y + 2), label_text, fill=chip_text_color, font=font)

    # 저장
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    img.save(out_path, "JPEG", quality=90)
    return out_path


def annotate_image_with_risk_badge(
    image_path: str,
    detections: List[Dict[str, Any]],
    out_path: str,
    risk_level: Optional[str] = None,
    font_size: int = 14,
) -> str:
    """주석본 + 위험도 배지를 추가.

    위험 검출 시 이미지 상단 중앙에 대형 경보 배지를 추가한다.
    """
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arial.ttf", font_size)
        large_font = ImageFont.truetype("arial.ttf", font_size + 8)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
            large_font = ImageFont.truetype("DejaVuSans.ttf", font_size + 8)
        except Exception:
            font = ImageFont.load_default()
            large_font = font

    has_risk = any(det.get("label", "") in RISK_LABELS for det in detections)

    # 박스·칩 주석
    for det in detections:
        label = det.get("label", "")
        conf = det.get("conf", 0.0)
        box = det.get("box", [0, 0, 0, 0])
        if len(box) != 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in box]

        is_risk = label in RISK_LABELS

        if is_risk:
            box_color = (255, 0, 0)
            box_width = 3
            chip_bg = (255, 200, 200)
            chip_text_color = (0, 0, 0)
            chip_border = (200, 0, 0)
        else:
            box_color = (255, 255, 255)
            box_width = 2
            chip_bg = (255, 255, 255)
            chip_text_color = (0, 0, 0)
            chip_border = (180, 180, 180)

        draw.rectangle([x1, y1, x2, y2], outline=box_color, width=box_width)

        label_text = f"{label} {conf:.0%}"
        bbox = draw.textbbox((0, 0), label_text, font=font)
        chip_w = bbox[2] - bbox[0] + 12
        chip_h = bbox[3] - bbox[1] + 8

        chip_x = x1
        chip_y = max(0, y1 - chip_h - 4)

        draw.rectangle([chip_x, chip_y, chip_x + chip_w, chip_y + chip_h], fill=chip_bg, outline=chip_border, width=1)
        draw.text((chip_x + 6, chip_y + 2), label_text, fill=chip_text_color, font=font)

    # 위험 검출 시 중앙 대형 경보 배지
    if has_risk:
        w, h = img.size
        # 상단 중앙 1/3 지점에 배지
        badge_w = int(w * 0.7)
        badge_h = 60
        badge_x = (w - badge_w) // 2
        badge_y = int(h * 0.15)

        # 빨강 대형 배지 배경
        draw.rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], fill=(255, 0, 0), outline=(180, 0, 0), width=2)

        # 경보 텍스트
        alert_text = "⚠ 시설 결함(부식) 위험 !!"
        sub_text = "긴급 · 산업안전보건법 제38조 · 즉시 안전조치 · 보수/정비"

        alert_bbox = draw.textbbox((0, 0), alert_text, font=large_font)
        alert_w = alert_bbox[2] - alert_bbox[0]
        alert_x = badge_x + (badge_w - alert_w) // 2
        alert_y = badge_y + 8
        draw.text((alert_x, alert_y), alert_text, fill=(255, 255, 255), font=large_font)

        sub_bbox = draw.textbbox((0, 0), sub_text, font=font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_x = badge_x + (badge_w - sub_w) // 2
        sub_y = badge_y + 34
        draw.text((sub_x, sub_y), sub_text, fill=(255, 255, 255), font=font)

    # 저장
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    img.save(out_path, "JPEG", quality=90)
    return out_path
