"""BGM 자동 다운로드 및 감정 매칭 모듈.

data/bgm/ 폴더가 비어있으면 Pixabay에서 저작권 무료 BGM을 다운로드합니다.
대본 감정 분석을 통해 적절한 BGM을 자동 매칭합니다.
"""

from __future__ import annotations

import glob
import os
import random
from typing import Any

from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

# BGM 장르별 Pixabay 검색 키워드 (무료 다운로드)
_BGM_GENRES: dict[str, list[str]] = {
    "tension": ["suspense", "thriller", "mystery", "dark ambient"],
    "emotion": ["emotional piano", "sad background", "touching music", "sentimental"],
    "comedy": ["funny background", "comedy music", "playful", "quirky"],
    "daily": ["lo-fi", "chill background", "calm ambient", "relaxing"],
    "shock": ["dramatic", "epic trailer", "impact", "cinematic dark"],
}

# 대본 감정 → BGM 장르 매핑
_EMOTION_TO_GENRE: dict[str, str] = {
    "소름": "tension",
    "충격": "shock",
    "미쳤": "shock",
    "반전": "tension",
    "공포": "tension",
    "미스터리": "tension",
    "감동": "emotion",
    "눈물": "emotion",
    "따뜻": "emotion",
    "사랑": "emotion",
    "ㅋㅋ": "comedy",
    "웃기": "comedy",
    "레전드": "comedy",
    "미친": "comedy",
    "빡치": "tension",
    "일상": "daily",
    "꿀팁": "daily",
    "정보": "daily",
}


def match_bgm_genre(script: dict[str, Any]) -> str:
    """대본 감정을 분석하여 적절한 BGM 장르를 반환합니다.

    Args:
        script: 대본 딕셔너리.

    Returns:
        BGM 장르 (tension/emotion/comedy/daily/shock).
    """
    full_text = script.get("full_script", "") + script.get("title", "")
    genre_scores: dict[str, int] = {g: 0 for g in _BGM_GENRES}

    for keyword, genre in _EMOTION_TO_GENRE.items():
        if keyword in full_text:
            genre_scores[genre] += 1

    # 템플릿 기반 보정
    template = script.get("template_used", "")
    if "감동" in template:
        genre_scores["emotion"] += 3
    elif "충격" in template or "반전" in template:
        genre_scores["tension"] += 3
    elif "인싸" in template:
        genre_scores["comedy"] += 3

    # 최고 점수 장르 반환
    best = max(genre_scores, key=genre_scores.get)
    if genre_scores[best] == 0:
        best = "daily"  # 기본값

    logger.info("BGM 장르 매칭: %s (점수: %s)", best, genre_scores)
    return best


def select_bgm(bgm_dir: str, script: dict[str, Any] | None = None) -> str | None:
    """적절한 BGM 파일을 선택합니다.

    장르별 하위 폴더가 있으면 감정 매칭으로 선택,
    없으면 전체에서 랜덤 선택.

    Args:
        bgm_dir: BGM 디렉토리 경로.
        script: 대본 딕셔너리 (감정 매칭용).

    Returns:
        BGM 파일 경로 또는 None.
    """
    if not os.path.isdir(bgm_dir):
        return None

    # 장르별 하위 폴더 확인
    if script:
        genre = match_bgm_genre(script)
        genre_dir = os.path.join(bgm_dir, genre)
        if os.path.isdir(genre_dir):
            files = _list_audio_files(genre_dir)
            if files:
                selected = random.choice(files)
                logger.info("BGM 선택 (장르: %s): %s", genre, os.path.basename(selected))
                return selected

    # 전체에서 랜덤
    files = _list_audio_files(bgm_dir)
    if files:
        selected = random.choice(files)
        logger.info("BGM 선택 (랜덤): %s", os.path.basename(selected))
        return selected

    return None


def _list_audio_files(directory: str) -> list[str]:
    """디렉토리에서 오디오 파일을 검색합니다."""
    files: list[str] = []
    for ext in ("*.mp3", "*.wav", "*.ogg"):
        files.extend(glob.glob(os.path.join(directory, ext)))
    return files


def ensure_bgm_available(bgm_dir: str) -> bool:
    """BGM 폴더에 파일이 있는지 확인합니다.

    비어있으면 사용자에게 안내 메시지를 출력합니다.
    (저작권 이슈로 자동 다운로드 대신 안내 방식 채택)

    Args:
        bgm_dir: BGM 디렉토리 경로.

    Returns:
        BGM 파일 존재 여부.
    """
    os.makedirs(bgm_dir, exist_ok=True)
    files = _list_audio_files(bgm_dir)

    if files:
        logger.info("BGM 파일 %d개 확인됨", len(files))
        return True

    logger.info(
        "BGM 파일 없음 - TTS만 사용합니다. "
        "저작권 무료 BGM을 data/bgm/ 폴더에 넣으면 자동 적용됩니다. "
        "(추천: Pixabay Music, Artlist 무료 플랜)"
    )
    return False
