# 변경 사유: yt-dlp 기반 만족감 배경 영상 시스템으로 완전 교체
# 레퍼런스: 김준표, 똘킹, 군림보 스타일 (마인크래프트, 서브웨이서퍼, 요리 등)
"""배경 영상 다운로드 모듈 (v2.0).

yt-dlp로 유튜브에서 "만족감 주는 배경 영상"을 다운로드하고,
data/backgrounds/ 에 카테고리별로 저장합니다.
한 번만 다운로드하면 계속 재사용합니다.

주요 기능:
- yt-dlp 기반 유튜브 배경 영상 자동 다운로드
- 카테고리별 영상 관리 (마인크래프트, 서브웨이서퍼, 요리 등)
- 영상에서 4~6초 단위 랜덤 클립 추출
- Pexels/Pixabay 폴백 (yt-dlp 실패 시)
"""

from __future__ import annotations

import gc
import os
import random
import subprocess
import time
from typing import Any

import numpy as np
import requests
from PIL import Image

from youshorts.config.settings import BG_GRADIENTS_COMMUNITY, Settings, get_settings
from youshorts.security.secrets_manager import SecretsManager
from youshorts.utils.file_handler import ensure_dir
from youshorts.utils.logger import get_logger
from youshorts.utils.retry import retry

logger = get_logger(__name__)


# ============================================================
# 만족감 배경 영상 카테고리 (레퍼런스 채널 스타일)
# ============================================================
# 검색어: Creative Commons / Free to use 키워드 포함
BACKGROUND_CATEGORIES: dict[str, list[str]] = {
    "minecraft_parkour": [
        "minecraft parkour no copyright gameplay",
        "minecraft parkour free to use background",
    ],
    "subway_surfers": [
        "subway surfers gameplay no copyright",
        "subway surfers free to use gameplay",
    ],
    "satisfying": [
        "satisfying soap cutting ASMR compilation",
        "satisfying slime ASMR no copyright",
    ],
    "cooking": [
        "cooking satisfying ASMR no copyright",
        "satisfying cooking compilation free to use",
    ],
    "gta_driving": [
        "GTA V free roam driving gameplay no copyright",
        "GTA free drive gameplay",
    ],
    "city_night": [
        "city night aerial 4K free stock footage",
        "city night drone footage free to use",
    ],
    "typing_asmr": [
        "keyboard typing ASMR satisfying no copyright",
        "mechanical keyboard typing ASMR",
    ],
    "water_flow": [
        "satisfying water flow compilation no copyright",
        "rain window satisfying free footage",
    ],
}

# Pexels 1순위 배경 키워드 (영상마다 랜덤 카테고리 사용)
PEXELS_RANDOM_CATEGORIES: list[str] = [
    "cooking",
    "food",
    "street",
    "city night",
    "rain",
    "ocean",
    "fire",
    "neon",
]

# Pexels 폴백용 범용 배경 키워드 (주제 무관, 항상 고품질 결과)
UNIVERSAL_BACKGROUNDS: list[str] = [
    "city aerial night 4k",
    "cooking close up satisfying",
    "ocean waves drone aerial",
    "rain window close up",
    "highway traffic night timelapse",
    "neon lights city street",
    "coffee shop close up",
    "nature forest aerial drone",
    "sunset clouds timelapse",
    "fireworks celebration night",
]

# Pexels 최소 파일 크기 (2MB 미만은 저품질로 판단)
PEXELS_MIN_FILE_SIZE_MB = 2.0

# 배경 영상 저장 경로
BACKGROUNDS_DIR = os.path.join("data", "backgrounds")


# ============================================================
# yt-dlp 기반 배경 영상 다운로드
# ============================================================

def _get_ytdlp_exe() -> str:
    """yt-dlp 실행 파일 경로를 반환합니다."""
    # Python Scripts 디렉토리에서 yt-dlp 찾기
    import sys
    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
    ytdlp_path = os.path.join(scripts_dir, "yt-dlp.exe")
    if os.path.exists(ytdlp_path):
        return ytdlp_path
    # PATH에서 찾기
    return "yt-dlp"


