#!/usr/bin/env python3
"""
=============================================================
🎬 YouTube Shorts 팩토리 v5.0 'The Viral Machine'
=============================================================
v4.3 → v5.0 변경사항:
  ✅ 멀티플랫폼 크롤러 (에펨코리아/루리웹/인스티즈/더쿠/네이트판)
  ✅ 플랫폼 자동 감지 본문 추출 (_fetch_article_by_platform)
  ✅ 각 플랫폼별 댓글 추출
  ✅ requests 우선 → Apify 폴백 (전 플랫폼 통일)
v4.2 → v4.3 변경사항:
  ✅ 바이럴 전문 프롬프트 적용 (왜 베스트인지 분석 → 대본)
  ✅ 감정 태그 확장 (excited/shocked/warm/whisper/funny 등)
  ✅ 바이럴 가산점 URL 정렬 (ㅋㅋ/레전드/소름/실화/대박 우선)
  ✅ pause_ms 범위 확대 (반전 800~1200ms, 평소 200~400ms)
  ✅ viral_reason 필드 추가 (왜 베스트인지 한줄)
v4.1 → v4.2 변경사항:
  ✅ 크롤러 2단계 분리 (목록→개별 URL) + UI 키워드 필터링
  ✅ 대본 소스 품질 검증 (200자 미만/스팸 → None)
  ✅ TTS 문장별 개별 생성 (완벽 음성-자막 싱크)
  ✅ Pillow stroke_width 내장 사용 (렌더링 20배 가속)
  ✅ 사인파 앰비언트 드론 BGM (핑크노이즈 → 220+330+440Hz)
  ✅ 디시 실시간베스트/개념글 소스 추가
v4.0 → v4.1 변경사항:
  ✅ 3단 비주얼 레이아웃 (블러배경 + 선명스크린샷 + 타이틀바)
  ✅ Imagen 4.0 맥락 기반 정밀 프롬프트
  ✅ 단어별 하이라이트 Pop + 4px 외곽선 + 5px 그림자
  ✅ Sidechain Ducking -20dB + 공백 80ms
  ✅ Ken Burns + Dynamic Blur + Voice 마스터링
  ✅ 3초 후킹 대본 + 구독 유도 CTA 엔딩
  ✅ upload_info.json 자동 생성

파이프라인:
  [크롤링+스크린샷] Apify → 글 텍스트 + 페이지 캡처
      ↓
  [대본생성] Claude API → 후킹 대본 + SEO 태그 15개
      ↓
  [TTS+자막] edge-tts → 감정별 prosody + WordBoundary 타이밍
      ↓
  [AI 배경] Imagen 4.0 → 핵심 장면 AI 이미지 2~3장
      ↓
  [영상조립] FFmpeg → Dynamic Blur + Ken Burns + 자막 + BGM Ducking
      ↓
  [출력] shorts_제목_날짜.mp4 + upload_info.json

사용법:
  python main.py --source dcinside_realtime_best --count 1
  python main.py --source fmkorea --count 3
  python main.py --source ruliweb --count 2
  python main.py --source theqoo --count 1
  python main.py --source instiz --count 1
  python main.py --source natepann --count 5
  python main.py --url "https://gall.dcinside.com/..."
  python main.py --topic "상견례 파토" --skip-crawl
=============================================================
"""

import argparse
import asyncio
import io
import json
import os
import re
import subprocess
import sys
import time
import math
import textwrap
import shutil
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Windows cp949 콘솔에서 이모지/한글 출력 깨짐 방지
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# .env 파일 로드
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=True)
except ImportError:
    pass  # dotenv 없으면 환경변수에서 직접 읽음

