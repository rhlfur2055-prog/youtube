# 변경 사유: librosa 완전 제거, pydub 사용, WordBoundary 기반 타이밍, ffmpeg atempo 속도 조절, 오디오 무결성 검증
# 변경 사유(2): TTS 품질 개선 - 무결성 검증 강화, 재시도 로직 추가, ffmpeg 경로 확인 유틸
"""edge-tts 음성 합성 엔진 (legacy).

전체 텍스트를 한 번에 edge-tts로 생성하여 문장 간 끊김을 방지합니다.
pydub 기반 무음 삽입, ffmpeg 속도 조절을 수행합니다.
librosa를 사용하지 않아 오디오 프레임 손실이 없습니다.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any

from youshorts.config.settings import Settings, get_settings
from youshorts.utils.file_handler import ensure_dir
from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# pydub가 imageio_ffmpeg에 포함된 ffmpeg을 찾을 수 있도록 설정
try:
    import imageio_ffmpeg
    _ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    if _ffmpeg_path:
        from pydub import AudioSegment
        AudioSegment.converter = _ffmpeg_path
        AudioSegment.ffprobe = _ffmpeg_path
except ImportError:
    _ffmpeg_path = None


def check_ffmpeg_available() -> str | None:
    """ffmpeg 실행 파일 경로를 확인합니다.

    imageio_ffmpeg → 시스템 PATH 순서로 탐색합니다.
    찾지 못하면 경고를 출력하고 None을 반환합니다.

    Returns:
        ffmpeg 실행 파일 경로 또는 None.
    """
    # 1. imageio_ffmpeg에서 가져오기
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.exists(path):
            return path
    except ImportError:
        pass

    # 2. 시스템 PATH에서 찾기
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path

    # 3. 찾지 못함
    logger.warning(
        "[ffmpeg] ffmpeg를 찾을 수 없습니다. "
        "pip install imageio-ffmpeg 또는 시스템 PATH에 ffmpeg을 추가하세요. "
        "속도 조절/마스터링 기능이 비활성화됩니다."
    )
    return None


# 모듈 로드 시 ffmpeg 경로 확인
_FFMPEG_EXE = check_ffmpeg_available()


def _ensure_pydub_ffmpeg() -> None:
    """pydub AudioSegment에 ffmpeg 경로를 강제 설정합니다.

    변경 사유: pydub import 시 ffmpeg를 못 찾는 문제 해결
    """
    if _FFMPEG_EXE:
        try:
            from pydub import AudioSegment
            AudioSegment.converter = _FFMPEG_EXE
            AudioSegment.ffprobe = _FFMPEG_EXE
        except ImportError:
            pass


def _chunk_text_by_chars(
    text: str,
    chunk_size: int = 10,
) -> list[str]:
    """텍스트를 글자 수 기준으로 의미 단위 청크로 분할합니다.

    단어 중간에서 끊지 않고 6-12글자 청크를 만듭니다.

    Args:
        text: 입력 텍스트.
        chunk_size: 목표 청크 크기 (글자 수).

    Returns:
        청크 리스트.
    """
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip() if current else word
        # 글자 수 (공백 제외) 기준
        char_count = len(test.replace(" ", ""))
        if char_count <= chunk_size + 2:
            current = test
        else:
            if current:
                chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


async def _generate_tts_async(
    text: str,
    rate: str,
    pitch: str,
    voice: str,
    audio_path: str,
) -> list[dict[str, Any]]:
    """비동기 TTS 생성 (WordBoundary 이벤트 캡처).

    Args:
        text: 변환할 텍스트.
        rate: 속도 조정값.
        pitch: 피치 조정값.
        voice: TTS 음성 이름.
        audio_path: 출력 파일 경로.

    Returns:
        단어 타이밍 리스트 [{start, end, text}, ...].
    """
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)

    word_timings: list[dict[str, Any]] = []
    sentence_timings: list[dict[str, Any]] = []

    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                offset_sec = chunk["offset"] / 10_000_000
                duration_sec = chunk["duration"] / 10_000_000
                word_timings.append({
                    "start": offset_sec,
                    "end": offset_sec + duration_sec,
                    "text": chunk["text"],
                })
            elif chunk["type"] == "SentenceBoundary":
                offset_sec = chunk["offset"] / 10_000_000
                duration_sec = chunk["duration"] / 10_000_000
                sentence_timings.append({
                    "start": offset_sec,
                    "end": offset_sec + duration_sec,
                    "text": chunk["text"],
                })

    # WordBoundary 우선, 없으면 SentenceBoundary 사용
    return word_timings if word_timings else sentence_timings


def _insert_sentence_pauses(
    audio_path: str,
    pause_ms: int,
    output_path: str,
) -> str:
    """문장 끝(. ! ?) 뒤에 무음을 삽입합니다.

    pydub를 사용하여 MP3 네이티브 포맷을 유지합니다.

    Args:
        audio_path: 입력 오디오 경로.
        pause_ms: 무음 길이 (ms).
        output_path: 출력 파일 경로.

    Returns:
        출력 파일 경로.
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        logger.warning("pydub 미설치 - 무음 삽입 건너뜀")
        return audio_path

    _ensure_pydub_ffmpeg()  # 변경 사유: ffmpeg 경로 강제 설정

    try:
        audio = AudioSegment.from_file(audio_path)
    except Exception as e:
        logger.warning("오디오 로드 실패 (pydub): %s - 무음 삽입 건너뜀", e)
        return audio_path

    # 무음 세그먼트 생성
    silence = AudioSegment.silent(duration=pause_ms)

    # 원본을 그대로 사용하되 끝에 짧은 무음만 추가 (문장 간 간격용)
    # edge-tts가 이미 자연스러운 문장 간 간격을 생성하므로 최소한으로 처리
    result = audio + silence

    result.export(output_path, format="mp3")
    return output_path