def download_background_videos(
    categories: list[str] | None = None,
    max_duration: int = 600,  # 최대 10분
    min_duration: int = 120,  # 최소 2분
) -> dict[str, str]:
    """유튜브에서 카테고리별 배경 영상을 다운로드합니다.

    이미 다운로드된 카테고리는 스킵합니다.
    한 번만 실행하면 이후 재사용됩니다.

    Args:
        categories: 다운로드할 카테고리 목록 (None이면 전체).
        max_duration: 최대 영상 길이 (초).
        min_duration: 최소 영상 길이 (초).

    Returns:
        {카테고리: 다운로드된 파일 경로} 딕셔너리.
    """
    ensure_dir(BACKGROUNDS_DIR)
    ytdlp = _get_ytdlp_exe()

    if categories is None:
        categories = list(BACKGROUND_CATEGORIES.keys())

    downloaded: dict[str, str] = {}

    for category in categories:
        cat_dir = os.path.join(BACKGROUNDS_DIR, category)
        ensure_dir(cat_dir)

        # 이미 영상이 있으면 스킵
        existing = [
            f for f in os.listdir(cat_dir)
            if f.endswith((".mp4", ".webm", ".mkv"))
        ]
        if existing:
            downloaded[category] = os.path.join(cat_dir, existing[0])
            logger.info("배경 영상 이미 존재: %s (%s)", category, existing[0])
            continue

        # 검색어 목록
        queries = BACKGROUND_CATEGORIES.get(category, [])
        if not queries:
            continue

        success = False
        for query in queries:
            if success:
                break
            try:
                logger.info("배경 영상 다운로드: [%s] '%s'", category, query)
                output_template = os.path.join(cat_dir, f"{category}_%(id)s.%(ext)s")

                cmd = [
                    ytdlp,
                    f"ytsearch3:{query}",  # 상위 3개 검색
                    "--no-playlist",
                    "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
                    "--merge-output-format", "mp4",
                    "--match-filter", f"duration>{min_duration} & duration<{max_duration}",
                    "--max-downloads", "1",
                    "-o", output_template,
                    "--no-warnings",
                    "--quiet",
                    "--no-check-certificates",
                ]

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300,
                )

                # 다운로드된 파일 확인
                new_files = [
                    f for f in os.listdir(cat_dir)
                    if f.endswith((".mp4", ".webm", ".mkv"))
                ]
                if new_files:
                    filepath = os.path.join(cat_dir, new_files[0])
                    size_mb = os.path.getsize(filepath) / (1024 * 1024)
                    logger.info("  다운로드 완료: %s (%.1fMB)", new_files[0], size_mb)
                    downloaded[category] = filepath
                    success = True
                else:
                    logger.warning("  다운로드 결과 없음 (검색: %s)", query)

            except subprocess.TimeoutExpired:
                logger.warning("  다운로드 타임아웃 (5분): %s", query)
            except Exception as e:
                logger.warning("  다운로드 실패: %s", e)

        if not success:
            logger.warning("카테고리 '%s' 배경 영상 다운로드 실패", category)

    return downloaded


