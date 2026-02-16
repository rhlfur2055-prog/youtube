"""구조화된 로깅 설정.

파이프라인 단계별 컨텍스트, 민감정보 자동 마스킹,
파일 로깅, 색상 출력을 제공합니다.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import Optional

from youshorts.security.sanitizer import SensitiveDataFilter


class _ColorFormatter(logging.Formatter):
    """콘솔 출력에 색상을 적용하는 포매터."""

    COLORS = {
        logging.DEBUG: "\033[36m",     # cyan
        logging.INFO: "\033[32m",      # green
        logging.WARNING: "\033[33m",   # yellow
        logging.ERROR: "\033[31m",     # red
        logging.CRITICAL: "\033[1;31m",  # bold red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        formatted = super().format(record)
        if color and sys.stdout.isatty():
            return f"{color}{formatted}{self.RESET}"
        return formatted


class PipelineContextFilter(logging.Filter):
    """파이프라인 단계 컨텍스트를 로그에 추가하는 필터."""

    def __init__(self) -> None:
        super().__init__()
        self._step: str = ""

    def set_step(self, step: str) -> None:
        """현재 파이프라인 단계를 설정합니다."""
        self._step = step

    def filter(self, record: logging.LogRecord) -> bool:
        record.pipeline_step = self._step  # type: ignore[attr-defined]
        return True


# 싱글톤 컨텍스트 필터
_pipeline_filter = PipelineContextFilter()


def set_pipeline_step(step: str) -> None:
    """로그에 표시할 파이프라인 단계를 설정합니다.

    Args:
        step: 단계 문자열 (예: "[1/8 대본생성]").
    """
    _pipeline_filter.set_step(step)


def setup_logging(
    level: int = logging.INFO,
    log_dir: Optional[str] = None,
) -> None:
    """애플리케이션 로깅을 초기화합니다.

    Args:
        level: 로그 레벨.
        log_dir: 파일 로그 저장 디렉토리 (None이면 파일 로깅 비활성).
    """
    root = logging.getLogger("youshorts")
    root.setLevel(level)

    # 기존 핸들러 제거
    root.handlers.clear()

    # 민감정보 필터
    sensitive_filter = SensitiveDataFilter()

    # 콘솔 핸들러 (UTF-8 인코딩으로 래핑하여 Windows cp949 에러 방지)
    fmt = "%(asctime)s %(levelname)-7s %(pipeline_step)s %(message)s"
    date_fmt = "%H:%M:%S"

    # Windows에서 UTF-8 출력을 위해 stdout을 래핑
    import io
    utf8_stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",  # 인코딩 불가능 문자는 ? 로 대체
        line_buffering=True,
    )

    console_handler = logging.StreamHandler(utf8_stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(_ColorFormatter(fmt, datefmt=date_fmt))
    console_handler.addFilter(sensitive_filter)
    console_handler.addFilter(_pipeline_filter)
    root.addHandler(console_handler)

    # 파일 핸들러
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(log_dir, f"youshorts_{timestamp}.log")
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
        file_handler.addFilter(sensitive_filter)
        file_handler.addFilter(_pipeline_filter)
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """모듈별 로거를 생성합니다.

    Args:
        name: 모듈 이름 (__name__ 권장).

    Returns:
        구성된 Logger 인스턴스.
    """
    return logging.getLogger(f"youshorts.{name}")
