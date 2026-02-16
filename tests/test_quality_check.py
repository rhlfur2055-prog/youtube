"""quality_check 모듈 테스트."""

from __future__ import annotations

from typing import Any

from youshorts.quality.quality_check import check_factual_claims, check_script_quality


class TestCheckScriptQuality:
    """check_script_quality 함수 테스트."""

    def test_high_quality_script(self, sample_script: dict[str, Any]) -> None:
        """정상 대본은 높은 점수를 받아야 합니다."""
        score, issues, suggestions = check_script_quality(sample_script)
        assert score >= 60

    def test_short_script_penalized(self, sample_script: dict[str, Any]) -> None:
        """짧은 대본은 감점됩니다."""
        sample_script["full_script"] = "짧은 대본."
        score, issues, _ = check_script_quality(sample_script)
        assert score < 100
        assert any("짧" in i for i in issues)

    def test_missing_opinion_penalized(self, sample_script: dict[str, Any]) -> None:
        """크리에이터 의견 누락 시 감점됩니다."""
        sample_script["creator_opinion"] = ""
        score, issues, _ = check_script_quality(sample_script)
        assert any("의견" in i or "분석" in i for i in issues)

    def test_missing_storytelling_penalized(self, sample_script: dict[str, Any]) -> None:
        """스토리텔링 구조 불완전 시 감점됩니다."""
        sample_script["hook"] = ""
        sample_script["twist"] = ""
        score, issues, _ = check_script_quality(sample_script)
        assert any("스토리텔링" in i for i in issues)

    def test_misleading_claim_detected(self, sample_script: dict[str, Any]) -> None:
        """허위 정보 패턴이 감지됩니다."""
        sample_script["full_script"] = "이 방법은 100% 확실한 효과가 있습니다."
        score, issues, _ = check_script_quality(sample_script)
        assert any("100%" in i for i in issues)


class TestCheckFactualClaims:
    """check_factual_claims 함수 테스트."""

    def test_statistical_claims_detected(self, sample_script: dict[str, Any]) -> None:
        """통계 수치가 감지됩니다."""
        claims = check_factual_claims(sample_script)
        assert len(claims) >= 1

    def test_empty_script_no_claims(self) -> None:
        """빈 대본에는 팩트체크 대상이 없습니다."""
        claims = check_factual_claims({"full_script": ""})
        assert claims == []
