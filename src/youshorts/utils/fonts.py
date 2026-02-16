# 변경 사유: v3.0 FontManager 통합 (fc-list, apt-get, 웹 다운로드, Windows 지원)
"""크로스플랫폼 폰트 감지 및 자동 설치.

Windows, macOS, Linux에서 한국어 폰트를 자동으로 탐색합니다.
v3.0: fc-list 기반 시스템 폰트 검색, apt-get 자동 설치,
웹 다운로드 폴백, NanumSquareRound 우선 사용.
"""

from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from typing import Optional

from PIL import ImageFont

from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

# 선호 한글 폰트 목록 (우선순위 순)
_PREFERRED_FONTS = [
    "NanumSquareRoundB",
    "NanumSquareRoundR",
    "NanumSquareRound",
    "NanumGothicBold",
    "NanumGothic",
    "NotoSansCJK",
    "NotoSansKR",
    "Pretendard",
    "D2Coding",
]

# 플랫폼별 폰트 후보 (정적 경로)
_FONT_CANDIDATES: dict[str, list[str]] = {
    "win32": [
        "C:/Windows/Fonts/NanumSquareRoundB.ttf",
        "C:/Windows/Fonts/NanumSquareRoundR.ttf",
        "C:/Windows/Fonts/NanumSquareRound.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/gulim.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ],
    "darwin": [
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/NanumSquareRoundR.ttf",
        "/Library/Fonts/AppleGothic.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    "linux": [
        "/usr/share/fonts/truetype/nanum/NanumSquareRoundR.ttf",
        "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}

# 나눔스퀘어라운드 다운로드 URL
_NANUM_DOWNLOAD_URL = (
    "https://github.com/nicedoctor/NanumSquareRound/raw/master/NanumSquareRoundR.ttf"
)


def _find_system_font_fclist(bold: bool = False) -> Optional[str]:
    """fc-list를 사용하여 시스템 한글 폰트를 검색합니다 (Linux/macOS).

    Args:
        bold: Bold 폰트 우선 여부.

    Returns:
        폰트 파일 경로 또는 None.
    """
    if sys.platform == "win32":
        return None

    try:
        result = subprocess.run(
            ["fc-list", ":lang=ko", "file"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None

        font_lines = result.stdout.strip().split("\n")
        if not font_lines or font_lines == [""]:
            return None

        # 선호 폰트 순서대로 검색
        preferred = list(_PREFERRED_FONTS)
        if bold:
            # Bold 버전 우선
            preferred = [f + "B" if "Bold" not in f else f for f in preferred] + preferred

        for pref in preferred:
            for line in font_lines:
                path = line.split(":")[0].strip()
                if pref.lower() in path.lower() and os.path.exists(path):
                    return path

        # 아무 한글 폰트라도
        for line in font_lines:
            path = line.split(":")[0].strip()
            if os.path.exists(path) and path.endswith((".ttf", ".otf")):
                return path

    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return None


def _find_system_font_windows(bold: bool = False) -> Optional[str]:
    """Windows에서 레지스트리/경로 기반 폰트를 검색합니다.

    Args:
        bold: Bold 폰트 우선 여부.

    Returns:
        폰트 파일 경로 또는 None.
    """
    if sys.platform != "win32":
        return None

    font_dirs = [
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
        os.path.expanduser("~/.local/share/fonts"),
    ]

    # 선호 폰트 파일명 후보
    if bold:
        filenames = [
            "NanumSquareRoundB.ttf", "NanumSquareRoundEB.ttf",
            "NanumGothicBold.ttf", "malgunbd.ttf",
        ]
    else:
        filenames = [
            "NanumSquareRoundR.ttf", "NanumSquareRound.ttf",
            "NanumGothic.ttf", "malgun.ttf", "malgunbd.ttf",
        ]

    for font_dir in font_dirs:
        if not os.path.isdir(font_dir):
            continue
        for filename in filenames:
            path = os.path.join(font_dir, filename)
            if os.path.exists(path):
                return path

    return None


def _install_nanum_fonts() -> bool:
    """apt-get으로 나눔 폰트를 설치합니다 (Linux only).

    Returns:
        설치 성공 여부.
    """
    if sys.platform == "win32" or sys.platform == "darwin":
        return False

    try:
        logger.info("한글 폰트 설치 중 (NanumSquareRound)...")
        subprocess.run(
            ["apt-get", "install", "-y", "-qq",
             "fonts-nanum", "fonts-nanum-extra"],
            capture_output=True, timeout=30,
        )
        subprocess.run(["fc-cache", "-f"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        logger.debug("apt-get 폰트 설치 실패: %s", e)
        return False


def _download_nanum_font() -> Optional[str]:
    """나눔스퀘어라운드 폰트를 웹에서 다운로드합니다.

    Returns:
        다운로드된 폰트 파일 경로 또는 None.
    """
    if sys.platform == "win32":
        font_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "Microsoft", "Windows", "Fonts",
        )
    else:
        font_dir = os.path.expanduser("~/.local/share/fonts")

    os.makedirs(font_dir, exist_ok=True)
    font_path = os.path.join(font_dir, "NanumSquareRoundR.ttf")

    if os.path.exists(font_path):
        return font_path

    try:
        import requests

        logger.info("나눔스퀘어라운드 폰트 다운로드 중...")
        resp = requests.get(_NANUM_DOWNLOAD_URL, timeout=15)
        if resp.status_code == 200:
            with open(font_path, "wb") as f:
                f.write(resp.content)

            # Linux/macOS에서 폰트 캐시 갱신
            if sys.platform != "win32":
                try:
                    subprocess.run(
                        ["fc-cache", "-f"], capture_output=True, timeout=10,
                    )
                except Exception:
                    pass

            logger.info("폰트 다운로드 완료: %s", font_path)
            return font_path
    except Exception as e:
        logger.debug("폰트 다운로드 실패: %s", e)

    return None


@lru_cache(maxsize=4)
def get_font_path(bold: bool = False) -> str:
    """시스템에 존재하는 가장 좋은 한글 폰트 경로를 반환합니다.

    탐색 순서:
    1. fc-list 시스템 폰트 검색 (Linux/macOS)
    2. Windows 폰트 디렉토리 검색
    3. 정적 경로 후보 확인
    4. apt-get 자동 설치 후 재검색 (Linux)
    5. 웹에서 NanumSquareRound 다운로드
    6. 빈 문자열 (기본 폰트 폴백)

    Args:
        bold: Bold 폰트 우선 여부.

    Returns:
        폰트 파일 경로. 사용 가능한 폰트가 없으면 빈 문자열.
    """
    # 1차: fc-list (Linux/macOS)
    font_path = _find_system_font_fclist(bold)
    if font_path:
        return font_path

    # 2차: Windows 폰트 디렉토리
    font_path = _find_system_font_windows(bold)
    if font_path:
        return font_path

    # 3차: 정적 경로 후보
    platform = sys.platform
    candidates = _FONT_CANDIDATES.get(platform, [])
    if not candidates and platform.startswith("linux"):
        candidates = _FONT_CANDIDATES["linux"]

    for path in candidates:
        if os.path.exists(path):
            return path

    # 4차: apt-get 설치 시도 (Linux)
    if _install_nanum_fonts():
        font_path = _find_system_font_fclist(bold)
        if font_path:
            return font_path

    # 5차: 웹 다운로드
    font_path = _download_nanum_font()
    if font_path:
        return font_path

    return ""


def load_font(
    size: int,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """지정 크기의 폰트를 로드합니다.

    NanumSquareRound를 우선 탐색하고,
    없으면 시스템 한글 폰트 → 자동 설치 → 웹 다운로드 → 기본 폰트 순으로 폴백합니다.

    Args:
        size: 폰트 크기 (px).
        bold: Bold 폰트 사용 여부.

    Returns:
        로드된 폰트 인스턴스.
    """
    font_path = get_font_path(bold)
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except (IOError, OSError):
            pass

    # 모든 후보를 순회 (폴백)
    for candidates in _FONT_CANDIDATES.values():
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                continue

    logger.warning("한글 폰트를 찾을 수 없어 기본 폰트 사용")
    return ImageFont.load_default()
