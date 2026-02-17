# 변경 사유: 시스템 프롬프트 전체 교체 + 실시간 트렌드 크롤링 + AI 슬롭 방지
"""LLM 기반 대본 생성 모듈.

Gemini 2.0 Flash (1순위) → OpenAI GPT-4o-mini (2순위) → Claude (3순위) 폴백 체인으로
유튜브 수익창출 정책을 준수하는 독창적 스토리텔링 기반
YouTube Shorts 대본을 생성합니다.

주요 기능:
- 실시간 트렌드 크롤링 (Apify → 네이버/구글/트위터)
- 폴백 주제 풀 (TRENDING_TOPICS)
- 주제 중복 방지 (data/history.json)
- 대본 템플릿 5종 랜덤 (AI 슬롭 방지)
- 하루 최대 3개 생산 제한
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, date
from typing import Any

from youshorts.config.settings import Settings, get_settings
from youshorts.config.styles import (
    COMMUNITY_HOOKS,
    STORYTELLING_HOOKS,
    STYLE_TEMPLATES,
    UNIQUE_ANGLES,
)
from youshorts.security.secrets_manager import SecretsManager
from youshorts.utils.logger import get_logger
from youshorts.utils.retry import retry

logger = get_logger(__name__)

# ============================================================
# 폴백 주제 풀 (트렌드 크롤링 실패 시 사용, 매주 수동 업데이트)
# ============================================================
# 레퍼런스 채널급 폴백 주제풀 (커뮤 썰 스타일 - 조회수 검증된 패턴)
TRENDING_TOPICS: list[dict[str, str]] = [
    {"title": "배달 초밥 10개 역대급 논란ㄷㄷ", "body": "배달앱으로 초밥 10개 시켰는데 도착해서 열어보니까 밥이 반은 뭉개져있고 생선은 말라비틀어져 있음. 사진 찍어서 리뷰 올렸더니 사장이 답글 달았는데 내용이 레전드. 너같은 손님 때문에 장사 못한다고. 다른 리뷰 보니까 나만 그런 게 아니었음. 별점 1점이 80%넘음. 근데 아직도 영업중이라 소름.", "source": "폴백"},
    {"title": "편의점 진상이 라면 끓이다 벌인 일ㅋㅋ", "body": "편의점 야간 알바 중인데 새벽 3시에 아저씨가 라면 3개를 한번에 끓이겠다고 함. 냄비가 하나라 안된다고 했더니 빡쳐서 컵라면 용기에 끓이기 시작. 물이 넘쳐서 전자레인지 고장남. 수리비 청구했더니 도망감. CCTV 확인하니까 매주 오는 상습범이었음. 경찰 신고해서 결국 잡음.", "source": "폴백"},
    {"title": "치킨 리뷰 별점 1점 단 손님 결말ㄷㄷ", "body": "치킨집 운영하는데 매일 주문하면서 매번 별점 1점 테러하는 놈이 있었음. 리뷰 내용도 매번 같음. 맛없다 양적다 느리다. 이상해서 주소 확인해보니까 200m 거리 경쟁 치킨집 사장이었음. 증거 모아서 공정위에 신고했더니 과태료 500만원 나옴. 그 치킨집 결국 폐업함.", "source": "폴백"},
    {"title": "알바생이 사장한테 문자 잘못 보낸 썰ㅋㅋ", "body": "편의점 알바하는데 친구한테 보낼 카톡을 사장한테 보냄. 내용이 사장 욕이었음. 오늘도 그 꼰대가 어쩌고. 보내고 5초만에 알아챔. 심장 멈추는 줄. 바로 전화했더니 사장이 웃으면서 나도 내 사장한테 그랬다고. 다음날 출근하니까 사장이 편의점 과자 하나 사줌. 의외로 쿨한 사장.", "source": "폴백"},
    {"title": "배달 리뷰 1000개 단 사람 정체ㄷㄷ", "body": "배달앱에서 리뷰 1200개 넘게 단 계정 발견. 프로필 들어가보니까 하루에 3끼 전부 배달 시켜먹음. 직업이 재택 프로그래머라 밖에 안 나간다고. 1년 배달비만 300만원 넘게 씀. 근데 리뷰마다 사진이랑 별점이 진짜 꼼꼼해서 그 동네에서 맛집 가이드로 유명해짐.", "source": "폴백"},
    {"title": "PC방 손님이 자리에 남기고 간 것ㅋㅋ", "body": "PC방 청소하다가 구석자리에서 봉투 발견. 열어보니까 현금 200만원이 들어있었음. CCTV 확인해서 손님한테 연락했더니 이사비용이었는데 술먹고 잊어버린거. 돌려주니까 고맙다고 치킨 10마리 보내줌. 사장이 그중에 5마리 알바한테 나눠줌.", "source": "폴백"},
    {"title": "택시 기사가 손님 거부하는 진짜 이유ㄷㄷ", "body": "택시 10년차 기사가 올린 글. 절대 안 태우는 손님 특징 3가지. 첫번째 음식 들고 타는 사람. 국물 엎으면 청소비 10만원인데 안 냄. 두번째 술 냄새 심한 사람. 차 안에서 토하면 하루 영업 끝남. 세번째 짧은 거리인데 카드 결제하면서 빨리 가라는 사람. 기본요금도 안 나오는데 재촉까지.", "source": "폴백"},
    {"title": "마트 폐점 30분 전에 가면 생기는 일ㅋㅋ", "body": "이마트 폐점 30분 전에 가면 할인 스티커 붙이는 직원 뒤를 아줌마 10명이 따라다님. 직원이 스티커 붙이는 순간 손이 5개가 동시에 들어옴. 어떤 아줌마는 직원한테 저거 먼저 붙여달라고 부탁까지 함. 한번은 치킨 할인 붙이자마자 아줌마 두 명이 동시에 잡아서 치킨이 찢어짐.", "source": "폴백"},
    {"title": "중고거래 사기꾼한테 역관광 시킨 썰ㄷㄷ", "body": "당근마켓에서 에어팟 프로 8만원에 올라온거 봄. 택배거래 하자고 해서 수상해서 직거래 요청. 만나서 확인하니까 짝퉁임. 바로 경찰 부름. 알고보니 같은 수법으로 20명한테 사기친 상습범이었음. 피해자 단톡방 만들어서 같이 고소함. 합의금으로 1인당 50만원 받음.", "source": "폴백"},
    {"title": "식당 CCTV에 찍힌 사장 행동 소름ㄷㄷ", "body": "단골 식당인데 좀 이상해서 CCTV 영상 요청함. 사장이 매번 음식 나가기 전에 국물을 맛보는데 쓰던 숟가락 그대로 다시 넣음. 한두번이 아니라 매번 그럼. 보건소 신고했더니 영업정지 나옴. 사장이 항의하길래 CCTV 보여줬더니 할 말 없어함.", "source": "폴백"},
    {"title": "쿠팡맨이 배달 중 목격한 장면ㄷㄷ", "body": "새벽배송 하는데 아파트 복도에 할머니가 쓰러져 있었음. 119 부르고 응급처치 했더니 저혈당 쇼크였음. 병원 가서 괜찮아졌는데 할머니 가족이 고맙다고 사례금 100만원 주겠다고 함. 거절했더니 쿠팡 고객센터에 칭찬 글 올림. 쿠팡에서 포상금 50만원 줌.", "source": "폴백"},
    {"title": "고깃집 2인분 시켰는데 나온 양 실화ㅋㅋ", "body": "삼겹살 2인분 시켰는데 접시에 고기가 4점 나옴. 1인분에 고기 2점. 항의했더니 사장이 원래 이 양이라고. 저울로 재보니까 120g도 안됨. 1인분 기준 200g인데. 리뷰에 사진 올렸더니 사장이 영업방해로 고소하겠다고 협박. 근데 다른 손님들도 같은 리뷰 올려서 결국 폐업.", "source": "폴백"},
]


def _is_valid_trend_topic(keyword: str) -> bool:
    """트렌드 키워드가 콘텐츠로 만들 가치가 있는지 검증합니다.

    단순 인물명, 의미 없는 단어, 브랜드명 등을 걸러냅니다.

    Args:
        keyword: 트렌드 키워드.

    Returns:
        콘텐츠 가치가 있으면 True.
    """
    kw = keyword.strip()

    # 1. 길이 체크 (너무 짧으면 대부분 인물명)
    if len(kw) < 4:
        logger.debug("트렌드 필터: '%s' → 너무 짧음 (인명 가능성)", kw)
        return False

    # 2. 순수 인명 패턴 감지 (2~3글자 한글만)
    import re
    if re.fullmatch(r"[가-힣]{2,3}", kw):
        logger.debug("트렌드 필터: '%s' → 인명 패턴", kw)
        return False

    # 3. "이름 + 단순 단어" 패턴 (예: "레이 탈퇴", "장동혁 사건")
    parts = kw.split()
    if len(parts) == 2 and re.fullmatch(r"[가-힣]{2,4}", parts[0]):
        logger.debug("트렌드 필터: '%s' → 인명+단어 패턴", kw)
        return False

    # 4. 콘텐츠성 키워드 포함 여부 (최소 하나는 있어야)
    content_markers = [
        "현실", "근황", "레전드", "후기", "사건", "실화", "비밀",
        "방법", "꿀팁", "이유", "차이", "비교", "논란", "충격",
        "가격", "순위", "모음", "유형", "특징", "vs", "반응",
        "법", "제도", "정책", "문제", "위기", "전쟁", "사고",
        "먹방", "리뷰", "추천", "역사", "문화", "과학", "건강",
        "투자", "주식", "부동산", "창업", "알바", "취업",
        "학교", "군대", "결혼", "이혼", "연애", "육아",
        "맛집", "여행", "호텔", "항공", "택시", "버스",
        "아파트", "전세", "월세", "대출", "보험", "세금",
    ]

    # 5글자 이상이면서 콘텐츠 마커 없어도 통과 (문장형 키워드)
    if len(kw) >= 8:
        return True

    # 짧은 키워드는 콘텐츠 마커가 있어야 통과
    has_marker = any(m in kw for m in content_markers)
    if not has_marker:
        logger.debug("트렌드 필터: '%s' → 콘텐츠성 키워드 없음", kw)
        return False

    return True

# ============================================================
# 클릭 유발 제목 패턴
# ============================================================
_TITLE_PATTERNS: list[str] = [
    "{topic}하면 어떻게 될까?",
    "{topic}의 현실",
    "{topic} 레전드",
    "이거 나만 몰랐어? {topic}",
    "[충격] {topic}의 진실",
    "{topic}하면 생기는 일",
    "한국에서만 가능한 {topic}",
    "{topic} 근황 ㄷㄷ",
    "{topic} 실화냐?",
    "{topic} 알고나면 소름",
]

# ============================================================
# 대본 템플릿 5종 (AI 슬롭 방지 - 매번 다른 구조)
# ============================================================
_SCRIPT_TEMPLATES: list[dict[str, str]] = [
    {
        "name": "충격_반전형",
        "structure": "충격 오프닝 → 배경 설명 → 반전 1 → 반전 2 → 댓글 유도",
        "hook_style": "가장 충격적인 결과부터 던지기",
        "tone": "소름돋는 분위기, 긴장감 유지",
    },
    {
        "name": "공감_분노형",
        "structure": "빡치는 상황 제시 → 디테일 추가 → 해결/못한 결말 → 시청자 분노 유도",
        "hook_style": "\"이거 ㄹㅇ 미쳤다\" 스타일 오프닝",
        "tone": "분노 공감, 시청자가 같이 빡치게",
    },
    {
        "name": "스토리텔링형",
        "structure": "인물 소개 → 사건 발생 → 전개 → 반전 → 후일담",
        "hook_style": "등장인물의 행동으로 시작",
        "tone": "몰입감 있는 이야기체, 구체적 묘사",
    },
    {
        "name": "정보_폭탄형",
        "structure": "미끼 질문 → 핵심 정보 3개 연타 → 가장 충격적인 사실 → CTA",
        "hook_style": "\"이거 모르면 손해\" 스타일 오프닝",
        "tone": "빠른 호흡, 팩트 연타, 숫자 강조",
    },
    {
        "name": "비교_대결형",
        "structure": "A vs B 제시 → A 설명 → B 설명 → 의외의 결과 → 시청자 선택 유도",
        "hook_style": "\"A vs B 뭐가 이길까?\" 질문",
        "tone": "대결 구도, 호기심 자극, 의외성",
    },
]

# ============================================================
# 한국어 주제 → 영어 Pexels 검색 키워드 매핑
# ============================================================
_TOPIC_KEYWORD_MAP: dict[str, list[str]] = {
    # ── 일상/생활 ──
    "생활": ["daily life tips", "home organization", "kitchen cooking", "household cleaning"],
    "꿀팁": ["life hack tips", "smart home ideas", "saving money", "productivity tips"],
    "일상": ["daily routine morning", "cozy home interior", "person relaxing sofa", "city street walking"],
    # ── 건강/운동 ──
    "건강": ["healthy lifestyle", "exercise workout", "nutritious food", "wellness routine"],
    "운동": ["gym workout fitness", "running jogging outdoor", "yoga stretching", "home exercise"],
    "수면": ["sleeping peacefully", "bedroom cozy night", "morning alarm wake up", "relaxation meditation"],
    "다이어트": ["healthy salad meal", "weight scale fitness", "jogging park morning", "smoothie preparation"],
    # ── 재무/경제 ──
    "돈": ["saving money piggy bank", "finance budget planning", "shopping smart", "investment growth"],
    "경제": ["stock market chart", "business meeting office", "economy finance coins", "calculator budget"],
    "투자": ["stock trading screen", "real estate building", "gold bars investment", "cryptocurrency chart"],
    "절약": ["piggy bank savings", "discount shopping mall", "budget notebook pen", "coins stacking"],
    "자영업": ["small business owner", "restaurant kitchen busy", "cash register store", "market vendor stall"],
    "알바": ["part time job cafe", "convenience store worker", "delivery driver scooter", "student working"],
    # ── 음식/요리 ──
    "음식": ["cooking kitchen food", "healthy meal prep", "restaurant dining", "grocery shopping"],
    "요리": ["chef cooking kitchen", "food preparation close-up", "recipe ingredients table", "delicious meal plate"],
    "맛집": ["restaurant food plating", "street food market", "cafe coffee latte", "fine dining table"],
    "배달": ["food delivery rider", "takeout packaging", "phone ordering app", "doorbell package delivery"],
    # ── 교육/학습 ──
    "공부": ["studying desk books", "student classroom", "reading library", "online learning"],
    "교육": ["teacher classroom board", "student studying hard", "university campus", "exam preparation"],
    "면접": ["job interview office", "handshake business", "resume document", "nervous person waiting"],
    # ── 여행 ──
    "여행": ["travel suitcase packing", "airplane airport", "tourist sightseeing", "hotel vacation"],
    "해외": ["international airport terminal", "passport stamps travel", "landmark tourist spot", "beach resort vacation"],
    # ── 패션/뷰티 ──
    "패션": ["fashion outfit style", "clothing wardrobe", "shopping mall store", "accessories jewelry"],
    "뷰티": ["skincare routine face", "makeup cosmetics mirror", "beauty salon treatment", "fashion model portrait"],
    # ── 관계/심리 ──
    "심리": ["person thinking deeply", "emotional face close-up", "brain illustration concept", "therapy session calm"],
    "관계": ["couple holding hands", "friends laughing together", "family dinner table", "lonely person window"],
    "사랑": ["romantic couple sunset", "heart shape gesture", "love letter handwriting", "wedding ceremony"],
    "소개팅": ["couple first meeting cafe", "nervous date dinner", "phone text message", "awkward conversation"],
    "자취": ["small apartment room", "cooking alone kitchen", "lonely dinner table", "empty room person"],
    # ── 미스터리/공포 ──
    "미스터리": ["dark mysterious corridor", "detective magnifying glass", "old mysterious book", "foggy forest path"],
    "공포": ["dark scary hallway", "horror atmosphere night", "abandoned building dark", "shadowy figure silhouette"],
    "소름": ["person shocked face", "goosebumps close-up arm", "dark empty room", "eerie moonlight night"],
    "CCTV": ["security camera footage", "surveillance monitor screen", "night vision camera", "dark alley camera"],
    # ── 과학/기술 ──
    "과학": ["science laboratory experiment", "space stars galaxy", "DNA molecule close-up", "technology circuit board"],
    "기술": ["futuristic technology screen", "robot artificial intelligence", "coding computer screen", "smartphone innovation"],
    "우주": ["space galaxy stars nebula", "astronaut space station", "moon surface landscape", "earth from space"],
    # ── 역사 ──
    "역사": ["ancient ruins architecture", "old historical painting", "vintage photograph sepia", "castle medieval fortress"],
    # ── 동물 ──
    "동물": ["cute animal puppy kitten", "wildlife nature safari", "ocean marine life", "bird flying sky"],
    # ── 사건/사고 ──
    "사건": ["police investigation scene", "courtroom justice gavel", "newspaper headline breaking", "detective evidence board"],
    "충격": ["person shocked surprised face", "dramatic lightning storm", "explosion fire flames", "breaking news screen"],
    "사기": ["scam warning sign", "handcuffs arrest", "fake document", "worried person phone"],
    # ── 법률 ──
    "법": ["courtroom judge gavel", "law books library", "justice scale balance", "contract document signing"],
    "법률": ["courtroom judge gavel", "law books library", "justice scale balance", "contract document signing"],
    # ── 직장/비즈니스 ──
    "회사": ["office workplace desk", "business meeting conference", "coworker teamwork discussion", "corporate building exterior"],
    "직장": ["office worker computer", "boss employee meeting", "workplace stress tired", "career promotion success"],
    "퇴사": ["person leaving office", "packing desk belongings", "resignation letter", "freedom celebration outdoors"],
    "공무원": ["government office building", "official document stamp", "public service desk", "civil servant working"],
    "군대": ["military training soldiers", "army barracks", "camouflage uniform", "salute formation"],
    # ── 부동산 ──
    "집값": ["apartment building exterior", "real estate sign sale", "house key handover", "mortgage document calculator"],
    "전세": ["apartment empty room", "contract signing pen", "moving boxes", "worried couple documents"],
    # ── 외국인 반응 ──
    "외국인": ["foreigner tourist korea", "cultural shock reaction", "trying korean food", "subway crowded seoul"],
    # ── 트렌드/이슈 ──
    "트렌드": ["social media phone scroll", "trending fashion style", "viral content creation", "modern lifestyle urban"],
    "이슈": ["debate discussion argument", "protest crowd rally", "news broadcast studio", "social issue awareness"],
    "당근마켓": ["used items marketplace", "second hand trade", "phone chat negotiation", "meeting for trade"],
    "중고나라": ["used items marketplace", "online shopping phone", "package shipping box", "scam warning"],
    # ── 통계/수치 ──
    "통계": ["data chart infographic", "statistics graph analysis", "survey research data", "percentage pie chart"],
    "상식": ["question mark curiosity", "lightbulb idea concept", "book knowledge wisdom", "trivia quiz show"],
    "출산율": ["baby nursery room", "empty playground", "hospital maternity ward", "declining graph chart"],
}


def _generate_topic_keywords(topic: str) -> list[str]:
    """주제에서 관련 영어 검색 키워드를 추출합니다 (폴백용).

    Args:
        topic: 한국어 주제 문자열.

    Returns:
        영어 검색 키워드 리스트.
    """
    for kr_key, en_keywords in _TOPIC_KEYWORD_MAP.items():
        if kr_key in topic:
            return en_keywords
    return ["lifestyle daily routine", "home living room", "people working", "modern city life"]


# ============================================================
# 실시간 트렌드 크롤링 (Apify API)
# ============================================================

def fetch_trending_topics(settings: Settings | None = None) -> list[str]:
    """실시간 트렌드 키워드를 크롤링합니다 (무료 직접 HTTP).

    1순위: Google Trends RSS (무료, API 키 불필요)
    2순위: 네이버 시그널 API (무료, API 키 불필요)

    Args:
        settings: 설정 인스턴스.

    Returns:
        트렌드 키워드 리스트 (최대 20개). 실패 시 빈 리스트.
    """
    if settings is None:
        settings = get_settings()

    topics: list[str] = []

    # 1. Google Trends RSS (무료, 가장 안정적)
    try:
        google_topics = _fetch_google_trends_rss()
        topics.extend(google_topics)
        logger.info("구글 트렌드 RSS %d개 수집", len(google_topics))
    except Exception as e:
        logger.debug("구글 트렌드 RSS 실패: %s", e)

    # 2. 네이버 시그널 (무료)
    try:
        naver_topics = _fetch_naver_signal()
        topics.extend(naver_topics)
        logger.info("네이버 시그널 %d개 수집", len(naver_topics))
    except Exception as e:
        logger.debug("네이버 시그널 실패: %s", e)

    # 중복 제거
    seen = set()
    unique: list[str] = []
    for t in topics:
        t_clean = t.strip()
        if t_clean and t_clean not in seen and len(t_clean) >= 2:
            seen.add(t_clean)
            unique.append(t_clean)

    logger.info("총 트렌드 키워드 %d개 수집 완료", len(unique))
    return unique[:20]


def _fetch_google_trends_rss() -> list[str]:
    """Google Trends 한국 실시간 인기 검색어 RSS를 크롤링합니다.

    무료, API 키 불필요. Google 공식 RSS 피드 사용.
    """
    import requests
    import xml.etree.ElementTree as ET

    url = "https://trends.google.co.kr/trending/rss?geo=KR"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    topics: list[str] = []

    # RSS XML 파싱
    root = ET.fromstring(resp.content)

    # RSS 2.0: channel > item > title
    for item in root.findall(".//item"):
        title_el = item.find("title")
        if title_el is not None and title_el.text:
            keyword = title_el.text.strip()
            # 불필요한 접두사/접미사 제거
            keyword = keyword.replace("&amp;", "&")
            if keyword and len(keyword) >= 2:
                topics.append(keyword)

    # Atom 네임스페이스도 시도
    if not topics:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            if title_el is not None and title_el.text:
                keyword = title_el.text.strip()
                if keyword and len(keyword) >= 2:
                    topics.append(keyword)

    return topics[:10]


def _fetch_naver_signal() -> list[str]:
    """네이버 시그널 API로 급상승 검색어를 크롤링합니다.

    무료, API 키 불필요. 네이버 내부 JSON API 사용.
    """
    import requests

    # 네이버 급상승 검색어 JSON API
    url = "https://apis.naver.com/mobile-search/trending-search/trending-search"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://m.naver.com/",
        "Accept": "application/json",
    }
    params = {
        "page": "1",
        "display": "20",
    }

    resp = requests.get(url, headers=headers, params=params, timeout=10)

    topics: list[str] = []

    if resp.status_code == 200:
        try:
            data = resp.json()
            # 응답 구조: {"result": {"itemList": [{"title": "키워드"}, ...]}}
            items = (
                data.get("result", {}).get("itemList", [])
                or data.get("data", {}).get("itemList", [])
                or data.get("items", [])
            )
            for item in items:
                keyword = (
                    item.get("title", "")
                    or item.get("keyword", "")
                    or item.get("query", "")
                )
                keyword = keyword.strip()
                if keyword and len(keyword) >= 2:
                    topics.append(keyword)
        except (ValueError, KeyError):
            pass

    # 폴백: 네이버 DataLab 급상승 페이지 HTML 파싱
    if not topics:
        topics = _fetch_naver_datalab_html()

    return topics[:10]


def _fetch_naver_datalab_html() -> list[str]:
    """네이버 DataLab 급상승 검색어를 HTML에서 직접 파싱합니다."""
    import requests
    import re

    url = "https://datalab.naver.com/keyword/realtimeList.naver"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        return []

    topics: list[str] = []

    # <span class="item_title"> 또는 유사한 패턴에서 추출
    patterns = [
        r'<span[^>]*class="item_title"[^>]*>([^<]+)</span>',
        r'"keyword"\s*:\s*"([^"]+)"',
        r'"title"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, resp.text)
        if matches:
            for m in matches:
                keyword = m.strip()
                if keyword and len(keyword) >= 2 and len(keyword) <= 30:
                    topics.append(keyword)
            break

    return topics[:10]


# ============================================================
# 주제 선정 로직 (트렌드 → 폴백 → 수동 지정)
# ============================================================

def _load_topic_history(settings: Settings) -> list[str]:
    """data/history.json에서 이전 사용 주제를 로드합니다."""
    from youshorts.utils.file_handler import read_json

    history_path = settings.history_file
    if not os.path.exists(history_path):
        return []

    try:
        data = read_json(history_path)
        if isinstance(data, list):
            return [
                item.get("topic", "") or item.get("title", "")
                for item in data
                if isinstance(item, dict)
            ]
        return []
    except Exception:
        return []


def _get_today_production_count(settings: Settings) -> int:
    """오늘 생산된 영상 개수를 확인합니다 (AI 슬롭 방지)."""
    from youshorts.utils.file_handler import read_json

    history_path = settings.history_file
    if not os.path.exists(history_path):
        return 0

    try:
        data = read_json(history_path)
        if not isinstance(data, list):
            return 0

        today_str = date.today().isoformat()
        count = 0
        for item in data:
            if isinstance(item, dict):
                created = item.get("created_at", "") or item.get("generated_at", "")
                if created.startswith(today_str):
                    count += 1
        return count
    except Exception:
        return 0


def check_daily_limit(settings: Settings | None = None, max_per_day: int = 3) -> bool:
    """하루 최대 생산 제한을 확인합니다.

    Args:
        settings: 설정 인스턴스.
        max_per_day: 하루 최대 생산 개수 (기본 3).

    Returns:
        생산 가능 여부.
    """
    if settings is None:
        settings = get_settings()

    count = _get_today_production_count(settings)
    if count >= max_per_day:
        logger.warning(
            "하루 최대 생산 제한 도달 (%d/%d) - AI 슬롭 방지",
            count, max_per_day,
        )
        return False
    logger.info("오늘 생산량: %d/%d", count, max_per_day)
    return True


def select_topic(
    topic_override: str | None = None,
    style: str = "creative",
    settings: Settings | None = None,
) -> dict[str, str]:
    """주제를 자동 선정합니다.

    1순위: 커뮤니티 실시간 인기글 크롤링 (CommunityCrawler)
    2순위: 정적 TRENDING_TOPICS 폴백

    Args:
        topic_override: 사용자 지정 주제.
        style: 대본 스타일.
        settings: 설정 인스턴스.

    Returns:
        {"title": str, "body": str, "source": str} 딕셔너리.
    """
    if settings is None:
        settings = get_settings()

    # 1순위: 사용자 직접 지정
    if topic_override:
        logger.info("사용자 지정 주제: %s", topic_override)
        return {"title": topic_override, "body": "", "source": "manual"}

    # 이전 사용 주제 로드 (중복 방지)
    used_topics = set(_load_topic_history(settings))

    # 2순위: 커뮤니티 실시간 인기글 크롤링
    try:
        from youshorts.core.community_crawler import CommunityCrawler
        crawler = CommunityCrawler()
        posts = crawler.pick_best(count=3)
        # 15점 이상 주제가 0개면 즉시 폴백 사용
        if not posts or len(posts) == 0:
            logger.warning("크롤링 주제 품질 미달 (15점 이상 0개) → 폴백 주제 사용")
            available = [t for t in TRENDING_TOPICS if t["title"] not in used_topics]
            if not available:
                available = TRENDING_TOPICS.copy()
            selected = random.choice(available)
            logger.info("폴백 주제 선정: %s", selected["title"])
            return selected
        if posts:
            for post in posts:
                if post["title"] not in used_topics:
                    logger.info(
                        "커뮤니티 인기글 선정: '%s' (소스: %s, 점수: %s)",
                        post["title"][:30],
                        post.get("source", "?"),
                        post.get("score", "?"),
                    )
                    return {
                        "title": post["title"],
                        "body": post.get("body", ""),
                        "source": post.get("source", "community"),
                    }
            # 모두 중복이면 1등 강제 사용
            best = posts[0]
            logger.info("커뮤니티 인기글 (중복 허용): '%s'", best["title"][:30])
            return {
                "title": best["title"],
                "body": best.get("body", ""),
                "source": best.get("source", "community"),
            }
    except Exception as e:
        logger.warning("커뮤니티 크롤링 실패: %s - 폴백 주제 사용", e)

    # [비활성화] Google Trends 크롤링 - community_crawler.py에서 통합 관리
    # try:
    #     trend_topics = fetch_trending_topics(settings)
    #     ...
    # except Exception as e:
    #     logger.debug("트렌드 크롤링 실패: %s", e)

    # 3순위: TRENDING_TOPICS 폴백
    available = [t for t in TRENDING_TOPICS if t["title"] not in used_topics]
    if not available:
        available = TRENDING_TOPICS.copy()

    selected = random.choice(available)
    logger.info("폴백 주제 선정: %s", selected["title"])
    return selected


def _make_clickbait_title(keyword: str) -> str:
    """트렌드 키워드를 클릭 유발 제목으로 변환합니다.

    Args:
        keyword: 원본 트렌드 키워드.

    Returns:
        클릭 유발 형태의 제목.
    """
    pattern = random.choice(_TITLE_PATTERNS)
    return pattern.format(topic=keyword)


# ============================================================
# 시스템 프롬프트 (전체 교체)
# ============================================================

# 랜덤 영상 길이 (45~90초 사이, AI 슬롭 방지)
def _get_random_duration() -> tuple[int, int]:
    """랜덤 영상 길이를 생성합니다 (45~90초).

    Returns:
        (최소 글자수, 최대 글자수) 튜플.
    """
    duration = random.randint(45, 90)
    # 대략 1초 = 5~6자 (한국어 TTS 기준)
    min_chars = int(duration * 5)
    max_chars = int(duration * 7)
    return min_chars, max_chars


def _build_prompt(topic: str, angle: str, hook_style: str, style: str) -> str:
    """LLM에 전달할 프롬프트를 구성합니다.

    대본 템플릿 5종 중 랜덤 선택하여 AI 슬롭을 방지합니다.

    Args:
        topic: 영상 주제.
        angle: 독창적 관점.
        hook_style: 시작 방식.
        style: 대본 스타일.

    Returns:
        완성된 프롬프트 문자열.
    """
    style_config = STYLE_TEMPLATES.get(style, STYLE_TEMPLATES["creative"])
    template = random.choice(_SCRIPT_TEMPLATES)
    min_chars, max_chars = _get_random_duration()

    return f"""너는 한국 유튜브 쇼츠 대본 작가야.
