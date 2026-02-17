# 변경 사유: Claude AI 기반 심층 품질 체크 함수 추가
"""콘텐츠 품질 체크 모듈.

대본 품질 점수 채점, 팩트체크 대상 식별,
허위정보 방지, 출처 명시 확인, AI 심층 분석을 수행합니다.
"""

from __future__ import annotations

import re
from typing import Any

from youshorts.utils.logger import get_logger

logger = get_logger(__name__)


def check_script_quality(
    script: dict[str, Any],
    style: str = "community",
) -> tuple[int, list[str], list[str]]:
    """대본 품질 점수를 계산합니다 (100점 만점 감점 방식).

    Args:
        script: 대본 딕셔너리.
        style: 대본 스타일.

    Returns:
        (score, issues, suggestions).
    """
    text = script.get("tts_script", script.get("full_script", ""))
    title = script.get("title", "")
    issues: list[str] = []
    suggestions: list[str] = []
    score = 100

    # ── 1. 길이 체크 ──
    if len(text) < 150:
        issues.append(f"대본 너무 짧음 ({len(text)}자 < 150자)")
        score -= 20
    elif len(text) > 500:
        issues.append(f"대본 너무 김 ({len(text)}자 > 500자)")
        score -= 10

    # ── 2. AI 슬롭 감점 (1개당 -15점) ──
    ai_slop = [
        '여러분', '선택은', '어떻게 생각', '경제학', '딜레마', '철학',
        '마무리하며', '결론적으로', '요약하자면', '의견을', '남겨주세요',
        '살펴보겠습니다', '흥미로운', '놀라운',
    ]
    for kw in ai_slop:
        if kw in text:
            issues.append(f"AI 슬롭 발견: '{kw}'")
            score -= 15

    # ── 3. 볼드체 잔존 ──
    if '**' in text:
        issues.append("볼드체(**) 잔존")
        score -= 10

    # ── 4. 사람 이름 감점 ──
    name_prefixes = '김이박최정강조윤장임한오서신권황안송류홍'
    names = re.findall(
        rf'[{name_prefixes}][가-힣]{{1,2}}(?:이|가|는|을|를|의|에게|한테|씨)',
        text,
    )
    if names:
        issues.append(f"AI 생성 이름 발견: {names[:3]}")
        score -= 20

    # ── 5. 커뮤니티 말투 체크 ──
    community_markers = ['ㅋㅋ', 'ㄷㄷ', 'ㄹㅇ', '실화', '레전드', '소름', '빡치', '개웃']
    marker_count = sum(1 for m in community_markers if m in text)
    if marker_count == 0:
        issues.append("커뮤니티 말투 없음")
        score -= 15

    # ── 6. 첫 문장 체크 ──
    first_sentence = text[:20]
    good_starts = ['야', '아니', '실화', '이거', 'ㅋㅋ', '와', '헐']
    if not any(s in first_sentence for s in good_starts):
        suggestions.append("첫 문장에 '야/아니/실화' 등으로 시작 권장")
        score -= 5

    # ── 7. 마지막 문장 체크 ──
    last_30 = text[-30:]
    good_ends = ['ㅋㅋ', 'ㄷㄷ', '실화', '레전드', '소름', '말이 됨']
    if not any(e in last_30 for e in good_ends):
        suggestions.append("마지막에 'ㅋㅋ/ㄷㄷ/레전드' 등으로 마무리 권장")
        score -= 5

    # ── 8. 허위 정보 패턴 ──
    misleading_patterns = [
        (r'100%\s*(확실|보장|효과)', "100% 보장 표현"),
        (r'반드시\s*(치료|완치)', "의학적 보장 표현"),
        (r'(무조건|절대)\s*(돈|수익)', "금전적 보장 표현"),
    ]
    for pattern, warning in misleading_patterns:
        if re.search(pattern, text):
            issues.append(f"주의: {warning}")
            score -= 10

    # ── 9. 반복 문장 ──
    sentences = re.split(r'[.!?]', text)
    seen: set[str] = set()
    for sent in sentences:
        clean = sent.strip()
        if len(clean) > 10 and clean in seen:
            issues.append("반복 문장 발견")
            score -= 5
            break
        seen.add(clean)

    score = max(0, min(100, score))
    return score, issues, suggestions


def check_factual_claims(
    script: dict[str, Any],
) -> list[dict[str, Any]]:
    """팩트체크가 필요한 부분을 식별합니다.

    Args:
        script: 대본 딕셔너리.

    Returns:
        팩트체크 대상 리스트.
    """
    full_script = script.get("full_script", "")
    claims: list[dict[str, Any]] = []

    stat_patterns = [
        (r'(\d+[\d.]*)\s*(%|퍼센트)', "통계 수치"),
        (r'(\d+[\d.]*)\s*(명|만명|억|만)', "인원/규모 수치"),
        (r'(\d+[\d.]*)\s*(배|倍)', "비교 수치"),
        (r'연구\s*(결과|에\s*따르면)', "연구 인용"),
        (r'(전문가|과학자|의사)\s*(들이|가|에\s*따르면)', "전문가 인용"),
    ]

    for pattern, claim_type in stat_patterns:
        matches = re.finditer(pattern, full_script)
        for match in matches:
            claims.append({
                "claim": match.group(0),
                "context": full_script[max(0, match.start() - 20):match.end() + 20],
                "type": claim_type,
                "needs_verification": True,
            })

    return claims


