# 변경 사유: Apify API를 활용한 트렌드/경쟁 분석 모듈 신규 생성
"""Apify 기반 트렌드 분석 모듈.

YouTube 트렌드 스크래핑, 경쟁 채널 분석,
Google Trends 기반 주제 추천 기능을 제공합니다.
"""

from __future__ import annotations

from typing import Any

from youshorts.config.settings import Settings, get_settings
from youshorts.security.secrets_manager import SecretsManager
from youshorts.utils.logger import get_logger

logger = get_logger(__name__)


def _get_apify_client(settings: Settings | None = None) -> Any:
    """Apify 클라이언트를 초기화합니다.

    Args:
        settings: 설정 인스턴스.

    Returns:
        ApifyClient 인스턴스.

    Raises:
        RuntimeError: apify-client 미설치 또는 API 토큰 미설정 시.
    """
    try:
        from apify_client import ApifyClient
    except ImportError:
        raise RuntimeError(
            "apify-client 패키지가 필요합니다: pip install apify-client"
        )

    if settings is None:
        settings = get_settings()

    token = SecretsManager.get_secret_value(settings.apify_api_token)
    if not token:
        raise RuntimeError(
            "APIFY_API_TOKEN 환경변수를 설정해주세요."
        )

    return ApifyClient(token)


def scrape_youtube_trends(
    region: str = "KR",
    max_results: int = 20,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """YouTube 인기 급상승 숏츠를 스크래핑합니다.

    Args:
        region: 국가 코드 (KR, US, JP 등).
        max_results: 최대 결과 수.
        settings: 설정 인스턴스.

    Returns:
        트렌딩 영상 리스트 [{title, views, channel, url}, ...].
    """
    client = _get_apify_client(settings)

    logger.info("YouTube 트렌드 스크래핑 (지역: %s)", region)

    run_input = {
        "searchKeywords": "shorts",
        "maxResults": max_results,
        "countryCode": region,
        "resultsType": "video",
        "uploadDate": "week",
        "sortBy": "viewCount",
    }

    try:
        run = client.actor("bernardo/youtube-scraper").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    except Exception as e:
        logger.warning("YouTube 트렌드 스크래핑 실패: %s", e)
        return []

    results: list[dict[str, Any]] = []
    for item in items[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "views": item.get("viewCount", 0),
            "channel": item.get("channelName", ""),
            "url": item.get("url", ""),
            "duration": item.get("duration", ""),
            "likes": item.get("likes", 0),
        })

    logger.info("트렌드 %d개 수집 완료", len(results))
    return results


def analyze_competitor(
    channel_url: str,
    max_videos: int = 10,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """경쟁 채널의 최근 숏츠를 분석합니다.

    Args:
        channel_url: 채널 URL.
        max_videos: 분석할 최대 영상 수.
        settings: 설정 인스턴스.

    Returns:
        분석 결과 딕셔너리 {channel, videos, avg_views, top_keywords}.
    """
    client = _get_apify_client(settings)

    logger.info("경쟁 채널 분석: %s", channel_url)

    run_input = {
        "startUrls": [{"url": channel_url}],
        "maxResults": max_videos,
        "resultsType": "video",
        "sortBy": "date",
    }

    try:
        run = client.actor("bernardo/youtube-scraper").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    except Exception as e:
        logger.warning("경쟁 채널 분석 실패: %s", e)
        return {"channel": channel_url, "videos": [], "avg_views": 0, "top_keywords": []}

    videos: list[dict[str, Any]] = []
    total_views = 0
    all_titles: list[str] = []

    for item in items[:max_videos]:
        views = item.get("viewCount", 0)
        title = item.get("title", "")
        videos.append({
            "title": title,
            "views": views,
            "likes": item.get("likes", 0),
            "url": item.get("url", ""),
        })
        total_views += views
        all_titles.append(title)

    avg_views = total_views // max(len(videos), 1)

    # 간단한 키워드 빈도 분석
    word_freq: dict[str, int] = {}
    stop_words = {"의", "에", "를", "을", "이", "가", "은", "는", "and", "the", "a", "for", "in"}
    for title in all_titles:
        for word in title.split():
            clean = word.strip("[]()!?.,#")
            if len(clean) > 1 and clean.lower() not in stop_words:
                word_freq[clean] = word_freq.get(clean, 0) + 1

    top_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]

    result = {
        "channel": channel_url,
        "videos": videos,
        "avg_views": avg_views,
        "total_videos": len(videos),
        "top_keywords": [kw for kw, _ in top_keywords],
    }

    logger.info(
        "분석 완료: %d개 영상, 평균 조회수 %d",
        len(videos), avg_views,
    )
    return result


def scrape_google_trends(
    keywords: list[str] | None = None,
    region: str = "KR",
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Google Trends에서 인기 검색어를 스크래핑합니다.

    Args:
        keywords: 검색할 키워드 리스트 (None이면 일반 트렌드).
        region: 국가 코드.
        settings: 설정 인스턴스.

    Returns:
        트렌드 리스트 [{keyword, score, related}, ...].
    """
    client = _get_apify_client(settings)

    logger.info("Google Trends 스크래핑 (지역: %s)", region)

    run_input = {
        "geo": region,
        "searchTerms": keywords or [],
        "isPublic": True,
        "timeRange": "now 7-d",
    }

    try:
        run = client.actor("emastra/google-trends-scraper").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    except Exception as e:
        logger.warning("Google Trends 스크래핑 실패: %s", e)
        return []

    results: list[dict[str, Any]] = []
    for item in items:
        results.append({
            "keyword": item.get("term", item.get("keyword", "")),
            "score": item.get("value", item.get("score", 0)),
            "related": item.get("relatedQueries", []),
        })

    logger.info("트렌드 %d개 수집 완료", len(results))
    return results


def suggest_topics(
    region: str = "KR",
    count: int = 5,
    settings: Settings | None = None,
) -> list[str]:
    """트렌드 기반 주제를 추천합니다.

    YouTube 트렌드와 Google Trends를 결합하여
    잠재적으로 조회수가 높을 주제를 추천합니다.

    Args:
        region: 국가 코드.
        count: 추천할 주제 수.
        settings: 설정 인스턴스.

    Returns:
        추천 주제 리스트.
    """
    logger.info("주제 추천 시작 (지역: %s, %d개)", region, count)

    # YouTube 트렌드에서 인기 주제 수집
    trends = scrape_youtube_trends(region=region, max_results=20, settings=settings)

    if not trends:
        logger.warning("트렌드 데이터 없음 - 기본 주제 반환")
        return [
            "한국인이 모르는 생활꿀팁 TOP5",
            "수면의 질을 높이는 과학적 방법",
            "돈 모으는 사람들의 공통 습관",
            "하루 5분 건강 루틴",
            "집에서 할 수 있는 다이어트 운동",
        ][:count]

    # 트렌드 제목에서 패턴 추출
    topics: list[str] = []
    for trend in trends[:count]:
        title = trend.get("title", "")
        if title:
            topics.append(title)

    logger.info("추천 주제 %d개 생성 완료", len(topics))
    return topics[:count]
