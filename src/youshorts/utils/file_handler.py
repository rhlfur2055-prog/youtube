"""파일 I/O 유틸리티.

JSON 읽기/쓰기, atomic write, 디렉토리 생성 등을 제공합니다.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def ensure_dir(path: str) -> str:
    """디렉토리가 존재하지 않으면 생성합니다.

    Args:
        path: 디렉토리 경로.

    Returns:
        생성된/확인된 디렉토리 경로.
    """
    os.makedirs(path, exist_ok=True)
    return path


def read_json(filepath: str, default: Any = None) -> Any:
    """JSON 파일을 안전하게 읽습니다.

    Args:
        filepath: JSON 파일 경로.
        default: 파일이 없거나 파싱 실패 시 반환할 기본값.

    Returns:
        파싱된 JSON 데이터 또는 default.
    """
    if not os.path.exists(filepath):
        return default if default is not None else []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default if default is not None else []


def write_json(filepath: str, data: Any) -> str:
    """JSON 파일을 atomic write로 안전하게 저장합니다.

    임시 파일에 쓴 후 rename하여 중간 실패 시 데이터 손실을 방지합니다.

    Args:
        filepath: 저장할 파일 경로.
        data: JSON으로 직렬화할 데이터.

    Returns:
        저장된 파일 경로.
    """
    ensure_dir(os.path.dirname(filepath))
    dir_path = os.path.dirname(filepath)

    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # Windows에서는 기존 파일을 먼저 삭제해야 rename 가능
        if os.path.exists(filepath):
            os.replace(tmp_path, filepath)
        else:
            os.rename(tmp_path, filepath)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return filepath
