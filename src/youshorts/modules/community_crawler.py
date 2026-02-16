"""커뮤니티 게시글 크롤링 모듈 (Apify 기반).

네이트판, 디시인사이드 등 커뮤니티 사이트에서
바이럴 잠재력이 높은 '썰' 게시글을 크롤링합니다.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import requests

from youshorts.config.settings import get_settings
from youshorts.utils.logger import get_logger
from youshorts.utils.retry import retry

logger = get_logger(__name__)


class CommunityCrawler:
    """커뮤니티 게시글 크롤러."""

    def __init__(self) -> None:
        """크롤러를 초기화합니다."""
        settings = get_settings()
        self.apify_token = settings.apify_api_token.get_secret_value()
        self.timeout = settings.download_timeout

    def _detect_platform(self, url: str) -> str:
        """URL에서 플랫폼을 자동 감지합니다.

        Args:
            url: 크롤링할 URL

        Returns:
            플랫폼 이름 (natepann/dcinside/instiz/fmkorea/ruliweb)
        """
        domain = urlparse(url).netloc.lower()

        if "pann.nate.com" in domain:
            return "natepann"
        elif "dcinside.com" in domain:
            return "dcinside"
        elif "instiz.net" in domain:
            return "instiz"
        elif "fmkorea.com" in domain:
            return "fmkorea"
        elif "ruliweb.com" in domain:
            return "ruliweb"
        else:
            logger.warning(f"알 수 없는 플랫폼: {domain}, 기본값 사용")
            return "unknown"

    def _clean_text(self, text: str) -> str:
        """텍스트를 정제합니다.

        Args:
            text: 원본 텍스트

        Returns:
            정제된 텍스트
        """
        # HTML 태그 제거
        text = re.sub(r"<[^>]+>", "", text)
        # 연속된 공백 제거
        text = re.sub(r"\s+", " ", text)
        # 특수문자 정리 (이모티콘 제외)
        text = re.sub(r"[^\w\s\u3131-\u3163\uac00-\ud7a3ㅋㅎㅠㅜㅡㄷ!?.,\"\'\n\-]", "", text)
        return text.strip()

    @retry(max_attempts=3, backoff_factor=2.0)
    def fetch_post(self, url: str) -> dict[str, Any]:
        """URL에서 게시글을 크롤링합니다.

        Args:
            url: 크롤링할 게시글 URL

        Returns:
            게시글 데이터 딕셔너리
            {
                "url": str,
                "platform": str,
                "title": str,
                "content": str,
                "author": str,
                "views": int,
                "likes": int,
                "comments_count": int,
            }

        Raises:
            requests.RequestException: API 호출 실패 시
            ValueError: 잘못된 응답 형식
        """
        if not self.apify_token:
            logger.error("Apify API 토큰이 설정되지 않았습니다")
            raise ValueError("APIFY_API_TOKEN이 환경변수에 없습니다")

        platform = self._detect_platform(url)
        logger.info(f"크롤링 시작: {platform} - {url}")

        # Apify Cheerio Scraper Actor 호출
        actor_id = "apify/cheerio-scraper"
        run_url = f"https://api.apify.com/v2/acts/{actor_id}/runs"

        # 플랫폼별 셀렉터 설정
        selectors = self._get_platform_selectors(platform)

        payload = {
            "startUrls": [{"url": url}],
            "pseudoUrls": [],
            "linkSelector": "",
            "pageFunction": self._generate_page_function(selectors),
            "proxyConfiguration": {"useApifyProxy": False},
            "maxRequestRetries": 3,
            "maxPagesPerCrawl": 1,
            "maxRequestsPerCrawl": 1,
        }

        headers = {
            "Authorization": f"Bearer {self.apify_token}",
            "Content-Type": "application/json",
        }

        try:
            # Actor 실행
            response = requests.post(
                run_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            run_data = response.json()
            run_id = run_data["data"]["id"]

            logger.info(f"Apify Run ID: {run_id}, 완료 대기 중...")

            # 실행 완료 대기 (최대 60초)
            wait_url = f"https://api.apify.com/v2/acts/{actor_id}/runs/{run_id}/wait-for-finish"
            wait_response = requests.get(
                wait_url,
                headers=headers,
                params={"timeout": 60},
                timeout=70,
            )
            wait_response.raise_for_status()

            # 결과 가져오기
            dataset_id = wait_response.json()["data"]["defaultDatasetId"]
            items_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
            items_response = requests.get(items_url, headers=headers, timeout=30)
            items_response.raise_for_status()

            items = items_response.json()
            if not items:
                raise ValueError("크롤링 결과가 비어있습니다")

            post_data = items[0]
            logger.info(f"크롤링 완료: 제목={post_data.get('title', '')[:30]}")

            # 데이터 정제 및 반환
            return {
                "url": url,
                "platform": platform,
                "title": self._clean_text(post_data.get("title", "")),
                "content": self._clean_text(post_data.get("content", "")),
                "author": post_data.get("author", "익명"),
                "views": int(post_data.get("views", 0)),
                "likes": int(post_data.get("likes", 0)),
                "comments_count": int(post_data.get("comments_count", 0)),
            }

        except requests.RequestException as e:
            logger.error(f"Apify API 호출 실패: {e}")
            raise
        except (KeyError, ValueError, IndexError) as e:
            logger.error(f"응답 파싱 실패: {e}")
            raise ValueError(f"잘못된 응답 형식: {e}")

    def _get_platform_selectors(self, platform: str) -> dict[str, str]:
        """플랫폼별 CSS 셀렉터를 반환합니다.

        Args:
            platform: 플랫폼 이름

        Returns:
            셀렉터 딕셔너리
        """
        selectors_map = {
            "natepann": {
                "title": ".subject",
                "content": ".content_view",
                "author": ".nick",
                "views": ".hit",
                "likes": ".upCnt",
                "comments": ".cbox_info",
            },
            "dcinside": {
                "title": ".title_subject",
                "content": ".write_div",
                "author": ".nickname",
                "views": ".gall_count",
                "likes": ".up_num",
                "comments": ".cmt_cnt",
            },
            "instiz": {
                "title": ".sbjWrap",
                "content": ".memo_content",
                "author": ".writer",
                "views": ".viewCount",
                "likes": ".likeCount",
                "comments": ".comment_cnt",
            },
            "fmkorea": {
                "title": ".np_18px",
                "content": ".xe_content",
                "author": ".member",
                "views": ".m_no",
                "likes": ".voteNum",
                "comments": ".cmtNum",
            },
            "ruliweb": {
                "title": ".subject",
                "content": ".board_main_view",
                "author": ".nick",
                "views": ".view",
                "likes": ".like_num",
                "comments": ".reply_num",
            },
        }
        return selectors_map.get(platform, selectors_map["natepann"])

    def _generate_page_function(self, selectors: dict[str, str]) -> str:
        """Apify pageFunction 자바스크립트 코드를 생성합니다.

        Args:
            selectors: CSS 셀렉터 딕셔너리

        Returns:
            자바스크립트 함수 문자열
        """
        return f"""
