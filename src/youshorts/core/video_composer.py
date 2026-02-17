# 변경 사유: 사인파 BGM 제거 → MP3 로딩, BGM 덕킹, 카운트다운/whoosh 제거, Ken Burns 효과, 크로스 디졸브 1초, 프로그레스 바 상단 3px
"""영상 합성 엔진.

배경 블러, Ken Burns 효과, 크로스 디졸브, 타이틀 슬라이드인,
자막, 시각 효과를 레이어링하여 최종 MP4 영상을 생성합니다.
사인파 BGM을 완전히 제거하고 로열티 프리 MP3를 사용합니다.
"""

from __future__ import annotations

import gc
import glob
import os
import random
import re
import subprocess
import shutil
from datetime import datetime
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from youshorts.config.constants import (
    BG_BLUR_RADIUS,
    BG_DARKEN_OPACITY,
    BOTTOM_BAR_HEIGHT,
    CROSSFADE_DURATION,
    KEN_BURNS_ZOOM_PER_5SEC,
    PROGRESS_BAR_COLOR,
    PROGRESS_BAR_HEIGHT,
    SUBTITLE_Y_RATIO,
    TRANSITION_INTERVAL,
)
from youshorts.config.settings import Settings, get_settings
from youshorts.config.styles import EDIT_STYLES
from youshorts.rendering.subtitle_engine import (
    create_bottom_bar,
    create_subtitle_image,
    create_title_bar,
    get_section_for_time,
)
from youshorts.rendering.visual_effects import generate_visual_effects_for_script
from youshorts.utils.file_handler import ensure_dir
from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

try:
    from moviepy.editor import (
        AudioFileClip,
        ColorClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
    )
except ImportError:
    from moviepy import (
        AudioFileClip,
        ColorClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FFmpeg 직접 호출 함수 (OOM 해결)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_ffmpeg_path() -> str | None:
    """FFmpeg 경로 자동 탐지.

    Returns:
        FFmpeg 실행 파일 경로 또는 None.
    """
    path = shutil.which('ffmpeg')
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    common = [
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
        r'C:\tool\ffmpeg\bin\ffmpeg.exe',
    ]
    for p in common:
        if os.path.exists(p):
            return p
    return None


def render_with_ffmpeg(
    bg_video: str,
    tts_audio: str,
    subtitle_file: str,
    output_path: str,
    config: dict[str, Any],
) -> str:
    """FFmpeg 직접 렌더링. MoviePy 대비 메모리 1/10.

    ASS 자막(워드 하이라이트) 또는 SRT 자막 자동 감지.

    Args:
        bg_video: 배경 영상 경로.
        tts_audio: TTS 오디오 경로.
        subtitle_file: ASS 또는 SRT 자막 파일 경로.
        output_path: 출력 파일 경로.
        config: 랜덤화 설정 (font_size, margin_v, bg_darken 등).

    Returns:
        출력 파일 경로.

    Raises:
        FileNotFoundError: FFmpeg 미설치 시.
        RuntimeError: FFmpeg 실행 실패 시.
    """
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        raise FileNotFoundError("FFmpeg 미설치. pip install imageio-ffmpeg 또는 시스템 PATH에 추가하세요.")

    ensure_dir(os.path.join(os.getcwd(), 'temp'))
    darken = config.get('bg_darken', 0.25)
    brightness = round(-darken, 2)

    # ASS vs SRT 자동 감지
    is_ass = subtitle_file.endswith('.ass')

    if is_ass:
        # ASS 자막: 스타일이 파일에 내장되어 있으므로 ass= 필터 사용
        safe_sub = os.path.join('temp', 'sub.ass')
        shutil.copy2(subtitle_file, safe_sub)
        safe_sub_escaped = safe_sub.replace('\\', '/').replace(':', '\\\\:')
        vf_filter = f"eq=brightness={brightness}:contrast=1.1,ass='{safe_sub_escaped}'"
        logger.info("[렌더링] ASS 워드 하이라이트 자막 사용")
    else:
        # SRT 자막: force_style 사용 (기존 로직)
        safe_sub = os.path.join('temp', 'sub.srt')
        shutil.copy2(subtitle_file, safe_sub)
        safe_sub_escaped = safe_sub.replace('\\', '/').replace(':', '\\\\:')
        font_size = config.get('font_size', 30)
        margin_v = config.get('margin_v', 25)
        subtitle_style = (
            f"FontSize={font_size},"
            f"PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,"
            f"BackColour=&H80000000,"
            f"BorderStyle=3,"
            f"Outline=2,"
            f"Shadow=1,"
            f"Alignment=2,"
            f"MarginV={margin_v}"
        )
        vf_filter = f"eq=brightness={brightness}:contrast=1.1,subtitles='{safe_sub_escaped}':force_style='{subtitle_style}'"

    cmd = [
        ffmpeg, '-y',
        '-i', bg_video,
        '-i', tts_audio,
        '-vf', vf_filter,
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-shortest',
        '-fps_mode', 'cfr',
        '-r', '24',
        '-s', '1080x1920',
        output_path
    ]

    logger.info("[렌더링] FFmpeg 시작: %s", output_path)
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="ignore") if isinstance(result.stderr, bytes) else (result.stderr or "")
        logger.error("[FFmpeg 에러] %s", stderr[-500:])
        raise RuntimeError(f"FFmpeg 실패: returncode={result.returncode}")
    logger.info("[렌더링] FFmpeg 완료: %s", output_path)
    return output_path


