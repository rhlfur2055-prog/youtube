"""pytest 공통 fixtures."""

from __future__ import annotations

import os
import tempfile
from typing import Any, Generator

import pytest
from pydantic import SecretStr

from youshorts.config.settings import Settings


@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    """임시 디렉토리를 생성하고 테스트 후 정리합니다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_settings(temp_dir: str) -> Settings:
    """테스트용 Settings 인스턴스를 생성합니다."""
    return Settings(
        anthropic_api_key=SecretStr("sk-ant-test-key-12345678901234567890"),
        pexels_api_key=SecretStr("test-pexels-key-1234567890"),
        youtube_api_key=SecretStr(""),
        project_dir=temp_dir,
        output_dir=os.path.join(temp_dir, "output"),
        temp_dir=os.path.join(temp_dir, "temp"),
        data_dir=os.path.join(temp_dir, "data"),
        logs_dir=os.path.join(temp_dir, "logs"),
    )


@pytest.fixture
def sample_script() -> dict[str, Any]:
    """테스트용 대본 딕셔너리를 생성합니다."""
    return {
        "title": "수면의 질을 높이는 과학적 방법",
        "hook": "[놀람] 한국인의 45%가 수면 부족이라는 사실, 알고 계셨나요?",
        "content": "[강조] 첫째, 취침 2시간 전에는 스마트폰을 내려놓으세요.",
        "creator_opinion": "제가 직접 한 달간 실험해보니, 수면 시간이 평균 30분 늘었거든요.",
        "twist": "[놀람] 사실 낮잠이 오히려 밤잠을 방해할 수 있습니다.",
        "conclusion": "오늘부터 하나씩 바꿔보시는 건 어떨까요? 구독 부탁드려요!",
        "full_script": (
            "[놀람] 한국인의 45%가 수면 부족이라는 사실, 알고 계셨나요? "
            "[강조] 첫째, 취침 2시간 전에는 스마트폰을 내려놓으세요. "
            "제가 직접 한 달간 실험해보니, 수면 시간이 평균 30분 늘었거든요. "
            "[놀람] 사실 낮잠이 오히려 밤잠을 방해할 수 있습니다. "
            "오늘부터 하나씩 바꿔보시는 건 어떨까요? 구독 부탁드려요!"
        ),
        "tts_script": (
            "한국인의 45%가 수면 부족이라는 사실, 알고 계셨나요? "
            "첫째, 취침 2시간 전에는 스마트폰을 내려놓으세요. "
            "제가 직접 한 달간 실험해보니, 수면 시간이 평균 30분 늘었거든요. "
            "사실 낮잠이 오히려 밤잠을 방해할 수 있습니다. "
            "오늘부터 하나씩 바꿔보시는 건 어떨까요? 구독 부탁드려요!"
        ),
        "keywords": ["수면", "스마트폰", "낮잠"],
        "search_keywords": ["sleeping peacefully", "smartphone screen", "nap time", "bedroom night"],
        "section_backgrounds": {
            "hook": "tired person yawning",
            "content": "smartphone screen night",
            "twist": "napping on couch",
            "conclusion": "peaceful sleeping bedroom",
        },
        "background_keywords_en": {
            "hook": ["tired person yawning at desk", "alarm clock morning"],
            "content": ["person putting away smartphone", "dark bedroom night"],
            "opinion": ["person thinking at desk", "notebook writing"],
            "twist": ["person napping on couch", "afternoon sleepy"],
            "conclusion": ["peaceful sleeping bedroom", "sunrise morning"],
        },
        "subtitle_chunks": [
            {"text": "한국인의 45%가", "section": "hook", "emotion": "curiosity"},
            {"text": "수면 부족이라는", "section": "hook", "emotion": "curiosity"},
        ],
        "youtube_titles": [
            "수면의 질을 높이는 과학적 방법",
            "당신의 잠이 부족한 진짜 이유",
            "수면 전문가도 놀란 꿀팁",
        ],
        "thumbnail_text": "수면꿀팁",
        "description_draft": "수면의 질을 높이는 과학적 방법을 알아봅시다. #수면 #건강",
        "seo_tags": ["수면", "건강", "꿀팁", "수면부족", "숏츠"],
        "unique_angle": "뇌과학이 밝혀낸 수면 개선법",
        "fact_sources": ["한국수면학회 2024 보고서", "네이처 수면 연구"],
        "emotion_map": [
            {"text": "한국인의 45%가", "emotion": "놀람"},
            {"text": "스마트폰을 내려놓으세요", "emotion": "강조"},
        ],
        "hashtags": ["#수면", "#건강", "#꿀팁", "#숏츠", "#과학"],
        "style": "analytical",
        "angle": "뇌과학이 밝혀낸",
    }