# ============================================================
# 📦 의존성 체크 & 설치
# ============================================================
def _get_ffmpeg_path() -> str:
    """FFmpeg 실행 파일 경로를 찾습니다 (imageio_ffmpeg 우선)."""
    # 1차: imageio_ffmpeg 번들
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.exists(path):
            return path
    except ImportError:
        pass

    # 2차: PATH에서 검색
    ffmpeg_cmd = "where" if sys.platform == "win32" else "which"
    result = subprocess.run([ffmpeg_cmd, "ffmpeg"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode == 0:
        return result.stdout.strip().split("\n")[0].strip()

    return ""


# 전역 FFmpeg 경로 (check_dependencies 후 설정)
FFMPEG_PATH = ""
FFPROBE_PATH = ""


def check_dependencies():
    """필요한 패키지 자동 설치"""
    global FFMPEG_PATH, FFPROBE_PATH

    required = {
        "anthropic": "anthropic",
        "edge_tts": "edge-tts",
        "requests": "requests",
        "apify_client": "apify-client",
        "PIL": "Pillow",
        "imageio_ffmpeg": "imageio-ffmpeg",
        "google.genai": "google-genai",
    }
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            print(f"[+] {package} 설치 중...")
            subprocess.check_call([
                sys.executable, "-m", "pip", "install",
                package, "--break-system-packages", "-q"
            ])

    # FFmpeg 경로 확보
    FFMPEG_PATH = _get_ffmpeg_path()
    if not FFMPEG_PATH:
        if sys.platform == "win32":
            print("[!] FFmpeg가 필요합니다: pip install imageio-ffmpeg")
        else:
            print("[!] FFmpeg가 필요합니다: sudo apt install ffmpeg")
        sys.exit(1)

    # ffprobe 경로 (같은 디렉토리에서 탐색)
    ffmpeg_dir = os.path.dirname(FFMPEG_PATH)
    for name in ["ffprobe", "ffprobe.exe"]:
        probe = os.path.join(ffmpeg_dir, name)
        if os.path.exists(probe):
            FFPROBE_PATH = probe
            break
    if not FFPROBE_PATH:
        # PATH에서 시도
        probe_cmd = "where" if sys.platform == "win32" else "which"
        r = subprocess.run([probe_cmd, "ffprobe"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            FFPROBE_PATH = r.stdout.strip().split("\n")[0].strip()

    print(f"  FFmpeg: {FFMPEG_PATH}")
    if FFPROBE_PATH:
        print(f"  FFprobe: {FFPROBE_PATH}")

check_dependencies()

import anthropic
import edge_tts
import requests
from apify_client import ApifyClient
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from google import genai as google_genai
from google.genai import types as genai_types


# ============================================================
# ⚙️ 설정값
# ============================================================
@dataclass
class Config:
    # API 키
    claude_api_key: str = ""
    apify_api_token: str = ""
    google_api_key: str = ""

    # 크롤링
    source: str = "dcinside"
    gallery: str = "humor"
    crawl_count: int = 3
    target_url: str = ""

    # 대본
    script_style: str = "storytelling"
    max_duration: int = 58
    skip_crawl: bool = False
    manual_topic: str = ""

    # TTS (v3.3: HyunsuNeural + 감정별 prosody)
    tts_voice: str = "ko-KR-HyunsuNeural"
    tts_rate: str = "+5%"
    tts_pitch: str = "-1Hz"

    # 영상
    width: int = 1080
    height: int = 1920
    fps: int = 30
    quality: int = 80

    # 폰트 (자연스러운 한글)
    font_name: str = "NanumSquareRound"
    font_size: int = 56
    font_size_highlight: int = 67

    # v4.0: 비주얼/오디오 설정
    use_ai_bg: bool = True         # Imagen 4.0 AI 배경 사용
    bgm_enabled: bool = True       # BGM + Auto-Ducking

    # 출력
    output_dir: str = "./output"

    def __post_init__(self):
        self.claude_api_key = os.getenv("ANTHROPIC_API_KEY", self.claude_api_key)
        self.apify_api_token = os.getenv("APIFY_API_TOKEN", self.apify_api_token)
        self.google_api_key = os.getenv("GOOGLE_API_KEY", self.google_api_key)
        os.makedirs(self.output_dir, exist_ok=True)


# ============================================================
# 🔤 폰트 매니저 (자연스러운 한글 폰트 자동 설치)
# ============================================================
class FontManager:
    """시스템에 자연스러운 한글 폰트 확보"""

    # 우선순위 폰트 목록
    FONT_PRIORITY = [
        # apt로 설치 가능한 폰트
        ("NanumSquareRound", "fonts-nanum"),
        ("NanumGothic", "fonts-nanum"),
        ("NanumGothicBold", "fonts-nanum"),
        # 기본 내장 가능성
        ("NotoSansCJK-Bold", None),
        ("NotoSansKR-Bold", None),
        ("DejaVuSans", None),
    ]

    @staticmethod
    def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """사용 가능한 가장 좋은 한글 폰트 반환"""
        # 1차: Windows 폰트 디렉토리 검색
        if sys.platform == "win32":
            font_path = FontManager._find_windows_font(bold)
            if font_path:
                return ImageFont.truetype(font_path, size)

        # 2차: fc-list로 시스템 한글 폰트 검색 (Linux/macOS)
        font_path = FontManager._find_system_font(bold)
        if font_path:
            return ImageFont.truetype(font_path, size)

        # 3차: apt로 나눔 폰트 설치 시도 (Linux)
        FontManager._install_nanum_fonts()
        font_path = FontManager._find_system_font(bold)
        if font_path:
            return ImageFont.truetype(font_path, size)

        # 4차: 웹에서 폰트 다운로드 시도
        font_path = FontManager._download_font()
        if font_path:
            return ImageFont.truetype(font_path, size)

        # 최후: 기본 폰트
        print("  [!] 한글 폰트를 찾을 수 없어 기본 폰트 사용")
        return ImageFont.load_default()

    @staticmethod
    def _find_windows_font(bold: bool = False) -> Optional[str]:
        """Windows 폰트 디렉토리에서 한글 폰트 검색"""
        font_dirs = [
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
        ]
        if bold:
            filenames = [
                "NanumSquareRoundB.ttf", "NanumSquareRoundEB.ttf",
                "NanumGothicBold.ttf", "malgunbd.ttf",
            ]
        else:
            filenames = [
                "NanumSquareRoundR.ttf", "NanumSquareRound.ttf",
                "NanumGothic.ttf", "malgun.ttf", "malgunbd.ttf",
            ]
        for font_dir in font_dirs:
            if not os.path.isdir(font_dir):
                continue
            for filename in filenames:
                path = os.path.join(font_dir, filename)
                if os.path.exists(path):
                    return path
        return None

    @staticmethod
    def _find_system_font(bold: bool = False) -> Optional[str]:
        """fc-list로 한글 폰트 경로 찾기 (Linux/macOS)"""
        if sys.platform == "win32":
            return None
        try:
            preferred = [
                "NanumSquareRoundB" if bold else "NanumSquareRoundR",
                "NanumSquareRound",
                "NanumGothicBold" if bold else "NanumGothic",
                "NanumGothic",
                "NotoSansCJK",
                "NotoSansKR",
                "Pretendard",
                "D2Coding",
            ]
            result = subprocess.run(
                ["fc-list", ":lang=ko", "file"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5
            )
            font_lines = result.stdout.strip().split("\n")

            for pref in preferred:
                for line in font_lines:
                    path = line.split(":")[0].strip()
                    if pref.lower() in path.lower() and os.path.exists(path):
                        return path

            # 아무 한글 폰트라도
            for line in font_lines:
                path = line.split(":")[0].strip()
                if os.path.exists(path) and path.endswith((".ttf", ".otf")):
                    return path

        except Exception:
            pass
        return None

    @staticmethod
    def _install_nanum_fonts():
        """apt로 나눔 폰트 설치"""
        try:
            print("  📦 한글 폰트 설치 중 (NanumSquareRound)...")
            subprocess.run(
                ["apt-get", "install", "-y", "-qq",
                 "fonts-nanum", "fonts-nanum-extra"],
                capture_output=True, timeout=30
            )
            subprocess.run(["fc-cache", "-f"], capture_output=True, timeout=10)
        except Exception:
            pass

    @staticmethod
    def _download_font() -> Optional[str]:
        """나눔스퀘어라운드 폰트 다운로드"""
        font_dir = os.path.expanduser("~/.local/share/fonts")
        os.makedirs(font_dir, exist_ok=True)
        font_path = os.path.join(font_dir, "NanumSquareRoundR.ttf")

        if os.path.exists(font_path):
            return font_path

        try:
            # 나눔스퀘어라운드 다운로드 URL
            url = ("https://github.com/nicedoctor/NanumSquareRound/raw/"
                   "master/NanumSquareRoundR.ttf")
            print(f"  📥 폰트 다운로드 중...")
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                with open(font_path, "wb") as f:
                    f.write(resp.content)
                subprocess.run(["fc-cache", "-f"], capture_output=True)
                return font_path
        except Exception:
            pass
        return None


# ============================================================
# 🎨 감정 스타일 (v3: 더 자연스러운 색상)
# ============================================================
EMOTION_STYLES = {
    "anger": {
        "text_color": (255, 80, 80),       # 빨강 (부드럽게)
        "bg_color": (40, 10, 10, 200),      # 어두운 빨강 배경
        "border_color": (255, 60, 60),
    },
    "fun": {
        "text_color": (255, 220, 50),       # 골드 (밝게)
        "bg_color": (40, 35, 5, 200),
        "border_color": (255, 200, 0),
    },
    "surprise": {
        "text_color": (100, 230, 255),      # 하늘색
        "bg_color": (5, 30, 40, 200),
        "border_color": (0, 200, 255),
    },
    "sad": {
        "text_color": (200, 160, 255),      # 라벤더
        "bg_color": (25, 15, 40, 200),
        "border_color": (180, 130, 255),
    },
    "neutral": {
        "text_color": (255, 255, 255),      # 흰색
        "bg_color": (20, 20, 20, 190),
        "border_color": (100, 100, 100),
    },
    "tension": {
        "text_color": (255, 130, 100),      # 코랄
        "bg_color": (40, 15, 10, 200),
        "border_color": (255, 100, 70),
    },
    "relief": {
        "text_color": (130, 255, 190),      # 민트
        "bg_color": (10, 35, 20, 200),
        "border_color": (100, 230, 160),
    },
    "shock": {
        "text_color": (255, 180, 50),       # 주황
        "bg_color": (40, 25, 5, 200),
        "border_color": (255, 150, 0),
    },
}


# ============================================================
# 🕷️ Stage 1: 크롤링 + 스크린샷 캡처
# ============================================================
class CommunityScraper:
    """디시/네이트판 베스트글 크롤링 + 페이지 스크린샷 캡처"""

    SOURCES = {
        "natepann": {
            "best_url": "https://pann.nate.com/talk/ranking/d",
            "name": "네이트판",
            "platform": "natepann",
        },
        "dcinside": {
            "best_url": "https://gall.dcinside.com/board/lists/?id={gallery}&exception_mode=recommend&sort_type=N&page=1",
            "name": "디시인사이드",
            "platform": "dcinside",
        },
        "dcinside_realtime_best": {
            "best_url": "https://gall.dcinside.com/board/lists/?id=dcbest",
            "name": "디시 실시간베스트",
            "platform": "dcinside",
        },
        "dcinside_hit": {
            "best_url": "https://gall.dcinside.com/board/lists/?id=hit",
            "name": "디시 개념글",
            "platform": "dcinside",
        },
        "fmkorea": {
            "best_url": "https://www.fmkorea.com/best",
            "name": "에펨코리아",
            "platform": "fmkorea",
        },
        "ruliweb": {
            "best_url": "https://bbs.ruliweb.com/best/humor/best",
            "name": "루리웹 유머 베스트",
            "platform": "ruliweb",
        },
        "instiz": {
            "best_url": "https://www.instiz.net/pt",
            "name": "인스티즈",
            "platform": "instiz",
        },
        "theqoo": {
            "best_url": "https://theqoo.net/hot",
            "name": "더쿠",
            "platform": "theqoo",
        },
    }

    # UI/광고/소개글/공지글 키워드 (1개라도 포함 → 즉시 차단)
    BLOCK_KEYWORDS = [
        # DC
        "갤러리 이용 안내", "갤러리 이용안내", "이용 안내",
        "갤러리 소개", "갤러리를 소개", "갤러리 개설",
        "마이너 갤러리", "마이너갤러리",
        "CONNECTING HEARTS", "디시인사이드입니다",
        # 공통 공지/안내
        "[공지]", "[필독]", "[안내]", "[운영]", "[규칙]",
        "[Notice]", "[notice]",
        "운영자입니다", "공지사항입니다", "이용규칙",
    ]
    # UI/스팸 키워드 (2개 이상 포함 → 차단)
    UI_KEYWORDS = [
        "갤러리 만들기", "회원가입", "로그인", "광고 문의",
        "이 갤러리를 , , ,", "갤러리 규정", "공지사항",
        "운영 방침", "매니저 신청", "부매니저",
    ]

    # Apify removeElements 강화 셀렉터
    DC_REMOVE_CSS = (
        "nav, footer, .ad, .advertisement, #header, .sidebar, "
        "script, style, .comment_box, .reply_box, "
        ".minor_intro_banner, .dchead_bg, .visit_card, .pop_wrap, "
        ".issue_wrap, .dc_logo, .gnb_bar, .user_info, .fl, "
        ".btn_recommend, .gall_exposure, .ad_bottom_list, .appdown, "
        ".notion_tag, #dchead, .darkmode-layer, .issue_contentbox, "
        ".minor_banner_list, .dcwiki, .listwrap.clear, "
        "#dccon_progress_bar, .repimg_thumb"
    )

    def __init__(self, config: Config):
        self.config = config
        self.client = None
        if config.apify_api_token:
            self.client = ApifyClient(config.apify_api_token)

    def scrape_with_screenshots(self) -> list[dict]:
        """
        베스트글 크롤링 + 스크린샷 캡처
        Returns: [{title, content, url, screenshots: [path1, path2, ...]}]
        """
        print(f"\n{'='*60}")
        print(f"🕷️  Stage 1: 크롤링 + 스크린샷")
        src_name = self.SOURCES.get(self.config.source, {}).get('name', self.config.source)
        print(f"  소스: {src_name}")
        print(f"{'='*60}")

        if self.config.target_url:
            return self._scrape_single_with_screenshot(self.config.target_url)

        if self.client:
            return self._scrape_apify_with_screenshots()

        return self._scrape_fallback_with_fake_screenshots()

    # 디시 공지/소개글 번호 (항상 목록 최상단에 고정, 실제 베스트글이 아님)
    DC_NOTICE_NOS = {
        "30638",   # 실시간베스트 갤러리 이용 안내
        "17784",   # 개념글 갤러리 이용 안내
    }

    # 바이럴 가산점 키워드 (제목에 포함 시 우선 선택)
    VIRAL_BOOST_KEYWORDS = [
        "ㅋㅋ", "레전드", "소름", "실화", "대박",
        "충격", "반전", "웃긴", "미쳤", "역대급",
        "ㄹㅇ", "ㅇㅈ", "개웃", "ㅂㄷㅂㄷ", "헐",
    ]

    def _extract_article_urls_requests(self, list_url: str) -> list[str]:
        """requests로 목록 페이지 HTML에서 개별 글 URL+제목 추출 (바이럴 가산점 정렬)"""
        try:
            import requests as _req
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                "Referer": "https://gall.dcinside.com/",
            }
            r = _req.get(list_url, headers=headers, timeout=15)
            r.encoding = "utf-8"
            html = r.text

            # ── URL + 제목 함께 추출 ──
            url_title_pairs = []

            # 디시: view-msg 속성 <a> 태그 (제목 링크만 정확히 매칭)
            dc_title_links = re.findall(
                r'<a\s+href="(/board/view/\?id=\w+&no=\d+[^"]*)"\s*view-msg\s*[^>]*>'
                r'(.*?)</a>',
                html, re.DOTALL
            )
            for path, inner_html in dc_title_links:
                full = "https://gall.dcinside.com" + path.replace("&amp;", "&")
                # inner_html에서 태그 제거 → 순수 제목 텍스트
                title = re.sub(r'<[^>]+>', '', inner_html).strip()
                if title:
                    url_title_pairs.append((full, title))

            # 폴백: view-msg 없는 일반 패턴
            if not url_title_pairs:
                dc_rows = re.findall(
                    r'<a[^>]*href="(/board/view/\?id=\w+&no=\d+[^"]*)"[^>]*>'
                    r'\s*(?:<[^>]*>)*\s*([^<]{2,})',
                    html
                )
                for path, title in dc_rows:
                    full = "https://gall.dcinside.com" + path.replace("&amp;", "&")
                    url_title_pairs.append((full, title.strip()))

            # 디시: reply_numbox 등 전체 URL (제목 없이, 중복 제거용)
            dc_full_pat = re.findall(
                r'https?://gall\.dcinside\.com/board/view/\?id=\w+&no=\d+[^\s"\'<>]*',
                html
            )
            existing_urls = {u for u, _ in url_title_pairs}
            for u in dc_full_pat:
                if u not in existing_urls:
                    url_title_pairs.append((u, ""))

            # 네이트판: /talk/숫자
            nate_pat = re.findall(r'href="(/talk/\d+)"', html)
            for path in nate_pat:
                url_title_pairs.append(("https://pann.nate.com" + path, ""))

            nate_full = re.findall(r'https?://pann\.nate\.com/talk/\d+', html)
            for u in nate_full:
                url_title_pairs.append((u, ""))

            # 에펨코리아: /숫자 (document_srl 10자리)
            fm_links = re.findall(
                r'<a[^>]*href="(/\d{8,})"[^>]*>(.*?)</a>', html, re.DOTALL
            )
            for path, inner in fm_links:
                full = "https://www.fmkorea.com" + path
                title = re.sub(r'<[^>]+>', '', inner).strip()
                url_title_pairs.append((full, title))

            # 루리웹: bbs.ruliweb.com/.../read/숫자
            ruli_links = re.findall(
                r'<a[^>]*href="(https?://bbs\.ruliweb\.com/[^"]*read/\d+)"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )
            for href, inner in ruli_links:
                title = re.sub(r'<[^>]+>', '', inner).strip()
                if title and len(title) > 3:
                    url_title_pairs.append((href, title))

            # 인스티즈: /pt/숫자
            instiz_links = re.findall(
                r'href="(?:https?://www\.instiz\.net)?(/pt/\d+)[^"]*"', html
            )
            for path in instiz_links:
                url_title_pairs.append(("https://www.instiz.net" + path, ""))

            # 더쿠: /hot/숫자
            theqoo_links = re.findall(
                r'href="(/hot/\d{5,})"', html
            )
            for path in theqoo_links:
                url_title_pairs.append(("https://theqoo.net" + path, ""))

            # ── 공지/소개글 필터링 ──
            filtered = []
            for u, title in url_title_pairs:
                no_m = re.search(r'no=(\d+)', u)
                if no_m and no_m.group(1) in self.DC_NOTICE_NOS:
                    continue
                if no_m and ("dcbest" in u or "hit" in u):
                    if int(no_m.group(1)) < 100000:
                        continue
                if title and any(kw in title for kw in self.BLOCK_KEYWORDS):
                    continue
                filtered.append((u, title))

            # ── 바이럴 가산점 정렬 (키워드 많을수록 상위) ──
            def _viral_score(pair):
                _, t = pair
                return sum(1 for kw in self.VIRAL_BOOST_KEYWORDS if kw in t)

            filtered.sort(key=_viral_score, reverse=True)

            # 제목 정보를 인스턴스에 저장 (후속 단계에서 활용)
            self._url_titles = {u: t for u, t in filtered if t}

            result_urls = [u for u, _ in filtered]
            if result_urls:
                top_title = filtered[0][1] if filtered[0][1] else "(제목 미확인)"
                print(f"  ✅ requests로 {len(result_urls)}개 URL 추출 (공지 제외)")
                print(f"     🔥 1순위: {top_title[:50]}")
            else:
                print(f"  ⚠️  requests HTML에서 URL 미발견")
            return result_urls

        except Exception as e:
            print(f"  ⚠️  requests 목록 가져오기 실패: {e}")
            return []

    def _extract_article_urls_apify(self, list_url: str) -> list[str]:
        """Apify로 목록 페이지에서 개별 글 URL 추출 (폴백)"""
        try:
            list_input = {
                "startUrls": [{"url": list_url}],
                "crawlerType": "playwright:firefox",
                "maxCrawlPages": 1,
                "maxCrawlDepth": 0,
                "outputFormats": ["markdown"],
                "removeCookieWarnings": True,
                "saveScreenshots": False,
            }
            list_run = self.client.actor("apify/website-content-crawler").call(
                run_input=list_input, timeout_secs=120,
            )

            urls = []
            list_dataset = self.client.dataset(list_run["defaultDatasetId"])
            for item in list_dataset.iterate_items():
                page_text = item.get("text", "") or item.get("markdown", "")

                dc_pat = re.findall(
                    r'https?://gall\.dcinside\.com/board/view/\?id=\w+&no=\d+[^\s"\'<>]*',
                    page_text + " " + str(item)
                )
                urls.extend(dc_pat)

                nate_pat = re.findall(
                    r'https?://pann\.nate\.com/talk/\d+',
                    page_text + " " + str(item)
                )
                urls.extend(nate_pat)

            return urls

        except Exception as e:
            print(f"  ⚠️  Apify 목록 크롤링 실패: {e}")
            return []

    def _scrape_apify_with_screenshots(self) -> list[dict]:
        """
        v4.2: 2단계 크롤링 — 목록→URL 추출→개별 글 크롤링
        [1단계] 글 목록 페이지에서 개별 글 URL만 추출
        [2단계] 각 개별 글 URL을 별도로 크롤링 + 스크린샷
        """
        source_info = self.SOURCES[self.config.source]
        url = source_info["best_url"]
        if self.config.source == "dcinside":
            url = url.format(gallery=self.config.gallery)
        # dcinside_realtime_best, dcinside_hit은 format 불필요

        print(f"  🔗 목록 URL: {url}")
        print(f"  📡 [1단계] 글 목록에서 개별 URL 추출 중...")

        try:
            # ━━ 1단계: 목록 페이지에서 개별 글 URL 추출 ━━
            # requests로 직접 가져오기 (Apify보다 빠르고 무료)
            article_urls = self._extract_article_urls_requests(url)

            # requests 실패 시 Apify 폴백
            if not article_urls and self.client:
                print(f"  📡 requests 실패, Apify로 1단계 재시도...")
                article_urls = self._extract_article_urls_apify(url)

            # 중복 제거 + 제한
            seen = set()
            unique_urls = []
            for u in article_urls:
                base = re.sub(r'&page=\d+', '', u)
                if base not in seen:
                    seen.add(base)
                    unique_urls.append(u)
            unique_urls = unique_urls[:self.config.crawl_count]

            if not unique_urls:
                print(f"  ⚠️  개별 글 URL을 찾지 못했습니다. 폴백 시도...")
                return self._scrape_fallback_with_fake_screenshots()

            print(f"  ✅ {len(unique_urls)}개 글 URL 추출 완료")
            for u in unique_urls:
                print(f"     📄 {u[:80]}")

            # ━━ 2단계: 각 개별 글 크롤링 + 스크린샷 ━━
            print(f"  📡 [2단계] 개별 글 크롤링 + 스크린샷...")
            posts = []

            for art_idx, art_url in enumerate(unique_urls):
                # 1단계에서 가져온 제목 정보 활용
                known_title = getattr(self, '_url_titles', {}).get(art_url, "")
                title_display = known_title[:40] if known_title else art_url[:60]
                print(f"  📖 [{art_idx+1}/{len(unique_urls)}] {title_display}...")

                post = None

                # ── requests로 본문 먼저 시도 (빠르고 안정적) ──
                try:
                    req_post = self._fetch_article_by_platform(art_url)
                    if req_post and len(req_post.get("content", "")) >= 200:
                        # 품질 필터
                        text = req_post["content"]
                        title = req_post["title"]
                        if any(kw in text for kw in self.BLOCK_KEYWORDS):
                            blk = [kw for kw in self.BLOCK_KEYWORDS if kw in text]
                            print(f"     🚫 소개/공지글 차단: {blk[0]}")
                            continue
                        if any(kw in title for kw in self.BLOCK_KEYWORDS):
                            print(f"     🚫 제목에서 소개글 감지, 건너뜀")
                            continue
                        spam_count = sum(1 for kw in self.UI_KEYWORDS if kw in text)
                        if spam_count >= 2:
                            print(f"     ⚠️  UI 텍스트 감지 ({spam_count}개), 건너뜀")
                            continue
                        post = req_post
                        print(f"     ✅ requests 본문 확보 ({len(text)}자)")
                except Exception as e:
                    print(f"     ⚠️  requests 실패: {e}")

                # ── requests 실패 시 Apify 폴백 ──
                if not post:
                    try:
                        art_input = {
                            "startUrls": [{"url": art_url}],
                            "crawlerType": "playwright:firefox",
                            "maxCrawlPages": 1,
                            "maxCrawlDepth": 0,
                            "outputFormats": ["markdown"],
                            "removeCookieWarnings": True,
                            "saveScreenshots": True,
                            "screenshotQuality": 80,
                            "removeElementsCssSelector": self.DC_REMOVE_CSS,
                        }
                        art_run = self.client.actor("apify/website-content-crawler").call(
                            run_input=art_input, timeout_secs=120,
                        )

                        art_dataset = self.client.dataset(art_run["defaultDatasetId"])
                        art_kvs = self.client.key_value_store(art_run["defaultKeyValueStoreId"])

                        for item in art_dataset.iterate_items():
                            text = item.get("text", "") or item.get("markdown", "")
                            if len(text) < 200:
                                continue
                            if any(kw in text for kw in self.BLOCK_KEYWORDS):
                                blk = [kw for kw in self.BLOCK_KEYWORDS if kw in text]
                                print(f"     🚫 소개/공지글 차단: {blk[0]}")
                                continue
                            item_title = item.get("metadata", {}).get("title", "")
                            if any(kw in item_title for kw in self.BLOCK_KEYWORDS):
                                print(f"     🚫 제목에서 소개글 감지, 건너뜀")
                                continue
                            spam_count = sum(1 for kw in self.UI_KEYWORDS if kw in text)
                            if spam_count >= 2:
                                continue

                            post = {
                                "title": item_title or "제목없음",
                                "content": text[:3000],
                                "url": item.get("url", art_url),
                                "source": self.config.source,
                                "screenshots": [],
                            }
                            # 스크린샷 다운로드
                            ss_key = item.get("screenshotUrl", "")
                            if ss_key:
                                ss_path = self._download_screenshot(
                                    art_kvs, ss_key, len(posts)
                                )
                                if ss_path:
                                    post["screenshots"].append(ss_path)
                            break

                    except Exception as e:
                        print(f"     ⚠️  Apify 폴백도 실패: {e}")

                if post:
                    posts.append(post)

            # 스크린샷 없는 글 → 텍스트 기반 생성
            for post in posts:
                if not post["screenshots"]:
                    fake_ss = self._generate_text_screenshots(post)
                    post["screenshots"] = fake_ss

            if not posts:
                print(f"  ⚠️  크롤링된 글 중 본문이 있는 글이 없습니다")
                return self._scrape_fallback_with_fake_screenshots()

            print(f"  ✅ {len(posts)}개 글 수집 완료! (본문 확인됨)")
            for p in posts:
                print(f"     📄 {p['title'][:30]} ({len(p['content'])}자)")
            return posts

        except Exception as e:
            print(f"  ⚠️  Apify 에러: {e}")
            return self._scrape_fallback_with_fake_screenshots()

    def _scrape_single_with_screenshot(self, url: str) -> list[dict]:
        """단일 URL 크롤링 + 스크린샷"""
        print(f"  🔗 단일 URL: {url}")

        post = {"title": "", "content": "", "url": url,
                "source": "direct", "screenshots": []}

        if self.client:
            try:
                run_input = {
                    "startUrls": [{"url": url}],
                    "crawlerType": "playwright:firefox",
                    "maxCrawlPages": 1,
                    "maxCrawlDepth": 0,
                    "outputFormats": ["markdown"],
                    "saveScreenshots": True,
                    "screenshotQuality": 80,
                }
                run = self.client.actor("apify/website-content-crawler").call(
                    run_input=run_input, timeout_secs=90
                )
                dataset = self.client.dataset(run["defaultDatasetId"])
                for item in dataset.iterate_items():
                    post["title"] = item.get("metadata", {}).get("title", "")
                    post["content"] = (
                        item.get("text", "") or item.get("markdown", "")
                    )[:3000]

                    # 스크린샷
                    ss_key = item.get("screenshotUrl", "")
                    if ss_key:
                        kvs = self.client.key_value_store(
                            run["defaultKeyValueStoreId"]
                        )
                        ss_path = self._download_screenshot(kvs, ss_key, 0)
                        if ss_path:
                            post["screenshots"].append(ss_path)
                    break

            except Exception as e:
                print(f"  ⚠️  Apify 에러: {e}, 폴백 시도...")

        # 내용이 없으면 requests 폴백
        if not post["content"]:
            post = self._fetch_simple(url)

        # 스크린샷 없으면 텍스트 기반 생성
        if not post["screenshots"]:
            post["screenshots"] = self._generate_text_screenshots(post)

        return [post]

    def _download_screenshot(self, kvs, key: str, idx: int) -> Optional[str]:
        """Apify KVS에서 스크린샷 다운로드"""
        try:
            ss_dir = os.path.join(self.config.output_dir, "_screenshots")
            os.makedirs(ss_dir, exist_ok=True)
            path = os.path.join(ss_dir, f"screenshot_{idx}.png")

            record = kvs.get_record(key)
            if record and record.get("value"):
                with open(path, "wb") as f:
                    f.write(record["value"])
                print(f"  📸 스크린샷 저장: {path}")
                return path
        except Exception:
            pass
        return None

    def _fetch_dc_article_requests(self, url: str) -> Optional[dict]:
        """requests로 디시 개별 글 본문+댓글 직접 추출 (Apify 불필요, 빠름)"""
        try:
            import requests as _req
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                "Referer": "https://gall.dcinside.com/",
            }
            r = _req.get(url, headers=headers, timeout=15)
            r.encoding = "utf-8"
            html = r.text

            # 제목 추출
            title = ""
            title_m = re.search(r'<span\s+class="title_subject">(.*?)</span>', html)
            if title_m:
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
            if not title:
                title_m = re.search(r'<title>(.*?)</title>', html)
                title = title_m.group(1).strip() if title_m else ""

            # 본문 추출 (write_div 영역)
            body = ""
            body_m = re.search(
                r'<div\s+class="write_div"[^>]*>(.*?)</div>\s*(?:<div\s+class="btn)',
                html, re.DOTALL
            )
            if not body_m:
                body_m = re.search(
                    r'<div\s+class="write_div"[^>]*>(.*?)</div>',
                    html, re.DOTALL
                )
            if body_m:
                raw = body_m.group(1)
                # <br> → 줄바꿈, 태그 제거
                raw = re.sub(r'<br\s*/?>', '\n', raw)
                raw = re.sub(r'<[^>]+>', ' ', raw)
                raw = re.sub(r'&[a-zA-Z]+;', ' ', raw)
                raw = re.sub(r'&#\d+;', ' ', raw)
                body = re.sub(r'\s+', ' ', raw).strip()

            # 댓글 추출 (베스트 댓글 우선)
            comments = []
            cmt_matches = re.findall(
                r'<p\s+class="usertxt\s*[^"]*">(.*?)</p>', html
            )
            for cmt in cmt_matches[:5]:
                cmt_text = re.sub(r'<[^>]+>', '', cmt).strip()
                if cmt_text and len(cmt_text) > 5:
                    comments.append(cmt_text)

            if not body or len(body) < 50:
                return None

            return {
                "title": title,
                "content": body[:3000],
                "url": url,
                "source": self.config.source,
                "comments": comments,
                "screenshots": [],
            }

        except Exception as e:
            return None

    def _fetch_article_by_platform(self, url: str) -> Optional[dict]:
        """URL 기반으로 플랫폼 자동 감지 → 해당 플랫폼 파서로 본문 추출"""
        if "dcinside.com" in url:
            return self._fetch_dc_article_requests(url)
        elif "fmkorea.com" in url:
            return self._fetch_fmkorea_article(url)
        elif "ruliweb.com" in url:
            return self._fetch_ruliweb_article(url)
        elif "instiz.net" in url:
            return self._fetch_instiz_article(url)
        elif "theqoo.net" in url:
            return self._fetch_theqoo_article(url)
        elif "pann.nate.com" in url:
            return self._fetch_natepann_article(url)
        return None

    _REQ_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    }

    def _clean_html(self, raw: str) -> str:
        """HTML 태그 제거 + 공백 정리"""
        raw = re.sub(r'<br\s*/?>', '\n', raw)
        raw = re.sub(r'<[^>]+>', ' ', raw)
        raw = re.sub(r'&[a-zA-Z]+;', ' ', raw)
        raw = re.sub(r'&#\d+;', ' ', raw)
        return re.sub(r'\s+', ' ', raw).strip()

    def _fetch_fmkorea_article(self, url: str) -> Optional[dict]:
        """에펨코리아 개별 글 본문 추출"""
        try:
            import requests as _req
            r = _req.get(url, headers=self._REQ_HEADERS, timeout=15)
            r.encoding = "utf-8"
            html = r.text

            title = ""
            title_m = re.search(r'<title>(.*?)</title>', html)
            if title_m:
                title = self._clean_html(title_m.group(1))

            # document_* 클래스 또는 xe_content
            body = ""
            body_m = re.search(
                r'class="document_\d+_\d+\s+[^"]*xe_content[^"]*"[^>]*>(.*?)</div>\s*(?:<div|<script)',
                html, re.DOTALL
            )
            if not body_m:
                body_m = re.search(r'class="xe_content"[^>]*>(.*?)</div>', html, re.DOTALL)
            if body_m:
                body = self._clean_html(body_m.group(1))

            # 댓글 추출
            comments = []
            cmt_matches = re.findall(r'class="xe_content"[^>]*>(.*?)</div>', html)
            for i, cmt in enumerate(cmt_matches[1:6]):  # 첫 번째는 본문
                cmt_text = self._clean_html(cmt)
                if cmt_text and 5 < len(cmt_text) < 200:
                    comments.append(cmt_text)

            if not body or len(body) < 50:
                return None

            return {
                "title": title,
                "content": body[:3000],
                "url": url,
                "source": "fmkorea",
                "comments": comments,
                "screenshots": [],
            }
        except Exception:
            return None

    def _fetch_ruliweb_article(self, url: str) -> Optional[dict]:
        """루리웹 개별 글 본문 추출"""
        try:
            import requests as _req
            r = _req.get(url, headers=self._REQ_HEADERS, timeout=15)
            r.encoding = "utf-8"
            html = r.text

            title = ""
            title_m = re.search(r'<title>(.*?)</title>', html)
            if title_m:
                title = self._clean_html(title_m.group(1))

            body = ""
            # view_content 클래스 (autolink 등 뒤에 올 수 있음)
            body_m = re.search(
                r'class="view_content[^"]*"[^>]*>(.*?)<div\s+class="(?:view_bottom|board_bottom|row)',
                html, re.DOTALL
            )
            if not body_m:
                body_m = re.search(r'class="view_content[^"]*"[^>]*>(.*?)</article>', html, re.DOTALL)
            if body_m:
                body = self._clean_html(body_m.group(1))

            # 댓글
            comments = []
            cmt_matches = re.findall(r'class="text_wrapper[^"]*"[^>]*>(.*?)</div>', html)
            for cmt in cmt_matches[:5]:
                cmt_text = self._clean_html(cmt)
                if cmt_text and 5 < len(cmt_text) < 200:
                    comments.append(cmt_text)

            if not body or len(body) < 50:
                return None

            return {
                "title": title,
                "content": body[:3000],
                "url": url,
                "source": "ruliweb",
                "comments": comments,
                "screenshots": [],
            }
        except Exception:
            return None

    def _fetch_instiz_article(self, url: str) -> Optional[dict]:
        """인스티즈 개별 글 본문 추출"""
        try:
            import requests as _req
            r = _req.get(url, headers=self._REQ_HEADERS, timeout=15)
            r.encoding = "utf-8"
            html = r.text

            title = ""
            title_m = re.search(r'<title>(.*?)</title>', html)
            if title_m:
                title = self._clean_html(title_m.group(1))
                # "- 인스티즈(instiz) ..." 접미사 제거
                title = re.sub(r'\s*-\s*인스티즈.*$', '', title)

            body = ""
            body_m = re.search(r'class="memo_content[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
            if not body_m:
                body_m = re.search(r'id="memo_content_\d+"[^>]*>(.*?)</div>', html, re.DOTALL)
            if body_m:
                body = self._clean_html(body_m.group(1))

            # 댓글
            comments = []
            cmt_matches = re.findall(r'class="reply_content[^"]*"[^>]*>(.*?)</div>', html)
            for cmt in cmt_matches[:5]:
                cmt_text = self._clean_html(cmt)
                if cmt_text and 5 < len(cmt_text) < 200:
                    comments.append(cmt_text)

            if not body or len(body) < 50:
                return None

            return {
                "title": title,
                "content": body[:3000],
                "url": url,
                "source": "instiz",
                "comments": comments,
                "screenshots": [],
            }
        except Exception:
            return None

    def _fetch_theqoo_article(self, url: str) -> Optional[dict]:
        """더쿠 개별 글 본문 추출 (Rhymix/XE CMS 기반)"""
        try:
            import requests as _req
            r = _req.get(url, headers=self._REQ_HEADERS, timeout=15)
            r.encoding = "utf-8"
            html = r.text

            title = ""
            title_m = re.search(r'<title>(.*?)</title>', html)
            if title_m:
                title = self._clean_html(title_m.group(1))
                title = re.sub(r'\s*-\s*더쿠.*$', '', title)

            body = ""
            # xe_content / rhymix_content
            body_m = re.search(
                r'class="[^"]*xe_content[^"]*"[^>]*>(.*?)</div>\s*(?:<div\s+class="(?:document_|rd_body|comment)|<script)',
                html, re.DOTALL
            )
            if not body_m:
                body_m = re.search(r'class="[^"]*xe_content[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
            if body_m:
                body = self._clean_html(body_m.group(1))

            # 댓글
            comments = []
            cmt_matches = re.findall(r'class="[^"]*xe_content[^"]*"[^>]*>(.*?)</div>', html)
            for cmt in cmt_matches[1:6]:
                cmt_text = self._clean_html(cmt)
                if cmt_text and 5 < len(cmt_text) < 200:
                    comments.append(cmt_text)

            if not body or len(body) < 50:
                return None

            return {
                "title": title,
                "content": body[:3000],
                "url": url,
                "source": "theqoo",
                "comments": comments,
                "screenshots": [],
            }
        except Exception:
            return None

    def _fetch_natepann_article(self, url: str) -> Optional[dict]:
        """네이트판 개별 글 본문 추출"""
        try:
            import requests as _req
            r = _req.get(url, headers=self._REQ_HEADERS, timeout=15)
            r.encoding = "utf-8"
            html = r.text

            title = ""
            title_m = re.search(r'<title>(.*?)</title>', html)
            if title_m:
                title = self._clean_html(title_m.group(1))

            body = ""
            body_m = re.search(r'id="contentArea"[^>]*>(.*?)</div>', html, re.DOTALL)
            if not body_m:
                body_m = re.search(r'class="posting_area[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
            if body_m:
                body = self._clean_html(body_m.group(1))

            # 댓글
            comments = []
            cmt_matches = re.findall(r'class="txt_detail[^"]*"[^>]*>(.*?)</p>', html)
            for cmt in cmt_matches[:5]:
                cmt_text = self._clean_html(cmt)
                if cmt_text and 5 < len(cmt_text) < 200:
                    comments.append(cmt_text)

            if not body or len(body) < 50:
                return None

            return {
                "title": title,
                "content": body[:3000],
                "url": url,
                "source": "natepann",
                "comments": comments,
                "screenshots": [],
            }
        except Exception:
            return None

    def _fetch_simple(self, url: str) -> dict:
        """requests 폴백 크롤링"""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                )
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.encoding = "utf-8"

            from html.parser import HTMLParser

            class TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.texts = []
                    self.skip = False
                def handle_starttag(self, tag, attrs):
                    if tag in ("script", "style", "nav", "footer"):
                        self.skip = True
                def handle_endtag(self, tag):
                    if tag in ("script", "style", "nav", "footer"):
                        self.skip = False
                def handle_data(self, data):
                    if not self.skip and data.strip():
                        self.texts.append(data.strip())

            parser = TextExtractor()
            parser.feed(resp.text)
            content = "\n".join(parser.texts)

            title_match = re.search(r"<title>(.*?)</title>", resp.text)
            title = title_match.group(1) if title_match else "크롤링된 글"

            return {
                "title": title,
                "content": content[:3000],
                "url": url,
                "source": "fallback",
                "screenshots": [],
            }
        except Exception as e:
            print(f"  ❌ 크롤링 실패: {e}")
            return {"title": "실패", "content": "", "url": url,
                    "source": "error", "screenshots": []}

    def _scrape_fallback_with_fake_screenshots(self) -> list[dict]:
        """Apify 없을 때 폴백 + 텍스트 스크린샷 생성"""
        source_info = self.SOURCES[self.config.source]
        url = source_info["best_url"]
        if self.config.source == "dcinside":
            url = url.format(gallery=self.config.gallery)
        post = self._fetch_simple(url)
        post["screenshots"] = self._generate_text_screenshots(post)
        return [post]

    def _generate_text_screenshots(self, post: dict) -> list[str]:
        """
        🎨 텍스트 기반 가짜 '커뮤니티 스크린샷' 생성
        실제 디시/네이트판 UI를 흉내낸 이미지
        """
        print(f"  🎨 텍스트 기반 스크린샷 생성 중...")
        ss_dir = os.path.join(self.config.output_dir, "_screenshots")
        os.makedirs(ss_dir, exist_ok=True)

        w, h = self.config.width, self.config.height
        content = post.get("content", "")
        title = post.get("title", "")
        source = post.get("source", "community")

        # 내용을 3~5 청크로 분할 (각 청크가 한 장면의 배경)
        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
        if not paragraphs:
            paragraphs = [content[:200]]

        # 최소 3장, 최대 6장
        chunk_size = max(1, len(paragraphs) // 5)
        text_chunks = []
        for i in range(0, len(paragraphs), max(1, chunk_size)):
            chunk = "\n".join(paragraphs[i:i + chunk_size])
            if chunk.strip():
                text_chunks.append(chunk[:300])
        text_chunks = text_chunks[:6] if text_chunks else ["내용 없음"]

        font = FontManager.get_font(36)
        title_font = FontManager.get_font(44, bold=True)

        paths = []
        for idx, chunk_text in enumerate(text_chunks):
            img = Image.new("RGB", (w, h))
            draw = ImageDraw.Draw(img)

            # 커뮤니티 느낌의 그라데이션 배경
            # (어두운 배경 + 본문 텍스트 = 디시/네이트판 느낌)
            colors = [
                [(25, 28, 35), (45, 38, 30)],   # 다크블루 → 다크브라운
                [(35, 25, 30), (25, 35, 40)],   # 다크레드 → 다크틸
                [(30, 30, 20), (20, 25, 40)],   # 다크옐로 → 다크블루
                [(20, 30, 25), (35, 25, 35)],   # 다크그린 → 다크퍼플
                [(35, 30, 20), (25, 20, 35)],   # 다크오렌지 → 다크퍼플
                [(25, 25, 35), (35, 30, 25)],   # 다크블루 → 다크브라운
            ]
            c1, c2 = colors[idx % len(colors)]
            for y in range(h):
                ratio = y / h
                r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
                g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
                b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
                draw.line([(0, y), (w, y)], fill=(r, g, b))

            # 상단: 소스 표시 바
            bar_h = 80
            draw.rectangle([(0, 0), (w, bar_h)], fill=(18, 18, 22, 230))
            source_labels = {
                "dcinside": "디시인사이드 베스트",
                "natepann": "네이트판 HOT",
                "direct": "커뮤니티 글",
                "fallback": "커뮤니티",
                "manual": "썰",
            }
            label = source_labels.get(source, "커뮤니티")
            draw.text((30, 20), f"📋 {label}", fill=(180, 180, 180), font=font)

            # 제목 영역 (첫 번째 장에만)
            y_offset = bar_h + 30
            if idx == 0 and title:
                # 제목 배경 박스
                title_wrapped = textwrap.fill(title[:40], width=20)
                draw.rectangle(
                    [(40, y_offset), (w - 40, y_offset + 120)],
                    fill=(255, 255, 255, 15),
                    outline=(80, 80, 80),
                    width=1
                )
                draw.text(
                    (60, y_offset + 15), title_wrapped,
                    fill=(255, 255, 255), font=title_font
                )
                y_offset += 140

            # 본문 텍스트 (커뮤니티 글 느낌)
            # 줄바꿈 처리
            wrapped_lines = []
            for line in chunk_text.split("\n"):
                wrapped = textwrap.fill(line, width=24)  # 세로 화면이라 좁게
                wrapped_lines.extend(wrapped.split("\n"))

            text_y = y_offset + 40
            for line in wrapped_lines[:20]:  # 최대 20줄
                if text_y > h - 200:
                    break
                # 약간의 투명 배경
                bbox = draw.textbbox((60, text_y), line, font=font)
                text_w = bbox[2] - bbox[0]
                draw.rectangle(
                    [(50, text_y - 5), (70 + text_w, text_y + 42)],
                    fill=(0, 0, 0, 60)
                )
                draw.text(
                    (60, text_y), line,
                    fill=(220, 220, 220), font=font
                )
                text_y += 48

            # 하단: 페이지 표시
            page_text = f"{idx + 1} / {len(text_chunks)}"
            draw.text(
                (w // 2 - 30, h - 80), page_text,
                fill=(120, 120, 120), font=font
            )

            # 저장
            path = os.path.join(ss_dir, f"textss_{idx:02d}.png")
            img.save(path, quality=90)
            paths.append(path)

        print(f"  ✅ {len(paths)}장 스크린샷 이미지 생성")
        return paths


# ============================================================
# 📝 Stage 2: 대본 생성 (Claude API) — v3 업그레이드
# ============================================================
class ScriptGenerator:
    """v4.3: 한국 인터넷 커뮤니티 바이럴 콘텐츠 전문 대본 생성기"""

    SYSTEM_PROMPT = """너는 한국 인터넷 커뮤니티 바이럴 콘텐츠 전문 작가야.
유튜브 숏츠 조회수 100만+ 찍는 대본만 만든다.

## 🎯 핵심: "왜 베스트에 올랐는지"를 꿰뚫어라
- 공감성: "아 나도 ㅋㅋ" 반응 나올 포인트
- 반전력: 결말이 예상 밖인 부분
- 감정 롤러코스터: 웃다가 울다가 소름돋는 구간
- 밈 잠재력: 짤로 퍼질 수 있는 명대사

## 📐 출력 형식 (반드시 JSON만 출력)
```json
{
  "title": "숏츠 제목 (15자 이내, 이모지 포함)",
  "hook": "첫 3초 후킹 멘트 (질문형 or 충격형)",
  "script": [
    {
      "text": "자막 문장 (15자 이내)",
      "emotion": "excited|shocked|warm|sad|funny|serious|whisper|angry|neutral|tension",
      "highlight": false,
      "pause_ms": 0,
      "scene_hint": "배경 이미지 키워드 (영어, 분위기 묘사)"
    }
  ],
  "tags": ["#태그1", ..., "#태그15"],
  "thumbnail_text": "썸네일 텍스트 (5자 이내)",
  "description": "영상 설명 (50자 이내, 해시태그 포함)",
  "viral_reason": "이 글이 베스트 된 이유 한줄 요약"
}
```

## 🎬 대본 구성 규칙
1. **첫 3초 (Hook)**: 시청자가 스크롤을 멈출 후킹 멘트
   - 질문형: "이거 실화냐고요?" / "이런 경험 저만 있나요?"
   - 충격형: "병원에서 절대 안 알려주는 거" / "읽다가 소름돋았습니다"
   - 결말 스포일러형: "결국 이렇게 됐습니다"
2. **본문**: 원글의 핵심 썰을 구어체로 풀어서 전달
   - "~했는데요" "~거든요" "~잖아요" 말투 필수
   - 반전 포인트는 반드시 살려서
   - 댓글 반응도 1~2개 인용 ("댓글에서 난리남 ㅋㅋ", "반응이 실화임")
3. **마무리**: CTA (좋아요/구독 유도) + 여운 한마디
4. **역순 구조**: 결말/반전을 첫 줄에 던짐 → "이 사건의 시작은..."으로 돌아감
5. **문장 길이**: 한 줄 최대 15자 (숏츠 가독성)
6. **감정 변화**: 최소 5가지 이상 감정 전환으로 이탈 방지
7. **highlight**: 핵심 반전/충격/웃음 포인트에 true (25-35%)
8. **분량**: 18~25문장 (50~58초)
9. **pause_ms**: 반전 직전 800~1200ms, 평소 200~400ms (긴장감 극대화)
10. **scene_hint**: AI 이미지 생성용, 영어로 분위기 묘사
11. **tags**: 반드시 15개. SEO 최적화 (#숏츠 #썰 #레전드 등)

## 🚫 절대 금지
- 갤러리 소개글, 이용안내, 공지사항 내용 일체 금지
- "마이너 갤러리", "갤러리 개설", "매니저 신청" 등 운영 관련 멘트 금지
- 네이트판/디시 사이트 UI 설명 금지
- 딱딱한 뉴스 보도체 금지 (구어체만!)
- 실명/개인정보 사용 금지
- 비속어 순화 (자연스럽게)
- 허위사실 추가 금지 (원문 기반 각색만)
- text 필드에 따옴표 사용 시 이스케이프 처리
"""

    def __init__(self, config: Config):
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.claude_api_key)

    def generate(self, post: dict) -> Optional[dict]:
        """커뮤니티 글 → 숏츠 대본. 소스 부족 시 None 반환."""
        print(f"\n{'='*60}")
        print(f"📝 Stage 2: 대본 생성")
        print(f"  제목: {post['title'][:40]}...")
        print(f"{'='*60}")

        content = post.get("content", "")
        title = post.get("title", "")

        # ── 소스 품질 체크 ──
        if len(content) < 200:
            print(f"  ⚠️  소스 내용 부족 ({len(content)}자), 건너뜀")
            return None

        # 소개글/공지글 즉시 차단 (1개만 있어도 OUT)
        block_kw = [
            "갤러리 이용 안내", "갤러리 이용안내", "이용 안내",
            "갤러리 소개", "갤러리를 소개", "갤러리 개설",
            "마이너 갤러리", "마이너갤러리",
            "CONNECTING HEARTS", "디시인사이드입니다",
        ]
        for kw in block_kw:
            if kw in content or kw in title:
                print(f"  🚫 소개/공지글 차단: '{kw}' 발견 → 건너뜀")
                return None

        # UI/스팸 키워드 (2개 이상)
        spam_keywords = [
            "갤러리 만들기", "회원가입", "로그인", "광고 문의",
            "갤러리 규정", "공지사항", "운영 방침", "매니저 신청",
        ]
        spam_count = sum(1 for kw in spam_keywords if kw in content)
        if spam_count >= 2:
            print(f"  ⚠️  UI/광고 텍스트 감지 ({spam_count}개 키워드), 건너뜀")
            return None

        start = time.time()

        # 베스트 댓글 추출
        comments = post.get('comments', [])
        comments_text = ""
        if comments:
            top_comments = comments[:4]
            comments_text = "\n## 베스트 댓글 (반응 활용 가능)\n"
            for c in top_comments:
                comments_text += f"- {c}\n"

        source_name = post.get('source', '커뮤니티')
        user_prompt = f"""[소스 정보]
- 출처: {source_name}
- 원문 제목: {post['title']}

[원문 내용]
{post['content'][:2500]}
{comments_text}
[임무]
이 글이 왜 베스트에 올랐는지 핵심 포인트를 파악하고,
유튜브 숏츠 60초 분량의 대본으로 재구성해라.

[필수 규칙]
1. 첫 3초: 시청자가 스크롤을 멈출 후킹 멘트 (질문형 or 충격형)
   예: "이거 실화냐고요?" / "병원에서 절대 안 알려주는 거" / "읽다가 소름돋았습니다"
2. 본문: 원글의 핵심 썰을 구어체로 풀어서 전달
   - "~했는데요" "~거든요" "~잖아요" 말투 필수
   - 반전 포인트는 반드시 살려서
   - 댓글 반응도 1~2개 인용 ("댓글에서 난리남 ㅋㅋ")
3. 마무리: CTA (좋아요/구독 유도) + 여운 한마디
4. 감정 태그: excited/shocked/warm/sad/funny/serious/whisper/angry/neutral/tension
5. pause_ms: 반전 직전 800~1200ms, 평소 200~400ms
6. scene_hint: AI 이미지 생성용 → 영어로 분위기 묘사
7. viral_reason: 이 글이 왜 베스트인지 한줄로
8. 한 문장 최대 15자 (자막 가독성)
9. 총 18~25문장 (50~58초)
10. JSON만 출력 (다른 텍스트 없이)
"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            elapsed = time.time() - start
            raw = response.content[0].text
            script_data = self._extract_json(raw)

            script_data["_meta"] = {
                "time": f"{elapsed:.1f}s",
                "model": "claude-sonnet-4-20250514",
                "source": post.get("content", "")[:100],
            }

            n = len(script_data.get("script", []))
            print(f"  ✅ 대본 완료! ({elapsed:.1f}초, {n}문장)")
            return script_data

        except Exception as e:
            print(f"  ❌ Claude API 에러: {e}")
            return self._fallback_script(post)

    def generate_from_topic(self, topic: str) -> Optional[dict]:
        # manual topic은 품질 필터를 우회하기 위해 200자 이상 패딩
        padded = (f"'{topic}'에 대한 커뮤니티 썰을 만들어주세요. "
                  f"실제 있을법한 에피소드, 반전과 감정 변화 포함. "
                  f"디테일한 상황 묘사와 사람들의 반응, 댓글 반응까지 포함해서 생생하게 작성. "
                  f"주제: {topic}. 이 주제로 조회수 폭발형 숏츠 대본을 만들어야 합니다.")
        fake = {
            "title": topic,
            "content": padded,
            "source": "manual",
        }
        return self.generate(fake)

    def _extract_json(self, text: str) -> dict:
        json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        raise ValueError("JSON 파싱 실패")

    def _fallback_script(self, post: dict) -> dict:
        t = post["title"][:10]
        return {
            "title": t, "hook": f"{t} 이 사건의 전말",
            "script": [
                {"text": t, "emotion": "surprise", "highlight": True,
                 "pause_ms": 0, "scene_hint": "제목 장면"},
                {"text": "이 이야기의 시작은", "emotion": "neutral",
                 "highlight": False, "pause_ms": 0, "scene_hint": "도입"},
                {"text": "아무도 예상 못했죠", "emotion": "tension",
                 "highlight": False, "pause_ms": 500, "scene_hint": "긴장"},
                {"text": "여러분 생각은?", "emotion": "neutral",
                 "highlight": False, "pause_ms": 0, "scene_hint": "마무리"},
            ],
            "tags": ["#썰", "#레전드"], "thumbnail_text": t[:5],
        }


# ============================================================
# 🔊 Stage 3: TTS + 자막 타이밍
# ============================================================
class TTSEngine:
    """v4.2: 문장별 개별 TTS — 완벽한 음성-자막 싱크

    각 문장을 독립적으로 TTS 생성 → ffprobe로 정확한 길이 측정.
    감정별 rate/pitch를 문장 단위로 적용.
    """

    # 감정별 속도/피치 매핑 (v4.3 확장)
    EMOTION_PROSODY = {
        "neutral":  {"rate": "+5%",  "pitch": "-1Hz"},
        "tension":  {"rate": "+12%", "pitch": "+1Hz"},
        "surprise": {"rate": "+0%",  "pitch": "+3Hz"},
        "anger":    {"rate": "+8%",  "pitch": "-3Hz"},
        "angry":    {"rate": "+8%",  "pitch": "-3Hz"},
        "sad":      {"rate": "-5%",  "pitch": "-4Hz"},
        "fun":      {"rate": "+10%", "pitch": "+2Hz"},
        "funny":    {"rate": "+10%", "pitch": "+2Hz"},
        "shock":    {"rate": "-3%",  "pitch": "+0Hz"},
        "shocked":  {"rate": "-3%",  "pitch": "+0Hz"},
        "relief":   {"rate": "+3%",  "pitch": "-2Hz"},
        "excited":  {"rate": "+15%", "pitch": "+4Hz"},
        "warm":     {"rate": "-2%",  "pitch": "-2Hz"},
        "serious":  {"rate": "+0%",  "pitch": "-3Hz"},
        "whisper":  {"rate": "-8%",  "pitch": "-5Hz"},
    }

    def __init__(self, config: Config):
        self.config = config

    async def generate(self, script_data: dict, work_dir: str) -> list[dict]:
        print(f"\n{'='*60}")
        print(f"🔊 Stage 3: TTS 생성 (문장별 개별 모드 v4.2)")
        print(f"{'='*60}")

        script_lines = script_data.get("script", [])
        chunks = []
        current_ms = 0

        for idx, line in enumerate(script_lines):
            text = line["text"]
            emotion = line.get("emotion", "neutral")
            prosody = self.EMOTION_PROSODY.get(emotion, self.EMOTION_PROSODY["neutral"])

            # 문장 간 간격 (80ms)
            if idx > 0:
                pause_extra = line.get("pause_ms", 0)
                current_ms += 80 + pause_extra

            # 개별 오디오 파일
            audio_path = os.path.join(work_dir, f"sent_{idx:03d}.mp3")

            try:
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=self.config.tts_voice,
                    rate=prosody["rate"],
                    pitch=prosody["pitch"],
                )

                with open(audio_path, "wb") as f:
                    async for ev in communicate.stream():
                        if ev["type"] == "audio":
                            f.write(ev["data"])

                # 빈 파일 체크
                if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 100:
                    raise ValueError(f"빈 오디오 파일: {os.path.getsize(audio_path) if os.path.exists(audio_path) else 0}B")

                # 정확한 길이 측정
                duration_ms = self._get_duration_ms(audio_path)

            except Exception as e:
                print(f"  ⚠️  TTS 실패 [{idx}] {text}: {e}")
                duration_ms = 1500
                # 무음 파일 생성
                subprocess.run([
                    FFMPEG_PATH, "-y", "-f", "lavfi",
                    "-i", f"anoisesrc=a=0.001:c=pink:r=44100:d=1.5",
                    "-c:a", "libmp3lame", "-b:a", "128k", audio_path,
                ], capture_output=True)

            start_ms = current_ms
            end_ms = current_ms + duration_ms

            chunks.append({
                "index": idx,
                "text": text,
                "emotion": emotion,
                "highlight": line.get("highlight", False),
                "scene_hint": line.get("scene_hint", ""),
                "audio_file": audio_path,
                "batch_idx": idx,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": duration_ms,
                "pause_ms": line.get("pause_ms", 0),
            })

            current_ms = end_ms

            emo = emotion[:3]
            marker = "⭐" if line.get("highlight") else "  "
            print(
                f"  🎙️ {marker}[{idx+1:02d}] "
                f"[{emo}|{prosody['rate']}/{prosody['pitch']}] "
                f"{text} ({duration_ms}ms)"
            )

        total = current_ms / 1000
        print(f"\n  ✅ TTS 완료: {len(chunks)}문장, 개별생성, {total:.1f}초")
        return chunks

    def _get_duration_ms(self, path: str) -> int:
        """오디오 파일 길이를 밀리초로 반환합니다."""
        # 1차: ffprobe 사용
        if FFPROBE_PATH:
            try:
                r = subprocess.run(
                    [FFPROBE_PATH, "-v", "quiet", "-show_entries",
                     "format=duration", "-of", "csv=p=0", path],
                    capture_output=True, text=True, encoding="utf-8", errors="replace"
                )
                if r.returncode == 0 and r.stdout.strip():
                    return int(float(r.stdout.strip()) * 1000)
            except Exception:
                pass

        # 2차: ffmpeg -i 로 duration 파싱 (ffprobe 없을 때)
        try:
            r = subprocess.run(
                [FFMPEG_PATH, "-i", path, "-f", "null", "-"],
                capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            # stderr에서 Duration 정보 파싱
            import re as _re
            m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", r.stderr)
            if m:
                h, mi, s, cs = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                return (h * 3600 + mi * 60 + s) * 1000 + cs * 10
        except Exception:
            pass

        return 2000


# ============================================================
# 🎬 Stage 4: 영상 조립 (스크린샷 배경 + 자연스러운 자막)
# ============================================================
class VideoAssembler:
    """
    v3 핵심 변경:
    - 배경: 단색 → 커뮤니티 글 스크린샷 (블러+어둡게)
    - 자막: ASS → Pillow로 프레임별 렌더링 (폰트 자유도 ↑)
    - 장면 전환: 스크린샷 간 부드러운 전환
    """

    def __init__(self, config: Config):
        self.config = config
        self.w = config.width
        self.h = config.height
        self.font = FontManager.get_font(config.font_size)
        self.font_bold = FontManager.get_font(config.font_size_highlight, bold=True)

    def assemble(self, script_data: dict, chunks: list[dict],
                 screenshots: list[str], work_dir: str) -> str:
        """스크린샷 배경 + 자연스러운 자막 → 최종 MP4"""
        print(f"\n{'='*60}")
        print(f"🎬 Stage 4: 영상 조립")
        print(f"  스크린샷: {len(screenshots)}장")
        print(f"{'='*60}")

        # Step 1: 오디오 합치기
        concat_audio = os.path.join(work_dir, "full_audio.mp3")
        self._concat_audio(chunks, concat_audio, work_dir)

        total_ms = max(c["end_ms"] for c in chunks) + 500
        total_sec = total_ms / 1000
        total_frames = int(total_sec * self.config.fps)

        # Step 2: 스크린샷 배경 준비 (블러 + 어둡게)
        bg_frames = self._prepare_backgrounds(
            screenshots, total_frames, script_data, work_dir
        )

        # Step 3: 프레임별 자막 렌더링 → PNG 시퀀스
        frames_dir = os.path.join(work_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        print(f"  🖼️  {total_frames}프레임 렌더링 중...")
        for frame_idx in range(total_frames):
            current_time_ms = (frame_idx / self.config.fps) * 1000

            # 배경 선택 (시간에 따라 스크린샷 전환)
            bg_idx = min(
                int(frame_idx / total_frames * len(bg_frames)),
                len(bg_frames) - 1
            )
            frame = bg_frames[bg_idx].copy()

            # Ken Burns 효과: 느린 줌인 (1.0→1.08x over total duration)
            progress = frame_idx / max(1, total_frames)
            zoom = 1.0 + 0.08 * progress
            if zoom > 1.01:
                zw = int(self.w * zoom)
                zh = int(self.h * zoom)
                frame = frame.resize((zw, zh), Image.LANCZOS)
                left = (zw - self.w) // 2
                top = (zh - self.h) // 2
                frame = frame.crop((left, top, left + self.w, top + self.h))

            # 현재 시간에 해당하는 자막 찾기
            active_chunk = None
            for chunk in chunks:
                if chunk["start_ms"] <= current_time_ms <= chunk["end_ms"]:
                    active_chunk = chunk
                    break

            # 자막 렌더링
            if active_chunk:
                frame = self._render_subtitle(frame, active_chunk, current_time_ms)

            # 상단 타이틀 바 (항상 노출)
            title = script_data.get("title", "")
            if title:
                frame = self._render_title_bar(frame, title, alpha=0.9)

            # 아웃트로: 마지막 2초 구독 유도 CTA
            remaining_sec = (total_ms - current_time_ms) / 1000
            if remaining_sec <= 2.0 and remaining_sec >= 0:
                frame = self._render_cta_outro(frame, remaining_sec)

            # 저장
            frame_path = os.path.join(frames_dir, f"frame_{frame_idx:06d}.png")
            frame.save(frame_path, optimize=True)

            # 진행률
            if frame_idx % (self.config.fps * 5) == 0:
                pct = (frame_idx / total_frames) * 100
                print(f"  📊 렌더링 진행: {pct:.0f}%")

        print(f"  ✅ 프레임 렌더링 완료!")

        # Step 4: FFmpeg로 PNG 시퀀스 + 오디오 → MP4
        title_safe = re.sub(r'[^\w가-힣]', '_',
                            script_data.get("title", "shorts"))[:20]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"shorts_{title_safe}_{timestamp}.mp4"
        output_path = os.path.join(self.config.output_dir, output_filename)

        # 절대 경로로 변환 (Windows FFmpeg 호환)
        abs_frames_pattern = os.path.abspath(
            os.path.join(frames_dir, "frame_%06d.png")
        )
        abs_audio = os.path.abspath(concat_audio)
        abs_output = os.path.abspath(output_path)

        # v3.1: 2-pass 인코딩 — 비디오 2Mbps 보장, AAC 256k@44100Hz
        # 어두운/단순 배경에서도 최소 비트레이트 강제
        print(f"  🔧 FFmpeg 2-pass 인코딩 중...")

        # Pass 1 (분석만, 출력 안 함)
        passlog = os.path.join(work_dir, "ffmpeg2pass")
        null_out = "NUL" if sys.platform == "win32" else "/dev/null"
        cmd_pass1 = [
            FFMPEG_PATH, "-y",
            "-framerate", str(self.config.fps),
            "-i", abs_frames_pattern,
            "-c:v", "libx264",
            "-preset", "fast",
            "-b:v", "2000k",
            "-maxrate", "5000k",
            "-bufsize", "4000k",
            "-pass", "1",
            "-passlogfile", passlog,
            "-pix_fmt", "yuv420p",
            "-an",
            "-f", "null", null_out,
        ]
        result1 = subprocess.run(cmd_pass1, capture_output=True, text=True, encoding="utf-8", errors="replace")

        # Pass 2 (실제 인코딩)
        cmd_pass2 = [
            FFMPEG_PATH, "-y",
            "-framerate", str(self.config.fps),
            "-i", abs_frames_pattern,
            "-i", abs_audio,
            "-c:v", "libx264",
            "-preset", "fast",
            "-b:v", "2000k",
            "-maxrate", "5000k",
            "-bufsize", "4000k",
            "-pass", "2",
            "-passlogfile", passlog,
            "-c:a", "aac",
            "-b:a", "256k",          # 오디오 256kbps AAC
            "-ar", "44100",          # 44.1kHz 샘플레이트
            "-pix_fmt", "yuv420p",
            "-shortest",
            "-metadata", f"title={script_data.get('title', 'Shorts')}",
            abs_output,
        ]

        result = subprocess.run(cmd_pass2, capture_output=True, text=True, encoding="utf-8", errors="replace")

        # 2-pass 로그 정리
        for ext in [".log", "-0.log", "-0.log.mbtree", ".log.mbtree"]:
            logf = passlog + ext
            if os.path.exists(logf):
                os.remove(logf)

        if result.returncode != 0:
            print(f"  ⚠️  FFmpeg 에러: {result.stderr[-500:] if result.stderr else 'unknown'}")
            print(f"  🔄 간소화 버전으로 재시도...")
            return self._assemble_simple_fallback(
                concat_audio, total_sec, chunks, output_path, work_dir
            )

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  ✅ 영상 완성! {output_path} ({size_mb:.1f}MB)")

        # 프레임 정리 (공간 절약)
        shutil.rmtree(frames_dir, ignore_errors=True)
        return output_path

    def _generate_ai_image(self, scene_hint: str, work_dir: str,
                            idx: int, context_text: str = "") -> Optional[str]:
        """
        v4.1: Imagen 4.0 맥락 기반 AI 배경 — scene_hint의 '상황+분위기' 정밀 반영
        context_text: 해당 장면의 대본 문장 (맥락 보강용)
        """
        api_key = self.config.google_api_key
        if not api_key:
            return None
        try:
            client = google_genai.Client(api_key=api_key)
            # 맥락 기반 프롬프트: scene_hint를 최우선, context로 보강
            prompt = (
                f"Abstract atmospheric background illustration for a Korean YouTube Shorts video. "
                f"Scene: {scene_hint}. "
                f"Style: dark cinematic color grading, soft depth-of-field blur, "
                f"moody dramatic lighting, vertical 9:16 composition, "
                f"NO text, NO faces, NO logos, NO UI elements. "
                f"Color palette: deep blues, muted oranges, atmospheric fog."
            )
            response = client.models.generate_images(
                model="imagen-4.0-generate-001",
                prompt=prompt,
                config=genai_types.GenerateImagesConfig(number_of_images=1),
            )
            for img in response.generated_images:
                path = os.path.join(work_dir, f"ai_bg_{idx:03d}.png")
                with open(path, "wb") as f:
                    f.write(img.image.image_bytes)
                print(f"    🎨 AI 배경 생성: {scene_hint[:40]}...")
                return path
        except Exception as e:
            print(f"    ⚠️  AI 이미지 생성 실패: {e}")
        return None

    def _prepare_backgrounds(self, screenshots: list[str],
                              total_frames: int,
                              script_data: dict = None,
                              work_dir: str = "") -> list[Image.Image]:
        """
        v4.1: 3단 비주얼 레이아웃
        ─ 배경(하단): 스크린샷 1.5배 확대 + GaussianBlur(20px) → 깊이감만
        ─ 중앙(메인): 스크린샷 선명 원본 (블러 없음) + 외곽선 + 그림자 → 리얼리티
        ─ 상단: 타이틀바는 프레임 루프에서 _render_title_bar()가 처리
        ─ AI 배경은 scene_hint 맥락 정밀 프롬프트로 생성
        """
        print(f"  🖼️  배경 이미지 처리 중 (3단 레이아웃)...")
        backgrounds = []

        # ── Imagen AI 배경 (highlight 장면, 최대 3장) ──
        ai_images = {}
        if script_data and self.config.use_ai_bg and work_dir:
            lines = script_data.get("script", [])
            ai_targets = []
            for i, line in enumerate(lines):
                if line.get("highlight") or line.get("emotion") in ("shock", "surprise"):
                    hint = line.get("scene_hint", "dramatic cinematic atmosphere")
                    ctx = line.get("text", "")
                    ai_targets.append((i, hint, ctx))
            ai_targets = ai_targets[:3]

            for target_idx, hint, ctx in ai_targets:
                ai_path = self._generate_ai_image(hint, work_dir, target_idx, ctx)
                if ai_path:
                    try:
                        ai_img = Image.open(ai_path).convert("RGB")
                        ai_img = self._fit_to_vertical(ai_img)
                        enhancer = ImageEnhance.Brightness(ai_img)
                        ai_img = enhancer.enhance(0.55)
                        ai_images[target_idx] = ai_img
                    except Exception:
                        pass

        # ── 3단 레이아웃 합성 ──
        if not screenshots:
            bg = self._create_gradient_bg(0)
            backgrounds.append(bg)
        else:
            for ss_path in screenshots:
                try:
                    orig = Image.open(ss_path).convert("RGB")
                    fitted = self._fit_to_vertical(orig)

                    # ▼ 배경 레이어: 1.5배 확대 + GaussianBlur(20px) + 어둡게
                    bg_w, bg_h = int(self.w * 1.5), int(self.h * 1.5)
                    bg_layer = fitted.resize((bg_w, bg_h), Image.LANCZOS)
                    left = (bg_w - self.w) // 2
                    top = (bg_h - self.h) // 2
                    bg_layer = bg_layer.crop((left, top, left + self.w, top + self.h))
                    bg_layer = bg_layer.filter(ImageFilter.GaussianBlur(radius=20))
                    enhancer = ImageEnhance.Brightness(bg_layer)
                    bg_layer = enhancer.enhance(0.30)

                    # ▼ 전경 레이어: 선명한 원본 (블러 없음) + 외곽선 + 그림자
                    # 상단 타이틀바(~60px) 아래, 자막 영역(h*0.60~) 위에 배치
                    fg_w = int(self.w * 0.88)
                    fg_h = int(fitted.height * (fg_w / fitted.width))
                    max_fg_h = int(self.h * 0.50)
                    if fg_h > max_fg_h:
                        fg_h = max_fg_h
                        fg_w = int(fitted.width * (fg_h / fitted.height))
                    fg = fitted.resize((fg_w, fg_h), Image.LANCZOS)

                    fg_x = (self.w - fg_w) // 2
                    fg_y = int(self.h * 0.08)  # 타이틀바 바로 아래

                    # 그림자 (8px offset + blur 15px)
                    shadow = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
                    shadow_draw = ImageDraw.Draw(shadow)
                    shadow_draw.rectangle(
                        [(fg_x + 6, fg_y + 6), (fg_x + fg_w + 6, fg_y + fg_h + 6)],
                        fill=(0, 0, 0, 140)
                    )
                    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=15))

                    # 합성
                    composite = bg_layer.convert("RGBA")
                    composite = Image.alpha_composite(composite, shadow)

                    # 흰색 외곽선 (4px)
                    border = 4
                    fg_draw = ImageDraw.Draw(composite)
                    fg_draw.rectangle(
                        [(fg_x - border, fg_y - border),
                         (fg_x + fg_w + border, fg_y + fg_h + border)],
                        fill=(255, 255, 255, 230)
                    )
                    # 선명한 원본 붙이기 (블러 없음)
                    composite.paste(fg, (fg_x, fg_y))

                    backgrounds.append(composite.convert("RGB"))
                except Exception as e:
                    print(f"    ⚠️  이미지 처리 실패: {e}")
                    backgrounds.append(self._create_gradient_bg(len(backgrounds)))

        if not backgrounds:
            backgrounds = [self._create_gradient_bg(0)]

        # AI 이미지를 배경 리스트에 삽입
        if ai_images:
            total_bg = len(backgrounds)
            script_len = len(script_data.get("script", [])) if script_data else 1
            for line_idx, ai_bg in ai_images.items():
                bg_pos = min(int(line_idx / script_len * total_bg), total_bg - 1)
                if bg_pos < len(backgrounds):
                    backgrounds.insert(bg_pos + 1, ai_bg)
            print(f"    🎨 AI 배경 {len(ai_images)}장 삽입 완료")

        return backgrounds

    def _fit_to_vertical(self, img: Image.Image) -> Image.Image:
        """이미지를 1080x1920에 맞게 크롭+리사이즈"""
        target_ratio = self.w / self.h  # 0.5625
        img_ratio = img.width / img.height

        if img_ratio > target_ratio:
            # 이미지가 더 넓음 → 좌우 크롭
            new_w = int(img.height * target_ratio)
            left = (img.width - new_w) // 2
            img = img.crop((left, 0, left + new_w, img.height))
        else:
            # 이미지가 더 높음 → 상하 크롭
            new_h = int(img.width / target_ratio)
            top = (img.height - new_h) // 2
            img = img.crop((0, top, img.width, top + new_h))

        return img.resize((self.w, self.h), Image.LANCZOS)

    def _create_gradient_bg(self, idx: int) -> Image.Image:
        """그라데이션 폴백 배경"""
        img = Image.new("RGB", (self.w, self.h))
        draw = ImageDraw.Draw(img)
        gradients = [
            [(30, 25, 40), (50, 35, 25)],
            [(25, 35, 30), (40, 25, 40)],
            [(35, 30, 25), (25, 30, 45)],
        ]
        c1, c2 = gradients[idx % len(gradients)]
        for y in range(self.h):
            r = y / self.h
            color = tuple(int(c1[i] * (1-r) + c2[i] * r) for i in range(3))
            draw.line([(0, y), (self.w, y)], fill=color)
        return img

    def _render_title_bar(self, frame: Image.Image, title: str,
                           alpha: float = 1.0) -> Image.Image:
        """
        v4.1: 세련된 상단 타이틀 바
        ─ 노란색 악센트 박스 + 핵심 주제 고정 타이틀
        ─ 어두운 그라데이션 배경으로 시인성 확보
        """
        overlay = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font = FontManager.get_font(30, bold=True)

        # 타이틀 텍스트 (최대 18자)
        title_text = title[:18] + ("..." if len(title) > 18 else "")
        bbox = draw.textbbox((0, 0), title_text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        bar_h = th + 32
        a = int(220 * alpha)

        # 배경: 그라데이션 (위쪽 불투명 → 아래쪽 반투명)
        for y in range(bar_h + 10):
            fade = max(0, a - int(y * 1.5))
            draw.line([(0, y), (self.w, y)], fill=(10, 10, 10, fade))

        # 노란색 악센트 라인 (상단 3px)
        draw.rectangle([(0, 0), (self.w, 3)], fill=(255, 220, 0, a))

        # 텍스트 중앙 (Pillow stroke_width)
        tx = (self.w - tw) // 2
        ty = 8 + (bar_h - th) // 2
        draw.text((tx, ty), title_text, font=font,
                   fill=(255, 255, 255, int(250 * alpha)),
                   stroke_width=2,
                   stroke_fill=(0, 0, 0, int(200 * alpha)))

        frame = frame.convert("RGBA")
        return Image.alpha_composite(frame, overlay).convert("RGB")

    def _render_cta_outro(self, frame: Image.Image,
                           remaining_sec: float) -> Image.Image:
        """v4.0: 마지막 2초 구독 유도 CTA 애니메이션"""
        overlay = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 페이드인 (0→1 over 0.3초)
        alpha = min(1.0, (2.0 - remaining_sec) / 0.3)

        # 반투명 배경
        draw.rectangle(
            [(0, int(self.h * 0.40)), (self.w, int(self.h * 0.60))],
            fill=(0, 0, 0, int(160 * alpha))
        )

        # "구독" 버튼 (빨간색 둥근 사각형)
        btn_w, btn_h = 240, 70
        btn_x = (self.w - btn_w) // 2
        btn_y = int(self.h * 0.44)
        draw.rounded_rectangle(
            [(btn_x, btn_y), (btn_x + btn_w, btn_y + btn_h)],
            radius=12, fill=(255, 0, 0, int(230 * alpha))
        )

        # "구독" 텍스트
        font_btn = FontManager.get_font(32, bold=True)
        bbox = draw.textbbox((0, 0), "구독", font=font_btn)
        tw = bbox[2] - bbox[0]
        draw.text(
            (btn_x + (btn_w - tw) // 2, btn_y + 16),
            "구독", font=font_btn,
            fill=(255, 255, 255, int(255 * alpha))
        )

        # "좋아요와 구독 부탁해요!" 텍스트
        font_msg = FontManager.get_font(26, bold=False)
        msg = "좋아요와 구독 부탁해요!"
        bbox2 = draw.textbbox((0, 0), msg, font=font_msg)
        mw = bbox2[2] - bbox2[0]
        draw.text(
            ((self.w - mw) // 2, btn_y + btn_h + 15),
            msg, font=font_msg,
            fill=(255, 255, 0, int(220 * alpha))
        )

        frame = frame.convert("RGBA")
        return Image.alpha_composite(frame, overlay).convert("RGB")

    def _render_subtitle(self, frame: Image.Image, chunk: dict,
                          current_ms: float) -> Image.Image:
        """
        v4.1 High-Retention Captions — 단어별 하이라이트 Pop
        ─ 기본: 흰색 글자 + 검정 4px 외곽선 → 어떤 배경에서도 가독성 1순위
        ─ 동적 하이라이트: 현재 읽고 있는 단어만 노란색(#FFFF00) + 살짝 커짐(Pop)
        ─ 등장: scale 0.7→1.0 (120ms ease-out), 퇴장: fade-out (80ms)
        """
        text = chunk["text"]
        emotion = chunk.get("emotion", "neutral")
        highlight = chunk.get("highlight", False)
        start_ms = chunk["start_ms"]
        end_ms = chunk["end_ms"]

        # ── 애니메이션 계산 ──
        elapsed = current_ms - start_ms
        remaining = end_ms - current_ms
        duration = end_ms - start_ms
        fade_in_ms = 120
        fade_out_ms = 80

        alpha = 1.0
        if elapsed < fade_in_ms:
            alpha = elapsed / fade_in_ms
        elif remaining < fade_out_ms:
            alpha = remaining / fade_out_ms
        alpha = max(0.0, min(1.0, alpha))

        # 등장 스케일
        scale = 1.0
        if elapsed < fade_in_ms:
            t = elapsed / fade_in_ms
            scale = 0.7 + 0.3 * (1 - (1 - t) ** 3)

        # ── 폰트 (Bold, 흰색 기본) ──
        fs = int(self.config.font_size * scale)
        font = FontManager.get_font(max(24, fs), bold=True)
        font_pop = FontManager.get_font(max(24, int(fs * 1.15)), bold=True)

        # ── 단어 분할 + 현재 읽는 단어 계산 ──
        words = text.split() if " " in text else list(text)
        # 한글은 공백이 없을 수 있으므로, 2~4글자 단위로 분할
        if len(words) == 1 and len(text) > 4:
            # 한글 텍스트를 의미 단위로 분할
            words = []
            chunk_size = max(2, len(text) // max(2, len(text) // 3))
            for j in range(0, len(text), chunk_size):
                words.append(text[j:j + chunk_size])

        n_words = len(words)
        progress = max(0.0, min(1.0, elapsed / max(1, duration)))
        active_word_idx = min(int(progress * n_words), n_words - 1)

        # ── 줄바꿈 (전체 텍스트 기준) ──
        full_text = " ".join(words) if " " in text else "".join(words)
        max_chars = 15
        if len(full_text) > max_chars:
            mid = len(full_text) // 2
            best_break = mid
            for offset in range(min(6, mid)):
                for pos in [mid + offset, mid - offset]:
                    if 0 < pos < len(full_text) and full_text[pos] in " .,!?은는이가을를에서도로의":
                        best_break = pos + 1
                        break
                else:
                    continue
                break
            lines = [full_text[:best_break].strip(), full_text[best_break:].strip()]
        else:
            lines = [full_text]

        # ── 측정 (전체 텍스트 기준) ──
        draw_temp = ImageDraw.Draw(frame)
        line_heights, line_widths = [], []
        for line in lines:
            bbox = draw_temp.textbbox((0, 0), line, font=font)
            line_widths.append(bbox[2] - bbox[0])
            line_heights.append(bbox[3] - bbox[1])

        max_line_w = max(line_widths) if line_widths else 100
        total_text_h = sum(line_heights) + (len(lines) - 1) * 12
        padding_x, padding_y = 44, 28
        box_w = max_line_w + padding_x * 2
        box_h = total_text_h + padding_y * 2

        box_x = (self.w - box_w) // 2
        box_y = int(self.h * 0.65)

        # ── 오버레이 ──
        overlay = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 배경 박스 (어두운 반투명)
        bg_a = int(min(230, 200) * alpha)
        draw.rounded_rectangle(
            [(box_x, box_y), (box_x + box_w, box_y + box_h)],
            radius=16, fill=(15, 15, 15, bg_a),
        )

        # ── 단어별 렌더링 (외곽선 4px + 그림자 + 메인) ──
        text_y = box_y + padding_y
        word_global_idx = 0

        for i, line in enumerate(lines):
            line_w = line_widths[i]
            line_x = box_x + (box_w - line_w) // 2

            # 이 줄의 단어들을 추적하며 개별 렌더링
            cursor_x = line_x
            # 줄 내 문자를 단어 단위로 매칭
            remaining_line = line
            while remaining_line and word_global_idx < n_words:
                word = words[word_global_idx]
                # 줄에서 이 단어의 위치 확인
                pos = remaining_line.find(word)
                if pos < 0:
                    break

                # 단어 앞의 공백/문자 렌더링 (일반)
                prefix = remaining_line[:pos]
                if prefix:
                    p_bbox = draw.textbbox((0, 0), prefix, font=font)
                    p_w = p_bbox[2] - p_bbox[0]
                    self._draw_text_with_stroke(
                        draw, cursor_x, text_y, prefix, font,
                        (255, 255, 255), alpha, stroke_px=4
                    )
                    cursor_x += p_w

                # 현재 읽고 있는 단어 판별
                is_active = (word_global_idx == active_word_idx)

                if is_active and highlight:
                    # ★ 활성 단어 + highlight: 노란색 Pop
                    pop_scale = 1.0 + 0.08 * math.sin(
                        min(1.0, (elapsed % 500) / 250) * math.pi
                    )
                    w_font = FontManager.get_font(
                        max(24, int(fs * 1.15 * pop_scale)), bold=True
                    )
                    self._draw_text_with_stroke(
                        draw, cursor_x, text_y - 2, word, w_font,
                        (255, 255, 0), alpha, stroke_px=4
                    )
                    w_bbox = draw.textbbox((0, 0), word, font=w_font)
                elif is_active:
                    # ★ 활성 단어 (non-highlight): 노란색
                    self._draw_text_with_stroke(
                        draw, cursor_x, text_y, word, font,
                        (255, 255, 0), alpha, stroke_px=4
                    )
                    w_bbox = draw.textbbox((0, 0), word, font=font)
                else:
                    # 일반 단어: 흰색
                    self._draw_text_with_stroke(
                        draw, cursor_x, text_y, word, font,
                        (255, 255, 255), alpha, stroke_px=4
                    )
                    w_bbox = draw.textbbox((0, 0), word, font=font)

                w_w = w_bbox[2] - w_bbox[0]
                cursor_x += w_w
                remaining_line = remaining_line[pos + len(word):]
                word_global_idx += 1

            # 남은 문자가 있으면 렌더링
            if remaining_line.strip():
                self._draw_text_with_stroke(
                    draw, cursor_x, text_y, remaining_line, font,
                    (255, 255, 255), alpha, stroke_px=4
                )

            text_y += line_heights[i] + 12

        frame = frame.convert("RGBA")
        frame = Image.alpha_composite(frame, overlay)
        return frame.convert("RGB")

    def _draw_text_with_stroke(self, draw: ImageDraw.Draw,
                                x: int, y: int, text: str,
                                font: ImageFont.FreeTypeFont,
                                color: tuple, alpha: float,
                                stroke_px: int = 4):
        """v4.2: Pillow 내장 stroke_width 사용 → 49루프→1콜 (20배 가속)"""
        a = int(255 * alpha)
        stroke_a = int(230 * alpha)
        shadow_a = int(140 * alpha)

        # 1) 그림자 (5px offset)
        draw.text((x + 5, y + 5), text, font=font,
                   fill=(0, 0, 0, shadow_a))

        # 2) 외곽선 + 메인 텍스트 (Pillow built-in stroke_width)
        draw.text((x, y), text, font=font,
                   fill=(*color, a),
                   stroke_width=stroke_px,
                   stroke_fill=(0, 0, 0, stroke_a))

    def _concat_audio(self, chunks: list[dict], output: str, work_dir: str):
        """
        v4.1: Voice EQ + BGM + Sidechain Ducking -20dB
        ─ 공백: 0.08초 (80ms) → 쉴 틈 없는 텐션
        ─ Ducking: ratio=20 + threshold=0.008 → 보이스 있을 때 BGM -20dB
        """
        concat_list = os.path.join(work_dir, "concat_list.txt")

        # v4.2: 문장별 개별 TTS → 순서대로 concat
        # 각 문장 사이에 80ms + pause_ms 무음 삽입

        # ── Step 1: 보이스 concat (80ms 기본 + pause_ms 추가) ──
        with open(concat_list, "w", encoding="utf-8") as f:
            for i, chunk in enumerate(chunks):
                if i > 0:
                    # 기본 80ms + 스크립트 지정 pause_ms
                    pause_sec = 0.08 + chunk.get("pause_ms", 0) / 1000
                    pause_file = os.path.join(work_dir, f"pause_{i:03d}.mp3")
                    subprocess.run([
                        FFMPEG_PATH, "-y", "-f", "lavfi",
                        "-i", "anullsrc=r=44100:cl=mono",
                        "-t", f"{pause_sec:.3f}",
                        "-c:a", "libmp3lame", "-b:a", "128k",
                        "-ar", "44100", pause_file
                    ], capture_output=True)
                    abs_pause = os.path.abspath(pause_file).replace("\\", "/")
                    f.write(f"file '{abs_pause}'\n")
                abs_audio = os.path.abspath(chunk['audio_file']).replace("\\", "/")
                f.write(f"file '{abs_audio}'\n")

        raw_voice = os.path.join(work_dir, "voice_raw.mp3")
        result = subprocess.run([
            FFMPEG_PATH, "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100",
            raw_voice
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            print(f"  ⚠️  오디오 concat 실패: {result.stderr[-300:] if result.stderr else ''}")
            # 폴백: 첫 번째 오디오 파일이라도 사용
            if os.path.exists(raw_voice):
                shutil.move(raw_voice, output)
            elif chunks and os.path.exists(chunks[0].get("audio_file", "")):
                shutil.copy2(chunks[0]["audio_file"], output)
            return

        # ── Step 2: Voice 마스터링 (강화 EQ + compressor) ──
        print(f"  🎛️  Voice 마스터링...")
        mastered_voice = os.path.join(work_dir, "voice_mastered.mp3")
        voice_filter = (
            "acompressor=threshold=-18dB:ratio=4:attack=5:release=50,"
            "equalizer=f=200:t=q:w=1:g=3,"
            "equalizer=f=3000:t=q:w=0.8:g=2,"
            "equalizer=f=5000:t=q:w=1:g=1,"
            "loudnorm=I=-14:TP=-1:LRA=9"
        )
        r = subprocess.run([
            FFMPEG_PATH, "-y", "-i", raw_voice,
            "-af", voice_filter,
            "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100",
            mastered_voice
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print(f"  ⚠️  Voice 마스터링 실패, raw 사용")
            mastered_voice = raw_voice

        # ── Step 3: BGM 생성 + Sidechain Ducking (-20dB) ──
        if self.config.bgm_enabled:
            print(f"  🎵 앰비언트 드론 BGM + Sidechain Ducking (-20dB)...")
            total_sec = max(c["end_ms"] for c in chunks) / 1000 + 1
            bgm_file = os.path.join(work_dir, "bgm.mp3")
            # v4.2: 사인파 앰비언트 드론 (220Hz+330Hz+440Hz)
            # 핑크노이즈 대신 따뜻한 드론 → 몰입감 + 집중도 UP
            drone_src = (
                f"sine=f=220:r=44100:d={total_sec:.1f},"
                f"volume=0.03[s1];"
                f"sine=f=330:r=44100:d={total_sec:.1f},"
                f"volume=0.02[s2];"
                f"sine=f=440:r=44100:d={total_sec:.1f},"
                f"volume=0.015[s3];"
                f"[s1][s2][s3]amix=inputs=3:duration=shortest,"
                f"lowpass=f=500,"
                f"afade=t=in:st=0:d=1.5,"
                f"afade=t=out:st={max(0, total_sec - 2):.1f}:d=2,"
                f"volume=0.4"
            )
            subprocess.run([
                FFMPEG_PATH, "-y", "-f", "lavfi",
                "-i", drone_src,
                "-c:a", "libmp3lame", "-b:a", "64k", "-ar", "44100",
                bgm_file
            ], capture_output=True)

            ducked_output = os.path.join(work_dir, "final_mix.mp3")
            abs_voice = os.path.abspath(mastered_voice)
            abs_bgm = os.path.abspath(bgm_file)

            # Sidechain: threshold=0.008 ratio=20 → voice시 BGM -20dB
            duck_filter = (
                "[1:a]acompressor=threshold=0.008:ratio=20:attack=20:release=300"
                ":detection=peak:link=average:level_sc=1[bgm_ducked];"
                "[0:a][bgm_ducked]amix=inputs=2:weights=1 0.25:duration=shortest"
            )
            r2 = subprocess.run([
                FFMPEG_PATH, "-y",
                "-i", abs_voice,
                "-i", abs_bgm,
                "-filter_complex", duck_filter,
                "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100",
                ducked_output
            ], capture_output=True, text=True, encoding="utf-8", errors="replace")

            if r2.returncode == 0:
                shutil.move(ducked_output, output)
                print(f"  ✅ BGM + Sidechain Ducking (-20dB) 완료")
            else:
                print(f"  ⚠️  Ducking 실패, voice만 사용")
                shutil.move(mastered_voice, output)
        else:
            shutil.move(mastered_voice, output)
            print(f"  ✅ Voice 마스터링 완료 (BGM 없음)")

        # 임시 파일 정리
        for tmp in [raw_voice, mastered_voice,
                     os.path.join(work_dir, "bgm.mp3"),
                     os.path.join(work_dir, "final_mix.mp3")]:
            if os.path.exists(tmp) and tmp != output:
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _assemble_simple_fallback(self, audio: str, duration: float,
                                   chunks: list, output: str,
                                   work_dir: str) -> str:
        """프레임 렌더링 실패 시 ASS 자막 폴백"""
        print(f"  🔄 ASS 자막 폴백 모드...")
        ass_file = os.path.join(work_dir, "subs.ass")
        self._generate_ass_fallback(chunks, ass_file)

        # ASS 파일 경로에서 Windows 백슬래시를 이스케이프
        ass_escaped = ass_file.replace("\\", "/").replace(":", "\\\\:")
        cmd = [
            FFMPEG_PATH, "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x1a1a1a:s={self.w}x{self.h}:d={duration:.2f}:r={self.config.fps}",
            "-i", audio,
            "-vf", f"ass={ass_escaped}",
            "-c:v", "libx264", "-preset", "fast",
            "-b:v", "2000k", "-minrate", "1500k", "-maxrate", "5000k", "-bufsize", "4000k",
            "-c:a", "aac", "-b:a", "256k", "-ar", "44100",
            "-shortest", "-pix_fmt", "yuv420p",
            output,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            print(f"  ⚠️  ASS 폴백도 실패, 자막 없이 재시도...")
            cmd_simple = [
                FFMPEG_PATH, "-y",
                "-f", "lavfi",
                "-i", f"color=c=0x1a1a1a:s={self.w}x{self.h}:d={duration:.2f}:r={self.config.fps}",
                "-i", audio,
                "-c:v", "libx264", "-preset", "fast",
                "-b:v", "2000k", "-minrate", "1500k", "-maxrate", "5000k", "-bufsize", "4000k",
                "-c:a", "aac", "-b:a", "256k", "-ar", "44100",
                "-shortest", "-pix_fmt", "yuv420p",
                output,
            ]
            subprocess.run(cmd_simple, capture_output=True)
        return output

    def _generate_ass_fallback(self, chunks: list, output: str):
        """ASS 자막 폴백 생성"""
        ass = f"""[Script Info]
Title: Shorts
ScriptType: v4.00+
PlayResX: {self.w}
PlayResY: {self.h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,NanumSquareRound,58,&H00FFFFFF,&H000000FF,&H00000000,&HC0000000,-1,0,0,0,100,100,0,0,1,3,2,2,60,60,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        for c in chunks:
            s = self._ms_to_ass(c["start_ms"])
            e = self._ms_to_ass(c["end_ms"])
            ass += f"Dialogue: 0,{s},{e},Default,,0,0,0,,{c['text']}\n"

        with open(output, "w", encoding="utf-8") as f:
            f.write(ass)

    @staticmethod
    def _ms_to_ass(ms: int) -> str:
        t = ms / 1000
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        cs = int((t % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ============================================================
# 🏭 메인 파이프라인
# ============================================================
class ShortsFactory:
    def __init__(self, config: Config):
        self.config = config
        self.scraper = CommunityScraper(config)
        self.scriptgen = ScriptGenerator(config)
        self.tts = TTSEngine(config)
        self.assembler = VideoAssembler(config)

    async def run(self) -> list[str]:
        start_time = time.time()
        output_files = []

        print("\n" + "🎬" * 30)
        print("  YouTube Shorts 팩토리 v5.0 'The Viral Machine'")
        print("  🌐 멀티플랫폼 + 🔥 바이럴 프롬프트 + 🎵 드론 BGM + ⚡ 바이럴 가산점 정렬")
        print("🎬" * 30)

        # Stage 1: 크롤링 + 스크린샷
        if self.config.skip_crawl and self.config.manual_topic:
            posts = [{
                "title": self.config.manual_topic,
                "content": self.config.manual_topic,
                "source": "manual",
                "screenshots": [],
            }]
        else:
            posts = self.scraper.scrape_with_screenshots()

        if not posts:
            print("❌ 크롤링 결과 없음!")
            return []

        # 각 글마다 영상 생성
        for idx, post in enumerate(posts):
            print(f"\n{'🎬'*20}")
            print(f"  [{idx+1}/{len(posts)}] {post['title'][:40]}")
            print(f"{'🎬'*20}")

            work_dir = os.path.join(
                self.config.output_dir,
                f"_work_{idx}_{datetime.now().strftime('%H%M%S')}"
            )
            os.makedirs(work_dir, exist_ok=True)

            try:
                # Stage 2: 대본
                if self.config.skip_crawl and self.config.manual_topic:
                    script_data = self.scriptgen.generate_from_topic(
                        self.config.manual_topic
                    )
                else:
                    script_data = self.scriptgen.generate(post)

                if script_data is None:
                    print(f"  ⏭️  소스 품질 부족, 건너뜀")
                    continue

                # 대본 저장
                with open(os.path.join(work_dir, "script.json"), "w",
                          encoding="utf-8") as f:
                    json.dump(script_data, f, ensure_ascii=False, indent=2)

                # 스크린샷 없으면 텍스트 기반 생성
                screenshots = post.get("screenshots", [])
                if not screenshots:
                    screenshots = self.scraper._generate_text_screenshots(post)

                # Stage 3: TTS
                chunks = await self.tts.generate(script_data, work_dir)
                if not chunks:
                    print("  ⚠️  TTS 실패, 건너뜀")
                    continue

                # Stage 4: 영상 조립
                output_path = self.assembler.assemble(
                    script_data, chunks, screenshots, work_dir
                )
                output_files.append(output_path)

                # 메타 저장
                duration_sec = max(c["end_ms"] for c in chunks) / 1000
                meta = {
                    "video": output_path,
                    "script": script_data,
                    "chunks": len(chunks),
                    "duration_sec": duration_sec,
                    "screenshots": screenshots,
                    "created": datetime.now().isoformat(),
                }
                with open(output_path.replace(".mp4", "_meta.json"), "w",
                          encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)

                # v4.0: upload_info.json (업로드 준비 완료)
                upload_info = {
                    "title": script_data.get("title", "숏츠"),
                    "description": script_data.get("description",
                        f"{script_data.get('title', '')} #숏츠 #썰 #레전드"),
                    "tags": [t.replace("#", "") for t in
                             script_data.get("tags", ["숏츠", "썰", "레전드"])],
                    "thumbnail_text": script_data.get("thumbnail_text", ""),
                    "category": "22",  # People & Blogs
                    "privacy": "public",
                    "shorts": True,
                    "duration_sec": round(duration_sec, 1),
                    "video_file": os.path.basename(output_path),
                    "created": datetime.now().isoformat(),
                }
                upload_path = output_path.replace(".mp4", "_upload_info.json")
                with open(upload_path, "w", encoding="utf-8") as f:
                    json.dump(upload_info, f, ensure_ascii=False, indent=2)
                print(f"  📋 upload_info.json 생성 완료")

            except Exception as e:
                print(f"  ❌ 에러: {e}")
                import traceback
                traceback.print_exc()

        # 리포트
        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"📊 최종 리포트")
        print(f"{'='*60}")
        print(f"  ⏱️  소요시간: {elapsed:.1f}초")
        print(f"  🎬 생성 영상: {len(output_files)}개")
        for f in output_files:
            if os.path.exists(f):
                sz = os.path.getsize(f) / (1024*1024)
                print(f"     📁 {f} ({sz:.1f}MB)")
            else:
                print(f"     ⚠️  {f} (파일 미생성)")
        print(f"{'='*60}\n")

        return output_files


# ============================================================
# 🚀 CLI
# ============================================================
def parse_args():
    p = argparse.ArgumentParser(
        description="🎬 YouTube Shorts 팩토리 v5.0 'The Viral Machine'",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python main.py --source dcinside --gallery humor --count 3
  python main.py --source natepann --count 5
  python main.py --url "https://gall.dcinside.com/board/view/..."
  python main.py --topic "상견례 파토 썰" --skip-crawl
  python main.py --source natepann --voice ko-KR-InJoonNeural

환경변수:
  ANTHROPIC_API_KEY   Claude API 키 (필수)
  APIFY_API_TOKEN     Apify API 토큰 (선택)
        """
    )

    src = p.add_argument_group("📡 크롤링")
    src.add_argument("--source",
                     choices=["natepann", "dcinside",
                              "dcinside_realtime_best", "dcinside_hit",
                              "fmkorea", "ruliweb", "instiz", "theqoo"],
                     default="dcinside_realtime_best")
    src.add_argument("--gallery", default="humor")
    src.add_argument("--count", type=int, default=3)
    src.add_argument("--url", default="")

    scr = p.add_argument_group("📝 대본")
    scr.add_argument("--topic", default="")
    scr.add_argument("--skip-crawl", action="store_true")

    tts = p.add_argument_group("🔊 TTS")
    tts.add_argument("--voice", default="ko-KR-HyunsuNeural")
    tts.add_argument("--rate", default="+5%")
    tts.add_argument("--pitch", default="-1Hz")

    out = p.add_argument_group("📁 출력")
    out.add_argument("--output", default="./output")
    out.add_argument("--quality", type=int, default=80)

    return p.parse_args()


async def main():
    args = parse_args()

    config = Config(
        source=args.source,
        gallery=args.gallery,
        crawl_count=args.count,
        target_url=args.url,
        manual_topic=args.topic,
        skip_crawl=args.skip_crawl or bool(args.topic),
        tts_voice=args.voice,
        tts_rate=args.rate,
        tts_pitch=args.pitch,
        quality=args.quality,
        output_dir=args.output,
    )

    if not config.claude_api_key:
        print("❌ ANTHROPIC_API_KEY 환경변수 필요!")
        print("   export ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    if not config.apify_api_token:
        print("⚠️  APIFY_API_TOKEN 미설정 → 폴백 크롤링")

    factory = ShortsFactory(config)
    results = await factory.run()

    if results:
        print("🎉 완료!")
    else:
        print("😢 생성된 영상 없음")


if __name__ == "__main__":
    asyncio.run(main())