커뮤니티(에펨코리아, 디시인사이드, 블라인드) 스타일의 재미있는 이야기를 만들어.

[대본 구조 - 반드시 이 순서대로]
1. 도입 (1~2문장): 감탄사로 시작. 시청자를 잡아끄는 한 줄.
2. 본문 (8~15문장): 이야기의 핵심. 대화체 섞어서.
3. 리액션 (1~2문장): 중간에 "ㅋㅋㅋ" 또는 "아 진짜" 등
4. 반전/결론 (2~3문장): 이야기의 핵심 포인트
5. 마무리 (1문장): 본인 의견 또는 질문

[말투 규칙 - 20대 남성 커뮤니티]
- 한 문장 최대 12자. 길면 쪼개.
- "~했는데", "~인 거야", "~한 거임" 체
- "ㅋㅋ", "ㄷㄷ", "ㄹㅇ", "진짜", "개~" 자연스럽게 섞기
- 대화가 나오면 "근데 걔가 뭐라 했냐면" 식으로

[절대 금지 - AI 슬롭 제거 (위반 시 대본 폐기됨)]
- **사람 이름 절대 금지. 한글 이름(최가온, 김서연, 박준호 등) 쓰면 대본 폐기됨** → 반드시 "걔", "그놈", "그 손님", "사장", "알바생", "배달기사" 등으로 대체
- "여러분" 절대 금지 → "야" 또는 아예 생략
- "선택은?", "어떻게 생각해?", "의견을 남겨주세요", "댓글로 알려줘" 같은 AI 마무리 절대 금지
- "경제학", "딜레마", "철학", "심리학", "사회학" 같은 학문 용어 절대 금지
- "마무리하며", "결론적으로", "요약하자면" 같은 AI 전환어 절대 금지
- "안녕하세요", "오늘은 ~에 대해" 금지
- "흥미로운", "놀라운", "살펴보겠습니다" 금지
- "정말 대단하지 않나요?" 금지
- 실존 인물 구체적 허위 사실 금지
- 숫자/통계 지어내기 금지

