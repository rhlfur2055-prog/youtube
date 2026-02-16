"""향상된 TTS 엔진 (ElevenLabs 우선 + edge-tts 폴백).

변경 사유: ElevenLabs v2 API 전면 재작성
- 전체 텍스트를 한 번에 ElevenLabs API로 전송 (문장 분할/결합 제거)
- eleven_multilingual_v2 모델, stability=0.5, similarity_boost=0.8
- OpenAI TTS 완전 제거 (API 키 없음)
- edge-tts 폴백 (3회 재시도, 지수 백오프)
- pydub ffmpeg 경로 자동 설정
- 2-pass loudnorm 마스터링
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from youshorts.config.settings import Settings, get_settings
from youshorts.utils.file_handler import ensure_dir
from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

# Windows 이벤트 루프 정책 설정
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── ffmpeg 경로 설정 (pydub 호환) ──
_FFMPEG_EXE: str | None = None

try:
    import imageio_ffmpeg
    _FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
    if _FFMPEG_EXE and os.path.exists(_FFMPEG_EXE):
        # PATH에 추가
        _ffmpeg_dir = os.path.dirname(_FFMPEG_EXE)
        if _ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

        # pydub 패치
        try:
            import pydub.utils
            import pydub.audio_segment

            _original_which = pydub.utils.which

            def _patched_which(program):
                """imageio_ffmpeg의 ffmpeg를 우선 반환."""
                if program in ("ffmpeg", "ffmpeg.exe", "ffprobe", "ffprobe.exe"):
                    return _FFMPEG_EXE
                return _original_which(program)

            pydub.utils.which = _patched_which
            pydub.audio_segment.AudioSegment.converter = _FFMPEG_EXE
            if hasattr(pydub.audio_segment, "converter"):
                pydub.audio_segment.converter = _FFMPEG_EXE
        except ImportError:
            pass

        logger.info("[ffmpeg] imageio_ffmpeg 사용: %s", _FFMPEG_EXE)
    else:
        _FFMPEG_EXE = shutil.which("ffmpeg")
except ImportError:
    _FFMPEG_EXE = shutil.which("ffmpeg")
    if not _FFMPEG_EXE:
        logger.warning("[ffmpeg] ffmpeg를 찾을 수 없습니다")

# ── TTS 전처리 (자막은 원본 유지, TTS 음성에만 적용) ──

def preprocess_script_for_tts(text: str) -> str:
    """TTS용 전처리. 초성/줄임말 제거, 쉼표로 자연스러운 끊김.

    자막에는 원본 텍스트 그대로 표시 (ㅋㅋ, ㄹㅇ 포함).
    TTS 음성에만 이 전처리된 버전을 사용합니다.

    Args:
        text: 원본 대본 텍스트.

    Returns:
        TTS용으로 전처리된 텍스트.
    """
    result = text
    # 초성 반복 제거 (TTS가 못 읽으니 빼기)
    result = re.sub(r"ㅋ{2,}", "", result)
    result = re.sub(r"ㅎ{2,}", "", result)
    result = re.sub(r"ㅠ{2,}", "", result)
    result = re.sub(r"ㄷ{2,}", "", result)
    # 인터넷 줄임말 제거
    result = result.replace("ㄹㅇ", "")
    result = result.replace("ㅇㅈ", "")
    result = result.replace("ㄱㄱ", "")
    result = result.replace("ㅇㅇ", "")
    result = result.replace("ㅂㅂ", "")
    result = result.replace("ㄴㄴ", "")
    # ".." / "..." → 쉼표 (자연스러운 끊김)
    result = result.replace("...", ", ")
    result = result.replace("..", ", ")
    # 연속 쉼표 정리
    result = re.sub(r",\s*,+", ",", result)
    # 연속 공백 정리
    result = re.sub(r"\s+", " ", result)
    return result.strip()


# ── 캐시 디렉토리 ──
CACHE_DIR = Path("cache/tts")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── API 사용량 추적 ──
_usage_stats = {
    "elevenlabs_chars": 0,
    "edge_calls": 0,
    "cache_hits": 0,
}


def _get_cache_path(text: str, provider: str = "elevenlabs") -> Path:
    """텍스트+제공자 조합으로 캐시 키 생성."""
    key = f"{text}|{provider}"
    hash_val = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{hash_val}.mp3"


def _check_cache(cache_path: Path, max_age_days: int = 30) -> bool:
    """캐시 존재 + 만료 확인."""
    if not cache_path.exists():
        return False
    age_seconds = time.time() - cache_path.stat().st_mtime
    return age_seconds < max_age_days * 86400


def log_usage_stats() -> None:
    """API 사용량 통계를 로깅합니다."""
    logger.info("TTS 사용량: %s", _usage_stats)
    el_cost = _usage_stats["elevenlabs_chars"] * 0.00018
    logger.info("ElevenLabs 예상 비용: $%.3f", el_cost)


def _get_ffmpeg_exe() -> str:
    """ffmpeg 실행 파일 경로를 반환합니다."""
    return _FFMPEG_EXE or "ffmpeg"


def _get_audio_duration_ffmpeg(audio_path: str) -> float:
    """ffmpeg로 오디오 길이를 측정합니다.

    Args:
        audio_path: 오디오 파일 경로.

    Returns:
        오디오 길이 (초).
    """
    try:
        cmd = [_get_ffmpeg_exe(), "-i", audio_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        if match:
            hours, minutes, seconds = match.groups()
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except Exception as e:
        logger.warning("ffmpeg 길이 측정 실패: %s", e)

    # 폴백: moviepy
    try:
        from moviepy.editor import AudioFileClip
    except ImportError:
        from moviepy import AudioFileClip

    clip = AudioFileClip(audio_path)
    duration = clip.duration
    clip.close()
    return duration


# ────────────────────────────────────────────────────────────────
# ElevenLabs TTS (전체 텍스트 한 번에 전송)
# ────────────────────────────────────────────────────────────────

def _generate_elevenlabs_full_text(
    text: str,
    output_path: str,
    voice_id: str = "",
    stability: float = 0.5,
    similarity_boost: float = 0.8,
) -> str:
    """ElevenLabs v2 API로 전체 텍스트를 한 번에 TTS 생성합니다.

    변경 사유: 문장 분할+결합 방식 제거, 전체 텍스트 단일 요청

    Args:
        text: 변환할 전체 텍스트.
        output_path: 출력 파일 경로.
        voice_id: ElevenLabs 음성 ID (빈 문자열이면 기본값 사용).
        stability: 음성 안정성 (0.0~1.0).
        similarity_boost: 음색 유사도 (0.0~1.0).

    Returns:
        생성된 오디오 파일 경로.

    Raises:
        RuntimeError: ElevenLabs API 호출 실패 시.
    """
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings

    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY 환경변수가 설정되지 않았습니다")

    # 음성 ID: 환경변수 > 파라미터 > 기본값
    # eleven_multilingual_v2 한국어 지원 음성:
    # - "21m00Tcm4TlvDq8ikWAM" (Rachel - 여성, 다국어)
    # - "pNInz6obpgDQGcFmaJgB" (Adam - 남성, 다국어)
    voice = os.getenv("ELEVENLABS_VOICE_ID", "") or voice_id or "pNInz6obpgDQGcFmaJgB"

    client = ElevenLabs(api_key=api_key)

    # 변경 사유: ElevenLabs 한국어 쇼츠 최적화
    # stability 0.35 (더 감정적), similarity 0.85, style 0.3 (스타일 표현)
    audio_generator = client.text_to_speech.convert(
        text=text,
        voice_id=voice,
        model_id="eleven_multilingual_v2",
        voice_settings=VoiceSettings(
            stability=0.35,
            similarity_boost=0.85,
            style=0.3,
            use_speaker_boost=True,
        ),
        output_format="mp3_44100_128",
    )

    # 제너레이터에서 바이트 수집 후 파일 저장
    audio_bytes = b""
    for chunk in audio_generator:
        if isinstance(chunk, bytes):
            audio_bytes += chunk

    if not audio_bytes:
        raise RuntimeError("ElevenLabs API 응답이 비어있습니다")

    with open(output_path, "wb") as f:
        f.write(audio_bytes)

    # 사용량 추적
    global _usage_stats
    _usage_stats["elevenlabs_chars"] += len(text)

    file_size = os.path.getsize(output_path)
    logger.info(
        "ElevenLabs TTS 생성 완료: %d자, %.1fKB",
        len(text), file_size / 1024,
    )
    return output_path


# ────────────────────────────────────────────────────────────────
# OpenAI TTS (2순위 폴백 - tts-1-hd)
# ────────────────────────────────────────────────────────────────

def _generate_openai_tts_full_text(
    text: str,
    output_path: str,
    voice: str = "onyx",
    model: str = "tts-1-hd",
) -> str:
    """OpenAI TTS API로 전체 텍스트를 한 번에 TTS 생성합니다.

    ElevenLabs 실패 시 2순위 폴백으로 사용됩니다.

    Args:
        text: 변환할 전체 텍스트.
        output_path: 출력 파일 경로.
        voice: OpenAI TTS 음성 (onyx/nova/shimmer/alloy/echo/fable).
        model: OpenAI TTS 모델 (tts-1 | tts-1-hd).

    Returns:
        생성된 오디오 파일 경로.

    Raises:
        RuntimeError: OpenAI TTS API 호출 실패 시.
    """
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다")

    client = OpenAI(api_key=api_key)

    # 전체 텍스트를 한 번에 전송 (최대 4096자)
    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=text[:4096],
        response_format="mp3",
    )

    response.stream_to_file(output_path)

    file_size = os.path.getsize(output_path)
    if file_size < 1024:
        raise RuntimeError(f"OpenAI TTS 파일 크기 부족: {file_size} bytes")

    logger.info(
        "OpenAI TTS 생성 완료: %d자, %.1fKB (모델: %s, 음성: %s)",
        len(text), file_size / 1024, model, voice,
    )
    return output_path


# ────────────────────────────────────────────────────────────────
# edge-tts 폴백 (3순위 - 전체 텍스트 한 번에 생성)
# ────────────────────────────────────────────────────────────────

def _generate_edge_tts_full_text(
    text: str,
    output_path: str,
    voice: str = "ko-KR-SunHiNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> str:
    """edge-tts로 전체 텍스트를 한 번에 TTS 생성합니다 (3회 재시도).

    Args:
        text: 변환할 전체 텍스트.
        output_path: 출력 파일 경로.
        voice: TTS 음성.
        rate: 속도.
        pitch: 피치.

    Returns:
        생성된 오디오 파일 경로.

    Raises:
        RuntimeError: 모든 재시도 실패 시.
    """
    import edge_tts

    max_attempts = 3
    backoff_delays = [2, 4, 8]

    for attempt in range(1, max_attempts + 1):
        try:
            communicate = edge_tts.Communicate(
                text, voice=voice, rate=rate, pitch=pitch,
            )
            asyncio.run(communicate.save(output_path))

            global _usage_stats
            _usage_stats["edge_calls"] += 1

            if attempt > 1:
                logger.info("edge-tts 성공 (시도 %d/%d)", attempt, max_attempts)

            return output_path

        except Exception as e:
            error_msg = str(e)
            is_retryable = any(
                kw in error_msg for kw in
                ("503", "Invalid response", "Connection", "Timeout")
            )

            if not is_retryable:
                raise RuntimeError(f"edge-tts 실패 (재시도 불가): {e}")

            if attempt < max_attempts:
                delay = backoff_delays[attempt - 1]
                logger.warning(
                    "edge-tts 실패 (시도 %d/%d): %s - %d초 후 재시도",
                    attempt, max_attempts, error_msg[:100], delay,
                )
                time.sleep(delay)
            else:
                raise RuntimeError(
                    f"edge-tts 최종 실패 ({max_attempts}회): {e}"
                )

    raise RuntimeError("edge-tts 생성 실패")


# ────────────────────────────────────────────────────────────────
# 마스터링 (2-pass loudnorm, -14 LUFS)
# ────────────────────────────────────────────────────────────────

def master_audio(input_path: str, output_path: str) -> str:
    """오디오 마스터링 (2-pass loudnorm, -14 LUFS).

    Args:
        input_path: 입력 오디오 경로.
        output_path: 출력 오디오 경로.

    Returns:
        마스터링된 오디오 파일 경로.
    """
    import json as _json

    ffmpeg_exe = _get_ffmpeg_exe()

    try:
        # Pass 1: 현재 음량 측정
        measure_cmd = [
            ffmpeg_exe, "-i", input_path,
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-",
        ]
        measure_result = subprocess.run(
            measure_cmd, capture_output=True, timeout=60,
        )
        stderr_text = measure_result.stderr.decode("utf-8", errors="ignore")

        json_matches = list(
            re.finditer(r'\{[^{}]*"input_i"[^{}]*\}', stderr_text, re.DOTALL)
        )
        if not json_matches:
            raise ValueError("loudnorm JSON 출력 파싱 실패")

        measured = _json.loads(json_matches[-1].group(0))
        measured_I = measured.get("input_i", "-14.0")
        measured_TP = measured.get("input_tp", "-1.5")
        measured_LRA = measured.get("input_lra", "11.0")
        measured_thresh = measured.get("input_thresh", "-24.0")

        # Pass 2: 정밀 정규화
        normalize_cmd = [
            ffmpeg_exe, "-y", "-i", input_path,
            "-af", (
                "highpass=f=80,"
                "equalizer=f=1000:width_type=o:width=2:g=2,"
                "acompressor=threshold=-20dB:ratio=4:attack=5:release=50,"
                f"loudnorm=I=-14:TP=-1.5:LRA=11:"
                f"measured_I={measured_I}:"
                f"measured_TP={measured_TP}:"
                f"measured_LRA={measured_LRA}:"
                f"measured_thresh={measured_thresh}:"
                f"linear=true"
            ),
            "-ar", "44100", "-ac", "1",
            output_path,
        ]
        subprocess.run(normalize_cmd, capture_output=True, check=True, timeout=120)
        logger.info("마스터링 완료 (2-pass, -14 LUFS)")
        return output_path

    except Exception as e:
        logger.warning("2-pass 마스터링 실패: %s - 1-pass 시도", e)
        try:
            fallback_cmd = [
                ffmpeg_exe, "-y", "-i", input_path,
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-ar", "44100", "-ac", "1",
                output_path,
            ]
            subprocess.run(
                fallback_cmd, capture_output=True, check=True, timeout=120,
            )
            logger.info("마스터링 완료 (1-pass 폴백)")
            return output_path
        except Exception as e2:
            logger.warning("1-pass 마스터링도 실패: %s - 원본 사용", e2)
            return input_path


# ────────────────────────────────────────────────────────────────
# 속도 조절
# ────────────────────────────────────────────────────────────────

def _adjust_speed_with_ffmpeg(
    audio_path: str,
    speed_factor: float,
    output_path: str,
) -> str:
    """ffmpeg atempo 필터로 오디오 속도를 조절합니다."""
    # 변경 사유: 최소 속도 0.80 → 0.95 상향 (한국 쇼츠는 빠른 말투가 표준)
    speed_factor = max(0.95, min(1.25, speed_factor))
    try:
        cmd = [
            _get_ffmpeg_exe(), "-y",
            "-i", audio_path,
            "-filter:a", f"atempo={speed_factor:.4f}",
            "-vn", output_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        return output_path
    except Exception as e:
        logger.warning("속도 조절 실패: %s", e)
        return audio_path


# ────────────────────────────────────────────────────────────────
# 단어 그룹 타이밍 추정
# ────────────────────────────────────────────────────────────────

def _estimate_word_groups(
    text: str,
    audio_path: str,
    chunk_size: int = 10,
) -> list[dict[str, Any]]:
    """텍스트 길이 비율로 단어 그룹 타이밍을 추정합니다.

    Args:
        text: 전체 텍스트.
        audio_path: 오디오 파일 경로.
        chunk_size: 자막 청크 크기 (글자 수).

    Returns:
        단어 그룹 타이밍 리스트.
    """
    total_duration = _get_audio_duration_ffmpeg(audio_path)

    # 글자 수 기준 청크 분할
    words = text.split()
    if not words:
        return [{"start": 0.0, "end": total_duration, "text": text}]

    chunks: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip() if current else word
        if len(test.replace(" ", "")) <= chunk_size + 2:
            current = test
        else:
            if current:
                chunks.append(current)
            current = word
    if current:
        chunks.append(current)

    if not chunks:
        return [{"start": 0.0, "end": total_duration, "text": text}]

    # 각 청크의 글자 수 비율로 시간 분배
    char_counts = [len(c.replace(" ", "")) for c in chunks]
    total_chars = sum(char_counts)

    groups: list[dict[str, Any]] = []
    current_time = 0.0
    for i, chunk in enumerate(chunks):
        ratio = char_counts[i] / total_chars if total_chars > 0 else 1.0 / len(chunks)
        duration = ratio * total_duration
        groups.append({
            "start": current_time,
            "end": current_time + duration,
            "text": chunk,
        })
        current_time += duration

    return groups


# ────────────────────────────────────────────────────────────────
# 메인 파이프라인 호환 래퍼
# ────────────────────────────────────────────────────────────────

def generate_fitted_tts(
    text: str,
    target_duration: float,
    emotion_segments: list[dict[str, Any]] | None = None,
    subtitle_chunks: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> tuple[str, list[dict[str, Any]], float]:
    """Pipeline 호환 TTS 생성 래퍼.

    ElevenLabs 우선 → edge-tts 폴백.
    전체 텍스트를 한 번에 전송하여 끊김 없는 자연스러운 음성을 생성합니다.

    변경 사유: 문장 분할/결합 제거, ElevenLabs 전체 텍스트 단일 요청
    3회 재시도, 2초 간격

    Args:
        text: TTS 변환할 전체 텍스트.
        target_duration: 목표 길이 (초).
        emotion_segments: 감정 세그먼트 (미사용, 호환성 유지).
        subtitle_chunks: 자막 청크 (pause_ms 포함, 선택).
        settings: 설정 인스턴스.

    Returns:
        (오디오 경로, 단어 그룹 리스트, 실제 길이).
    """
    if settings is None:
        settings = get_settings()

    ensure_dir(settings.temp_dir)
    chunk_size = getattr(settings, "subtitle_chunk_size", 10)

    # ── TTS 전처리 (자막은 원본 text 유지, TTS 음성에만 적용) ──
    tts_text = preprocess_script_for_tts(text)
    logger.debug("TTS 전처리: %d자 → %d자", len(text), len(tts_text))

    # ── 캐시 확인 ──
    cache_enabled = getattr(settings, "tts_cache_enabled", True)
    cache_path = _get_cache_path(text, "elevenlabs")
    if cache_enabled and _check_cache(cache_path):
        _usage_stats["cache_hits"] += 1
        logger.info("TTS 캐시 히트 (%d자)", len(text))
        audio_path = os.path.join(settings.temp_dir, "tts_cached.mp3")
        shutil.copy(str(cache_path), audio_path)
        actual_duration = _get_audio_duration_ffmpeg(audio_path)
        word_groups = _estimate_word_groups(text, audio_path, chunk_size)
        return audio_path, word_groups, actual_duration

    # ── TTS 생성 (3회 재시도, 2초 간격) ──
    max_retries = 3
    audio_path = os.path.join(settings.temp_dir, "tts_raw.mp3")
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            # 3단계 폴백 체인: ElevenLabs → OpenAI TTS → edge-tts
            tts_generated = False

            # 1순위: ElevenLabs (전체 텍스트 한 번에)
            elevenlabs_key = os.getenv("ELEVENLABS_API_KEY", "")
            if elevenlabs_key and not tts_generated:
                try:
                    _generate_elevenlabs_full_text(
                        text=tts_text,
                        output_path=audio_path,
                        voice_id=getattr(settings, "elevenlabs_voice_id", ""),
                        stability=0.5,
                        similarity_boost=0.8,
                    )
                    logger.info("ElevenLabs TTS 사용 (전체 텍스트 단일 요청)")
                    tts_generated = True
                except Exception as el_err:
                    logger.warning(
                        "ElevenLabs 실패 (시도 %d): %s - OpenAI TTS 폴백 시도",
                        attempt, el_err,
                    )

            # 2순위: OpenAI TTS (tts-1-hd, 폴백)
            openai_key = os.getenv("OPENAI_API_KEY", "")
            if openai_key and not tts_generated:
                try:
                    _generate_openai_tts_full_text(
                        text=tts_text,
                        output_path=audio_path,
                        voice=getattr(settings, "openai_tts_voice", "onyx"),
                        model=getattr(settings, "openai_tts_model", "tts-1-hd"),
                    )
                    logger.info("OpenAI TTS 폴백 사용 (tts-1-hd)")
                    tts_generated = True
                except Exception as oai_err:
                    logger.warning(
                        "OpenAI TTS 실패 (시도 %d): %s - edge-tts 최종 폴백",
                        attempt, oai_err,
                    )

            # 3순위: edge-tts (최종 폴백, 무료)
            if not tts_generated:
                _generate_edge_tts_full_text(
                    text=tts_text,
                    output_path=audio_path,
                    voice=settings.tts_voice,
                    rate=settings.tts_rate,
                    pitch=settings.tts_pitch,
                )
                logger.info("edge-tts 최종 폴백 사용 (전체 텍스트)")

            # 무결성 검증
            if not os.path.exists(audio_path):
                raise RuntimeError("TTS 파일 생성 실패")
            file_size = os.path.getsize(audio_path)
            if file_size < 1024:
                raise RuntimeError(f"TTS 파일 크기 부족: {file_size} bytes")

            if attempt > 1:
                logger.info("TTS 생성 성공 (시도 %d/%d)", attempt, max_retries)

            break  # 성공

        except Exception as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(
                    "TTS 생성 실패 (시도 %d/%d): %s - 2초 후 재시도",
                    attempt, max_retries, e,
                )
                time.sleep(2)
            else:
                raise RuntimeError(
                    f"TTS 생성 최종 실패 ({max_retries}회): {last_error}"
                )

    # ── 마스터링 ──
    mastering_enabled = getattr(settings, "tts_mastering_enabled", True)
    if mastering_enabled:
        mastered_path = os.path.join(settings.temp_dir, "tts_mastered.mp3")
        audio_path = master_audio(audio_path, mastered_path)

    # ── 실제 길이 측정 ──
    actual_duration = _get_audio_duration_ffmpeg(audio_path)

    # ── 속도 조절 (목표와 5초 이상 차이나면) ──
    # 변경 사유: 속도 하한 0.95, 글자수 기반 목표 속도 자동 계산
    # 350자 이하 → 1.0x / 350~450자 → 1.05x / 450자+ → 1.1x
    text_len = len(text) if text else 0
    if text_len > 450:
        target_speed = 1.10
    elif text_len > 350:
        target_speed = 1.05
    else:
        target_speed = 1.0

    if abs(actual_duration - target_duration) > 3.0 and actual_duration > 0:
        speed_factor = actual_duration / target_duration
        # 글자수 기반 최소 속도 적용
        speed_factor = max(max(0.95, target_speed), min(1.25, speed_factor))

        adjusted_path = os.path.join(settings.temp_dir, "tts_speed_adjusted.mp3")
        result_path = _adjust_speed_with_ffmpeg(audio_path, speed_factor, adjusted_path)

        if result_path != audio_path:
            audio_path = result_path
            actual_duration = _get_audio_duration_ffmpeg(audio_path)
            logger.info("속도 조절 (x%.2f): %.1f초", speed_factor, actual_duration)

    # ── 단어 그룹 타이밍 추정 ──
    word_groups = _estimate_word_groups(text, audio_path, chunk_size)

    # ── pause_ms 무음 삽입 (subtitle_chunks에서) ──
    if subtitle_chunks:
        paused_path = os.path.join(settings.temp_dir, "tts_with_pauses.mp3")
        audio_path, word_groups = _inject_subtitle_pauses(
            audio_path, word_groups, subtitle_chunks, paused_path,
        )
        actual_duration = _get_audio_duration_ffmpeg(audio_path)

    # ── 캐시 저장 ──
    if cache_enabled:
        try:
            shutil.copy(audio_path, str(cache_path))
        except Exception:
            pass

    # ── 사용량 통계 ──
    log_usage_stats()

    logger.info(
        "Enhanced TTS 완료: %.1f초 (목표: %.1f초)",
        actual_duration, target_duration,
    )
    return audio_path, word_groups, actual_duration


def _inject_subtitle_pauses(
    audio_path: str,
    word_groups: list[dict[str, Any]],
    subtitle_chunks: list[dict[str, Any]],
    output_path: str,
) -> tuple[str, list[dict[str, Any]]]:
    """subtitle_chunks의 pause_ms를 오디오에 무음으로 삽입합니다."""
    pauses = [
        (c.get("text", ""), c.get("pause_ms", 0))
        for c in subtitle_chunks
        if c.get("pause_ms", 0) > 0
    ]
    if not pauses:
        return audio_path, word_groups

    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(audio_path)
    except Exception as e:
        logger.warning("pause 오디오 로드 실패: %s", e)
        return audio_path, word_groups

    total_pause_added = 0
    for pause_text, pause_ms in pauses:
        for i, wg in enumerate(word_groups):
            if pause_text in wg.get("text", "") or wg.get("text", "") in pause_text:
                insert_ms = int(wg["start"] * 1000) + total_pause_added
                silence = AudioSegment.silent(duration=pause_ms)
                audio = audio[:insert_ms] + silence + audio[insert_ms:]

                shift_sec = pause_ms / 1000.0
                for j in range(i, len(word_groups)):
                    word_groups[j]["start"] += shift_sec
                    word_groups[j]["end"] += shift_sec

                total_pause_added += pause_ms
                break

    if total_pause_added > 0:
        audio.export(output_path, format="mp3")
        logger.info("pause_ms 총 %dms 삽입 완료", total_pause_added)
        return output_path, word_groups

    return audio_path, word_groups
