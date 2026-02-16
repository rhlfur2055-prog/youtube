"""보안 모듈 테스트."""

from __future__ import annotations

import logging

from pydantic import SecretStr

from youshorts.security.sanitizer import SensitiveDataFilter, sanitize_text
from youshorts.security.secrets_manager import SecretsManager
from youshorts.security.validators import (
    ValidationError,
    validate_api_key_format,
    validate_topic_input,
)


class TestSecretsManager:
    """SecretsManager 테스트."""

    def test_mask_key_standard(self) -> None:
        """API 키가 정상적으로 마스킹됩니다."""
        masked = SecretsManager.mask_key("sk-ant-api03-1234567890abcdef")
        assert "sk-ant" in masked
        assert "***" in masked
        assert "1234567890abcdef" not in masked

    def test_mask_key_short(self) -> None:
        """짧은 키는 완전히 마스킹됩니다."""
        masked = SecretsManager.mask_key("short")
        assert masked == "***"

    def test_get_secret_value(self) -> None:
        """SecretStr에서 값을 추출합니다."""
        secret = SecretStr("my-secret-key-12345")
        value = SecretsManager.get_secret_value(secret)
        assert value == "my-secret-key-12345"

    def test_validate_key_empty(self) -> None:
        """빈 키는 검증 실패합니다."""
        assert SecretsManager.validate_key("", "TEST_KEY") is False

    def test_validate_key_too_short(self) -> None:
        """짧은 키는 검증 실패합니다."""
        assert SecretsManager.validate_key("abc", "TEST_KEY") is False

    def test_validate_anthropic_key_wrong_prefix(self) -> None:
        """잘못된 접두사는 검증 실패합니다."""
        assert SecretsManager.validate_anthropic_key("wrong-prefix-key-12345") is False


class TestSanitizer:
    """SensitiveDataFilter 테스트."""

    def test_sanitize_anthropic_key(self) -> None:
        """Anthropic API 키가 마스킹됩니다."""
        text = "Error with key sk-ant-api03-abcdefghijklmnop"
        result = sanitize_text(text)
        assert "sk-ant-api03-abcdefghijklmnop" not in result
        assert "MASKED" in result

    def test_sanitize_bearer_token(self) -> None:
        """Bearer 토큰이 마스킹됩니다."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = sanitize_text(text)
        assert "eyJhbGci" not in result

    def test_filter_in_logging(self) -> None:
        """logging.Filter로서 정상 동작합니다."""
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Key: sk-ant-api03-secretkey123456789", args=(), exc_info=None,
        )
        filt.filter(record)
        assert "secretkey123456789" not in record.msg


class TestValidators:
    """입력 검증 테스트."""

    def test_validate_topic_normal(self) -> None:
        """정상 주제는 통과합니다."""
        result = validate_topic_input("한국인이 모르는 생활꿀팁")
        assert result == "한국인이 모르는 생활꿀팁"

    def test_validate_topic_empty(self) -> None:
        """빈 주제는 실패합니다."""
        try:
            validate_topic_input("")
            assert False, "Should have raised"
        except ValidationError:
            pass

    def test_validate_topic_too_long(self) -> None:
        """너무 긴 주제는 실패합니다."""
        try:
            validate_topic_input("x" * 201)
            assert False, "Should have raised"
        except ValidationError:
            pass

    def test_validate_api_key_format_anthropic(self) -> None:
        """Anthropic 키 형식 검증."""
        assert validate_api_key_format("sk-ant-api03-1234567890", "ANTHROPIC_API_KEY") is True
        assert validate_api_key_format("wrong-key", "ANTHROPIC_API_KEY") is False
        assert validate_api_key_format("", "ANTHROPIC_API_KEY") is False