[필수 규칙]
- **첫 문장**: 반드시 "야", "아니", "실화임" 중 하나로 시작
- **마지막 문장**: 반드시 "ㄹㅇ 레전드ㅋㅋ" 또는 "이게 말이 됨?ㄷㄷ" 또는 "아직도 소름ㄷㄷ" 스타일로 끝내기
- **모든 문장은 최대 15자. 이 규칙을 어기면 대본이 폐기됨**

[대본 구조 - {template['name']}]
- 이번 대본 구조: {template['structure']}
- 훅 스타일: {template['hook_style']}
- 톤앤매너: {template['tone']}

[길이]
- {min_chars}~{max_chars}자. 350~500자 분량.
- 문장은 짧게 끊어서 (15자 이내)
- TTS로 읽으면 45~55초

주제: {topic}
독창적 관점: {angle}
시작 방식: {hook_style}
스타일: {style_config.tone}
구조: {style_config.structure}
퍼소나: {style_config.personality}

추가 작성 규칙:

1. 크리에이터 개인 의견 필수:
   - 단순 정보 나열이 아닌 자신만의 해석과 의견 필수
   - "근데 내 생각엔..." / "솔직히 이건..." 스타일

2. 감정 표현 태그 (TTS 감정 변화용):
   - emotion 필드에 anger/fun/surprise/neutral/sad/tension/relief/shock 사용
   - 감정이 연속 3번 이상 같으면 시청자 이탈