def check_quality_with_ai(
    script: dict[str, Any],
    settings: Any = None,
) -> dict[str, Any]:
    """Claude AI를 활용한 심층 품질 분석을 수행합니다.

    대본의 독창성, 수익창출 적합성, 팩트 정확성 등을
    Claude API로 분석합니다.

    Args:
        script: 대본 딕셔너리.
        settings: 설정 인스턴스.

    Returns:
        AI 분석 결과 딕셔너리.
    """
    import anthropic

    from youshorts.config.settings import get_settings
    from youshorts.security.secrets_manager import SecretsManager

    if settings is None:
        settings = get_settings()

    api_key = SecretsManager.get_secret_value(settings.anthropic_api_key)
    client = anthropic.Anthropic(api_key=api_key)

    full_script = script.get("full_script", "")
    title = script.get("title", "")
    opinion = script.get("creator_opinion", "")

    prompt = f"""당신은 YouTube Shorts 콘텐츠 품질 검수관입니다.
아래 대본을 분석하여 JSON으로 평가해주세요.

제목: {title}
대본: {full_script}
크리에이터 의견: {opinion}

평가 항목:
1. monetization_safe (bool): YouTube 수익창출 정책 준수 여부
2. originality_score (0-100): 독창성 점수
3. engagement_score (0-100): 시청자 참여 유도 점수
4. fact_accuracy (0-100): 사실 정확성 점수
5. improvements (list[str]): 구체적 개선 제안 3개
6. risk_flags (list[str]): 수익창출 위험 요소
7. overall_grade (str): A/B/C/D/F 등급

JSON만 출력:
{{"monetization_safe": true, "originality_score": 80, "engagement_score": 75, "fact_accuracy": 70, "improvements": ["제안1", "제안2", "제안3"], "risk_flags": [], "overall_grade": "B"}}"""

    logger.info("AI 품질 분석 요청 중...")

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )

        import json
        text = message.content[0].text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        result = json.loads(text.strip())
        logger.info(
            "AI 분석 완료 - 등급: %s, 독창성: %d, 참여도: %d",
            result.get("overall_grade", "?"),
            result.get("originality_score", 0),
            result.get("engagement_score", 0),
        )
        return result

    except Exception as e:
        logger.warning("AI 품질 분석 실패: %s", e)
        return {
            "monetization_safe": True,
            "originality_score": 0,
            "engagement_score": 0,
            "fact_accuracy": 0,
            "improvements": [],
            "risk_flags": [],
            "overall_grade": "N/A",
            "error": str(e),
        }


def log_quality_report(
    score: int,
    issues: list[str],
    suggestions: list[str],
    claims: list[dict[str, Any]],
    ai_result: dict[str, Any] | None = None,
) -> None:
    """품질 리포트를 로깅합니다.

    Args:
        score: 품질 점수.
        issues: 문제점 리스트.
        suggestions: 제안 리스트.
        claims: 팩트체크 대상 리스트.
        ai_result: AI 분석 결과 (선택).
    """
    grade = "(우수)" if score >= 80 else "(보통)" if score >= 60 else "(개선 필요)"
    logger.info("품질 점수: %d/100 %s", score, grade)

    if issues:
        logger.info("문제점:")
        for issue in issues:
            logger.info("  - %s", issue)

    if suggestions:
        logger.info("제안:")
        for sug in suggestions:
            logger.info("  - %s", sug)

    if claims:
        logger.info("팩트체크 필요: %d건", len(claims))
        for claim in claims[:3]:
            logger.info("  [%s] \"%s\"", claim["type"], claim["claim"])

    if ai_result and ai_result.get("overall_grade") != "N/A":
        logger.info("AI 분석 등급: %s", ai_result["overall_grade"])
        logger.info(
            "  독창성: %d | 참여도: %d | 정확성: %d",
            ai_result.get("originality_score", 0),
            ai_result.get("engagement_score", 0),
            ai_result.get("fact_accuracy", 0),
        )
        if ai_result.get("improvements"):
            logger.info("AI 개선 제안:")
            for imp in ai_result["improvements"][:3]:
                logger.info("  - %s", imp)
        if ai_result.get("risk_flags"):
            logger.info("수익창출 위험:")
            for flag in ai_result["risk_flags"]:
                logger.info("  - %s", flag)
