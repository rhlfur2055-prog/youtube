# 변경 사유: BGM_VOLUME 제거(settings로 이동), 프로그레스 바/자막 관련 상수 추가
"""프로젝트 전역 상수 정의.

해상도, 폰트, 색상, 이모지 맵 등 변경되지 않는 값들을 정의합니다.
"""

from __future__ import annotations

# ── Font ──
FONT_SIZE_MAX: int = 90
FONT_SIZE_MIN: int = 60
# 변경 사유: 레퍼런스 채널(김준표/똘킹/군림보) 스타일 - 화면 너비 7~8% = 약 80px
SUBTITLE_FONT_SIZE: int = 80
# 변경 사유: 한 번에 표시 글자 수 최대 8~10자 (2줄 이내, 가독성 극대화)
MAX_CHARS_PER_LINE: int = 8
MAX_LINES: int = 2
WORDS_PER_GROUP: int = 2

# ── Subtitle ──
SUBTITLE_MARGIN: int = 80
# 변경 사유: 레퍼런스 채널 스타일 - 두꺼운 검정 테두리 4px
OUTLINE_WIDTH: int = 4
# 변경 사유: 자막 위치 - 화면 세로 35~55% 영역 (정중앙~약간 위)
SUBTITLE_Y_RATIO: float = 0.45
SUBTITLE_BG_OPACITY: int = 0
SUBTITLE_BG_PADDING: int = 20
SUBTITLE_BG_RADIUS: int = 0

# ── Colors (RGB) ──
COLOR_GOLD: tuple[int, int, int] = (255, 215, 0)
COLOR_WHITE: tuple[int, int, int] = (255, 255, 255)
COLOR_RED: tuple[int, int, int] = (255, 68, 68)
COLOR_CYAN: tuple[int, int, int] = (0, 220, 255)
COLOR_GREEN: tuple[int, int, int] = (100, 255, 100)
COLOR_ORANGE: tuple[int, int, int] = (255, 165, 0)
COLOR_PINK: tuple[int, int, int] = (255, 105, 180)
COLOR_PURPLE: tuple[int, int, int] = (180, 100, 255)
OUTLINE_COLOR: tuple[int, int, int] = (0, 0, 0)

SUBTITLE_BG_COLOR: tuple[int, int, int] = (0, 0, 0)

KEYWORD_COLORS: list[tuple[int, int, int]] = [
    COLOR_RED, COLOR_CYAN, COLOR_GREEN, COLOR_ORANGE, COLOR_PINK, COLOR_PURPLE,
]

# ── Background ──
# 변경 사유: 레퍼런스 채널 스타일 - 4~6초 하드컷 전환
TRANSITION_INTERVAL: int = 5  # 4-6초 범위 중앙값
CROSSFADE_DURATION: float = 0.0  # 하드컷 (페이드 없이 바로 전환)
BG_BLUR_RADIUS: int = 0  # 블러 제거 (만족감 배경은 선명해야 함)
BG_DARKEN_OPACITY: float = 0.25  # 어둡게 25%만 (배경이 잘 보여야 함)

# ── Ken Burns ──
KEN_BURNS_ZOOM_PER_5SEC: float = 0.04  # 줌 효과 강화 (4%)

# ── Title Bar ──
TITLE_BAR_HEIGHT: int = 120
TITLE_BAR_COLOR: tuple[int, int, int] = (0, 0, 0)
TITLE_BAR_OPACITY: int = 200
TITLE_FONT_SIZE: int = 36

# ── Bottom Bar ──
BOTTOM_BAR_HEIGHT: int = 100
BOTTOM_BAR_COLOR: tuple[int, int, int] = (0, 0, 0)
BOTTOM_BAR_OPACITY: int = 180
CHANNEL_FONT_SIZE: int = 28

# ── Progress Bar (top thin line) ──
PROGRESS_BAR_HEIGHT: int = 3
PROGRESS_BAR_COLOR: tuple[int, int, int] = COLOR_ORANGE

# ── Emoji Map ──
EMOJI_MAP: dict[str, str] = {
    "중요": "\u26a0\ufe0f",
    "위험": "\u26a0\ufe0f",
    "주의": "\u26a0\ufe0f",
    "꿀팁": "\U0001f4a1",
    "팁": "\U0001f4a1",
    "방법": "\U0001f4a1",
    "비밀": "\U0001f510",
    "충격": "\U0001f4a5",
    "놀라": "\U0001f62e",
    "돈": "\U0001f4b0",
    "절약": "\U0001f4b0",
    "건강": "\U0001f4aa",
    "운동": "\U0001f3cb\ufe0f",
    "음식": "\U0001f354",
    "시간": "\u23f0",
    "1위": "\U0001f947",
    "최고": "\U0001f947",
    "TOP": "\U0001f3c6",
}