4. 배경 영상 검색 키워드 (매우 중요!!!):
   - background_keywords_en의 각 섹션에 구체적 영어 키워드 2개씩
   - "woman looking surprised at phone" 같은 구체적 장면 필수
   - "nature", "life" 같은 추상적 키워드 절대 금지

5. 자막 청크 (subtitle_chunks):
   - 대본 전체를 6-12글자 단위로 분할
   - 의미 단위로 끊기 (단어 중간에서 절대 끊지 않기)
   - 각 청크에 섹션, 감정 태그, scene_hint 포함

JSON만 출력:
{{
    "title": "15자 이내 호기심 자극 제목",
    "hook": "훅 파트 (2초, 감정태그 포함)",
    "content": "본론 파트 (28초, 핵심 내용 + 감정태그)",
    "creator_opinion": "크리에이터 개인 분석/의견 (10초)",
    "twist": "클라이맥스 파트 (15초, 반전 + 감정태그)",
    "conclusion": "마무리 (5초, 댓글 유도 + CTA)",
    "full_script": "전체 대본 (감정태그 포함, 자연스럽게 연결)",
    "keywords": ["강조할키워드1", "강조할키워드2", "강조할키워드3"],
    "search_keywords": ["영어키워드1", "영어키워드2", "영어키워드3", "영어키워드4"],
    "background_keywords_en": {{
        "hook": ["구체적 장면 키워드1", "구체적 장면 키워드2"],
        "content": ["구체적 장면 키워드1", "구체적 장면 키워드2"],
        "opinion": ["구체적 장면 키워드1", "구체적 장면 키워드2"],
        "twist": ["구체적 장면 키워드1", "구체적 장면 키워드2"],
        "conclusion": ["구체적 장면 키워드1", "구체적 장면 키워드2"]
    }},
    "section_backgrounds": {{
        "hook": "도입부 배경 영어검색어",
        "content": "본문 배경 영어검색어",
        "twist": "반전 배경 영어검색어",
        "conclusion": "결론 배경 영어검색어"
    }},
    "subtitle_chunks": [
        {{"text": "야 이거 실화냐", "section": "hook", "emotion": "surprise", "scene_hint": "충격 장면"}},
        {{"text": "미쳤다 ㅋㅋ", "section": "hook", "emotion": "fun", "scene_hint": "웃긴 상황"}}
    ],
    "youtube_titles": [
        "CTR 높은 제목 패턴 1",
        "CTR 높은 제목 패턴 2",
        "CTR 높은 제목 패턴 3"
    ],
    "thumbnail_text": "5글자임팩트",
    "description_draft": "영상 설명문 초안 (해시태그 포함)",
    "seo_tags": ["태그1", "태그2", "...15-20개"],
    "unique_angle": "이 영상만의 독창적 관점 한 줄 설명",
    "fact_sources": ["인용한 통계/사실의 출처1", "출처2"],
    "emotion_map": [
        {{"text": "문장1", "emotion": "놀람"}},
        {{"text": "문장2", "emotion": "강조"}}
    ],
    "hashtags": ["#쇼츠", "#shorts", "#한국", "#레전드", "#실화"],
    "template_used": "{template['name']}"
}}"""


def _build_community_prompt(
    topic: str, source_text: str, hook_style: str, style: str,
) -> str:
    """커뮤니티 썰 전문 프롬프트를 구성합니다.

    오프닝에 결말을 던지는 '역순 스토리텔링',
    감정 기반 연출 지시, 하이라이트 키워드를 포함합니다.

    Args:
        topic: 영상 주제 (또는 크롤링된 게시글 제목).
        source_text: 크롤링된 원본 텍스트.
        hook_style: 시작 방식 (COMMUNITY_HOOKS에서 선택).
        style: 대본 스타일.

    Returns:
        완성된 프롬프트 문자열.
    """
    style_config = STYLE_TEMPLATES.get(style, STYLE_TEMPLATES["community"])
    template = random.choice(_SCRIPT_TEMPLATES)
    min_chars, max_chars = _get_random_duration()

    source_section = ""
    if source_text:
        source_section = f"""
