"""
============================================================================
 youshorts 완벽한 영상 1개 생성 마스터 파이프라인
 ──────────────────────────────────────────────
 역할: 풀스택 개발자 + 숏츠 배포 전문가
 목표: 트렌드 수집 → 대본 → TTS → 자막 → 렌더링까지 1개 영상 완성

 사용법: python perfect_one_shot.py
 필요: pip install edge-tts google-generativeai requests beautifulsoup4
 환경변수: GOOGLE_API_KEY (Gemini용)
============================================================================
"""
import argparse
import asyncio
import functools
import io
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Type, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger("youshorts")

# .env 파일 로드 (GOOGLE_API_KEY 등)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass  # python-dotenv 없으면 환경변수 직접 설정 필요

# Windows cp949 콘솔 유니코드 출력 대응
if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace"
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace"
    )


# ============================================================================
# 설정
# ============================================================================
class Config:
    """프로젝트 전체 설정 - constants.py 역할"""

    # ── 경로 ──
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output"
    BGM_DIR = BASE_DIR / "data" / "bgm"
    BG_DIR = BASE_DIR / "data" / "backgrounds"
    HISTORY_FILE = BASE_DIR / "data" / "history.json"

    # ── 영상 스펙 ──
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 30
    MAX_DURATION = 59  # 숏츠 제한 60초 미만

    # ── TTS ──
    TTS_VOICE = "ko-KR-InJoonNeural"  # 남성 음성 (SunHi=여성→InJoon=남성)
    TTS_RATE = "+10%"
    TTS_PITCH = "+0Hz"

    # ── 자막 ──
    SUBTITLE_FONT = "Malgun Gothic"
    SUBTITLE_SIZE = 62
    SUBTITLE_COLOR_NORMAL = "&H00FFFFFF"
    SUBTITLE_COLOR_HIGHLIGHT = "&H0000FFFF"
    SUBTITLE_OUTLINE = 4
    SUBTITLE_SHADOW = 2
    SUBTITLE_MARGIN_V = 350

    # ── 품질 ──
    MIN_QUALITY_SCORE = 80
    MAX_RETRY = 5

    # ── AI 슬롭 금지어 (대폭 확장) ──
    AI_SLOP_WORDS = [
        # 격식체/뉴스체
        "흥미롭", "놀라운", "충격적", "심층", "탐구", "여정",
        "알아보겠", "살펴보겠", "함께 알아", "그렇다면",
        "~인 셈이다", "~라 할 수 있", "결론적으로",
        "마무리하며", "정리하자면", "요약하자면",
        "주목할 만한", "눈여겨볼", "한편으로는", "다른 한편으로는",
        "주목해야", "깊이 있는", "의미 있는", "다양한 측면",
        "시사하는 바", "귀추가 주목", "전문가들은", "관계자에 따르면",
        "이목이 집중", "화제를 모으", "논란이 되고",
        # AI 특유의 과잉 서술
        "매력적인", "인상적인", "독보적인", "혁신적인",
        "획기적인", "압도적인", "경이로운", "놀랍게도",
        "흥미진진", "감탄을 자아", "눈길을 끄",
        # AI 특유의 연결어
        "그뿐만 아니라", "이에 더해", "나아가", "더불어",
        "한 걸음 더", "이어서", "덧붙이자면",
        # AI 특유의 마무리
        "되새겨 보", "돌아보면", "곰곰이 생각",
        "깊은 울림", "큰 교훈", "시사하는 점",
        # 격식 높임 (숏츠 부적합)
        "하겠습니다", "드리겠습니다", "말씀드리",
        "되겠습니다", "되시겠습니까",
    ]

    # ── 생산 한도 ──
    MAX_PER_DAY = 10

    # ── 이모지 패턴 ──
    EMOJI_PATTERN = re.compile(
        "[😀-🙏🌀-🗿"
        "🚀-🛿🇠-🇿"
        "✂-➰︀-️"
        "🤀-🧿🨀-🩯]"
    )

    # ── YouTube ──
    YOUTUBE_PRIVACY = "public"

    # ── FFmpeg ──
    FFMPEG_EXE = "ffmpeg"
    FFPROBE_EXE = "ffprobe"

    # ── 주제 필터 ──
    TOPIC_BLACKLIST = [
        # 정치 (은어/비속어 포함)
        "국회", "대통령", "탄핵", "여당", "야당", "민주당", "국민의힘",
        "총선", "선거", "후보", "정당", "의원", "청와대", "정부",
        "외교", "북한", "한미", "정상회담", "국방", "안보",
        "친노", "친문", "친윤", "좌파", "우파", "진보", "보수",
        "이재명", "윤석열", "한동훈", "이낙연", "손학규",
        "똥파리", "손가혁", "문빠", "윤빠", "국짐", "민짜",
        "핵협상", "속보", "긴급",
        # 경제
        "금리", "환율", "증시", "코스피", "코스닥", "주가", "GDP",
        "물가", "인플레이션", "기준금리", "한은", "국채",
        # 사건사고
        "사망", "사고", "화재", "지진", "태풍", "폭발", "추모",
        "유족", "희생", "참사", "실종", "붕괴",
        # 법률
        "재판", "판결", "구속", "기소", "검찰", "경찰", "수사",
        "피의자", "혐의", "체포", "송치",
        # 행정
        "국무회의", "예산", "법안", "조례", "감사원", "규제",
        # 커뮤니티 잡글 (공지/광고/모집/질문)
        "공지", "통합", "체험단", "모집", "이벤트", "광고", "제휴",
        "스포", "질문드립니다", "질문있습니다", "문의", "안내",
        "구인", "구직", "팝니다", "삽니다", "한줄평", "설문",
        # 숏츠 부적합
        "밥상", "명절", "시어머니", "며느리",
        "택시", "심쿵", "로맨스",
        # 시즌/명절 이슈 (지난 이슈 배제)
        "설날", "새해", "추석", "한가위", "크리스마스", "성탄절",
        "발렌타인", "화이트데이", "어버이날", "스승의날",
        "졸업식", "입학식", "수능", "수능날",
        # 광고/스팸
        "텔레그램", "단톡방", "카톡방", "오픈채팅",
        "비트코인", "가상화폐", "코인", "NFT",
        "투자", "수익률", "원금보장",
        "무료나눔", "선착순", "할인코드",
        # 의료/건강 허위정보 위험
        "암 치료", "특효약", "민간요법", "자가진단",
        "병원에서 안 알려주는", "의사가 숨기는",
        # 성인/부적절
        "후방주의", "19금", "은꼴",
    ]

    # 바이럴 신호 키워드 (브랜드명 제거, 반응/감정/행동 키워드 위주)
    TOPIC_BOOST_KEYWORDS = [
        "레전드", "실화", "대박", "미쳤", "소름", "논란",
        "반전", "후기", "먹방", "게임", "리뷰",
        "아이돌", "드라마", "영화", "웹툰",
        "밈", "챌린지", "핫", "터짐", "난리",
        "비교", "랭킹", "순위", "VS", "TOP",
        "꿀팁", "해봄", "써봄", "사봄", "가봄",
        # 2030 타겟 부스트
        "월급", "퇴사", "야근", "자취", "월세", "전세",
        "사회초년생", "직장상사", "꼰대", "MZ", "워라밸",
        "연봉", "이직", "알바", "면접", "취준",
        "썸", "소개팅", "결혼", "축의금", "청첩장",
        "연애", "재테크", "고백", "적금", "청약",
    ]

    # ── 숏츠 폭발력 카테고리 (조회수 100만+ 실적 기반) ──
    VIRAL_CATEGORY_KEYWORDS = {
        # Tier S: 100만뷰 확률 높은 카테고리
        "공포_미스터리": {
            "keywords": ["공포", "귀신", "심령", "미스터리", "소름", "무서운", "괴담",
                          "호러", "폐건물", "도시전설", "납골당", "저주"],
            "boost": 50000,
        },
        "놀라운_사실": {
            "keywords": ["충격", "알고보니", "진실", "몰랐던", "비밀", "반전",
                          "실화", "레전드", "역대급", "미쳤", "경악"],
            "boost": 45000,
        },
        "밈_유머": {
            "keywords": ["밈", "짤", "ㅋㅋ", "웃긴", "개웃", "존웃", "킹받",
                          "빡침", "어이없", "황당", "해프닝", "웃참"],
            "boost": 40000,
        },
        "비교_랭킹": {
            "keywords": ["비교", "VS", "랭킹", "순위", "TOP", "1위",
                          "최고", "최악", "차이", "어떤게", "뭐가"],
            "boost": 40000,
        },
        "꿀팁_라이프핵": {
            "keywords": ["꿀팁", "방법", "노하우", "핵꿀", "개꿀", "팁",
                          "가성비", "알뜰", "저렴", "아끼는", "절약"],
            "boost": 35000,
        },
        "문화충격_반응": {
            "keywords": ["외국인", "문화충격", "반응", "한국", "해외", "리액션",
                          "충격받", "놀란", "차이점", "비교문화"],
            "boost": 45000,
        },
        "게임_애니": {
            "keywords": ["게임", "롤", "발로란트", "마크", "원신", "애니",
                          "원피스", "귀멸", "나루토", "주술회전", "진격"],
            "boost": 35000,
        },
    }

    # ── 숏츠 부적합 감점 카테고리 (조회수 낮은 유형) ──
    BORING_PENALTY_PATTERNS = [
        # 일상 잡담 (숏츠에서 안 터짐)
        (r"남친|여친|남자친구|여자친구|설거지|시댁|시어머니|결혼식", -30000, "연애/결혼 일상"),
        (r"회사|직장|퇴근|출근|야근|상사|선배|신입", -20000, "직장 일상"),
        (r"다이어트|식단|운동|헬스", -15000, "다이어트 일상"),
        (r"카페|맛집|디저트|빵집", -15000, "카페/맛집 일상"),
        # 연예 단순 가십 (깊이 없는 것)
        (r"열애|결별|소속사|컴백|앨범|팬싸", -10000, "연예 단순뉴스"),
    ]

    # ── 주제별 배경 모드 ──
    TOPIC_BG_MAP: dict[str, list[str]] = {
        "gameplay": ["게임", "롤", "서퍼", "챌린지", "밈", "짤", "마크", "발로란트"],
        "gradient": [
            "맛집", "편의점", "카페", "음식", "요리", "레시피",
            "다이소", "올리브영", "뷰티", "패션", "꿀팁", "가성비",
            "자취", "꿀조합", "신상", "후기", "먹방",
        ],
    }

    # 주제 키워드 → 그라디언트 색상 (상단→하단, 어둡지만 확실히 색감 보이는 톤)
    GRADIENT_COLORS: dict[str, tuple[str, str]] = {
        "food":    ("#1C1C1C", "#3D2B1F"),  # 차콜 → 다크브라운 (따뜻한 톤)
        "beauty":  ("#1C1C1C", "#2D2D3F"),  # 차콜 → 다크슬레이트 (차가운 톤)
        "info":    ("#1C1C1C", "#1A2A3A"),  # 차콜 → 다크네이비
        "default": ("#1C1C1C", "#2A2A2A"),  # 차콜 → 다크그레이 (무채색)
    }
    GRADIENT_TOPIC_MAP: dict[str, list[str]] = {
        "food":   ["맛집", "편의점", "음식", "요리", "레시피", "먹방", "꿀조합", "카페", "맥도날드", "스타벅스"],
        "beauty": ["올리브영", "뷰티", "패션", "다이소", "화장", "스킨"],
        "info":   ["꿀팁", "가성비", "후기", "자취", "신상", "정보"],
    }


