# 변경 사유: Shotstack 렌더링용 SRT 자막 파일 자동 생성 유틸
"""SRT 자막 파일 생성 유틸리티.

TTS 워드 타이밍 데이터를 기반으로 SRT 형식의 자막 파일을 생성합니다.
한 번에 최대 10~12자를 표시하며, TTS 음성과 정확히 동기화됩니다.
"""

from __future__ import annotations

import os
from typing import Any

from youshorts.utils.logger import get_logger

logger = get_logger(__name__)


def _format_srt_time(seconds: float) -> str:
    """초 단위 시간을 SRT 타임스탬프 형식으로 변환합니다.

    Args:
        seconds: 시간 (초).

    Returns:
        "HH:MM:SS,mmm" 형식 문자열.
    """
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt_from_words(
    word_groups: list[dict[str, Any]],
    output_path: str,
    max_chars: int = 12,
) -> str:
    """워드 그룹 타이밍에서 SRT 자막 파일을 생성합니다.

    Args:
        word_groups: TTS 워드 그룹 리스트 [{start, end, text}, ...].
        output_path: SRT 파일 저장 경로.
        max_chars: 한 자막당 최대 글자 수 (기본 12자).

    Returns:
        생성된 SRT 파일 경로.
    """
    if not word_groups:
        logger.warning("워드 그룹이 비어있어 SRT 생성을 건너뜁니다.")
        # 빈 SRT 파일 생성 (Shotstack 에러 방지)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("")
        return output_path

    # SRT 항목 생성
    srt_entries: list[str] = []
    index = 1

    for group in word_groups:
        start = group.get("start", 0.0)
        end = group.get("end", start + 1.0)
        text = group.get("text", "").strip()

        if not text:
            continue

        # 너무 긴 텍스트는 분할
        if len(text.replace(" ", "")) > max_chars:
            # 단어 단위로 분할하여 max_chars 이내로 묶기
            words = text.split()
            sub_groups = _split_into_chunks(words, max_chars)
            chunk_duration = (end - start) / max(len(sub_groups), 1)

            for i, chunk_text in enumerate(sub_groups):
                chunk_start = start + i * chunk_duration
                chunk_end = start + (i + 1) * chunk_duration

                entry = (
                    f"{index}\n"
                    f"{_format_srt_time(chunk_start)} --> {_format_srt_time(chunk_end)}\n"
                    f"{chunk_text}\n"
                )
                srt_entries.append(entry)
                index += 1
        else:
            entry = (
                f"{index}\n"
                f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n"
                f"{text}\n"
            )
            srt_entries.append(entry)
            index += 1

    # SRT 파일 쓰기
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_entries))

    logger.info("SRT 자막 생성: %d개 항목 → %s", len(srt_entries), output_path)
    return output_path


def _split_into_chunks(words: list[str], max_chars: int) -> list[str]:
    """단어 리스트를 max_chars 이내 청크로 분할합니다.

    Args:
        words: 단어 리스트.
        max_chars: 청크당 최대 글자 수 (공백 제외).

    Returns:
        청크 텍스트 리스트.
    """
    chunks: list[str] = []
    current = ""
    current_chars = 0

    for word in words:
        word_chars = len(word.replace(" ", ""))
        if current_chars + word_chars > max_chars and current:
            chunks.append(current.strip())
            current = word
            current_chars = word_chars
        else:
            current = f"{current} {word}".strip() if current else word
            current_chars += word_chars

    if current:
        chunks.append(current.strip())

    return chunks
