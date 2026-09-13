#!/usr/bin/env python3
"""
make_demo_doc.py — 가상 사업장 「가온물류센터」 현장점검 보고서 PDF를 PIL로 생성한다.
make_fixtures.py의 폰트·기하(A4@150dpi, 맑은고딕 24px 본문, 22px 참고문헌)를 재사용한다.

심는 내용 (7종 함정):
  (a) 정상 법령 인용 1건   — 「산업안전보건법」 제38조
  (b) 존재하지 않는 조항   — 「산업안전보건법」 제999조
  (c) 적법도급 위험 신호    — 도급인 직원의 직접 작업 지시
  (d) 근거 없는 적법 주장   — '당 현장은 모든 항목에서 적법 도급 기준을 충족한다'
  (e) [사진 1]~[사진 3]    — 사진1 부식 확인(배관), 사진2 정리 양호 주장(하역장, 실제론 적재물 검출됨),
                                사진3 존재하지 않는 사진 참조
  (f) 개인정보 1건          — 전화번호
  (g) 참고문헌 2건          — 실존 arXiv 1 + 가짜 DOI 1
"""

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── 경로 ──────────────────────────────────────────────────────────────────────
DEMO_DIR = Path("assets/demo")
DEMO_DIR.mkdir(parents=True, exist_ok=True)

# ── make_fixtures.py의 폰트·기하 재사용 ──────────────────────────────────────
PAGE_W, PAGE_H = 1240, 1754          # A4 @ 150dpi
MARGIN = 120
CONTENT_W = PAGE_W - 2 * MARGIN      # 1000px

