"""입력값 검증 모듈.

CLI 입력, 파일 경로, API 키 형식 등을 검증합니다.
"""

from __future__ import annotations

import re

from youshorts.config.styles import EDIT_STYLES, SCRIPT_STYLES


class ValidationError(Exception):
    """입력 검증 실패 시 발생하는 예외."""


def validate_topic_input(topic: str) -> str:
    """주제 입력값을 검증합니다.

    Args:
        topic: 사용자 입력 주제.

    Returns:
        정제된 주제 문자열.

    Raises:
        ValidationError: 유효하지 않은 주제.
    """
    topic = topic.strip()
    if not topic:
        raise ValidationError("주제가 비어있습니다.")
    if len(topic) > 200:
        raise ValidationError("주제가 너무 깁니다 (최대 200자).")
    if len(topic) < 2:
        raise ValidationError("주제가 너무 짧습니다 (최소 2자).")
    return topic


def validate_style(style: str) -> str:
    """대본 스타일을 검증합니다.

    Args:
        style: 스타일 이름.

    Returns:
        검증된 스타일 이름.

    Raises:
        ValidationError: 유효하지 않은 스타일.
    """
    if style not in SCRIPT_STYLES:
        raise ValidationError(
            f"유효하지 않은 스타일: {style}. 가능한 값: {', '.join(SCRIPT_STYLES)}"
        )
    return style


def validate_edit_style(edit_style: str | None) -> str | None:
    """편집 스타일을 검증합니다.

    Args:
        edit_style: 편집 스타일 이름 (None 허용).

    Returns:
        검증된 편집 스타일 이름.

    Raises:
        ValidationError: 유효하지 않은 편집 스타일.
    """
    if edit_style is None:
        return None
    if edit_style not in EDIT_STYLES:
        raise ValidationError(
            f"유효하지 않은 편집 스타일: {edit_style}. 가능한 값: {', '.join(EDIT_STYLES)}"
        )
    return edit_style


def validate_api_key_format(key: str, key_name: str) -> bool:
    """API 키의 기본 형식을 검증합니다.

    Args:
        key: API 키 문자열.
        key_name: 키 이름 (에러 메시지용).

    Returns:
        검증 통과 여부.
    """
    if not key:
        return False
    if key_name == "ANTHROPIC_API_KEY" and not key.startswith("sk-ant-"):
        return False
    if len(key) < 10:
        return False
    return True