# ============================================================================
# retry 데코레이터 (지수 백오프 + 지터)
# ============================================================================
DEFAULT_RETRYABLE: tuple[Type[BaseException], ...] = (
    ConnectionError, TimeoutError, OSError,
)


def retry(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    jitter: float = 0.5,
    retryable_exceptions: Sequence[Type[BaseException]] = DEFAULT_RETRYABLE,
) -> Callable[[F], F]:
    """API 호출 실패 시 자동 재시도 (지수 백오프)."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except tuple(retryable_exceptions) as e:
                    last_exc = e
                    if attempt < max_retries:
                        wait = backoff_factor ** attempt + random.uniform(0, jitter)
                        print(f"  [RETRY] {func.__name__} ({attempt+1}/{max_retries+1}): {e}")
                        time.sleep(wait)
            raise last_exc  # type: ignore
        return wrapper  # type: ignore
    return decorator


# ============================================================================
# 일일 생산 한도 체크
# ============================================================================
def check_daily_limit() -> bool:
    """오늘 생산 개수가 MAX_PER_DAY 이하인지 확인."""
    if not Config.HISTORY_FILE.exists():
        return True
    try:
        data = json.loads(Config.HISTORY_FILE.read_text(encoding="utf-8"))
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = sum(
            1 for item in data
            if item.get("created_at", "").startswith(today)
        )
        if today_count >= Config.MAX_PER_DAY:
            print(f"  [WARN] 일일 한도 도달: {today_count}/{Config.MAX_PER_DAY}개")
            return False
        print(f"  오늘 생산: {today_count}/{Config.MAX_PER_DAY}개")
        return True
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        logger.warning(f"일일 한도 확인 실패: {e}")
        return True


# ============================================================================
# FFmpeg / FFprobe 경로 탐색
# ============================================================================
def _find_ffmpeg_exe() -> str:
    """imageio_ffmpeg 우선, 없으면 PATH의 ffmpeg."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def _find_ffprobe_exe() -> str:
    """imageio_ffmpeg 기반 ffprobe 경로."""
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")
        if os.path.exists(ffprobe_path):
            return ffprobe_path
    except ImportError:
        pass
    return "ffprobe"


# ============================================================================
# STEP 1: 트렌드 수집 - 3개 소스 + APIFY
# ============================================================================
class TrendCollector:
    """
    트렌드 수집 전략:
    Google Trends RSS + 네이버 시그널 + 커뮤니티 핫글 + APIFY
    → 블랙리스트 필터 → 부스트 적용 → 중복 제거 → TOP 1 선정
    """

    def __init__(self):
        self.trends = []

    def fetch_google_trends_rss(self) -> list[dict]:
        """RSS 피드라 API 키 불필요, IP 차단 0%"""
        import requests

        url = "https://trends.google.co.kr/trending/rss?geo=KR"
        results = []

        try:
            resp = requests.get(url, timeout=5, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0"
            })
            resp.raise_for_status()

            root = ET.fromstring(resp.text)
            ns = {"ht": "https://trends.google.co.kr/trending/rss"}

            for idx, item in enumerate(root.findall(".//item")):
                title = item.find("title")
                if title is not None and title.text:
                    traffic = item.find("ht:approx_traffic", ns)
                    traffic_num = 0
                    if traffic is not None and traffic.text:
                        traffic_num = int(
                            traffic.text.replace(",", "").replace("+", "")
                        )
                    # traffic 값 없으면 순위 기반 기본점수 (실검이니 최소 10,000)
                    if traffic_num == 0:
                        traffic_num = max(50000 - idx * 3000, 10000)
                    results.append({
                        "keyword": title.text.strip(),
                        "source": "google_trends",
                        "score": traffic_num,
                    })

            print(f"  [OK] Google Trends: {len(results)}개 수집")

        except Exception as e:
            print(f"  [WARN] Google Trends 실패: {e}")

        return results

    def fetch_naver_realtime(self) -> list[dict]:
        """네이버 실시간 급상승 검색어 (연관검색어 API 활용)"""
        import requests
        from bs4 import BeautifulSoup

        results = []

        # 1) 네이버 모바일 메인 급상승 검색어
        try:
            url = "https://m.search.naver.com/search.naver?query=%EC%8B%A4%EC%8B%9C%EA%B0%84+%EA%B8%89%EC%83%81%EC%8A%B9"
            resp = requests.get(url, timeout=5, headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S908B) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
            })
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # 급상승 검색어 항목
                items = soup.select(".lst_relate .item") or soup.select("a.keyword")
                for i, item in enumerate(items[:15]):
                    text = item.get_text(strip=True)
                    if text and len(text) > 1:
                        results.append({
                            "keyword": text,
                            "source": "naver_realtime",
                            "score": (15 - i) * 5000,
                        })
        except (ConnectionError, TimeoutError, Exception) as e:
            logger.warning(f"요청 실패: {e}")

        # 2) 네이버 쇼핑 인기 검색어 (소비 트렌드 = 쇼츠 주제 적합)
        try:
            url2 = "https://search.shopping.naver.com/search/all?query=%EC%9D%B8%EA%B8%B0&sort=rel"
            resp2 = requests.get(url2, timeout=5, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0",
            })
            if resp2.status_code == 200:
                soup2 = BeautifulSoup(resp2.text, "html.parser")
                items2 = soup2.select(".relateKeyword_relation_item__key") or []
                for i, item in enumerate(items2[:10]):
                    text = item.get_text(strip=True)
                    if text and len(text) > 1:
                        results.append({
                            "keyword": text,
                            "source": "naver_shopping",
                            "score": (10 - i) * 4000,
                        })
        except (ConnectionError, TimeoutError, Exception) as e:
            logger.warning(f"요청 실패: {e}")

        if results:
            print(f"  [OK] 네이버 실시간: {len(results)}개 수집")
        else:
            print(f"  [WARN] 네이버 실시간 수집 실패")

        return results

    def fetch_community_hot(self) -> list[dict]:
        """커뮤니티 실시간 베스트 — 봇차단 없는 사이트 위주"""
        import requests
        from bs4 import BeautifulSoup

        results = []
        communities = [
            {
                "name": "네이트판",
                "url": "https://pann.nate.com/talk/ranking",
                "title_sel": ".tlt",
                "base_url": "https://pann.nate.com",
            },
            {
                "name": "클리앙",
                "url": "https://www.clien.net/service/board/park",
                "title_sel": ".list_subject .subject_fixed",
                "base_url": "https://www.clien.net",
            },
            {
                "name": "루리웹",
                "url": "https://bbs.ruliweb.com/community/board/300143/best",
                "title_sel": ".subject .deco",
                "base_url": "https://bbs.ruliweb.com",
            },
            {
                "name": "더쿠",
                "url": "https://theqoo.net/hot",
                "title_sel": ".tit_topic a, .title a",
                "base_url": "https://theqoo.net",
            },
        ]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }

        for comm in communities:
            try:
                resp = requests.get(
                    comm["url"], timeout=8, headers=headers,
                )
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                titles = soup.select(comm["title_sel"])

                count = 0
                for i, t in enumerate(titles[:10]):
                    text = t.get_text(strip=True)
                    text = re.sub(r'\d{2,}$', '', text).strip()

                    if not text or len(text) < 5 or "[광고]" in text:
                        continue

                    href = t.get("href", "")
                    if href and not href.startswith("http"):
                        href = comm["base_url"] + href

                    # ── 참여도 추출 (조회수/댓글수/추천수) ──
                    engagement_score = 0
                    parent = t.find_parent("tr") or t.find_parent("div") or t.find_parent("li")
                    if parent:
                        parent_text = parent.get_text()
                        # 조회수 (일반적인 패턴)
                        view_m = re.search(r'(\d{1,3}(?:,\d{3})*)\s*(?:조회|읽음|hit)', parent_text)
                        if view_m:
                            engagement_score += int(view_m.group(1).replace(",", "")) * 0.01
                        # 댓글수 (숫자 + [] 패턴)
                        cmt_m = re.search(r'\[(\d+)\]', parent_text)
                        if cmt_m:
                            engagement_score += int(cmt_m.group(1)) * 1.5
                        # 추천수
                        rec_m = re.search(r'(\d+)\s*(?:추천|공감|좋아요)', parent_text)
                        if rec_m:
                            engagement_score += int(rec_m.group(1)) * 2.0

                    # 위치 기반 + 참여도 복합 점수
                    base_score = (10 - i) * 3000
                    results.append({
                        "keyword": text,
                        "source": f"community_{comm['name']}",
                        "score": base_score + engagement_score,
                        "url": href,
                        "body": "",
                    })
                    count += 1

                print(f"  [OK] {comm['name']}: {count}개")

            except Exception as e:
                print(f"  [WARN] {comm['name']} 실패: {e}")

        return results

    def fetch_post_body(self, url: str) -> str:
        """게시글 URL에서 본문 텍스트를 크롤링"""
        import requests
        from bs4 import BeautifulSoup

        if not url:
            return ""

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }

        try:
            resp = requests.get(url, timeout=8, headers=headers)
            if resp.status_code != 200:
                return ""

            soup = BeautifulSoup(resp.text, "html.parser")
            body_selectors = [
                "#contentArea", ".posting_area", "#content",
                ".rd_body", ".xe_content", "article",
                ".memo_content", ".post_content",
            ]

            for sel in body_selectors:
                body_el = soup.select_one(sel)
                if body_el:
                    text = body_el.get_text(separator="\n", strip=True)
                    if len(text) > 30:
                        return text[:2000]

        except Exception as e:
            logger.warning(f"본문 크롤링 실패: {e}")

        return ""

    def collect_all(self) -> list[dict]:
        """기본 3개 소스 + APIFY 합산, 블랙리스트 필터 + 부스트"""
        print("\n" + "=" * 60)
        print("STEP 1: 트렌드 수집")
        print("=" * 60)

        all_trends = []
        all_trends.extend(self.fetch_google_trends_rss())
        all_trends.extend(self.fetch_naver_realtime())
        all_trends.extend(self.fetch_community_hot())

        # APIFY 크롤러 (토큰 있으면 자동 추가)
        apify_results = ApifyCrawler.crawl()
        if apify_results:
            all_trends.extend(apify_results)
            print(f"  [OK] APIFY: {len(apify_results)}개 추가")

        # ── 블랙리스트 + 영어/짧은 제목 필터링 ──
        filtered = []
        blocked = 0
        for t in all_trends:
            kw = t["keyword"]
            # 블랙리스트
            if any(bw in kw for bw in Config.TOPIC_BLACKLIST):
                blocked += 1
                continue
            # 영어 비율 50% 이상이면 제거 (한국어 쇼츠에 부적합)
            eng_chars = sum(1 for c in kw if c.isascii() and c.isalpha())
            if len(kw) > 3 and eng_chars / len(kw) > 0.5:
                blocked += 1
                continue
            # 너무 짧은 키워드 (2글자 이하) 제거
            clean_kw = re.sub(r'[^가-힣a-zA-Z0-9]', '', kw)
            if len(clean_kw) < 3:
                blocked += 1
                continue
            filtered.append(t)

        if blocked:
            print(f"  [FILTER] 블랙리스트 {blocked}개 제거")

        # ── 커뮤니티 잡글 필터 (질문/공지/짧은 제목 제거) ──
        junk_patterns = ["?", "질문", "뭘까", "어떻게", "하는건가", "드립니다",
                         "📢", "중요", "변경 권장", "규칙", "카테고리"]
        pre_junk = len(filtered)
        filtered = [
            t for t in filtered
            if not ("community" in t.get("source", "")
                    and (len(t["keyword"]) < 10
                         or any(jp in t["keyword"] for jp in junk_patterns)))
        ]
        junk_removed = pre_junk - len(filtered)
        if junk_removed:
            print(f"  [FILTER] 커뮤니티 잡글 {junk_removed}개 제거")

        # ── 점수 재조정 ──
        # Google Trends: 실제 검색량 기반이므로 가장 신뢰도 높음
        # 커뮤니티: 게시판 글 순서 기반, 쇼츠 적합성 불확실
        for t in filtered:
            src = t.get("source", "")
            if src == "google_trends":
                pass  # 기본 점수 유지
            elif "community" in src:
                t["score"] = int(t["score"] * 1.5)  # 약한 부스트만

        # ── 부스트 키워드 보너스 (어느 소스든 적용) ──
        for t in filtered:
            kw = t["keyword"]
            boost_count = sum(1 for bk in Config.TOPIC_BOOST_KEYWORDS if bk in kw)
            if boost_count:
                t["score"] += boost_count * 20000

        # ── 숏츠 폭발력 카테고리 부스트 (가장 중요!) ──
        for t in filtered:
            kw = t["keyword"]
            best_cat = ""
            best_boost = 0
            for cat_name, cat_info in Config.VIRAL_CATEGORY_KEYWORDS.items():
                match_count = sum(1 for ck in cat_info["keywords"] if ck in kw)
                if match_count > 0 and cat_info["boost"] > best_boost:
                    best_boost = cat_info["boost"]
                    best_cat = cat_name
            if best_boost:
                t["score"] += best_boost
                t["_viral_category"] = best_cat

        # ── 숏츠 부적합 감점 (일상 잡담/가십 걸러내기) ──
        for t in filtered:
            kw = t["keyword"]
            for pat, penalty, label in Config.BORING_PENALTY_PATTERNS:
                if re.search(pat, kw):
                    t["score"] += penalty  # 음수값이므로 감점
                    break

        # ── 중복 키워드 합산 (URL/body 보존) ──
        merged = {}
        for t in filtered:
            kw = t["keyword"]
            if kw in merged:
                merged[kw]["score"] += t["score"]
                merged[kw]["sources"].append(t["source"])
                if t.get("url") and not merged[kw].get("url"):
                    merged[kw]["url"] = t["url"]
            else:
                merged[kw] = {
                    "keyword": kw,
                    "score": t["score"],
                    "sources": [t["source"]],
                    "url": t.get("url", ""),
                }

        sorted_trends = sorted(
            merged.values(), key=lambda x: x["score"], reverse=True
        )

        print(f"\n  총 {len(sorted_trends)}개 트렌드 수집 완료")
        for i, t in enumerate(sorted_trends[:5]):
            sources = ", ".join(t["sources"])
            print(f"  {i + 1}. [{t['score']:,}점] {t['keyword']} ({sources})")

        return sorted_trends


