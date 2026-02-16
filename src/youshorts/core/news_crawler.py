"""뉴스 크롤러 모듈 - 팩트 기반 대본 생성의 원재료 수집.

트렌드 키워드를 받아 실제 한국 뉴스 기사를 크롤링하고,
기사 제목 + 본문 텍스트를 반환합니다.

크롤링 소스 우선순위:
1. Google News Korea RSS (무료, API 키 불필요)
2. 네이버 뉴스 검색 (무료, API 키 불필요)
3. 다음 뉴스 검색 (무료, 폴백)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

import feedparser
import requests
from bs4 import BeautifulSoup

from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _USER_AGENT}
_TIMEOUT = 10
_MAX_RETRIES = 2
_CACHE_DIR = os.path.join("data", "news_cache")


class NewsCrawler:
    """뉴스 기사 크롤러."""

    def __init__(self) -> None:
        os.makedirs(_CACHE_DIR, exist_ok=True)

    # ================================================================
    # 메인 API
    # ================================================================

    def fetch_news_articles(
        self, keyword: str, count: int = 5
    ) -> list[dict[str, Any]]:
        """키워드로 실제 뉴스 기사를 크롤링해서 반환합니다.

        Args:
            keyword: 검색 키워드.
            count: 수집할 기사 수.

        Returns:
            [{"title", "body", "source", "url", "date"}, ...]
        """
        articles: list[dict[str, Any]] = []

        # 소스1: Google News RSS
        try:
            google_articles = self._fetch_google_news_rss(keyword, count)
            articles.extend(google_articles)
            logger.info("Google News: %d개 기사 수집", len(google_articles))
        except Exception as e:
            logger.warning("Google News RSS 실패: %s", e)

        # 소스2: 네이버 뉴스 검색
        if len(articles) < count:
            try:
                naver_articles = self._fetch_naver_news(
                    keyword, count - len(articles)
                )
                articles.extend(naver_articles)
                logger.info("네이버 뉴스: %d개 기사 수집", len(naver_articles))
            except Exception as e:
                logger.warning("네이버 뉴스 실패: %s", e)

        # 소스3: 다음 뉴스 검색 (폴백)
        if len(articles) < count:
            try:
                daum_articles = self._fetch_daum_news(
                    keyword, count - len(articles)
                )
                articles.extend(daum_articles)
                logger.info("다음 뉴스: %d개 기사 수집", len(daum_articles))
            except Exception as e:
                logger.warning("다음 뉴스 실패: %s", e)

        # 본문이 있는 기사만 필터
        valid = [a for a in articles if a.get("body") and len(a["body"]) >= 300]
        logger.info(
            "총 %d개 기사 수집 (본문 유효: %d개)", len(articles), len(valid)
        )
        return valid[:count]

    def select_best_article(
        self, articles: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """크롤링된 기사 중 쇼츠로 만들기 가장 좋은 기사 1개를 선택합니다.

        선택 기준:
        - 본문 길이 300자 이상
        - 숫자/통계 포함 우선
        - 인용문 포함 우선
        - 감정 키워드 포함 우선
        - 연예인 이름 제목 → 후순위

        Args:
            articles: 기사 리스트.

        Returns:
            최적 기사 또는 None.
        """
        if not articles:
            return None

        scored: list[tuple[float, dict[str, Any]]] = []

        for article in articles:
            score = 0.0
            title = article.get("title", "")
            body = article.get("body", "")

            # 본문 길이 점수 (300~1500자 최적)
            body_len = len(body)
            if body_len < 300:
                continue
            if 500 <= body_len <= 1500:
                score += 3
            elif body_len >= 300:
                score += 1

            # 숫자/통계 포함 (숫자 많을수록 좋음)
            numbers = re.findall(r"\d+", body)
            score += min(len(numbers) * 0.5, 3)

            # 인용문 포함
            if '"' in body or "'" in body or "\u201c" in body:
                score += 2

            # 감정 키워드 (제목 or 본문)
            emotion_keywords = [
                "충격", "논란", "화제", "반전", "실화", "폭로",
                "긴급", "속보", "경악", "발칵", "파문", "위기",
            ]
            for ek in emotion_keywords:
                if ek in title:
                    score += 1.5
                elif ek in body[:200]:
                    score += 0.5

            # 연예인 이름 패턴 → 후순위 (허위사실 위험)
            celeb_patterns = [
                "아이돌", "배우", "가수", "연예인",
            ]
            for cp in celeb_patterns:
                if cp in title:
                    score -= 2

            # 2~3글자 인명만 제목인 경우 감점
            title_clean = re.sub(r"[^\w가-힣]", "", title)
            if re.fullmatch(r"[가-힣]{2,3}", title_clean):
                score -= 5

            scored.append((score, article))

        if not scored:
            return articles[0] if articles else None

        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][1]
        logger.info(
            "최적 기사 선택: '%s' (점수: %.1f)",
            best.get("title", "")[:30],
            scored[0][0],
        )
        return best

    # ================================================================
    # 소스1: Google News Korea RSS
    # ================================================================

    def _fetch_google_news_rss(
        self, keyword: str, count: int
    ) -> list[dict[str, Any]]:
        """Google News 한국 RSS에서 기사를 수집합니다."""
        url = (
            f"https://news.google.com/rss/search?"
            f"q={quote_plus(keyword)}&hl=ko&gl=KR&ceid=KR:ko"
        )

        feed = feedparser.parse(url)
        articles: list[dict[str, Any]] = []

        for entry in feed.entries[:count * 2]:  # 여유분 수집
            if len(articles) >= count:
                break

            title = entry.get("title", "")
            link = entry.get("link", "")
            published = entry.get("published", "")
            source = entry.get("source", {}).get("title", "Google News")

            if not link:
                continue

            # 본문 추출 (캐시 확인)
            body = self._get_article_body_cached(link)
            if body and len(body) >= 300:
                articles.append({
                    "title": title,
                    "body": body[:2000],
                    "source": source,
                    "url": link,
                    "date": published,
                })

        return articles

    # ================================================================
    # 소스2: 네이버 뉴스 검색
    # ================================================================

    def _fetch_naver_news(
        self, keyword: str, count: int
    ) -> list[dict[str, Any]]:
        """네이버 뉴스 검색에서 기사를 수집합니다."""
        url = (
            f"https://search.naver.com/search.naver?"
            f"where=news&query={quote_plus(keyword)}&sort=1"
        )

        resp = self._safe_get(url)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        articles: list[dict[str, Any]] = []

        # 뉴스 검색 결과 파싱
        news_items = soup.select("div.news_area") or soup.select("li.bx")

        for item in news_items[:count * 2]:
            if len(articles) >= count:
                break

            # 제목 추출
            title_tag = (
                item.select_one("a.news_tit")
                or item.select_one("a.title_link")
            )
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            link = title_tag.get("href", "")

            # 요약문 추출
            desc_tag = (
                item.select_one("div.news_dsc")
                or item.select_one("div.dsc_wrap")
                or item.select_one("a.api_txt_lines.dsc_txt_wrap")
            )
            summary = desc_tag.get_text(strip=True) if desc_tag else ""

            # 출처 추출
            source_tag = (
                item.select_one("a.info.press")
                or item.select_one("span.info_press")
            )
            source = source_tag.get_text(strip=True) if source_tag else "네이버뉴스"

            # 네이버 뉴스 링크면 직접 본문 추출
            if "news.naver.com" in link:
                body = self._get_article_body_cached(link)
            else:
                body = self._get_article_body_cached(link)

            if not body or len(body) < 300:
                # 요약문이라도 사용 (단, 짧을 수 있음)
                body = summary if len(summary) >= 200 else ""

            if body and len(body) >= 200:
                articles.append({
                    "title": title,
                    "body": body[:2000],
                    "source": source,
                    "url": link,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                })

        return articles

    # ================================================================
    # 소스3: 다음 뉴스 검색
    # ================================================================

    def _fetch_daum_news(
        self, keyword: str, count: int
    ) -> list[dict[str, Any]]:
        """다음 뉴스 검색에서 기사를 수집합니다."""
        url = (
            f"https://search.daum.net/search?"
            f"w=news&q={quote_plus(keyword)}&sort=recency"
        )

        resp = self._safe_get(url)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        articles: list[dict[str, Any]] = []

        news_items = soup.select("div.wrap_cont") or soup.select("li.fst")

        for item in news_items[:count * 2]:
            if len(articles) >= count:
                break

            title_tag = item.select_one("a.tit_main") or item.select_one("a.f_link_b")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            link = title_tag.get("href", "")

            desc_tag = item.select_one("p.f_eb") or item.select_one("div.desc")
            summary = desc_tag.get_text(strip=True) if desc_tag else ""

            source_tag = item.select_one("span.f_nb") or item.select_one("a.f_nb")
            source = source_tag.get_text(strip=True) if source_tag else "다음뉴스"

            body = self._get_article_body_cached(link)
            if not body or len(body) < 300:
                body = summary if len(summary) >= 200 else ""

            if body and len(body) >= 200:
                articles.append({
                    "title": title,
                    "body": body[:2000],
                    "source": source,
                    "url": link,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                })

        return articles

    # ================================================================
    # 기사 본문 추출
    # ================================================================

    def extract_article_body(self, url: str) -> str:
        """기사 URL에서 본문 텍스트만 추출합니다.

        HTML 태그 제거, 광고 텍스트 제거, 기자명/이메일 제거.

        Args:
            url: 기사 URL.

        Returns:
            정제된 본문 텍스트 (최대 2000자).
        """
        resp = self._safe_get(url)
        if not resp:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        # 불필요 태그 제거
        for tag in soup.find_all(["script", "style", "iframe", "nav", "header", "footer"]):
            tag.decompose()

        body = ""

        # 파싱 전략 우선순위
        strategies = [
            # 네이버 뉴스
            lambda: soup.select_one("#newsct_article"),
            lambda: soup.select_one("#dic_area"),
            lambda: soup.select_one("#articleBodyContents"),
            # 일반 기사
            lambda: soup.select_one("article"),
            lambda: soup.select_one("#articleBody"),
            lambda: soup.select_one(".article_body"),
            lambda: soup.select_one(".news_body"),
            lambda: soup.select_one("#article_body"),
            lambda: soup.select_one(".article-body"),
            lambda: soup.select_one("[itemprop='articleBody']"),
        ]

        for strategy in strategies:
            element = strategy()
            if element:
                body = element.get_text(separator=" ", strip=True)
                if len(body) >= 300:
                    break

        # 폴백: 가장 긴 <p> 태그 묶음
        if len(body) < 300:
            paragraphs = soup.find_all("p")
            p_texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
            body = " ".join(p_texts)

        # 정제
        body = self._clean_article_body(body)

        if len(body) < 300:
            return ""

        return body[:2000]

    # ================================================================
    # 캐싱
    # ================================================================

    def _get_article_body_cached(self, url: str) -> str:
        """캐시된 기사 본문을 반환하거나, 없으면 크롤링 후 캐시합니다."""
        cache_key = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(_CACHE_DIR, f"{cache_key}.json")

        # 캐시 확인 (24시간 유효)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                cached_time = datetime.fromisoformat(cached.get("cached_at", ""))
                if datetime.now() - cached_time < timedelta(hours=24):
                    return cached.get("body", "")
            except Exception:
                pass

        # 크롤링
        body = self.extract_article_body(url)

        # 캐시 저장
        if body:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "url": url,
                        "body": body,
                        "cached_at": datetime.now().isoformat(),
                    }, f, ensure_ascii=False)
            except Exception:
                pass

        return body

    # ================================================================
    # 유틸리티
    # ================================================================

    def _safe_get(self, url: str) -> requests.Response | None:
        """안전한 HTTP GET 요청 (재시도 포함)."""
        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.get(
                    url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True
                )
                resp.raise_for_status()
                return resp
            except Exception as e:
                logger.debug(
                    "HTTP 요청 실패 (시도 %d/%d): %s → %s",
                    attempt + 1, _MAX_RETRIES, url[:60], e,
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(1)
        return None

    def _clean_article_body(self, text: str) -> str:
        """기사 본문을 정제합니다."""
        # 기자명/이메일 제거
        text = re.sub(r"\S+@\S+\.\S+", "", text)
        text = re.sub(r"기자\s*=?\s*[가-힣]{2,4}\s*기자", "", text)
        text = re.sub(r"\[.{1,20}\]\s*", "", text)  # [서울경제] 등

        # 광고/저작권 문구 제거
        ad_patterns = [
            r"무단\s?전재\s?및\s?재배포\s?금지",
            r"저작권자\s?[^\n]{0,50}",
            r"Copyright\s?[^\n]{0,50}",
            r"ⓒ[^\n]{0,50}",
            r"관련\s?기사\s?보기",
            r"기사\s?제보\s*:",
            r"구독\s?좋아요\s?알림",
        ]
        for pat in ad_patterns:
            text = re.sub(pat, "", text, flags=re.IGNORECASE)

        # 연속 공백 정리
        text = re.sub(r"\s+", " ", text).strip()

        return text