def merge_bg_clips_ffmpeg(clip_paths: list[str], output_path: str) -> str:
    """배경 클립들을 FFmpeg concat으로 합치기 (메모리 0 사용).

    Args:
        clip_paths: 배경 클립 경로 리스트.
        output_path: 출력 파일 경로.

    Returns:
        출력 파일 경로.
    """
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        raise FileNotFoundError("FFmpeg 미설치")

    ensure_dir(os.path.join(os.getcwd(), 'temp'))
    concat_list = os.path.join('temp', 'concat_list.txt')
    with open(concat_list, 'w', encoding='utf-8') as f:
        for clip in clip_paths:
            safe = clip.replace('\\', '/')
            f.write(f"file '{safe}'\n")

    cmd = [
        ffmpeg, '-y',
        '-f', 'concat', '-safe', '0',
        '-i', concat_list,
        '-c', 'copy',
        '-an',  # 오디오 제거 (TTS로 교체할 거니까)
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.warning("[FFmpeg concat 실패] %s", result.stderr[-200:] if result.stderr else "")
    return output_path


def _img_to_clip(
    img_array: np.ndarray,
    duration: float,
    start_time: float,
    y_ratio: float = 0.5,
    video_height: int = 1920,
) -> ImageClip:
    """RGBA 이미지 배열을 moviepy 클립으로 변환합니다.

    Args:
        img_array: RGBA numpy 배열.
        duration: 클립 길이 (초).
        start_time: 시작 시간 (초).
        y_ratio: 수직 위치 비율 (0~1).
        video_height: 영상 높이.

    Returns:
        위치가 지정된 ImageClip.
    """
    rgb = img_array[:, :, :3]
    alpha = img_array[:, :, 3].astype(float) / 255.0

    clip = ImageClip(rgb).set_duration(duration).set_start(start_time)
    mask = ImageClip(alpha, ismask=True).set_duration(duration).set_start(start_time)
    clip = clip.set_mask(mask)

    y = max(0, int(video_height * y_ratio - img_array.shape[0] / 2))
    clip = clip.set_position((0, y))
    return clip


def _img_to_clip_pos(
    img_array: np.ndarray,
    duration: float,
    start_time: float,
    x: int = 0,
    y: int = 0,
) -> ImageClip:
    """절대 좌표로 배치하는 클립.

    Args:
        img_array: RGBA numpy 배열.
        duration: 클립 길이.
        start_time: 시작 시간.
        x: X 좌표.
        y: Y 좌표.

    Returns:
        위치가 지정된 ImageClip.
    """
    rgb = img_array[:, :, :3]
    alpha = img_array[:, :, 3].astype(float) / 255.0

    clip = ImageClip(rgb).set_duration(duration).set_start(start_time)
    mask = ImageClip(alpha, ismask=True).set_duration(duration).set_start(start_time)
    clip = clip.set_mask(mask)
    clip = clip.set_position((x, y))
    return clip


def _fit_to_vertical(
    clip: VideoFileClip,
    video_width: int,
    video_height: int,
) -> VideoFileClip:
    """영상을 세로 화면에 맞게 크롭합니다."""
    scale = max(video_width / clip.w, video_height / clip.h)
    new_w = int(clip.w * scale)
    new_h = int(clip.h * scale)
    resized = clip.resize((new_w, new_h))
    x1 = (new_w - video_width) // 2
    y1 = (new_h - video_height) // 2
    return resized.crop(x1=x1, y1=y1, x2=x1 + video_width, y2=y1 + video_height)


def _apply_blur_to_clip(clip: VideoFileClip, radius: int = BG_BLUR_RADIUS) -> VideoFileClip:
    """프레임 단위로 가우시안 블러를 적용합니다."""
    def blur_frame(get_frame: Any, t: float) -> np.ndarray:
        frame = get_frame(t)
        img = Image.fromarray(frame)
        blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))
        return np.array(blurred, dtype=np.uint8)
    return clip.fl(blur_frame)


