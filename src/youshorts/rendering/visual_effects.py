# 변경 사유: 프로그레스 바를 상단 3px 라인으로 변경 (video_composer에서 구현), 인포박스 페이드인, TIP 박스 슬라이드인
"""시각 효과 모듈.

인포그래픽 박스, 강조 박스 등
영상에 추가되는 시각 효과를 생성합니다.
프로그레스 바는 video_composer에서 상단 3px 라인으로 구현됩니다.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from youshorts.config.constants import (
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_ORANGE,
    COLOR_RED,
    COLOR_WHITE,
)
from youshorts.config.settings import get_settings
from youshorts.utils.fonts import load_font


def create_info_box(
    title: str,
    value: str,
    unit: str = "",
) -> np.ndarray:
    """인포그래픽 정보 박스를 생성합니다.

    화면 중앙에 큰 숫자와 제목을 표시합니다.

    Args:
        title: 정보 제목.
        value: 주요 수치.
        unit: 단위 문자열.

    Returns:
        RGBA numpy 배열.
    """
    settings = get_settings()
    video_width = settings.video_width
    video_height = settings.video_height

    box_w, box_h = 700, 220
    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    x = (video_width - box_w) // 2
    y = video_height // 3 - box_h // 2

    draw.rounded_rectangle(
        [(x, y), (x + box_w, y + box_h)],
        radius=25,
        fill=(15, 15, 35, 220),
    )
    draw.rounded_rectangle(
        [(x, y), (x + box_w, y + box_h)],
        radius=25,
        outline=COLOR_CYAN + (220,),
        width=3,
    )
    draw.rectangle(
        [(x + 20, y + 10), (x + box_w - 20, y + 15)],
        fill=COLOR_CYAN + (200,),
    )

    title_font = load_font(30)
    bbox = draw.textbbox((0, 0), title, font=title_font)
    ttw = bbox[2] - bbox[0]
    draw.text(
        ((video_width - ttw) // 2, y + 30),
        title, font=title_font, fill=COLOR_WHITE + (230,),
    )

    value_font = load_font(72)
    value_text = f"{value}{unit}"
    bbox2 = draw.textbbox((0, 0), value_text, font=value_font)
    vtw = bbox2[2] - bbox2[0]
    draw.text(
        ((video_width - vtw) // 2, y + 80),
        value_text, font=value_font, fill=COLOR_CYAN + (255,),
    )

    return np.array(img)


def create_highlight_box(text: str, style: str = "tip") -> np.ndarray:
    """강조 박스를 생성합니다.

    Args:
        text: 표시할 텍스트.
        style: 스타일 (warning/tip/info).

    Returns:
        RGBA numpy 배열.
    """
    settings = get_settings()
    video_width = settings.video_width
    video_height = settings.video_height

    styles = {
        "warning": {"bg": (60, 15, 15), "border": COLOR_RED, "icon": "!"},
        "tip": {"bg": (15, 40, 15), "border": COLOR_GREEN, "icon": "TIP"},
        "info": {"bg": (15, 15, 50), "border": COLOR_CYAN, "icon": "i"},
    }
    s = styles.get(style, styles["info"])

    font = load_font(32)
    icon_font = load_font(36)

    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    box_w = video_width - 100
    box_h = 110
    x = 50
    y = video_height // 4

    draw.rounded_rectangle(
        [(x, y), (x + box_w, y + box_h)],
        radius=18,
        fill=s["bg"] + (220,),
    )
    draw.rectangle(
        [(x, y + 6), (x + 7, y + box_h - 6)],
        fill=s["border"] + (255,),
    )
    draw.ellipse(
        [(x + 22, y + 28), (x + 68, y + 74)],
        fill=s["border"] + (210,),
    )
    draw.text((x + 33, y + 32), s["icon"], font=icon_font, fill=COLOR_WHITE + (255,))
    draw.text((x + 82, y + 35), text, font=font, fill=COLOR_WHITE + (245,))

    return np.array(img)


def create_did_you_know_overlay() -> np.ndarray:
    """'알고 계셨나요?' 오버레이 이미지를 생성합니다.

    변경 사유: 한국형 숏츠 스타일 - 도입부 "알고 계셨나요?" 오버레이

    Returns:
        RGBA numpy 배열.
    """
    settings = get_settings()
    video_width = settings.video_width
    video_height = settings.video_height

    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 반투명 배경 박스
    box_w, box_h = 800, 140
    x = (video_width - box_w) // 2
    y = video_height // 4

    draw.rounded_rectangle(
        [(x, y), (x + box_w, y + box_h)],
        radius=25,
        fill=(0, 0, 0, 200),
    )

    # "알고 계셨나요?" 텍스트
    font = load_font(48)
    text = "🤔 알고 계셨나요?"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(
        ((video_width - tw) // 2, y + 40),
        text, font=font, fill=(255, 215, 0, 255),  # 노란색
    )

    return np.array(img)


def generate_visual_effects_for_script(
    script: dict[str, Any],
    total_duration: float,
) -> list[dict[str, Any]]:
    """대본을 분석하여 시각 효과를 생성합니다.

    변경 사유: 한국형 숏츠 스타일 효과 추가
    - "알고 계셨나요?" 오버레이 (도입부)
    - 핵심 수치 인포 박스
    - 크리에이터 분석 TIP 박스

    Args:
        script: 대본 딕셔너리.
        total_duration: 전체 영상 길이 (초).

    Returns:
        효과 리스트 [{image, start, duration}, ...].
    """
    effects: list[dict[str, Any]] = []
    full_script = script.get("full_script", "")

    # 1. "알고 계셨나요?" 오버레이 (도입 3-6초 구간)
    did_you_know_img = create_did_you_know_overlay()
    effects.append({
        "image": did_you_know_img,
        "start": 3.0,
        "duration": 3.0,
    })

    # 2. 숫자 추출 → 핵심 수치 인포 박스
    numbers = re.findall(
        r'(\d+[\d.]*)\s*(%|명|만|억|개|번|가지|위|초|분|시간|일|주|년|원|배)',
        full_script,
    )

    for i, (num, unit) in enumerate(numbers[:3]):
        effect_time = 10 + i * 12
        if effect_time < total_duration - 5:
            img = create_info_box(f"핵심 수치 #{i + 1}", num, unit)
            effects.append({
                "image": img,
                "start": effect_time,
                "duration": 3.5,
            })

    # 3. 크리에이터 의견 강조
    if script.get("creator_opinion"):
        t = 0.52 * total_duration
        img = create_highlight_box("크리에이터 분석", style="tip")
        effects.append({
            "image": img,
            "start": t,
            "duration": 2.5,
        })

    return effects