def get_background_clips(
    duration_seconds: float,
    count: int = 10,
    category: str | None = None,
    settings: Settings | None = None,
) -> list[str]:
    """배경 영상에서 4~6초 클립을 추출합니다.

    각 클립은 서로 다른 시작점에서 추출되어
    총 duration_seconds 이상이 됩니다.

    Args:
        duration_seconds: 필요한 총 길이 (초).
        count: 추출할 클립 수.
        category: 사용할 카테고리 (None이면 랜덤).
        settings: 설정 인스턴스.

    Returns:
        추출된 클립 파일 경로 리스트.
    """
    if settings is None:
        settings = get_settings()

    ensure_dir(settings.temp_dir)

    # 사용 가능한 배경 영상 수집
    available_videos: list[tuple[str, str]] = []  # (category, filepath)

    if os.path.isdir(BACKGROUNDS_DIR):
        for cat_name in os.listdir(BACKGROUNDS_DIR):
            cat_dir = os.path.join(BACKGROUNDS_DIR, cat_name)
            if not os.path.isdir(cat_dir):
                continue
            for f in os.listdir(cat_dir):
                if f.endswith((".mp4", ".webm", ".mkv")):
                    available_videos.append(
                        (cat_name, os.path.join(cat_dir, f))
                    )

    if not available_videos:
        logger.warning("배경 영상 없음 - 자동 다운로드 시도")
        # 3개 카테고리만 빠르게 다운로드
        quick_cats = random.sample(
            list(BACKGROUND_CATEGORIES.keys()),
            min(3, len(BACKGROUND_CATEGORIES)),
        )
        downloaded = download_background_videos(categories=quick_cats)
        for cat, path in downloaded.items():
            available_videos.append((cat, path))

    if not available_videos:
        logger.error("배경 영상 확보 실패 - 그라데이션 폴백")
        return []

    # 카테고리 선택
    if category:
        filtered = [(c, p) for c, p in available_videos if c == category]
        if filtered:
            available_videos = filtered

    # 랜덤 영상 선택 (1~2개 소스에서 클립 추출)
    source_video = random.choice(available_videos)
    logger.info("배경 영상 소스: %s [%s]", source_video[0], os.path.basename(source_video[1]))

    # FFmpeg로 클립 추출 (MoviePy 대비 메모리 절약 + 빠름)
    clips: list[str] = []
    clip_duration = 5  # 각 클립 5초

    try:
        # ffprobe로 영상 길이 측정
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            ffmpeg_exe = "ffmpeg"

        ffprobe_exe = ffmpeg_exe.replace("ffmpeg", "ffprobe") if "ffprobe" not in ffmpeg_exe else ffmpeg_exe
        # ffprobe가 없으면 ffmpeg -i 로 폴백
        video_path = source_video[1]
        video_dur = 0.0

        try:
            probe_cmd = [
                ffmpeg_exe, "-i", video_path,
            ]
            result = subprocess.run(
                probe_cmd, capture_output=True, timeout=15,
            )
            stderr_text = result.stderr.decode("utf-8", errors="ignore")
            import re as _re
            dur_match = _re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", stderr_text)
            if dur_match:
                h, m, s = dur_match.groups()
                video_dur = int(h) * 3600 + int(m) * 60 + float(s)
        except Exception as dur_err:
            logger.warning("ffmpeg 길이 측정 실패: %s", dur_err)

        if video_dur < 30:
            logger.warning("배경 영상 짧음 (%.1f초) - 전체 복사 사용", video_dur)
            clip_path = os.path.join(settings.temp_dir, "bg_clip_0.mp4")
            try:
                subprocess.run(
                    [ffmpeg_exe, "-y", "-i", video_path,
                     "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:-1:-1",
                     "-an", "-preset", "ultrafast", "-crf", "23", clip_path],
                    capture_output=True, timeout=120,
                )
                clips.append(clip_path)
            except Exception as e:
                logger.warning("전체 복사 실패: %s", e)
            return clips

        # 랜덤 시작점 기반 클립 추출 (같은 영상이어도 매번 다른 구간)
        random_offset = random.randint(0, max(0, int(video_dur) - 70))
        logger.info("배경 랜덤 시작점: %.1f초 (전체 %.1f초)", random_offset, video_dur)

        max_clips = int((video_dur - random_offset) / clip_duration) - 1
        actual_count = min(count, max_clips, 15)

        for idx in range(actual_count):
            start = random_offset + (idx * clip_duration)
            if start + clip_duration > video_dur:
                break

            clip_path = os.path.join(settings.temp_dir, f"bg_clip_{idx}.mp4")

            try:
                cmd = [
                    ffmpeg_exe, "-y",
                    "-ss", f"{start:.2f}",
                    "-i", video_path,
                    "-t", str(clip_duration),
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:-1:-1",
                    "-an", "-preset", "ultrafast", "-crf", "23",
                    clip_path,
                ]
                subprocess.run(cmd, capture_output=True, timeout=30)

                if os.path.exists(clip_path) and os.path.getsize(clip_path) > 1024:
                    clips.append(clip_path)
                else:
                    logger.warning("클립 %d: 파일 크기 부족", idx)
            except Exception as e:
                logger.warning("FFmpeg 클립 %d 추출 실패: %s", idx, e)

    except Exception as e:
        logger.error("배경 클립 추출 실패: %s", e)

    logger.info("배경 클립 %d개 추출 완료 (카테고리: %s, 랜덤시작)", len(clips), source_video[0])
    return clips


# ============================================================
# Pexels 폴백 (기존 로직 유지)
# ============================================================

KOREAN_KEYWORDS: dict[str, list[str]] = {
    "자영업": ["korean restaurant kitchen", "seoul small business"],
    "알바": ["korean convenience store", "delivery rider seoul"],
    "직장": ["korean office worker", "seoul subway commute"],
    "회사": ["korean office meeting", "corporate workspace"],
    "편의점": ["korean convenience store night", "late night snack"],
    "돈": ["korean won bills", "seoul real estate"],
    "일상": ["seoul city aerial", "korean apartment complex"],
    "충격": ["surprised face reaction", "breaking news screen"],
}


