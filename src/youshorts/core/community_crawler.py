"""실시간 커뮤니티 인기글 크롤링 모듈.

네이트판, 에펨코리아, 더쿠, 네이버뉴스, Google Trends에서
도파민 적합성이 높은 게시글을 직접 크롤링합니다.
"""

from __future__ import annotations

import random
import re
import xml.etree.ElementTree as ET
from typing import Any

import requests
from bs4 import BeautifulSoup

from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

# ── 레퍼런스 채널급 폴백 주제 (크롤링 전부 실패 시) ──
DOPAMINE_FALLBACK_TOPICS: list[dict[str, str]] = [
    {
        "title": "배달 치킨 3마리 시켰는데 준 반찬 레전드ㄷㄷ",
        "body": "배달앱으로 치킨 3마리 주문했는데 사장님이 서비스로 준 반찬이 역대급이었다. 감자튀김 2봉, 콜라 2L, 떡볶이까지. 리뷰 남겼더니 사장님 답글이 더 레전드.",
        "source": "폴백"
    },
    {
        "title": "편의점 알바 3개월 만에 목격한 진상 TOP3ㅋㅋ",
        "body": "편의점에서 3개월 알바하면서 겪은 진상 손님 3명. 1등은 삼각김밥 전자레인지 5분 돌려달라는 사람. 2등은 1+1 제품 3개 가져와서 공짜 달라는 사람.",
        "source": "폴백"
    },
    {
        "title": "중고거래로 에어팟 샀는데 택배 열어보니 결말ㄷㄷ",
        "body": "당근에서 에어팟 프로 8만원에 올라온 거 바로 샀는데, 택배 열어보니 에어팟 케이스 안에 사탕이 들어있었다. 바로 경찰 신고했더니 판매자 반응이 더 충격.",
        "source": "폴백"
    },
    {
        "title": "카페 알바가 실수로 준 음료 1잔 때문에 생긴 일ㅋㅋ",
        "body": "스타벅스 알바가 아메리카노 대신 자바칩 프라푸치노를 줬는데, 손님이 먹어보고 감동받아서 매일 오기 시작. 결국 그 손님이 사장한테 칭찬 편지까지 보냄.",
        "source": "폴백"
    },
    {
        "title": "식당 사장이 손님 1명한테 서비스 거절한 이유ㄷㄷ",
        "body": "단골 식당에서 사장님이 갑자기 서비스 안 준다고 했는데, 알고 보니 그 손님이 매번 서비스만 먹고 리뷰에 별 1개 주는 사람이었다.",
        "source": "폴백"
    },
    {
        "title": "배달 기사한테 팁 5만원 줬더니 생긴 일ㅋㅋ",
        "body": "비 오는 날 배달 기사한테 현금 5만원 팁을 줬더니, 다음날 같은 기사가 와서 직접 만든 반찬을 가져왔다. 그 뒤로 매번 배달 올 때마다 서비스가 추가됨.",
        "source": "폴백"
    },
    {
        "title": "PC방 손님이 라면 20개 주문한 결말ㄷㄷ",
        "body": "PC방에서 혼자 라면 20개를 시킨 손님이 있었는데, 알고 보니 유튜브 먹방 찍는 사람이었다. 문제는 다 먹고 나서 자리 상태가 역대급.",
        "source": "폴백"
    },
    {
        "title": "마트 직원이 할인 스티커 붙이는 시간 알려준 결말ㅋㅋ",
        "body": "이마트 직원이 마감 할인 시간을 SNS에 올렸다가 그 시간에 200명이 몰린 사건. 매장 난리 나고 직원은 시말서 쓰고 결국 그 시간대 할인 폐지됨.",
        "source": "폴백"
    },
    {
        "title": "택시 기사가 손님 1명 거부한 이유 알고보니ㄷㄷ",
        "body": "택시 기사가 특정 손님을 계속 거부했는데, 알고 보니 그 손님이 매번 택시에서 음식을 흘리고 토하고 도망가는 상습범이었다. CCTV 모아서 신고한 결과.",
        "source": "폴백"
    },
    {
        "title": "쿠팡 배달 1건으로 100만원 벌어버린 실화ㅋㅋ",
        "body": "쿠팡 배달하다가 고객이 실수로 100만원짜리 물건을 반품 안 한 채 돌려보냈는데, 정직하게 신고했더니 쿠팡에서 포상금 100만원을 줌.",
        "source": "폴백"
    },
    {
        "title": "고깃집 2인분 시켰는데 나온 양 레전드 논란ㄷㄷ",
        "body": "삼겹살 2인분 시켰는데 나온 고기가 손바닥만 했음. 항의했더니 사장이 '원래 이 양'이라고 해서 리뷰 남겼더니 사장 답글이 더 역대급.",
        "source": "폴백"
    },
    {
        "title": "중국집 배달 40분 걸린 이유 알고보니ㅋㅋ",
        "body": "짜장면 배달이 40분이나 걸려서 전화했더니, 배달 기사가 길에서 교통사고 목격하고 신고+응급처치까지 하고 온 거였다. 별점 5개 박고 팁 만원 더 줌.",
        "source": "폴백"
    }
]