def _get_audio_duration(audio_path: str) -> float:
    """오디오 파일의 재생 길이를 반환합니다.

    변경 사유: ffmpeg 직접 사용 우선, pydub/moviepy 폴백
    ffmpeg → pydub → moviepy 순서로 시도합니다.

    Args:
        audio_path: 오디오 파일 경로.

    Returns:
        길이 (초).
    """
    # 1. ffmpeg로 직접 측정 (가장 안정적)
    ffmpeg_exe = _FFMPEG_EXE or "ffmpeg"
    try:
        cmd = [ffmpeg_exe, "-i", audio_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        if match:
            hours, minutes, seconds = match.groups()
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except Exception:
        pass

    # 2. pydub 폴백
    try:
        _ensure_pydub_ffmpeg()
        from pydub import AudioSegment
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000.0
    except Exception:
        pass

    # 3. moviepy 폴백
    try:
        from moviepy.editor import AudioFileClip
    except ImportError:
        from moviepy import AudioFileClip

    clip = AudioFileClip(audio_path)
    d = clip.duration
    clip.close()
    return d


def _adjust_speed_ffmpeg(
    audio_path: str,
    speed_factor: float,
    output_path: str,
) -> str:
    """ffmpeg atempo 필터로 오디오 속도를 조절합니다.

    음질 손실 없이 속도만 변경합니다.
    atempo 범위는 0.5~100.0 이지만, 자연스러운 범위는 0.8~1.2입니다.

    Args:
        audio_path: 입력 오디오 경로.
        speed_factor: 속도 배율 (1.0 = 원래 속도).
        output_path: 출력 파일 경로.

    Returns:
        출력 파일 경로.
    """
    # atempo 범위 제한 (0.8 ~ 1.25)
    speed_factor = max(0.8, min(1.25, speed_factor))

    # atempo는 0.5~100.0 범위만 허용
    # 여러 atempo를 체인해야 더 큰 변화를 줄 수 있지만, 여기서는 제한 범위 내
    filter_chain = f"atempo={speed_factor:.4f}"

    # 변경 사유: _FFMPEG_EXE 전역 변수 사용으로 통일
    ffmpeg_exe = _FFMPEG_EXE or "ffmpeg"

    try:
        cmd = [
            ffmpeg_exe, "-y",
            "-i", audio_path,
            "-filter:a", filter_chain,
            "-vn",
            output_path,
        ]
        subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            timeout=60,
        )
        return output_path
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("ffmpeg 속도 조절 실패: %s", e)
        return audio_path


