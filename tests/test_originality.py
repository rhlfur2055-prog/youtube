"""originality 모듈 테스트."""

from __future__ import annotations

import os
from typing import Any

from youshorts.config.settings import Settings
from youshorts.quality.originality import (
    _compute_similarity,
    check_originality,
    save_to_history,
)
from youshorts.utils.file_handler import write_json


class TestComputeSimilarity:
    """_compute_similarity 함수 테스트."""

    def test_identical_texts(self) -> None:
        """동일 텍스트의 유사도는 1.0에 가까워야 합니다."""
        sim = _compute_similarity("안녕하세요 반갑습니다", "안녕하세요 반갑습니다")
        assert sim > 0.95

    def test_different_texts(self) -> None:
        """전혀 다른 텍스트의 유사도는 낮아야 합니다."""
        sim = _compute_similarity(
            "오늘 날씨가 좋습니다 산책을 갑시다",
            "프로그래밍 언어 파이썬을 배웁시다",
        )
        assert sim < 0.5

    def test_empty_texts(self) -> None:
        """빈 텍스트는 유사도 0.0입니다."""
        sim = _compute_similarity("", "")
        assert sim == 0.0


class TestCheckOriginality:
    """check_originality 함수 테스트."""

    def test_no_history_is_original(
        self,
        sample_script: dict[str, Any],
        test_settings: Settings,
    ) -> None:
        """히스토리가 없으면 독창적으로 판단됩니다."""
        is_original, max_sim, _ = check_originality(sample_script, settings=test_settings)
        assert is_original is True
        assert max_sim == 0.0

    def test_similar_script_detected(
        self,
        sample_script: dict[str, Any],
        test_settings: Settings,
    ) -> None:
        """유사한 대본이 감지됩니다."""
        os.makedirs(test_settings.data_dir, exist_ok=True)
        # 기존 히스토리 저장
        history = [{
            "title": sample_script["title"],
            "script": sample_script["full_script"],
            "style": "creative",
        }]
        write_json(test_settings.history_file, history)

        is_original, max_sim, _ = check_originality(sample_script, settings=test_settings)
        assert max_sim > 0.5


class TestSaveToHistory:
    """save_to_history 함수 테스트."""

    def test_save_creates_file(
        self,
        sample_script: dict[str, Any],
        test_settings: Settings,
    ) -> None:
        """히스토리 저장 후 파일이 생성됩니다."""
        save_to_history(sample_script, "dynamic", "/fake/path.mp4", settings=test_settings)
        assert os.path.exists(test_settings.history_file)
        assert os.path.exists(test_settings.style_log_file)