# ── 도파민 키워드 ──
_DOPAMINE_KEYWORDS: list[str] = [
    "레전드", "실화", "소름", "미쳤", "충격", "ㅋㅋ", "ㄹㅇ",
    "대박", "역대급", "반전", "논란", "폭로", "고백", "참교육",
    "복수", "사이다", "감동", "후회", "눈물", "소개팅", "직장",
    "알바", "상사", "진상", "몰랐", "알고보니", "결국",
]

_STORY_INDICATORS: list[str] = [
    "했는데", "했더니", "알고보니", "그래서", "결국", "그런데", "진짜",
]

_BAD_KEYWORDS: list[str] = [
    "정치", "대통령", "국회", "여당", "야당", "종교",
    "자살", "사망", "시신", "성범죄", "아동",
]


class CommunityCrawler:
    """실시간 커뮤니티 인기글 크롤러."""

    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    _TIMEOUT = 10

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self._USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.3",
        })
        self.used_titles: set[str] = set()

    # ──────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────

    def fetch_all(self) -> list[dict[str, Any]]:
        """모든 소스에서 인기글을 수집합니다. 실패한 소스는 스킵.

        Returns:
            [{'title': str, 'body': str, 'source': str}, ...] 리스트.
        """
        posts: list[dict[str, Any]] = []

        sources = [
            ("네이트판", self._fetch_natepann),
            ("에펨코리아", self._fetch_fmkorea),
            ("더쿠", self._fetch_theqoo),
            ("네이버뉴스", self._fetch_naver_news),
            ("Google Trends", self._fetch_google_trends),
        ]

        for name, fetcher in sources:
            try:
                result = fetcher()
                posts.extend(result)
                logger.info("[크롤링] %s: %d개", name, len(result))
            except Exception as e:
                logger.warning("[크롤링 실패] %s: %s", name, e)
                continue

        # 중복 제거
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for p in posts:
            if p["title"] not in seen:
                seen.add(p["title"])
                unique.append(p)

        logger.info("[크롤링] 총 %d개 수집", len(unique))
        return unique

    def pick_best(self, count: int = 1) -> list[dict[str, Any]]:
        """쇼츠에 적합한 글을 count개 선택합니다.

        Args:
            count: 반환할 게시글 수.

        Returns:
            [{title, body, source, score}, ...] 리스트.
        """
        posts = self.fetch_all()

        scored: list[dict[str, Any]] = []
        for p in posts:
            score = self._calc_shorts_score(p)
            if score > 0:
                p["score"] = score
                scored.append(p)

        scored.sort(key=lambda x: x["score"], reverse=True)

        # 이미 사용한 제목 제외
        filtered = [p for p in scored if p["title"] not in self.used_titles]

        # 점수 15점 이상만 사용
        high_quality = [p for p in filtered if p.get("score", 0) >= 15]

        if high_quality:
            selected = high_quality[:count]
            for p in selected:
                self.used_titles.add(p["title"])
                logger.info(
                    "[주제] 선정: %s (점수: %d, 소스: %s)",
                    p["title"][:30], p["score"], p.get("source", "?")
                )
            return selected

        # 전부 10점 미만이면 폴백 사용
        logger.info("[주제] 크롤링 결과 품질 낮음 → 폴백 주제 사용")
        return self._get_fallback()[:count]

    # ──────────────────────────────────────
    # 점수 산출
    # ──────────────────────────────────────

    def _calc_shorts_score(self, post: dict[str, Any]) -> int:
        """쇼츠 적합성 점수를 산출합니다 (높을수록 좋음).

        점수 기준:
        - 음식/배달/알바/진상: +8점
        - 레전드/역대급/논란/충격/결말/ㄷㄷ/ㅋㅋ: +5점
        - 구체적 숫자: +4점
        - 정치/고양이/강아지/투표/설문: -100점
        최소 10점 이상만 통과
        """
        score = 0
        title = post.get("title", "")
        body = post.get("body", "")
        text = title + " " + body

        # ━━ 절대 금지 (-100점) - 먼저 체크 ━━
        banned = [
            '정치', '선거', '대통령', '여당', '야당', '국회',
            '페미', '일베', '한남', '한녀',
            '고양이', '강아지', '반려동물', '육아', '임신',
            '톡선', '투표', '설문', '광고', '홍보', '구독',
            '주식', '코인', '비트', '부동산'
        ]
        for kw in banned:
            if kw in text:
                return -100

        # ── 음식/배달/알바/진상 (+8점) ──
        food_keywords = [
            '배달', '치킨', '피자', '짜장면', '초밥', '마라탕',
            '편의점', '알바', '카페', '식당', '횟집', '고깃집',
            '서브웨이', 'PC방', '정육점', '빵집', '떡볶이',
            '중국집', '손님', '사장', '주문', '리뷰', '별점',
            '진상', '서비스'
        ]
        if any(kw in text for kw in food_keywords):
            score += 8

        # ── 바이럴 키워드 (+5점) ──
        viral_keywords = [
            '레전드', '역대급', '논란', '충격', '결말',
            'ㄷㄷ', 'ㅋㅋ', '소름', '대박', '실화',
            '미친', '참교육', '복수', '폭로', 'ㄹㅇ'
        ]
        if any(kw in text for kw in viral_keywords):
            score += 5

        # ── 구체적 숫자 (+4점) ──
        import re
        numbers = re.findall(r'\d+', title)
        if numbers:
            score += 4

        return score

    # ──────────────────────────────────────
    # 폴백
    # ──────────────────────────────────────

    def _get_fallback(self) -> list[dict[str, Any]]:
        """크롤링 전부 실패 시 레퍼런스 채널급 폴백 주제를 반환합니다."""
        return [random.choice(DOPAMINE_FALLBACK_TOPICS)]

    # ──────────────────────────────────────
    # 크롤러 1: 네이트판
    # ──────────────────────────────────────

    def _fetch_natepann(self) -> list[dict[str, Any]]:
        """네이트판 톡커들의 선택 (인기글) 크롤링."""
        posts: list[dict[str, Any]] = []
        try:
            resp = self._session.get(
                "https://pann.nate.com/talk/ranking",
                timeout=self._TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # 인기글 목록에서 제목 추출
            items = soup.select("div.post_wrap a.tit, li.first a, a.rankTit")
            if not items:
                items = soup.select("a[href*='/talk/']")

            for item in items[:15]:
                title = item.get_text(strip=True)
                if len(title) < 5:
                    continue
                href = item.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://pann.nate.com" + href

                # 본문 가져오기 시도
                body = ""
                if href:
                    try:
                        detail = self._session.get(href, timeout=self._TIMEOUT)
                        detail_soup = BeautifulSoup(detail.text, "html.parser")
                        content = detail_soup.select_one(
                            "div.posting_area, div#contentArea, div.post_content"
                        )
                        if content:
                            body = content.get_text(strip=True)[:500]
                    except Exception:
                        pass

                posts.append({
                    "title": title,
                    "body": body,
                    "source": "네이트판",
                })

        except Exception as e:
            logger.debug("네이트판 크롤링 에러: %s", e)
        return posts

    # ──────────────────────────────────────
    # 크롤러 2: 에펨코리아
    # ──────────────────────────────────────

    def _fetch_fmkorea(self) -> list[dict[str, Any]]:
        """에펨코리아 포텐터짐(인기글) 크롤링."""
        posts: list[dict[str, Any]] = []
        try:
            resp = self._session.get(
                "https://www.fmkorea.com/index.php?mid=best",
                timeout=self._TIMEOUT,
                verify=False,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            items = soup.select("h3.title a, td.title a.hx")
            if not items:
                items = soup.select("a[href*='fmkorea.com']")

            for item in items[:10]:
                title = item.get_text(strip=True)
                # 카테고리/태그 제거
                title = re.sub(r"^\[.*?\]\s*", "", title)
                if len(title) < 5:
                    continue

                posts.append({
                    "title": title,
                    "body": "",
                    "source": "에펨코리아",
                })

        except Exception as e:
            logger.debug("에펨코리아 크롤링 에러: %s", e)
        return posts

    # ──────────────────────────────────────
    # 크롤러 3: 더쿠
    # ──────────────────────────────────────

    def _fetch_theqoo(self) -> list[dict[str, Any]]:
        """더쿠 핫 게시판 크롤링."""
        posts: list[dict[str, Any]] = []
        try:
            resp = self._session.get(
                "https://theqoo.net/hot",
                timeout=self._TIMEOUT,
                verify=False,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            items = soup.select("a.document-link, td.title a")
            if not items:
                items = soup.select("a[href*='/hot/']")

            for item in items[:10]:
                title = item.get_text(strip=True)
                title = re.sub(r"^\[.*?\]\s*", "", title)
                if len(title) < 5:
                    continue

                posts.append({
                    "title": title,
                    "body": "",
                    "source": "더쿠",
                })

        except Exception as e:
            logger.debug("더쿠 크롤링 에러: %s", e)
        return posts

    # ──────────────────────────────────────
    # 크롤러 4: 네이버 뉴스 랭킹
    # ──────────────────────────────────────

    def _fetch_naver_news(self) -> list[dict[str, Any]]:
        """네이버 뉴스 랭킹 (실시간 인기) 크롤링."""
        posts: list[dict[str, Any]] = []
        try:
            resp = self._session.get(
                "https://news.naver.com/main/ranking/popularDay.naver",
                timeout=self._TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            items = soup.select(
                "a.list_title, div.rankingnews_box a, "
                "a.ranking_headline, a[class*='title']"
            )

            for item in items[:10]:
                title = item.get_text(strip=True)
                if len(title) < 8:
                    continue

                posts.append({
                    "title": title,
                    "body": "",
                    "source": "네이버뉴스",
                })

        except Exception as e:
            logger.debug("네이버뉴스 크롤링 에러: %s", e)
        return posts

    # ──────────────────────────────────────
    # 크롤러 5: Google Trends
    # ──────────────────────────────────────

    def _fetch_google_trends(self) -> list[dict[str, Any]]:
        """Google Trends 한국 실시간 트렌드 크롤링 (RSS)."""
        posts: list[dict[str, Any]] = []
        try:
            resp = self._session.get(
                "https://trends.google.co.kr/trends/trendingsearches/daily/rss?geo=KR",
                timeout=self._TIMEOUT,
            )
            resp.raise_for_status()

            root = ET.fromstring(resp.text)
            ns = {"ht": "https://trends.google.co.kr/trends/trendingsearches/daily"}

            for item in root.findall(".//item")[:10]:
                title_el = item.find("title")
                if title_el is None or title_el.text is None:
                    continue
                title = title_el.text.strip()

                # 4글자 미만 제외
                if len(title) < 4:
                    continue

                # 관련 기사 제목 가져오기
                body = ""
                news_items = item.findall(".//ht:news_item_title", ns)
                if news_items:
                    body = " / ".join(
                        ni.text.strip() for ni in news_items[:3]
                        if ni.text
                    )

                posts.append({
                    "title": title,
                    "body": body,
                    "source": "Google Trends",
                })

        except Exception as e:
            logger.debug("Google Trends 크롤링 에러: %s", e)
        return posts