def _convert_korean_keywords(keywords: list[str]) -> list[str]:
    """한국어 키워드를 영어 검색 키워드로 변환합니다."""
    converted: list[str] = []
    for kw in keywords:
        if kw.isascii():
            converted.append(kw)
            continue
        matched = False
        for kr_key, en_keywords in KOREAN_KEYWORDS.items():
            if kr_key in kw:
                converted.extend(en_keywords[:2])
                matched = True
                break
        if not matched:
            converted.append("seoul city korea")
    return converted if converted else ["seoul city", "korea aerial"]


@retry(max_retries=2, retryable_exceptions=(ConnectionError, TimeoutError, requests.RequestException))
def _search_pexels_videos(
    query: str,
    api_key: str,
    per_page: int = 10,
) -> list[dict[str, Any]]:
    """Pexels API에서 영상을 검색합니다."""
    headers = {"Authorization": api_key}
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": "portrait",
        "size": "medium",
    }
    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers=headers,
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("videos", [])


def _get_best_video_url(video: dict[str, Any], min_width: int = 1080) -> str | None:
    """비디오에서 최적 품질의 URL을 추출합니다."""
    files = video.get("video_files", [])
    for f in files:
        if f.get("quality") == "hd" and f.get("width", 0) >= min_width:
            return f["link"]
    for f in files:
        if f.get("quality") == "hd":
            return f["link"]
    for f in files:
        if f.get("quality") == "sd":
            return f["link"]
    if files:
        return files[0]["link"]
    return None


def _download_file(url: str, filepath: str) -> bool:
    """URL에서 파일을 다운로드합니다."""
    try:
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        logger.warning("다운로드 실패: %s", e)
        return False


def _check_first_frame_brightness(filepath: str) -> bool:
    """다운로드된 영상의 첫 프레임 밝기를 체크합니다."""
    try:
        try:
            from moviepy.editor import VideoFileClip
        except ImportError:
            from moviepy import VideoFileClip

        clip = VideoFileClip(filepath)
        frame = clip.get_frame(0)
        clip.close()
        del clip
        gc.collect()
        time.sleep(0.5)

        avg_brightness = np.mean(frame)
        if avg_brightness < 20:
            logger.info("  영상이 너무 어둡습니다 (밝기: %.0f)", avg_brightness)
            return False
        if avg_brightness > 240:
            logger.info("  영상이 너무 밝습니다 (밝기: %.0f)", avg_brightness)
            return False
        return True
    except Exception as e:
        logger.warning("  밝기 체크 실패: %s", e)
        return True


# ============================================================
# 그라데이션 폴백 (최후 수단)
# ============================================================

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """hex 색상을 RGB 튜플로 변환합니다."""
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def _generate_gradient_background(
    output_path: str,
    width: int = 1080,
    height: int = 1920,
    color_top: tuple[int, int, int] = (10, 15, 40),
    color_bottom: tuple[int, int, int] = (0, 0, 0),
) -> str:
    """그라데이션 배경 이미지를 생성합니다."""
    gradient = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        ratio = y / height
        r = int(color_top[0] * (1 - ratio) + color_bottom[0] * ratio)
        g = int(color_top[1] * (1 - ratio) + color_bottom[1] * ratio)
        b = int(color_top[2] * (1 - ratio) + color_bottom[2] * ratio)
        gradient[y, :] = [r, g, b]

    img = Image.fromarray(gradient)
    img.save(output_path)
    logger.info("그라데이션 배경 생성: %s", output_path)
    return output_path


def _get_theme_colors(bg_theme: str) -> list[tuple[tuple[int, int, int], tuple[int, int, int]]]:
    """테마별 그라데이션 색상 쌍을 반환합니다."""
    theme_gradients = BG_GRADIENTS_COMMUNITY.get(bg_theme, {})
    if not theme_gradients:
        return [
            ((10, 15, 40), (0, 0, 0)),
            ((20, 10, 35), (0, 0, 5)),
            ((5, 20, 25), (0, 0, 0)),
            ((25, 15, 10), (0, 0, 0)),
        ]

    colors: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
    for grad in theme_gradients:
        if len(grad) >= 2:
            colors.append((_hex_to_rgb(grad[0]), _hex_to_rgb(grad[-1])))
        else:
            rgb = _hex_to_rgb(grad[0])
            colors.append((rgb, (0, 0, 0)))
    return colors