[원글 내용]
{source_text[:2000]}
"""

    return f"""너는 에펨코리아 인기글을 읽어주는 유튜브 쇼츠 나레이터야.

규칙:
1. 아래 [원글 내용]을 20대 남성 말투로 읽어주기만 해. 절대 새로 지어내지 마.
2. 원글에 없는 내용 추가 금지. 팩트만 전달.
3. 첫 문장: "야 이거 실화임" 또는 "아니 이게 말이 돼?" 중 하나로 시작
4. 마지막 문장: "ㄹㅇ 레전드ㅋㅋ" 또는 "소름돋음ㄷㄷ" 중 하나로 끝
5. 문장당 최대 15자. 짧게 끊어.
6. "여러분", 사람이름, "경제학", "딜레마", **볼드**, "마무리하며" 전부 금지
7. 원글 body의 핵심 사실을 80% 이상 포함해야 함
8. 전체 대본 200~350자

{source_section}
주제: {topic}
시작 방식: "{hook_style}"

[절대 금지 - 위반 시 대본 폐기]
- 사람 이름 (김서연, 박준호 등) → "걔", "그놈", "사장", "알바생"으로 대체
- "여러분", "선택은?", "어떻게 생각해?", "의견을 남겨주세요"
- "경제학", "딜레마", "철학", "마무리하며", "결론적으로"
- "안녕하세요", "오늘은", "흥미로운", "살펴보겠습니다"
- **볼드**, 숫자/통계 지어내기