async function pageFunction(context) {{
    const {{ $, request }} = context;

    const title = $('{selectors["title"]}').text().trim();
    const content = $('{selectors["content"]}').text().trim();
    const author = $('{selectors["author"]}').text().trim();
    const views = $('{selectors["views"]}').text().replace(/[^0-9]/g, '') || '0';
    const likes = $('{selectors["likes"]}').text().replace(/[^0-9]/g, '') || '0';
    const comments = $('{selectors["comments"]}').text().replace(/[^0-9]/g, '') || '0';

    return {{
        url: request.url,
        title: title,
        content: content,
        author: author,
        views: parseInt(views, 10),
        likes: parseInt(likes, 10),
        comments_count: parseInt(comments, 10),
    }};
}}
"""

    def fetch_best_posts(
        self,
        platform: str = "natepann",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """플랫폼의 베스트 게시글 목록을 크롤링합니다.

        Args:
            platform: 플랫폼 이름
            limit: 가져올 게시글 수

        Returns:
            게시글 데이터 리스트
        """
        # 베스트 페이지 URL 매핑
        best_urls = {
            "natepann": "https://pann.nate.com/talk/ranking/d",
            "dcinside": "https://www.dcinside.com/",
            "instiz": "https://www.instiz.net/pt/",
            "fmkorea": "https://www.fmkorea.com/best",
            "ruliweb": "https://bbs.ruliweb.com/best/humor",
        }

        base_url = best_urls.get(platform)
        if not base_url:
            logger.warning(f"지원하지 않는 플랫폼: {platform}")
            return []

        logger.info(f"{platform} 베스트 게시글 크롤링 (상위 {limit}개)")

        # TODO: 베스트 목록 페이지 크롤링 구현
        # 현재는 단일 URL 크롤링만 지원
        logger.warning("베스트 목록 크롤링은 아직 구현되지 않았습니다")
        return []
