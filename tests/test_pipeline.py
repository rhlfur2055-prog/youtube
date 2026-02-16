"""pipeline 모듈 테스트."""

from __future__ import annotations

from youshorts.config.settings import Settings
from youshorts.core.pipeline import Pipeline, PipelineResult


class TestPipelineResult:
    """PipelineResult 데이터클래스 테스트."""

    def test_default_not_success(self) -> None:
        """기본 결과는 실패 상태입니다."""
        result = PipelineResult()
        assert result.success is False

    def test_with_output_is_success(self) -> None:
        """출력 경로가 있으면 성공 상태입니다."""
        result = PipelineResult(output_path="/path/to/output.mp4")
        assert result.success is True


class TestPipelineInit:
    """Pipeline 초기화 테스트."""

    def test_init_defaults(self, test_settings: Settings) -> None:
        """기본값으로 초기화됩니다."""
        pipeline = Pipeline(
            topic="테스트 주제",
            settings=test_settings,
        )
        assert pipeline.topic == "테스트 주제"
        assert pipeline.style == "creative"
        assert pipeline.edit_style is None

    def test_init_custom(self, test_settings: Settings) -> None:
        """커스텀 값으로 초기화됩니다."""
        pipeline = Pipeline(
            topic="테스트",
            style="analytical",
            edit_style="cinematic",
            label="A",
            settings=test_settings,
        )
        assert pipeline.style == "analytical"
        assert pipeline.edit_style == "cinematic"
        assert pipeline.label == "A"
