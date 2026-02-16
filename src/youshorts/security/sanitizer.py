"""로그 및 에러 메시지에서 민감 정보를 필터링합니다.

logging.Filter를 상속하여 모든 로그에서
API 키 패턴을 자동으로 마스킹합니다.
"""

from __future__ import annotations

import logging
import re
import traceback
from typing import Optional

# 마스킹 대상 정규식 패턴
_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-ant-api\S+"), "[ANTHROPIC_KEY_MASKED]"),
    (re.compile(r"sk-ant-\S+"), "[ANTHROPIC_KEY_MASKED]"),
    (re.compile(r"apify_api_[a-zA-Z0-9]+"), "[APIFY_KEY_MASKED]"),
    (re.compile(r"ya29\.[a-zA-Z0-9_-]+"), "[GOOGLE_TOKEN_MASKED]"),
    (re.compile(r"Bearer\s+\S{10,}"), "Bearer [TOKEN_MASKED]"),
    (re.compile(r"(?<=Authorization:\s)\S{10,}"), "[API_KEY_MASKED]"),
    (re.compile(r"(?<=api_key=)\S{10,}"), "[API_KEY_MASKED]"),
    (re.compile(r"(?<=key=)\S{10,}"), "[API_KEY_MASKED]"),
    (re.compile(r"(?<=token=)\S{10,}"), "[TOKEN_MASKED]"),
    (re.compile(r"(?<=secret=)\S{10,}"), "[SECRET_MASKED]"),
]


class SensitiveDataFilter(logging.Filter):
    """로그 레코드에서 민감 데이터를 자동 마스킹하는 필터."""

    def filter(self, record: logging.LogRecord) -> bool:
        """로그 메시지 및 예외 정보에서 민감 정보를 제거합니다.

        Args:
            record: 로그 레코드.

        Returns:
            항상 True (로그는 출력하되 내용만 정화).
        """
        if isinstance(record.msg, str):
            record.msg = sanitize_text(record.msg)
        if record.args:
            record.args = tuple(
                sanitize_text(str(a)) if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        if record.exc_text:
            record.exc_text = sanitize_text(record.exc_text)
        return True


def sanitize_text(text: str) -> str:
    """텍스트에서 모든 민감 패턴을 마스킹합니다.

    Args:
        text: 원본 텍스트.

    Returns:
        정화된 텍스트.
    """
    result = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def sanitize_traceback(exc: Optional[BaseException] = None) -> str:
    """예외의 traceback에서 민감 정보를 제거합니다.

    Args:
        exc: 예외 인스턴스 (None이면 현재 예외 사용).

    Returns:
        정화된 traceback 문자열.
    """
    if exc:
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        tb_text = traceback.format_exc()
    return sanitize_text(tb_text)
