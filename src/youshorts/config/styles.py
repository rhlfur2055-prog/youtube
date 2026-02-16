"""편집 스타일 및 대본 스타일 정의."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptStyleConfig:
    """대본 스타일 설정."""

    tone: str
    structure: str
    personality: str


EDIT_STYLES: list[str] = [
    "dynamic",
    "cinematic",
    "infographic",
    "storytelling",
    "energetic",
]

SCRIPT_STYLES: list[str] = [
    "creative",
    "analytical",
    "emotional",
    "humorous",
    "expert",
    "community",
]

STYLE_TEMPLATES: dict[str, ScriptStyleConfig] = {
    "creative": ScriptStyleConfig(
        tone="독창적이고 신선한 관점, 비유와 유머 활용",
        structure="기승전결에 반전 2개 이상",
        personality="호기심 많은 탐험가 스타일",
    ),
    "analytical": ScriptStyleConfig(
        tone="논리적이고 데이터 중심, 깊이 있는 분석",
        structure="문제-분석-해결-인사이트",
        personality="냉철한 분석가 스타일",
    ),
    "emotional": ScriptStyleConfig(
        tone="공감과 감동, 스토리텔링 중심",
        structure="공감-전개-클라이맥스-교훈",
        personality="따뜻한 멘토 스타일",
    ),
    "humorous": ScriptStyleConfig(
        tone="위트와 유머, 재미있는 비유",
        structure="농담-반전-핵심-웃긴마무리",
        personality="개그맨 지식인 스타일",
    ),
    "expert": ScriptStyleConfig(
        tone="전문적이고 신뢰감 있는 어조",
        structure="주장-근거-사례-결론",
        personality="해당 분야 10년차 전문가 스타일",
    ),
    "community": ScriptStyleConfig(
        tone="실제 경험담을 전하는 생생한 구어체, 감탄사와 공감 유도",
        structure="떡밥-전개-반전-후일담",
        personality="커뮤니티 레전드 썰 전문 나레이터",
    ),
}

UNIQUE_ANGLES: list[str] = [
    "역사적 관점에서 바라본",
    "심리학적으로 분석한",
    "경제학 원리로 설명하는",
    "외국인이 보면 놀라는",
    "과학적으로 증명된",
    "뇌과학이 밝혀낸",
    "통계로 증명하는",
    "전문가들만 아는",
    "10년 후 후회할",
    "데이터가 말해주는",
]

STORYTELLING_HOOKS: list[str] = [
    "개인 경험담으로 시작",
    "충격적인 통계로 시작",
    "반전 질문으로 시작",
    "비유/은유로 시작",
    "최근 뉴스 연결로 시작",
    "일상 속 관찰로 시작",
]

COMMUNITY_HOOKS: list[str] = [
    "실화임. 소름 주의.",
    "이거 레전드인데 아직도 모르는 사람 많음.",
    "방금 본 글인데 소름 돋았음.",
    "이건 진짜 들으면 잠이 안 옴.",
    "커뮤니티에서 난리난 글 가져왔음.",
    "이 썰 듣고 경악한 사람 나만 아니지?",
    "아직도 이걸 모르는 사람이 있다고?",
    "글 읽다가 소름 돋아서 가져옴.",
]