FONT_PATHS = [
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

FONT = None
FONT_SMALL = None
for fp in FONT_PATHS:
    if os.path.exists(fp):
        try:
            FONT = ImageFont.truetype(fp, 24)      # 본문
            FONT_SMALL = ImageFont.truetype(fp, 22)  # 참고문헌
            break
        except Exception:
            continue

if FONT is None:
    FONT = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()
    print("경고: 시스템 폰트를 찾지 못해 기본 폰트를 사용합니다.")


# ── 유틸 (make_fixtures.py와 동일) ────────────────────────────────────────────

def text_size(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except Exception:
        return draw.textlength(text, font=font), 30


def get_text_width(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except Exception:
        return int(draw.textlength(text, font=font))


def draw_text_centered(draw, text, y, font, page_w=PAGE_W, color=(0, 0, 0)):
    w, h = text_size(draw, text, font)
    x = (page_w - w) // 2
    draw.text((x, y), text, font=font, fill=color)
    return y + h


def wrap_text(draw, text, max_chars, max_width, font):
    """문자 수(max_chars)와 픽셀 폭(max_width)을 동시에 존중하는 하이브리드 줄바꿈."""
    words = text.split()
    if not words:
        return []
    lines = []
    cur = ""
    for w in words:
        trial = cur + (" " if cur else "") + w
        if len(trial) > max_chars or get_text_width(draw, trial, font) > max_width:
            if cur:
                lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def draw_wrapped(draw, text, x, y, max_chars, max_width, font,
                 color=(0, 0, 0), line_height=30):
    lines = wrap_text(draw, text, max_chars, max_width, font)
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        _, h = text_size(draw, line, font)
        y += h + 4
    return y


def draw_explicit_lines(draw, lines, x, y, font, color=(0, 0, 0), line_height=30):
    """미리 분할된 줄 목록을 그대로 그린다."""
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        _, h = text_size(draw, line, font)
        y += h + 4
    return y


# ── 보고서 생성 ────────────────────────────────────────────────────────────────

def make_demo_report():
    img = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = MARGIN

    # ── 표지 ──────────────────────────────────────────────────────────────────
    y = draw_text_centered(draw, "현장점검 보고서", y, FONT, color=(0, 51, 102))
    y += 12
    y = draw_text_centered(draw, "가온물류센터", y, FONT, color=(0, 51, 102))
    y += 8
    y = draw_text_centered(draw, "점검일시: 2026년 9월 12일", y, FONT_SMALL, color=(80, 80, 80))
    y += 4
    y = draw_text_centered(draw, "점검자: 김안전 (산업안전보건지도사)", y, FONT_SMALL, color=(80, 80, 80))
    y += 28

    # ── 1. 점검 개요 ──────────────────────────────────────────────────────────
    y = draw_text_centered(draw, "1. 점검 개요", y, FONT, color=(0, 51, 102))
    y += 10

    overview = (
        "본 점검은 가온물류센터의 산업안전보건법 준수 여부를 확인하기 위하여 실시되었다. "
        "점검 범위는 창고동(A동, B동), 하역장, 전기실, 옥외 배관을 포함하며, "
        "도급 작업과 관련된 적법성 검토를 병행하였다."
    )
    y = draw_wrapped(draw, overview, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 20

    # ── 2. 법령 준수 현황 ─────────────────────────────────────────────────────
    y = draw_text_centered(draw, "2. 법령 준수 현황", y, FONT, color=(0, 51, 102))
    y += 10

    law_section = (
        "2.1 「산업안전보건법」 제38조(안전보건관리체제의 구축)에 따라, "
        "당 현장은 안전보건관리책임자를 지정하고 정기적인 안전보건교육을 실시하고 있다. "
        "이는 동법에서 요구하는 안전보건관리체제의 기본 요건을 충족한다."
    )
    y = draw_wrapped(draw, law_section, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 8

    # (b) 존재하지 않는 조항 — 「산업안전보건법」 제999조
    fake_law = (
        "2.2 「산업안전보건법」 제999조(물류창고 특별안전관리)에 따라, "
        "가온물류센터는 물류창고 특별안전관리 구역으로 지정되어 있으며, "
        "분기별 특별안전점검을 시행하고 있다."
    )
    y = draw_wrapped(draw, fake_law, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 8

    # ── 3. 도급 작업 적법성 검토 ─────────────────────────────────────────────
    y = draw_text_centered(draw, "3. 도급 작업 적법성 검토", y, FONT, color=(0, 51, 102))
    y += 10

    # (c) 적법도급 위험 신호 — 도급인 직원의 직접 작업 지시
    risk_sentence = (
        "3.1 하역 작업과 관련하여, 원청인 가온물류센터 직원의 직접 작업 지시로 인하여 "
        "수급인 근로자 A가 포장 라인을 정리하도록 지시받은 사실이 서면으로 확인되었다. "
        "이는 도급인 직원이 수급인 근로자에게 직접 작업 지시를 한 사례로서 "
        "적법도급 요건에 위배될 소지가 있다."
    )
    y = draw_wrapped(draw, risk_sentence, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 8

    # (d) 근거 없는 적법 주장
    false_compliant = (
        "3.2 당 현장은 모든 항목에서 적법 도급 기준을 충족한다. "
        "도급 계약은 명확히 확정되어 있으며, 수급인은 독자적인 사업체로 운영되고 있다. "
        "이에 따라 당 현장의 도급 구조는 완전히 적법하다."
    )
    y = draw_wrapped(draw, false_compliant, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 12

    # ── 4. 현장 사진 참조 ─────────────────────────────────────────────────────
    y = draw_text_centered(draw, "4. 현장 사진 참조", y, FONT, color=(0, 51, 102))
    y += 10

    # (e) [사진 1] — 부식 확인 (배관) — 실제 사진과 일치해야 함
    photo1 = (
        "[사진 1] B동 옥외 배관에서 부식이 확인되어 즉시 보수가 필요한 상태이다. "
        "배관 표면에 적갈색 산화물이 광범위하게 관찰되며, 일부 구간에서는 "
        "부식으로 인한 두께 감소가 우려된다."
    )
    y = draw_wrapped(draw, photo1, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 8

    # (e) [사진 2] — 정리 양호 주장 (하역장) — 실제로는 적재물 검출됨 (함정)
    photo2 = (
        "[사진 2] A동 1층 하역장은 적재물이 정리되어 양호하다. "
        "모든 자재가 designated 구역에 정돈되어 있으며, "
        "통로 확보도 적절히 이루어지고 있다."
    )
    y = draw_wrapped(draw, photo2, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 8

    # (e) [사진 3] — 존재하지 않는 사진 참조 (함정)
    photo3 = (
        "[사진 3] 전기실 내 누전차단기 설치 상태가 양호하며, "
        "모든 분전반에 적절한 표지판이 부착되어 있다. "
        "전기실 바닥은 청결하게 유지되고 있다."
    )
    y = draw_wrapped(draw, photo3, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 12

    # ── 5. 특이사항 ───────────────────────────────────────────────────────────
    y = draw_text_centered(draw, "5. 특이사항", y, FONT, color=(0, 51, 102))
    y += 10

    # (f) 개인정보 — 전화번호
    private_info = (
        "5.1 현장 관계자 문의: 김안전 지도사 (연락처: 010-9876-5432). "
        "추가 확인이 필요한 사항에 대해서는 위 연락처로 문의할 수 있다."
    )
    y = draw_wrapped(draw, private_info, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 8

    # ── 6. 결론 ────────────────────────────────────────────────────────────────
    y = draw_text_centered(draw, "6. 결론", y, FONT, color=(0, 51, 102))
    y += 10

    conclusion = (
        "본 점검 결과, 가온물류센터는 전반적으로 산업안전보건법을 준수하고 있으나, "
        "일부 도급 작업 관련 사항에 대해서는 추가 확인이 필요하다. "
        "특히 법령 제999조에 따른 특별안전관리는 향후 보강이 권장된다."
    )
    y = draw_wrapped(draw, conclusion, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 20

    # ── 참고문헌 ──────────────────────────────────────────────────────────────
    y += 16
    y = draw_text_centered(draw, "참고문헌", y, FONT, color=(0, 0, 160))
    y += 10

    # (g) 참고문헌 2건: 실존 arXiv 1 + 가짜 DOI 1
    ref1 = (
        "1. Smith, J., Johnson, R., Lee, K. (2024). "
        "A survey of safety management systems in logistics warehouses. "
        "arXiv: 2401.12345"
    )
    y = draw_wrapped(draw, ref1, MARGIN, y, 60, CONTENT_W, FONT_SMALL, line_height=30)
    y += 6

    # 가짜 DOI
    ref2 = (
        "2. 가온물류센터 안전관리팀 (2026). "
        "2026년 상반기 물류창고 안전관리 백서. "
        "DOI: 10.9999/fake/logistics-safety-2026"
    )
    y = draw_wrapped(draw, ref2, MARGIN, y, 60, CONTENT_W, FONT_SMALL, line_height=30)
    y += 6

    # ── 저장 ──────────────────────────────────────────────────────────────────
    pdf_path = DEMO_DIR / "demo_report_gaon.pdf"
    img.save(pdf_path, "PDF", resolution=150.0)
    print(f"보고서 저장: {pdf_path}")
    return pdf_path


if __name__ == "__main__":
    pdf = make_demo_report()
    print(f"완료: {pdf}")
