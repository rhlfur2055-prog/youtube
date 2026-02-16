# 변경 사유: 제목/태그 자동 생성 개선 + AI 사용 공시 강화 + 대본 저장
"""YouTube 메타데이터 생성 모듈.

영상 설명, 태그, 해시태그, AI 공시 정보를 포함한
YouTube 업로드용 JSON 메타데이터를 생성합니다.

주요 기능:
- 클릭 유발 제목 패턴 자동 적용
- 주제 관련 해시태그 자동 생성
- AI 사용 공시 자동 삽입 (유튜브 정책 대응)
- 대본 data/scripts/ 저장 (수동 검토용)
"""

from __future__ import annotations

import os
import random
from datetime import datetime
from typing import Any

from youshorts.config.settings import Settings, get_settings
from youshorts.utils.file_handler import ensure_dir, write_json
from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# 제목 패턴 (CTR 높은 유형)
# ============================================================
_TITLE_PATTERNS: list[str] = [
    "[충격] {topic}의 현실",
    "{topic}하면 생기는 일",
    "한국에서만 가능한 {topic}",
    "이거 나만 몰랐어?",
    "{topic} 레전드 ㄷㄷ",
    "{topic} 실화?!",
    "소름주의) {topic}",
    "{topic} 근황이 미쳤다",
    "{topic} 알고나면 소름",
    "아직도 이거 모르는 사람?",
]

# ============================================================
# 기본 해시태그 (주제 관련 태그 자동 추가)
# ============================================================
_BASE_HASHTAGS: list[str] = [
    "#쇼츠", "#shorts", "#한국", "#레전드", "#실화",
]

_TOPIC_HASHTAG_MAP: dict[str, list[str]] = {
    "경제": ["#경제", "#돈", "#재테크", "#투자", "#절약"],
    "돈": ["#돈", "#재테크", "#투자", "#부업", "#월급"],
    "직장": ["#직장인", "#회사", "#퇴사", "#연봉", "#야근"],
    "회사": ["#직장인", "#회사생활", "#상사", "#퇴사", "#야근"],
    "퇴사": ["#퇴사", "#이직", "#프리랜서", "#자유", "#직장인"],
    "음식": ["#맛집", "#음식", "#먹방", "#요리", "#배달"],
    "여행": ["#여행", "#해외여행", "#국내여행", "#관광", "#힐링"],
    "연애": ["#연애", "#소개팅", "#사랑", "#썸", "#커플"],
    "소개팅": ["#소개팅", "#연애", "#첫만남", "#레전드", "#썸"],
    "공포": ["#공포", "#소름", "#미스터리", "#실화", "#무서운이야기"],
    "미스터리": ["#미스터리", "#소름", "#공포", "#실화", "#충격"],
    "외국인": ["#외국인반응", "#한국", "#K컬처", "#문화충격", "#리액션"],
    "군대": ["#군대", "#군생활", "#현역", "#전역", "#훈련소"],
    "법률": ["#법률", "#법", "#상식", "#법꿀팁", "#불법"],
    "부동산": ["#부동산", "#집값", "#전세", "#월세", "#청약"],
    "알바": ["#알바", "#아르바이트", "#편의점", "#카페", "#최저시급"],
    "사기": ["#사기", "#주의", "#조심", "#당근마켓", "#중고거래"],
    "CCTV": ["#CCTV", "#소름", "#실화", "#충격영상", "#미스터리"],
}


def _generate_title(script: dict[str, Any]) -> str:
    """클릭 유발 제목을 생성합니다.

    LLM이 생성한 youtube_titles가 있으면 그 중 랜덤,
    없으면 패턴 기반 자동 생성.

    Args:
        script: 대본 딕셔너리.

    Returns:
        최종 제목 문자열.
    """
    youtube_titles = script.get("youtube_titles", [])
    if youtube_titles and len(youtube_titles) > 0:
        # LLM이 생성한 제목 중 랜덤 선택
        return random.choice(youtube_titles)

    # 폴백: 패턴 기반 제목 생성
    topic = script.get("title", "")
    if topic:
        pattern = random.choice(_TITLE_PATTERNS)
        return pattern.format(topic=topic[:8])

    return script.get("title", "")