def _generate_gradient_fallbacks(
    count: int,
    settings: Settings,
    start_idx: int = 0,
    bg_theme: str = "",
) -> list[str]:
    """그라데이션 폴백 배경을 생성합니다."""
    gradient_colors = _get_theme_colors(bg_theme)
    paths: list[str] = []
    for i in range(count):
        idx = start_idx + i
        colors = gradient_colors[i % len(gradient_colors)]
        filepath = os.path.join(settings.temp_dir, f"bg_gradient_{idx}.png")
        _generate_gradient_background(
            filepath,
            settings.video_width,
            settings.video_height,
            colors[0],
            colors[1],
        )
        paths.append(filepath)
    return paths


# ============================================================
# 메인 진입점: 배경 영상 다운로드 (통합)
# ============================================================

def download_backgrounds(
    keywords: list[str],
    count: int = 10,
    bg_theme: str = "",
    settings: Settings | None = None,
) -> list[str]:
    """배경 영상을 준비합니다.

    우선순위:
    1. data/backgrounds/ 로컬 영상 (subway_surfers 등) + 랜덤 시작점
    2. Pexels API 폴백
    3. 그라데이션 배경 최후 폴백

    Args:
        keywords: 검색 키워드 리스트.
        count: 필요한 클립 수.
        bg_theme: 배경 테마.
        settings: 설정 인스턴스.

    Returns:
        배경 클립 파일 경로 리스트.
    """
    if settings is None:
        settings = get_settings()

    ensure_dir(settings.temp_dir)
    target_duration = getattr(settings, "target_duration", 59)

    # ── 1순위: 로컬 data/backgrounds/ (subway_surfers 등 + 랜덤 시작점) ──
    clips = get_background_clips(
        duration_seconds=target_duration,
        count=count,
        settings=settings,
    )
    if clips and len(clips) >= 3:
        logger.info("로컬 배경 클립 %d개 준비 완료 (랜덤 시작점)", len(clips))
        return clips

    # ── 2순위: Pexels API 폴백 ──
    downloaded: list[str] = []
    api_key = None
    if settings.use_pexels:
        api_key = SecretsManager.get_secret_value(settings.pexels_api_key)

    if api_key:
        pexels_keywords = UNIVERSAL_BACKGROUNDS.copy()
        random.shuffle(pexels_keywords)
        logger.info("로컬 배경 부족 - Pexels 폴백 시도: %s", pexels_keywords[:3])

        for keyword in pexels_keywords:
            if len(downloaded) >= count:
                break
            try:
                videos = _search_pexels_videos(keyword, api_key, per_page=10)
            except Exception as e:
                logger.warning("Pexels 검색 오류 (%s): %s", keyword, e)
                continue

            for video in videos:
                if len(downloaded) >= count:
                    break
                url = _get_best_video_url(video, min_width=1080)
                if not url:
                    continue
                filename = f"bg_{len(downloaded)}.mp4"
                filepath = os.path.join(settings.temp_dir, filename)
                if _download_file(url, filepath):
                    size_mb = os.path.getsize(filepath) / (1024 * 1024)
                    if size_mb < PEXELS_MIN_FILE_SIZE_MB:
                        logger.info("  Pexels 스킵 (저품질): %s (%.1fMB)", filename, size_mb)
                        for attempt in range(3):
                            try:
                                os.remove(filepath)
                                break
                            except PermissionError:
                                time.sleep(1)
                        continue
                    logger.info("  Pexels 다운로드: %s (%.1fMB)", filename, size_mb)
                    if not _check_first_frame_brightness(filepath):
                        for attempt in range(3):
                            try:
                                os.remove(filepath)
                                break
                            except PermissionError:
                                time.sleep(1)
                        continue
                    downloaded.append(filepath)

        if downloaded:
            logger.info("Pexels 배경 %d개 다운로드 완료", len(downloaded))
    else:
        logger.info("Pexels API 키 없음 / 비활성화")

    # ── 3순위: 그라데이션 최후 폴백 ──
    if len(downloaded) < 3:
        logger.info("배경 영상 부족 (%d개) - 그라데이션 보충", len(downloaded))
        needed = max(count - len(downloaded), 3)
        fallbacks = _generate_gradient_fallbacks(
            needed, settings, start_idx=len(downloaded), bg_theme=bg_theme,
        )
        downloaded.extend(fallbacks)

    logger.info("총 %d개 배경 영상 준비 완료", len(downloaded))
    return downloaded
