"""API 키 안전 로딩, 검증, 마스킹 관리.

API 키를 .env / 환경변수에서 로딩하고,
로그 출력 시 마스킹, 접근 감사 로깅을 제공합니다.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import SecretStr

logger = logging.getLogger(__name__)

# API 키 패턴 (마스킹 대상)
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-api\S{5,}"),       # Anthropic
    re.compile(r"sk-ant-\S{5,}"),           # Anthropic (legacy)
    re.compile(r"Bearer\s+\S{10,}"),        # Bearer tokens
    re.compile(r"[A-Za-z0-9]{30,60}"),      # Pexels / generic long keys
]


class SecretsManager:
    """API 키의 안전한 접근과 마스킹을 담당합니다."""

    @staticmethod
    def mask_key(key: str, visible_prefix: int = 6, visible_suffix: int = 3) -> str:
        """API 키를 마스킹합니다.

        Args:
            key: 원본 API 키.
            visible_prefix: 노출할 앞 글자 수.
            visible_suffix: 노출할 뒤 글자 수.

        Returns:
            "sk-ant-***...***abc" 형태의 마스킹된 문자열.
        """
        if len(key) <= visible_prefix + visible_suffix:
            return "***"
        return f"{key[:visible_prefix]}***...***{key[-visible_suffix:]}"

    @staticmethod
    def get_secret_value(secret: SecretStr) -> str:
        """SecretStr에서 실제 값을 안전하게 추출합니다.

        Args:
            secret: pydantic SecretStr 인스턴스.

        Returns:
            복호화된 키 문자열.
        """
        value = secret.get_secret_value()
        if value:
            logger.debug("API 키 접근됨 (마스킹: %s)", SecretsManager.mask_key(value))
        return value

    @staticmethod
    def mask_string(text: str) -> str:
        """문자열에서 모든 API 키 패턴을 마스킹합니다.

        Args:
            text: 검사할 텍스트.

        Returns:
            마스킹된 텍스트.
        """
        result = text
        for pattern in _SECRET_PATTERNS:
            result = pattern.sub(
                lambda m: SecretsManager.mask_key(m.group(0)),
                result,
            )
        return result

    @staticmethod
    def validate_key(key: str, key_name: str) -> bool:
        """API 키의 기본 형식을 검증합니다.

        Args:
            key: 검사할 API 키.
            key_name: 키 이름 (에러 메시지용).

        Returns:
            검증 통과 여부.
        """
        if not key:
            logger.warning("%s 가 설정되지 않았습니다.", key_name)
            return False
        if len(key) < 10:
            logger.warning("%s 형식이 올바르지 않습니다 (너무 짧음).", key_name)
            return False
        return True

    @staticmethod
    def validate_anthropic_key(key: str) -> bool:
        """Anthropic API 키 형식을 검증합니다."""
        if not key:
            return False
        if not key.startswith("sk-ant-"):
            logger.warning("ANTHROPIC_API_KEY 형식이 올바르지 않습니다 (sk-ant- 접두사 필요).")
            return False
        return SecretsManager.validate_key(key, "ANTHROPIC_API_KEY")