def _generate_hashtags(script: dict[str, Any]) -> list[str]:
    """주제 관련 해시태그를 자동 생성합니다.

    기본 태그 5개 + 주제 관련 태그 5개 = 최대 10개.

    Args:
        script: 대본 딕셔너리.

    Returns:
        해시태그 리스트.
    """
    hashtags = list(_BASE_HASHTAGS)

    # LLM이 생성한 해시태그 추가
    llm_hashtags = script.get("hashtags", [])
    for tag in llm_hashtags:
        if tag not in hashtags:
            hashtags.append(tag)

    # 주제 기반 해시태그 추가
    title = script.get("title", "")
    full_script = script.get("full_script", "")
    topic_text = f"{title} {full_script}"

    for keyword, tags in _TOPIC_HASHTAG_MAP.items():
        if keyword in topic_text:
            for tag in tags:
                if tag not in hashtags:
                    hashtags.append(tag)
            break

    # 키워드 기반 해시태그 추가
    keywords = script.get("keywords", [])
    for kw in keywords[:3]:
        tag = f"#{kw}"
        if tag not in hashtags:
            hashtags.append(tag)

    return hashtags[:10]


def _generate_seo_tags(script: dict[str, Any]) -> list[str]:
    """SEO 최적화 태그를 생성합니다.

    Args:
        script: 대본 딕셔너리.

    Returns:
        태그 리스트 (최대 20개).
    """
    tags: list[str] = []

    # LLM이 생성한 seo_tags
    seo_tags = script.get("seo_tags", [])
    tags.extend(seo_tags)

    # 키워드 추가
    keywords = script.get("keywords", [])
    tags.extend(keywords)

    # 기본 태그
    base_tags = ["숏츠", "shorts", "한국", "꿀팁", "정보", "지식", "레전드", "실화", "소름"]
    for t in base_tags:
        if t not in tags:
            tags.append(t)

    # 중복 제거
    seen = set()
    unique: list[str] = []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            unique.append(t)

    return unique[:20]


