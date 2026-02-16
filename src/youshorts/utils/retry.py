"""재시도 데코레이터 (지수 백오프 + 지터).

API 호출, 네트워크 요청 등에서 일시적 실패를 자동 재시도합니다.
"""

from __future__ import annotations

import functools
import logging
import random
import time
from typing import Any, Callable, Sequence, Type, TypeVar

logger = logging.getLogger("youshorts.retry")

F = TypeVar("F", bound=Callable[..., Any])

# 기본 재시도 대상 예외
DEFAULT_RETRYABLE: tuple[Type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def retry(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    jitter: float = 0.5,
    retryable_exceptions: Sequence[Type[BaseException]] = DEFAULT_RETRYABLE,
) -> Callable[[F], F]:
    """지수 백오프 + 지터 방식의 재시도 데코레이터.

    Args:
        max_retries: 최대 재시도 횟수.
        backoff_factor: 대기 시간 배수.
        jitter: 대기 시간에 추가할 랜덤 범위 (초).
        retryable_exceptions: 재시도 대상 예외 타입.

    Returns:
        데코레이터 함수.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except tuple(retryable_exceptions) as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait = backoff_factor ** attempt + random.uniform(0, jitter)
                        logger.warning(
                            "%s 실패 (시도 %d/%d): %s. %.1f초 후 재시도...",
                            func.__name__,
                            attempt + 1,
                            max_retries + 1,
                            e,
                            wait,
                        )
                        time.sleep(wait)
                    else:
                        logger.error(
                            "%s 최종 실패 (%d회 시도): %s",
                            func.__name__,
                            max_retries + 1,
                            e,
                        )
            raise last_exception  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
