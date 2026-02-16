"""tts_engine 모듈 테스트."""

from __future__ import annotations

from youshorts.core.tts_engine import _build_word_groups_from_timings, _chunk_text_by_chars


class TestChunkTextByChars:
    """_chunk_text_by_chars 함수 테스트."""

    def test_basic_split(self) -> None:
        """기본 텍스트 분할이 정상 동작합니다."""
        chunks = _chunk_text_by_chars("안녕하세요 반갑습니다 좋은 하루 되세요")
        assert len(chunks) >= 1
        for chunk in chunks:
            # 각 청크의 글자 수 (공백 제외)가 12 이하
            assert len(chunk.replace(" ", "")) <= 12

    def test_empty_text(self) -> None:
        """빈 텍스트는 빈 리스트를 반환합니다."""
        chunks = _chunk_text_by_chars("")
        assert chunks == []

    def test_single_word(self) -> None:
        """단일 단어는 하나의 청크로 반환됩니다."""
        chunks = _chunk_text_by_chars("안녕")
        assert len(chunks) == 1
        assert chunks[0] == "안녕"

    def test_no_word_split(self) -> None:
        """단어 중간에서 끊기지 않습니다."""
        chunks = _chunk_text_by_chars("안녕하세요 반갑습니다")
        for chunk in chunks:
            assert not chunk.startswith(" ")
            assert not chunk.endswith(" ")


class TestBuildWordGroupsFromTimings:
    """_build_word_groups_from_timings 함수 테스트."""

    def test_basic_grouping(self) -> None:
        """기본 타이밍 그룹화가 정상 동작합니다."""
        timings = [
            {"text": "안녕하세요", "start": 0.0, "end": 0.5},
            {"text": "반갑습니다", "start": 0.5, "end": 1.0},
            {"text": "좋은", "start": 1.0, "end": 1.3},
            {"text": "하루", "start": 1.3, "end": 1.6},
            {"text": "되세요", "start": 1.6, "end": 2.0},
        ]
        groups = _build_word_groups_from_timings(timings, chunk_size=10)
        assert len(groups) >= 1
        # 각 그룹에 start, end, text 키가 있어야 함
        for group in groups:
            assert "start" in group
            assert "end" in group
            assert "text" in group

    def test_timing_order(self) -> None:
        """그룹의 타이밍이 순서대로입니다."""
        timings = [
            {"text": "첫째", "start": 0.0, "end": 0.5},
            {"text": "둘째", "start": 0.5, "end": 1.0},
            {"text": "셋째", "start": 1.0, "end": 1.5},
        ]
        groups = _build_word_groups_from_timings(timings)
        for i in range(1, len(groups)):
            assert groups[i]["start"] >= groups[i - 1]["start"]

    def test_empty_timings(self) -> None:
        """빈 타이밍은 빈 리스트를 반환합니다."""
        groups = _build_word_groups_from_timings([])
        assert groups == []
