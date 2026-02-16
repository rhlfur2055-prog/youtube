# 변경 사유: Shotstack API 기반 클라우드 영상 렌더링 모듈 생성
"""Shotstack API 기반 영상 렌더링 엔진.

Shotstack Edit API를 사용하여 클라우드에서 YouTube Shorts 영상을 렌더링합니다.
로컬 PC 부하 없이 고품질 영상을 생성할 수 있습니다.

SANDBOX 모드: 무료, 워터마크 포함
PRODUCTION 모드: 유료, 워터마크 없음
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from youshorts.config.settings import Settings, get_settings
from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

# Shotstack API 엔드포인트
_SHOTSTACK_HOSTS = {
    "sandbox": "https://api.shotstack.io/edit/stage",
    "production": "https://api.shotstack.io/edit/v1",
}
_INGEST_HOSTS = {
    "sandbox": "https://api.shotstack.io/ingest/stage",
    "production": "https://api.shotstack.io/ingest/v1",
}
_SERVE_HOSTS = {
    "sandbox": "https://api.shotstack.io/serve/stage",
    "production": "https://api.shotstack.io/serve/v1",
}


class ShotstackRenderer:
    """Shotstack API 기반 영상 렌더러.

    클라우드에서 타임라인 기반 영상 합성 및 렌더링을 수행합니다.
    SANDBOX/PRODUCTION 환경을 .env 설정으로 전환할 수 있습니다.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """렌더러를 초기화합니다.

        .env에서 SHOTSTACK_API_KEY, SHOTSTACK_ENV를 로드합니다.
        SHOTSTACK_ENV=sandbox (기본) 또는 production 으로 분기합니다.

        Args:
            settings: 설정 인스턴스.
        """
        self.settings = settings or get_settings()

        # 환경 결정 (sandbox 기본)
        self.env = os.environ.get("SHOTSTACK_ENV", "sandbox").lower()

        # API 키 선택
        if self.env == "production":
            self.api_key = os.environ.get("SHOTSTACK_PRODUCTION_KEY", "")
            if not self.api_key:
                logger.warning("SHOTSTACK_PRODUCTION_KEY 미설정 → SANDBOX 폴백")
                self.env = "sandbox"
                self.api_key = os.environ.get("SHOTSTACK_API_KEY", "")
        else:
            self.api_key = os.environ.get("SHOTSTACK_API_KEY", "")

        if not self.api_key:
            raise RuntimeError(
                "SHOTSTACK_API_KEY가 .env에 설정되지 않았습니다. "
                "Shotstack 렌더링을 사용하려면 API 키를 설정하세요."
            )

        # API 엔드포인트 설정
        self.edit_host = _SHOTSTACK_HOSTS[self.env]
        self.ingest_host = _INGEST_HOSTS[self.env]
        self.serve_host = _SERVE_HOSTS[self.env]

        # 공통 헤더
        self.headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        logger.info(
            "Shotstack 렌더러 초기화: env=%s, host=%s",
            self.env, self.edit_host,
        )
        if self.env == "sandbox":
            logger.warning(
                "⚠ SANDBOX 모드: 렌더링 결과에 워터마크가 포함됩니다. "
                "PRODUCTION 전환은 SHOTSTACK_ENV=production 으로 설정하세요."
            )

    def upload_asset(self, file_path: str) -> str:
        """로컬 파일을 Shotstack Ingest API로 업로드합니다.

        1) 서명된 업로드 URL 요청
        2) 파일 업로드
        3) Shotstack 소스 URL 반환

        Args:
            file_path: 업로드할 로컬 파일 경로.

        Returns:
            Shotstack에서 사용 가능한 소스 URL.

        Raises:
            RuntimeError: 업로드 실패 시.
        """
        filename = os.path.basename(file_path)
        logger.info("에셋 업로드 시작: %s", filename)

        # 1) 서명된 URL 요청
        signed_url_resp = requests.get(
            f"{self.ingest_host}/upload",
            headers=self.headers,
            timeout=30,
        )
        if signed_url_resp.status_code != 200:
            raise RuntimeError(
                f"Shotstack 업로드 URL 요청 실패: {signed_url_resp.status_code} "
                f"{signed_url_resp.text}"
            )

        upload_data = signed_url_resp.json()
        signed_url = upload_data["data"]["attributes"]["url"]
        source_id = upload_data["data"]["attributes"]["id"]

        # 2) 파일 업로드 (Content-Type 헤더 없이)
        file_size = os.path.getsize(file_path)
        logger.info("파일 업로드 중: %s (%.1f MB)", filename, file_size / 1024 / 1024)

        with open(file_path, "rb") as f:
            upload_resp = requests.put(
                signed_url,
                data=f,
                headers={"Content-Type": ""},
                timeout=300,
            )

        if upload_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Shotstack 파일 업로드 실패: {upload_resp.status_code}"
            )

        # 3) 소스가 처리될 때까지 폴링 (최대 60초)
        source_url = f"https://shotstack-ingest-api-{self.env}-sources.s3.ap-southeast-2.amazonaws.com/{source_id}"

        # Shotstack 소스 URL 형식으로 반환
        shotstack_url = f"https://shotstack-api-{self.env}-sources.s3.ap-southeast-2.amazonaws.com/{source_id}"

        logger.info("에셋 업로드 완료: %s → source_id=%s", filename, source_id)

        # Ingest API로 소스 상태 확인 및 URL 가져오기
        for _ in range(12):  # 최대 60초
            try:
                source_resp = requests.get(
                    f"{self.ingest_host}/sources/{source_id}",
                    headers=self.headers,
                    timeout=15,
                )
                if source_resp.status_code == 200:
                    source_data = source_resp.json()
                    status = source_data.get("data", {}).get("attributes", {}).get("status", "")
                    if status == "ready":
                        source_url_from_api = source_data.get("data", {}).get("attributes", {}).get("url", "")
                        if source_url_from_api:
                            logger.info("소스 준비 완료: %s", source_url_from_api)
                            return source_url_from_api
                        break
                    elif status == "failed":
                        raise RuntimeError(f"소스 처리 실패: {source_data}")
                    logger.info("소스 처리 중: %s (%s)", filename, status)
            except requests.RequestException:
                pass
            time.sleep(5)

        # 폴링 완료 후에도 URL을 구성하여 반환 (소스가 아직 처리 중일 수 있음)
        return shotstack_url

    def render_shorts(
        self,
        bg_paths: list[str],
        tts_path: str,
        srt_path: str,
        word_groups: list[dict[str, Any]],
        script: dict[str, Any],
        total_duration: float,
        bgm_path: str | None = None,
        bg_urls: list[str] | None = None,
    ) -> str:
        """Shotstack Edit API로 YouTube Shorts 영상을 렌더링합니다.

        타임라인 구성:
        - Track 1 (최상위): 자막 오버레이 (HtmlAsset)
        - Track 2: 시각 효과 텍스트 (도입부/아웃트로)
        - Track 3: TTS 오디오
        - Track 4: BGM (있으면, 볼륨 15%)
        - Track 5 (최하위): 배경 영상 (4~6초 전환, Ken Burns)

        Args:
            bg_paths: 배경 영상/이미지 로컬 경로 리스트.
            tts_path: TTS 오디오 파일 경로.
            srt_path: SRT 자막 파일 경로.
            word_groups: 워드 그룹 타이밍 리스트.
            script: 대본 딕셔너리.
            total_duration: 전체 영상 길이 (초).
            bgm_path: BGM 파일 경로 (선택).
            bg_urls: 배경 영상 URL 리스트 (Pexels URL 직접 사용 시).

        Returns:
            렌더링된 최종 MP4 파일 경로.
        """
        logger.info("=" * 50)
        logger.info("Shotstack 렌더링 시작 (%s 모드)", self.env.upper())
        logger.info("=" * 50)

        # --- 에셋 업로드 ---
        # TTS 오디오 업로드
        logger.info("[1/5] TTS 오디오 업로드 중...")
        tts_url = self.upload_asset(tts_path)

        # BGM 업로드 (있으면)
        bgm_url = None
        if bgm_path and os.path.exists(bgm_path):
            logger.info("[1/5] BGM 오디오 업로드 중...")
            bgm_url = self.upload_asset(bgm_path)

        # 배경 영상 URL 준비
        logger.info("[2/5] 배경 영상 URL 준비 중...")
        video_urls = []
        if bg_urls:
            # Pexels URL 직접 사용
            video_urls = bg_urls
            logger.info("Pexels URL 직접 사용: %d개", len(video_urls))
        else:
            # 로컬 파일 업로드
            for i, path in enumerate(bg_paths):
                if os.path.exists(path):
                    logger.info("배경 %d/%d 업로드: %s", i + 1, len(bg_paths), os.path.basename(path))
                    url = self.upload_asset(path)
                    video_urls.append(url)
            logger.info("배경 영상 업로드 완료: %d개", len(video_urls))

        # --- 타임라인 구성 ---
        logger.info("[3/5] 타임라인 구성 중...")

        # Track 5 (최하위): 배경 영상 클립들
        bg_clips = self._build_background_clips(video_urls, total_duration)

        # Track 4: BGM (있으면)
        bgm_clips = []
        if bgm_url:
            bgm_clips = self._build_bgm_clips(bgm_url, total_duration)

        # Track 3: TTS 오디오
        tts_clips = [{
            "asset": {
                "type": "audio",
                "src": tts_url,
                "volume": 1.0,
            },
            "start": 0,
            "length": total_duration,
        }]

        # Track 2: 시각 효과 텍스트 (도입부 + 아웃트로)
        effect_clips = self._build_effect_text_clips(script, total_duration)

        # Track 1 (최상위): 자막 오버레이
        subtitle_clips = self._build_subtitle_clips(word_groups, total_duration)

        # 타임라인 JSON 구성
        tracks = []

        # Track 순서: 상위 → 하위 (Shotstack에서 배열 앞쪽이 상위 레이어)
        if subtitle_clips:
            tracks.append({"clips": subtitle_clips})
        if effect_clips:
            tracks.append({"clips": effect_clips})
        if tts_clips:
            tracks.append({"clips": tts_clips})
        if bgm_clips:
            tracks.append({"clips": bgm_clips})
        if bg_clips:
            tracks.append({"clips": bg_clips})

        # 타임라인 & 출력 설정
        timeline = {
            "tracks": tracks,
            "background": "#000000",
        }

        output = {
            "format": "mp4",
            "resolution": "1080",
            "aspectRatio": "9:16",
            "fps": 30,
        }

        edit_payload = {
            "timeline": timeline,
            "output": output,
        }

        # --- 렌더링 요청 ---
        logger.info("[4/5] 렌더링 요청 전송 중...")
        render_id = self._submit_render(edit_payload)

        # --- 렌더링 완료 대기 ---
        logger.info("[5/5] 렌더링 완료 대기 중... (render_id: %s)", render_id)
        result_url = self.poll_render_status(render_id)

        # --- 결과 다운로드 ---
        output_path = self.download_result(result_url, script)

        logger.info("=" * 50)
        logger.info("Shotstack 렌더링 완료: %s", output_path)
        logger.info("=" * 50)

        return output_path

    def _build_background_clips(
        self,
        video_urls: list[str],
        total_duration: float,
    ) -> list[dict[str, Any]]:
        """배경 영상 클립들을 구성합니다.

        4~6초마다 다른 클립으로 전환하며, Ken Burns 줌 효과를 적용합니다.

        Args:
            video_urls: 배경 영상 URL 리스트.
            total_duration: 전체 영상 길이.

        Returns:
            배경 클립 리스트 (Shotstack JSON 형식).
        """
        if not video_urls:
            # 검은 배경 폴백
            return [{
                "asset": {
                    "type": "video",
                    "src": "https://shotstack-assets.s3.ap-southeast-2.amazonaws.com/footage/black-background.mp4",
                },
                "start": 0,
                "length": total_duration,
            }]

        clips = []
        interval = 5  # 5초 간격 전환
        crossfade = 0.3  # 0.3초 크로스페이드
        num_segments = max(1, int(total_duration / interval) + 1)

        # Ken Burns 효과 종류들 (랜덤 선택)
        zoom_effects = ["zoomIn", "zoomInSlow", "zoomOut", "zoomOutSlow",
                        "slideLeft", "slideRight", "slideUp", "slideDown"]

        for i in range(num_segments):
            url = video_urls[i % len(video_urls)]
            start_time = i * interval
            # 마지막 세그먼트는 남은 시간만큼
            seg_length = min(interval + crossfade, total_duration - start_time)
            if seg_length <= 0:
                break

            # 영상/이미지 구분
            is_image = url.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            asset_type = "image" if is_image else "video"

            clip: dict[str, Any] = {
                "asset": {
                    "type": asset_type,
                    "src": url,
                },
                "start": start_time,
                "length": seg_length,
                "fit": "cover",
                "effect": zoom_effects[i % len(zoom_effects)],
            }

            # 비디오 에셋에 볼륨 0 (배경 영상 소리 제거)
            if asset_type == "video":
                clip["asset"]["volume"] = 0

            # 첫 번째 이후 클립에 크로스페이드 트랜지션
            if i > 0:
                clip["transition"] = {
                    "in": "fade",
                }

            clips.append(clip)

        return clips

    def _build_bgm_clips(
        self,
        bgm_url: str,
        total_duration: float,
    ) -> list[dict[str, Any]]:
        """BGM 오디오 클립을 구성합니다.

        볼륨 15%, 페이드인/페이드아웃 적용.

        Args:
            bgm_url: BGM 파일 URL.
            total_duration: 전체 영상 길이.

        Returns:
            BGM 클립 리스트.
        """
        return [{
            "asset": {
                "type": "audio",
                "src": bgm_url,
                "volume": 0.15,  # TTS 대비 15%
                "effect": "fadeInFadeOut",
            },
            "start": 0,
            "length": total_duration,
        }]

    def _build_effect_text_clips(
        self,
        script: dict[str, Any],
        total_duration: float,
    ) -> list[dict[str, Any]]:
        """시각 효과 텍스트 클립을 구성합니다.

        - 첫 2초: 훅 텍스트 (예: "알고 계셨나요?")
        - 마지막 2초: "좋아요 & 구독" CTA

        Args:
            script: 대본 딕셔너리.
            total_duration: 전체 영상 길이.

        Returns:
            효과 텍스트 클립 리스트.
        """
        clips = []
        title = script.get("title", "")

        # 도입부 훅 텍스트 (첫 2초)
        hook_text = title[:20] if title else "알고 계셨나요?"
        hook_html = f"""
        <div style="
            font-family: 'Noto Sans KR', sans-serif;
            font-size: 48px;
            font-weight: 900;
            color: #FFFFFF;
            text-shadow: 3px 3px 6px rgba(0,0,0,0.8);
            text-align: center;
            padding: 20px;
            background: rgba(0,0,0,0.5);
            border-radius: 15px;
        ">{hook_text}</div>
        """

        clips.append({
            "asset": {
                "type": "html",
                "html": hook_html,
                "width": 900,
                "height": 200,
                "position": "center",
            },
            "start": 0,
            "length": 2.5,
            "transition": {
                "in": "fade",
                "out": "fade",
            },
            "position": "center",
            "offset": {"y": -0.15},
        })

        # 아웃트로 CTA (마지막 2.5초)
        outro_html = """
        <div style="
            font-family: 'Noto Sans KR', sans-serif;
            text-align: center;
            padding: 30px;
            background: rgba(0,0,0,0.7);
            border-radius: 20px;
        ">
            <div style="font-size: 44px; font-weight: 900; color: #FFD700; margin-bottom: 10px;">
                👍 좋아요 &amp; 구독
            </div>
            <div style="font-size: 28px; color: #FFFFFF;">
                🔔 알림 설정도 부탁해요!
            </div>
        </div>
        """

        outro_start = max(0, total_duration - 3.0)
        clips.append({
            "asset": {
                "type": "html",
                "html": outro_html,
                "width": 800,
                "height": 250,
                "position": "center",
            },
            "start": outro_start,
            "length": 3.0,
            "transition": {
                "in": "fade",
                "out": "fade",
            },
            "position": "center",
        })

        return clips

    def _build_subtitle_clips(
        self,
        word_groups: list[dict[str, Any]],
        total_duration: float,
    ) -> list[dict[str, Any]]:
        """자막 오버레이 클립들을 구성합니다.

        HTML 기반 자막으로 굵은 산세리프 폰트, 흰색 + 검은 테두리.
        화면 하단 80% 너비로 표시.

        Args:
            word_groups: 워드 그룹 타이밍 리스트.
            total_duration: 전체 영상 길이.

        Returns:
            자막 클립 리스트.
        """
        clips = []

        for group in word_groups:
            start = group.get("start", 0.0)
            end = group.get("end", start + 1.0)
            text = group.get("text", "").strip()

            if not text or start >= total_duration:
                continue

            length = min(end - start, total_duration - start)
            if length <= 0.1:
                continue

            # HTML 자막 (굵은 산세리프, 흰색 + 검은 테두리)
            subtitle_html = f"""
            <div style="
                font-family: 'Noto Sans KR', 'Arial Black', sans-serif;
                font-size: 58px;
                font-weight: 900;
                color: #FFFFFF;
                text-shadow:
                    -3px -3px 0 #000,
                    3px -3px 0 #000,
                    -3px 3px 0 #000,
                    3px 3px 0 #000,
                    0 0 8px rgba(0,0,0,0.5);
                text-align: center;
                line-height: 1.3;
                padding: 10px 20px;
            ">{text}</div>
            """

            clips.append({
                "asset": {
                    "type": "html",
                    "html": subtitle_html,
                    "width": 900,
                    "height": 200,
                    "position": "bottom",
                },
                "start": start,
                "length": length,
                "position": "bottom",
                "offset": {"y": -0.08},
                "transition": {
                    "in": "fade",
                    "out": "fade",
                },
            })

        logger.info("자막 클립 생성: %d개", len(clips))
        return clips

    def _submit_render(self, edit_payload: dict[str, Any]) -> str:
        """Shotstack Edit API에 렌더링 요청을 전송합니다.

        Args:
            edit_payload: 타임라인 + 출력 설정 JSON.

        Returns:
            렌더링 ID.

        Raises:
            RuntimeError: 요청 실패 시.
        """
        resp = requests.post(
            f"{self.edit_host}/render",
            json=edit_payload,
            headers=self.headers,
            timeout=30,
        )

        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Shotstack 렌더링 요청 실패: {resp.status_code} {resp.text}"
            )

        data = resp.json()
        render_id = data.get("response", {}).get("id", "")
        if not render_id:
            raise RuntimeError(f"렌더링 ID를 받지 못했습니다: {data}")

        logger.info("렌더링 요청 성공: render_id=%s", render_id)
        return render_id

    def poll_render_status(
        self,
        render_id: str,
        timeout: int = 300,
        interval: int = 10,
    ) -> str:
        """렌더링 상태를 폴링하여 완료 시 결과 URL을 반환합니다.

        Args:
            render_id: 렌더링 ID.
            timeout: 최대 대기 시간 (초, 기본 5분).
            interval: 폴링 간격 (초, 기본 10초).

        Returns:
            렌더링된 MP4 파일 URL.

        Raises:
            RuntimeError: 렌더링 실패 또는 타임아웃 시.
        """
        elapsed = 0
        while elapsed < timeout:
            resp = requests.get(
                f"{self.edit_host}/render/{render_id}",
                headers=self.headers,
                timeout=15,
            )

            if resp.status_code != 200:
                logger.warning("상태 조회 실패: %s", resp.status_code)
                time.sleep(interval)
                elapsed += interval
                continue

            data = resp.json()
            render_data = data.get("response", {})
            status = render_data.get("status", "unknown")

            if status == "done":
                result_url = render_data.get("url", "")
                if result_url:
                    logger.info(
                        "렌더링 완료 (%.0f초 소요): %s", elapsed, result_url,
                    )
                    return result_url
                raise RuntimeError("렌더링 완료되었으나 URL이 없습니다.")

            elif status == "failed":
                error_msg = render_data.get("error", "알 수 없는 오류")
                raise RuntimeError(f"Shotstack 렌더링 실패: {error_msg}")

            else:
                progress = render_data.get("progress", 0)
                logger.info(
                    "렌더링 중: %s (%d%%) [%d/%d초]",
                    status, progress, elapsed, timeout,
                )

            time.sleep(interval)
            elapsed += interval

        raise RuntimeError(
            f"Shotstack 렌더링 타임아웃 ({timeout}초). render_id: {render_id}"
        )

    def download_result(
        self,
        result_url: str,
        script: dict[str, Any] | None = None,
    ) -> str:
        """렌더링 완료된 MP4를 output/ 폴더에 다운로드합니다.

        Args:
            result_url: 렌더링된 MP4 URL.
            script: 대본 딕셔너리 (파일명 생성용, 선택).

        Returns:
            다운로드된 파일 경로.

        Raises:
            RuntimeError: 다운로드 실패 시.
        """
        import re
        from datetime import datetime

        output_dir = self.settings.output_dir
        os.makedirs(output_dir, exist_ok=True)

        # 파일명 생성
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if script:
            safe_title = re.sub(r'[^\w가-힣]', '_', script.get("title", "shorts"))[:30]
        else:
            safe_title = "shorts"
        output_path = os.path.join(
            output_dir, f"shorts_{safe_title}_{timestamp}_shotstack.mp4",
        )

        logger.info("결과 다운로드 중: %s", result_url)

        resp = requests.get(result_url, stream=True, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(
                f"결과 다운로드 실패: {resp.status_code}"
            )

        total_size = 0
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total_size += len(chunk)

        file_size_mb = total_size / 1024 / 1024
        logger.info("다운로드 완료: %s (%.1f MB)", output_path, file_size_mb)

        return output_path
