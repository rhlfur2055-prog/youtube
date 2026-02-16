# 변경 사유: BGM 디렉토리/볼륨, 자막 청크, Ken Burns, 카운트다운/whoosh 토글, Apify/YouTube OAuth 설정 추가
"""Pydantic BaseSettings 기반 프로젝트 설정.

.env 파일 자동 로딩, 타입 검증, API 키 자동 마스킹을 제공합니다.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_env_file() -> Optional[str]:
    """프로젝트 루트의 .env 파일을 찾아서 강제 로드합니다.

    시스템 환경변수에 빈 값이 있어도 .env 값으로 덮어씁니다.
    """
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(str(candidate), override=True)
            return str(candidate)
    return None


# 모듈 로드 시 즉시 .env를 환경변수에 반영
_ENV_FILE_PATH = _load_env_file()


# ── Background Gradients ──
BG_GRADIENTS = [
    ("#12c2e9", "#c471ed", "#f64f59"),  # 틱톡 스타일 (화려함)
    ("#2C3E50", "#4CA1AF"),             # 다크 모드 (진지한 썰)
    ("#FF512F", "#DD2476"),             # 공포/분노 썰
    ("#11998e", "#38ef7d"),             # 힐링/유머 썰
    ("#8E2DE2", "#4A00E0")              # 미스터리/이슈
]

# ── Community Theme Gradients ──
BG_GRADIENTS_COMMUNITY: dict[str, list[tuple[str, ...]]] = {
    "horror": [
        ("#1a0a0a", "#3d0000", "#000000"),
        ("#0d0d0d", "#2a0a0a", "#000000"),
    ],
    "funny": [
        ("#ff9a9e", "#fad0c4", "#ffecd2"),
        ("#f093fb", "#f5576c"),
    ],
    "touching": [
        ("#a18cd1", "#fbc2eb"),
        ("#ffecd2", "#fcb69f"),
    ],
    "shocking": [
        ("#f5af19", "#f12711"),
        ("#eb3349", "#f45c43"),
    ],
    "mystery": [
        ("#0f0c29", "#302b63", "#24243e"),
        ("#141e30", "#243b55"),
    ],
}


class Settings(BaseSettings):
    """애플리케이션 전체 설정.

    환경변수 또는 .env 파일에서 자동으로 값을 로딩합니다.
    API 키는 SecretStr로 관리되어 repr에서 자동 마스킹됩니다.
    """

    # ── API Keys ──
    anthropic_api_key: SecretStr = SecretStr("")
    pexels_api_key: SecretStr = SecretStr("")
    youtube_api_key: SecretStr = SecretStr("")
    google_application_credentials: str = ""

    # Google Gemini API
    google_api_key: SecretStr = SecretStr("")

    # Apify API
    apify_api_token: SecretStr = SecretStr("")

    # YouTube OAuth (업로드/분석용)
    youtube_client_id: str = ""
    youtube_client_secret: SecretStr = SecretStr("")
    youtube_refresh_token: SecretStr = SecretStr("")

    # ── Paths ──
    project_dir: str = Field(default_factory=lambda: str(Path.cwd()))
    output_dir: str = ""
    temp_dir: str = ""
    data_dir: str = ""
    logs_dir: str = ""

    # ── Video ──
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30
    target_duration: int = 59
    audio_sample_rate: int = 44100
    bitrate: str = "8000k"

    # ── Background ──
    use_pexels: bool = True
    default_bg_type: str = "gradient"  # gradient | solid
    download_timeout: int = 30

    # ElevenLabs API (고품질 TTS)
    elevenlabs_api_key: SecretStr = SecretStr("")

    # ── TTS ──
    # 변경 사유: enhanced 엔진 (ElevenLabs 우선, edge-tts 폴백)
    # 전체 텍스트를 한 번에 전송하여 끊김 없는 자연스러운 음성 생성
    tts_engine: str = "enhanced"  # "enhanced" | "legacy"
    tts_voice: str = "ko-KR-InJoonNeural"  # 변경: 자연스러운 남성 음성 (기계음 해소)
    tts_rate: str = "+10%"  # 변경: 약간 빠르게 (자연스러운 템포)
    tts_pitch: str = "+0Hz"  # 기본 피치 유지
    sentence_pause_ms: int = 200

    # Enhanced TTS (ElevenLabs 1순위 → OpenAI 2순위 → edge-tts 3순위)
    elevenlabs_voice_id: str = ""  # 사용자 설정 voice ID (빈값이면 한국어 남성 기본값)
    openai_api_key: SecretStr = SecretStr("")  # OpenAI API (대본 폴백 + TTS 폴백)
    openai_tts_voice: str = "onyx"  # OpenAI TTS 음성 (onyx: 깊은 남성)
    openai_tts_model: str = "tts-1-hd"  # OpenAI TTS 모델 (고품질)
    tts_mastering_enabled: bool = True  # -14 LUFS 마스터링
    tts_mastering_target_lufs: float = -14.0
    tts_cache_enabled: bool = True  # TTS 캐싱 활성화 (30일)

    # ── BGM ──
    bgm_dir: str = ""
    bgm_volume_db: float = -20.0
    bgm_ducking_db: float = -6.0

    # ── Subtitle ──
    subtitle_chunk_size: int = 10
    subtitle_font: str = "NanumSquareRoundEB"
    subtitle_font_size_max: int = 90
    subtitle_font_size_min: int = 70
    subtitle_stroke_width: int = 5
    subtitle_position: str = "center"
    subtitle_color: str = "white"

    # ── Shotstack API (클라우드 렌더링) ──
    shotstack_api_key: SecretStr = SecretStr("")
    shotstack_production_key: SecretStr = SecretStr("")
    shotstack_env: str = "sandbox"  # "sandbox" 또는 "production"
    renderer: str = "auto"  # "auto" | "shotstack" | "moviepy"

    # ── Visual Effects ──
    enable_ken_burns: bool = True
    enable_countdown: bool = False
    enable_whoosh: bool = False

    # ── Channel ──
    channel_name: str = ""  # 빈값 = 워터마크 비활성화

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        frozen=True,
        extra="ignore",
    )

    def model_post_init(self, __context: object) -> None:
        """경로 기본값을 project_dir 기반으로 설정합니다."""
        base = Path(self.project_dir)
        defaults = {
            "output_dir": str(base / "output"),
            "temp_dir": str(base / "temp"),
            "data_dir": str(base / "data"),
            "logs_dir": str(base / "logs"),
            "bgm_dir": str(base / "data" / "bgm"),
        }
        for field_name, default_val in defaults.items():
            current = getattr(self, field_name)
            if not current:
                object.__setattr__(self, field_name, default_val)

    @property
    def history_file(self) -> str:
        return os.path.join(self.data_dir, "history.json")

    @property
    def style_log_file(self) -> str:
        return os.path.join(self.data_dir, "style_log.json")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """싱글톤 Settings 인스턴스를 반환합니다."""
    return Settings()
