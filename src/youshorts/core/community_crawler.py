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

# ── 도파민 폴백 주제 (크롤링 전부 실패 시) ──
DOPAMINE_FALLBACK_TOPICS: list[str] = [
    "알바 진상 손님 레전드 모음",
    "소개팅에서 절대 하면 안 되는 행동",
    "직장 상사한테 한 마디 했더니 벌어진 일",
    "자취하면서 겪은 소름 돋는 경험",
    "택배 잘못 왔는데 열어봤더니",
    "군대에서 생긴 레전드 사건",
    "룸메이트 때문에 미쳐버린 썰",
    "중고거래 사기 당할 뻔한 썰",
    "면접에서 면접관이 한 말 실화냐",
    "편의점 야간 알바 소름 돋는 경험",
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
        selected = filtered[:count]

        for p in selected:
            self.used_titles.add(p["title"])

        # 아무것도 없으면 폴백
        if not selected:
            return self._get_fallback()[:count]

        return selected

    # ──────────────────────────────────────
    # 점수 산출
    # ──────────────────────────────────────

    def _calc_shorts_score(self, post: dict[str, Any]) -> int:
        """쇼츠 적합성 점수를 산출합니다 (높을수록 좋음)."""
        score = 0
        title = post.get("title", "")
        body = post.get("body", "")

        # 도파민 키워드
        for word in _DOPAMINE_KEYWORDS:
            if word in title:
                score += 3
            if word in body:
                score += 1

        # 스토리성
        for word in _STORY_INDICATORS:
            if word in body:
                score += 2

        # 길이 적합성
        body_len = len(body)
        if 100 <= body_len <= 800:
            score += 5
        elif body_len < 50:
            score -= 10

        # 정치/혐오 감점
        for word in _BAD_KEYWORDS:
            if word in title or word in body:
                score -= 100

        return score

    # ──────────────────────────────────────
    # 폴백
    # ──────────────────────────────────────

    def _get_fallback(self) -> list[dict[str, Any]]:
        """크롤링 전부 실패 시 도파민 폴백 주제를 반환합니다."""
        topic = random.choice(DOPAMINE_FALLBACK_TOPICS)
        return [{"title": topic, "body": "", "source": "fallback"}]

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