def save_script_for_review(
    script: dict[str, Any],
    settings: Settings,
) -> str:
    """대본을 data/scripts/ 폴더에 저장합니다 (수동 검토용).

    유튜브 정책 대응: 사람의 개입 흔적을 남기기 위해
    생성된 대본을 별도 파일로 저장합니다.

    Args:
        script: 대본 딕셔너리.
        settings: 설정 인스턴스.

    Returns:
        저장된 파일 경로.
    """
    scripts_dir = os.path.join(settings.data_dir, "scripts")
    ensure_dir(scripts_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title_slug = script.get("title", "untitled")[:20].replace(" ", "_")
    filename = f"script_{title_slug}_{timestamp}.txt"
    filepath = os.path.join(scripts_dir, filename)

    # 사람이 읽기 쉬운 형태로 저장
    lines = [
        f"제목: {script.get('title', '')}",
        f"스타일: {script.get('style', '')}",
        f"템플릿: {script.get('template_used', '')}",
        f"LLM: {script.get('llm_backend', '')}",
        f"생성시간: {datetime.now().isoformat()}",
        "",
        "=" * 50,
        "전체 대본 (TTS용)",
        "=" * 50,
        script.get("tts_script", script.get("full_script", "")),
        "",
        "=" * 50,
        "YouTube 제목 후보",
        "=" * 50,
    ]
    for i, t in enumerate(script.get("youtube_titles", []), 1):
        lines.append(f"  {i}. {t}")

    lines.extend([
        "",
        "=" * 50,
        "해시태그",
        "=" * 50,
        " ".join(script.get("hashtags", [])),
        "",
        "=" * 50,
        "검토 메모 (수동 입력)",
        "=" * 50,
        "[ ] 대본 내용 확인",
        "[ ] 팩트 체크 완료",
        "[ ] 업로드 승인",
        "",
    ])

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("대본 저장 (검토용): %s", filepath)
    return filepath


def generate_metadata(
    script: dict[str, Any],
    output_path: str,
    edit_style: str,
    settings: Settings | None = None,
) -> tuple[dict[str, Any], str]:
    """YouTube 업로드용 메타데이터를 생성합니다.

    AI 사용 공시가 자동으로 포함됩니다 (유튜브 정책 대응).

    Args:
        script: 대본 딕셔너리.
        output_path: 영상 파일 경로.
        edit_style: 사용된 편집 스타일.
        settings: 설정 인스턴스.

    Returns:
        (메타데이터 딕셔너리, 메타데이터 파일 경로).
    """
    if settings is None:
        settings = get_settings()

    # 제목 생성 (CTR 높은 패턴)
    title = _generate_title(script)
    keywords = script.get("keywords", [])
    fact_sources = script.get("fact_sources", [])
    unique_angle = script.get("unique_angle", "")

    # 해시태그 자동 생성
    hashtags = _generate_hashtags(script)

    # SEO 태그
    tags = _generate_seo_tags(script)

    # ── Description ──
    description_parts = [
        f"{title}",
        "",
        script.get("hook", "")[:50] + "...",
        "",
        "---",
        "",
    ]

    if script.get("creator_opinion"):
        description_parts.append(f"이 영상의 포인트: {unique_angle}")
        description_parts.append("")

    if fact_sources:
        description_parts.append("참고 자료:")
        for src in fact_sources:
            description_parts.append(f"  - {src}")
        description_parts.append("")

    # LLM이 생성한 description_draft가 있으면 활용
    description_draft = script.get("description_draft", "")
    if description_draft:
        description_parts.append(description_draft)
        description_parts.append("")

    # AI 사용 공시 (유튜브 정책 필수)
    description_parts.extend([
        "---",
        "이 영상은 AI 도구를 활용하여 제작되었습니다.",
        "대본 구성, 분석, 의견은 크리에이터의 독창적 관점입니다.",
        "사용된 도구: AI 대본 생성, TTS 음성 합성, 자동 편집",
        "",
    ])

    if hashtags:
        description_parts.append(" ".join(hashtags))

    description = "\n".join(description_parts)

    # ── Metadata ──
    metadata: dict[str, Any] = {
        "title": title,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "category": "22",
        "privacy": "public",
        "made_for_kids": False,
        "ai_disclosure": True,
        "ai_tools_used": [
            "AI 대본 생성 (LLM)",
            "TTS 음성 합성 (edge-tts / ElevenLabs)",
            "자동 영상 편집 (MoviePy)",
        ],
        "creator_involvement": [
            "주제 선정 및 기획",
            "독창적 관점/분석 작성",
            "팩트체크 및 출처 확인",
            "편집 스타일 선택",
            "최종 품질 검수",
        ],
        "unique_angle": unique_angle,
        "edit_style": edit_style,
        "fact_sources": fact_sources,
        "template_used": script.get("template_used", ""),
        "output_path": output_path,
        "generated_at": datetime.now().isoformat(),
    }

    # 대본 저장 (수동 검토용)
    try:
        script_path = save_script_for_review(script, settings)
        metadata["script_review_path"] = script_path
    except Exception as e:
        logger.debug("대본 저장 실패 (무시): %s", e)

    # Save metadata
    ensure_dir(settings.logs_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    meta_path = f"{settings.logs_dir}/metadata_{timestamp}.json"
    write_json(meta_path, metadata)

    return metadata, meta_path


def print_metadata_summary(metadata: dict[str, Any]) -> None:
    """메타데이터 요약을 출력합니다.

    Args:
        metadata: 메타데이터 딕셔너리.
    """
    logger.info("제목: %s", metadata["title"])
    logger.info("태그: %s...", ", ".join(metadata["tags"][:5]))
    logger.info("해시태그: %s", " ".join(metadata["hashtags"][:5]))
    logger.info("AI 공시: %s", "포함" if metadata["ai_disclosure"] else "미포함")
    logger.info("독창적 관점: %s", metadata["unique_angle"])
    logger.info("출처: %d개", len(metadata["fact_sources"]))
    logger.info("템플릿: %s", metadata.get("template_used", ""))