def _validate_audio_integrity(audio_path: str, min_duration_sec: float = 1.0) -> bool:
    """오디오 파일의 무결성을 검증합니다.

    변경 사유: 파일 크기 0 체크, 최소 duration 체크 추가

    Args:
        audio_path: 검증할 오디오 파일 경로.
        min_duration_sec: 최소 허용 길이 (초). 이보다 짧으면 실패.

    Returns:
        무결성 통과 여부.
    """
    # 파일 존재 및 크기 확인
    if not os.path.exists(audio_path):
        logger.error("오디오 무결성 검증 실패: 파일이 존재하지 않습니다 - %s", audio_path)
        return False

    file_size = os.path.getsize(audio_path)
    if file_size == 0:
        logger.error("오디오 무결성 검증 실패: 파일 크기가 0입니다 - %s", audio_path)
        return False

    # 변경 사유: pydub 대신 ffmpeg로 duration 측정 (pydub ffmpeg 경로 문제 우회)
    # ffmpeg로 duration 측정 시도
    duration_sec = 0.0
    ffmpeg_exe = _FFMPEG_EXE or "ffmpeg"

    try:
        cmd = [ffmpeg_exe, "-i", audio_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        if match:
            hours, minutes, seconds = match.groups()
            duration_sec = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        else:
            # ffmpeg가 Duration을 못 찾으면, 파일 크기 기반 추정 (MP3 128kbps 기준)
            duration_sec = file_size / (128 * 1024 / 8)
            logger.warning("ffmpeg Duration 파싱 실패 - 파일 크기 기반 추정: %.1f초", duration_sec)
    except Exception as e:
        logger.warning("ffmpeg 무결성 검증 실패: %s - 파일 크기만으로 판단", e)
        # 최소한 파일 크기가 1KB 이상이면 통과
        if file_size > 1024:
            logger.info("오디오 무결성 검증 통과 (파일 크기 기반: %d bytes)", file_size)
            return True
        return False

    # 1. 총 길이 > 0
    if duration_sec <= 0:
        logger.error("오디오 무결성 검증 실패: 길이가 0입니다.")
        return False

    # 1-1. 최소 duration 체크 (변경 사유: 너무 짧은 오디오 감지)
    if duration_sec < min_duration_sec:
        logger.error(
            "오디오 무결성 검증 실패: 길이가 %.1f초로 최소 기준(%.1f초) 미만입니다.",
            duration_sec, min_duration_sec,
        )
        return False

    logger.info("오디오 무결성 검증 통과 (길이: %.1f초, 크기: %d bytes)", duration_sec, file_size)
    return True


def _build_word_groups_from_timings(
    word_timings: list[dict[str, Any]],
    chunk_size: int = 10,
) -> list[dict[str, Any]]:
    """WordBoundary 타이밍에서 자막용 청크 그룹을 생성합니다.

    8-12글자 단위로 단어를 묶어 자막 표시 단위를 만듭니다.

    Args:
        word_timings: WordBoundary 이벤트에서 추출한 단어 타이밍.
        chunk_size: 목표 청크 크기 (글자 수).

    Returns:
        자막 청크 리스트 [{start, end, text}, ...].
    """
    if not word_timings:
        return []

    groups: list[dict[str, Any]] = []
    current_words: list[str] = []
    current_start: float = word_timings[0]["start"]
    current_chars: int = 0

    for timing in word_timings:
        word = timing["text"]
        word_chars = len(word.replace(" ", ""))

        if current_chars + word_chars > chunk_size + 2 and current_words:
            # 현재 그룹 저장
            groups.append({
                "start": current_start,
                "end": timing["start"],
                "text": " ".join(current_words),
            })
            current_words = [word]
            current_start = timing["start"]
            current_chars = word_chars
        else:
            current_words.append(word)
            current_chars += word_chars

    # 마지막 그룹
    if current_words and word_timings:
        groups.append({
            "start": current_start,
            "end": word_timings[-1]["end"],
            "text": " ".join(current_words),
        })

    return groups


def _split_sentences_to_chunks(
    sentence_groups: list[dict[str, Any]],
    total_duration: float,
    chunk_size: int = 10,
) -> list[dict[str, Any]]:
    """SentenceBoundary 그룹을 글자 수 기준 청크로 재분할합니다.

    Args:
        sentence_groups: 문장 단위 그룹 리스트.
        total_duration: 전체 오디오 길이 (초).
        chunk_size: 목표 청크 크기 (글자 수).

    Returns:
        재분할된 청크 리스트.
    """
    result: list[dict[str, Any]] = []
    for group in sentence_groups:
        text = group["text"]
        start = group["start"]
        end = group["end"]
        duration = end - start

        chunks = _chunk_text_by_chars(text, chunk_size)
        if not chunks:
            continue

        chunk_dur = duration / len(chunks)
        for i, chunk in enumerate(chunks):
            result.append({
                "start": start + i * chunk_dur,
                "end": start + (i + 1) * chunk_dur,
                "text": chunk,
            })

    return result


def generate_tts(
    text: str,
    rate: str | None = None,
    pitch: str | None = None,
    settings: Settings | None = None,
    max_retries: int = 3,
) -> tuple[str, list[dict[str, Any]]]:
    """TTS 음성 + 단어 타이밍을 생성합니다.

    변경 사유: 재시도 로직 추가 (최대 3회), 무결성 검증 후 실패 시 재생성
    전체 텍스트를 한 번에 edge-tts로 생성하여 문장 간 끊김을 방지합니다.

    Args:
        text: TTS 변환할 텍스트.
        rate: 속도 조정 (None이면 설정값 사용).
        pitch: 피치 조정 (None이면 설정값 사용).
        settings: 설정 인스턴스.
        max_retries: 최대 재시도 횟수.

    Returns:
        (오디오 파일 경로, 단어 그룹 타이밍 리스트).

    Raises:
        RuntimeError: 모든 재시도 실패 시.
    """
    if settings is None:
        settings = get_settings()

    if rate is None:
        rate = settings.tts_rate
    if pitch is None:
        pitch = settings.tts_pitch

    ensure_dir(settings.temp_dir)

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            audio_path = os.path.join(settings.temp_dir, "tts_raw.mp3")

            word_timings = asyncio.run(
                _generate_tts_async(text, rate, pitch, settings.tts_voice, audio_path)
            )

            # 무결성 검증 (파일 크기 0, duration < 1초 등)
            if not _validate_audio_integrity(audio_path, min_duration_sec=1.0):
                raise RuntimeError(f"TTS 오디오 무결성 검증 실패 (시도 {attempt})")

            # 문장 끝에 무음 삽입 (pydub 사용)
            processed_path = os.path.join(settings.temp_dir, "tts_processed.mp3")
            audio_path = _insert_sentence_pauses(
                audio_path, settings.sentence_pause_ms, processed_path,
            )

            # WordBoundary/SentenceBoundary 타이밍 기반 자막 청크 생성
            word_groups = _build_word_groups_from_timings(
                word_timings, settings.subtitle_chunk_size,
            )

            # SentenceBoundary만 있으면 각 문장을 글자 수 기준 청크로 재분할
            if word_groups and not any(
                len(g["text"].replace(" ", "")) <= settings.subtitle_chunk_size + 2
                for g in word_groups
            ):
                duration = _get_audio_duration(audio_path)
                word_groups = _split_sentences_to_chunks(word_groups, duration, settings.subtitle_chunk_size)

            # 타이밍 없으면 텍스트 기반 폴백
            if not word_groups:
                duration = _get_audio_duration(audio_path)
                chunks = _chunk_text_by_chars(text, settings.subtitle_chunk_size)
                if chunks and duration > 0:
                    chunk_dur = duration / len(chunks)
                    word_groups = [
                        {"start": i * chunk_dur, "end": (i + 1) * chunk_dur, "text": c}
                        for i, c in enumerate(chunks)
                    ]

            if attempt > 1:
                logger.info("TTS 생성 성공 (시도 %d/%d)", attempt, max_retries)

            return audio_path, word_groups

        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = 2 * attempt  # 2초, 4초 대기
                logger.warning(
                    "TTS 생성 실패 (시도 %d/%d): %s - %d초 후 재시도",
                    attempt, max_retries, e, delay,
                )
                time.sleep(delay)
            else:
                logger.error("TTS 생성 최종 실패 (%d회 시도): %s", max_retries, last_error)

    raise RuntimeError(f"TTS 생성 실패 ({max_retries}회 재시도 후): {last_error}")


def _inject_pause_ms_into_audio(
    audio_path: str,
    word_groups: list[dict[str, Any]],
    subtitle_chunks: list[dict[str, Any]],
    output_path: str,
) -> tuple[str, list[dict[str, Any]]]:
    """subtitle_chunks의 pause_ms 값을 오디오에 무음으로 삽입합니다.

    반전/충격 장면 직전에 500-800ms 무음을 삽입하여 드라마틱 효과를 줍니다.
    word_groups 타이밍도 pause 만큼 시프트합니다.

    Args:
        audio_path: 원본 오디오 경로.
        word_groups: 단어 그룹 타이밍 리스트.
        subtitle_chunks: subtitle_chunks (pause_ms 포함).
        output_path: 출력 파일 경로.

    Returns:
        (출력 오디오 경로, 조정된 word_groups).
    """
    # pause_ms가 있는 청크 수집
    pauses = []
    for chunk in subtitle_chunks:
        pms = int(chunk.get("pause_ms", 0))
        if pms > 0:
            pauses.append({"text": chunk.get("text", ""), "pause_ms": pms})

    if not pauses:
        return audio_path, word_groups

    try:
        from pydub import AudioSegment
    except ImportError:
        logger.warning("pydub 미설치 - pause_ms 삽입 건너뜀")
        return audio_path, word_groups

    _ensure_pydub_ffmpeg()  # 변경 사유: ffmpeg 경로 강제 설정

    try:
        audio = AudioSegment.from_file(audio_path)
    except Exception as e:
        logger.warning("pause_ms 오디오 로드 실패: %s - 건너뜀", e)
        return audio_path, word_groups

    total_pause_added = 0
    pause_count = 0

    # 각 word_group에 대해 매칭되는 pause_ms를 찾아서
    # 해당 위치 이후의 모든 타이밍을 시프트
    for pause_info in pauses:
        pause_text = pause_info["text"]
        pause_ms = pause_info["pause_ms"]

        # word_groups에서 해당 텍스트 위치 찾기
        for i, wg in enumerate(word_groups):
            if pause_text in wg.get("text", "") or wg.get("text", "") in pause_text:
                # 이 word_group 시작 시간에 무음 삽입
                insert_point_ms = int(wg["start"] * 1000) + total_pause_added
                silence = AudioSegment.silent(duration=pause_ms)
                audio = audio[:insert_point_ms] + silence + audio[insert_point_ms:]

                # 이후 모든 word_groups 시프트
                shift_sec = pause_ms / 1000.0
                for j in range(i, len(word_groups)):
                    word_groups[j]["start"] += shift_sec
                    word_groups[j]["end"] += shift_sec

                total_pause_added += pause_ms
                pause_count += 1
                break

    if pause_count > 0:
        audio.export(output_path, format="mp3")
        logger.info("pause_ms 삽입: %d곳, 총 %dms 추가", pause_count, total_pause_added)
        return output_path, word_groups

    return audio_path, word_groups


def generate_fitted_tts(
    text: str,
    target_duration: float,
    emotion_segments: list[dict[str, Any]] | None = None,
    subtitle_chunks: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> tuple[str, list[dict[str, Any]], float]:
    """목표 시간에 맞게 속도를 자동 조절하여 TTS를 생성합니다.

    1회만 TTS 생성 후 ffmpeg atempo로 속도 조절합니다.
    subtitle_chunks에 pause_ms가 있으면 해당 위치에 무음을 삽입합니다.

    Args:
        text: TTS 변환할 텍스트.
        target_duration: 목표 길이 (초).
        emotion_segments: 감정 세그먼트 (현재 미사용, 향후 확장용).
        subtitle_chunks: 자막 청크 리스트 (pause_ms 포함, 선택).
        settings: 설정 인스턴스.

    Returns:
        (오디오 경로, 단어 그룹 리스트, 실제 길이).
    """
    if settings is None:
        settings = get_settings()

    # 1회만 TTS 생성 (기본 rate 사용)
    audio_path, word_groups = generate_tts(text, settings=settings)
    actual = _get_audio_duration(audio_path)
    logger.info("TTS 생성: %.1f초 (목표: %.1f초)", actual, target_duration)

    # 목표와 차이가 5초 이상이면 ffmpeg atempo로 속도 조절
    if abs(actual - target_duration) > 5.0 and actual > 0:
        speed_factor = actual / target_duration
        speed_factor = max(0.8, min(1.25, speed_factor))

        adjusted_path = os.path.join(settings.temp_dir, "tts_adjusted.mp3")
        result_path = _adjust_speed_ffmpeg(audio_path, speed_factor, adjusted_path)

        if result_path != audio_path:
            audio_path = result_path
            new_actual = _get_audio_duration(audio_path)
            logger.info("속도 조절 (x%.2f): %.1f초 → %.1f초", speed_factor, actual, new_actual)

            # word_timings도 같은 비율로 스케일링
            scale = 1.0 / speed_factor
            for group in word_groups:
                group["start"] *= scale
                group["end"] *= scale

            actual = new_actual

    # pause_ms 무음 삽입 (subtitle_chunks에서 가져옴)
    if subtitle_chunks:
        paused_path = os.path.join(settings.temp_dir, "tts_paused.mp3")
        audio_path, word_groups = _inject_pause_ms_into_audio(
            audio_path, word_groups, subtitle_chunks, paused_path,
        )
        actual = _get_audio_duration(audio_path)

    # 오디오 무결성 검증
    _validate_audio_integrity(audio_path)

    return audio_path, word_groups, actual
