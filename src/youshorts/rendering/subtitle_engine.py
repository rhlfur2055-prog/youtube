# 변경 사유: 레퍼런스 채널(김준표/똘킹/군림보) 스타일 자막으로 완전 교체
# - 화면 정중앙, 80px ExtraBold, 두꺼운 검정 테두리 4px
# - 배경 박스 제거 (텍스트만 선명하게)
# - 핵심 단어 색상 강조: 숫자=노란색, 감정=빨간색, 인물/장소=하늘색
# - 그림자 효과 추가 (3,3 오프셋, 블러 5px)
"""고급 자막 렌더링 엔진 v4.0 (레퍼런스 채널 스타일).

화면 정중앙 80px ExtraBold, 두꺼운 검정 테두리,
핵심 단어 색상 강조 (숫자=노란색, 감정=빨간색, 인물=하늘색).
배경 박스 없이 텍스트만 선명하게 표시합니다.
"""

from __future__ import annotations

import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from youshorts.config.constants import (
    BOTTOM_BAR_COLOR,
    BOTTOM_BAR_HEIGHT,
    BOTTOM_BAR_OPACITY,
    CHANNEL_FONT_SIZE,
    COLOR_CYAN,
    COLOR_GOLD,
    COLOR_RED,
    COLOR_WHITE,
    MAX_CHARS_PER_LINE,
    MAX_LINES,
    OUTLINE_COLOR,
    OUTLINE_WIDTH,
    SUBTITLE_FONT_SIZE,
    TITLE_BAR_COLOR,
    TITLE_BAR_HEIGHT,
    TITLE_BAR_OPACITY,
    TITLE_FONT_SIZE,
)
from youshorts.config.settings import get_settings
from youshorts.utils.fonts import load_font


# ============================================================
# 핵심 단어 색상 강조 (레퍼런스 채널 스타일)
# ============================================================

# 숫자 패턴 → 노란색 (#FFD700)
COLOR_NUMBER = (255, 215, 0)

# 감정/강조 단어 → 빨간색 (#FF4444)
COLOR_EMOTION = (255, 68, 68)

# 인물명/장소명 → 하늘색 (#00BFFF)
COLOR_PROPER_NOUN = (0, 191, 255)

# 감정 키워드 목록 (빨간색으로 강조)
EMOTION_KEYWORDS = [
    "미쳤", "소름", "대박", "충격", "ㅋㅋ", "ㄹㅇ", "실화",
    "논란", "폭로", "경악", "빡치", "역대급", "레전드", "개",
    "헐", "와", "진짜", "반전", "파문", "위기", "긴급",
    "속보", "발칵", "화제", "폭발", "최악", "최고", "극혐",
    "존맛", "꿀잼", "노잼", "소오름", "오지", "미친",
    "쩔", "간다", "뒤집어", "터졌", "깜짝", "놀랍",
]


