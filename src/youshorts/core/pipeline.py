# 변경 사유: v3.0 스크린샷 배경 시스템 통합, scene_hint 지원
"""파이프라인 오케스트레이터.

(크롤링+스크린샷 →) 대본 생성 → 품질 검사 → 독창성 체크 → TTS →
배경 다운로드 → 영상 합성 → 메타데이터 → 히스토리 저장.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from youshorts.config.settings import Settings, get_settings
from youshorts.utils.file_handler import ensure_dir
from youshorts.utils.logger import get_logger, set_pipeline_step

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    """파이프라인 실행 결과."""

    script: dict[str, Any] = field(default_factory=dict)
    output_path: str = ""
    quality_score: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    meta_path: str = ""
    edit_style: str = ""
    tts_path: str = ""
    tts_duration: float = 0.0
    bg_paths: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    ai_quality: dict[str, Any] = field(default_factory=dict)
    source_text: str = ""

    @property
    def success(self) -> bool:
        """영상이 성공적으로 생성되었는지 여부."""
        return bool(self.output_path)


class Pipeline:
    """YouTube Shorts 생성 파이프라인.

    각 단계를 순차적으로 실행하며, 체크포인트를 지원합니다.
    """

    def __init__(
        self,
        topic: str,
        style: str = "creative",
        edit_style: str | None = None,
        label: str = "",
        quality_ai: bool = False,
        source_url: str = "",
        source_text: str = "",
        no_pexels: bool = False,
        renderer: str | None = None,
        settings: Settings | None = None,
        on_step_start: Callable[[str], None] | None = None,
        on_step_complete: Callable[[str], None] | None = None,
    ) -> None:
        """파이프라인을 초기화합니다.

        Args:
            topic: 영상 주제.
            style: 대본 스타일.
            edit_style: 편집 스타일 (None이면 랜덤).
            label: 표시 라벨 (A/B 테스트용).
            quality_ai: AI 심층 품질 분석 활성화 여부.
            source_url: 크롤링할 커뮤니티 게시글 URL.
            source_text: 커뮤니티 크롤러에서 가져온 원본 텍스트.
            no_pexels: Pexels 비활성화 (그라데이션 배경 사용).
            renderer: 렌더러 선택 ("shotstack" | "moviepy" | None=auto).
            settings: 설정 인스턴스.
            on_step_start: 단계 시작 콜백.
            on_step_complete: 단계 완료 콜백.
        """
        self.topic = topic
        self.style = style
        # community 스타일은 기본 edit_style을 storytelling으로 강제
        if edit_style is None and style == "community":
            self.edit_style = "storytelling"
        else:
            self.edit_style = edit_style
        self.label = label
        self.quality_ai = quality_ai
        self.source_url = source_url
        self.source_text = source_text  # 커뮤니티 크롤러 원본
        self.no_pexels = no_pexels
        self.renderer = renderer  # 렌더러 선택 (shotstack / moviepy / None=auto)
        self.settings = settings or get_settings()
        self.on_step_start = on_step_start
        self.on_step_complete = on_step_complete
        self.result = PipelineResult()

        # no_pexels 오버라이드
        if self.no_pexels:
            object.__setattr__(self.settings, "use_pexels", False)

    def _step(self, step_num: int, total: int, name: str) -> None:
        """파이프라인 단계 진입을 로깅합니다."""
        prefix = f"[{self.label}] " if self.label else ""
        step_label = f"{prefix}[{step_num}/{total}] {name}"
        set_pipeline_step(step_label)
        if self.on_step_start:
            self.on_step_start(step_label)

    def _step_done(self, step_num: int, total: int, name: str) -> None:
        """파이프라인 단계 완료를 알립니다."""
        if self.on_step_complete:
            prefix = f"[{self.label}] " if self.label else ""
            self.on_step_complete(f"{prefix}[{step_num}/{total}] {name}")

    def run(self) -> PipelineResult:
        """전체 파이프라인을 실행합니다.

        변경 사유: 생성 전 임시파일 정리, 생성 후 비정상 파일 정리 통합

        Returns:
            PipelineResult 인스턴스.
        """
        # 디렉토리 생성
        for d in [
            self.settings.output_dir,
            self.settings.temp_dir,
            self.settings.data_dir,
            self.settings.logs_dir,
        ]:
            ensure_dir(d)

        # 영상 생성 전: 임시 파일 정리
        self._pre_cleanup()

        total = 9 if self.source_url else 8

        if self.source_url:
            self._run_crawl(total)

        self._run_script_generation(total)
        self._run_quality_check(total)
        self._run_originality_check(total)
        self._run_tts(total)
        self._run_background_download(total)
        self._run_video_composition(total)
        self._run_metadata(total)
        self._run_save_history(total)

        # 영상 생성 후: 비정상 파일 정리
        self._post_cleanup()

        set_pipeline_step("")
        return self.result

    def _pre_cleanup(self) -> None:
        """영상 생성 전 임시 파일을 정리합니다."""
        try:
            from youshorts.utils.file_cleaner import CleanupManager
            cleaner = CleanupManager(settings=self.settings)
            cleaner.clean_temp()
        except Exception as e:
            logger.debug("사전 정리 중 오류 (무시): %s", e)

    def _post_cleanup(self) -> None:
        """영상 생성 후 비정상 파일을 정리합니다."""
        try:
            from youshorts.utils.file_cleaner import CleanupManager
            cleaner = CleanupManager(settings=self.settings)
            cleaner.clean_all()
        except Exception as e:
            logger.debug("사후 정리 중 오류 (무시): %s", e)

    def _run_crawl(self, total: int) -> None:
        """STEP 0: 커뮤니티 게시글 크롤링 + 스크린샷 캡처 (source_url이 있을 때만)."""
        self._step(1, total, "커뮤니티 크롤링 + 스크린샷")
        from youshorts.research.crawler import crawl_community_post_with_screenshots

        crawled = crawl_community_post_with_screenshots(
            self.source_url, settings=self.settings,
        )
        self.result.source_text = crawled["body"]
        self.result.screenshots = crawled.get("screenshots", [])

        # topic이 비어있으면 크롤링 제목으로 대체
        if not self.topic:
            self.topic = crawled.get("title", "커뮤니티 썰")

        logger.info(
            "크롤링 완료: '%s' (%d자, %d장 스크린샷)",
            crawled["title"][:30], len(crawled["body"]),
            len(self.result.screenshots),
        )
        self._step_done(1, total, "커뮤니티 크롤링 + 스크린샷")

    def _run_script_generation(self, total: int = 8) -> None:
        """대본 생성."""
        step = 2 if self.source_url else 1
        self._step(step, total, "대본 생성 중")
        from youshorts.core.script_generator import generate_script

        # source_text: source_url 크롤링 결과 또는 community_crawler 결과
        effective_source_text = self.result.source_text or self.source_text

        self.result.script = generate_script(
            self.topic,
            style=self.style,
            source_text=effective_source_text,
            settings=self.settings,
        )

        logger.info("제목: %s", self.result.script["title"])
        logger.info("독창적 관점: %s", self.result.script["unique_angle"])
        logger.info("대본 길이: %d자", len(self.result.script["tts_script"]))
        logger.info("키워드: %s", ", ".join(self.result.script.get("keywords", [])))

        # 다중 제목 로깅
        titles = self.result.script.get("youtube_titles", [])
        if titles:
            logger.info("YouTube 제목 후보: %d개", len(titles))
            for i, t in enumerate(titles, 1):
                logger.info("  %d. %s", i, t)

        self._step_done(step, total, "대본 생성")

    def _run_quality_check(self, total: int = 8) -> None:
        """품질 검사."""
        step = 3 if self.source_url else 2
        self._step(step, total, "품질 체크")
        from youshorts.quality.quality_check import (
            check_factual_claims,
            check_script_quality,
            log_quality_report,
        )

        score, issues, suggestions = check_script_quality(self.result.script)
        claims = check_factual_claims(self.result.script)

        # AI 심층 분석 (옵션)
        ai_result = None
        if self.quality_ai:
            from youshorts.quality.quality_check import check_quality_with_ai

            ai_result = check_quality_with_ai(
                self.result.script, settings=self.settings,
            )
            self.result.ai_quality = ai_result

        log_quality_report(score, issues, suggestions, claims, ai_result=ai_result)
        self.result.quality_score = score
        self._step_done(step, total, "품질 체크")

    def _run_originality_check(self, total: int = 8) -> None:
        """독창성 체크."""
        step = 4 if self.source_url else 3
        self._step(step, total, "독창성 체크")
        from youshorts.quality.originality import check_originality
        from youshorts.core.script_generator import generate_script

        is_original, max_sim, similar_title = check_originality(
            self.result.script, settings=self.settings,
        )

        if not is_original:
            logger.warning(
                "유사도 %.0f%% (기준: 70%%) - '%s'와 유사", max_sim * 100, similar_title,
            )
            logger.info("대본 재생성 중...")
            self.result.script = generate_script(
                self.topic, style=self.style,
                source_text=self.result.source_text,
                settings=self.settings,
            )
            is_original, max_sim, similar_title = check_originality(
                self.result.script, settings=self.settings,
            )
            if not is_original:
                logger.warning("재생성 후에도 유사도 %.0f%% - 그대로 진행", max_sim * 100)
            else:
                logger.info("재생성 완료 - 유사도 %.0f%%", max_sim * 100)
        else:
            sim_pct = f"{max_sim:.0%}" if max_sim > 0 else "0%"
            logger.info("독창성 확인 (최대 유사도: %s)", sim_pct)

        self._step_done(step, total, "독창성 체크")

    def _run_tts(self, total: int = 8) -> None:
        """음성 생성.

        변경 사유: TTS 에러 핸들링 강화 - 3회 재시도, 실패 시 명확한 에러 메시지
        """
        import time as _time

        step = 5 if self.source_url else 4
        self._step(step, total, "음성 생성 중")

        # TTS 엔진 선택 (config 기반 분기)
        if self.settings.tts_engine == "enhanced":
            try:
                from youshorts.core.tts_enhanced import generate_fitted_tts
                logger.info("Enhanced TTS 엔진 사용 (ElevenLabs/OpenAI)")
            except Exception as e:
                logger.warning(f"Enhanced TTS 로드 실패: {e} - legacy로 폴백")
                from youshorts.core.tts_engine import generate_fitted_tts
        elif self.settings.tts_engine == "legacy":
            from youshorts.core.tts_engine import generate_fitted_tts
            logger.info("Legacy TTS 엔진 사용 (edge-tts)")
        else:
            # 기본값: enhanced 시도 → 실패 시 legacy 폴백
            try:
                from youshorts.core.tts_enhanced import generate_fitted_tts
                logger.info("Enhanced TTS 엔진 사용 (auto)")
            except Exception:
                from youshorts.core.tts_engine import generate_fitted_tts
                logger.info("Legacy TTS 엔진 사용 (auto fallback)")

        emotion_segments = self.result.script.get("emotion_map", [])
        subtitle_chunks = self.result.script.get("subtitle_chunks", [])
        tts_target = self.settings.target_duration

        # 변경 사유: TTS 생성 3회 재시도 (각 시도 사이 2초 대기)
        max_tts_retries = 3
        last_tts_error = None

        for tts_attempt in range(1, max_tts_retries + 1):
            try:
                tts_path, words, tts_duration = generate_fitted_tts(
                    self.result.script["tts_script"],
                    tts_target,
                    emotion_segments=emotion_segments,
                    subtitle_chunks=subtitle_chunks,
                    settings=self.settings,
                )

                self.result.tts_path = tts_path
                self.result.tts_duration = min(
                    tts_duration, self.settings.target_duration
                )
                self.result.script["_words"] = words

                logger.info("단어 그룹: %d개", len(words))
                logger.info("최종 영상 길이: %.1f초", self.result.tts_duration)

                if tts_attempt > 1:
                    logger.info("TTS 생성 성공 (파이프라인 시도 %d/%d)", tts_attempt, max_tts_retries)
                break  # 성공 시 루프 탈출

            except Exception as e:
                last_tts_error = e
                if tts_attempt < max_tts_retries:
                    logger.warning(
                        "TTS 생성 실패 (파이프라인 시도 %d/%d): %s - 2초 후 재시도",
                        tts_attempt, max_tts_retries, e,
                    )
                    _time.sleep(2)
                else:
                    error_msg = (
                        f"TTS 생성 최종 실패 ({max_tts_retries}회 시도): {last_tts_error}. "
                        f"이 영상을 스킵합니다."
                    )
                    logger.error(error_msg)
                    raise RuntimeError(error_msg) from last_tts_error

        self._step_done(step, total, "음성 생성")

    def _run_background_download(self, total: int = 8) -> None:
        """배경 영상 다운로드 (스크린샷이 있으면 스킵)."""
        step = 6 if self.source_url else 5
        self._step(step, total, "배경 영상 다운로드")

        # 스크린샷이 있으면 별도 배경 다운로드 불필요 (스크린샷 자체가 배경)
        if self.result.screenshots:
            logger.info(
                "스크린샷 배경 %d장 사용 - Pexels/그라데이션 다운로드 스킵",
                len(self.result.screenshots),
            )
            self.result.bg_paths = self.result.screenshots
        else:
            from youshorts.core.video_downloader import download_backgrounds

            keywords = self.result.script.get(
                "search_keywords", ["seoul city", "korea aerial", "korean lifestyle", "urban night"],
            )
            bg_theme = self.result.script.get("bg_theme", "")
            # 변경 사유: 배경 클립 10~12개 (4~6초 하드컷 전환, 60초 영상 기준)
            self.result.bg_paths = download_backgrounds(
                keywords, count=12, bg_theme=bg_theme, settings=self.settings,
            )
        self._step_done(step, total, "배경 영상 다운로드")

    def _should_use_shotstack(self) -> bool:
        """Shotstack 렌더러를 사용할지 결정합니다.

        renderer 인자 또는 settings.renderer 기반으로 판단합니다.
        - "shotstack": 강제 Shotstack 사용
        - "moviepy": 강제 MoviePy 사용
        - "auto" / None: SHOTSTACK_API_KEY가 있으면 Shotstack, 없으면 MoviePy

        Returns:
            Shotstack 사용 여부.
        """
        import os

        renderer = self.renderer or self.settings.renderer
        if renderer == "moviepy":
            return False
        if renderer == "shotstack":
            return True
        # auto: API 키가 있으면 Shotstack
        return bool(os.environ.get("SHOTSTACK_API_KEY", ""))

    def _run_video_composition(self, total: int = 8) -> None:
        """영상 합성 (FFmpeg 우선 → MoviePy 폴백 → Shotstack 조건부).

        변경 사유: FFmpeg 1순위로 변경 (메모리 효율)
        - FFmpeg 직접 렌더링 시도 (기본)
        - 실패 시 MoviePy 폴백
        - Shotstack은 명시적 요청 시만
        """
        step = 7 if self.source_url else 6
        self._step(step, total, "영상 합성 중")

        words = self.result.script.get("_words", [])

        # 1순위: FFmpeg 직접 렌더링 시도 (메모리 효율)
        if self.renderer != "shotstack" and self.renderer != "moviepy":
            try:
                output_path = self._render_with_ffmpeg_simple(words)
                if output_path and os.path.exists(output_path):
                    self.result.output_path = output_path
                    self.result.edit_style = self.edit_style or "ffmpeg"
                    self._step_done(step, total, "영상 합성 (FFmpeg)")
                    return
            except Exception as e:
                logger.warning(
                    "FFmpeg 렌더링 실패: %s → MoviePy 폴백", e,
                )

        # 2순위: MoviePy 폴백 (기존 로직, 안정적)
        if self.renderer != "shotstack":
            logger.info("MoviePy 렌더러로 영상 합성 중...")
            from youshorts.core.video_composer import compose

            output_path, used_edit_style = compose(
                self.result.bg_paths,
                self.result.tts_path,
                words,
                self.result.script,
                self.result.tts_duration,
                edit_style=self.edit_style,
                settings=self.settings,
            )
            self.result.output_path = output_path
            self.result.edit_style = used_edit_style
            self._step_done(step, total, "영상 합성 (MoviePy)")
            return

        # 3순위: Shotstack (명시적 요청 시만)
        if self._should_use_shotstack():
            try:
                output_path = self._render_with_shotstack(words)
                self.result.output_path = output_path
                self.result.edit_style = self.edit_style or "shotstack"
                self._step_done(step, total, "영상 합성 (Shotstack)")
                return
            except Exception as e:
                logger.error("Shotstack 렌더링 실패: %s", e)
                raise

    def _render_with_ffmpeg_simple(self, words: list) -> str:
        """FFmpeg로 간단한 렌더링을 수행합니다.

        배경 영상 + TTS + SRT 자막만 합성하는 단순화 버전.
        복잡한 레이어 합성은 MoviePy로 폴백.

        Args:
            words: 워드 그룹 타이밍 리스트.

        Returns:
            렌더링된 MP4 파일 경로.

        Raises:
            Exception: FFmpeg 렌더링 실패 시.
        """
        import os
        import re
        from datetime import datetime
        from youshorts.core.video_composer import (
            get_ffmpeg_path,
            merge_bg_clips_ffmpeg,
            _randomize_video_params,
        )

        logger.info("FFmpeg 직접 렌더링 시도 중...")

        # FFmpeg 설치 확인
        if not get_ffmpeg_path():
            raise FileNotFoundError("FFmpeg 미설치 - MoviePy로 폴백")

        # 배경 영상 병합
        ensure_dir(self.settings.temp_dir)
        merged_bg = os.path.join(self.settings.temp_dir, "merged_bg.mp4")

        if len(self.result.bg_paths) > 1:
            logger.info("배경 클립 %d개 병합 중...", len(self.result.bg_paths))
            try:
                merge_bg_clips_ffmpeg(self.result.bg_paths, merged_bg)
            except Exception as e:
                logger.warning("배경 병합 실패: %s - 첫 번째 클립만 사용", e)
                merged_bg = self.result.bg_paths[0]
        else:
            merged_bg = self.result.bg_paths[0] if self.result.bg_paths else None

        if not merged_bg or not os.path.exists(merged_bg):
            raise FileNotFoundError("배경 영상 없음 - MoviePy로 폴백")

        # SRT 자막 생성
        srt_path = os.path.join(self.settings.temp_dir, "subtitles.srt")
        self._generate_srt(words, srt_path)

        # 랜덤 파라미터
        config = _randomize_video_params()

        # 출력 파일명
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[^\w가-힣]', '_', self.result.script.get("title", "shorts"))[:30]
        output_path = os.path.join(self.settings.output_dir, f"shorts_{safe_title}_{timestamp}.mp4")

        # FFmpeg 렌더링
        from youshorts.core.video_composer import render_with_ffmpeg
        return render_with_ffmpeg(
            merged_bg,
            self.result.tts_path,
            srt_path,
            output_path,
            config,
        )

    def _generate_srt(self, words: list, output_path: str) -> None:
        """워드 타이밍에서 SRT 자막 파일을 생성합니다.

        Args:
            words: 워드 그룹 타이밍 리스트.
            output_path: SRT 출력 경로.
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, word_group in enumerate(words, 1):
                start_ms = int(word_group['start'] * 1000)
                end_ms = int(word_group['end'] * 1000)

                start_h = start_ms // 3600000
                start_m = (start_ms % 3600000) // 60000
                start_s = (start_ms % 60000) // 1000
                start_ms_remainder = start_ms % 1000

                end_h = end_ms // 3600000
                end_m = (end_ms % 3600000) // 60000
                end_s = (end_ms % 60000) // 1000
                end_ms_remainder = end_ms % 1000

                f.write(f"{i}\n")
                f.write(
                    f"{start_h:02d}:{start_m:02d}:{start_s:02d},{start_ms_remainder:03d} --> "
                    f"{end_h:02d}:{end_m:02d}:{end_s:02d},{end_ms_remainder:03d}\n"
                )
                f.write(f"{word_group['text']}\n\n")

    def _render_with_shotstack(self, words: list) -> str:
        """Shotstack API로 영상을 렌더링합니다.

        네트워크 에러 시 최대 3회 재시도합니다.

        Args:
            words: 워드 그룹 타이밍 리스트.

        Returns:
            렌더링된 MP4 파일 경로.

        Raises:
            RuntimeError: 3회 재시도 후에도 실패 시.
        """
        import os
        import time as _time

        from youshorts.core.shotstack_renderer import ShotstackRenderer
        from youshorts.utils.srt_generator import generate_srt_from_words

        logger.info("Shotstack 렌더러로 영상 합성 중...")

        # SRT 자막 파일 생성
        srt_path = os.path.join(self.settings.temp_dir, "subtitles.srt")
        generate_srt_from_words(words, srt_path)

        # BGM 파일 탐색
        bgm_path = None
        bgm_dir = self.settings.bgm_dir
        if os.path.isdir(bgm_dir):
            import glob as _glob
            import random

            bgm_files = (
                _glob.glob(os.path.join(bgm_dir, "*.mp3"))
                + _glob.glob(os.path.join(bgm_dir, "*.wav"))
            )
            if bgm_files:
                bgm_path = random.choice(bgm_files)

        # Pexels 원본 URL 추출 (업로드 없이 직접 사용 가능)
        bg_urls = self.result.script.get("_pexels_urls", None)

        # 3회 재시도
        max_retries = 3
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                renderer = ShotstackRenderer(settings=self.settings)
                output_path = renderer.render_shorts(
                    bg_paths=self.result.bg_paths,
                    tts_path=self.result.tts_path,
                    srt_path=srt_path,
                    word_groups=words,
                    script=self.result.script,
                    total_duration=self.result.tts_duration,
                    bgm_path=bgm_path,
                    bg_urls=bg_urls,
                )
                if attempt > 1:
                    logger.info("Shotstack 렌더링 성공 (시도 %d/%d)", attempt, max_retries)
                return output_path

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    wait = 5 * attempt
                    logger.warning(
                        "Shotstack 렌더링 실패 (시도 %d/%d): %s → %d초 후 재시도",
                        attempt, max_retries, e, wait,
                    )
                    _time.sleep(wait)

        raise RuntimeError(
            f"Shotstack 렌더링 최종 실패 ({max_retries}회 시도): {last_error}"
        )

    def _run_metadata(self, total: int = 8) -> None:
        """메타데이터 생성."""
        step = 8 if self.source_url else 7
        self._step(step, total, "메타데이터 생성")
        from youshorts.core.metadata import generate_metadata, print_metadata_summary

        metadata, meta_path = generate_metadata(
            self.result.script,
            self.result.output_path,
            self.result.edit_style,
            settings=self.settings,
        )
        self.result.metadata = metadata
        self.result.meta_path = meta_path
        print_metadata_summary(metadata)
        self._step_done(step, total, "메타데이터 생성")

    def _run_save_history(self, total: int = 8) -> None:
        """히스토리 저장."""
        step = 9 if self.source_url else 8
        self._step(step, total, "히스토리 저장")
        from youshorts.quality.originality import save_to_history

        save_to_history(
            self.result.script,
            self.result.edit_style,
            self.result.output_path,
            settings=self.settings,
        )
        self._step_done(step, total, "히스토리 저장")
