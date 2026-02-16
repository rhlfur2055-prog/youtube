# 변경 사유: --source-url, --no-pexels CLI 플래그 추가 (커뮤니티 썰 모드)
"""CLI (Command Line Interface) 모듈.

argparse 기반 CLI를 제공하며, 파이프라인을 오케스트레이션합니다.
트렌드 분석, 경쟁 채널 분석, AI 품질 체크, 커뮤니티 썰 모드를 포함합니다.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from typing import Any

from youshorts import __version__
from youshorts.config.settings import get_settings
from youshorts.config.styles import EDIT_STYLES, SCRIPT_STYLES
from youshorts.security.secrets_manager import SecretsManager
from youshorts.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


def _print_banner(args: argparse.Namespace) -> None:
    """시작 배너를 출력합니다."""
    settings = get_settings()
    pexels_key = SecretsManager.get_secret_value(settings.pexels_api_key)
    apify_token = SecretsManager.get_secret_value(settings.apify_api_token)
    google_key = SecretsManager.get_secret_value(settings.google_api_key)
    anthropic_key = SecretsManager.get_secret_value(settings.anthropic_api_key)

    llm_status = "Gemini" if google_key else ("Claude" if anthropic_key else "미설정")

    logger.info("")
    logger.info("=" * 60)
    logger.info("   YouTube Shorts Generator v%s", __version__)
    logger.info("   유튜브 숏츠 자동 생성기 (수익창출 정책 준수)")
    logger.info("=" * 60)
    logger.info("   주제: %s", args.topic)
    logger.info("   스타일: %s", args.style)
    logger.info(
        "   목표: %d초 | %dx%d",
        settings.target_duration,
        settings.video_width,
        settings.video_height,
    )
    source_url = getattr(args, "source_url", None)
    no_pexels = getattr(args, "no_pexels", False)
    logger.info("   LLM: %s", llm_status)
    logger.info("   A/B 테스트: %s", "ON" if args.ab_test else "OFF")
    logger.info("   Pexels: %s", "비활성" if no_pexels else ("활성" if pexels_key else "미설정"))
    logger.info("   Apify: %s", "활성" if apify_token else "미설정")
    if source_url:
        logger.info("   소스 URL: %s", source_url)
    logger.info("=" * 60)
    logger.info("")


def _run_suggest_topics(args: argparse.Namespace) -> None:
    """트렌드 기반 주제 추천 모드."""
    from youshorts.research.trend_scraper import suggest_topics

    region = getattr(args, "trend_region", "KR")
    logger.info("트렌드 기반 주제 추천 (지역: %s)", region)
    logger.info("")

    topics = suggest_topics(region=region, count=10)
    for i, topic in enumerate(topics, 1):
        logger.info("  %d. %s", i, topic)

    logger.info("")
    logger.info("위 주제로 영상을 생성하려면:")
    logger.info('  youshorts --topic "주제" --style creative')


def _run_competitor_analysis(args: argparse.Namespace) -> None:
    """경쟁 채널 분석 모드."""
    from youshorts.research.trend_scraper import analyze_competitor

    channel_url = args.competitor
    logger.info("경쟁 채널 분석: %s", channel_url)
    logger.info("")

    result = analyze_competitor(channel_url, max_videos=10)

    logger.info("채널: %s", result["channel"])
    logger.info("분석 영상 수: %d", result["total_videos"])
    logger.info("평균 조회수: %d", result["avg_views"])
    logger.info("")

    if result["top_keywords"]:
        logger.info("자주 사용하는 키워드:")
        for kw in result["top_keywords"][:5]:
            logger.info("  - %s", kw)

    logger.info("")
    if result["videos"]:
        logger.info("최근 영상:")
        for video in result["videos"][:5]:
            logger.info(
                "  [%d회] %s",
                video.get("views", 0),
                video.get("title", ""),
            )


def _run_single(args: argparse.Namespace) -> dict[str, Any]:
    """단일 영상 생성 모드."""
    from youshorts.core.pipeline import Pipeline

    settings = get_settings()

    # --tts-engine CLI 옵션으로 오버라이드
    if hasattr(args, "tts_engine") and args.tts_engine:
        object.__setattr__(settings, "tts_engine", args.tts_engine)
        logger.info(f"TTS 엔진: {args.tts_engine} (CLI 오버라이드)")

    pipeline = Pipeline(
        topic=args.topic or "",
        style=args.style,
        edit_style=args.edit_style,
        quality_ai=getattr(args, "quality_ai", False),
        source_url=getattr(args, "source_url", "") or "",
        no_pexels=getattr(args, "no_pexels", False),
        settings=settings,
    )
    result = pipeline.run()

    return {
        "script": result.script,
        "output_path": result.output_path,
        "score": result.quality_score,
        "metadata": result.metadata,
        "meta_path": result.meta_path,
        "edit_style": result.edit_style,
    }


def _run_ab_test(args: argparse.Namespace) -> None:
    """A/B 테스트 모드."""
    from youshorts.core.pipeline import Pipeline
    from youshorts.quality.ab_test import (
        compare_versions,
        log_ab_comparison,
        save_ab_report,
        select_ab_styles,
    )

    settings = get_settings()

    # --tts-engine CLI 옵션으로 오버라이드
    if hasattr(args, "tts_engine") and args.tts_engine:
        object.__setattr__(settings, "tts_engine", args.tts_engine)
        logger.info(f"TTS 엔진: {args.tts_engine} (CLI 오버라이드)")

    logger.info("=" * 60)
    logger.info("   A/B 테스트 모드 - 두 가지 스타일로 생성")
    logger.info("=" * 60)

    styles = select_ab_styles(args.style)

    # Version A
    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "   Version A: %s + %s",
        styles["A"]["script_style"],
        styles["A"]["edit_style"],
    )
    logger.info("=" * 60)

    pipeline_a = Pipeline(
        topic=args.topic,
        style=styles["A"]["script_style"],
        edit_style=styles["A"]["edit_style"],
        label="A",
        settings=settings,
    )
    result_a = pipeline_a.run()

    # Clean temp for B
    try:
        shutil.rmtree(settings.temp_dir, ignore_errors=True)
    except Exception:
        pass

    # Version B
    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "   Version B: %s + %s",
        styles["B"]["script_style"],
        styles["B"]["edit_style"],
    )
    logger.info("=" * 60)

    pipeline_b = Pipeline(
        topic=args.topic,
        style=styles["B"]["script_style"],
        edit_style=styles["B"]["edit_style"],
        label="B",
        settings=settings,
    )
    result_b = pipeline_b.run()

    # Compare
    comparison = compare_versions(
        result_a.script, result_b.script,
        result_a.quality_score, result_b.quality_score,
    )
    report_path = save_ab_report(comparison, args.topic)
    log_ab_comparison(comparison)

    logger.info("")
    logger.info("  A/B 리포트 저장: %s", report_path)
    logger.info("  Version A: %s", result_a.output_path)
    logger.info("  Version B: %s", result_b.output_path)


def main() -> None:
    """CLI 메인 진입점."""
    parser = argparse.ArgumentParser(
        description="YouTube Shorts 자동 생성기 v2.0 (수익창출 정책 준수)",
    )
    parser.add_argument(
        "--topic", "-t",
        default=None,
        help="영상 주제 (예: '한국인 99%%가 모르는 생활꿀팁 TOP5')",
    )
    parser.add_argument(
        "--style", "-s",
        default="creative",
        choices=SCRIPT_STYLES,
        help="대본 스타일 (default: creative)",
    )
    parser.add_argument(
        "--ab-test",
        action="store_true",
        help="A/B 테스트: 두 가지 스타일로 영상 생성 후 비교",
    )
    parser.add_argument(
        "--edit-style", "-e",
        default=None,
        choices=EDIT_STYLES,
        help="편집 스타일 (미지정 시 랜덤)",
    )
    parser.add_argument(
        "--suggest-topics",
        action="store_true",
        help="Apify 트렌드 기반 주제 추천 (영상 생성 없이)",
    )
    parser.add_argument(
        "--competitor",
        default=None,
        help="경쟁 채널 URL 분석 (예: https://youtube.com/@channel)",
    )
    parser.add_argument(
        "--auto-topic",
        action="store_true",
        help="트렌드 기반 자동 주제 선정 후 영상 생성",
    )
    parser.add_argument(
        "--trend-region",
        default="KR",
        help="트렌드 분석 지역 코드 (default: KR)",
    )
    parser.add_argument(
        "--quality-ai",
        action="store_true",
        help="Claude AI를 활용한 심층 품질 체크 활성화",
    )
    parser.add_argument(
        "--source-url",
        default=None,
        help="커뮤니티 게시글 URL (크롤링 → 썰 대본 생성)",
    )
    parser.add_argument(
        "--no-pexels",
        action="store_true",
        help="Pexels 비활성화, 그라데이션 배경 사용",
    )
    parser.add_argument(
        "--tts-engine",
        default=None,
        choices=["enhanced", "legacy"],
        help="TTS 엔진 선택: enhanced (ElevenLabs/OpenAI) | legacy (edge-tts)",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()

    # 설정 로드
    settings = get_settings()

    # 로깅 초기화
    setup_logging(log_dir=settings.logs_dir)

    # 트렌드 기반 주제 추천 모드
    if args.suggest_topics:
        _run_suggest_topics(args)
        return

    # 경쟁 채널 분석 모드
    if args.competitor:
        _run_competitor_analysis(args)
        return

    # --source-url 사용 시 style 미지정이면 자동으로 community 설정
    if args.source_url and args.style == "creative":
        args.style = "community"
        logger.info("--source-url 사용: 스타일 자동 설정 → community")

    # 자동 주제 선정 모드
    if args.auto_topic:
        from youshorts.research.trend_scraper import suggest_topics

        logger.info("트렌드 기반 자동 주제 선정 중...")
        topics = suggest_topics(
            region=getattr(args, "trend_region", "KR"),
            count=1,
        )
        if topics:
            args.topic = topics[0]
            logger.info("선정된 주제: %s", args.topic)
        else:
            logger.error("트렌드 분석 실패 - --topic 옵션으로 직접 주제를 지정해주세요.")
            sys.exit(1)

    # topic 필수 체크 (영상 생성 모드) - source_url이 있으면 topic 없어도 OK
    if not args.topic and not args.source_url:
        logger.error("--topic, --auto-topic, 또는 --source-url 옵션이 필요합니다.")
        parser.print_help()
        sys.exit(1)

    # API 키 검증 (Google API 키 또는 Anthropic API 키 중 하나 필요)
    google_key = SecretsManager.get_secret_value(settings.google_api_key)
    anthropic_key = SecretsManager.get_secret_value(settings.anthropic_api_key)

    if not google_key and not anthropic_key:
        logger.error("GOOGLE_API_KEY 또는 ANTHROPIC_API_KEY 환경변수를 설정해주세요.")
        logger.error("  set GOOGLE_API_KEY=AIza...  (Gemini, 무료)")
        logger.error("  set ANTHROPIC_API_KEY=sk-ant-...  (Claude)")
        sys.exit(1)

    if anthropic_key and not google_key:
        if not SecretsManager.validate_anthropic_key(anthropic_key):
            logger.error("ANTHROPIC_API_KEY 형식이 올바르지 않습니다.")
            sys.exit(1)

    _print_banner(args)
    start_time = time.time()

    if args.ab_test:
        _run_ab_test(args)
    else:
        result = _run_single(args)

    # Cleanup
    logger.info("")
    logger.info("임시 파일 정리...")
    try:
        shutil.rmtree(settings.temp_dir, ignore_errors=True)
    except Exception:
        pass

    # Done
    elapsed = time.time() - start_time
    logger.info("")
    logger.info("=" * 60)
    logger.info("   COMPLETE!")
    logger.info("=" * 60)
    if not args.ab_test:
        logger.info("   제목: %s", result["script"]["title"])
        logger.info("   파일: %s", result["output_path"])
        logger.info("   메타: %s", result["meta_path"])
        logger.info("   품질: %d/100", result["score"])
        logger.info("   편집: %s", result["edit_style"])
    logger.info("   소요: %.0f초", elapsed)
    logger.info("   AI 공시: 메타데이터에 포함")
    logger.info("=" * 60)
    logger.info("")