# ============================================================================
# STEP 1.5: 뉴스 보강 - 팩트 기반 대본 원료
# ============================================================================
class NewsCollector:
    """트렌드 키워드 → Google News RSS + 네이버 뉴스 → 팩트 원료"""

    def fetch_google_news_rss(self, keyword: str) -> list[dict]:
        import requests
        results = []
        try:
            url = (
                f"https://news.google.com/rss/search?"
                f"q={keyword}&hl=ko&gl=KR&ceid=KR:ko"
            )
            resp = requests.get(url, timeout=5)
            root = ET.fromstring(resp.text)

            for item in root.findall(".//item")[:5]:
                title = item.find("title")
                desc = item.find("description")
                if title is not None:
                    results.append({
                        "title": title.text or "",
                        "desc": (desc.text or "")[:200],
                        "source": "google_news",
                    })
            print(f"  [OK] Google News: {len(results)}건")
        except Exception as e:
            print(f"  [WARN] Google News 실패: {e}")
        return results

    def fetch_naver_news(self, keyword: str) -> list[dict]:
        import requests
        from bs4 import BeautifulSoup

        results = []
        try:
            url = f"https://search.naver.com/search.naver?where=news&query={keyword}"
            resp = requests.get(url, timeout=5, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0",
            })
            soup = BeautifulSoup(resp.text, "html.parser")
            news_items = soup.select(".news_tit") or soup.select("a.news_tit")
            for item in news_items[:5]:
                results.append({
                    "title": item.get_text(strip=True),
                    "desc": "",
                    "source": "naver_news",
                })
            print(f"  [OK] 네이버 뉴스: {len(results)}건")
        except Exception as e:
            print(f"  [WARN] 네이버 뉴스 실패: {e}")
        return results

    def collect_news(self, keyword: str) -> list[dict]:
        print(f"\n  뉴스 수집: '{keyword}'")
        news = []
        news.extend(self.fetch_google_news_rss(keyword))
        news.extend(self.fetch_naver_news(keyword))
        return news