[말투]
- "~했는데", "~인 거야", "~한 거임" 체
- "ㅋㅋ", "ㄷㄷ", "ㄹㅇ", "진짜", "개~" 자연스럽게

[감정 태그]
- 모든 문장에 emotion 필수: anger/fun/surprise/neutral/sad/tension/relief/shock
- 감정 연속 3회 금지

[시각 강조]
- 모든 문장에 highlight (핵심 단어 1개) + scene_hint 필수

## 출력 형식 (JSON)

script 배열의 각 요소가 하나의 자막/TTS 단위이다.
emotion은 반드시 anger/fun/surprise/neutral/sad/tension/relief/shock 중 하나.

JSON만 출력:
{{
    "title": "15자 이내 어그로 제목",
    "bg_theme": "horror/funny/touching/shocking/mystery 중 택1",
    "script": [
        {{"text": "야 오늘 회사 뒤집어짐 ㅋㅋ", "emotion": "fun", "highlight": "뒤집어짐", "pause_ms": 0, "scene_hint": "회사 사무실"}},
        {{"text": "꼰대 부장이 나한테 커피를 뿌림.", "emotion": "anger", "highlight": "커피", "pause_ms": 0, "scene_hint": "커피잔 엎어짐"}},
        {{"text": "근데 여기서 반전.", "emotion": "surprise", "highlight": "반전", "pause_ms": 700, "scene_hint": "반전 분위기"}}
    ],
    "keywords": ["강조키워드1", "강조키워드2", "강조키워드3"],
    "search_keywords": ["영어키워드1", "영어키워드2", "영어키워드3", "영어키워드4"],
    "background_keywords_en": {{
        "hook": ["구체적 장면1", "구체적 장면2"],
        "content": ["구체적 장면1", "구체적 장면2"],
        "opinion": ["구체적 장면1", "구체적 장면2"],
        "twist": ["구체적 장면1", "구체적 장면2"],
        "conclusion": ["구체적 장면1", "구체적 장면2"]
    }},
    "section_backgrounds": {{
        "hook": "도입 배경 영어검색어",
        "content": "전개 배경 영어검색어",
        "twist": "반전 배경 영어검색어",
        "conclusion": "결말 배경 영어검색어"
    }},
    "youtube_titles": [
        "CTR 높은 어그로 제목 1",
        "CTR 높은 어그로 제목 2",
        "CTR 높은 어그로 제목 3"
    ],
    "thumbnail_text": "5글자임팩트",
    "description_draft": "영상 설명문 (해시태그 포함)",
    "seo_tags": ["태그1", "태그2", "...15-20개"],
    "unique_angle": "이 썰만의 핵심 포인트",
    "fact_sources": ["원본 출처"],
    "hashtags": ["#쇼츠", "#shorts", "#한국", "#레전드", "#실화"],
    "template_used": "{template['name']}"
}}

