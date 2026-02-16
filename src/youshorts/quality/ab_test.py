"""A/B 테스트 모듈.

같은 주제로 스타일이 다른 영상 2개를 생성 후
독창성/품질을 비교합니다.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from youshorts.config.settings import Settings, get_settings
from youshorts.quality.originality import _compute_similarity
from youshorts.utils.file_handler import ensure_dir, write_json
from youshorts.utils.logger import get_logger

logger = get_logger(__name__)


def select_ab_styles(current_style: str = "creative") -> dict[str, dict[str, str]]:
    """A/B 테스트용 두 가지 다른 스타일을 선택합니다.

    Args:
        current_style: 기본 스타일.

    Returns:
        {"A": {script_style, edit_style}, "B": {script_style, edit_style}}.
    """
    contrasts = {
        "creative": "analytical",
        "analytical": "emotional",
        "emotional": "humorous",
        "humorous": "expert",
        "expert": "creative",
    }
    style_b = contrasts.get(current_style, "analytical")

    edit_style_pairs = [
        ("dynamic", "cinematic"),
        ("infographic", "storytelling"),
        ("energetic", "cinematic"),
    ]
    edit_a, edit_b = random.choice(edit_style_pairs)

    return {
        "A": {"script_style": current_style, "edit_style": edit_a},
        "B": {"script_style": style_b, "edit_style": edit_b},
    }


def compare_versions(
    script_a: dict[str, Any],
    script_b: dict[str, Any],
    score_a: int,
    score_b: int,
) -> dict[str, Any]:
    """두 버전의 독창성/품질을 비교합니다.

    Args:
        script_a: A 버전 대본.
        script_b: B 버전 대본.
        score_a: A 버전 품질 점수.
        score_b: B 버전 품질 점수.

    Returns:
        비교 결과 딕셔너리.
    """
    comparison: dict[str, Any] = {
        "version_A": {
            "title": script_a.get("title", ""),
            "style": script_a.get("style", ""),
            "unique_angle": script_a.get("unique_angle", ""),
            "quality_score": score_a,
            "char_count": len(script_a.get("full_script", "").replace(" ", "")),
            "keyword_count": len(script_a.get("keywords", [])),
            "source_count": len(script_a.get("fact_sources", [])),
        },
        "version_B": {
            "title": script_b.get("title", ""),
            "style": script_b.get("style", ""),
            "unique_angle": script_b.get("unique_angle", ""),
            "quality_score": score_b,
            "char_count": len(script_b.get("full_script", "").replace(" ", "")),
            "keyword_count": len(script_b.get("keywords", [])),
            "source_count": len(script_b.get("fact_sources", [])),
        },
        "recommendation": "A" if score_a >= score_b else "B",
    }

    sim = _compute_similarity(
        script_a.get("full_script", ""),
        script_b.get("full_script", ""),
    )
    comparison["mutual_similarity"] = round(sim * 100, 1)
    comparison["diversity_score"] = round((1 - sim) * 100, 1)

    return comparison


def save_ab_report(
    comparison: dict[str, Any],
    topic: str,
    settings: Settings | None = None,
) -> str:
    """A/B 테스트 결과를 저장합니다.

    Args:
        comparison: 비교 결과.
        topic: 영상 주제.
        settings: 설정 인스턴스.

    Returns:
        저장된 리포트 파일 경로.
    """
    if settings is None:
        settings = get_settings()

    ensure_dir(settings.logs_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"{settings.logs_dir}/ab_test_{timestamp}.json"

    report = {
        "topic": topic,
        "timestamp": datetime.now().isoformat(),
        "comparison": comparison,
    }
    write_json(report_path, report)

    return report_path


def log_ab_comparison(comparison: dict[str, Any]) -> None:
    """A/B 비교 결과를 로깅합니다.

    Args:
        comparison: 비교 결과.
    """
    logger.info("")
    logger.info("  ┌─────────────────────────────────────────────┐")
    logger.info("  │            A/B 테스트 결과                   │")
    logger.info("  ├─────────────────────────────────────────────┤")

    for version in ["version_A", "version_B"]:
        v = comparison[version]
        label = "A" if version == "version_A" else "B"
        logger.info("  │ [%s] %s", label, v["title"][:25])
        logger.info("  │     스타일: %s", v["style"])
        logger.info("  │     품질: %d/100", v["quality_score"])
        logger.info("  │     관점: %s", v["unique_angle"][:30])
        logger.info("  │")

    logger.info("  │ 두 버전 유사도: %s%%", comparison["mutual_similarity"])
    logger.info("  │ 다양성 점수: %s%%", comparison["diversity_score"])
    logger.info("  │ 추천 버전: %s", comparison["recommendation"])
    logger.info("  └─────────────────────────────────────────────┘")
