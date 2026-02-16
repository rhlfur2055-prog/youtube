#!/usr/bin/env python3
# 변경 사유: AI 슬롭 방지 + 하루 최대 3개 제한 + TTS 음성 로테이션 + 업로드 스케줄링
"""youshorts 대량 생산 자동화 스크립트.

24/7 무인 운영을 위한 영상 대량 생성 스크립트입니다.
AI 슬롭 방지 조치가 적용됩니다:
- 하루 최대 3개 생산 제한
- TTS 음성 로테이션 (3개 음성)
- 대본 템플릿 5종 랜덤
- 영상 길이 45~90초 랜덤
- 최소 4시간 업로드 간격

사용법:
    python mass_produce.py --count 3 --style creative
    python mass_produce.py --count 1 --topic "퇴사 후 현실"
    python mass_produce.py --clean-all
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from youshorts.config.settings import get_settings
from youshorts.core.pipeline import Pipeline, PipelineResult
from youshorts.utils.logger import setup_logging

# ============================================================
# TTS 음성 로테이션 (AI 슬롭 방지 - 3개 음성 사용)
# ============================================================
_EDGE_TTS_VOICES: list[str] = [
    "ko-KR-InJoonNeural",   # 남성 (차분한, 기본)
    "ko-KR-HyunsuNeural",   # 남성 (에너지 있는)
    "ko-KR-SunHiNeural",    # 여성 (밝고 자연스러운)
]

_ELEVENLABS_VOICE_IDS: list[str] = [
    "pNInz6obpgDQGcFmaJgB",  # Adam (남성, 깊은 목소리)
    "21m00Tcm4TlvDq8ikWAM",  # Rachel (여성, 부드러운)
    "ErXwobaYiN019PkySvjV",  # Antoni (남성, 따뜻한)
]

# ============================================================
# 자막 스타일 로테이션 (AI 슬롭 방지)
# ============================================================
_SUBTITLE_STYLES: list[dict[str, str | int]] = [
    {"font": "NanumSquareRoundEB", "size_max": 90, "size_min": 70, "color": "white"},
    {"font": "NanumSquareRoundEB", "size_max": 80, "size_min": 65, "color": "#FFD700"},
    {"font": "NanumSquareRoundEB", "size_max": 85, "size_min": 68, "color": "#00FFFF"},
]


def _rotate_tts_voice(settings: object, index: int) -> None:
    """TTS 음성을 로테이션합니다 (AI 슬롭 방지).

    Args:
        settings: 설정 인스턴스.
        index: 현재 영상 인덱스.
    """
    # edge-tts 음성 로테이션
    voice = _EDGE_TTS_VOICES[index % len(_EDGE_TTS_VOICES)]
    object.__setattr__(settings, "tts_voice", voice)

    # ElevenLabs 음성 로테이션
    el_voice = _ELEVENLABS_VOICE_IDS[index % len(_ELEVENLABS_VOICE_IDS)]
    object.__setattr__(settings, "elevenlabs_voice_id", el_voice)

    logger = logging.getLogger("youshorts")
    logger.info("TTS 음성: %s (ElevenLabs: %s)", voice, el_voice[:8] + "...")


def _rotate_subtitle_style(settings: object, index: int) -> None:
    """자막 스타일을 로테이션합니다 (AI 슬롭 방지).

    Args:
        settings: 설정 인스턴스.
        index: 현재 영상 인덱스.
    """
    style = _SUBTITLE_STYLES[index % len(_SUBTITLE_STYLES)]
    object.__setattr__(settings, "subtitle_font", style["font"])
    object.__setattr__(settings, "subtitle_font_size_max", style["size_max"])
    object.__setattr__(settings, "subtitle_font_size_min", style["size_min"])
    object.__setattr__(settings, "subtitle_color", style["color"])


def _randomize_duration(settings: object) -> None:
    """영상 길이를 랜덤화합니다 (45~90초, AI 슬롭 방지).

    Args:
        settings: 설정 인스턴스.
    """
    duration = random.randint(45, 90)
    object.__setattr__(settings, "target_duration", duration)

    logger = logging.getLogger("youshorts")
    logger.info("영상 목표 길이: %d초 (랜덤)", duration)


def run_single_production(
    topic: str | None,
    style: str,
    tts_engine: str,
    no_pexels: bool,
    renderer: str | None = None,
    production_index: int = 0,
) -> tuple[bool, PipelineResult | None]:
    """단일 영상 생성을 실행합니다.

    AI 슬롭 방지:
    - TTS 음성 로테이션
    - 자막 스타일 로테이션
    - 영상 길이 랜덤화

    Args:
        topic: 주제 (None이면 자동 선정).
        style: 대본 스타일.
        tts_engine: TTS 엔진 ("enhanced" | "legacy").
        no_pexels: Pexels 비활성화 여부.
        renderer: 렌더러 ("shotstack" | "moviepy" | None=auto).
        production_index: 현재 생산 인덱스 (로테이션용).

    Returns:
        (성공 여부, PipelineResult).
    """
    logger = logging.getLogger("youshorts")

    # 주제 자동 선정 (커뮤니티 크롤러 → 폴백 → 수동)
    source_text = ""
    if not topic:
        from youshorts.core.script_generator import select_topic
        topic_info = select_topic(topic_override=None, style=style)
        # select_topic()은 dict 반환: {title, body, source}
        if isinstance(topic_info, dict):
            topic = topic_info.get("title", "")
            source_text = topic_info.get("body", "")
            source_name = topic_info.get("source", "unknown")
        else:
            # 호환성: 혹시 str이 반환되면
            topic = topic_info
            source_name = "legacy"

    logger.info("=" * 60)
    logger.info(f"영상 생성 시작: {topic}")
    if source_text:
        logger.info(f"  소스: {source_name} ({len(source_text)}자)")
    logger.info(f"스타일: {style}, TTS: {tts_engine}, 렌더러: {renderer or 'auto'}")
    logger.info("=" * 60)

    try:
        settings = get_settings()

        # TTS 엔진 오버라이드
        if tts_engine:
            object.__setattr__(settings, "tts_engine", tts_engine)

        # 렌더러 오버라이드
        if renderer:
            object.__setattr__(settings, "renderer", renderer)

        # AI 슬롭 방지: 로테이션 적용
        _rotate_tts_voice(settings, production_index)
        _rotate_subtitle_style(settings, production_index)
        _randomize_duration(settings)

        pipeline = Pipeline(
            topic=topic,
            style=style,
            no_pexels=no_pexels,
            renderer=renderer,
            settings=settings,
            source_text=source_text,
        )

        result = pipeline.run()

        if result.success:
            logger.info("=" * 60)
            logger.info(f"영상 생성 완료: {result.output_path}")
            logger.info(f"  제목: {result.metadata.get('title', topic)}")
            logger.info(f"  길이: {result.tts_duration:.1f}초")
            logger.info(f"  품질: {result.quality_score}/100")
            logger.info(f"  템플릿: {result.script.get('template_used', '알수없음')}")
            logger.info("=" * 60)
            return True, result
        else:
            logger.error("영상 생성 실패")
            return False, result

    except KeyboardInterrupt:
        logger.warning("사용자 중단")
        raise
    except Exception as e:
        logger.error(f"영상 생성 실패: {e}", exc_info=True)
        return False, None


def _try_upload(
    result: PipelineResult,
    upload_mode: str,
    video_index: int = 0,
) -> None:
    """영상 업로드를 시도합니다.

    Args:
        result: 파이프라인 결과.
        upload_mode: "upload" (즉시) 또는 "schedule" (예약).
        video_index: 영상 순번 (예약 간격 계산용).
    """
    _logger = logging.getLogger("youshorts")
    try:
        from youshorts.core.youtube_uploader import YouTubeUploader

        uploader = YouTubeUploader()
        if not uploader.authenticate():
            _logger.warning("YouTube 인증 실패 - 업로드 스킵")
            return

        if upload_mode == "schedule":
            url = uploader.upload_with_schedule(
                result.output_path,
                result.metadata,
                video_index=video_index,
            )
        else:
            url = uploader.upload_short(
                result.output_path,
                result.metadata,
            )

        if url:
            _logger.info("YouTube 업로드 성공: %s", url)
        else:
            _logger.warning("YouTube 업로드 실패 (스킵)")
    except Exception as e:
        _logger.warning("YouTube 업로드 에러 (스킵): %s", e)


def mass_produce(
    count: int | None,
    style: str,
    tts_engine: str,
    no_pexels: bool,
    delay: int,
    max_retries: int,
    topic_override: str | None = None,
    renderer: str | None = None,
    max_per_day: int = 3,
    upload_mode: str = "none",
) -> None:
    """대량 생산을 실행합니다.

    AI 슬롭 방지 조치:
    - 하루 최대 3개 제한 (기본값)
    - TTS 음성 로테이션
    - 자막 스타일 로테이션
    - 영상 길이 랜덤화
    - 최소 4시간 업로드 간격

    Args:
        count: 생성할 영상 개수 (None이면 무한).
        style: 대본 스타일.
        tts_engine: TTS 엔진.
        no_pexels: Pexels 비활성화 여부.
        delay: 영상 간 대기 시간 (초).
        max_retries: 실패 시 최대 재시도 횟수.
        topic_override: 고정 주제 (None이면 자동 선정).
        renderer: 렌더러 ("shotstack" | "moviepy" | None=auto).
        max_per_day: 하루 최대 생산 개수 (기본 3).
    """
    logger = logging.getLogger("youshorts")

    # 하루 최대 생산 제한 체크
    from youshorts.core.script_generator import check_daily_limit
    if not check_daily_limit(max_per_day=max_per_day):
        logger.warning("하루 최대 생산 제한 도달 - 내일 다시 실행하세요")
        return

    logger.info("=" * 60)
    logger.info("youshorts 대량 생산 시작")
    logger.info(f"목표: {count if count else '무한'}개, 스타일: {style}, TTS: {tts_engine}")
    logger.info(f"렌더러: {renderer or 'auto'}")
    logger.info(f"하루 최대: {max_per_day}개 (AI 슬롭 방지)")
    if topic_override:
        logger.info(f"고정 주제: {topic_override}")
    logger.info(f"재시도: {max_retries}회, 지연: {delay}초")
    logger.info("=" * 60)

    produced = 0
    failed = 0
    infinite_mode = count is None

    # 실제 count를 하루 최대로 제한
    if count is not None:
        from youshorts.core.script_generator import _get_today_production_count
        settings = get_settings()
        today_count = _get_today_production_count(settings)
        remaining = max_per_day - today_count
        if count > remaining:
            logger.warning(
                "요청 %d개 → %d개로 제한 (오늘 이미 %d개 생산)",
                count, remaining, today_count,
            )
            count = max(remaining, 0)
            if count == 0:
                return

    try:
        while infinite_mode or produced < count:
            # 매 반복마다 하루 제한 재확인
            if not check_daily_limit(max_per_day=max_per_day):
                logger.info("하루 최대 생산 제한 도달 - 생산 종료")
                break

            iteration = produced + failed + 1
            topic = topic_override  # None이면 run_single_production에서 자동 선정

            logger.info(f"\n[{iteration}번째 시도]")

            # 재시도 로직
            success = False
            for attempt in range(1, max_retries + 1):
                if attempt > 1:
                    logger.warning(f"재시도 {attempt}/{max_retries}...")

                success, result = run_single_production(
                    topic=topic,
                    style=style,
                    tts_engine=tts_engine,
                    no_pexels=no_pexels,
                    renderer=renderer,
                    production_index=produced + failed,
                )

                if success:
                    produced += 1
                    # YouTube 업로드 (옵션)
                    if upload_mode != "none" and result and result.success:
                        _try_upload(result, upload_mode, produced - 1)
                    break

                if attempt < max_retries:
                    retry_delay = min(delay * attempt, 300)
                    logger.warning(f"{retry_delay}초 후 재시도...")
                    time.sleep(retry_delay)

            if not success:
                failed += 1
                logger.error(f"{max_retries}회 재시도 후에도 실패")

            # 진행 상황 출력
            logger.info(f"\n현재 진행: 성공 {produced}개, 실패 {failed}개")

            # 다음 영상까지 대기 (최소 4시간 간격 옵션)
            if infinite_mode or produced < count:
                actual_delay = max(delay, 60)  # 최소 1분
                logger.info(f"{actual_delay}초 대기 중...")
                time.sleep(actual_delay)

    except KeyboardInterrupt:
        logger.warning("\n\n사용자 중단 (Ctrl+C)")
    finally:
        logger.info("=" * 60)
        logger.info("대량 생산 종료")
        logger.info(f"총 성공: {produced}개, 실패: {failed}개")
        if produced > 0:
            success_rate = produced / (produced + failed) * 100
            logger.info(f"성공률: {success_rate:.1f}%")
        logger.info("=" * 60)


def main() -> None:
    """메인 실행 함수."""
    parser = argparse.ArgumentParser(
        description="youshorts 대량 생산 자동화 (AI 슬롭 방지 적용)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-c", "--count",
        type=int,
        default=None,
        help="생성할 영상 개수 (미지정 시 무한, 하루 최대 3개 제한)",
    )

    parser.add_argument(
        "-s", "--style",
        choices=["creative", "humorous", "emotional", "expert", "analytical", "community"],
        default="creative",
        help="대본 스타일",
    )

    parser.add_argument(
        "-t", "--topic",
        type=str,
        default=None,
        help="영상 주제 (미지정 시 트렌드 자동 선정)",
    )

    parser.add_argument(
        "--tts-engine",
        choices=["enhanced", "legacy"],
        default="enhanced",
        help="TTS 엔진 (enhanced: 고품질 유료 / legacy: 무료)",
    )

    parser.add_argument(
        "--no-pexels",
        action="store_true",
        help="Pexels 비활성화 (그라데이션 배경 사용)",
    )

    parser.add_argument(
        "--renderer",
        choices=["shotstack", "moviepy", "auto"],
        default="auto",
        help="렌더러 선택 (shotstack: 클라우드 / moviepy: 로컬 / auto)",
    )

    parser.add_argument(
        "-d", "--delay",
        type=int,
        default=60,
        help="영상 간 대기 시간 (초, 최소 60초)",
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="실패 시 최대 재시도 횟수",
    )

    parser.add_argument(
        "--max-per-day",
        type=int,
        default=3,
        help="하루 최대 생산 개수 (AI 슬롭 방지, 기본 3개)",
    )

    parser.add_argument(
        "--schedule-interval",
        type=int,
        default=14400,
        help="업로드 간격 (초, 기본 4시간=14400초)",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="상세 로그 출력 (DEBUG 레벨)",
    )

    # ── YouTube 업로드 옵션 ──
    upload_group = parser.add_mutually_exclusive_group()
    upload_group.add_argument(
        "--upload",
        action="store_true",
        default=False,
        help="생성 즉시 YouTube 업로드",
    )
    upload_group.add_argument(
        "--schedule",
        action="store_true",
        default=False,
        help="4시간 간격 예약 업로드",
    )
    upload_group.add_argument(
        "--no-upload",
        action="store_true",
        default=True,
        help="생성만, 업로드 안 함 (기본값)",
    )

    parser.add_argument(
        "--clean",
        action="store_true",
        help="비정상 MP4 파일만 삭제 (30MB 미만, 30초 미만, 0KB)",
    )

    parser.add_argument(
        "--clean-all",
        action="store_true",
        help="비정상 파일 + 임시파일(_work_*, __pycache__, temp/) 전부 삭제",
    )

    args = parser.parse_args()

    # 로깅 설정
    log_level = logging.DEBUG if args.verbose else logging.INFO
    settings = get_settings()
    setup_logging(level=log_level, log_dir=settings.logs_dir)

    # --clean 또는 --clean-all 모드
    if args.clean or args.clean_all:
        from youshorts.utils.file_cleaner import CleanupManager
        cleaner = CleanupManager(settings=settings)
        result = cleaner.clean_all()
        if args.clean_all:
            cleaner2 = CleanupManager(settings=settings)
            result2 = cleaner2.clean_temp()
        return

    # 스케줄링 간격이 delay보다 크면 delay를 스케줄링 간격으로 설정
    delay = max(args.delay, 60)
    if args.schedule_interval > delay and args.count and args.count > 1:
        delay = args.schedule_interval
        logging.getLogger("youshorts").info(
            "업로드 간격 적용: %d초 (%.1f시간)", delay, delay / 3600,
        )

    # 업로드 모드 결정
    upload_mode = "none"
    if args.upload:
        upload_mode = "upload"
    elif args.schedule:
        upload_mode = "schedule"

    # 대량 생산 실행
    mass_produce(
        count=args.count,
        style=args.style,
        tts_engine=args.tts_engine,
        no_pexels=args.no_pexels,
        delay=delay,
        max_retries=args.max_retries,
        topic_override=args.topic,
        renderer=args.renderer if args.renderer != "auto" else None,
        max_per_day=args.max_per_day,
        upload_mode=upload_mode,
    )


if __name__ == "__main__":
    main()
