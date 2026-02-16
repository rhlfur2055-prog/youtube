# 변경 사유: v3.0 스크린샷 배경 시스템 통합 (website-content-crawler + 텍스트 기반 스크린샷)
"""커뮤니티 게시글 크롤링 모듈.

Apify cheerio-scraper 또는 website-content-crawler를 사용하여
네이트판, 디시인사이드, 에펨코리아 등 커뮤니티 게시글 본문을 크롤링합니다.
v3.0: 페이지 스크린샷 캡처 및 텍스트 기반 가짜 스크린샷 생성을 지원합니다.
"""

from __future__ import annotations

import os
import re
import textwrap
from typing import Any
from urllib.parse import urlparse

from youshorts.config.settings import Settings, get_settings
from youshorts.security.secrets_manager import SecretsManager
from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

# 도메인별 CSS 셀렉터 매핑
_SELECTORS: dict[str, dict[str, str]] = {
    "pann.nate.com": {
        "title": "h3.tit_view, .post-tit-view h4",
        "body": "#contentArea, .post-content",
    },
    "gall.dcinside.com": {
        "title": ".title_subject span.title_headtext + span, .title_subject",
        "body": ".write_div, .writing_view_box",
    },
    "m.dcinside.com": {
        "title": ".gallview_head .title",
        "body": ".thum-txtin, .writing_view_box",
    },
    "www.fmkorea.com": {
        "title": ".np_18px, .np_18px_span",
        "body": ".xe_content, .document_style",
    },
    "theqoo.net": {
        "title": ".document_title h1, .document_title",
        "body": ".document_style, .xe_content",
    },
    "www.instiz.net": {
        "title": ".title_view, .subject",
        "body": ".memo_content, .memo_view",
    },
}

# 범용 폴백 셀렉터
_FALLBACK_SELECTORS = {
    "title": "h1, h2, .title, .subject, [class*=title], [class*=subject]",
    "body": (
        "article, .content, .post-content, .view-content, "
        "[class*=content], [class*=body], main"
    ),
}

# 본문 최대 글자수
_MAX_BODY_LENGTH = 3000

# 커뮤니티 소스 라벨 매핑
_SOURCE_LABELS: dict[str, str] = {
    "dcinside": "디시인사이드 베스트",
    "natepann": "네이트판 HOT",
    "direct": "커뮤니티 글",
    "fallback": "커뮤니티",
    "manual": "썰",
}

# 텍스트 스크린샷 배경 그라데이션 팔레트
_TEXT_SS_GRADIENTS = [
    [(25, 28, 35), (45, 38, 30)],   # 다크블루 → 다크브라운
    [(35, 25, 30), (25, 35, 40)],   # 다크레드 → 다크틸
    [(30, 30, 20), (20, 25, 40)],   # 다크옐로 → 다크블루
    [(20, 30, 25), (35, 25, 35)],   # 다크그린 → 다크퍼플
    [(35, 30, 20), (25, 20, 35)],   # 다크오렌지 → 다크퍼플
    [(25, 25, 35), (35, 30, 25)],   # 다크블루 → 다크브라운
]


def _get_domain(url: str) -> str:
    """URL에서 도메인을 추출합니다."""
    parsed = urlparse(url)
    return parsed.netloc.lower()


def _clean_text(text: str) -> str:
    """크롤링된 텍스트를 정리합니다."""
    # 연속 공백 제거
    text = re.sub(r"\s+", " ", text)
    # 앞뒤 공백 제거
    text = text.strip()
    return text


def _build_page_function(title_sel: str, body_sel: str) -> str:
    """Apify cheerio-scraper용 페이지 함수를 생성합니다."""
    return f"""
async function pageFunction(context) {{
    const {{ $, request }} = context;
    const title = $('{title_sel}').first().text().trim();
    const body = $('{body_sel}').first().text().trim();
    return {{
        url: request.url,
        title: title || '',
        body: body || '',
    }};
}}
"""


