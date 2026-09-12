#!/usr/bin/env python3
"""
make_fixtures.py — M2 검수용 합성 fixture 4종을 PIL로 생성한다.

설계:
- 캔버스: A4@150dpi = 1240 x 1754 픽셀
- 본문 폰트: 맑은고딕 24px
- 참고문헌 폰트: 맑은고딕 22px
- 줄바꿈: 줄당 60~65자 목표 (문자 수 + 픽셀 폭 하이브리드)
- 4개 fixture 모두 동일 내용·동일 서지
- fixture_1col의 2번 항목(Devlin)은 DOI가 줄바꿈에 걸치도록 의도적 유지 (줄 병합 검증용)
"""

import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FIXTURES_DIR = Path("tests/fixtures")
CACHE_DIR = Path("tests/fixtures/cache")

# ── 페이지/레이아웃 ──────────────────────────────────────────────────────────
PAGE_W, PAGE_H = 1240, 1754          # A4 @ 150dpi
MARGIN = 120
CONTENT_W = PAGE_W - 2 * MARGIN      # 1000px

# ── 폰트 ─────────────────────────────────────────────────────────────────────
FONT_PATHS = [
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

FONT = None
FONT_SMALL = None
FONT_APA = None
for fp in FONT_PATHS:
    if os.path.exists(fp):
        try:
            FONT = ImageFont.truetype(fp, 24)     # 본문
            FONT_SMALL = ImageFont.truetype(fp, 22)  # 참고문헌 (fixture_1col, fixture_2col_bracket, fixture_2page)
            FONT_APA = ImageFont.truetype(fp, 20)    # APA 참고문헌 (fixture_apa)
            break
        except Exception:
            continue

if FONT is None:
    FONT = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()
    print("경고: 시스템 폰트를 찾지 못해 기본 폰트를 사용합니다.")


# ── 유틸 ─────────────────────────────────────────────────────────────────────

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
    """
    문자 수(max_chars)와 픽셀 폭(max_width)을 동시에 존중하는 하이브리드 줄바꿈.
    단어 경계(공백)에서만 분할한다.
    """
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


def draw_wrapped_hanging(draw, text, x_hang, x_normal, y, max_chars, max_width_normal, font,
                 color=(0, 0, 0), line_height=30):
    """
    APA 저자-연도형 내어쓰기(hanging indent)용 wrapped 텍스트.
    첫 줄은 x_hang(예: 90), 이어지는 줄은 x_normal(예: MARGIN=120)에 그린다.
    줄 분할은 max_width_normal 기준으로 하되, 첫 줄은 실제 더 넓게 써도 무방하다.
    """
    lines = wrap_text(draw, text, max_chars, max_width_normal, font)
    for i, line in enumerate(lines):
        if i == 0:
            draw.text((x_hang, y), line, font=font, fill=color)
        else:
            draw.text((x_normal, y), line, font=font, fill=color)
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


# ── Fixture 1: 1단 번호형 ─────────────────────────────────────────────────────

def make_fixture_1col():
    """1단 번호형: 본문 + 참고문헌 6건 (DOI 4, arXiv 1, 한국어 1).

    2번 항목(Devlin)은 DOI가 '10.' / '18653/v1/n19-1423'으로 줄바꿈되도록
    명시적으로 분할하여 그린다 (E9 줄 병합 검증용).
    """
    img = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = MARGIN
    body_text = (
        "이 연구는 트랜스포머 아키텍처의 효율성을 분석한다. "
        "Vorontsov et al. (2024)는 대규모 언어 모델의 스케일링 법칙을 제시하였고, "
        "Devlin et al. (2019)은 BERT를 통해 사전학습의 효과를 입증하였다. "
        "Vaswani et al. (2017)은 Attention is All You Need에서 트랜스포머를 처음 제안하였으며, "
        "Brown et al. (2020)은 GPT-3의 Few-shot 성능을 보고하였다. "
        "국내에서는 김현우 및 이영희 (2023)가 한국어 문장 분류 모델을 연구하였다."
    )
    y = draw_wrapped(draw, body_text, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 24

    y = draw_text_centered(draw, "References", y, FONT, color=(0, 0, 160))
    y += 12

    # 일반 항목은 wrap으로 그림
    refs_normal = [
        # 1. DOI (arXiv ID 포함)
        "1. Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., "
        "Kaiser, U., Polosukhin, I. (2017). Attention is all you need. "
        "Advances in Neural Information Processing Systems, 30. "
        "DOI: 10.48550/arXiv.1706.03762",
        # 3. arXiv만
        "3. Liu, Y., Ott, M., Goyal, N., Du, J., Joshi, M., Chen, D., Levy, O., "
        "Lewis, M., Zettlemoyer, S., Stoyanov, V. (2019). RoBERTa: A robustly optimized "
        "BERT pretraining approach. arXiv: 1907.11692",
        # 4. DOI만
        "4. Brown, T. B., Mann, B., Ryder, N., Subbiah, M., Kaplan, J., Dhariwal, P., "
        "Neelakantan, A., et al. (2020). Language models are few-shot learners. "
        "Advances in Neural Information Processing Systems, 33, 1877-1901. "
        "DOI: 10.48550/arXiv.2005.14165",
        # 5. 한국어 (식별자 없음)
        "5. 김현우, 이영희 (2023). 한국어 문장 분류를 위한 트랜스포머 기반 모델 연구. "
        "한국어 정보처리학회 논문지, 27(3), 112-128.",
        # 6. DOI만
        "6. Vorontsov, A., Marra, F., Pufal, J. (2024). Scaling laws for large language models. "
        "Journal of Machine Learning Research, 25(1), 1-30. "
        "DOI: 10.1145/3627673.3679215",
    ]

    for ref in refs_normal:
        y = draw_wrapped(draw, ref, MARGIN, y, 60, CONTENT_W, FONT_SMALL, line_height=30)
        y += 6

    # 2번 항목: DOI가 줄바꿈에 걸치도록 명시적 분할
    #   Line 1: ...DOI: 10.
    #   Line 2: 18653/v1/n19-1423
    ref2_lines = [
        "2. Devlin, J., Chang, M. W., Lee, K., Toutanova, K. (2019). BERT: Pre-training of deep",
        "bidirectional transformers for language understanding. Proceedings of NAACL-HLT. DOI: 10.",
        "18653/v1/n19-1423",
    ]
    y = draw_explicit_lines(draw, ref2_lines, MARGIN, y, FONT_SMALL, line_height=30)
    y += 6

    path_pdf = FIXTURES_DIR / "fixture_1col.pdf"
    img.save(path_pdf, "PDF", resolution=150.0)
    print(f"fixture_1col 저장: {path_pdf}")
    path_png = FIXTURES_DIR / "fixture_1col.png"
    img.save(path_png, "PNG")
    print(f"fixture_1col 저장: {path_png}")
    return path_pdf


# ── Fixture 2: 2단 대괄호형 ───────────────────────────────────────────────────

def make_fixture_2col_bracket():
    """2단 대괄호형: 좌단 본문+[1][2], 우단 본문+[3][4].

    각 단 너비 ≈ 470px. 줄당 문자는 단 너비에 맞춰 자동 제한.
    """
    img = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    half_w = CONTENT_W // 2
    gap = 40
    left_x = MARGIN
    right_x = MARGIN + half_w + gap
    col_w = half_w - 20   # ≈ 470px

    y = MARGIN

    # 좌측 본문
    left_body = (
        "본 연구에서는 여러 참고문헌을 검토하였다. 특히 [1]과 [2]의 연구 방법이 "
        "중요한 시사점을 제공한다."
    )
    y_left = draw_wrapped(draw, left_body, left_x, y, 38, col_w, FONT, line_height=32)
    y_left += 10

    # 좌측 References 헤딩
    y_left = draw_text_centered(draw, "References", y_left, FONT,
                                 page_w=half_w, color=(0, 0, 160))
    y_left += 8

    refs_left = [
        # [1] DOI
        "[1] Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., "
        "Kaiser, U., Polosukhin, I. (2017). Attention is all you need. "
        "Advances in Neural Information Processing Systems, 30. "
        "DOI: 10.48550/arXiv.1706.03762",
        # [2] arXiv
        "[2] Liu, Y., Ott, M., Goyal, N., Du, J., Joshi, M., Chen, D., Levy, O., "
        "Lewis, M., Zettlemoyer, S., Stoyanov, V. (2019). RoBERTa: A robustly optimized "
        "BERT pretraining approach. arXiv: 1907.11692",
    ]
    for ref in refs_left:
        y_left = draw_wrapped(draw, ref, left_x, y_left, 60, col_w, FONT_SMALL, line_height=30)
        y_left += 4

    # 우측 본문
    right_y = MARGIN
    right_body = (
        "또한 최근 연구 [3]과 [4]는 대규모 언어 모델의 스케일링 법칙을 다루고 있다. "
        "이러한 배경 하에서 본 실험을 수행하였다."
    )
    right_y = draw_wrapped(draw, right_body, right_x, right_y, 38, col_w, FONT, line_height=32)
    right_y += 10

    # 우측 References 헤딩
    right_y = draw_text_centered(draw, "References", right_y, FONT,
                                  page_w=half_w, color=(0, 0, 160))
    right_y += 8

    refs_right = [
        # [3] DOI
        "[3] Devlin, J., Chang, M. W., Lee, K., Toutanova, K. (2019). BERT: Pre-training of deep "
        "bidirectional transformers for language understanding. "
        "Proceedings of NAACL-HLT. DOI: 10.18653/v1/n19-1423",
        # [4] 식별자 없음
        "[4] Brown, T. B., Mann, B., Ryder, N., Subbiah, M., Kaplan, J., Dhariwal, P., "
        "Neelakantan, A., et al. (2020). Language models are few-shot learners. "
        "Advances in Neural Information Processing Systems, 33, 1877-1901.",
    ]
    for ref in refs_right:
        right_y = draw_wrapped(draw, ref, right_x, right_y, 60, col_w, FONT_SMALL, line_height=30)
        right_y += 4

    path_pdf = FIXTURES_DIR / "fixture_2col_bracket.pdf"
    img.save(path_pdf, "PDF", resolution=150.0)
    print(f"fixture_2col_bracket 저장: {path_pdf}")
    path_png = FIXTURES_DIR / "fixture_2col_bracket.png"
    img.save(path_png, "PNG")
    print(f"fixture_2col_bracket 저장: {path_png}")
    return path_pdf


# ── Fixture 3: APA 저자-연도형 ─────────────────────────────────────────────────

def make_fixture_apa():
    """APA 저자-연도형: 표지 없음 5건, 본문에 He et al. (2016) 함정 포함.

    DOI 3개, arXiv 1개, 한국어 1개.
    """
    img = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = MARGIN
    body_text = (
        "최근 자연어 처리 분야에서는 트랜스포머 기반 모델이 주류를 이루고 있다. "
        "He et al. (2016)은 심층 신경망의 효율성을 분석하였으나, 본 연구의 참고문헌 목록에는 "
        "포함되지 않았다. Vaswani et al. (2017)은 Attention 메커니즘을 제안하였고, "
        "Devlin et al. (2019)은 BERT를 소개하였다. Brown et al. (2020)은 GPT-3를 보고하였으며, "
        "Liu et al. (2019)은 RoBERTa를 통해 성능 개선을 입증하였다."
    )
    y = draw_wrapped(draw, body_text, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 20

    y = draw_text_centered(draw, "References", y, FONT, color=(0, 0, 160))
    y += 10

    refs = [
        # 1. DOI
        "Brown, T. B., Mann, B., Ryder, N., Subbiah, M., Kaplan, J., Dhariwal, P., "
        "Neelakantan, A., et al. (2020). Language models are few-shot learners. "
        "Advances in Neural Information Processing Systems, 33, 1877-1901. "
        "DOI: 10.48550/arXiv.2005.14165",
        # 2. DOI
        "Devlin, J., Chang, M. W., Lee, K., Toutanova, K. (2019). BERT: Pre-training of deep "
        "bidirectional transformers for language understanding. "
        "Proceedings of NAACL-HLT. DOI: 10.18653/v1/n19-1423",
        # 3. arXiv
        "Liu, Y., Ott, M., Goyal, N., Du, J., Joshi, M., Chen, D., Levy, O., "
        "Lewis, M., Zettlemoyer, S., Stoyanov, V. (2019). RoBERTa: A robustly optimized "
        "BERT pretraining approach. arXiv: 1907.11692",
        # 4. DOI
        "Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., "
        "Kaiser, U., Polosukhin, I. (2017). Attention is all you need. "
        "Advances in Neural Information Processing Systems, 30. "
        "DOI: 10.48550/arXiv.1706.03762",
        # 5. 한국어 (식별자 없음)
        "김현우, 이영희 (2023). 한국어 문장 분류를 위한 트랜스포머 기반 모델 연구. "
        "한국어 정보처리학회 논문지, 27(3), 112-128.",
    ]

    for ref in refs:
        y = draw_wrapped_hanging(draw, ref, 90, 132, y, 66, CONTENT_W, FONT_APA, line_height=34)
        y += 16

    path_pdf = FIXTURES_DIR / "fixture_apa.pdf"
    img.save(path_pdf, "PDF", resolution=150.0)
    print(f"fixture_apa 저장: {path_pdf}")
    path_png = FIXTURES_DIR / "fixture_apa.png"
    img.save(path_png, "PNG")
    print(f"fixture_apa 저장: {path_png}")
    return path_pdf


# ── Fixture 4: 2페이지 (페이지 경계) ───────────────────────────────────────────

def make_fixture_2page():
    """
    2페이지: 항목 4번(Liu et al.)이 p1끝~p2첫머리에 걸침.
    arXiv 식별자는 p2쪽. 러닝헤더(header 범주)+쪽번호 푸터(footer 범주).
    DOI 4개, arXiv 1개, 한국어 1개.
    """
    # --- 페이지 1 ---
    img1 = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw1 = ImageDraw.Draw(img1)

    y = MARGIN
    body1 = (
        "이 논문은 대규모 언어 모델의 발전 과정을 정리한다. "
        "Vaswani et al. (2017)의 Attention 메커니즘은 후속 연구의 기초가 되었다. "
        "이후 BERT (Devlin et al., 2019)와 GPT 시리즈 (Brown et al., 2020)가 등장하면서 "
        "자연어 처리 성능이 크게 향상되었다."
    )
    y = draw_wrapped(draw1, body1, MARGIN, y, 63, CONTENT_W, FONT, line_height=32)
    y += 16

    y = draw_text_centered(draw1, "References", y, FONT, color=(0, 0, 160))
    y += 8

    refs_p1 = [
        "1. Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., "
        "Kaiser, U., Polosukhin, I. (2017). Attention is all you need. "
        "Advances in Neural Information Processing Systems, 30. "
        "DOI: 10.48550/arXiv.1706.03762",
        "2. Devlin, J., Chang, M. W., Lee, K., Toutanova, K. (2019). BERT: Pre-training of deep "
        "bidirectional transformers for language understanding. "
        "Proceedings of NAACL-HLT. DOI: 10.18653/v1/n19-1423",
        "3. Brown, T. B., Mann, B., Ryder, N., Subbiah, M., Kaplan, J., Dhariwal, P., "
        "Neelakantan, A., et al. (2020). Language models are few-shot learners. "
        "Advances in Neural Information Processing Systems, 33, 1877-1901. "
        "DOI: 10.48550/arXiv.2005.14165",
        # 4번 항목의 첫 부분만 (나머지는 p2로)
        "4. Liu, Y., Ott, M., Goyal, N., Du, J., Joshi, M., Chen, D., Levy, O., "
        "Lewis, M., Zettlemoyer, S., Stoyanov, V. (2019). RoBERTa: A robustly optimized "
        "BERT pretraining approach.",
    ]
    for ref in refs_p1:
        y = draw_wrapped(draw1, ref, MARGIN, y, 62, CONTENT_W, FONT_SMALL, line_height=30)
        y += 4

    # PNG 먼저 저장 (결합 PDF용)
    png1_path = FIXTURES_DIR / "fixture_2page_p1.png"
    img1.save(png1_path, "PNG")

    # --- 페이지 2 ---
    img2 = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw2 = ImageDraw.Draw(img2)

    # 러닝헤더 (상단)
    header_y = 50
    draw2.text((MARGIN, header_y),
               "Demo Paper — References (continued)",
               font=FONT_SMALL, fill=(120, 120, 120))

    # 쪽번호 푸터 (하단)
    footer_y = PAGE_H - 70
    draw2.text((PAGE_W - MARGIN - 50, footer_y), "- 2 -",
               font=FONT_SMALL, fill=(120, 120, 120))

    y2 = MARGIN + 40

    # p1에서 넘어온 4번 항목의 나머지 (arXiv 식별자 포함)
    ref4_p2 = "arXiv: 1907.11692."
    y2 = draw_wrapped(draw2, ref4_p2, MARGIN, y2, 62, CONTENT_W, FONT_SMALL, line_height=30)
    y2 += 6

    refs_p2 = [
        # 5. 식별자 없음 (저자-연도 패턴만)
        "5. Zhao, W. X., Zhou, K., Li, J., Tang, T., Wang, X., Hou, Y., Min, Y., "
        "Zhang, B., Men, C., Chen, Y. (2023). A survey of large language models. "
        "Transactions of the Association for Computational Linguistics, 11, 1-36.",
        # 6. DOI
        "6. Radford, A., Wu, J., Child, R., Luan, D., Amodei, D., Sutskever, I. (2019). "
        "Language models are unsupervised multitask learners. "
        "OpenAI Technical Report. DOI: 10.48550/arXiv.1901.08843",
        # 7. 한국어 (식별자 없음)
        "7. 김현우, 이영희 (2023). 한국어 문장 분류를 위한 트랜스포머 기반 모델 연구. "
        "한국어 정보처리학회 논문지, 27(3), 112-128.",
    ]
    for ref in refs_p2:
        y2 = draw_wrapped(draw2, ref, MARGIN, y2, 60, CONTENT_W, FONT_SMALL, line_height=30)
        y2 += 4

    png2_path = FIXTURES_DIR / "fixture_2page_p2.png"
    img2.save(png2_path, "PNG")

    # 결합 PDF
    combined_pdf = FIXTURES_DIR / "fixture_2page.pdf"
    imgs = [Image.open(png1_path), Image.open(png2_path)]
    imgs[0].save(combined_pdf, "PDF", resolution=150.0, save_all=True, append_images=imgs[1:])
    print(f"fixture_2page 저장: {combined_pdf}")
    return combined_pdf


# ── 메인 ───────────────────────────────────────────────────────────────────────

def main():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print("=== 합성 fixture 생성 시작 (A4@150dpi, 본문24px/참고문헌22px) ===")
    make_fixture_1col()
    make_fixture_2col_bracket()
    make_fixture_apa()
    make_fixture_2page()
    print("=== fixture 생성 완료 ===")

    for p in sorted(FIXTURES_DIR.glob("*.pdf")):
        print(f"  {p.name} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