def _wrap_text(
    text: str,
    max_chars: int = MAX_CHARS_PER_LINE,
    max_lines: int = MAX_LINES,
) -> str:
    """텍스트를 최대 8글자/줄, 최대 2줄로 줄바꿈합니다."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        if len(test.replace(" ", "")) <= max_chars:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    return "\n".join(lines) if lines else text


def _get_word_color(
    word: str,
    keywords: list[str],
    highlight: str = "",
    highlight_color_override: tuple[int, int, int] | None = None,
) -> tuple[int, int, int]:
    """단어의 강조 색상을 결정합니다.

    우선순위:
    1. highlight 단어 → 강조색 (기본 노란색, 오버라이드 가능)
    2. 숫자/통계 (%, 억, 만, 원) → 강조색
    3. 감정 키워드 → 빨간색
    4. keywords 리스트에 포함 → 하늘색
    5. 기본 → 흰색

    Args:
        word: 분석할 단어.
        keywords: 대본에서 강조할 키워드 리스트.
        highlight: 특별 강조 단어.
        highlight_color_override: 강조 색상 오버라이드 (AI 탐지 회피).

    Returns:
        RGB 색상 튜플.
    """
    clean_word = word.strip(".,!?~…()[]{}\"' ")
    hl_color = highlight_color_override if highlight_color_override else COLOR_NUMBER

    # 1. highlight 매칭 → 강조색
    if highlight and highlight in clean_word:
        return hl_color

    # 2. 숫자/통계 패턴 → 강조색
    if re.search(r'\d', clean_word):
        return hl_color
    number_suffixes = ["억", "만", "원", "천", "백", "조", "명", "개", "건", "배"]
    for suffix in number_suffixes:
        if clean_word.endswith(suffix) and len(clean_word) > 1:
            return hl_color

    # 3. 감정 키워드 → 빨간색
    for ek in EMOTION_KEYWORDS:
        if ek in clean_word:
            return COLOR_EMOTION

    # 4. keywords 매칭 → 하늘색
    for kw in keywords:
        if kw in clean_word or clean_word in kw:
            return COLOR_PROPER_NOUN

    # 5. 기본 → 흰색
    return COLOR_WHITE


def create_subtitle_image(
    text: str,
    keywords: list[str] | None = None,
    color_idx: int = 0,
    is_hook: bool = False,
    section: str = "content",
    emotion: str = "",
    highlight: str = "",
    font_size_override: int | None = None,
    highlight_color_override: tuple[int, int, int] | None = None,
) -> np.ndarray:
    """레퍼런스 채널 스타일 자막 이미지를 생성합니다.

    - 70~90px ExtraBold (랜덤), 두꺼운 검정 테두리 4px
    - 배경 박스 없음 (텍스트만 선명하게)
    - 핵심 단어별 색상 강조 (랜덤 강조색 지원)
    - 그림자 효과 (검정, 오프셋 3px, 블러)

    Args:
        text: 자막 텍스트.
        keywords: 강조할 키워드 리스트.
        color_idx: 색상 인덱스 (미사용, 호환용).
        is_hook: 도입부 여부.
        section: 현재 섹션 이름.
        emotion: 감정 태그.
        highlight: 강조할 핵심 단어.
        font_size_override: 폰트 크기 오버라이드 (AI 탐지 회피).
        highlight_color_override: 강조 색상 오버라이드 (AI 탐지 회피).

    Returns:
        RGBA numpy 배열.
    """
    if keywords is None:
        keywords = []

    # highlight가 있으면 keywords에 자동 추가
    if highlight and highlight not in keywords:
        keywords = [highlight] + keywords

    settings = get_settings()
    video_width = settings.video_width

    # 줄바꿈 (최대 8글자/줄, 2줄)
    wrapped = _wrap_text(text)

    # 폰트 크기 (기본 80px, 랜덤 오버라이드 가능)
    effective_font_size = font_size_override if font_size_override else SUBTITLE_FONT_SIZE
    font = load_font(effective_font_size)
    ow = OUTLINE_WIDTH  # 4px 테두리

    # 텍스트 크기 측정
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = wrapped.split("\n")
    line_sizes = []
    for line in lines:
        bbox = dummy.textbbox((0, 0), line, font=font)
        line_sizes.append((bbox[2] - bbox[0], bbox[3] - bbox[1]))

    max_tw = max(s[0] for s in line_sizes)
    line_gap = 16  # 줄 간격 16px
    total_th = sum(s[1] for s in line_sizes) + (len(lines) - 1) * line_gap

    # 이미지 크기 (좌우 여백 충분히)
    shadow_offset = 3
    img_w = video_width
    img_h = total_th + ow * 2 + shadow_offset + 20

    # 그림자 레이어
    shadow_img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_img)

    # 메인 레이어
    main_img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    main_draw = ImageDraw.Draw(main_img)

    # 각 줄을 단어별로 렌더링
    y_cursor = ow + 5

    for line_idx, line in enumerate(lines):
        words = line.split(" ")
        # 전체 줄 너비 계산 (가운데 정렬용)
        line_w, line_h = line_sizes[line_idx]
        x_start = (img_w - line_w) // 2

        # 단어별 색상 결정 및 렌더링
        x_cursor = x_start

        for word_idx, word in enumerate(words):
            if not word:
                continue

            # 단어 + 공백 텍스트
            display_word = word
            if word_idx < len(words) - 1:
                display_word += " "

            word_bbox = dummy.textbbox((0, 0), display_word, font=font)
            word_w = word_bbox[2] - word_bbox[0]

            # 단어 색상 결정
            word_color = _get_word_color(word, keywords, highlight, highlight_color_override)

            # 그림자 (검정, 오프셋 3px)
            shadow_draw.text(
                (x_cursor + shadow_offset, y_cursor + shadow_offset),
                display_word, font=font, fill=(0, 0, 0, 160),
            )

            # 검정 외곽선 (4px 두께)
            for dx in range(-ow, ow + 1):
                for dy in range(-ow, ow + 1):
                    if dx * dx + dy * dy <= ow * ow + 1:
                        main_draw.text(
                            (x_cursor + dx, y_cursor + dy),
                            display_word, font=font,
                            fill=OUTLINE_COLOR + (255,),
                        )

            # 메인 텍스트 (색상 적용)
            main_draw.text(
                (x_cursor, y_cursor),
                display_word, font=font,
                fill=word_color + (255,),
            )

            x_cursor += word_w

        y_cursor += line_sizes[line_idx][1] + line_gap

    # 그림자에 블러 적용
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=3))

    # 레이어 합성: 그림자 → 메인 텍스트
    result = Image.alpha_composite(shadow_img, main_img)

    return np.array(result)


def create_title_bar(
    title: str,
    font_size_override: int | None = None,
    opacity_override: float | None = None,
) -> np.ndarray:
    """상단 고정 타이틀 바를 생성합니다.

    반투명 검은색 배경에 쇼츠 제목을 표시합니다.

    Args:
        title: 표시할 제목.
        font_size_override: 폰트 크기 오버라이드 (AI 탐지 회피).
        opacity_override: 투명도 오버라이드 0.0~1.0 (AI 탐지 회피).

    Returns:
        RGBA numpy 배열.
    """
    settings = get_settings()
    video_width = settings.video_width
    bar_height = 100  # 약간 줄임 (120 → 100)

    # 투명도 랜덤화 (기본 0.7)
    bar_opacity = opacity_override if opacity_override is not None else 0.7

    img = Image.new("RGBA", (video_width, bar_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 반투명 배경
    draw.rectangle(
        [(0, 0), (video_width, bar_height)],
        fill=TITLE_BAR_COLOR + (int(255 * bar_opacity),),
    )

    # 하단 페이드아웃
    for i in range(15):
        alpha = int(255 * bar_opacity) - int(255 * bar_opacity * i / 15)
        draw.rectangle(
            [(0, bar_height - 15 + i), (video_width, bar_height - 14 + i)],
            fill=TITLE_BAR_COLOR + (max(0, alpha),),
        )

    # 제목 텍스트 (폰트 크기 랜덤화 가능)
    title_font_size = font_size_override if font_size_override else int(SUBTITLE_FONT_SIZE * 0.8)
    font = load_font(title_font_size)
    display = title[:25]

    bbox = draw.textbbox((0, 0), display, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (video_width - tw) // 2
    y = (bar_height - th) // 2

    # 외곽선 3px
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            if dx * dx + dy * dy <= 9:
                draw.text((x + dx, y + dy), display, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), display, font=font, fill=COLOR_WHITE + (255,))

    return np.array(img)


def create_bottom_bar(channel_name: str | None = None) -> np.ndarray:
    """하단 채널명/로고 바를 생성합니다.

    Args:
        channel_name: 채널 이름 (None이면 설정값 사용).

    Returns:
        RGBA numpy 배열.
    """
    settings = get_settings()
    video_width = settings.video_width
    if channel_name is None:
        channel_name = settings.channel_name

    img = Image.new("RGBA", (video_width, BOTTOM_BAR_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rectangle(
        [(0, 0), (video_width, BOTTOM_BAR_HEIGHT)],
        fill=BOTTOM_BAR_COLOR + (BOTTOM_BAR_OPACITY,),
    )

    # 상단 페이드인
    for i in range(20):
        alpha = BOTTOM_BAR_OPACITY - int(BOTTOM_BAR_OPACITY * i / 20)
        draw.rectangle(
            [(0, i), (video_width, i + 1)],
            fill=BOTTOM_BAR_COLOR + (alpha,),
        )

    font = load_font(CHANNEL_FONT_SIZE)
    text = f"@{channel_name}"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (video_width - tw) // 2
    y = (BOTTOM_BAR_HEIGHT - th) // 2 + 10

    draw.text((x, y), text, font=font, fill=COLOR_WHITE + (200,))

    small_font = load_font(18)
    ai_text = "AI tools assisted"
    bbox2 = draw.textbbox((0, 0), ai_text, font=small_font)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(
        ((video_width - tw2) // 2, y + th + 4),
        ai_text,
        font=small_font,
        fill=(180, 180, 180, 150),
    )

    return np.array(img)


def get_section_for_time(time_sec: float, total_duration: float) -> str:
    """시간대에 따른 섹션을 구분합니다.

    Args:
        time_sec: 현재 시간 (초).
        total_duration: 전체 길이 (초).

    Returns:
        섹션 이름 (hook/content/opinion/twist/conclusion).
    """
    ratio = time_sec / total_duration
    if ratio < 0.12:
        return "hook"
    elif ratio < 0.45:
        return "content"
    elif ratio < 0.62:
        return "opinion"
    elif ratio < 0.78:
        return "twist"
    else:
        return "conclusion"