def generate_text_screenshots(
    content: str,
    title: str = "",
    source: str = "community",
    output_dir: str = "",
    width: int = 1080,
    height: int = 1920,
) -> list[str]:
    """텍스트 기반 가짜 '커뮤니티 스크린샷'을 생성합니다.

    실제 디시/네이트판 UI를 흉내낸 이미지로,
    스크린샷이 없을 때 배경으로 사용됩니다.

    Args:
        content: 게시글 본문 텍스트.
        title: 게시글 제목.
        source: 소스 식별자 (dcinside, natepann, etc).
        output_dir: 스크린샷 저장 디렉토리.
        width: 이미지 너비.
        height: 이미지 높이.

    Returns:
        생성된 이미지 파일 경로 리스트.
    """
    from PIL import Image, ImageDraw

    from youshorts.utils.fonts import load_font

    if not output_dir:
        settings = get_settings()
        output_dir = os.path.join(settings.temp_dir, "_screenshots")

    os.makedirs(output_dir, exist_ok=True)

    logger.info("텍스트 기반 스크린샷 생성 중...")

    # 내용을 3~6 청크로 분할 (각 청크가 한 장면의 배경)
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    if not paragraphs:
        paragraphs = [content[:200]] if content else ["내용 없음"]

    # 최소 3장, 최대 6장
    chunk_size = max(1, len(paragraphs) // 5)
    text_chunks: list[str] = []
    for i in range(0, len(paragraphs), max(1, chunk_size)):
        chunk = "\n".join(paragraphs[i:i + chunk_size])
        if chunk.strip():
            text_chunks.append(chunk[:300])
    text_chunks = text_chunks[:6] if text_chunks else ["내용 없음"]

    font = load_font(36)
    title_font = load_font(44)

    paths: list[str] = []
    for idx, chunk_text in enumerate(text_chunks):
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)

        # 커뮤니티 느낌의 그라데이션 배경
        c1, c2 = _TEXT_SS_GRADIENTS[idx % len(_TEXT_SS_GRADIENTS)]
        for y in range(height):
            ratio = y / height
            r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
            g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
            b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # 상단: 소스 표시 바
        bar_h = 80
        draw.rectangle([(0, 0), (width, bar_h)], fill=(18, 18, 22))
        label = _SOURCE_LABELS.get(source, "커뮤니티")
        draw.text((30, 20), label, fill=(180, 180, 180), font=font)

        # 제목 영역 (첫 번째 장에만)
        y_offset = bar_h + 30
        if idx == 0 and title:
            title_wrapped = textwrap.fill(title[:40], width=20)
            draw.rectangle(
                [(40, y_offset), (width - 40, y_offset + 120)],
                fill=(30, 30, 30),
                outline=(80, 80, 80),
                width=1,
            )
            draw.text(
                (60, y_offset + 15), title_wrapped,
                fill=(255, 255, 255), font=title_font,
            )
            y_offset += 140

        # 본문 텍스트 (커뮤니티 글 느낌)
        wrapped_lines: list[str] = []
        for line in chunk_text.split("\n"):
            wrapped = textwrap.fill(line, width=24)  # 세로 화면이라 좁게
            wrapped_lines.extend(wrapped.split("\n"))

        text_y = y_offset + 40
        for line in wrapped_lines[:20]:  # 최대 20줄
            if text_y > height - 200:
                break
            # 약간의 투명 배경
            try:
                bbox = draw.textbbox((60, text_y), line, font=font)
                text_w = bbox[2] - bbox[0]
            except Exception:
                text_w = len(line) * 20
            draw.rectangle(
                [(50, text_y - 5), (70 + text_w, text_y + 42)],
                fill=(0, 0, 0),
            )
            draw.text(
                (60, text_y), line,
                fill=(220, 220, 220), font=font,
            )
            text_y += 48

        # 하단: 페이지 표시
        page_text = f"{idx + 1} / {len(text_chunks)}"
        draw.text(
            (width // 2 - 30, height - 80), page_text,
            fill=(120, 120, 120), font=font,
        )

        # 저장
        path = os.path.join(output_dir, f"textss_{idx:02d}.png")
        img.save(path, quality=90)
        paths.append(path)

    logger.info("%d장 스크린샷 이미지 생성", len(paths))
    return paths


def crawl_community_post_with_screenshots(
    url: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """커뮤니티 게시글을 크롤링하고 스크린샷을 캡처합니다.

    Apify website-content-crawler를 사용하여 게시글 텍스트와
    페이지 스크린샷을 동시에 수집합니다.
    스크린샷이 없으면 텍스트 기반 가짜 스크린샷을 생성합니다.

    Args:
        url: 크롤링할 게시글 URL.
        settings: 설정 인스턴스.

    Returns:
        {title, body, source_url, domain, screenshots: [path1, ...]} 딕셔너리.
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
        raise RuntimeError("APIFY_API_TOKEN 환경변수를 설정해주세요.")

    domain = _get_domain(url)
    logger.info("커뮤니티 크롤링 + 스크린샷: %s (도메인: %s)", url, domain)

    client = ApifyClient(token)
    ss_dir = os.path.join(settings.temp_dir, "_screenshots")
    os.makedirs(ss_dir, exist_ok=True)

    title = ""
    body = ""
    screenshots: list[str] = []

    try:
        # website-content-crawler로 스크린샷 포함 크롤링
        run_input: dict[str, Any] = {
            "startUrls": [{"url": url}],
            "crawlerType": "playwright:firefox",
            "maxCrawlPages": 1,
            "maxCrawlDepth": 0,
            "outputFormats": ["markdown"],
            "removeCookieWarnings": True,
            "saveScreenshots": True,
            "screenshotQuality": 80,
            "removeElementsCssSelector": (
                "nav, footer, .ad, .advertisement, "
                "#header, .sidebar, script, style, "
                ".comment_box, .reply_box"
            ),
        }

        run = client.actor("apify/website-content-crawler").call(
            run_input=run_input,
            timeout_secs=120,
        )

        dataset = client.dataset(run["defaultDatasetId"])
        kvs = client.key_value_store(run["defaultKeyValueStoreId"])

        for item in dataset.iterate_items():
            text = item.get("text", "") or item.get("markdown", "")
            title = item.get("metadata", {}).get("title", "")
            body = _clean_text(text)

            # 스크린샷 다운로드
            ss_key = item.get("screenshotUrl", "")
            if ss_key:
                try:
                    record = kvs.get_record(ss_key)
                    if record and record.get("value"):
                        ss_path = os.path.join(ss_dir, "screenshot_0.png")
                        with open(ss_path, "wb") as f:
                            f.write(record["value"])
                        screenshots.append(ss_path)
                        logger.info("스크린샷 저장: %s", ss_path)
                except Exception as e:
                    logger.warning("스크린샷 다운로드 실패: %s", e)
            break  # 첫 번째 결과만 사용

    except Exception as e:
        logger.warning("website-content-crawler 실패: %s, cheerio-scraper로 폴백", e)

    # website-content-crawler 실패 시 cheerio-scraper 폴백
    if not body:
        logger.info("cheerio-scraper로 폴백 크롤링...")
        result = crawl_community_post(url, settings=settings)
        title = result["title"]
        body = result["body"]

    if not body:
        raise ValueError(f"본문을 추출할 수 없습니다: {url}")

    # 본문 길이 제한
    if len(body) > _MAX_BODY_LENGTH:
        body = body[:_MAX_BODY_LENGTH] + "..."

    # 개인정보 경고
    if re.search(r"\d{3}-\d{4}-\d{4}|\d{6}-\d{7}", body):
        logger.warning("본문에 개인정보(전화번호/주민번호) 패턴이 감지되었습니다.")

    # 스크린샷이 없으면 텍스트 기반 가짜 스크린샷 생성
    if not screenshots:
        source_key = "dcinside" if "dcinside" in domain else (
            "natepann" if "nate" in domain else "direct"
        )
        screenshots = generate_text_screenshots(
            body, title=title, source=source_key,
            output_dir=ss_dir,
            width=settings.video_width,
            height=settings.video_height,
        )

    logger.info("크롤링 완료: '%s' (%d자, %d장 스크린샷)", title[:30], len(body), len(screenshots))

    return {
        "title": title,
        "body": body,
        "source_url": url,
        "domain": domain,
        "screenshots": screenshots,
    }


def crawl_community_post(
    url: str,
    settings: Settings | None = None,
) -> dict[str, str]:
    """커뮤니티 게시글을 크롤링합니다.

    Apify cheerio-scraper Actor를 사용하여 게시글의 제목과 본문을 추출합니다.

    Args:
        url: 크롤링할 게시글 URL.
        settings: 설정 인스턴스.

    Returns:
        {title, body, source_url, domain} 딕셔너리.

    Raises:
        RuntimeError: apify-client 미설치 또는 API 토큰 미설정 시.
        ValueError: 크롤링 결과가 비어있을 때.
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
        raise RuntimeError("APIFY_API_TOKEN 환경변수를 설정해주세요.")

    domain = _get_domain(url)
    logger.info("커뮤니티 크롤링: %s (도메인: %s)", url, domain)

    # 도메인별 셀렉터 선택
    selectors = _SELECTORS.get(domain, _FALLBACK_SELECTORS)
    title_sel = selectors["title"]
    body_sel = selectors["body"]

    client = ApifyClient(token)

    run_input: dict[str, Any] = {
        "startUrls": [{"url": url}],
        "pageFunction": _build_page_function(title_sel, body_sel),
        "maxCrawlingDepth": 0,
        "maxPagesPerCrawl": 1,
    }

    try:
        run = client.actor("apify/cheerio-scraper").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    except Exception as e:
        logger.error("크롤링 실패: %s", e)
        raise ValueError(f"크롤링 실패: {e}") from e

    if not items:
        raise ValueError(f"크롤링 결과가 비어있습니다: {url}")

    item = items[0]
    title = _clean_text(item.get("title", ""))
    body = _clean_text(item.get("body", ""))

    if not body:
        # 폴백 셀렉터로 재시도
        if domain in _SELECTORS:
            logger.info("도메인 셀렉터 실패, 폴백 셀렉터로 재시도...")
            fb_title = _FALLBACK_SELECTORS["title"]
            fb_body = _FALLBACK_SELECTORS["body"]
            run_input["pageFunction"] = _build_page_function(fb_title, fb_body)
            try:
                run = client.actor("apify/cheerio-scraper").call(run_input=run_input)
                items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
                if items:
                    item = items[0]
                    title = title or _clean_text(item.get("title", ""))
                    body = _clean_text(item.get("body", ""))
            except Exception as e:
                logger.warning("폴백 크롤링도 실패: %s", e)

    if not body:
        raise ValueError(f"본문을 추출할 수 없습니다: {url}")

    # 본문 길이 제한
    if len(body) > _MAX_BODY_LENGTH:
        body = body[:_MAX_BODY_LENGTH] + "..."
        logger.info("본문 %d자 → %d자로 잘림", len(item.get("body", "")), _MAX_BODY_LENGTH)

    # 개인정보 경고
    if re.search(r"\d{3}-\d{4}-\d{4}|\d{6}-\d{7}", body):
        logger.warning("본문에 개인정보(전화번호/주민번호) 패턴이 감지되었습니다.")

    logger.info("크롤링 완료: '%s' (%d자)", title[:30], len(body))

    return {
        "title": title,
        "body": body,
        "source_url": url,
        "domain": domain,
    }