script 배열은 반드시 15-25개 요소를 가져야 한다. 너무 적으면 영상이 빈다."""


def _parse_script_response(text: str) -> dict[str, Any]:
    """LLM API 응답에서 JSON을 추출합니다.

    잘린 JSON도 복구를 시도합니다.

    Args:
        text: API 응답 텍스트.

    Returns:
        파싱된 대본 딕셔너리.
    """
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 잘린 JSON 복구 시도: 닫히지 않은 괄호를 닫아줌
        last_comma = text.rfind(",")
        if last_comma > 0:
            truncated = text[:last_comma]
            open_braces = truncated.count("{") - truncated.count("}")
            open_brackets = truncated.count("[") - truncated.count("]")
            truncated += "]" * max(0, open_brackets)
            truncated += "}" * max(0, open_braces)
            try:
                return json.loads(truncated)
            except json.JSONDecodeError:
                pass

        # 최후 수단: { 부터 마지막 } 까지 추출
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            try:
                return json.loads(text[first_brace:last_brace + 1])
            except json.JSONDecodeError:
                pass

        raise


def _apply_defaults(script: dict[str, Any], topic: str) -> dict[str, Any]:
    """누락된 필드에 기본값을 적용합니다.

    Args:
        script: 파싱된 대본.
        topic: 원본 주제.

    Returns:
        기본값이 적용된 대본.
    """
    defaults: dict[str, Any] = {
        "title": topic[:15],
        "hook": "", "content": "", "creator_opinion": "",
        "twist": "", "conclusion": "", "full_script": "",
        "keywords": [],
        "search_keywords": [],
        "section_backgrounds": {},
        "background_keywords_en": {},
        "subtitle_chunks": [],
        "youtube_titles": [],
        "thumbnail_text": "",
        "description_draft": "",
        "seo_tags": [],
        "unique_angle": "", "fact_sources": [],
        "emotion_map": [], "hashtags": [],
        "bg_theme": "",
        "template_used": "",
    }
    for key, default in defaults.items():
        if key not in script:
            script[key] = default

    # search_keywords 폴백
    if not script["search_keywords"] or len(script["search_keywords"]) < 3:
        script["search_keywords"] = _generate_topic_keywords(topic)

    # section_backgrounds 폴백
    if not script.get("section_backgrounds"):
        kw = script["search_keywords"]
        script["section_backgrounds"] = {
            "hook": kw[0] if kw else "lifestyle",
            "content": kw[1] if len(kw) > 1 else "daily life",
            "twist": kw[2] if len(kw) > 2 else "surprise",
            "conclusion": kw[3] if len(kw) > 3 else "happy people",
        }

    # background_keywords_en 폴백
    if not script.get("background_keywords_en"):
        kw = script["search_keywords"]
        script["background_keywords_en"] = {
            "hook": [kw[0]] if kw else ["lifestyle daily routine"],
            "content": [kw[1]] if len(kw) > 1 else ["daily life home"],
            "opinion": [kw[2]] if len(kw) > 2 else ["person thinking"],
            "twist": [kw[3]] if len(kw) > 3 else ["surprise reveal"],
            "conclusion": [kw[0]] if kw else ["happy person smiling"],
        }

    # youtube_titles 폴백
    if not script.get("youtube_titles"):
        script["youtube_titles"] = [script.get("title", topic[:15])]

    # hashtags 기본값 보강 (쇼츠 기본 태그)
    base_hashtags = ["#쇼츠", "#shorts", "#한국", "#레전드", "#실화"]
    existing = script.get("hashtags", [])
    if len(existing) < 5:
        for tag in base_hashtags:
            if tag not in existing:
                existing.append(tag)
        script["hashtags"] = existing[:10]

    return script


def _call_gemini(prompt: str, settings: Settings) -> str:
    """Gemini 2.0 Flash API를 호출합니다.

    Args:
        prompt: 프롬프트 문자열.
        settings: 설정 인스턴스.

    Returns:
        응답 텍스트.
    """
    import google.generativeai as genai

    api_key = SecretsManager.get_secret_value(settings.google_api_key)
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )
    return response.text


def _call_openai(prompt: str, settings: Settings) -> str:
    """OpenAI GPT-4o-mini API를 호출합니다 (대본 생성 폴백).

    Args:
        prompt: 프롬프트 문자열.
        settings: 설정 인스턴스.

    Returns:
        응답 텍스트.
    """
    import openai

    api_key = SecretsManager.get_secret_value(settings.openai_api_key)
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=6000,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content


def _call_anthropic(prompt: str, settings: Settings) -> str:
    """Claude API를 호출합니다.

    Args:
        prompt: 프롬프트 문자열.
        settings: 설정 인스턴스.

    Returns:
        응답 텍스트.
    """
    import anthropic

    api_key = SecretsManager.get_secret_value(settings.anthropic_api_key)
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _select_llm_backend(settings: Settings) -> str:
    """사용 가능한 LLM 백엔드를 선택합니다.

    Google Gemini 1순위 → OpenAI GPT-4o-mini 2순위

    Returns:
        "gemini" 또는 "openai".
    """
    google_key = SecretsManager.get_secret_value(settings.google_api_key)
    if google_key:
        return "gemini"
    openai_key = SecretsManager.get_secret_value(settings.openai_api_key)
    if openai_key:
        return "openai"
    raise RuntimeError("GOOGLE_API_KEY 또는 OPENAI_API_KEY를 설정해주세요.")


@retry(max_retries=2, retryable_exceptions=(ConnectionError, TimeoutError, OSError))
def generate_script(
    topic: str,
    style: str = "creative",
    source_text: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """독창적 스토리텔링 기반 숏츠 대본을 생성합니다.

    AI 슬롭 방지:
    - 대본 템플릿 5종 랜덤 사용
    - 영상 길이 45~90초 랜덤
    - template_used 필드에 사용된 템플릿 기록

    Args:
        topic: 영상 주제.
        style: 대본 스타일 (creative/analytical/emotional/humorous/expert/community).
        source_text: 크롤링된 원본 텍스트 (community 스타일에서 사용).
        settings: 설정 인스턴스 (None이면 글로벌 설정 사용).

    Returns:
        대본 딕셔너리 (title, full_script, tts_script, keywords 등).
    """
    if settings is None:
        settings = get_settings()

    # community 스타일이고 source_text가 있으면 커뮤니티 프롬프트 사용
    if style == "community" and source_text:
        hook_style = random.choice(COMMUNITY_HOOKS)
        angle = "커뮤니티 썰 재구성"
        prompt = _build_community_prompt(topic, source_text, hook_style, style)
    elif style == "community":
        hook_style = random.choice(COMMUNITY_HOOKS)
        angle = "커뮤니티 썰 스타일"
        prompt = _build_community_prompt(topic, "", hook_style, style)
    else:
        angle = random.choice(UNIQUE_ANGLES)
        hook_style = random.choice(STORYTELLING_HOOKS)
        prompt = _build_prompt(topic, angle, hook_style, style)

    backend = _select_llm_backend(settings)
    logger.info("%s 대본 생성 요청 (스타일: %s, 관점: %s)", backend.upper(), style, angle)

    # 대본 생성: Gemini 1순위 → OpenAI 2순위
    text = ""
    if backend == "gemini":
        try:
            text = _call_gemini(prompt, settings)
        except Exception as e:
            logger.warning("Gemini 호출 실패: %s - OpenAI 폴백 시도", e)
            openai_key = SecretsManager.get_secret_value(settings.openai_api_key)
            if openai_key:
                text = _call_openai(prompt, settings)
                backend = "openai"
                logger.info("OpenAI GPT-4o-mini 폴백 성공")
            else:
                raise
    elif backend == "openai":
        try:
            text = _call_openai(prompt, settings)
        except Exception as e:
            logger.warning("OpenAI 호출 실패: %s", e)
            raise

    script = _parse_script_response(text)

    # community 스타일: script[] 배열 → full_script + emotion_map 변환
    if style == "community" and "script" in script and isinstance(script["script"], list):
        script = _convert_community_script(script)

    script = _apply_defaults(script, topic)

    # TTS용 클린 텍스트 생성 (모든 감정 태그 + 마크다운 제거)
    tts_text = script["full_script"]
    # **볼드** 마크다운 먼저 제거 (TTS가 별표 읽으면 안됨)
    tts_text = tts_text.replace("**", "")
    for tag in [
        "[놀람]", "[강조]", "[속삭임]", "[열정]",
        "[크리에이터 분석]", "[소름]", "[분노]", "[공감]", "[웃김]", "[반전]",
        "(극대노)", "(속삭임)", "(비웃음)", "(다급하게)", "(침착하게)",
        "*",
    ]:
        tts_text = tts_text.replace(tag, "")
    script["tts_script"] = tts_text.strip()
    # full_script에서도 볼드 제거
    script["full_script"] = script["full_script"].replace("**", "")

    script["style"] = style
    script["angle"] = angle
    script["llm_backend"] = backend

    # 최소 대본 길이 체크 (최소 200자 필요)
    MIN_SCRIPT_LENGTH = 200
    script_length = len(script["tts_script"])

    if script_length < MIN_SCRIPT_LENGTH:
        logger.warning(
            f"대본 너무 짧음 ({script_length}자 < {MIN_SCRIPT_LENGTH}자) - 재생성 시도..."
        )
        try:
            return generate_script(topic, style, source_text, settings)
        except Exception as e:
            logger.error(f"대본 재생성 실패: {e} - 짧은 대본 그대로 사용")

    # 금지 키워드 최종 체크 (AI 슬롭 + 금지 주제)
    banned_in_script = [
        '고양이', '강아지', '반려동물',
        '여러분', '선택은', '어떻게 생각',
        '경제학', '딜레마', '철학',
        '여러분의', '의견을', '남겨주세요',
        '마무리하며', '결론적으로', '요약하자면',
    ]
    script_text = script["tts_script"] + " " + script.get("title", "")
    found_banned = [kw for kw in banned_in_script if kw in script_text]

    # AI가 생성한 한국인 이름 패턴 감지 (2~3글자 성+이름)
    import re
    korean_names = re.findall(r'[가-힣]{1}[가-힣]{1,2}(?:이|가|는|을|를|의|에게|한테|씨)', script_text)
    # "걔가", "사장이" 같은 건 제외하고 실제 이름만
    name_prefixes = ['김', '이', '박', '최', '정', '강', '조', '윤', '장', '임', '한', '오', '서', '신', '권', '황', '안', '송', '류', '홍']
    real_names = [n for n in korean_names if n[0] in name_prefixes and len(n) >= 3]

    if found_banned or real_names:
        if real_names:
            logger.warning(f"대본에 AI 생성 이름 발견: {real_names} - 폴백 주제로 재생성...")
        else:
            logger.warning(f"대본에 금지 키워드 발견: {found_banned} - 폴백 주제로 재생성...")
        try:
            fallback_topic = random.choice(TRENDING_TOPICS)
            return generate_script(
                fallback_topic["title"],
                style,
                fallback_topic.get("body", ""),
                settings
            )
        except Exception as e:
            logger.error(f"폴백 재생성 실패: {e} - 원본 대본 사용")

    logger.info(
        "대본 생성 완료: '%s' (%d자, %s, 템플릿: %s)",
        script["title"], len(script["tts_script"]), backend,
        script.get("template_used", "알수없음"),
    )
    return script


def _convert_community_script(script: dict[str, Any]) -> dict[str, Any]:
    """community 프롬프트의 script[] 배열을 기존 파이프라인 포맷으로 변환합니다.

    script[] → full_script, emotion_map, subtitle_chunks, keywords 등.
    highlight 필드(string 또는 boolean)를 keywords에 자동 수집합니다.
    pause_ms 필드를 subtitle_chunks에 보존합니다.

    Args:
        script: LLM 응답에서 파싱된 raw 딕셔너리.

    Returns:
        파이프라인 호환 딕셔너리.
    """
    entries = script["script"]

    # full_script: 모든 text를 공백으로 연결
    full_text = " ".join(e["text"] for e in entries if "text" in e)
    script["full_script"] = full_text

    # emotion_map: [{text, emotion}]
    script["emotion_map"] = [
        {"text": e["text"], "emotion": e.get("emotion", "neutral")}
        for e in entries if "text" in e
    ]

    # subtitle_chunks: [{text, section, emotion, highlight, pause_ms}]
    total = len(entries)
    chunks = []
    for idx, e in enumerate(entries):
        ratio = idx / max(total, 1)
        if ratio < 0.12:
            section = "hook"
        elif ratio < 0.45:
            section = "content"
        elif ratio < 0.62:
            section = "opinion"
        elif ratio < 0.78:
            section = "twist"
        else:
            section = "conclusion"

        raw_hl = e.get("highlight", "")
        if isinstance(raw_hl, bool):
            highlight = e.get("text", "") if raw_hl else ""
        else:
            highlight = str(raw_hl) if raw_hl else ""

        chunks.append({
            "text": e.get("text", ""),
            "section": section,
            "emotion": e.get("emotion", "neutral"),
            "highlight": highlight,
            "pause_ms": int(e.get("pause_ms", 0)),
            "scene_hint": e.get("scene_hint", ""),
        })
    script["subtitle_chunks"] = chunks

    # hook/content/twist/conclusion 파트 분할
    hook_entries = [e for i, e in enumerate(entries) if i / max(total, 1) < 0.12]
    content_entries = [e for i, e in enumerate(entries) if 0.12 <= i / max(total, 1) < 0.45]
    twist_entries = [e for i, e in enumerate(entries) if 0.62 <= i / max(total, 1) < 0.78]
    conclusion_entries = [e for i, e in enumerate(entries) if i / max(total, 1) >= 0.78]

    script.setdefault("hook", " ".join(e["text"] for e in hook_entries))
    script.setdefault("content", " ".join(e["text"] for e in content_entries))
    script.setdefault("twist", " ".join(e["text"] for e in twist_entries))
    script.setdefault("conclusion", " ".join(e["text"] for e in conclusion_entries))
    script.setdefault("creator_opinion", "")

    # highlight → keywords 자동 수집 (중복 제거)
    highlights: list[str] = []
    for e in entries:
        hl = e.get("highlight", "")
        if isinstance(hl, bool) and hl:
            highlights.append(e.get("text", ""))
        elif isinstance(hl, str) and hl:
            highlights.append(hl)
    highlights = list(dict.fromkeys(highlights))
    if highlights and not script.get("keywords"):
        script["keywords"] = highlights[:5]

    return script