# ============================================================================
# STEP 2: 대본 생성 (Gemini 2.0 Flash — 무료)
# ============================================================================
class ScriptGenerator:
    """
    대본 생성: Gemini 2.0 Flash (무료, 유료 폴백 제거)
    검증된 프롬프트 + 커뮤니티 본문 기반 + 품질 85점 이상
    """

    # ── 원글 있을 때: 팩트 기반 나레이션 ──
    PROMPT_WITH_SOURCE = """유튜브 숏츠 100만뷰 나레이션 대본을 만들어.

역할: 20대 한국 남자가 친구한테 "야 이거 봐봐" 하면서 얘기하는 느낌.

규칙:
1. [원글 내용]의 핵심 팩트를 전달해. 없는 내용 절대 지어내지 마.
2. 원글에 없는 대화/인용/수치/날짜를 추가하지 마.
3. 문장 길이는 자유롭게 — 짧은 것(5자)도 긴 것(25자)도 섞어서 리듬감 있게.
4. 전체 15~22문장. 250~400자.
5. 첫 문장은 주제를 바로 꺼내. 훅 잡는 질문이나 핵심 팩트로 시작.
   (패턴: 질문형/충격형/공감형/비밀폭로형/대조형 중 택1)
6. 3줄 연속 같은 분위기 금지 — 감정을 계속 전환해서 이탈 방지.
7. 마지막은 자연스럽게 끝내. 억지 구독유도 하지 마. 대신 질문 던져서 댓글 유도.
8. 금지: "여러분", 실명, **볼드**, 이모지, "구독", "좋아요"

말투 참고 (이걸 그대로 쓰지 말고 자연스럽게 변형해):
- 놀랄 때: "이게 진짜?", "아 이건 좀...", "와 미쳤는데"
- 설명할 때: "근데 이게", "진짜 웃긴 게", "포인트는"
- 마무리: "이 정도면 해볼 만하지", "한번 써봐", "알아서 판단"

절대 쓰지 말 것:
{slop_words}

[주제] {topic}

[원글 내용]
{source_text}

JSON만 출력:
{{
  "title": "제목 15자 이내 (이모지 금지)",
  "tts_script": "줄바꿈으로 구분된 대본",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "description": "설명란 2줄"
}}"""

    # ── 원글 없을 때: 주제 기반 정보형 대본 ──
    PROMPT_NO_SOURCE = """유튜브 쇼츠 나레이션 대본을 만들어.

역할: 20대 한국 남자가 특정 주제에 대해 얘기하는 느낌. 가벼운 정보 전달형.

규칙:
1. [주제]에 대해 널리 알려진 사실이나 대중적으로 공감할 수 있는 내용 위주로 전달.
2. 확인되지 않은 통계/수치/연구결과 절대 사용 금지.
3. 직접 경험한 것처럼 쓰지 마. "~라는 사실 알아?" 같은 일반적 사실만 OK.
4. 의학/법률/금융 정보는 절대 다루지 마. 잘못된 정보는 위험함.
5. 문장 길이 자유 — 짧은 것도 긴 것도 섞어서 리듬감 있게.
6. 전체 15~22문장. 250~400자.
7. 첫 문장은 주제의 핵심을 바로 꺼내. 질문형이나 공감할 수 있는 사실로 시작.
8. 마지막은 자연스럽게 끝내. "구독해" 같은 CTA 하지 마.
9. 금지: "여러분", 실명, **볼드**, 이모지, "구독", "좋아요"
10. "~라는 말이 있다", "전문가에 따르면" 같은 근거 없는 인용 금지.

말투: 친구한테 얘기하듯이 편하게. 억지로 인터넷 용어 넣지 마.
자연스러우면 "ㅋㅋ"나 "ㄷㄷ" 써도 되지만 매 문장마다 쓰지 마.

절대 쓰지 말 것:
{slop_words}

[주제] {topic}

[참고 헤드라인]
{source_text}

JSON만 출력:
{{
  "title": "제목 15자 이내 (이모지 금지)",
  "tts_script": "줄바꿈으로 구분된 대본",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "description": "설명란 2줄"
}}"""

    def _build_prompt(self, topic: str, source_text: str) -> str:
        slop = ", ".join(Config.AI_SLOP_WORDS)
        has_real_source = bool(source_text and len(source_text) > 50
                               and "관련 뉴스 없음" not in source_text)

        if has_real_source:
            # 원글 본문이 있으면 팩트 기반 프롬프트
            return self.PROMPT_WITH_SOURCE.format(
                topic=topic,
                source_text=source_text[:2000],
                slop_words=slop,
            )
        else:
            # 원글 없으면 정보형 프롬프트 (뉴스 헤드라인만 참고)
            headlines = source_text if source_text else "관련 헤드라인 없음"
            return self.PROMPT_NO_SOURCE.format(
                topic=topic,
                source_text=headlines,
                slop_words=slop,
            )

    def _parse_json_response(self, text: str) -> dict:
        """Gemini JSON 응답 파싱 (마크다운 + 제어문자 처리)."""
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)

        # JSON 객체 추출 (regex)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            json_str = match.group(0)
        else:
            json_str = text.strip()

        # 제어 문자 제거
        json_str = re.sub(r'[\x00-\x1f\x7f]', '', json_str)
        # 이스케이프되지 않은 줄바꿈 처리
        json_str = json_str.replace('\n', '\\n')

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 파싱 실패: {e}") from e

    def _call_gemini(self, topic: str, source_text: str) -> Optional[dict]:
        """Gemini 2.0 Flash - 무료, 1순위"""
        try:
            import google.generativeai as genai

            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                print("  [WARN] GOOGLE_API_KEY 없음")
                return None

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")

            prompt = self._build_prompt(topic, source_text)

            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=1024,
                ),
            )

            result = self._parse_json_response(response.text)
            print("  [OK] Gemini 대본 생성 성공")
            return result

        except Exception as e:
            print(f"  [WARN] Gemini 실패: {e}")
            return None

    # v5.0: OpenAI 폴백 제거 — Gemini 2.0 Flash만 사용 (무료)

    def _quality_check(self, script_data: dict) -> int:
        """품질 채점 (100점 만점, 감점 방식) — 콘텐츠 다양성 + 정보 밀도 포함"""
        score = 100
        reasons = []

        text = script_data.get("tts_script", "")
        title = script_data.get("title", "")

        # 길이 체크 (250~350자 최적)
        if len(text) < 150:
            score -= 30
            reasons.append(f"너무 짧음 ({len(text)}자)")
        elif len(text) < 250:
            score -= 10
            reasons.append(f"짧음 ({len(text)}자)")
        elif len(text) > 400:
            score -= 15
            reasons.append(f"너무 김 ({len(text)}자)")

        # 문장 수 체크 (15~25문장 최적)
        sentences = [s.strip() for s in text.split("\n") if s.strip()]
        if len(sentences) < 12:
            score -= 15
            reasons.append(f"문장 부족 ({len(sentences)}문장)")
        elif len(sentences) > 30:
            score -= 10
            reasons.append(f"문장 과다 ({len(sentences)}문장)")

        # 문장 길이 다양성 체크 (전부 비슷한 길이면 감점)
        if sentences:
            lens = [len(s) for s in sentences]
            avg_len = sum(lens) / len(lens)
            variance = sum((l - avg_len) ** 2 for l in lens) / len(lens)
            if variance < 5:  # 분산이 너무 낮으면 = 전부 비슷한 길이
                score -= 10
                reasons.append("문장 길이가 너무 균일 (리듬감 부족)")

        # AI 슬롭 체크
        slop_found = 0
        for word in Config.AI_SLOP_WORDS:
            if word in text:
                slop_found += 1
        if slop_found:
            score -= min(slop_found * 10, 30)
            reasons.append(f"AI슬롭 {slop_found}개")

        # 실명 체크
        name_pattern = r"[김이박최정강조윤장임][가-힣]{1,2}(?:씨|님|이|가|을|를)"
        if re.search(name_pattern, text):
            score -= 20
            reasons.append("실명 포함 의심")

        # 금지어 체크
        banned = ["여러분", "경제학", "딜레마", "마무리하며", "정리하자면",
                  "알아보겠", "살펴보겠", "흥미롭", "놀라운"]
        for bw in banned:
            if bw in text:
                score -= 15
                reasons.append(f"금지어: '{bw}'")

        # 제목 길이
        if len(title) > 20:
            score -= 10
            reasons.append(f"제목 너무 김 ({len(title)}자)")

        # 이모지 체크
        if Config.EMOJI_PATTERN.search(title) or Config.EMOJI_PATTERN.search(text):
            score -= 10
            reasons.append("이모지 포함")

        # 자연스러움 체크 (구어체 흔적이 최소한 있는지)
        natural_markers = ["?", "!", "...", "근데", "진짜", "좀"]
        natural_count = sum(1 for m in natural_markers if m in text)
        if natural_count == 0:
            score -= 10
            reasons.append("너무 딱딱한 문체")

        # 반복 문장 체크 (동일 시작 문장 감점)
        starts = [s[:5] for s in sentences if len(s) >= 5]
        if starts:
            from collections import Counter
            start_counts = Counter(starts)
            repeated = sum(1 for c in start_counts.values() if c > 2)
            if repeated:
                score -= repeated * 5
                reasons.append(f"반복 패턴 {repeated}개")

        # ── 정확성 검증 (허위정보 탐지) ──
        # 1) 미확인 연구/전문가 인용 감점
        fake_authority = [
            "연구에 따르면", "연구결과", "연구팀", "연구진",
            "전문가에 따르면", "전문가들은", "관계자에 따르면",
            "통계에 따르면", "조사에 따르면",
        ]
        fake_count = sum(1 for fa in fake_authority if fa in text)
        if fake_count:
            score -= fake_count * 15
            reasons.append(f"미확인 인용 {fake_count}건")

        # 2) 위험 정보 패턴 (의학/법률/금융)
        danger_patterns = [
            r'\d+%\s*(확률|가능성|치료율|효과|감소)',
            r'(벌금|과태료|징역)\s*\d+',
            r'(투자|수익률?|이자율?)\s*\d+',
        ]
        for dp in danger_patterns:
            if re.search(dp, text):
                score -= 20
                reasons.append("위험정보 포함(의학/법률/금융)")
                break

        # 3) 가짜 경험담 패턴
        fake_exp = [
            "내 친구가", "내 동생이", "옆집 아저씨",
            "아는 형이", "직접 해봤는데",
        ]
        if not hasattr(self, '_source_text') or not self._source_text:
            # 소스 없는 대본에서 구체적 경험담 = 허위 가능성 높음
            exp_count = sum(1 for fe in fake_exp if fe in text)
            if exp_count:
                score -= exp_count * 10
                reasons.append(f"미확인 경험담 {exp_count}건")

        score = max(0, score)

        if reasons:
            print(f"  품질: {score}점 (감점: {', '.join(reasons)})")
        else:
            print(f"  품질: {score}점 - 완벽")

        return score

    def _post_process(self, script_data: dict) -> dict:
        """후처리: 볼드 제거 + AI 슬롭 교체 + 긴 문장 분리"""
        text = script_data.get("tts_script", "")

        # 볼드/이탤릭 마크다운 제거
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)

        # AI 슬롭 → 커뮤니티 말투로 교체 (대폭 확장)
        replacements = {
            "흥미롭": "재밌",
            "놀라운": "대박인",
            "충격적": "미친",
            "심층": "진짜",
            "탐구": "파헤치",
            "알아보겠": "얘기해볼",
            "살펴보겠": "봐볼",
            "주목할 만한": "개쩌는",
            "눈여겨볼": "봐야 할",
            "한편으로는": "근데",
            "매력적인": "끌리는",
            "인상적인": "쩌는",
            "독보적인": "개유일한",
            "혁신적인": "새로운",
            "획기적인": "대박인",
            "그뿐만 아니라": "게다가",
            "이에 더해": "그리고",
            "나아가": "더",
            "더불어": "그리고",
            "결론적으로": "결국",
            "정리하자면": "걍",
            "요약하자면": "걍",
            "되새겨 보": "생각해 보",
            "큰 교훈": "배운 거",
            "하겠습니다": "할게",
            "되겠습니다": "될 거야",
            "전문가들은": "사람들이",
            "귀추가 주목": "기대됨",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)

        # 이모지 제거
        text = Config.EMOJI_PATTERN.sub("", text)

        # 빈 줄 정리만 (인위적 문장 분리 하지 않음)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        text = "\n".join(lines)
        script_data["tts_script"] = text

        # 제목에서도 이모지 제거
        title = script_data.get("title", "")
        title = Config.EMOJI_PATTERN.sub("", title).strip()
        script_data["title"] = title

        return script_data

    def generate(self, topic: str, source_text: str) -> dict:
        """대본 생성 메인 - 품질 85점 이상까지 최대 3회 재시도"""
        print("\n" + "=" * 60)
        print("STEP 2: 대본 생성 (Gemini 2.0 Flash — 무료)")
        print("=" * 60)

        # 정확성 검증용 소스 저장
        self._source_text = source_text

        if not source_text:
            print("  [WARN] 원글 본문 없음 — 주제만으로 생성")

        best_result = None
        best_score = 0

        for attempt in range(Config.MAX_RETRY):
            print(f"\n  시도 {attempt + 1}/{Config.MAX_RETRY}")

            result = self._call_gemini(topic, source_text)

            if result is None:
                print("  [ERROR] Gemini 실패 — 재시도")
                continue

            result = self._post_process(result)
            score = self._quality_check(result)

            if score > best_score:
                best_score = score
                best_result = result
                best_result["quality_score"] = score

            if score >= Config.MIN_QUALITY_SCORE:
                result["quality_score"] = score
                print(f"\n  [OK] 대본 확정! (점수: {score})")
                print(f"  제목: {result.get('title', 'N/A')}")
                print(f"  길이: {len(result.get('tts_script', ''))}자")
                return result

            print(f"  [FAIL] {score}점 < {Config.MIN_QUALITY_SCORE}점 -> 재생성")

        # graceful fallback
        if best_result and best_score > 0 and len(best_result.get("tts_script", "")) >= 100:
            print(f"\n  [WARN] {Config.MAX_RETRY}회 미달 -> 최선의 결과 사용 ({best_score}점)")
            return best_result

        raise RuntimeError("대본 생성 실패: 3회 모두 품질 미달")


