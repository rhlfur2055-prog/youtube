"""script_generator 모듈 테스트."""

from __future__ import annotations

from youshorts.core.script_generator import _generate_topic_keywords, _parse_script_response


class TestGenerateTopicKeywords:
    """_generate_topic_keywords 함수 테스트."""

    def test_health_topic(self) -> None:
        """건강 관련 주제에서 영어 키워드를 생성합니다."""
        keywords = _generate_topic_keywords("건강한 생활습관")
        assert len(keywords) == 4
        assert all(isinstance(k, str) for k in keywords)

    def test_money_topic(self) -> None:
        """돈 관련 주제에서 영어 키워드를 생성합니다."""
        keywords = _generate_topic_keywords("돈 모으는 방법")
        assert "saving" in keywords[0].lower() or "money" in keywords[0].lower()

    def test_unknown_topic_fallback(self) -> None:
        """알 수 없는 주제에서 기본 키워드를 반환합니다."""
        keywords = _generate_topic_keywords("우주의 신비")
        assert len(keywords) == 4


class TestParseScriptResponse:
    """_parse_script_response 함수 테스트."""

    def test_parse_json_block(self) -> None:
        """```json 블록을 파싱합니다."""
        response = '```json\n{"title": "테스트 제목"}\n```'
        result = _parse_script_response(response)
        assert result["title"] == "테스트 제목"

    def test_parse_plain_json(self) -> None:
        """순수 JSON을 파싱합니다."""
        response = '{"title": "테스트"}'
        result = _parse_script_response(response)
        assert result["title"] == "테스트"

    def test_parse_code_block(self) -> None:
        """``` 블록을 파싱합니다."""
        response = '```\n{"title": "코드블록"}\n```'
        result = _parse_script_response(response)
        assert result["title"] == "코드블록"