def _apply_ken_burns(
    clip: Any,
    video_width: int,
    video_height: int,
    zoom_per_5sec: float = KEN_BURNS_ZOOM_PER_5SEC,
    effect_type: str | None = None,
) -> Any:
    """Ken Burns 효과를 적용합니다 (랜덤 줌인/줌아웃/팬).

    변경 사유: 한국형 숏츠 - 정적 느낌 제거를 위한 랜덤 카메라 효과
    - zoom_in: 1.0 → 1.05 (5초간) 확대
    - zoom_out: 1.05 → 1.0 (5초간) 축소
    - pan_left: 좌→우 수평 이동
    - pan_right: 우→좌 수평 이동

    Args:
        clip: 배경 비디오/이미지 클립.
        video_width: 영상 너비.
        video_height: 영상 높이.
        zoom_per_5sec: 5초당 줌 비율.
        effect_type: 효과 종류 (None이면 랜덤).

    Returns:
        Ken Burns 효과가 적용된 클립.
    """
    if effect_type is None:
        effect_type = random.choice(["zoom_in", "zoom_out", "pan_left", "pan_right"])

    def ken_burns_frame(get_frame: Any, t: float) -> np.ndarray:
        frame = get_frame(t)
        h, w = frame.shape[:2]
        duration = clip.duration if clip.duration > 0 else 5.0
        progress = t / duration  # 0.0 ~ 1.0

        if effect_type == "zoom_in":
            zoom = 1.0 + progress * zoom_per_5sec * (duration / 5.0)
        elif effect_type == "zoom_out":
            zoom = 1.0 + zoom_per_5sec * (duration / 5.0) - progress * zoom_per_5sec * (duration / 5.0)
        else:
            zoom = 1.0 + zoom_per_5sec  # 팬 효과 시 약간 줌

        new_h = int(h * zoom)
        new_w = int(w * zoom)

        img = Image.fromarray(frame)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        if effect_type == "pan_left":
            # 좌→우 팬: x 오프셋이 점점 증가
            max_offset = new_w - w
            x1 = int(max_offset * progress)
            y1 = (new_h - h) // 2
        elif effect_type == "pan_right":
            # 우→좌 팬: x 오프셋이 점점 감소
            max_offset = new_w - w
            x1 = int(max_offset * (1.0 - progress))
            y1 = (new_h - h) // 2
        else:
            # 줌인/줌아웃: 중앙 기준
            x1 = (new_w - w) // 2
            y1 = (new_h - h) // 2

        x1 = max(0, min(x1, new_w - w))
        y1 = max(0, min(y1, new_h - h))
        img = img.crop((x1, y1, x1 + w, y1 + h))

        return np.array(img, dtype=np.uint8)

    return clip.fl(ken_burns_frame)


def _fit_image_to_vertical(
    img_path: str,
    video_width: int,
    video_height: int,
) -> np.ndarray:
    """정적 이미지를 세로 화면(1080x1920)에 맞게 크롭+리사이즈합니다.

    Args:
        img_path: 이미지 파일 경로.
        video_width: 영상 너비.
        video_height: 영상 높이.

    Returns:
        크롭+리사이즈된 numpy 배열.
    """
    img = Image.open(img_path).convert("RGB")
    target_ratio = video_width / video_height

    img_ratio = img.width / img.height
    if img_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))

    img = img.resize((video_width, video_height), Image.LANCZOS)
    return np.array(img, dtype=np.uint8)


def _prepare_screenshot_bg(
    img_path: str,
    video_width: int,
    video_height: int,
    blur_radius: int = 3,
    brightness: float = 0.4,
) -> np.ndarray:
    """스크린샷을 배경용으로 처리합니다 (크롭 + 블러 + 어둡게).

    Args:
        img_path: 스크린샷 파일 경로.
        video_width: 영상 너비.
        video_height: 영상 높이.
        blur_radius: 가우시안 블러 반경.
        brightness: 밝기 비율 (0.4 = 40% 밝기).

    Returns:
        처리된 numpy 배열.
    """
    from PIL import ImageEnhance

    img = Image.open(img_path).convert("RGB")
    target_ratio = video_width / video_height

    # 9:16 비율로 크롭+리사이즈
    img_ratio = img.width / img.height
    if img_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))

    img = img.resize((video_width, video_height), Image.LANCZOS)

    # 블러 (배경이니까 적당히)
    img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    # 어둡게 (자막 가독성)
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(brightness)

    return np.array(img, dtype=np.uint8)