# ============================================================================
# STEP 3: TTS 생성 (edge-tts 전용 — 무료, 단어별 타이밍)
# ============================================================================
class TTSEngine:
    """
    v5.0: edge-tts 전용 TTS (무료, WordBoundary 타이밍 지원)
    유료 폴백(ElevenLabs/OpenAI) 제거 — API 비용 0원
    """

    async def _edge_tts(self, text: str, output_mp3: str) -> list[dict]:
        """edge-tts로 음성 생성 + 단어별 타이밍 수집"""
        import edge_tts

        word_timings = []
        communicate = edge_tts.Communicate(
            text=text,
            voice=Config.TTS_VOICE,
            rate=Config.TTS_RATE,
            pitch=Config.TTS_PITCH,
        )

        with open(output_mp3, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    word_timings.append({
                        "word": chunk["text"],
                        "start_ms": chunk["offset"] // 10000,
                        "end_ms": (chunk["offset"] + chunk["duration"]) // 10000,
                    })

        return word_timings

    # v5.0: ElevenLabs / OpenAI TTS 제거 — edge-tts만 사용 (무료)

    async def generate_with_timing(self, text: str, output_mp3: str) -> list[dict]:
        """edge-tts 전용 TTS (무료, 단어별 타이밍 지원)"""
        try:
            word_timings = await self._edge_tts(text, output_mp3)
            if os.path.exists(output_mp3) and os.path.getsize(output_mp3) > 1000:
                print(f"  [OK] edge-tts 성공: {len(word_timings)}개 타이밍")
                return word_timings
            raise RuntimeError("edge-tts 출력 파일 없음 또는 비정상")
        except Exception as e:
            print(f"  [ERROR] edge-tts 실패: {e}")
            raise RuntimeError(f"TTS 실패 (edge-tts): {e}")

    def generate(self, text: str, output_mp3: str) -> list[dict]:
        """동기 래퍼"""
        print("\n" + "=" * 60)
        print("STEP 3: TTS 생성 (edge-tts — 무료)")
        print("=" * 60)
        return asyncio.run(self.generate_with_timing(text, output_mp3))


# ============================================================================
# STEP 3.5: 오디오 마스터링 (2-pass loudnorm, -14 LUFS)
# ============================================================================
def master_audio(input_path: str, output_path: str) -> str:
    """오디오 볼륨 정규화 + EQ. 2-pass loudnorm."""
    ffmpeg = _find_ffmpeg_exe()
    try:
        measure_cmd = [
            ffmpeg, "-i", input_path,
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-",
        ]
        result = subprocess.run(measure_cmd, capture_output=True, timeout=60)
        stderr_text = result.stderr.decode("utf-8", errors="ignore")

        json_matches = list(
            re.finditer(r'\{[^{}]*"input_i"[^{}]*\}', stderr_text, re.DOTALL)
        )
        if not json_matches:
            raise ValueError("loudnorm JSON 파싱 실패")

        measured = json.loads(json_matches[-1].group(0))
        m_I = measured.get("input_i", "-14.0")
        m_TP = measured.get("input_tp", "-1.5")
        m_LRA = measured.get("input_lra", "11.0")
        m_thresh = measured.get("input_thresh", "-24.0")

        normalize_cmd = [
            ffmpeg, "-y", "-i", input_path,
            "-af", (
                "highpass=f=80,"
                "acompressor=threshold=-20dB:ratio=4:attack=5:release=50,"
                f"loudnorm=I=-14:TP=-1.5:LRA=11:"
                f"measured_I={m_I}:measured_TP={m_TP}:"
                f"measured_LRA={m_LRA}:measured_thresh={m_thresh}:"
                f"linear=true"
            ),
            "-ar", "44100", "-ac", "1",
            output_path,
        ]
        subprocess.run(normalize_cmd, capture_output=True, check=True, timeout=120)
        print("  [OK] 마스터링 완료 (2-pass, -14 LUFS)")
        return output_path

    except Exception as e:
        try:
            fallback_cmd = [
                ffmpeg, "-y", "-i", input_path,
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-ar", "44100", "-ac", "1",
                output_path,
            ]
            subprocess.run(fallback_cmd, capture_output=True, check=True, timeout=120)
            print("  [OK] 마스터링 완료 (1-pass 폴백)")
            return output_path
        except Exception as e:
            logger.warning(f"마스터링 폴백 실패: {e}")
            print(f"  [WARN] 마스터링 실패 - 원본 사용: {e}")
            return input_path


def adjust_audio_speed(audio_path: str, speed_factor: float, output_path: str) -> str:
    """FFmpeg atempo로 오디오 속도 조절."""
    speed_factor = max(0.8, min(1.25, speed_factor))
    if abs(speed_factor - 1.0) < 0.01:
        return audio_path

    ffmpeg = _find_ffmpeg_exe()
    try:
        cmd = [
            ffmpeg, "-y", "-i", audio_path,
            "-filter:a", f"atempo={speed_factor:.4f}",
            "-vn", output_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        print(f"  [OK] 속도 조절: x{speed_factor:.2f}")
        return output_path
    except Exception as e:
        print(f"  [WARN] 속도 조절 실패: {e}")
        return audio_path


# ============================================================================
# STEP 4: 단어별 하이라이트 자막 (ASS 형식)
# ============================================================================
class SubtitleGenerator:
    """ASS 형식 단어별 하이라이트 (현재=노란, 나머지=흰)"""

    def _group_words_into_lines(
        self, word_timings: list[dict], max_chars: int = 15
    ) -> list[dict]:
        lines = []
        current_line = []
        current_chars = 0

        for wt in word_timings:
            word = wt["word"].strip()
            if not word:
                continue

            if current_chars + len(word) > max_chars and current_line:
                lines.append({
                    "words": current_line.copy(),
                    "start_ms": current_line[0]["start_ms"],
                    "end_ms": current_line[-1]["end_ms"],
                })
                current_line = []
                current_chars = 0

            current_line.append(wt)
            current_chars += len(word) + 1

        if current_line:
            lines.append({
                "words": current_line,
                "start_ms": current_line[0]["start_ms"],
                "end_ms": current_line[-1]["end_ms"],
            })

        return lines

    def _ms_to_ass_time(self, ms: int) -> str:
        h = ms // 3600000
        m = (ms % 3600000) // 60000
        s = (ms % 60000) // 1000
        cs = (ms % 1000) // 10
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def _get_ass_header(self) -> str:
        """ASS header"""
        return f"""[Script Info]
Title: youshorts subtitles
ScriptType: v4.00+
PlayResX: {Config.WIDTH}
PlayResY: {Config.HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{Config.SUBTITLE_FONT},{Config.SUBTITLE_SIZE},{Config.SUBTITLE_COLOR_NORMAL},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{Config.SUBTITLE_OUTLINE},{Config.SUBTITLE_SHADOW},2,40,40,{Config.SUBTITLE_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


    def generate_ass(self, word_timings: list[dict], output_ass: str) -> str:
        """ASS 자막 파일 생성 - 단어별 하이라이트"""
        lines = self._group_words_into_lines(word_timings)

        ass_content = self._get_ass_header()

        for line in lines:
            words_in_line = line["words"]
            for wi, current_word in enumerate(words_in_line):
                start = self._ms_to_ass_time(current_word["start_ms"])
                if wi + 1 < len(words_in_line):
                    end = self._ms_to_ass_time(words_in_line[wi + 1]["start_ms"])
                else:
                    end = self._ms_to_ass_time(current_word["end_ms"])

                text_parts = []
                for wj, w in enumerate(words_in_line):
                    word_text = w["word"].strip()
                    if not word_text:
                        continue
                    if wj == wi:
                        text_parts.append(
                            f"{{\\c{Config.SUBTITLE_COLOR_HIGHLIGHT}"
                            f"\\b1}}{word_text}{{\\r}}"
                        )
                    else:
                        text_parts.append(
                            f"{{\\c{Config.SUBTITLE_COLOR_NORMAL}"
                            f"}}{word_text}{{\\r}}"
                        )

                dialogue_text = " ".join(text_parts)
                ass_content += (
                    f"Dialogue: 0,{start},{end},Default,,0,0,0,,"
                    f"{dialogue_text}\n"
                )

        with open(output_ass, "w", encoding="utf-8") as f:
            f.write(ass_content)

        print(f"  [OK] ASS 자막 생성: {output_ass}")
        print(f"  {len(lines)}개 줄, 단어별 하이라이트 적용")
        return output_ass

    def generate_ass_from_chunks(
        self, text: str, total_duration: float, output_ass: str
    ) -> str:
        """WordBoundary 없을 때 청크 기반 폴백 자막"""
        sentences = re.split(r'(?<=[.?!~])\s*|(?<=ㅋ)\s+|(?<=ㅎ)\s+', text)
        chunks = [s.strip() for s in sentences if s.strip()]

        if not chunks:
            chunks = [text[i:i+15] for i in range(0, len(text), 15)]

        chunk_duration = total_duration / len(chunks) if chunks else 3.0

        ass_content = self._get_ass_header()

        for i, chunk in enumerate(chunks):
            start_ms = int(i * chunk_duration * 1000)
            end_ms = int((i + 1) * chunk_duration * 1000)
            start = self._ms_to_ass_time(start_ms)
            end = self._ms_to_ass_time(end_ms)

            highlighted = (
                f"{{\\c{Config.SUBTITLE_COLOR_HIGHLIGHT}\\b1}}"
                f"{chunk}{{\\r}}"
            )

            if i + 1 < len(chunks):
                next_text = (
                    f"\\N{{\\c{Config.SUBTITLE_COLOR_NORMAL}}}"
                    f"{chunks[i+1]}{{\\r}}"
                )
            else:
                next_text = ""

            ass_content += (
                f"Dialogue: 0,{start},{end},Default,,0,0,0,,"
                f"{highlighted}{next_text}\n"
            )

        with open(output_ass, "w", encoding="utf-8") as f:
            f.write(ass_content)

        print(f"  [OK] ASS 하이라이트 자막: {output_ass}")
        print(f"  {len(chunks)}개 청크, 현재=노란/다음=흰색")
        return output_ass


# ============================================================================
# STEP 5: 배경 영상 + BGM + 렌더링
# ============================================================================
class VideoRenderer:
    """FFmpeg CLI로 배경+TTS+BGM+자막 합성"""

    def _find_ffmpeg(self) -> str:
        return _find_ffmpeg_exe()

    def _find_ffprobe(self) -> str:
        return _find_ffprobe_exe()

    def _resolve_bg_mode(self, topic: str) -> str:
        """주제 키워드 → 배경 모드 결정 (gameplay / gradient)"""
        for mode, keywords in Config.TOPIC_BG_MAP.items():
            if any(kw in topic for kw in keywords):
                return mode
        return "gradient"  # 기본값

    def _resolve_gradient_colors(self, topic: str) -> tuple[str, str]:
        """주제 키워드 → 그라디언트 색상 선택"""
        for category, keywords in Config.GRADIENT_TOPIC_MAP.items():
            if any(kw in topic for kw in keywords):
                return Config.GRADIENT_COLORS[category]
        return Config.GRADIENT_COLORS["default"]

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        """#RRGGBB → (R, G, B)"""
        h = hex_color.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def _generate_gradient_bg(self, topic: str) -> Optional[str]:
        """FFmpeg geq 필터로 실제 세로 그라디언트 배경 영상 생성 (65초)"""
        c0, c1 = self._resolve_gradient_colors(topic)
        r0, g0, b0 = self._hex_to_rgb(c0)
        r1, g1, b1 = self._hex_to_rgb(c1)

        temp_dir = Config.BASE_DIR / "temp"
        temp_dir.mkdir(exist_ok=True)
        gen_mp4 = str(temp_dir / "gradient_bg.mp4")
        ffmpeg = self._find_ffmpeg()
        dur = 65
        W, H, FPS = Config.WIDTH, Config.HEIGHT, Config.FPS

        # geq 필터: 상단(c0) → 하단(c1) 세로 그라디언트 + 노이즈로 미세 움직임
        # Y좌표(0=상단, H=하단) 기반 선형 보간
        geq_r = f"{r0}+(({r1}-{r0})*Y/{H})"
        geq_g = f"{g0}+(({g1}-{g0})*Y/{H})"
        geq_b = f"{b0}+(({b1}-{b0})*Y/{H})"

        lavfi = (
            f"color=c=black:s={W}x{H}:r={FPS}:d={dur},"
            f"geq=r='{geq_r}':g='{geq_g}':b='{geq_b}',"
            f"noise=alls=15:allf=t+u"
        )

        try:
            cmd = [
                ffmpeg, "-y",
                "-f", "lavfi", "-i", lavfi,
                "-t", str(dur),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-pix_fmt", "yuv420p",
                gen_mp4,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode == 0 and os.path.exists(gen_mp4):
                size_mb = os.path.getsize(gen_mp4) / (1024 * 1024)
                print(f"  [OK] 그라디언트 배경 생성 ({c0}→{c1}, {size_mb:.1f}MB)")
                return gen_mp4
            else:
                stderr = result.stderr.decode("utf-8", errors="ignore")[-300:]
                print(f"  [WARN] 그라디언트 생성 실패: {stderr[:200]}")
        except Exception as e:
            print(f"  [WARN] 그라디언트 생성 실패: {e}")
        return None

    def _get_background_video(self, topic: str = "") -> Optional[str]:
        """주제 기반 배경 선택: gameplay→실제영상 / gradient→자동생성"""
        bg_mode = self._resolve_bg_mode(topic)
        print(f"  배경 모드: {bg_mode} (주제: {topic[:30]})")

        # gameplay 모드: 실제 배경 영상 사용
        if bg_mode == "gameplay":
            bg_dir = Config.BG_DIR
            videos = []
            if bg_dir.exists():
                videos = list(bg_dir.rglob("*.mp4"))
            if videos:
                selected = random.choice(videos)
                print(f"  배경 선택: {selected.name}")
                return str(selected)
            print("  [INFO] gameplay 영상 없음 → 그라디언트 폴백")

        # gradient 모드 (또는 gameplay 폴백)
        result = self._generate_gradient_bg(topic)
        if result:
            return result

        # 최종 폴백: None → render()에서 검정 단색
        return None

    def _get_random_bgm(self) -> Optional[str]:
        bgm_dir = Config.BGM_DIR
        if not bgm_dir.exists():
            return None
        bgms = list(bgm_dir.glob("*.mp3"))
        if not bgms:
            return None
        return str(random.choice(bgms))

    def _get_video_duration(self, video_path: str) -> float:
        # 1차: ffprobe
        try:
            result = subprocess.run(
                [self._find_ffprobe(), "-v", "quiet",
                 "-show_entries", "format=duration",
                 "-of", "csv=p=0", video_path],
                capture_output=True, text=True, timeout=10,
            )
            val = result.stdout.strip()
            if val:
                return float(val)
        except (ValueError, subprocess.SubprocessError, OSError) as e:
            logger.warning(f"ffprobe 듀레이션 확인 실패: {e}")
        # 2차: ffmpeg -i stderr에서 Duration 파싱
        try:
            result = subprocess.run(
                [self._find_ffmpeg(), "-i", video_path],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
            if m:
                h, mi, s, cs = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                return h * 3600 + mi * 60 + s + cs / 100
        except (ValueError, subprocess.SubprocessError, OSError) as e:
            logger.warning(f"ffmpeg 듀레이션 파싱 실패: {e}")
        return 60  # 안전한 기본값

    def render(self, tts_mp3: str, ass_subtitle: str, output_mp4: str,
               topic: str = "", title: str = "") -> str:
        print("\n" + "=" * 60)
        print("STEP 5: FFmpeg 렌더링")
        print("=" * 60)

        ffmpeg = self._find_ffmpeg()
        bg_video = self._get_background_video(topic=topic)
        bgm_mp3 = self._get_random_bgm()

        tts_duration = self._get_video_duration(tts_mp3)
        target_duration = min(tts_duration + 1.5, Config.MAX_DURATION)

        # ASS 파일을 상대경로 temp/sub.ass에 복사 (Windows 호환)
        import shutil
        temp_dir = Config.BASE_DIR / "temp"
        temp_dir.mkdir(exist_ok=True)
        temp_ass = str(temp_dir / "sub.ass")
        shutil.copy2(ass_subtitle, temp_ass)

        cmd = [ffmpeg, "-y"]

        if bg_video:
            bg_duration = self._get_video_duration(bg_video)
            # 생성된 배경(65초)이면 duration 신뢰 불가 → 0부터 시작
            if bg_duration > target_duration + 10:
                max_start = max(0, bg_duration - target_duration - 5)
                random_start = random.uniform(0, max_start)
            else:
                random_start = 0
            cmd.extend(["-ss", f"{random_start:.1f}", "-i", bg_video])
            print(f"  렌더링 시작...")
            print(f"  목표 길이: {target_duration:.1f}초")
            print(f"  배경 랜덤 시작: {random_start:.1f}초")
        else:
            cmd.extend([
                "-f", "lavfi", "-i",
                f"color=c=black:s={Config.WIDTH}x{Config.HEIGHT}:"
                f"r={Config.FPS}:d={target_duration}",
            ])

        cmd.extend(["-i", tts_mp3])

        input_idx_bgm = None
        if bgm_mp3:
            cmd.extend(["-i", bgm_mp3])
            input_idx_bgm = 2

        video_filters = [
            "crop=ih*9/16:ih:(iw-ih*9/16)/2:0",
            f"scale={Config.WIDTH}:{Config.HEIGHT}",
        ]

        if os.path.exists(temp_ass):
            video_filters.append("ass=temp/sub.ass")

        # ── 상단 제목 바 (drawbox + drawtext via textfile) ──
        display_title = (title or topic or "")[:25]
        if display_title:
            # 한글 → textfile 방식 (FFmpeg text= 한글 깨짐 방지)
            title_txt = str(temp_dir / "title.txt")
            with open(title_txt, "w", encoding="utf-8") as tf:
                tf.write(display_title)
            # Windows 경로 → FFmpeg 호환 (C\:/path)
            fontpath = "C\\:/Windows/Fonts/malgunbd.ttf"
            titlepath = title_txt.replace("\\", "/").replace("C:/", "C\\:/")
            video_filters.append(
                "drawbox=x=0:y=60:w=iw:h=130:color=black@0.5:t=fill"
            )
            video_filters.append(
                f"drawtext=fontfile='{fontpath}'"
                f":textfile='{titlepath}'"
                f":fontcolor=white:fontsize=30"
                f":x=(w-text_w)/2:y=105"
            )
            print(f"  상단 제목 바: '{display_title}'")

        video_filter_str = ",".join(video_filters)

        if input_idx_bgm is not None:
            audio_filter = (
                f"[{input_idx_bgm}:a]volume=0.15,aloop=loop=-1:size=2e+09[bgm];"
                f"[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            cmd.extend([
                "-filter_complex",
                f"[0:v]{video_filter_str}[vout];{audio_filter}",
                "-map", "[vout]", "-map", "[aout]",
            ])
        else:
            cmd.extend([
                "-vf", video_filter_str,
                "-map", "0:v", "-map", "1:a",
            ])

        cmd.extend([
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{target_duration:.1f}", "-shortest",
            output_mp4,
        ])

        result = subprocess.run(cmd, capture_output=True, timeout=300)

        if result.returncode == 0 and os.path.exists(output_mp4):
            size_mb = os.path.getsize(output_mp4) / (1024 * 1024)
            print(f"  [OK] 렌더링 완료: {output_mp4}")
            print(f"  파일 크기: {size_mb:.1f}MB")
            return output_mp4
        else:
            stderr = result.stderr.decode("utf-8", errors="ignore")[-500:]
            print(f"  [ERROR] 렌더링 실패:\n  {stderr}")
            raise RuntimeError("FFmpeg 렌더링 실패")


# ============================================================================
# STEP 6: 이력 저장 (중복 방지)
# ============================================================================
class HistoryManager:
    """history.json으로 중복 방지 (Jaccard 유사도)"""

    def __init__(self):
        self.history_file = Config.HISTORY_FILE
        self._ensure_file()

    def _ensure_file(self):
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_file.exists():
            self.history_file.write_text("[]", encoding="utf-8")

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.history_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"히스토리 로드 실패: {e}")
            return []

    def is_duplicate(self, topic: str) -> bool:
        history = self._load()
        for h in history:
            prev_topic = h.get("topic", "")
            set_a = set(topic)
            set_b = set(prev_topic)
            if not set_a or not set_b:
                continue
            overlap = len(set_a & set_b) / len(set_a | set_b)
            if overlap > 0.8:
                return True
        return False

    def save(self, topic: str, title: str, output_file: str):
        history = self._load()
        history.append({
            "topic": topic,
            "title": title,
            "file": output_file,
            "date": datetime.now().isoformat(),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        self.history_file.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  [OK] 이력 저장 완료 (총 {len(history)}건)")


# ============================================================================
# STEP 7: 메타데이터 생성 (해시태그 + SEO 태그)
# ============================================================================
class MetadataGenerator:
    BASE_HASHTAGS = ["#shorts", "#쇼츠", "#숏츠"]

    @staticmethod
    def generate_hashtags(script_data: dict) -> list[str]:
        tags = list(MetadataGenerator.BASE_HASHTAGS)
        for tag in script_data.get("tags", []):
            clean = tag.strip().replace(" ", "")
            if not clean.startswith("#"):
                clean = f"#{clean}"
            if clean not in tags:
                tags.append(clean)
        title = script_data.get("title", "")
        for word in re.findall(r'[가-힣a-zA-Z]{2,}', title):
            t = f"#{word}"
            if t not in tags and len(tags) < 15:
                tags.append(t)
        return tags[:15]

    @staticmethod
    def generate_seo_tags(script_data: dict) -> list[str]:
        seo_tags = ["숏츠", "쇼츠", "shorts", "한국", "실화"]
        for tag in script_data.get("tags", []):
            clean = tag.strip().lstrip("#")
            if clean and clean not in seo_tags:
                seo_tags.append(clean)
        title = script_data.get("title", "")
        for word in re.findall(r'[가-힣]{2,}', title):
            if word not in seo_tags and len(seo_tags) < 20:
                seo_tags.append(word)
        return seo_tags[:20]

    @staticmethod
    def generate(script_data: dict) -> dict:
        title = script_data.get("title", "쇼츠")[:46]
        if "#Shorts" not in title:
            title = f"{title} #Shorts"
        hashtags = MetadataGenerator.generate_hashtags(script_data)
        seo_tags = MetadataGenerator.generate_seo_tags(script_data)
        desc_parts = [
            script_data.get("title", ""), "",
            " ".join(hashtags), "", "---",
            "이 영상은 AI 도구를 활용하여 제작되었습니다.",
        ]
        return {
            "title": title,
            "description": "\n".join(desc_parts),
            "tags": seo_tags,
            "hashtags": hashtags,
            "category": "22",
        }


# ============================================================================
# STEP 8: YouTube 업로드 (OAuth2)
# ============================================================================
class YouTubeUploader:
    """YouTube Shorts 업로더 — OAuth2 인증 + 3회 재시도"""

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    MAX_RETRIES = 3

    def __init__(self):
        self.client_id = os.getenv("YOUTUBE_CLIENT_ID", "")
        self.client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "")
        self.token_path = str(Config.BASE_DIR / "data" / "youtube_token.json")
        self.service = None
        self.available = bool(self.client_id and self.client_secret)

    def authenticate(self) -> bool:
        if not self.available:
            print("  [WARN] YOUTUBE_CLIENT_ID/SECRET 미설정 -> 업로드 불가")
            return False

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None
            if os.path.exists(self.token_path):
                creds = Credentials.from_authorized_user_file(self.token_path, self.SCOPES)

            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning(f"YouTube 토큰 갱신 실패: {e}")
                    creds = None

            if not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_config(
                    {"installed": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }},
                    self.SCOPES,
                )
                creds = flow.run_local_server(port=0)
                os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
                with open(self.token_path, "w") as f:
                    f.write(creds.to_json())

            self.service = build("youtube", "v3", credentials=creds)
            return True

        except ImportError:
            print("  [WARN] google-auth-oauthlib 미설치")
            return False
        except Exception as e:
            print(f"  [ERROR] YouTube 인증 실패: {e}")
            return False

    def _do_upload(self, mp4_path: str, body: dict) -> Optional[str]:
        title = body["snippet"]["title"]
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                from googleapiclient.http import MediaFileUpload
                media = MediaFileUpload(
                    mp4_path, mimetype="video/mp4", resumable=True,
                    chunksize=10 * 1024 * 1024,
                )
                request = self.service.videos().insert(
                    part="snippet,status", body=body, media_body=media,
                )
                print(f"  업로드 시작: '{title}'")
                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        print(f"  업로드: {int(status.progress() * 100)}%")
                video_id = response["id"]
                url = f"https://youtube.com/shorts/{video_id}"
                print(f"  [OK] 업로드 완료: {url}")
                return url
            except Exception as e:
                print(f"  [WARN] 업로드 실패 ({attempt}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(10)
        return None

    def upload(self, mp4_path: str, metadata: dict, privacy: str = "public") -> Optional[str]:
        if not self.service and not self.authenticate():
            return None
        title = metadata.get("title", "쇼츠")[:100]
        body = {
            "snippet": {
                "title": title,
                "description": metadata.get("description", ""),
                "tags": metadata.get("tags", [])[:20],
                "categoryId": "22",
                "defaultLanguage": "ko",
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }
        return self._do_upload(mp4_path, body)

    def upload_scheduled(self, mp4_path: str, metadata: dict,
                         video_index: int = 0) -> Optional[str]:
        if not self.service and not self.authenticate():
            return None
        tomorrow_9am = (
            datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        )
        publish_time = tomorrow_9am + timedelta(hours=4 * video_index)
        publish_at = publish_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        print(f"  예약 공개: {publish_at} (영상 #{video_index + 1})")
        title = metadata.get("title", "쇼츠")[:100]
        body = {
            "snippet": {
                "title": title,
                "description": metadata.get("description", ""),
                "tags": metadata.get("tags", [])[:20],
                "categoryId": "22",
                "defaultLanguage": "ko",
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at,
                "selfDeclaredMadeForKids": False,
            },
        }
        return self._do_upload(mp4_path, body)


# ============================================================================
# 파일 정리 유틸
# ============================================================================
class FileCleaner:
    MIN_MP4_SIZE = 5 * 1024 * 1024

    @staticmethod
    def clean_output(output_dir: str = None):
        if output_dir is None:
            output_dir = str(Config.OUTPUT_DIR)
        cleaned = 0
        for root, dirs, files in os.walk(output_dir):
            for f in files:
                fp = os.path.join(root, f)
                if f.endswith(".mp4") and os.path.getsize(fp) < FileCleaner.MIN_MP4_SIZE:
                    os.remove(fp)
                    cleaned += 1
                    print(f"  삭제 (비정상): {f}")
        temp_dir = os.path.join(str(Config.BASE_DIR), "temp")
        if os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        if cleaned:
            print(f"  [OK] {cleaned}개 비정상 파일 정리")


# ============================================================================
# APIFY 크롤링 강화
# ============================================================================
class ApifyCrawler:
    SITES = [
        ("에펨코리아", "https://www.fmkorea.com/index.php?mid=humor_best"),
        ("인스티즈", "https://www.instiz.net/pt"),
        ("더쿠", "https://theqoo.net/hot"),
        ("클리앙", "https://www.clien.net/service/board/park"),
        ("루리웹", "https://bbs.ruliweb.com/community/board/300143/best"),
    ]

    @staticmethod
    def crawl() -> list[dict]:
        import requests
        token = os.getenv("APIFY_TOKEN", "")
        if not token:
            return []
        results = []
        for name, url in ApifyCrawler.SITES:
            try:
                resp = requests.post(
                    f"https://api.apify.com/v2/acts/apify~cheerio-scraper/runs?token={token}",
                    json={
                        "startUrls": [{"url": url}],
                        "maxRequestsPerCrawl": 20,
                        "pageFunction": """async function pageFunction(context) {
                            const $ = context.jQuery;
                            const results = [];
                            $('a').each((i, el) => {
                                const title = $(el).text().trim();
                                const href = $(el).attr('href') || '';
                                if (title.length > 10 && title.length < 80) {
                                    results.push({ title, url: href });
                                }
                            });
                            return results.slice(0, 10);
                        }""",
                    },
                    timeout=30,
                )
                if resp.status_code == 201:
                    run_id = resp.json().get("data", {}).get("id", "")
                    for _ in range(6):
                        time.sleep(5)
                        status_resp = requests.get(
                            f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items?token={token}",
                            timeout=10,
                        )
                        if status_resp.status_code == 200:
                            items = status_resp.json()
                            for i, item in enumerate(items[:10]):
                                if isinstance(item, dict) and "title" in item:
                                    results.append({
                                        "keyword": item["title"],
                                        "source": f"apify_{name}",
                                        "score": (10 - i) * 4000,
                                    })
                            break
                print(f"  [OK] APIFY {name}: {len([r for r in results if name in r.get('source', '')])}개")
            except Exception as e:
                print(f"  [WARN] APIFY {name} 실패: {e}")
        return results


# ============================================================================
# 임시 파일 정리
# ============================================================================
def cleanup_temp_files(work_dir: Path):
    temp_exts = {".ass", ".json"}
    removed = 0
    for f in work_dir.iterdir():
        if f.is_file() and f.suffix in temp_exts:
            if f.name == "script.json":
                continue
            try:
                f.unlink()
                removed += 1
            except OSError as e:
                logger.warning(f"파일 삭제 실패: {e}")
    if removed:
        print(f"  [OK] 임시 파일 {removed}개 정리")


# ============================================================================
# 메인 파이프라인 - 영상 1개 완벽 생성
# ============================================================================
def make_one_perfect_short(
    upload: bool = False,
    scheduled: bool = False,
    video_index: int = 0,
    keep_temp: bool = True,
    topic: Optional[str] = None,
):
    """
    youshorts 올인원 영상 1개 생성 파이프라인
    1→1.5→2→3→3.5→4→5→6→7→8(선택)
    """
    start_time = time.time()

    print("\n" + "=" * 60)
    print("  youshorts - 완벽한 영상 1개 생성 시작")
    print("=" * 60)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = Config.OUTPUT_DIR / f"session_{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # ── STEP 1: 주제 선정 ──
    history = HistoryManager()

    if topic:
        selected_topic = topic
        selected_trend = {"keyword": topic, "source": "manual"}
        print(f"\n  수동 지정 주제: {selected_topic}")
    else:
        trend_collector = TrendCollector()
        trends = trend_collector.collect_all()

        if not trends:
            print("\n  [WARN] 트렌드 수집 실패 -> 폴백 주제")
            fallback_topics = [
                "요즘 가장 핫한 유튜브 밈 총정리",
                "역대급 반전 있는 영화 3편",
                "외국인이 한국 와서 충격받은 것들",
                "한국에서만 가능한 것들 TOP5",
                "20대가 모르면 손해인 앱 추천",
                "직장인 퇴근 후 루틴 현실",
            ]
            trends = [{"keyword": random.choice(fallback_topics), "score": 0}]

        selected_trend = None
        for t in trends:
            if not history.is_duplicate(t["keyword"]):
                selected_trend = t
                break
        if not selected_trend:
            selected_trend = trends[0]

        selected_topic = selected_trend["keyword"]
        print(f"\n  선정된 주제: {selected_topic}")

    # ── STEP 1.5: 본문 크롤링 + 뉴스 보강 ──
    source_text = ""
    post_url = selected_trend.get("url", "") if isinstance(selected_trend, dict) else ""
    if post_url and "community_" in str(selected_trend.get("source", "")):
        print(f"\n  본문 크롤링 시도: {post_url[:80]}...")
        if not topic:  # trend_collector 있을 때만
            source_text = trend_collector.fetch_post_body(post_url)
        if source_text:
            print(f"  [OK] 본문 수집: {len(source_text)}자")
        else:
            print("  [WARN] 본문 수집 실패 — 뉴스로 보강")

    if not source_text:
        news_collector = NewsCollector()
        news = news_collector.collect_news(selected_topic)
        if news:
            source_text = "\n".join(
                [f"- {n['title']}: {n.get('desc', '')}" for n in news[:5]]
            )

    # ── STEP 2: 대본 생성 ──
    script_gen = ScriptGenerator()
    script_data = script_gen.generate(selected_topic, source_text)

    script_file = work_dir / "script.json"
    script_file.write_text(
        json.dumps(script_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ── STEP 3: TTS 생성 ──
    tts_engine = TTSEngine()
    tts_mp3 = str(work_dir / "tts.mp3")
    word_timings = tts_engine.generate(script_data["tts_script"], tts_mp3)

    timing_file = work_dir / "word_timings.json"
    timing_file.write_text(
        json.dumps(word_timings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ── STEP 3.5: 오디오 마스터링 ──
    print("\n" + "=" * 60)
    print("STEP 3.5: 오디오 마스터링 (-14 LUFS)")
    print("=" * 60)

    mastered_mp3 = str(work_dir / "tts_mastered.mp3")
    tts_mp3 = master_audio(tts_mp3, mastered_mp3)

    try:
        ffprobe = _find_ffprobe_exe()
        probe = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", tts_mp3],
            capture_output=True, text=True, timeout=10,
        )
        try:
            tts_duration = float(probe.stdout.strip())
        except (ValueError, TypeError):
            tts_duration = 40.0
        if tts_duration > Config.MAX_DURATION:
            speed = tts_duration / Config.MAX_DURATION
            adjusted_mp3 = str(work_dir / "tts_adjusted.mp3")
            tts_mp3 = adjust_audio_speed(tts_mp3, speed, adjusted_mp3)
    except (ValueError, subprocess.SubprocessError, OSError) as e:
        logger.warning(f"TTS 듀레이션 확인 실패: {e}")
        tts_duration = 40.0

    # ── STEP 4: 자막 생성 ──
    print("\n" + "=" * 60)
    print("STEP 4: 단어별 하이라이트 자막 (ASS)")
    print("=" * 60)

    subtitle_gen = SubtitleGenerator()
    ass_file = str(work_dir / "subtitles.ass")

    if word_timings:
        subtitle_gen.generate_ass(word_timings, ass_file)
    else:
        _dur = 40.0
        try:
            _r = VideoRenderer()
            _dur = _r._get_video_duration(tts_mp3)
        except Exception as e:
            logger.warning(f"듀레이션 확인 실패: {e}")
        subtitle_gen.generate_ass_from_chunks(
            script_data["tts_script"], _dur, ass_file
        )

    # ── STEP 5: 렌더링 ──
    safe_title = re.sub(r'[\\/*?:"<>|()!\[\]{}]', '', script_data["title"])
    safe_title = safe_title.replace(" ", "_")[:30]
    output_filename = f"shorts_{safe_title}_{timestamp}.mp4"
    output_mp4 = str(work_dir / output_filename)

    renderer = VideoRenderer()
    final_video = renderer.render(
        tts_mp3, ass_file, output_mp4,
        topic=selected_topic, title=script_data.get("title", ""),
    )

    # ── STEP 6: 이력 저장 ──
    print("\n" + "=" * 60)
    print("STEP 6: 이력 저장")
    print("=" * 60)
    history.save(selected_topic, script_data["title"], final_video)

    # ── STEP 7: 메타데이터 ──
    metadata = MetadataGenerator.generate(script_data)

    # ── STEP 8: YouTube 업로드 (선택) ──
    upload_url = None
    if upload:
        print("\n" + "=" * 60)
        mode = "예약 업로드" if scheduled else "즉시 업로드"
        print(f"STEP 8: YouTube {mode}")
        print("=" * 60)
        uploader = YouTubeUploader()
        if scheduled:
            upload_url = uploader.upload_scheduled(final_video, metadata, video_index)
        else:
            upload_url = uploader.upload(final_video, metadata)

    if not keep_temp:
        cleanup_temp_files(work_dir)

    elapsed = time.time() - start_time

    print("\n" + "=" * 60)
    print(f"  영상 생성 완료!")
    print(f"  파일: {final_video}")
    print(f"  제목: {script_data.get('title', 'Unknown')}")
    print(f"  품질: {script_data.get('quality_score', 'N/A')}점")
    print(f"  소요시간: {elapsed:.1f}초")
    print(f"  태그: {', '.join(script_data.get('tags', []))}")
    if upload_url:
        print(f"  YouTube: {upload_url}")
    print("=" * 60)

    return {
        "video": final_video,
        "title": script_data["title"],
        "description": metadata.get("description", ""),
        "tags": metadata.get("tags", []),
        "hashtags": metadata.get("hashtags", []),
        "quality_score": script_data.get("quality_score", 0),
        "elapsed_seconds": elapsed,
        "youtube_url": upload_url,
    }


# ============================================================================
# 배치 생산 (--count N)
# ============================================================================
def batch_produce(
    count: int = 3, upload: bool = False,
    scheduled: bool = False, topic: Optional[str] = None,
):
    print("\n" + "=" * 60)
    print(f"  배치 생산 시작: {count}개")
    print("=" * 60)

    results = []
    for i in range(count):
        if not check_daily_limit():
            print(f"\n  [STOP] 일일 한도 도달 — {i}개 생산 후 중단")
            break

        print(f"\n{'=' * 60}")
        print(f"  [{i + 1}/{count}] 영상 생산 중...")
        print(f"{'=' * 60}")

        try:
            result = make_one_perfect_short(
                upload=upload, scheduled=scheduled,
                video_index=i, keep_temp=False, topic=topic,
            )
            results.append(result)
            print(f"\n  [OK] [{i + 1}/{count}] 완료: {result['title']}")

            if i < count - 1:
                cooldown = random.randint(10, 30)
                print(f"  {cooldown}초 쿨다운...")
                time.sleep(cooldown)

        except Exception as e:
            print(f"\n  [ERROR] [{i + 1}/{count}] 실패: {e}")
            results.append({"error": str(e)})

    FileCleaner.clean_output()

    success = [r for r in results if "video" in r]
    failed = [r for r in results if "error" in r]

    print("\n" + "=" * 60)
    print(f"  배치 생산 완료! 성공: {len(success)}개, 실패: {len(failed)}개")
    for r in success:
        yt = r.get("youtube_url", "") or ""
        print(f"  - {r['title']} ({r.get('quality_score', '?')}점) {yt}")
    print("=" * 60)

    return results


# ============================================================================
# CLI 인터페이스
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="youshorts 올인원 숏츠 생성기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python perfect_one_shot.py                        # 영상 1개 생성
  python perfect_one_shot.py --count 3              # 3개 연속 생산
  python perfect_one_shot.py --count 5 --upload     # 5개 + YouTube 업로드
  python perfect_one_shot.py --upload --scheduled   # 예약 업로드 (4시간 간격)
  python perfect_one_shot.py --topic "편의점 꿀조합" # 주제 직접 지정
  python perfect_one_shot.py --keep-temp            # 임시파일 보관
        """,
    )
    parser.add_argument("--count", "-n", type=int, default=1, help="영상 개수")
    parser.add_argument("--topic", "-t", type=str, default=None, help="주제 직접 지정")
    parser.add_argument("--upload", "-u", action="store_true", help="YouTube 업로드")
    parser.add_argument("--scheduled", "-s", action="store_true", help="예약 업로드")
    parser.add_argument("--keep-temp", action="store_true", help="임시파일 보관")
    parser.add_argument("--no-clean", action="store_true", help="정리 스킵")
    parser.add_argument("--max-daily", type=int, default=None, help="일일 한도")
    args = parser.parse_args()

    if args.max_daily is not None:
        Config.MAX_PER_DAY = args.max_daily

    if args.count > 1:
        batch_produce(
            count=args.count, upload=args.upload,
            scheduled=args.scheduled, topic=args.topic,
        )
    else:
        make_one_perfect_short(
            upload=args.upload, scheduled=args.scheduled,
            keep_temp=args.keep_temp, topic=args.topic,
        )


if __name__ == "__main__":
    main()
