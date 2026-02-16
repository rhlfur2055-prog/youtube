"""독창성 보장 모듈.

TF-IDF + 코사인 유사도로 기존 영상과의 유사도를 체크하고,
영상 생성 히스토리를 관리합니다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from youshorts.config.settings import Settings, get_settings
from youshorts.config.styles import EDIT_STYLES
from youshorts.utils.file_handler import ensure_dir, read_json, write_json
from youshorts.utils.logger import get_logger

logger = get_logger(__name__)


def _compute_similarity(text_a: str, text_b: str) -> float:
    """두 텍스트 간 유사도를 계산합니다.

    sklearn이 있으면 TF-IDF + 코사인 유사도,
    없으면 자카드 유사도를 사용합니다.

    Args:
        text_a: 첫 번째 텍스트.
        text_b: 두 번째 텍스트.

    Returns:
        유사도 (0.0 ~ 1.0).
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer()
        tfidf = vectorizer.fit_transform([text_a, text_b])
        sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
        return float(sim)
    except ImportError:
        # Fallback: Jaccard similarity
        set_a = set(text_a.split())
        set_b = set(text_b.split())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)


def check_originality(
    script: dict[str, Any],
    settings: Settings | None = None,
) -> tuple[bool, float, str]:
    """기존 영상과의 유사도를 체크합니다.

    Args:
        script: 대본 딕셔너리.
        settings: 설정 인스턴스.

    Returns:
        (is_original, max_similarity, similar_title).
    """
    if settings is None:
        settings = get_settings()

    ensure_dir(settings.data_dir)
    history: list[dict[str, Any]] = read_json(settings.history_file, default=[])

    if not history:
        return True, 0.0, ""

    new_text = script.get("full_script", "") + " " + script.get("title", "")
    max_sim = 0.0
    similar_title = ""

    for entry in history:
        old_text = entry.get("script", "") + " " + entry.get("title", "")
        sim = _compute_similarity(new_text, old_text)
        if sim > max_sim:
            max_sim = sim
            similar_title = entry.get("title", "")

    is_original = max_sim < 0.70
    return is_original, max_sim, similar_title


def save_to_history(
    script: dict[str, Any],
    edit_style: str,
    output_path: str,
    settings: Settings | None = None,
) -> None:
    """생성된 영상 정보를 히스토리에 저장합니다.

    Args:
        script: 대본 딕셔너리.
        edit_style: 사용된 편집 스타일.
        output_path: 출력 파일 경로.
        settings: 설정 인스턴스.
    """
    if settings is None:
        settings = get_settings()

    ensure_dir(settings.data_dir)
    history: list[dict[str, Any]] = read_json(settings.history_file, default=[])

    entry = {
        "timestamp": datetime.now().isoformat(),
        "title": script.get("title", ""),
        "script": script.get("full_script", ""),
        "style": script.get("style", ""),
        "edit_style": edit_style,
        "unique_angle": script.get("unique_angle", ""),
        "keywords": script.get("keywords", []),
        "output_path": output_path,
    }
    history.append(entry)
    write_json(settings.history_file, history)

    # 스타일 로그
    style_log: list[dict[str, Any]] = read_json(settings.style_log_file, default=[])
    style_entry = {
        "timestamp": datetime.now().isoformat(),
        "title": script.get("title", ""),
        "script_style": script.get("style", ""),
        "edit_style": edit_style,
        "angle": script.get("angle", ""),
        "subtitle_sections": ["hook", "content", "opinion", "twist", "conclusion"],
        "visual_effects_count": len(script.get("keywords", [])),
    }
    style_log.append(style_entry)
    write_json(settings.style_log_file, style_log)

    logger.info("히스토리 저장 완료")


def get_unused_styles(
    settings: Settings | None = None,
) -> tuple[list[str], list[str]]:
    """최근에 사용하지 않은 스타일 조합을 반환합니다.

    Args:
        settings: 설정 인스턴스.

    Returns:
        (사용 가능한 편집 스타일, 사용 가능한 대본 스타일).
    """
    if settings is None:
        settings = get_settings()

    history: list[dict[str, Any]] = read_json(settings.history_file, default=[])
    recent = history[-5:] if len(history) >= 5 else history

    used_edit_styles = {e.get("edit_style") for e in recent}
    used_script_styles = {e.get("style") for e in recent}

    available_edit = [s for s in EDIT_STYLES if s not in used_edit_styles]
    if not available_edit:
        available_edit = list(EDIT_STYLES)

    script_styles = ["creative", "analytical", "emotional", "humorous", "expert"]
    available_script = [s for s in script_styles if s not in used_script_styles]
    if not available_script:
        available_script = script_styles

    return available_edit, available_script