def _generate_gradient_background(
    video_width: int,
    video_height: int,
    colors: tuple[str, ...],
    direction: str = "vertical",
) -> np.ndarray:
    """그라데이션 배경 이미지를 생성합니다.

    Args:
        video_width: 영상 너비
        video_height: 영상 높이
        colors: 그라데이션 색상 튜플 (2개 또는 3개)
        direction: 그라데이션 방향 ("vertical" | "horizontal" | "diagonal")

    Returns:
        RGB numpy 배열
    """
    def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        """헥스 색상을 RGB 튜플로 변환합니다."""
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))  # type: ignore

    rgb_colors = [hex_to_rgb(c) for c in colors]

    # 그라데이션 이미지 생성
    img = Image.new("RGB", (video_width, video_height))
    pixels = img.load()

    if direction == "vertical":
        # 상→하 그라데이션
        for y in range(video_height):
            # 색상 보간 위치 계산
            if len(rgb_colors) == 2:
                t = y / video_height
                color = tuple(
                    int(rgb_colors[0][i] * (1 - t) + rgb_colors[1][i] * t)
                    for i in range(3)
                )
            else:  # 3색
                if y < video_height // 2:
                    t = y / (video_height // 2)
                    color = tuple(
                        int(rgb_colors[0][i] * (1 - t) + rgb_colors[1][i] * t)
                        for i in range(3)
                    )
                else:
                    t = (y - video_height // 2) / (video_height // 2)
                    color = tuple(
                        int(rgb_colors[1][i] * (1 - t) + rgb_colors[2][i] * t)
                        for i in range(3)
                    )

            for x in range(video_width):
                pixels[x, y] = color  # type: ignore

    elif direction == "horizontal":
        # 좌→우 그라데이션
        for x in range(video_width):
            if len(rgb_colors) == 2:
                t = x / video_width
                color = tuple(
                    int(rgb_colors[0][i] * (1 - t) + rgb_colors[1][i] * t)
                    for i in range(3)
                )
            else:
                if x < video_width // 2:
                    t = x / (video_width // 2)
                    color = tuple(
                        int(rgb_colors[0][i] * (1 - t) + rgb_colors[1][i] * t)
                        for i in range(3)
                    )
                else:
                    t = (x - video_width // 2) / (video_width // 2)
                    color = tuple(
                        int(rgb_colors[1][i] * (1 - t) + rgb_colors[2][i] * t)
                        for i in range(3)
                    )

            for y in range(video_height):
                pixels[x, y] = color  # type: ignore

    elif direction == "diagonal":
        # 대각선 그라데이션
        max_dist = (video_width**2 + video_height**2) ** 0.5
        for y in range(video_height):
            for x in range(video_width):
                dist = (x**2 + y**2) ** 0.5
                t = dist / max_dist
                if len(rgb_colors) == 2:
                    color = tuple(
                        int(rgb_colors[0][i] * (1 - t) + rgb_colors[1][i] * t)
                        for i in range(3)
                    )
                else:
                    if t < 0.5:
                        t_scaled = t * 2
                        color = tuple(
                            int(rgb_colors[0][i] * (1 - t_scaled) + rgb_colors[1][i] * t_scaled)
                            for i in range(3)
                        )
                    else:
                        t_scaled = (t - 0.5) * 2
                        color = tuple(
                            int(rgb_colors[1][i] * (1 - t_scaled) + rgb_colors[2][i] * t_scaled)
                            for i in range(3)
                        )

                pixels[x, y] = color  # type: ignore

    return np.array(img, dtype=np.uint8)


def _build_background(
    bg_paths: list[str],
    total_dur: float,
    edit_style: str,
    video_width: int,
    video_height: int,
    enable_ken_burns: bool = True,
    is_screenshot_bg: bool = False,
    gradient_colors: tuple[str, ...] | None = None,
) -> CompositeVideoClip | ColorClip:
    """배경 영상을 구성합니다.

    1초 크로스 디졸브, Ken Burns 효과를 적용합니다.
    is_screenshot_bg=True이면 스크린샷에 대해 블러+어둡게 전처리 후 사용합니다.
    gradient_colors가 주어지면 그라데이션 배경을 생성합니다.
    """
    if not bg_paths:
        # 그라데이션 배경 사용
        if gradient_colors:
            gradient_img = _generate_gradient_background(
                video_width, video_height, gradient_colors, direction="vertical"
            )
            return ImageClip(gradient_img).set_duration(total_dur)
        else:
            # 기본 단색 배경
            return ColorClip(
                (video_width, video_height), color=(18, 18, 32)
            ).set_duration(total_dur)

    bg_clips = []
    for path in bg_paths:
        try:
            if path.endswith(".png") or path.endswith(".jpg"):
                if is_screenshot_bg:
                    processed = _prepare_screenshot_bg(
                        path, video_width, video_height,
                    )
                    c = ImageClip(processed).set_duration(total_dur)
                else:
                    c = ImageClip(path).set_duration(total_dur)
            else:
                c = VideoFileClip(path)
                c = _fit_to_vertical(c, video_width, video_height)
            # 변경 사유: 만족감 배경은 블러 제거 (선명해야 함)
            # 블러는 스크린샷 배경 또는 blur_radius > 0일 때만 적용
            if is_screenshot_bg:
                c = _apply_blur_to_clip(c, radius=3)
            elif BG_BLUR_RADIUS > 0:
                c = _apply_blur_to_clip(c, radius=BG_BLUR_RADIUS)
            if enable_ken_burns:
                # 변경 사유: 줌인/줌아웃 교차 적용 (매 클립마다 다른 효과)
                effects = ["zoom_in", "zoom_out", "zoom_in", "zoom_out"]
                effect_type = effects[len(bg_clips) % len(effects)]
                c = _apply_ken_burns(c, video_width, video_height, effect_type=effect_type)
            bg_clips.append(c)
        except Exception as e:
            logger.warning("배경 로드 실패: %s", e)

    if not bg_clips:
        return ColorClip(
            (video_width, video_height), color=(18, 18, 32)
        ).set_duration(total_dur)

    # 변경 사유: 한국형 숏츠 컷 편집 스타일
    # - 4-6초 간격 배경 전환 (스타일별 차이)
    # - 단일 배경 최대 10초 제한
    # - 0.3초 크로스페이드
    interval = TRANSITION_INTERVAL  # 기본 5초
    if edit_style == "dynamic":
        interval = 4
    elif edit_style == "cinematic":
        interval = 6
    elif edit_style == "energetic":
        interval = 3
    elif edit_style == "storytelling":
        interval = 5  # 한국형: 적당한 호흡

    fade_dur = CROSSFADE_DURATION  # 0.0초 (하드컷)

    # 단일 배경 최대 10초 제한
    MAX_SINGLE_BG_SEC = 10

    segments = []
    num_segments = int(total_dur / interval) + 1
    seg_dur = min(interval, MAX_SINGLE_BG_SEC)

    for i in range(num_segments):
        clip = bg_clips[i % len(bg_clips)]
        max_start = max(0, clip.duration - seg_dur)
        # 변경 사유: 각 세그먼트를 더 넓게 분산시켜 반복 느낌 제거
        start_pos = (i * 3.7) % max(max_start, 0.1)
        end_pos = min(start_pos + seg_dur, clip.duration)
        seg = clip.subclip(start_pos, end_pos)
        if seg.duration < seg_dur:
            seg = seg.loop(duration=seg_dur)
        seg = seg.set_start(i * interval)
        # 변경 사유: 하드컷 (페이드 없이 바로 전환)
        # 레퍼런스 채널 스타일: 쇼츠에서는 하드컷이 더 자연스러움
        if fade_dur > 0 and i > 0:
            seg = seg.crossfadein(fade_dur)
        segments.append(seg)

    bg = CompositeVideoClip(segments, size=(video_width, video_height))
    return bg.set_duration(total_dur)


def _build_overlay(
    total_dur: float,
    video_width: int,
    video_height: int,
) -> ColorClip:
    """배경 어둡게 오버레이를 생성합니다."""
    return (
        ColorClip((video_width, video_height), color=(0, 0, 0))
        .set_opacity(BG_DARKEN_OPACITY)
        .set_duration(total_dur)
    )


def _build_progress_bar(
    total_dur: float,
    video_width: int,
) -> Any:
    """상단 3px 얇은 프로그레스 바를 생성합니다.

    영상 최상단에 진행률을 나타내는 얇은 라인입니다.

    Args:
        total_dur: 전체 영상 길이 (초).
        video_width: 영상 너비.

    Returns:
        프로그레스 바 클립.
    """
    bar_h = PROGRESS_BAR_HEIGHT
    color = PROGRESS_BAR_COLOR

    def make_frame(t: float) -> np.ndarray:
        progress = t / total_dur if total_dur > 0 else 0
        bar_w = int(video_width * progress)
        frame = np.zeros((bar_h, video_width, 3), dtype=np.uint8)
        if bar_w > 0:
            frame[:, :bar_w] = color
        return frame

    clip = ColorClip((video_width, bar_h), color=(0, 0, 0)).set_duration(total_dur)
    clip = clip.fl(lambda gf, t: make_frame(t))
    clip = clip.set_position((0, 0))
    return clip


def _load_bgm(bgm_dir: str) -> str | None:
    """data/bgm/ 폴더에서 랜덤 BGM 파일을 선택합니다.

    Args:
        bgm_dir: BGM 디렉토리 경로.

    Returns:
        BGM 파일 경로 또는 None.
    """
    if not os.path.isdir(bgm_dir):
        return None

    bgm_files = glob.glob(os.path.join(bgm_dir, "*.mp3"))
    bgm_files += glob.glob(os.path.join(bgm_dir, "*.wav"))
    bgm_files += glob.glob(os.path.join(bgm_dir, "*.ogg"))

    if not bgm_files:
        return None

    selected = random.choice(bgm_files)
    logger.info("BGM 선택: %s", os.path.basename(selected))
    return selected


def _build_subtitle_clips(
    words: list[dict[str, Any]],
    script: dict[str, Any],
    time_offset: float,
    total_dur: float,
    video_height: int,
    font_size_override: int | None = None,
    y_ratio_override: float | None = None,
    highlight_color_override: tuple[int, int, int] | None = None,
) -> list[ImageClip]:
    """자막 클립 리스트를 생성합니다.

    community 스타일: subtitle_chunks의 emotion/highlight 정보를 자막에 반영합니다.
    랜덤화 파라미터를 받아 AI 탐지 회피에 활용합니다.
    """
    clips: list[ImageClip] = []
    keywords = script.get("keywords", [])
    color_idx = 0
    y_ratio = y_ratio_override if y_ratio_override is not None else SUBTITLE_Y_RATIO

    # community 스타일 subtitle_chunks에서 emotion/highlight 매핑 구축
    sub_chunks = script.get("subtitle_chunks", [])
    chunk_map: dict[str, dict[str, str]] = {}
    for chunk in sub_chunks:
        chunk_text = chunk.get("text", "").strip()
        if chunk_text:
            chunk_map[chunk_text] = {
                "emotion": chunk.get("emotion", ""),
                "highlight": chunk.get("highlight", ""),
            }

    for g in words:
        dur = max(g["end"] - g["start"], 0.3)
        start = g["start"] + time_offset
        if start >= total_dur:
            break

        section = get_section_for_time(start, total_dur)
        word_text = g["text"]

        # subtitle_chunks에서 emotion/highlight 매칭 시도
        emotion = ""
        highlight = ""
        if chunk_map:
            # 정확 매칭
            if word_text in chunk_map:
                emotion = chunk_map[word_text].get("emotion", "")
                highlight = chunk_map[word_text].get("highlight", "")
            else:
                # 부분 매칭: 자막 텍스트가 chunk text에 포함되거나 반대
                for ct, cv in chunk_map.items():
                    if ct in word_text or word_text in ct:
                        emotion = cv.get("emotion", "")
                        highlight = cv.get("highlight", "")
                        break

        img = create_subtitle_image(
            word_text,
            keywords=keywords,
            color_idx=color_idx,
            is_hook=(section == "hook"),
            section=section,
            emotion=emotion,
            highlight=highlight,
            font_size_override=font_size_override,
            highlight_color_override=highlight_color_override,
        )

        clip = _img_to_clip(img, dur, start, y_ratio=y_ratio, video_height=video_height)
        # 자막 페이드인/아웃 0.1초
        clip = clip.fadein(0.1).fadeout(0.1)
        clips.append(clip)
        color_idx += 1

    return clips


def _create_outro_overlay(
    video_width: int,
    video_height: int,
) -> np.ndarray:
    """'좋아요 & 구독' 아웃트로 오버레이를 생성합니다.

    변경 사유: 한국형 숏츠 스타일 - 마지막 3초 "좋아요 & 구독" CTA

    Args:
        video_width: 영상 너비.
        video_height: 영상 높이.

    Returns:
        RGBA numpy 배열.
    """
    from youshorts.utils.fonts import load_font

    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 반투명 배경
    box_w, box_h = 700, 200
    x = (video_width - box_w) // 2
    y = video_height // 2 - box_h // 2

    draw.rounded_rectangle(
        [(x, y), (x + box_w, y + box_h)],
        radius=30,
        fill=(0, 0, 0, 180),
    )

    # "좋아요 & 구독" 텍스트
    main_font = load_font(52)
    main_text = "👍 좋아요 & 구독"
    bbox = draw.textbbox((0, 0), main_text, font=main_font)
    tw = bbox[2] - bbox[0]
    draw.text(
        ((video_width - tw) // 2, y + 40),
        main_text, font=main_font, fill=(255, 215, 0, 255),
    )

    # "알림 설정도 부탁해요!" 보조 텍스트
    sub_font = load_font(32)
    sub_text = "🔔 알림 설정도 부탁해요!"
    bbox2 = draw.textbbox((0, 0), sub_text, font=sub_font)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(
        ((video_width - tw2) // 2, y + 120),
        sub_text, font=sub_font, fill=(255, 255, 255, 220),
    )

    return np.array(img)


def _build_visual_effect_clips(
    effects: list[dict[str, Any]],
    video_height: int,
) -> list[ImageClip]:
    """시각 효과 클립 리스트를 생성합니다."""
    clips: list[ImageClip] = []
    for effect in effects:
        img = effect["image"]
        clip = _img_to_clip(img, effect["duration"], effect["start"], y_ratio=0.5, video_height=video_height)
        # 페이드인 0.5초 추가
        clip = clip.fadein(0.5).fadeout(0.3)
        clips.append(clip)
    return clips


def _randomize_video_params() -> dict[str, Any]:
    """AI 탐지 회피용 영상 파라미터 랜덤화.

    매 영상마다 자막/배경/타이틀 파라미터를 미세하게 변경하여
    동일 채널의 영상이 똑같이 보이지 않도록 합니다.

    Returns:
        랜덤화된 파라미터 딕셔너리.
    """
    highlight_colors = [
        (255, 215, 0),    # 골드
        (0, 220, 255),    # 시안
        (255, 105, 180),  # 핑크
        (100, 255, 100),  # 그린
        (255, 165, 0),    # 오렌지
    ]
    return {
        # 자막 (레퍼런스 채널급 - 화면 하단 15% 영역)
        "font_size": random.randint(28, 32),
        "margin_v": random.randint(20, 30),
        "subtitle_font_size": random.randint(28, 32),
        "subtitle_y_ratio": round(random.uniform(0.78, 0.85), 2),
        "highlight_color": random.choice(highlight_colors),
        # 배경 어둡기
        "bg_darken": round(random.uniform(0.18, 0.35), 2),
        "bg_darken_opacity": round(random.uniform(0.18, 0.35), 2),
        # 타이틀 바
        "title_bar_opacity": round(random.uniform(0.5, 0.8), 2),
        "title_font_size": random.randint(28, 38),
        "title_y_pct": round(random.uniform(0.02, 0.08), 3),
        # 영상 길이 (40~70초)
        "target_duration_range": (40, 70),
    }


def compose(
    bg_paths: list[str],
    tts_path: str,
    words: list[dict[str, Any]],
    script: dict[str, Any],
    total_duration: float,
    edit_style: str | None = None,
    settings: Settings | None = None,
    gradient_colors: tuple[str, ...] | None = None,
) -> tuple[str, str]:
    """모든 요소를 합성하여 MP4 영상을 생성합니다.

    Args:
        bg_paths: 배경 영상 파일 경로들.
        tts_path: TTS 오디오 파일 경로.
        words: 단어 그룹 타이밍 리스트.
        script: 대본 딕셔너리.
        total_duration: 전체 길이 (초).
        edit_style: 편집 스타일 (None이면 랜덤).
        settings: 설정 인스턴스.
        gradient_colors: 그라데이션 배경 색상 (bg_paths 없을 때 사용).

    Returns:
        (출력 파일 경로, 사용된 편집 스타일).
    """
    if settings is None:
        settings = get_settings()

    ensure_dir(settings.output_dir)
    ensure_dir(settings.temp_dir)

    vw = settings.video_width
    vh = settings.video_height

    if edit_style is None:
        edit_style = random.choice(EDIT_STYLES)
    logger.info("편집 스타일: %s", edit_style)

    # ── AI 탐지 회피: 영상별 랜덤 파라미터 ──
    rp = _randomize_video_params()
    logger.info(
        "[랜덤화] 자막=%dpx y=%.2f / 배경어둡기=%.2f / 타이틀=%.0f%% %dpx",
        rp["subtitle_font_size"], rp["subtitle_y_ratio"],
        rp["bg_darken_opacity"],
        rp["title_bar_opacity"] * 100, rp["title_font_size"],
    )

    # 스크린샷 배경 여부 감지 (textss_*.png 또는 screenshot_*.png)
    is_screenshot_bg = any(
        os.path.basename(p).startswith(("textss_", "screenshot_"))
        for p in bg_paths if p
    )

    # 1. Background (Ken Burns + 하드컷)
    if is_screenshot_bg:
        logger.info("[1/9] 스크린샷 배경 (블러+어둡게 + Ken Burns + 하드컷)...")
    else:
        logger.info("[1/9] 만족감 배경 (Ken Burns 줌 + 하드컷 전환)...")
    background = _build_background(
        bg_paths, total_duration, edit_style, vw, vh,
        enable_ken_burns=settings.enable_ken_burns,
        is_screenshot_bg=is_screenshot_bg,
        gradient_colors=gradient_colors,
    )

    # 2. Dark overlay (랜덤 어둡기)
    rand_darken = rp["bg_darken_opacity"]
    logger.info("[2/9] 어둡게 오버레이 (%.0f%%)...", rand_darken * 100)
    overlay = (
        ColorClip((vw, vh), color=(0, 0, 0))
        .set_opacity(rand_darken)
        .set_duration(total_duration)
    )

    # 3. Title bar (랜덤 투명도/폰트크기/위치)
    logger.info("[3/9] 상단 타이틀 바 (랜덤: %dpx, %.0f%%)...",
                rp["title_font_size"], rp["title_bar_opacity"] * 100)
    title = script.get("title", "")
    title_bar_img = create_title_bar(
        title,
        font_size_override=rp["title_font_size"],
        opacity_override=rp["title_bar_opacity"],
    )
    title_y = int(vh * rp["title_y_pct"])
    title_bar_clip = _img_to_clip_pos(title_bar_img, total_duration, 0, x=0, y=title_y)
    title_bar_clip = title_bar_clip.fadein(0.5)

    # 4. Bottom bar (채널명이 비어있으면 생략)
    bottom_bar_clip = None
    if settings.channel_name:
        logger.info("[4/9] 하단 채널명 바...")
        bottom_bar_img = create_bottom_bar(settings.channel_name)
        bottom_bar_clip = _img_to_clip_pos(
            bottom_bar_img, total_duration, 0, x=0, y=vh - BOTTOM_BAR_HEIGHT,
        )
    else:
        logger.info("[4/9] 하단 채널명 바 생략 (채널명 미설정)")

    # 5. Progress bar (상단 3px 얇은 라인)
    logger.info("[5/9] 프로그레스 바 (상단 3px)...")
    progress_bar = _build_progress_bar(total_duration, vw)

    # 6. Subtitles (랜덤 폰트크기/위치/강조색)
    logger.info("[6/9] 자막 생성 (%dpx, y=%.2f, 랜덤 강조색)...",
                rp["subtitle_font_size"], rp["subtitle_y_ratio"])
    subtitle_clips = _build_subtitle_clips(
        words, script, time_offset=0.0, total_dur=total_duration, video_height=vh,
        font_size_override=rp["subtitle_font_size"],
        y_ratio_override=rp["subtitle_y_ratio"],
        highlight_color_override=rp["highlight_color"],
    )
    logger.info("  %d개 자막 클립", len(subtitle_clips))

    # 7. Visual effects
    logger.info("[7/9] 시각 효과 (인포그래픽 + 페이드인)...")
    visual_effects = generate_visual_effects_for_script(script, total_duration)
    ve_clips = _build_visual_effect_clips(visual_effects, vh)
    logger.info("  %d개 효과 클립", len(ve_clips))

    # 8. 아웃트로 "좋아요 & 구독" 오버레이 (마지막 2초)
    logger.info("[8/9] 아웃트로 '좋아요 & 구독' 오버레이...")
    outro_img = _create_outro_overlay(vw, vh)
    outro_start = max(0, total_duration - 2.0)
    outro_clip = _img_to_clip(outro_img, 2.0, outro_start, y_ratio=0.5, video_height=vh)
    outro_clip = outro_clip.fadein(0.3).fadeout(0.5)

    # 9. Composite
    logger.info("[9/9] 레이어 합성 + 오디오...")
    base_clips = [background, overlay, title_bar_clip, bottom_bar_clip, progress_bar]
    all_clips = (
        [c for c in base_clips if c is not None]
        + subtitle_clips + ve_clips + [outro_clip]
    )
    video = CompositeVideoClip(all_clips, size=(vw, vh)).set_duration(total_duration)

    # Audio mixing
    tts_audio = AudioFileClip(tts_path).set_start(0.0)

    # BGM: data/bgm/ 폴더에서 MP3 로드 (사인파 절대 생성하지 않음)
    bgm_path = _load_bgm(settings.bgm_dir)
    audio_clips = [tts_audio]

    if bgm_path:
        logger.info("BGM 로딩: %s", os.path.basename(bgm_path))
        try:
            bgm_audio = AudioFileClip(bgm_path)

            # BGM 길이를 영상 길이에 맞춤
            if bgm_audio.duration < total_duration:
                bgm_audio = bgm_audio.loop(duration=total_duration)
            else:
                bgm_audio = bgm_audio.subclip(0, total_duration)

            # BGM 볼륨: settings에서 dB 값을 선형 비율로 변환
            bgm_volume_linear = 10 ** (settings.bgm_volume_db / 20)
            bgm_audio = bgm_audio.volumex(bgm_volume_linear)

            # 페이드인 2초 / 페이드아웃 3초
            bgm_audio = bgm_audio.audio_fadein(2.0).audio_fadeout(3.0)

            bgm_audio = bgm_audio.set_duration(total_duration)
            audio_clips.append(bgm_audio)
        except Exception as e:
            logger.warning("BGM 로드 실패: %s - BGM 없이 진행합니다.", e)
    else:
        logger.info("BGM 파일 없음 (data/bgm/ 폴더) - TTS만 사용합니다.")

    final_audio = CompositeAudioClip(audio_clips)
    video = video.set_audio(final_audio)
    # 변경 사유: 인트로 0.3초 페이드인, 아웃트로 0.5초 페이드아웃 (빠른 시작)
    video = video.fadein(0.3).fadeout(0.5)

    # Render
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = re.sub(r'[^\w가-힣]', '_', script.get("title", "shorts"))[:30]
    output_path = os.path.join(settings.output_dir, f"shorts_{safe_title}_{timestamp}.mp4")

    logger.info("렌더링 -> %s", output_path)
    video.write_videofile(
        output_path,
        fps=settings.video_fps,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        bitrate=settings.bitrate,
        logger="bar",
    )

    try:
        video.close()
        tts_audio.close()
        for ac in audio_clips:
            try:
                ac.close()
            except Exception:
                pass
    except Exception:
        pass

    return output_path, edit_style
