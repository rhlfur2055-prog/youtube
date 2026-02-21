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
  ✅ 분위기별 그라데이션 배경 (Pillow, 무료)
  ✅ 단어별 하이라이트 Pop + 4px 외곽선 + 5px 그림자
  ✅ Sidechain Ducking -20dB + 공백 80ms
  ✅ Ken Burns + Dynamic Blur + Voice 마스터링
  ✅ 3초 후킹 대본 + 구독 유도 CTA 엔딩
  ✅ upload_info.json 자동 생성

파이프라인:
  [바이럴 소스] YouTube Trending + Google Trends + HN + Wikipedia (무료)
      ↓  (폴백: 커뮤니티 크롤링 Apify/requests)
  [대본생성] Gemini 2.0 Flash → 100만뷰 후킹 대본 + SEO 태그 (무료)
      ↓
  [TTS+자막] edge-tts → 감정별 prosody + WordBoundary 타이밍
      ↓
  [배경생성] Pillow 그라데이션 → 분위기별 배경 이미지 (무료)
      ↓
  [영상조립] FFmpeg → Dynamic Blur + Ken Burns + 자막 + BGM Ducking
      ↓
  [출력] shorts_제목_날짜.mp4 + upload_info.json

사용법:
  python main.py                                       # 바이럴 소스 (기본값)
  python main.py --source viral --count 5              # 바이럴 소스 5개
  python main.py --source dcinside_realtime_best --count 1
  python main.py --source fmkorea --count 3
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
import random
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
        "edge_tts": "edge-tts",
        "requests": "requests",
        "apify_client": "apify-client",
        "PIL": "Pillow",
        "imageio_ffmpeg": "imageio-ffmpeg",
        "google.generativeai": "google-generativeai",
        "anthropic": "anthropic",  # 대본 생성 (Claude)
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

    # pydub 등 외부 라이브러리가 ffmpeg를 찾을 수 있도록 PATH에 추가
    ffmpeg_dir = os.path.dirname(FFMPEG_PATH)
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    print(f"  FFmpeg: {FFMPEG_PATH}")
    if FFPROBE_PATH:
        print(f"  FFprobe: {FFPROBE_PATH}")

check_dependencies()

import edge_tts
import requests
import google.generativeai as genai_flash
try:
    import anthropic as _anthropic_module
except ImportError:
    _anthropic_module = None
from apify_client import ApifyClient
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance


# ============================================================
# ⚙️ 설정값
# ============================================================
@dataclass
class Config:
    # API 키
    google_api_key: str = ""
    anthropic_api_key: str = ""  # 대본 생성용 Claude (claude-sonnet-4-6)
    apify_api_token: str = ""

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
    theme: str = "auto"  # "gossip" | "life_hack" | "empathy" | "mystery" | "auto"

    # TTS (v6.0: ElevenLabs → OpenAI → edge-tts 폴백)
    tts_engine: str = "auto"  # "elevenlabs" | "openai" | "edge" | "auto"
    tts_voice: str = "ko-KR-HyunsuNeural"  # edge-tts 전용
    tts_rate: str = "+5%"
    tts_pitch: str = "-1Hz"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""  # 기본 voice_id (감정별 자동 전환)

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
    use_ai_bg: bool = False        # Imagen 제거 — 그라데이션 배경 사용 (무료)
    use_stock_video: bool = True   # v5.1: Pexels 스톡 비디오 배경 (무료)
    bgm_enabled: bool = True       # BGM + Auto-Ducking

    # 출력
    output_dir: str = "./output"

    def __post_init__(self):
        self.google_api_key = os.getenv("GOOGLE_API_KEY", self.google_api_key)
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", self.anthropic_api_key)
        self.apify_api_token = os.getenv("APIFY_API_TOKEN", self.apify_api_token)
        # v6.0: 멀티엔진 TTS + GoAPI
        self.elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY", self.elevenlabs_api_key)
        self.elevenlabs_voice_id = os.getenv("ELEVENLABS_VOICE_ID", self.elevenlabs_voice_id)
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

    # v6.0: 두껍고 귀여운 폰트 (Satisfying 스타일용)
    _shorts_font_cache: dict = {}

    @staticmethod
    def get_shorts_font(size: int) -> ImageFont.FreeTypeFont:
        """
        v6.0: 쇼츠 전용 두꺼운 폰트 반환 (GmarketSans Bold 우선)
        없으면 자동 다운로드 → 로컬 fonts/ 디렉토리에 캐시
        """
        cache_key = f"shorts_{size}"
        if cache_key in FontManager._shorts_font_cache:
            return FontManager._shorts_font_cache[cache_key]

        # 1) 로컬 fonts/ 디렉토리 체크
        local_fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
        os.makedirs(local_fonts_dir, exist_ok=True)

        gmarket_path = os.path.join(local_fonts_dir, "GmarketSansTTFBold.ttf")
        if os.path.exists(gmarket_path):
            font = ImageFont.truetype(gmarket_path, size)
            FontManager._shorts_font_cache[cache_key] = font
            return font

        # 2) Windows 폰트 디렉토리에서 GmarketSans / CookieRun 검색
        if sys.platform == "win32":
            font_dirs = [
                os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
            ]
            for font_dir in font_dirs:
                if not os.path.isdir(font_dir):
                    continue
                for fname in ["GmarketSansTTFBold.ttf", "GmarketSansBold.ttf",
                              "CookieRun Bold.ttf", "CookieRunOTF-Bold.otf"]:
                    path = os.path.join(font_dir, fname)
                    if os.path.exists(path):
                        font = ImageFont.truetype(path, size)
                        FontManager._shorts_font_cache[cache_key] = font
                        return font

        # 3) 자동 다운로드 (GmarketSans Bold — 무료 배포 폰트)
        download_urls = [
            "https://cdn.jsdelivr.net/gh/nicesharp/gmarket-sans@main/GmarketSansTTFBold.ttf",
            "https://raw.githubusercontent.com/nicesharp/gmarket-sans/main/GmarketSansTTFBold.ttf",
        ]
        for download_url in download_urls:
            print(f"  📥 GmarketSans Bold 폰트 다운로드 중...")
            try:
                resp = requests.get(download_url, timeout=30)
                if resp.status_code == 200 and len(resp.content) > 10000:
                    with open(gmarket_path, "wb") as f:
                        f.write(resp.content)
                    print(f"  ✅ GmarketSans Bold 다운로드 완료 ({len(resp.content)//1024}KB)")
                    font = ImageFont.truetype(gmarket_path, size)
                    FontManager._shorts_font_cache[cache_key] = font
                    return font
            except Exception as e:
                print(f"  ⚠️  GmarketSans 다운로드 실패: {e}")
                continue

        # 4) 폴백: 맑은고딕 Bold → 기본 Bold
        fallback = FontManager.get_font(size, bold=True)
        FontManager._shorts_font_cache[cache_key] = fallback
        return fallback

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
# 🎥 Satisfying Video 페처 (대본 무관 → 시각적 만족감 영상 1개)
# ============================================================
class StockVideoFetcher:
    """
    v6.0: Satisfying Video 전략
    - 대본 내용과 무관하게 Oddly Satisfying 고화질 세로 영상 1개 다운로드
    - 전체 배경으로 루프 사용 (문장별 컷 전환 제거)
    - API 비용: $0 (Pexels 무료 API)
    """

    PEXELS_API_URL = "https://api.pexels.com/videos/search"

    # v6.2: 감정(mood) → 시네마틱 4K 배경 키워드 매핑
    # 사람 연기 영상 절대 금지 — 질감/배경/추상 영상만
    MOOD_KEYWORDS = {
        "funny": [
            "glitch art abstract",
            "pop art animation",
            "fast motion clouds timelapse",
            "colorful liquid abstract",
            "neon lights abstract",
            "candy factory machine",
        ],
        "angry": [
            "breaking glass slow motion",
            "fire flames close up",
            "lightning storm 4k",
            "hydraulic press crushing",
            "volcanic eruption lava",
            "shredding machine metal",
        ],
        "sad": [
            "rain on window close up",
            "ink in water dark",
            "lonely night city lights",
            "autumn leaves falling",
            "ocean waves dark moody",
            "candle flame dark room",
        ],
        "touching": [
            "sunrise golden hour nature",
            "cherry blossom petals falling",
            "sand art satisfying",
            "calligraphy ink writing",
            "warm fireplace close up",
            "golden wheat field wind",
        ],
        "scary": [
            "dark forest fog",
            "old tv static noise",
            "smoke dark background",
            "abandoned hallway dark",
            "flickering light horror",
            "deep ocean dark water",
        ],
        "satisfying": [
            "soap cutting asmr",
            "kinetic sand satisfying",
            "epoxy resin art pour",
            "paint pouring abstract",
            "pressure washing satisfying",
            "slime mixing colorful",
        ],
        "shocking": [
            "explosion slow motion",
            "lightning strike close up",
            "chemical reaction colorful",
            "hydraulic press crushing",
            "glass shattering slow motion",
            "liquid metal melting pour",
        ],
    }

    # 폴백: mood 미지정 시 범용 풀
    SATISFYING_KEYWORDS = [
        "abstract liquid motion",
        "kinetic sand satisfying",
        "soap cutting asmr",
        "ink in water dark",
        "paint pouring abstract",
        "fire flames close up",
        "rain on window",
        "neon lights abstract",
        "smoke dark background",
        "ocean waves dark moody",
    ]

    def __init__(self):
        self.api_key = os.getenv("PEXELS_API_KEY", "")
        self._download_count = 0

    def search_satisfying_video(self, mood: str = "") -> Optional[dict]:
        """감정(mood) 기반 Satisfying 키워드 매칭 → Pexels 세로 영상 검색"""
        if not self.api_key:
            return None

        # mood가 있으면 해당 감정 키워드 우선, 없으면 폴백 풀
        if mood and mood.lower() in self.MOOD_KEYWORDS:
            keywords = self.MOOD_KEYWORDS[mood.lower()].copy()
            print(f"    🎭 감정 매칭: [{mood}] → {keywords[:3]}...")
            # 폴백으로 기본 풀 추가
            fallback = [k for k in self.SATISFYING_KEYWORDS if k not in keywords]
            random.shuffle(fallback)
            keywords += fallback[:3]
        else:
            keywords = self.SATISFYING_KEYWORDS.copy()
        random.shuffle(keywords)

        for keyword in keywords:
            try:
                headers = {"Authorization": self.api_key}
                params = {
                    "query": keyword,
                    "orientation": "portrait",
                    "size": "medium",
                    "per_page": 15,
                    "min_duration": 15,
                }
                resp = requests.get(self.PEXELS_API_URL, headers=headers,
                                    params=params, timeout=15)
                if resp.status_code != 200:
                    print(f"    ⚠️  Pexels API 오류 ({keyword}): {resp.status_code}")
                    continue

                data = resp.json()
                videos = data.get("videos", [])

                # 15초 이상 + 세로 영상 필터
                candidates = []
                for v in videos:
                    dur = v.get("duration", 0)
                    if dur >= 15:
                        candidates.append(v)

                if not candidates:
                    # orientation 없이 재시도
                    params.pop("orientation", None)
                    resp = requests.get(self.PEXELS_API_URL, headers=headers,
                                        params=params, timeout=15)
                    data = resp.json()
                    for v in data.get("videos", []):
                        if v.get("duration", 0) >= 15:
                            candidates.append(v)

                if not candidates:
                    continue

                # 랜덤 선택 (같은 영상 반복 방지)
                video = random.choice(candidates)
                video_files = video.get("video_files", [])

                # 세로 + 적절 해상도 파일 선택
                best_file = None
                for vf in video_files:
                    w = vf.get("width", 0)
                    h = vf.get("height", 0)
                    if 480 <= min(w, h) <= 1920:
                        if best_file is None:
                            best_file = vf
                        elif h > w and (best_file.get("height", 0) <= best_file.get("width", 0)):
                            best_file = vf  # 세로 우선

                if not best_file and video_files:
                    best_file = video_files[0]

                url = best_file.get("link", "") if best_file else ""
                if url:
                    print(f"    🎯 Satisfying 영상 발견! [{keyword}] (길이: {video.get('duration', 0)}초)")
                    return {"url": url, "keyword": keyword,
                            "duration": video.get("duration", 0)}

            except Exception as e:
                print(f"    ⚠️  Pexels 검색 실패 ({keyword}): {e}")
            time.sleep(0.3)

        return None

    def download_video(self, url: str, save_path: str) -> bool:
        """비디오 URL → 로컬 파일 다운로드"""
        try:
            resp = requests.get(url, timeout=60, stream=True)
            if resp.status_code == 200:
                with open(save_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                self._download_count += 1
                return True
        except Exception as e:
            print(f"    ⚠️  비디오 다운로드 실패: {e}")
        return False

    def fetch_satisfying_background(self, work_dir: str, mood: str = "") -> Optional[str]:
        """
        v6.1: 감정 기반 Satisfying 배경 영상 1개 다운로드.
        mood → MOOD_KEYWORDS 매핑으로 콘텐츠 톤에 맞는 배경 선택
        Returns: 비디오 파일 경로 or None
        """
        if not self.api_key:
            print("  ⚠️  PEXELS_API_KEY 없음 — 그라데이션 배경 폴백")
            return None

        os.makedirs(work_dir, exist_ok=True)

        mood_display = f" [감정: {mood}]" if mood else ""
        print(f"  🎥 Satisfying 배경 영상 검색 중...{mood_display}")

        result = self.search_satisfying_video(mood=mood)
        if not result:
            print("  ⚠️  Satisfying 영상 검색 실패 — 그라데이션 배경 폴백")
            return None

        video_path = os.path.join(work_dir, "satisfying_bg.mp4")
        if self.download_video(result["url"], video_path):
            size_mb = os.path.getsize(video_path) / (1024 * 1024)
            print(f"  ✅ Satisfying 배경 다운로드 완료: {result['keyword']} ({size_mb:.1f}MB, {result['duration']}초)")
            return video_path

        return None

    # 하위 호환: 기존 fetch_scene_videos 호출 시 새 방식으로 리다이렉트
    def fetch_scene_videos(self, script_data: dict, work_dir: str) -> list[dict]:
        """하위 호환 래퍼 — v6.1에서는 fetch_satisfying_background(mood=) 사용 권장"""
        mood = script_data.get("mood", "")
        bg_path = self.fetch_satisfying_background(work_dir, mood=mood)
        if bg_path:
            return [{"chunk_idx": -1, "video_path": bg_path, "scene_hint": "satisfying"}]
        return []


# ============================================================
# 🎬 Kling AI Image-to-Video (첫/마지막 장면 동영상화)
# ============================================================
class KlingVideoGenerator:
    """Kling AI API: 정적 이미지 → 5초 동영상 변환 (JWT 인증)"""
    BASE_URL = "https://api.klingai.com"

    def __init__(self):
        self.access_key = os.getenv("KLING_ACCESS_KEY", "")
        self.secret_key = os.getenv("KLING_SECRET_KEY", "")
        self._token = None
        self._token_exp = 0

    @property
    def available(self) -> bool:
        return bool(self.access_key and self.secret_key)

    def _get_token(self) -> str:
        """JWT 토큰 생성 (HS256, 1800초 유효)"""
        import jwt as pyjwt
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token
        payload = {
            "iss": self.access_key,
            "exp": int(now + 1800),
            "nbf": int(now - 5),
            "iat": int(now),
        }
        self._token = pyjwt.encode(payload, self.secret_key, algorithm="HS256")
        self._token_exp = now + 1800
        return self._token

    def _upload_temp_image(self, image_path: str) -> str:
        """이미지를 임시 호스팅에 업로드 → URL 반환"""
        try:
            with open(image_path, "rb") as f:
                resp = requests.post(
                    "https://0x0.st",
                    files={"file": (os.path.basename(image_path), f)},
                    timeout=30,
                )
            if resp.status_code == 200:
                url = resp.text.strip()
                print(f"    📤 이미지 업로드: {url}")
                return url
        except Exception as e:
            print(f"    ⚠️  이미지 업로드 실패: {e}")
        return ""

    def generate_video(self, image_path: str, prompt: str,
                       output_path: str, duration: int = 5) -> bool:
        """이미지 → 동영상 변환 (동기 폴링, 최대 5분 대기)"""
        if not self.available:
            return False
        try:
            # 이미지를 임시 호스팅에 업로드하여 URL 획득
            image_url = self._upload_temp_image(image_path)
            if not image_url:
                print(f"    ⚠️  Kling: 이미지 URL 생성 실패")
                return False

            token = self._get_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            # 태스크 생성
            body = {
                "model_name": "kling-v1",
                "image": image_url,
                "prompt": prompt[:200],
                "mode": "std",
                "duration": str(duration),
                "cfg_scale": 0.5,
            }
            resp = requests.post(
                f"{self.BASE_URL}/v1/videos/image2video",
                json=body, headers=headers, timeout=30,
            )
            if resp.status_code != 200:
                print(f"    ⚠️  Kling API {resp.status_code}: {resp.text[:200]}")
                return False
            result = resp.json()
            task_id = result.get("data", {}).get("task_id")
            if not task_id:
                print(f"    ⚠️  Kling 태스크 생성 실패: {result}")
                return False

            print(f"    🎬 Kling 태스크 생성: {task_id}")

            # 폴링 (최대 300초)
            for _ in range(60):
                time.sleep(5)
                token = self._get_token()
                headers["Authorization"] = f"Bearer {token}"
                qr = requests.get(
                    f"{self.BASE_URL}/v1/videos/image2video/{task_id}",
                    headers=headers, timeout=15,
                )
                qr.raise_for_status()
                status_data = qr.json().get("data", {})
                task_status = status_data.get("task_status", "")

                if task_status == "succeed":
                    videos = status_data.get("task_result", {}).get("videos", [])
                    if videos:
                        video_url = videos[0].get("url", "")
                        if video_url:
                            vr = requests.get(video_url, timeout=60)
                            vr.raise_for_status()
                            with open(output_path, "wb") as f:
                                f.write(vr.content)
                            print(f"    ✅ Kling 동영상 완료: {output_path}")
                            return True
                    return False
                elif task_status == "failed":
                    err = status_data.get("task_status_msg", "unknown")
                    print(f"    ⚠️  Kling 실패: {err}")
                    return False
            print(f"    ⚠️  Kling 타임아웃 (300초)")
            return False
        except Exception as e:
            print(f"    ⚠️  Kling 예외: {str(e)[:100]}")
            return False


# ============================================================
# 🖼️ AI 이미지 생성기 (Pollinations.ai 무료 + DALL-E 폴백)
# ============================================================
class ImageGenerator:
    """
    v7.2: 웹툰형 쇼츠용 장면별 이미지 생성기
    ─ 1순위: Replicate FLUX-schnell (웹툰/만화 스타일, go_fast, 9:16)
    ─ 2순위: Pexels 스톡 이미지 (무료 폴백, 고품질)
    ─ 출력: 1080x1920 (9:16 세로)
    ─ 용도: 대본 문장별 시각화 이미지 → Ken Burns 효과 적용
    """

    # ── 웹툰 프롬프트 엔지니어링 (★ 한국 B급 웹툰 특화) ──
    WEBTOON_PREFIX = (
        "Korean Naver webtoon realistic slice-of-life illustration, "
        "thick clean ink outlines, muted warm realistic color palette, "
        "realistic human proportions, detailed Korean facial features, "
        "realistic detailed Korean everyday background setting, "
        "warm dim natural lighting, moody cinematic tone, "
        "consistent character design throughout, "
        "absolutely NO text NO letters NO words NO writing NO watermark on the image, "
        "AVOID Japanese anime, AVOID big round eyes, AVOID chibi proportions, "
    )
    WEBTOON_NEGATIVE = (
        "Japanese anime, anime eyes, chibi, kawaii, moe, manga, "
        "pastel colors, sparkly eyes, "
        "photorealistic, photograph, 3d render, "
        "text, letters, words, writing, caption, subtitle, "
        "watermark, signature, logo, blurry, low quality, "
        "Japanese text, kanji, hiragana, katakana, Chinese characters"
    )

    # 무드별 스타일 보강 (★ 한국 현실 고증 / 고독 / 무거운 톤)
    MOOD_STYLE = {
        "angry": "dark red shadows, character gritting teeth in dim smoky room, oppressive tense atmosphere, ",
        "funny": "dim warm lighting, character with exhausted bitter smirk, dark humor irony, not cheerful, ",
        "sad": "cold blue darkness, character alone staring at empty soju glass, heavy lonely silence, ",
        "touching": "faint warm light in darkness, character with weary but relieved eyes, bittersweet moment, ",
        "scary": "pitch dark shadows, character pale with cold sweat, dread and isolation, ",
        "shocking": "harsh single spotlight in darkness, character frozen with hollow stare, devastating realization, ",
        "satisfying": "dim moody lighting, character with tired but defiant smirk, quiet victory alone, ",
    }

    # Pexels 폴백용 키워드 매핑
    PEXELS_KEYWORD_MAP = {
        "현관문": "door lock", "도어락": "smart door lock", "비번": "door keypad",
        "냉장고": "refrigerator food", "반찬": "korean side dishes", "주방": "kitchen",
        "아파트": "apartment building", "신혼집": "modern apartment interior",
        "CCTV": "security camera", "지문": "fingerprint scanner",
        "시어머니": "angry woman phone", "남편": "man worried", "경찰": "police",
        "전화": "phone call", "택배": "delivery package box", "에어팟": "airpods white",
        "콩나물": "bean sprouts", "중고거래": "online shopping phone", "사기": "fraud scam",
    }

    MOOD_PEXELS = {
        "angry": ["dramatic red", "breaking glass", "fire close up"],
        "funny": ["colorful abstract", "pop art", "bright neon"],
        "sad": ["rain window", "dark ocean", "lonely night"],
        "touching": ["sunset warm", "golden light", "flowers bloom"],
        "scary": ["dark forest", "fog horror", "abandoned building"],
        "shocking": ["lightning storm", "dramatic sky", "broken mirror"],
        "satisfying": ["marble texture", "geometric pattern", "water drop"],
    }

    def __init__(self):
        self.replicate_token = os.getenv("REPLICATE_API_TOKEN", "")
        self.pexels_key = os.getenv("PEXELS_API_KEY", "")
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self._gen_count = 0
        self._used_photo_ids = set()
        self._bing_creator = None  # Bing DALL-E 3 (lazy init)
        self._bing_failed = False  # Bing 전체 실패 플래그
        # v6.0: GoAPI Midjourney (0순위)
        self._goapi = None
        self._goapi_failed = False
        # v10.0: Kling AI image-to-video (첫/마지막 장면)
        self._kling = KlingVideoGenerator()
        if self._kling.available:
            print(f"  🎬 Kling AI 연동 완료 (첫/마지막 장면 동영상화)")

    def _get_bing_creator(self):
        """Bing Image Creator 인스턴스 (lazy init, 브라우저 1개 재사용)"""
        if self._bing_creator is None and not self._bing_failed:
            try:
                from bing_generator import BingImageCreator
                self._bing_creator = BingImageCreator()
            except Exception as e:
                print(f"    ⚠️  Bing Creator 초기화 실패: {str(e)[:80]}")
                self._bing_failed = True
        return self._bing_creator

    def generate_scene_images(self, script_data: dict, work_dir: str) -> list[dict]:
        """
        v6.0: 대본의 각 장면에 대해 웹툰 이미지 생성.
        우선순위: GoAPI Midjourney → Replicate FLUX → Bing DALL-E 3 → 재사용
        Returns: [{"chunk_idx": 0, "end_idx": 2, "image_path": "...", "prompt": "..."}]
        """
        # ★ 캐릭터 일관성: 새 영상 시작 시 캐릭터 기억 리셋
        self._character_desc = ""
        if self._goapi:
            self._goapi.reset_session()

        script_lines = script_data.get("script", [])
        mood = script_data.get("mood", "")

        images_dir = os.path.join(work_dir, "_scene_images")
        os.makedirs(images_dir, exist_ok=True)

        results = []
        scene_groups = self._group_sentences(script_lines)

        # 엔진 우선순위 표시
        engines = []
        if self._goapi and not self._goapi_failed:
            engines.append("Midjourney (GoAPI)")
        if self.replicate_token:
            engines.append("Replicate FLUX")
        engines.append("Bing DALL-E 3")
        print(f"\n  🖼️  장면 이미지 생성 중... ({len(scene_groups)}장, mood={mood})")
        print(f"    엔진 우선순위: {' → '.join(engines)}")

        bing_consecutive_fail = 0
        goapi_consecutive_fail = 0
        last_success_path = ""  # ★ 직전 성공 이미지 경로 (Pexels 대신 재사용)

        for gi, group in enumerate(scene_groups):
            raw_prompt = group.get("image_prompt", "")
            image_path = os.path.join(images_dir, f"scene_{gi:03d}.jpg")
            success = False

            # ── 0순위: GoAPI Midjourney (--sref/--cref 캐릭터 일관성) ──
            if self._goapi and not self._goapi_failed and goapi_consecutive_fail < 3:
                try:
                    mj_prompt = self._build_mj_prompt_for_goapi(
                        raw_prompt, group["texts"], mood
                    )
                    # 첫 이미지: sref/cref 없음 → 이후: 자동 주입
                    sref = self._goapi.first_image_url if gi > 0 else None
                    cref = self._goapi.first_image_url if gi > 0 else None
                    success = self._goapi.generate_image(
                        mj_prompt, image_path,
                        style_ref=sref, char_ref=cref,
                    )
                    if success:
                        goapi_consecutive_fail = 0
                        print(f"    ✅ [{gi+1}/{len(scene_groups)}] 🎨 Midjourney: "
                              f"{raw_prompt[:45]}...")
                    else:
                        goapi_consecutive_fail += 1
                        if goapi_consecutive_fail >= 3:
                            print(f"    ⚠️  GoAPI 3회 연속 실패 → 폴백 전환")
                            self._goapi_failed = True
                except Exception as e:
                    goapi_consecutive_fail += 1
                    print(f"    ⚠️  GoAPI 예외: {e}")
                    if goapi_consecutive_fail >= 3:
                        self._goapi_failed = True

            # ── 1순위: Replicate FLUX-schnell ──
            if not success and self.replicate_token:
                webtoon_prompt = self._build_webtoon_prompt(raw_prompt, group["texts"], mood)
                webp_path = image_path.replace(".jpg", ".webp")
                success = self._generate_replicate(webtoon_prompt, webp_path)
                if success:
                    image_path = webp_path
                    print(f"    ✅ [{gi+1}/{len(scene_groups)}] 🤖 FLUX: {raw_prompt[:45]}...")
                else:
                    # ★ NSFW 차단 시 safe-for-work 프롬프트로 1회 재시도
                    safe_prompt = (
                        "safe for work, cartoon illustration, "
                        + webtoon_prompt.replace("sexy", "").replace("nude", "")
                        .replace("violence", "action").replace("blood", "red")
                    )
                    success = self._generate_replicate(safe_prompt, webp_path)
                    if success:
                        image_path = webp_path
                        print(f"    ✅ [{gi+1}/{len(scene_groups)}] 🤖 FLUX (SFW 재시도): {raw_prompt[:35]}...")

            # ── 2순위: Bing Image Creator (DALL-E 3 웹툰) ──
            if not success and not self._bing_failed and bing_consecutive_fail < 3:
                webtoon_prompt = self._build_webtoon_prompt(raw_prompt, group["texts"], mood)
                bing = self._get_bing_creator()
                if bing:
                    success = bing.generate_image(webtoon_prompt, image_path)
                    if success:
                        bing_consecutive_fail = 0
                        print(f"    ✅ [{gi+1}/{len(scene_groups)}] 🎨 Bing: {raw_prompt[:45] or webtoon_prompt[80:125]}...")
                    else:
                        bing_consecutive_fail += 1
                        if bing_consecutive_fail >= 3:
                            print(f"    ⚠️  Bing 3회 연속 실패 → 폴백 전환")
                            self._bing_failed = True

            # ── 3순위: 직전 성공 이미지 재사용 (Pexels 스톡사진 → 화풍 깨짐 방지) ──
            if not success and last_success_path and os.path.exists(last_success_path):
                import shutil as _shutil
                _shutil.copy2(last_success_path, image_path)
                success = True
                print(f"    ♻️  [{gi+1}/{len(scene_groups)}] 직전 이미지 재사용 (화풍 일관성 유지)")

            if success:
                self._gen_count += 1
                last_success_path = image_path  # ★ 성공한 이미지 경로 기억
                results.append({
                    "chunk_idx": group["start_idx"],
                    "end_idx": group["end_idx"],
                    "image_path": image_path,
                    "prompt": raw_prompt or "auto",
                })
            else:
                print(f"    ⚠️  [{gi+1}] 이미지 실패 → 그라데이션 폴백")
                results.append({
                    "chunk_idx": group["start_idx"],
                    "end_idx": group["end_idx"],
                    "image_path": None,
                    "prompt": raw_prompt or "auto",
                })

            # 속도 조절 (Replicate 429 방지: 3초 딜레이)
            if gi < len(scene_groups) - 1:
                time.sleep(3)

        # Bing 브라우저 종료
        if self._bing_creator:
            try:
                self._bing_creator.close()
            except Exception:
                pass

        ok_count = sum(1 for r in results if r["image_path"])
        print(f"  ✅ 장면 이미지 완료: {ok_count}/{len(scene_groups)}장 생성")

        # ★ v10.0: Kling AI — 첫/마지막 장면만 image-to-video 변환
        if self._kling.available and results:
            kling_targets = []
            if results[0].get("image_path"):
                kling_targets.append((0, results[0]))
            if len(results) > 1 and results[-1].get("image_path"):
                kling_targets.append((len(results) - 1, results[-1]))

            for idx, r in kling_targets:
                img_path = r["image_path"]
                vid_path = img_path.rsplit(".", 1)[0] + "_kling.mp4"
                prompt_text = r.get("prompt", "cinematic slow motion")
                print(f"  🎬 Kling AI 동영상 변환 [{idx+1}/{len(results)}]...")
                ok = self._kling.generate_video(img_path, prompt_text, vid_path)
                if ok:
                    r["kling_video"] = vid_path
                else:
                    print(f"    ⚠️  Kling 실패 → Bing 이미지 유지 (폴백)")

        return results

    # ── 문장 그루핑 ──
    def _group_sentences(self, script_lines: list) -> list[dict]:
        """2~3문장씩 그루핑 → 장면 단위로 이미지 1장"""
        groups = []
        i = 0
        while i < len(script_lines):
            if script_lines[i].get("highlight"):
                groups.append({
                    "start_idx": i, "end_idx": i,
                    "texts": [script_lines[i]["text"]],
                    "image_prompt": script_lines[i].get("image_prompt", ""),
                })
                i += 1
            else:
                end = min(i + 3, len(script_lines))
                for j in range(i + 1, end):
                    if script_lines[j].get("highlight"):
                        end = j
                        break
                texts = [script_lines[k]["text"] for k in range(i, end)]
                img_prompt = script_lines[i].get("image_prompt", "")
                groups.append({
                    "start_idx": i, "end_idx": end - 1,
                    "texts": texts, "image_prompt": img_prompt,
                })
                i = end
        return groups

    # ── 웹툰 프롬프트 빌드 ──
    # ── 캐릭터 일관성: 첫 장면에서 설정한 캐릭터 묘사를 이후에도 유지 ──
    _character_desc = ""  # 클래스 레벨 캐릭터 기억

    def _build_webtoon_prompt(self, image_prompt: str, texts: list[str],
                               mood: str) -> str:
        """image_prompt → B급 한국 웹툰 스타일 FLUX 프롬프트 빌드
        ★ 캐릭터 일관성: 첫 장면 캐릭터 묘사를 이후 장면에 자동 삽입
        """
        mood_style = self.MOOD_STYLE.get(mood, "")
        # ★ 캐릭터 유지 접미사
        char_suffix = ""
        if self._character_desc:
            char_suffix = f", same character as before: {self._character_desc}"

        if image_prompt:
            # image_prompt → 영어 확인/변환 (v10: Gemini가 영어로 출력하면 바로 통과)
            en_prompt = self._auto_en_prompt_from_kr(image_prompt, mood)
            full = f"{self.WEBTOON_PREFIX}{mood_style}{en_prompt}{char_suffix}"
            # 첫 장면이면 캐릭터 묘사 기억
            if not self._character_desc and en_prompt:
                self._character_desc = en_prompt[:120]
            return full

        # 한글 텍스트 → 자동 영어 변환
        en_prompt = self._auto_en_prompt(texts, mood)
        full = f"{self.WEBTOON_PREFIX}{mood_style}{en_prompt}{char_suffix}"
        if not self._character_desc and en_prompt:
            self._character_desc = en_prompt[:120]
        return full

    def _build_mj_prompt_for_goapi(self, image_prompt: str,
                                     texts: list[str], mood: str) -> str:
        """Midjourney 최적화 프롬프트 빌드 (GoAPI용).

        ★ Midjourney는 프롬프트가 짧을수록 잘 동작함 (200자 이내 권장).
        ★ --sref/--cref 파라미터는 goapi_midjourney.py에서 가장 마지막에 붙임.
        """
        mood_style = self.MOOD_STYLE.get(mood, "")
        if image_prompt:
            en_prompt = self._auto_en_prompt_from_kr(image_prompt, mood)
        else:
            en_prompt = self._auto_en_prompt(texts, mood)

        prefix = ("Korean B-grade webtoon manhwa style, bold outlines, "
                   "exaggerated comedic expressions")
        prompt = f"{prefix}, {mood_style}{en_prompt}"

        # Midjourney 프롬프트 200자 제한 (파라미터 씹힘 방지)
        if len(prompt) > 200:
            prompt = prompt[:200].rstrip(", ")

        return prompt

    def _auto_en_prompt_from_kr(self, kr_prompt: str, mood: str) -> str:
        """한국어 image_prompt를 영어로 변환 (Gemini 번역 → 키워드 폴백)
        ★ v10.0: Gemini가 직접 영어로 출력하는 경우 → 바로 반환
        """
        import re
        # ★ 한글이 없으면 이미 영어 → 그대로 반환 (숫자/특수문자 포함 OK)
        if not re.search(r'[가-힣]', kr_prompt):
            return kr_prompt
        # ★ Gemini Flash로 직접 번역 (더 정확한 장면 묘사)
        try:
            import google.generativeai as _genai
            _m = _genai.GenerativeModel("gemini-2.0-flash")
            resp = _m.generate_content(
                f"Translate this Korean image description to English for an AI image generator. "
                f"Keep it as a visual scene description, comma separated keywords. "
                f"Add 'Korean cultural setting' if relevant. Max 80 words. "
                f"Output ONLY the English translation, nothing else.\n\n{kr_prompt}",
                generation_config=_genai.GenerationConfig(
                    temperature=0.2, max_output_tokens=200,
                ),
            )
            if resp.text and len(resp.text.strip()) > 10:
                en = resp.text.strip().replace('"', '').replace("'", "")
                return en
        except Exception:
            pass
        # 폴백: 키워드 매핑
        return self._auto_en_prompt([kr_prompt], mood)

    def _auto_en_prompt(self, texts: list[str], mood: str) -> str:
        """한글 텍스트 → 영어 장면 묘사 자동 생성 (B급 웹툰 과장 스타일)"""
        combined = " ".join(texts)
        kr_en = {
            "시어머니": "angry Korean mother-in-law with exaggerated furious expression",
            "남편": "young Korean husband with comically shocked face",
            "아내": "young Korean wife with dramatic expression",
            "결혼": "wedding scene with over-the-top emotions",
            "이혼": "divorce papers flying dramatically",
            "신혼집": "cozy newlywed apartment interior",
            "비번": "digital door lock keypad glowing ominously",
            "현관문": "apartment front door opening dramatically",
            "냉장고": "refrigerator wide open with food spilling out",
            "경찰": "police officer with stern comedic expression at door",
            "사기": "scam victim with jaw dropping to the floor",
            "택배": "person opening delivery package with extreme surprise",
            "에어팟": "wireless earbuds case close-up",
            "콩나물": "pile of fresh bean sprouts",
            "중고거래": "person staring at phone screen in disbelief",
            "전화": "person holding phone with veins popping from anger",
            "CCTV": "security camera footage on monitor screen",
            "도어락": "smart digital door lock close-up",
            "지문": "fingerprint scanner with blue glow",
            "직장": "office scene with comedic drama",
            "상사": "angry boss character with exaggerated expression",
            "신입": "nervous new employee sweating comically",
            "회식": "Korean company dinner party scene",
            "퇴사": "person throwing resignation letter dramatically",
            "월급": "paycheck with shocking amount",
            "학교": "Korean school classroom scene",
            "선생님": "teacher with dramatic expression",
            "편의점": "convenience store interior late at night",
            "대리": "stressed office worker with comedic exhaustion",
            "카페": "trendy Korean cafe interior",
        }
        parts = []
        for kr, en in kr_en.items():
            if kr in combined:
                parts.append(en)
        if not parts:
            parts = ["dramatic Korean webtoon scene with exaggerated comedic expression"]
        return ", ".join(parts[:4])

    # ── Replicate FLUX-schnell ──
    def _generate_replicate(self, prompt: str, save_path: str) -> bool:
        """Replicate FLUX-schnell 직접 REST API 호출 (SDK 우회)"""
        try:
            headers = {
                "Authorization": f"Token {self.replicate_token}",
                "Content-Type": "application/json",
            }

            payload = {
                "input": {
                    "prompt": prompt,
                    "go_fast": True,
                    "num_outputs": 1,
                    "aspect_ratio": "9:16",
                    "output_format": "webp",
                    "output_quality": 90,
                    "num_inference_steps": 4,
                }
            }

            api_url = "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions"

            # 429 재시도 (exponential backoff: 5초, 10초, 20초)
            pred_resp = None
            for retry in range(4):
                pred_resp = requests.post(
                    api_url, headers=headers, json=payload, timeout=30
                )
                if pred_resp.status_code == 429:
                    wait = 5 * (2 ** retry)  # 5, 10, 20, 40초
                    print(f"    ⏳ Replicate 429 → {wait}초 대기 후 재시도 ({retry+1}/4)")
                    time.sleep(wait)
                    continue
                break  # 429가 아니면 루프 탈출

            if pred_resp.status_code == 402:
                print(f"    ⚠️  Replicate 크레딧 부족")
                return False
            if pred_resp.status_code == 429:
                print(f"    ⚠️  Replicate 429 계속 발생 (4회 재시도 실패)")
                return False
            if pred_resp.status_code not in (200, 201):
                print(f"    ⚠️  Replicate API: {pred_resp.status_code}")
                return False

            pred = pred_resp.json()
            get_url = pred.get("urls", {}).get("get", "")
            if not get_url:
                return False

            # 2. 결과 폴링 (최대 60초)
            for _ in range(30):
                time.sleep(2)
                result = requests.get(get_url, headers=headers, timeout=10).json()
                status = result.get("status", "")

                if status == "succeeded":
                    outputs = result.get("output", [])
                    if outputs:
                        img_url = outputs[0]
                        img_resp = requests.get(img_url, timeout=60)
                        if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                            from PIL import Image
                            from io import BytesIO
                            img = Image.open(BytesIO(img_resp.content)).convert("RGB")
                            img = img.resize((1080, 1920), Image.LANCZOS)
                            img.save(save_path, "WEBP", quality=92)
                            return True
                    return False
                elif status == "failed":
                    err = result.get("error", "unknown")
                    print(f"    ⚠️  Replicate 생성 실패: {str(err)[:80]}")
                    return False

            print(f"    ⚠️  Replicate 타임아웃")
            return False

        except Exception as e:
            err_str = str(e)
            if "Unauthenticated" in err_str or "401" in err_str:
                print(f"    ⚠️  Replicate 인증 실패")
            else:
                print(f"    ⚠️  Replicate 실패: {err_str[:80]}")
        return False

    # ── Pexels 폴백 ──
    def _prompt_to_pexels_query(self, image_prompt: str, texts: list[str],
                                 mood: str) -> str:
        """image_prompt → Pexels 검색어 변환"""
        if image_prompt:
            stop_words = {
                "a", "an", "the", "with", "and", "of", "in", "on", "at", "to",
                "style", "cinematic", "dramatic", "lighting", "close-up", "shot",
                "atmosphere", "composition", "vertical", "4k", "photorealistic",
                "modern", "korean", "scene", "showing", "from",
            }
            words = image_prompt.lower().replace(",", " ").split()
            keywords = [w for w in words if w not in stop_words and len(w) > 2]
            if keywords:
                return " ".join(keywords[:4])

        combined = " ".join(texts)
        en_parts = []
        for kr, en in self.PEXELS_KEYWORD_MAP.items():
            if kr in combined:
                en_parts.append(en)
        if en_parts:
            return " ".join(en_parts[:3])

        import random
        mood_keys = self.MOOD_PEXELS.get(mood, ["cinematic texture", "abstract dark"])
        return random.choice(mood_keys)

    def _search_pexels(self, query: str, save_path: str) -> bool:
        """Pexels에서 세로 이미지 검색 + 다운로드"""
        try:
            headers = {"Authorization": self.pexels_key}
            url = (f"https://api.pexels.com/v1/search"
                   f"?query={requests.utils.quote(query)}"
                   f"&per_page=15&orientation=portrait")
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return False

            photos = resp.json().get("photos", [])
            if not photos:
                short_query = " ".join(query.split()[:2])
                url2 = (f"https://api.pexels.com/v1/search"
                        f"?query={requests.utils.quote(short_query)}"
                        f"&per_page=15&orientation=portrait")
                resp2 = requests.get(url2, headers=headers, timeout=15)
                if resp2.status_code == 200:
                    photos = resp2.json().get("photos", [])
                if not photos:
                    return False

            available = [p for p in photos if p["id"] not in self._used_photo_ids]
            if not available:
                available = photos

            import random
            chosen = random.choice(available[:5])
            self._used_photo_ids.add(chosen["id"])

            img_url = chosen["src"].get("portrait", chosen["src"].get("large2x", ""))
            if not img_url:
                return False

            img_resp = requests.get(img_url, timeout=30)
            if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                from PIL import Image
                from io import BytesIO
                img = Image.open(BytesIO(img_resp.content)).convert("RGB")
                img = img.resize((1080, 1920), Image.LANCZOS)
                img.save(save_path, quality=92)
                return True
        except Exception as e:
            print(f"    ⚠️  Pexels 실패: {e}")
        return False


# ============================================================
# 🎬 영상 소스 자동 편집기 (yt-dlp + Gemini Vision → 숏츠 편집)
# ============================================================
class VideoAutoEditor:
    """
    v5.0: Reddit/YouTube URL → 하이라이트 추출 → 9:16 숏츠 자동 변환
    비용: $0 (Gemini 2.0 Flash 무료 쿼터 + yt-dlp + FFmpeg)

    사용:
      python main.py --url "https://www.reddit.com/r/.../comments/..." --video-edit
      python main.py --url "https://www.youtube.com/watch?v=..." --video-edit
    """

    def __init__(self, config):
        self.config = config
        self.download_dir = os.path.join(config.output_dir, "_video_temp")
        os.makedirs(self.download_dir, exist_ok=True)

        # yt-dlp 경로 자동 탐색 (PATH에 없을 때 Scripts 폴더에서 찾기)
        self.ytdlp_cmd = self._find_ytdlp()

        # Gemini Vision 모델 (영상 분석용 — 무료)
        api_key = config.google_api_key
        if not api_key:
            raise ValueError("GOOGLE_API_KEY 필요 (영상 분석용)")
        genai_flash.configure(api_key=api_key)
        self.model = genai_flash.GenerativeModel("gemini-2.0-flash")

    @staticmethod
    def _find_ytdlp() -> list:
        """yt-dlp 실행 경로를 자동 탐색"""
        import shutil
        # 1차: PATH에서 찾기
        if shutil.which("yt-dlp"):
            return ["yt-dlp"]
        # 2차: Python Scripts 폴더
        scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
        ytdlp_exe = os.path.join(scripts_dir, "yt-dlp.exe")
        if os.path.exists(ytdlp_exe):
            return [ytdlp_exe]
        # 3차: python -m yt_dlp
        return [sys.executable, "-m", "yt_dlp"]

    # 검증된 대박 영상만 소싱 (10만뷰 미만 차단)
    MIN_VIEW_COUNT = 100_000

    def download_video(self, url: str) -> Optional[str]:
        """yt-dlp로 검증된 바이럴 영상만 다운로드 (view_count >= 100K 필터)"""
        output_template = os.path.join(self.download_dir, "%(id)s.%(ext)s")
        cmd = self.ytdlp_cmd + [
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", output_template,
            "--no-playlist",
            "--max-filesize", "500M",
            # ── 10만뷰 이상만 다운로드 (검증된 대박 영상) ──
            "--match-filter", f"view_count >= {self.MIN_VIEW_COUNT}",
            url,
        ]
        try:
            print(f"\n  ⬇️  영상 다운로드: {url[:60]}...")
            print(f"     🔥 조건: 조회수 {self.MIN_VIEW_COUNT:,}회 이상만 허용")
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
                encoding="utf-8", errors="replace",
            )
            if result.returncode != 0:
                stderr = result.stderr[:300]
                if "filter" in stderr.lower() or "not pass" in stderr.lower():
                    print(f"  🚫 조회수 {self.MIN_VIEW_COUNT:,}회 미달 → 쓰레기 영상 차단됨")
                else:
                    print(f"  ❌ yt-dlp 실패: {stderr[:200]}")
                return None

            # 가장 최근 mp4 파일 찾기
            files = [
                os.path.join(self.download_dir, f)
                for f in os.listdir(self.download_dir)
                if f.endswith(".mp4")
            ]
            if not files:
                print("  ❌ 다운로드된 MP4 없음")
                return None

            latest = max(files, key=os.path.getctime)
            size_mb = os.path.getsize(latest) / (1024 * 1024)
            print(f"  ✅ 다운로드 완료: {os.path.basename(latest)} ({size_mb:.1f}MB)")
            return latest

        except subprocess.TimeoutExpired:
            print("  ⏰ 다운로드 타임아웃 (5분 초과)")
            return None
        except FileNotFoundError:
            print("  ❌ yt-dlp가 설치되어 있지 않습니다!")
            print("     pip install yt-dlp")
            return None
        except Exception as e:
            print(f"  ❌ 다운로드 에러: {e}")
            return None

    def get_highlights(self, video_path: str) -> Optional[dict]:
        """Gemini Vision으로 영상 분석 → 하이라이트 구간 추출"""
        print("  👀 AI 영상 분석: 도파민 구간 탐색 중...")
        try:
            video_file = genai_flash.upload_file(path=video_path)

            # 업로드 처리 대기
            wait_count = 0
            while video_file.state.name == "PROCESSING":
                time.sleep(3)
                video_file = genai_flash.get_file(video_file.name)
                wait_count += 1
                if wait_count > 60:  # 3분 타임아웃
                    print("  ⏰ 영상 처리 타임아웃")
                    return None

            if video_file.state.name == "FAILED":
                print(f"  ❌ Gemini 영상 처리 실패")
                return None

            prompt = """이 영상에서 유튜브 숏츠로 만들기 가장 좋은 구간을 찾고,
그 구간에 덮을 한국어 나레이션 대본도 써줘.

조건:
- 최대 60초 이내
- 가장 충격적이거나, 웃기거나, 감동적인 구간
- 시작/끝 타임스탬프를 초 단위로
- 나레이션은 한국어, 유튜브 숏츠 말투 (구어체, 반말OK, 텐션 높게)
- 첫 문장은 반드시 "이거 실화냐" / "미쳤다 진짜" 같은 후킹 멘트
- 감정 지문을 반드시 포함해: (놀람), (충격), (소름), (속삭임), (강조), (웃음) 등
  예: "(놀람) 이거 실화냐?! 이 사람이 방금 한 짓 좀 봐."

반드시 아래 JSON 형식으로만 답해:
{"start_sec": 0, "end_sec": 60, "reason": "이유를 한줄로", "narration": "여기에 나레이션 전체 대본"}"""

            response = self.model.generate_content(
                [video_file, prompt],
                generation_config=genai_flash.GenerationConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )

            result = json.loads(response.text)
            start = result.get("start_sec", 0)
            end = result.get("end_sec", 60)
            reason = result.get("reason", "")
            narration = result.get("narration", "")

            # 유효성 체크
            if end <= start:
                end = start + 60
            if end - start > 60:
                end = start + 60

            print(f"  🎯 하이라이트: {start}초 ~ {end}초 ({end - start}초)")
            if reason:
                print(f"     이유: {reason}")
            if narration:
                print(f"  📝 나레이션: {narration[:50]}...")

            return {"start_sec": start, "end_sec": end, "reason": reason, "narration": narration}

        except Exception as e:
            print(f"  ❌ 영상 분석 실패: {e}")
            return None

    # ── 대본 지문(stage direction) → SSML 변환 매핑 ──
    # (놀람) → 볼륨 UP + 약간 더 빠르게
    # (속삭임) → 볼륨 DOWN + 느리게
    # (강조) → 볼륨 UP
    STAGE_DIRECTION_MAP = {
        "(놀람)":   ("<prosody volume='+30%' rate='+10%'>",  "</prosody>"),
        "(충격)":   ("<prosody volume='+30%' rate='+10%'>",  "</prosody>"),
        "(소름)":   ("<prosody volume='+20%' rate='-5%'>",   "</prosody>"),
        "(속삭임)": ("<prosody volume='-20%' rate='-10%'>",  "</prosody>"),
        "(강조)":   ("<prosody volume='+25%'>",              "</prosody>"),
        "(분노)":   ("<prosody volume='+35%' rate='+15%'>",  "</prosody>"),
        "(슬픔)":   ("<prosody volume='-10%' rate='-15%'>",  "</prosody>"),
        "(웃음)":   ("<prosody volume='+15%' rate='+5%'>",   "</prosody>"),
    }

    def _convert_stage_directions_to_ssml(self, text: str) -> str:
        """대본 지문 태그를 SSML prosody로 변환.
        예: '이거 (놀람) 실화냐?!' → SSML로 해당 부분만 볼륨/속도 조절
        """
        result = text
        for tag, (open_ssml, close_ssml) in self.STAGE_DIRECTION_MAP.items():
            if tag in result:
                # 지문 태그 제거하고, 해당 지문 뒤의 문장 끝(. ! ? 또는 다음 지문)까지를 SSML로 감쌈
                parts = result.split(tag)
                converted = parts[0]
                for part in parts[1:]:
                    # 다음 문장 끝 찾기
                    end_idx = -1
                    for punct in [".", "!", "?", "\n"]:
                        idx = part.find(punct)
                        if idx != -1 and (end_idx == -1 or idx < end_idx):
                            end_idx = idx + 1

                    if end_idx > 0:
                        converted += open_ssml + part[:end_idx] + close_ssml + part[end_idx:]
                    else:
                        converted += open_ssml + part + close_ssml
                result = converted
        return result

    async def _generate_narration_tts(self, text: str, output_mp3: str) -> Optional[str]:
        """
        edge-tts SSML 나레이션 (틱톡커 톤, 무료)
        - 음성: ko-KR-SunHiNeural 강제 (여성, 밝은 텐션)
        - 속도: +15% (빠르게, 숏츠 최적)
        - 피치: +2Hz (들뜬 톤, 도파민)
        - 지문 처리: (놀람)→볼륨UP, (속삭임)→볼륨DOWN 등 SSML 변환
        """
        if not text or not text.strip():
            return None

        print(f"  🗣️  AI 나레이션 TTS 생성 중... ({len(text)}자)")
        try:
            # ── 지문 태그를 SSML로 변환 ──
            ssml_body = self._convert_stage_directions_to_ssml(text)

            # ── SSML 래핑: rate +15%, pitch +2Hz (틱톡커 톤) ──
            ssml_text = (
                "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='ko-KR'>"
                "<prosody rate='+15%' pitch='+2Hz'>"
                f"{ssml_body}"
                "</prosody>"
                "</speak>"
            )

            # ── SunHi 강제 고정 (config 무시) ──
            voice = "ko-KR-SunHiNeural"
            communicate = edge_tts.Communicate(ssml_text, voice)
            await communicate.save(output_mp3)

            if os.path.exists(output_mp3) and os.path.getsize(output_mp3) > 1000:
                size_kb = os.path.getsize(output_mp3) // 1024
                print(f"  ✅ 나레이션 TTS 완료: {size_kb}KB (SunHi +15% +2Hz)")
                return output_mp3
            else:
                print("  ⚠️  TTS 출력 비정상")
                return None
        except Exception as e:
            print(f"  ⚠️  나레이션 TTS 실패: {e}")
            return None

    def edit_to_shorts(self, input_path: str, start_sec: int,
                       end_sec: int, output_path: str,
                       tts_path: Optional[str] = None) -> Optional[str]:
        """
        FFmpeg 프로급 9:16 숏츠 편집 (구독자 1만+ 채널 퀄리티)
        - 3단 레이아웃: 블러 배경(어둡게) + 중앙 원본 + 컬러 그레이딩
        - TTS 나레이션 믹싱: 원본 15% BGM + TTS 160% + loudnorm 마스터링
        - 인코딩: CRF 20 (고화질) + AAC 256k + faststart
        """
        has_tts = tts_path and os.path.exists(tts_path)
        mode = "🎙️ 나레이션 믹싱" if has_tts else "🔊 원본 오디오"
        print(f"  ✂️  프로급 숏츠 편집: {start_sec}s → {end_sec}s ({mode})")

        ffmpeg_path = _get_ffmpeg_path()

        # ── 공통 비디오 필터: 3단 레이아웃 + 시네마틱 컬러 ──
        # Layer 1 (bg): 확대 + 블러(25px) + 어둡게(brightness -0.15)
        # Layer 2 (fg): 원본 비율 유지 + 중앙 배치 + 얇은 비네팅
        # Layer 3: eq로 미세 컬러 그레이딩 (대비 +10%, 채도 +15%)
        video_filter_base = (
            f"[0:v]trim=start={start_sec}:end={end_sec},setpts=PTS-STARTPTS[v0];"
            f"[v0]split[bg_src][fg_src];"
            # 배경: 꽉 채움 + 강한 블러 + 어둡게
            f"[bg_src]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,boxblur=25:15,"
            f"eq=brightness=-0.15:contrast=0.9[bg_dark];"
            # 전경: 비율 유지 + 중앙 패딩
            f"[fg_src]scale=1080:-2:force_original_aspect_ratio=decrease,"
            f"scale='min(1080,iw)':'min(1440,ih)'[fg_scaled];"
            # 합성 + 컬러 그레이딩 (대비↑ 채도↑)
            f"[bg_dark][fg_scaled]overlay=(W-w)/2:(H-h)/2,"
            f"eq=contrast=1.1:saturation=1.15"
        )

        if has_tts:
            # ── TTS 나레이션 + 원본 BGM 믹싱 + loudnorm 마스터링 ──
            filter_complex = (
                f"{video_filter_base}[video];"
                # 오디오: 원본 15%(BGM) + TTS 160%(주도) → loudnorm(-14 LUFS)
                f"[0:a]atrim=start={start_sec}:end={end_sec},"
                f"asetpts=PTS-STARTPTS,volume=0.15,"
                f"highpass=f=80,lowpass=f=8000[bgm];"
                f"[1:a]volume=1.6,"
                f"highpass=f=60,acompressor=threshold=-18dB:ratio=3:attack=5:release=50[tts];"
                f"[bgm][tts]amix=inputs=2:duration=longest,"
                f"loudnorm=I=-14:TP=-1.5:LRA=11[audio]"
            )
            cmd = [
                ffmpeg_path, "-y",
                "-i", input_path,
                "-i", tts_path,
                "-filter_complex", filter_complex,
                "-map", "[video]", "-map", "[audio]",
                "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                "-profile:v", "high", "-level", "4.1",
                "-c:a", "aac", "-b:a", "256k", "-ar", "44100",
                "-movflags", "+faststart",
                "-shortest",
                output_path,
            ]
        else:
            # ── 원본 오디오 + loudnorm ──
            filter_complex = (
                f"{video_filter_base}[video];"
                f"[0:a]atrim=start={start_sec}:end={end_sec},"
                f"asetpts=PTS-STARTPTS,"
                f"loudnorm=I=-14:TP=-1.5:LRA=11[audio]"
            )
            cmd = [
                ffmpeg_path, "-y",
                "-i", input_path,
                "-filter_complex", filter_complex,
                "-map", "[video]", "-map", "[audio]",
                "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                "-profile:v", "high", "-level", "4.1",
                "-c:a", "aac", "-b:a", "256k", "-ar", "44100",
                "-movflags", "+faststart",
                output_path,
            ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0 and os.path.exists(output_path):
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                print(f"  ✅ 프로급 숏츠 완료: {os.path.basename(output_path)} ({size_mb:.1f}MB)")
                return output_path
            else:
                print(f"  ❌ FFmpeg 실패: {result.stderr[:300]}")
                return None
        except Exception as e:
            print(f"  ❌ 편집 에러: {e}")
            return None

    async def process_url_async(self, url: str) -> Optional[str]:
        """URL → 다운로드 → 분석 → 나레이션 TTS → 숏츠 편집 (전자동)"""
        print(f"\n{'='*60}")
        print(f"🎬 VideoAutoEditor: 영상 소스 → 나레이션 숏츠 변환")
        print(f"{'='*60}")

        tts_path = None

        # Step 1: 다운로드
        video_path = self.download_video(url)
        if not video_path:
            return None

        # Step 2: 하이라이트 + 나레이션 대본 추출
        highlights = self.get_highlights(video_path)
        if not highlights:
            print("  ⚠️  분석 실패 → 첫 60초, 나레이션 없이 편집")
            highlights = {"start_sec": 0, "end_sec": 60, "reason": "기본 구간", "narration": ""}

        # Step 3: 나레이션 TTS 생성 (있을 때만)
        narration = highlights.get("narration", "")
        if narration:
            tts_path = os.path.join(self.download_dir, "narration_tts.mp3")
            tts_path = await self._generate_narration_tts(narration, tts_path)

        # Step 4: 숏츠 편집 (나레이션 믹싱 포함)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(
            self.config.output_dir,
            f"shorts_video_{timestamp}.mp4"
        )
        result = self.edit_to_shorts(
            video_path,
            highlights["start_sec"],
            highlights["end_sec"],
            output_path,
            tts_path=tts_path,
        )

        # 임시 파일 정리
        for temp in [video_path, tts_path]:
            try:
                if temp and os.path.exists(temp):
                    os.remove(temp)
            except OSError:
                pass

        return result

    def process_url(self, url: str) -> Optional[str]:
        """동기 래퍼 (asyncio.run 사용)"""
        return asyncio.run(self.process_url_async(url))


# ============================================================
# 🔥 Stage 0: 커뮤니티 바이럴 크롤러 v6.0
# ── 네이트판 · 인스티즈 · 에펨코리아 · 디시 실베 ──
# ── 모바일 웹 우회 + 메트릭(댓글/추천) 기반 필터링 ──
# ============================================================
class ViralSourceScraper:
    """v6.0: 한국 커뮤니티 핫글 기반 바이럴 소재 크롤러

    4대 소스: 네이트판(인간관계 썰) → 인스티즈(공감형) → 에펨코리아(시사+유머) → 디시 실베(자극적)
    전략: 모바일 URL → BeautifulSoup → 댓글수/추천수 메트릭 → 상위 N개만 반환
    """

    _MOBILE_UA = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    _DESKTOP_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    _MIN_COMMENTS = 30  # 댓글 이 이상인 글만 후보

    # ── [1순위] 네이트판: 인간관계 썰의 성지 ──

    @classmethod
    def fetch_natepann(cls) -> list[dict]:
        """네이트판 명예의전당 + 오늘의판 (모바일) — 제목 + 댓글수 + 조회수 + 추천수"""
        results = []
        urls = [
            "https://m.pann.nate.com/talk/ranking",  # 명예의 전당
            "https://m.pann.nate.com/talk/today",     # 오늘의 판
        ]
        try:
            from bs4 import BeautifulSoup
            for page_url in urls:
                try:
                    resp = requests.get(page_url, headers={"User-Agent": cls._MOBILE_UA}, timeout=10)
                    if resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")

                    for a_tag in soup.select("a"):
                        href = a_tag.get("href", "")
                        if "/talk/" not in href:
                            continue
                        talk_match = re.search(r'/talk/(\d{6,})', href)
                        if not talk_match:
                            continue

                        raw = a_tag.get_text(strip=True)
                        if not raw or len(raw) < 10 or len(raw) > 120:
                            continue

                        # 파싱: "1동남아련들 다 탈퇴시켜라 걍(124)조회70,846|추천373"
                        title_raw = re.sub(r'^\d{1,2}', '', raw)  # 앞 순번 제거

                        comments = 0
                        cm = re.search(r'\((\d{1,5})\)', title_raw)
                        if cm:
                            comments = int(cm.group(1))

                        views = 0
                        vm = re.search(r'조회([\d,]+)', title_raw)
                        if vm:
                            views = int(vm.group(1).replace(",", ""))

                        recommends = 0
                        rm = re.search(r'추천(\d+)', title_raw)
                        if rm:
                            recommends = int(rm.group(1))

                        # 제목 클리닝: 메트릭 부분 제거
                        title = title_raw
                        for pat in [r'\(\d{1,5}\)', r'조회[\d,]+', r'\|?추천\d+']:
                            title = re.sub(pat, '', title)
                        title = title.strip()

                        if not title or len(title) < 3:
                            continue

                        score = comments * 3 + views // 100 + recommends * 2

                        results.append({
                            "title": title,
                            "url": f"https://m.pann.nate.com/talk/{talk_match.group(1)}",
                            "source": "네이트판",
                            "score": score,
                            "comments": comments,
                            "views": views,
                            "recommends": recommends,
                            "content": "",
                        })
                except Exception:
                    continue

            # 중복 제거
            seen = set()
            deduped = []
            for r in results:
                key = r["title"][:20]
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
            results = deduped

            print(f"  [OK] 네이트판: {len(results)}개")
        except Exception as e:
            print(f"  [WARN] 네이트판 실패: {e}")
        return results

    # ── [2순위] 인스티즈: 일상 공감형 소재 ──

    @classmethod
    def fetch_instiz(cls) -> list[dict]:
        """인스티즈 인기글 — 제목 + 댓글수"""
        results = []
        try:
            resp = requests.get(
                "https://www.instiz.net/pt?page=1",
                headers={"User-Agent": cls._DESKTOP_UA},
                timeout=10,
            )
            if resp.status_code != 200:
                print(f"  [WARN] 인스티즈 HTTP {resp.status_code}")
                return results

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            for subj in soup.select(".listsubject"):
                a_tag = subj.select_one("a")
                if not a_tag:
                    continue

                href = a_tag.get("href", "")
                if not href.startswith("http"):
                    href = "https://www.instiz.net" + href

                # ★ 댓글수: span.cmt3 요소에서 정확하게 추출
                comments = 0
                cmt_span = subj.select_one("span.cmt3, span.cmt2, span.cmt1")
                if cmt_span:
                    try:
                        comments = int(cmt_span.get_text(strip=True))
                    except (ValueError, TypeError):
                        pass

                # ★ 제목: a태그 텍스트에서 댓글수(뒤에 붙은 숫자) 제거
                raw_text = a_tag.get_text(strip=True)
                if not raw_text or len(raw_text) < 5:
                    continue

                # 댓글수 숫자가 제목 끝에 붙어있으면 제거
                # ★ A-1 fix: cmt 스팬 텍스트 자체를 raw_text에서 제거 (숫자 잔재 방지)
                if cmt_span:
                    cmt_text = cmt_span.get_text(strip=True)
                    # a태그 내 cmt 스팬 텍스트를 제거한 뒤 제목 추출
                    title = raw_text.replace(cmt_text, '').strip()
                    # 혹시 끝에 남은 댓글수 숫자 한번 더 제거
                    if comments > 0:
                        title = re.sub(rf'\s*{comments}\s*$', '', title).strip()
                else:
                    # cmt 스팬 없는 경우: 끝 숫자가 댓글수일 수 있음
                    cm = re.search(r'(\d{2,5})$', raw_text)
                    if cm:
                        comments = int(cm.group(1))
                        title = raw_text[:cm.start()].strip()
                    else:
                        title = raw_text

                # ★ 인스티즈 잔재 정리: 시간(14:27), 'l조회', 'l', .jpg 등 제거
                title = re.sub(r'\d{1,2}:\d{2}[lL]?조회.*$', '', title).strip()
                title = re.sub(r'\d{1,2}:\d{2}[lL]?$', '', title).strip()
                title = re.sub(r'[lL]조회\s*\d*$', '', title).strip()
                title = re.sub(r'\.jpg\s*\d*$', '', title).strip()
                title = re.sub(r'\.png\s*\d*$', '', title).strip()

                if not title or len(title) < 3:
                    continue

                score = comments * 3

                results.append({
                    "title": title,
                    "url": href,
                    "source": "인스티즈",
                    "score": score,
                    "comments": comments,
                    "views": 0,
                    "content": "",
                })

            print(f"  [OK] 인스티즈: {len(results)}개")
        except Exception as e:
            print(f"  [WARN] 인스티즈 실패: {e}")
        return results

    # ── [3순위] 에펨코리아: 시사+유머 혼합 ──

    @classmethod
    def fetch_fmkorea(cls) -> list[dict]:
        """에펨코리아 베스트 (모바일) — 제목 + 댓글수"""
        results = []
        try:
            resp = requests.get(
                "https://m.fmkorea.com/best",
                headers={"User-Agent": cls._MOBILE_UA},
                timeout=10,
            )
            if resp.status_code != 200:
                print(f"  [WARN] 에펨코리아 HTTP {resp.status_code}")
                return results

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            for a_tag in soup.select("a"):
                txt = a_tag.get_text(strip=True)
                if not txt or len(txt) < 8 or len(txt) > 80:
                    continue

                # 댓글수: "[456]" 패턴
                comments = 0
                cm = re.search(r'\[(\d{1,5})\]$', txt)
                if cm:
                    comments = int(cm.group(1))
                    title = txt[:cm.start()].strip()
                else:
                    title = txt

                if not title or len(title) < 5:
                    continue

                # 에펨 특성: 너무 짧은 제목은 메뉴/광고
                if len(title) < 8:
                    continue

                href = a_tag.get("href", "")

                score = comments * 3

                results.append({
                    "title": title,
                    "url": href if href.startswith("http") else f"https://m.fmkorea.com{href}",
                    "source": "에펨코리아",
                    "score": score,
                    "comments": comments,
                    "views": 0,
                    "content": "",
                })

            # 중복 제거
            seen = set()
            deduped = []
            for r in results:
                key = r["title"][:20]
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
            results = deduped

            print(f"  [OK] 에펨코리아: {len(results)}개")
        except Exception as e:
            print(f"  [WARN] 에펨코리아 실패: {e}")
        return results

    # ── [4순위] 디시인사이드 실베: 자극적 이슈 ──

    @classmethod
    def fetch_dcinside(cls) -> list[dict]:
        """디시인사이드 실시간베스트 (모바일) — 제목 + 추천수 + 조회수"""
        results = []
        try:
            resp = requests.get(
                "https://m.dcinside.com/board/dcbest",
                headers={"User-Agent": cls._MOBILE_UA},
                timeout=10,
            )
            if resp.status_code != 200:
                print(f"  [WARN] 디시 실베 HTTP {resp.status_code}")
                return results

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            for a_tag in soup.select("a.lt"):
                raw = a_tag.get_text(strip=True)
                if not raw or len(raw) < 10:
                    continue

                href = a_tag.get("href", "")
                if "/board/dcbest/" not in href:
                    continue

                # ★ A-1 fix: 공지글/소개글 즉시 스킵
                if any(kw in raw for kw in ["갤러리 이용 안내", "이용안내", "공지", "소개"]):
                    continue

                # 디시 모바일: "이미지[갤]제목ㅇㅇHH:MM조회 NNNNN추천NNN숫자"
                # 제목 추출: [갤] 뒤부터 시간(HH:MM) 또는 ㅇㅇ 직전까지
                title = raw
                views = 0
                recommends = 0

                # 갤러리 태그 제거
                gal_match = re.search(r'(?:이미지)?\[.+?\]', title)
                if gal_match:
                    title = title[gal_match.end():]

                # 조회수/추천수 추출
                vm = re.search(r'조회\s*([\d,]+)', title)
                if vm:
                    views = int(vm.group(1).replace(",", ""))
                rm = re.search(r'추천\s*(\d+)', title)
                if rm:
                    recommends = int(rm.group(1))

                # ★ A-1 fix: 제목 정리 강화 — 닉네임/시간/조회수/추천수/숫자잔재 전부 제거
                for pattern in [
                    r'ㅇㅇ(?:\([\d.]+\))?\s*\d{1,2}:\d{2}',  # ㅇㅇ(123.456)14:20
                    r'[a-zA-Z가-힣]+\d{1,2}:\d{2}',           # 닉네임14:20
                    r'\d{1,2}:\d{2}',                          # 단독 시간
                    r'조회\s*[\d,]+',
                    r'추천\s*\d+',
                ]:
                    cut = re.search(pattern, title)
                    if cut:
                        title = title[:cut.start()]
                # 끝에 붙은 닉네임 잔재 제거 (ㅇㅇ, 숫자만 남은 경우)
                title = re.sub(r'ㅇㅇ$', '', title).strip()
                title = re.sub(r'\d{1,3}$', '', title).strip()
                # .jpg / .gif 확장자 잔재 제거
                title = re.sub(r'\.(jpg|gif|png|jpeg)$', '', title, flags=re.IGNORECASE).strip()

                if not title or len(title) < 5:
                    continue

                score = recommends * 2 + views // 200

                results.append({
                    "title": title,
                    "url": href if href.startswith("http") else f"https://m.dcinside.com{href}",
                    "source": "디시실베",
                    "score": score,
                    "comments": 0,
                    "views": views,
                    "recommends": recommends,
                    "content": "",
                })

            print(f"  [OK] 디시 실베: {len(results)}개")
        except Exception as e:
            print(f"  [WARN] 디시 실베 실패: {e}")
        return results

    # ── 통합 수집 + 메트릭 필터링 ──

    # ── A-2: 숏츠 바이럴 카테고리 부스트 (100만뷰+ 검증 기반) ──
    _CATEGORY_BOOSTS = {
        "공포_미스터리": (["공포", "귀신", "심령", "미스터리", "소름", "괴담", "도시전설", "폐건물", "호러"], 50),
        "충격사실": (["충격", "알고보니", "진실", "몰랐던", "비밀", "반전", "실화", "경악", "역대급"], 45),
        "문화충격": (["외국인", "문화충격", "반응", "리액션", "놀란", "해외", "일본", "미국"], 45),
        "밈_유머": (["밈", "짤", "ㅋㅋ", "웃긴", "개웃", "존웃", "킹받", "황당", "웃참", "빡침"], 40),
        "비교_랭킹": (["비교", "VS", "랭킹", "순위", "TOP", "1위", "최고", "최악", "차이"], 40),
        "2030_직장": (["월급", "퇴사", "야근", "직장상사", "꼰대", "사직서", "워라밸", "이직", "연봉", "신입", "인턴", "MZ"], 35),
        "2030_돈": (["월세", "전세", "자취", "재테크", "적금", "사회초년생", "청약", "대출"], 35),
        "꿀팁_정보": (["꿀팁", "방법", "노하우", "핵꿀", "가성비", "꿀조합", "비법", "절약", "추천", "리뷰", "정리", "모르면 손해", "생활", "살림", "청소", "요리"], 35),
        "일상_코미디": (["웃긴", "개웃", "존웃", "황당", "킹받", "공감", "일상", "출근", "월요일", "귀찮", "특징", "유형"], 35),
        "상식_궁금": (["왜", "이유", "비밀", "상식", "퀴즈", "궁금", "과학", "원리", "진짜 이유"], 35),
    }

    # ── A-2: 숏츠 부적합 감점 (일상 잡담 = 조회수 저조) ──
    _BORING_PENALTIES = [
        (r"설거지|시댁|파혼", -30, "가정사"),
        (r"다이어트|식단|헬스|운동루틴", -20, "다이어트"),
        (r"카페|맛집|디저트|빵집|브런치", -15, "카페"),
        (r"열애|결별|소속사|컴백|팬싸", -10, "연예가십"),
    ]

    @classmethod
    def _compute_viral_score(cls, item: dict) -> float:
        """A-2: 숏츠 바이럴 예측 점수 (커뮤니티 인기와 별개로 숏츠 적합도 평가)"""
        title = item.get("title", "")
        score = 0.0

        # 1) 참여도 기본점수
        cmt = item.get("comments", 0)
        rec = item.get("recommends", 0)
        views = item.get("views", 0)
        score += cmt * 3 + rec * 2 + views / 200

        # 2) 카테고리 부스트 (핵심!)
        for cat_name, (keywords, boost) in cls._CATEGORY_BOOSTS.items():
            if any(kw in title for kw in keywords):
                score += boost
                break

        # 3) 바이럴 키워드 부스트 (×5점으로 상향)
        BOOST_KW = [
            "레전드", "실화", "대박", "미쳤", "소름", "논란", "반전",
            "후기", "먹방", "게임", "리뷰", "밈", "챌린지",
            "터짐", "난리", "비교", "랭킹", "꿀팁",
            "해봄", "써봄", "사봄", "가봄",
            "썸", "소개팅", "결혼", "축의금", "연애", "고백",
        ]
        kw_count = sum(1 for kw in BOOST_KW if kw in title)
        score += kw_count * 5

        # 4) 숏츠 부적합 감점
        for pat, penalty, label in cls._BORING_PENALTIES:
            if re.search(pat, title):
                score += penalty
                break

        # 5) 낚시/스팸 감점
        CLICKBAIT = [r"단톡방", r"텔레그램", r"무료\s*나눔", r"선착순", r"후방주의", r"19금"]
        for pat in CLICKBAIT:
            if re.search(pat, title):
                score -= 50

        # 6) 제목 길이 보정
        if len(title) < 5:
            score -= 20
        elif len(title) >= 15:
            score += 5  # 제목이 길면 정보량 ↑

        return score

    @classmethod
    def _gemini_evaluate_topics(cls, items: list[dict]) -> list[dict]:
        """A-3: Gemini로 상위 후보들의 숏츠 바이럴 가능성 0~100점 평가
        1회 API 호출로 최대 15개 동시 평가 → 비용 $0
        70점 이상만 통과"""
        if not items:
            return items

        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            print("  ⚠️  GOOGLE_API_KEY 없음 → Gemini 평가 스킵")
            return items

        # 상위 15개만 평가 (토큰 절약)
        candidates = items[:15]
        titles_text = "\n".join(
            f"{i+1}. [{c['source']}] {c['title']}"
            for i, c in enumerate(candidates)
        )

        prompt = f"""너는 유튜브 숏츠 바이럴 전문가다.
아래 커뮤니티 핫글 제목들을 보고, 각각 "유튜브 숏츠로 만들면 조회수가 터질 가능성"을 0~100점으로 평가해.

평가 기준 (4가지 테마 모두 고려):
- 90~100: 100만뷰+ (충격사실, 공포, 밈, 문화충격, 궁극의 꿀팁, 일상 개공감 코미디)
- 70~89: 10만뷰+ (공감형 썰, 비교/랭킹, 꿀팁/정보, 일상 코미디, 상식/미스터리, 호기심 자극)
- 50~69: 평범 (일상, 가십, 잡담)
- 0~49: 숏츠 부적합 (정치, 공지, 스팸, 시즌아웃)

숏츠 테마별 높은 점수 기준:
1. gossip(썰): 분노·공감 폭발, 반전 사이다
2. life_hack(꿀팁): "나만 몰랐네?" 실용 팁, 저장하고 싶게
3. empathy(공감): "어? 이거 나인데?" MBTI/직장 공감, 위트
4. mystery(미스터리): "왜 그런지 궁금하지 않아?" 호기심 유발

대상:
{titles_text}

반드시 아래 JSON 형식으로만 답해:
{{"scores": [85, 72, 45, ...]}}

scores 배열의 길이는 반드시 {len(candidates)}개여야 한다. JSON만 출력."""

        try:
            model = genai_flash.GenerativeModel("gemini-2.0-flash")
            response = model.generate_content(
                prompt,
                generation_config=genai_flash.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=500,
                    response_mime_type="application/json",
                ),
            )
            if response.text:
                data = json.loads(response.text)
                scores = data.get("scores", [])
                if isinstance(scores, list) and len(scores) == len(candidates):
                    passed = []
                    rejected = []
                    for item, gemini_score in zip(candidates, scores):
                        s = int(gemini_score) if isinstance(gemini_score, (int, float)) else 50
                        item["_gemini_score"] = s
                        if s >= 70:
                            item["score"] += s  # 기존 점수에 Gemini 점수 합산
                            passed.append(item)
                        else:
                            rejected.append(item)

                    print(f"  🧠 Gemini 평가: {len(passed)}개 통과 / {len(rejected)}개 탈락")
                    for p in passed[:5]:
                        print(f"    ✅ [{p['_gemini_score']}점] {p['title'][:40]}")
                    for r in rejected[:3]:
                        print(f"    ❌ [{r['_gemini_score']}점] {r['title'][:40]}")

                    # 통과한 것 + 평가 안 된 나머지 (15위 이후)
                    rest = items[15:]
                    return passed + rest
                else:
                    print(f"  ⚠️  Gemini 응답 길이 불일치 ({len(scores)} vs {len(candidates)}) → 스킵")
        except Exception as e:
            print(f"  ⚠️  Gemini 주제 평가 실패: {e} → 기존 점수 사용")

        return items

    @classmethod
    def _deduplicate_with_history(cls, items: list[dict]) -> list[dict]:
        """A-4: 주제 중복 방지 — 최근 200개 제목과 유사도 비교"""
        history_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "data", "topic_history.json")
        past_titles = []
        try:
            if os.path.exists(history_path):
                with open(history_path, "r", encoding="utf-8") as f:
                    past_titles = json.load(f)
        except Exception:
            pass

        if not past_titles:
            return items

        # 간단 유사도: 제목 앞 20자 비교
        past_keys = set(t[:20] for t in past_titles)
        filtered = []
        skipped = 0
        for item in items:
            key = item["title"][:20]
            if key in past_keys:
                skipped += 1
                continue
            filtered.append(item)

        if skipped:
            print(f"  🔄 중복 제거: {skipped}개 스킵 (최근 히스토리와 겹침)")
        return filtered

    @classmethod
    def _save_topic_history(cls, items: list[dict]) -> None:
        """A-4: 선택된 주제를 히스토리에 저장 (최대 200개 유지)"""
        history_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "data", "topic_history.json")
        past_titles = []
        try:
            if os.path.exists(history_path):
                with open(history_path, "r", encoding="utf-8") as f:
                    past_titles = json.load(f)
        except Exception:
            pass

        new_titles = [item["title"] for item in items if item.get("title")]
        past_titles = new_titles + past_titles
        past_titles = past_titles[:200]  # 최근 200개만 유지

        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(past_titles, f, ensure_ascii=False, indent=2)

    @classmethod
    def collect_all(cls) -> list[dict]:
        """v7.0: 4개 커뮤니티 크롤링 → 바이럴 예측 점수 → Gemini 평가 → 상위 후보 반환"""
        print(f"\n{'='*60}")
        print(f"🔥 Stage 0: 커뮤니티 바이럴 크롤링 v7.0 (AI 주제 선별)")
        print(f"{'='*60}")

        all_items = []
        # 순서대로 크롤링 (각 소스 실패해도 다음으로)
        all_items.extend(cls.fetch_natepann())
        all_items.extend(cls.fetch_instiz())
        all_items.extend(cls.fetch_fmkorea())
        all_items.extend(cls.fetch_dcinside())

        if not all_items:
            print("  ⚠️  모든 커뮤니티 크롤링 실패 — Google Trends 폴백")
            all_items.extend(cls._fallback_google_trends())

        # ★ A-2: 숏츠 바이럴 예측 점수로 정렬 (기존 단순 메트릭 대체)
        for item in all_items:
            item["score"] = cls._compute_viral_score(item)
        all_items.sort(key=lambda x: x.get("score", 0), reverse=True)

        # ★ A-4: 주제 중복 방지 (히스토리 기반)
        all_items = cls._deduplicate_with_history(all_items)

        # ★ A-3: Gemini 사전 평가 게이트 (상위 15개 → 70점+ 만 통과)
        all_items = cls._gemini_evaluate_topics(all_items)

        # 최종 정렬 (Gemini 점수 합산된 상태)
        all_items.sort(key=lambda x: x.get("score", 0), reverse=True)

        print(f"\n  📊 총 {len(all_items)}개 바이럴 소재 최종 선별 완료")
        for i, item in enumerate(all_items[:8]):
            src = item["source"]
            cmt = item.get("comments", 0)
            rec = item.get("recommends", 0)
            views = item.get("views", 0)
            gs = item.get("_gemini_score", "?")
            metric = f"💬{cmt}" if cmt else f"👍{rec}"
            if views:
                metric += f" 👀{views:,}"
            print(f"  #{i+1} [{src}] {item['title'][:40]} ({metric}, 점수:{item.get('score',0):.0f}, AI:{gs})")

        # ★ A-4: 선택된 주제를 히스토리에 저장
        cls._save_topic_history(all_items[:10])

        return all_items

    @staticmethod
    def _fallback_google_trends() -> list[dict]:
        """폴백: 커뮤니티 전멸 시 Google Trends KR RSS"""
        results = []
        try:
            import xml.etree.ElementTree as ET
            resp = requests.get(
                "https://trends.google.co.kr/trending/rss?geo=KR",
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                ns = {"ht": "https://trends.google.co.kr/trending/rss"}
                for item in root.findall(".//item")[:15]:
                    title_el = item.find("title")
                    title = title_el.text if title_el is not None else ""
                    if title:
                        results.append({
                            "title": title,
                            "url": "",
                            "source": "구글트렌드",
                            "score": 50,
                            "comments": 0,
                            "views": 0,
                            "content": "",
                        })
                print(f"  [OK] Google Trends KR 폴백: {len(results)}개")
        except Exception as e:
            print(f"  [WARN] Google Trends 폴백도 실패: {e}")
        return results


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
        # DC 갤러리 운영
        "갤러리 이용 안내", "갤러리 이용안내", "이용 안내",
        "갤러리 소개", "갤러리를 소개", "갤러리 개설",
        "마이너 갤러리", "마이너갤러리",
        "CONNECTING HEARTS", "디시인사이드입니다",
        # 공통 공지/안내
        "[공지]", "[필독]", "[안내]", "[운영]", "[규칙]",
        "[Notice]", "[notice]", "[이벤트]", "[모집]",
        "운영자입니다", "공지사항입니다", "이용규칙",
        # 광고/스팸
        "텔레그램", "단톡방", "카톡방", "오픈채팅",
        "무료 나눔", "선착순", "할인코드", "쿠폰코드",
        "비트코인", "가상화폐", "코인 추천", "NFT",
        "수익률", "투자 추천", "원금보장",
        # 성인/부적절
        "후방주의", "19금", "야짤", "은꼴",
        # 커뮤니티 관리
        "구인구직", "팝니다", "삽니다", "급구",
        "체험단", "협찬", "제휴 문의",
        # 시즌/명절 이슈 (지난 이슈 배제)
        "설날", "새해", "추석", "한가위", "크리스마스", "성탄절",
        "발렌타인", "화이트데이", "어버이날", "스승의날",
        "졸업식", "입학식", "수능", "수능날",
    ]
    # UI/스팸 키워드 (2개 이상 포함 → 차단)
    UI_KEYWORDS = [
        "갤러리 만들기", "회원가입", "로그인", "광고 문의",
        "이 갤러리를 , , ,", "갤러리 규정", "공지사항",
        "운영 방침", "매니저 신청", "부매니저",
        "한줄평", "평가해주세요", "설문조사",
    ]

    # 콘텐츠 위험 키워드 (의료/법률/금융 허위정보 방지)
    RISKY_CONTENT_KEYWORDS = [
        # 의료 — 허위정보 위험
        "암 치료", "특효약", "민간요법", "자가진단",
        "병원에서 안 알려주는", "의사가 숨기는",
        # 법률 — 소송 위험
        "고소", "소송", "합의금", "형사사건",
        # 금융 — 투자 권유 위험
        "대출", "사기", "피해사례",
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
        "ㅈㄹ", "존웃", "킹받", "개빡", "갓",
        "인생", "찐", "개꿀", "핵꿀", "꿀잼",
        # 2030 타겟 부스트
        "월급", "퇴사", "야근", "자취", "월세", "전세",
        "사회초년생", "직장상사", "꼰대", "MZ", "워라밸",
        "연봉", "이직", "알바", "면접", "취준",
        "썸", "소개팅", "결혼", "축의금", "청첩장",
    ]

    # 2차 블랙리스트: 바이럴 키워드가 있어도 걸러야 할 낚시 패턴
    CLICKBAIT_PENALTY_PATTERNS = [
        r"단톡방", r"텔레그램", r"카톡방",   # 스팸 유입
        r"무료\s*나눔", r"선착순",           # 광고성
        r"급구", r"구합니다", r"팝니다",      # 중고거래
        r"후방주의", r"19금", r"야짤",        # 성인 콘텐츠
    ]

    # ── 숏츠 폭발력 카테고리 (100만뷰+ 검증 기반) ──
    VIRAL_CATEGORY_BOOSTS = {
        "공포": (["공포", "귀신", "심령", "미스터리", "소름", "괴담", "도시전설", "폐건물"], 80.0),
        "충격사실": (["충격", "알고보니", "진실", "몰랐던", "비밀", "반전", "실화", "경악"], 70.0),
        "밈유머": (["밈", "짤", "ㅋㅋ", "웃긴", "개웃", "존웃", "킹받", "황당", "웃참"], 60.0),
        "비교랭킹": (["비교", "VS", "랭킹", "순위", "TOP", "1위", "최고", "최악"], 60.0),
        "문화충격": (["외국인", "문화충격", "반응", "리액션", "놀란", "해외"], 70.0),
        "꿀팁": (["꿀팁", "방법", "노하우", "핵꿀", "가성비"], 50.0),
        "2030직장썰": (["월급", "퇴사", "야근", "직장상사", "꼰대", "사직서", "워라밸",
                        "이직", "연봉", "신입", "인턴", "MZ"], 65.0),
        "2030돈썰": (["월세", "전세", "자취", "재테크", "적금", "사회초년생", "청약"], 60.0),
        "2030인간관계": (["썸", "소개팅", "결혼", "축의금", "인맥", "손절", "뒷담화"], 55.0),
    }

    # ── 숏츠 부적합 감점 (일상 잡담류 = 조회수 저조) ──
    # ※ 2030 타겟 전략: 직장/연애 썰은 핵심 콘텐츠이므로 감점 제거
    BORING_CONTENT_PENALTIES = [
        (r"설거지|시댁|시어머니|파혼", -50.0, "결혼 가정사"),
        (r"다이어트|식단|헬스|운동루틴", -20.0, "다이어트"),
        (r"카페|맛집|디저트|빵집|브런치", -20.0, "카페/맛집"),
        (r"열애|결별|소속사|컴백|팬싸", -15.0, "연예 가십"),
    ]

    def _extract_article_urls_requests(self, list_url: str) -> list[str]:
        """requests로 목록 페이지 HTML에서 개별 글 URL+제목+참여도 추출 (복합 점수 정렬)"""
        try:
            import requests as _req
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/133.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                "Referer": "https://gall.dcinside.com/",
            }
            r = _req.get(list_url, headers=headers, timeout=15)
            r.encoding = "utf-8"
            html = r.text

            # ── URL + 제목 + 참여도(추천/조회/댓글) 함께 추출 ──
            # (url, title, recommend, view_count, comment_count) 튜플
            url_title_pairs = []

            # ── DC인사이드: 행(row) 단위로 추천수/조회수/댓글수 추출 ──
            dc_engagement = {}  # url → {rec, view, comment}
            # tr.ub-content 각 행에서 추천수(gall_recommend), 조회수, 댓글수 추출
            dc_rows_html = re.findall(
                r'<tr\s+class="ub-content[^"]*"[^>]*>(.*?)</tr>',
                html, re.DOTALL
            )
            for row_html in dc_rows_html:
                # URL
                url_m = re.search(
                    r'href="(/board/view/\?id=\w+&no=\d+[^"]*)"', row_html
                )
                if not url_m:
                    continue
                row_url = "https://gall.dcinside.com" + url_m.group(1).replace("&amp;", "&")

                # 추천수 (gall_recommend)
                rec_m = re.search(r'<td[^>]*class="gall_recommend"[^>]*>\s*(\d+)\s*</td>', row_html)
                rec = int(rec_m.group(1)) if rec_m else 0

                # 조회수 (gall_count)
                view_m = re.search(r'<td[^>]*class="gall_count"[^>]*>\s*(\d+)\s*</td>', row_html)
                view = int(view_m.group(1)) if view_m else 0

                # 댓글수 (reply_numbox 안의 숫자)
                cmt_m = re.search(r'reply_numbox.*?>\[(\d+)\]', row_html)
                cmt = int(cmt_m.group(1)) if cmt_m else 0

                dc_engagement[row_url] = {"rec": rec, "view": view, "comment": cmt}

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

            # ── 복합 바이럴 점수 정렬 (참여도 + 키워드 + 낚시 감점) ──
            def _viral_score(pair):
                u, t = pair
                score = 0.0

                # 1) 참여도 점수 (댓글 최우선! 댓글 많음 = 찬반 논란 = 댓글창 폭발)
                eng = dc_engagement.get(u, {})
                rec = eng.get("rec", 0)
                view = eng.get("view", 0)
                cmt = eng.get("comment", 0)
                score += rec * 2.0 + cmt * 5.0 + view * 0.01
                # ★ 댓글 100개 이상 = 알고리즘 폭발 보장 소재 (슈퍼 부스트)
                if cmt >= 100:
                    score += 200.0
                elif cmt >= 50:
                    score += 80.0
                elif cmt >= 20:
                    score += 30.0

                # 2) 바이럴 키워드 가산점 (각 키워드 +3)
                kw_count = sum(1 for kw in self.VIRAL_BOOST_KEYWORDS if kw in t)
                score += kw_count * 3.0

                # 3) 낚시/스팸 패턴 감점 (-50 per match)
                for pat in self.CLICKBAIT_PENALTY_PATTERNS:
                    if re.search(pat, t):
                        score -= 50.0

                # 4) 숏츠 폭발력 카테고리 부스트 (핵심!)
                for cat_name, (cat_kws, cat_boost) in self.VIRAL_CATEGORY_BOOSTS.items():
                    if any(ck in t for ck in cat_kws):
                        score += cat_boost
                        break  # 최고 카테고리 1개만 적용

                # 5) 숏츠 부적합 콘텐츠 감점 (일상 잡담)
                for pat, penalty, label in self.BORING_CONTENT_PENALTIES:
                    if re.search(pat, t):
                        score += penalty  # 음수
                        break

                # 6) 제목 길이 보정 (너무 짧은 제목 = 저품질)
                if len(t) < 5:
                    score -= 10.0

                return score

            filtered.sort(key=_viral_score, reverse=True)

            # 제목 정보를 인스턴스에 저장 (후속 단계에서 활용)
            self._url_titles = {u: t for u, t in filtered if t}

            result_urls = [u for u, _ in filtered]
            if result_urls:
                top = filtered[0]
                top_title = top[1] if top[1] else "(제목 미확인)"
                top_eng = dc_engagement.get(top[0], {})
                top_score = _viral_score(top)
                print(f"  ✅ requests로 {len(result_urls)}개 URL 추출 (공지 제외)")
                print(f"     🔥 1순위: {top_title[:50]}")
                print(f"     📊 점수: {top_score:.1f} (추천 {top_eng.get('rec', 0)} / 조회 {top_eng.get('view', 0)} / 댓글 {top_eng.get('comment', 0)})")
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
                            print(f"     🚫 소개/공지글 차단: {blk[0] if blk else 'unknown'}")
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
                                print(f"     🚫 소개/공지글 차단: {blk[0] if blk else 'unknown'}")
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
        except Exception as e:
            print(f"  ⚠️  스크린샷 다운로드 실패: {e}")
        return None

    def _fetch_dc_article_requests(self, url: str) -> Optional[dict]:
        """requests로 디시 개별 글 본문+댓글 직접 추출 (Apify 불필요, 빠름)"""
        try:
            import requests as _req
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/133.0.0.0 Safari/537.36"
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
            "Chrome/133.0.0.0 Safari/537.36"
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
# 📝 Stage 2: 대본 생성 (Gemini 2.0 Flash)
# ============================================================
class ScriptGenerator:
    """v7.0: Gemini (gemini-2.0-flash) 기반 — 100만뷰 숏츠 대본 생성기

    3분할 프롬프트 아키텍처:
      ROLE_PROMPT  → 핵심 역할 (1인칭 썰 작가)
      FORMAT_SPEC  → JSON 스키마 + 예시
      CONTENT_RULES → 금지사항 + 2030 키워드 + 감정 곡선
    """

    # v6.1 → v6.2: Claude → Gemini 롤백 (크레딧 부족 이슈)
    GEMINI_MODEL = "gemini-2.0-flash"

    # ── [0/3] DIRECTOR_PERSONA: 모든 테마 공통 상위 페르소나 ──
    DIRECTOR_PERSONA = """당신은 전 세계 숏츠 트렌드를 실시간으로 분석하는 '바이럴 콘텐츠 디렉터'입니다.
단순히 대본을 쓰는 것이 아니라, 시청자가 화면을 멈추고 끝까지 보게 만드는 '후킹의 기술'과 '시각적 충격'을 설계합니다.

[3단계 분석 프로세스]
Step 1. 트렌드 분석: 이 주제가 왜 숏츠에서 터질 수 있는지(공감/분노/호기심/유익함) 이유를 한 줄로 정의.
Step 2. 숏츠 4-Scene Formula:
  - 0~3초 (도파민 후킹): 시청자의 상식을 파괴하거나 강한 공감을 유발하는 첫 문장.
  - 4~15초 (빌드업): "왜?"라는 의문이 해소되기 직전까지 텐션 유지.
  - 16~50초 (임팩트 팩트): 핵심 정보나 반전을 임팩트 있게 전달.
  - 51~60초 (댓글 유도): 정답을 맞히거나 의견이 갈리게 만들어 댓글창을 터뜨리는 전략.
Step 3. AI 시각화: 모든 image_prompt는 영어로, 아래 키워드를 조합해 '요즘 감성' 유지.
  기본 키워드: Cinematic, 8k, Trendy Aesthetic, Moody Lighting, High Contrast

[Pace 규칙] 1초당 3.5음절. 한 문장 20자 이내. 불필요한 미사여구 삭제.

주의: Step 1의 트렌드 분석 결과는 JSON에 포함하지 마. 대본 JSON만 출력."""

    # v6.2: Gemini 롤백 — DIRECTOR_PERSONA를 시스템 프롬프트로 사용
    SYSTEM_PROMPT = DIRECTOR_PERSONA

    # ── [1/3] ROLE_PROMPT: 핵심 역할 + 말투 ──
    ROLE_PROMPT = """너는 자극적인 커뮤니티 이슈를 전달하는 스토리텔러야.
찐친한테 카톡으로 분노 토하듯 말하는 스타일.

[핵심 규칙 3개]
1. 첫 문장 = 12자 이내 강렬한 감탄/질문 ("아 진짜 미쳤음" "이게 사람이냐")
2. 감정 롤러코스터 필수: shocked→sad→tension→angry→funny→neutral (6종+ 사용, 같은 감정 2연속까지만)
3. highlight는 최대 2개만 true. 진짜 핵심 반전/펀치라인만.

[말투]
- 어미: ~임, ~음, ~거든, ~잖아, ~인데 (반말 통일)
- 추임새: 아니, 진짜, ㅋㅋㅋ, ㄹㅇ, 아 근데, 헐
- 금지어: 흥미롭, 놀라운, 충격적, 알아보겠, 살펴보겠, 결론적으로, 하겠습니다
- text 한국어만 15자 이내. image_prompt 영어만.

[image_prompt — 절대 규칙]
- 주제와 100% 연관된 장면만 묘사 (무관한 이미지 금지)
- "Same character as scene 1" 절대 금지! 매 장면 독립적 묘사.
- 매 장면 카메라 앵글 달라야 함: extreme close-up / bird's eye / low angle / wide shot / over-the-shoulder / dutch angle / tracking shot
- 기본: Cinematic, 8k, High Contrast, Korean webtoon style, bold outlines
- 첫 장면: "Young Korean [성별], [머리], [체형], [옷], [표정], extreme close-up, cinematic lighting, 8k, Korean webtoon style"
- 이후 장면: 캐릭터 외모를 매번 직접 묘사 (키, 머리, 옷 반복 OK)
- 표정: jaw dropped / face burning red / veins popping / tears streaming
- 조명: cinematic lighting, high contrast, dramatic red backlight / single spotlight"""

    # ── [2/3] FORMAT_SPEC: JSON 스키마 (간결하게) ──
    FORMAT_SPEC = """{
  "title": "어그로 제목 15자 이내",
  "mood": "funny|angry|sad|touching|scary|satisfying|shocking",
  "tags": ["#태그1", ... "#태그15"],
  "thumbnail_text": "썸네일 5자 이내",
  "description": "영상 설명 50자 이내",
  "script": [
    {
      "scene_number": 1,
      "text": "한국어 대사 15자 이내",
      "emotion": "shocked",
      "highlight": true,
      "pause_ms": 800,
      "important_words": ["핵심단어"],
      "direction": "BGM+연출 지시 (한국어)",
      "image_prompt": "영어 장면 묘사 (English only, 주제 연관 필수, Same character 금지, 카메라 앵글 매번 다르게)",
      "sfx": "gasp",
      "sfx_volume": 0.4
    }
  ]
}
emotion 허용값: neutral, tension, surprise, angry, sad, funny, shocked, excited, warm, serious, whisper, relief
sfx 허용값: laugh, rimshot, boing, punch, glass_break, thunder, dramatic_stinger, whoosh, ding, swoosh, gasp, crowd_ooh, record_scratch, kakao_alert, typing, ddiyong (없으면 "")
highlight: 최대 2개만 true. 나머지는 false."""

    # ── [3/3] CONTENT_RULES: 구조 + 금지사항 (핵심만) ──
    CONTENT_RULES = """[Pace] 1초당 3.5음절. 한 문장 15자 이내 엄수. 미사여구 삭제.

[대본 구조 — 12~15개 장면 (60초 목표)]
Act1 훅 (1~2문장): shocked/excited. 첫문장 12자↓. sfx: gasp or glass_break. pause_ms: 0.
Act2 빌드업 (3~5문장): sad→tension. 공감 디테일. direction에 "불협화음 BGM" 명시.
Act3 피크 (2~3문장): angry. 감정 폭발. sfx: punch. pause_ms: 800~1200 (음소거 효과). highlight: true.
Act4 반전 (2~3문장): funny/relief. 카타르시스. sfx: dramatic_stinger or rimshot.
Act5 CTA (1문장): neutral. 댓글 유도 질문. pause_ms: 0.

[필수 체크]
- 같은 감정 최대 2연속. 6종류+ 감정 사용.
- highlight: 최대 2개만 (Act3 피크 + Act4 반전에만)
- important_words: 매 문장 1~2개. 금액/인물/핵심명사.
- direction: 매 장면 BGM 상태 명시 ("브금 유지" "브금 멈춤" "비장한 음악 IN")
- sfx: 전체 3~5개만 (매 장면 넣지 마. 피크에만.)
- CTA 마지막 문장 = 매번 다른 형식 (질문/도발/고백/제안 등 다양하게)

[금지]
- 원문에 없는 수치/대화 창작
- 실명, 보도체, 좋아요/구독 유도
- 시즌 지난 소재 (설날/추석/크리스마스)
- highlight 전부 true (반드시 대부분 false)"""

    # ── few-shot 예시 (실제 JSON으로 — Gemini가 정확히 따라하도록) ──
    FEW_SHOT_EXAMPLES = """[예시 — 이 JSON 형식을 정확히 따라해]
{"title":"기획안 도둑 상사","mood":"satisfying","tags":["#직장썰","#참교육","#상사","#사이다","#분노","#공감","#숏츠","#레전드","#회사","#직장인","#웃긴짤","#반전","#일상","#실화","#개빡침"],"thumbnail_text":"내 기획안?","description":"3주 야근한 기획안 훔쳐간 상사 결말 ㅋㅋ","script":[
{"scene_number":1,"text":"아 진짜 미쳤음","emotion":"shocked","highlight":false,"pause_ms":0,"important_words":["미쳤"],"direction":"경쾌한 브금 갑자기 멈춤","image_prompt":"Young Korean male, short brown hair, thin build, worn gray hoodie, jaw dropped with extreme shock, close-up shot, cold fluorescent office light, Korean webtoon style, bold outlines","sfx":"glass_break","sfx_volume":0.4},
{"scene_number":2,"text":"3주를 야근했거든","emotion":"sad","highlight":false,"pause_ms":300,"important_words":["3주","야근"],"direction":"불협화음 BGM 시작","image_prompt":"Same character as scene 1, hunched over desk surrounded by papers, dark circles under eyes, dimly lit office at night, Korean webtoon style","sfx":"","sfx_volume":0.3},
{"scene_number":3,"text":"기획안 진짜 피땀임","emotion":"sad","highlight":false,"pause_ms":200,"important_words":["피땀"],"direction":"불협화음 유지","image_prompt":"Same character as scene 1, exhausted face illuminated by laptop screen, energy drink cans around, Korean webtoon style","sfx":"","sfx_volume":0.3},
{"scene_number":4,"text":"근데 회의 때","emotion":"tension","highlight":false,"pause_ms":400,"important_words":["회의"],"direction":"브금 긴장감 상승","image_prompt":"Same character as scene 1, sitting nervously in meeting room, wide shot showing conference table, tense atmosphere, Korean webtoon style","sfx":"","sfx_volume":0.3},
{"scene_number":5,"text":"팀장이 내 기획안 발표함","emotion":"tension","highlight":false,"pause_ms":300,"important_words":["팀장","기획안"],"direction":"브금 멈춤 직전","image_prompt":"Same character as scene 1, eyes widening in disbelief, low angle looking at team leader presenting, dramatic shadows, Korean webtoon style","sfx":"","sfx_volume":0.3},
{"scene_number":6,"text":"제가 준비했습니다?","emotion":"angry","highlight":true,"pause_ms":1000,"important_words":["제가","준비"],"direction":"BGM 완전 멈춤 + 묵음 (음소거 효과)","image_prompt":"Same character as scene 1, extreme close-up on eyes, burning red face, veins on forehead, dark ominous background with red glow, Korean webtoon style","sfx":"punch","sfx_volume":0.6},
{"scene_number":7,"text":"피가 거꾸로 솟음 ㄹㅇ","emotion":"angry","highlight":false,"pause_ms":400,"important_words":["피"],"direction":"긴장 브금 IN","image_prompt":"Same character as scene 1, fists clenched on table, knuckles white, trembling with rage, Korean webtoon style","sfx":"","sfx_volume":0.3},
{"scene_number":8,"text":"근데 대표가 물어봄","emotion":"tension","highlight":false,"pause_ms":800,"important_words":["대표"],"direction":"브금 서스펜스","image_prompt":"Same character as scene 1, frozen in place, CEO pointing at screen questioning, wide shot meeting room, Korean webtoon style","sfx":"","sfx_volume":0.3},
{"scene_number":9,"text":"원본 파일 누구 거임?","emotion":"shocked","highlight":true,"pause_ms":400,"important_words":["원본"],"direction":"브금 멈춤","image_prompt":"Same character as scene 1, eyes wide open, mouth slightly open, dramatic close-up, single spotlight effect, Korean webtoon style","sfx":"dramatic_stinger","sfx_volume":0.5},
{"scene_number":10,"text":"내 이름 박혀있음 ㅋㅋ","emotion":"funny","highlight":true,"pause_ms":300,"important_words":["이름"],"direction":"통쾌한 비장 음악 IN","image_prompt":"Same character as scene 1, smirking with pure satisfaction, triumphant expression, bright warm light flooding in, Korean webtoon style","sfx":"rimshot","sfx_volume":0.4},
{"scene_number":11,"text":"팀장 얼굴 봤어야 함","emotion":"funny","highlight":false,"pause_ms":200,"important_words":["얼굴"],"direction":"비장 음악 유지","image_prompt":"Same character as scene 1, laughing with hand covering mouth, team leader blurred in background looking pale, Korean webtoon style","sfx":"","sfx_volume":0.3},
{"scene_number":12,"text":"이런 상사 어떻게 해야 됨?","emotion":"neutral","highlight":false,"pause_ms":0,"important_words":["상사"],"direction":"브금 페이드아웃","image_prompt":"Same character as scene 1, looking directly at viewer with curious expression, casual pose, soft lighting, Korean webtoon style","sfx":"","sfx_volume":0.3}
]}
주목: highlight는 12개 중 3개만 true. 감정 6종(shocked,sad,tension,angry,funny,neutral). sfx 4개만. 첫문장 7자."""

    # ── 대본 검증용 상수 ──
    _VALID_EMOTIONS = {
        "neutral", "tension", "surprise", "angry", "sad", "funny",
        "shocked", "excited", "warm", "serious", "whisper", "relief",
    }
    _AI_SLOP_WORDS = [
        "흥미롭", "놀라운", "충격적인", "알아보겠", "살펴보겠", "결론적으로",
        "하겠습니다", "마무리하", "요약하자면", "정리하면", "주목할 만한",
        "궁금하지 않으신가요", "함께 알아볼까요", "지금부터",
    ]

    # ── 테마별 프롬프트 프리셋 (info / comedy / mystery) ──
    # gossip 프리셋은 __init__에서 기존 클래스 상수로 동적 조립
    _LIFE_HACK_ROLE = """너는 살림과 업무 효율을 200% 높여주는 꿀팁 전문가야.
"나만 손해 보고 있었네?" 심리를 자극하는 실용 팁 영상 전문.

[핵심 규칙 3개]
1. 첫 문장 = 15자 이내 충격 질문/사실 ("아직도 세제로만 닦으세요?" "이거 모르면 매달 3만원 손해")
2. 감정 흐름: excited→neutral→warm (정보전달은 차분, 핵심은 강조)
3. highlight는 각 팁 제목(핵심 요약)에만 true. 전체의 30% 이하.

[말투]
- 어미: ~하세요, ~거든요, ~인데요 (존대지만 친근한 톤)
- 추임새: 근데요, 진짜, 이거, 아 그리고
- 금지어: 흥미롭, 놀라운, 충격적, 알아보겠, 살펴보겠, 결론적으로, 하겠습니다
- text 한국어만. image_prompt 영어만.

[image_prompt — 영어 필수]
- 기본 키워드: Cinematic close-up, 8k resolution, clean bright lighting, minimalist, trendy aesthetic
- 팁 장면: "High-quality cinematic close-up of [object], 8k resolution, clean lighting"
- before/after 비교, 인포그래픽 느낌
- 첫 장면: 주인공 외형 상세 + "8k, clean bright lighting, minimalist interior"
- 2장면+: "Same character as scene 1, ..." 필수"""

    _LIFE_HACK_FORMAT = """{
  "title": "꿀팁 제목 15자 이내 (의문형 권장)",
  "mood": "funny|satisfying|shocking",
  "tags": ["#태그1", ... "#태그15"],
  "thumbnail_text": "썸네일 5자 이내",
  "description": "영상 설명 50자 이내",
  "script": [
    {
      "scene_number": 1,
      "text": "한국어 대사 20자 이내",
      "emotion": "excited",
      "highlight": true,
      "pause_ms": 0,
      "important_words": ["핵심단어"],
      "direction": "BGM+연출 지시 (한국어)",
      "image_prompt": "영어 장면 묘사 (English only)",
      "sfx": "",
      "sfx_volume": 0.3
    }
  ]
}
emotion 허용값: neutral, excited, warm, surprise, funny, shocked, serious, relief
sfx 허용값: ding, whoosh, swoosh, typing, dramatic_stinger (없으면 "")
highlight: 각 팁 제목에만 true. 전체의 30% 이하."""

    _LIFE_HACK_RULES = """[Pace] 1초당 3.5음절. 한 문장 20자 이내 엄수. 미사여구 삭제.

[대본 구조 — 10~14문장]
Hook (1~2문장): excited/surprise. 충격 질문으로 시작. sfx: ding. pause_ms: 0.
팁1 (2~3문장): neutral→excited. 팁 제목(highlight:true) + 설명. direction에 "경쾌한 BGM" 명시.
팁2 (2~3문장): neutral→warm. 두번째 팁. sfx 없음.
팁3 (2~3문장): excited→surprise. 가장 놀라운 팁. sfx: dramatic_stinger.
CTA (1문장): warm. "저장하고 친구한테 공유하세요!" 류. pause_ms: 0.

[필수 체크]
- 감정 종류 최소 3종 (excited, neutral, warm 기본 + alpha)
- highlight: 전체의 30% 이하 (팁 제목에만)
- important_words: 매 문장 1~2개. 수치/핵심명사.
- direction: 매 장면 BGM 상태 명시
- sfx: 전체 2~3개만
- CTA = 공유/저장 유도 (구독/좋아요 금지)

[금지]
- 근거 없는 수치 창작, 의학/법률 조언
- 좋아요/구독 유도, highlight 전부 true"""

    _LIFE_HACK_FEWSHOT = """[예시 — 이 JSON 형식을 정확히 따라해]
{"title":"세제 없이 반짝","mood":"satisfying","tags":["#꿀팁","#청소","#생활팁","#살림","#자취","#라이프핵","#숏츠","#정보","#세탁","#주방","#욕실","#가성비","#꿀조합","#살림꿀팁","#자취생"],"thumbnail_text":"세제 대신?","description":"세제 없이도 반짝! 집에 있는 재료로 청소 끝","script":[
{"scene_number":1,"text":"아직도 세제로만 닦으세요?","emotion":"excited","highlight":false,"pause_ms":0,"important_words":["세제"],"direction":"경쾌한 브금 시작","image_prompt":"Young Korean woman, short bob hair, apron, holding cleaning spray, surprised expression, cinematic close-up, 8k resolution, clean bright lighting, minimalist kitchen","sfx":"ding","sfx_volume":0.4},
{"scene_number":2,"text":"식초 한 스푼이면 끝이에요","emotion":"neutral","highlight":true,"pause_ms":200,"important_words":["식초","한 스푼"],"direction":"브금 유지","image_prompt":"Same character as scene 1, pouring vinegar into spray bottle, cinematic close-up of hands, 8k, clean bright lighting","sfx":"","sfx_volume":0.3},
{"scene_number":3,"text":"기름때가 녹아요 진짜","emotion":"warm","highlight":false,"pause_ms":200,"important_words":["기름때"],"direction":"브금 유지","image_prompt":"High-quality cinematic close-up of greasy stovetop before and after, 8k resolution, clean lighting, trendy aesthetic","sfx":"","sfx_volume":0.3},
{"scene_number":4,"text":"두번째 베이킹소다","emotion":"excited","highlight":true,"pause_ms":200,"important_words":["베이킹소다"],"direction":"브금 밝게 전환","image_prompt":"Same character as scene 1, sprinkling baking soda on tiles, cinematic close-up, 8k, clean bright lighting","sfx":"","sfx_volume":0.3},
{"scene_number":5,"text":"욕실 곰팡이에 뿌리면","emotion":"neutral","highlight":false,"pause_ms":200,"important_words":["곰팡이"],"direction":"브금 유지","image_prompt":"Same character as scene 1, spraying bathroom grout, cinematic close-up, 8k, clean lighting","sfx":"","sfx_volume":0.3},
{"scene_number":6,"text":"30분 뒤에 싹 사라져요","emotion":"surprise","highlight":false,"pause_ms":300,"important_words":["30분"],"direction":"브금 유지","image_prompt":"High-quality cinematic close-up of sparkling clean bathroom result, 8k resolution, bright lighting, trendy aesthetic","sfx":"","sfx_volume":0.3},
{"scene_number":7,"text":"세번째가 진짜 대박인데요","emotion":"excited","highlight":false,"pause_ms":400,"important_words":["대박"],"direction":"브금 서스펜스 전환","image_prompt":"Same character as scene 1, excited expression holding mysterious bottle, cinematic, 8k, clean lighting","sfx":"dramatic_stinger","sfx_volume":0.5},
{"scene_number":8,"text":"콜라로 변기 청소돼요","emotion":"surprise","highlight":true,"pause_ms":300,"important_words":["콜라","변기"],"direction":"브금 반전","image_prompt":"High-quality cinematic close-up of cola being poured into toilet, bubbling reaction, 8k resolution, clean lighting","sfx":"","sfx_volume":0.3},
{"scene_number":9,"text":"저장하고 나중에 써보세요","emotion":"warm","highlight":false,"pause_ms":0,"important_words":["저장"],"direction":"브금 페이드아웃","image_prompt":"Same character as scene 1, smiling at viewer giving thumbs up, 8k, clean bright lighting, trendy aesthetic","sfx":"","sfx_volume":0.3}
]}
주목: highlight 9개 중 3개. 감정 4종(excited,neutral,warm,surprise). sfx 2개. 존대체."""

    _EMPATHY_ROLE = """너는 현대인의 마음을 꿰뚫어 보는 위트 있는 관찰자야.
누구나 겪는 귀찮은 상황을 유머로 터뜨리는 스타일. "어? 이거 나인데?" 반응 유도.

[핵심 규칙 3개]
1. 첫 문장 = 15자 이내 공감 상황 ("월요일 아침 알람 5개째" "엄마한테 전화 옴")
2. 감정: funny 중심 + surprise 반전. ㅋㅋㅋ 자유롭게.
3. highlight는 반전/펀치라인에만 true. 전체의 25% 이하.

[말투]
- 어미: ~임, ~음, ~거든, ~잖아 (반말 통일)
- 추임새: ㅋㅋㅋ, ㄹㅇ, 아니, 진짜, 헐, 아 근데
- 금지어: 흥미롭, 놀라운, 충격적, 알아보겠, 결론적으로
- text 한국어만. image_prompt 영어만.

[image_prompt — 영어 필수]
- 기본 키워드: Anime style, vibrant colors, high contrast, expressive, trendy aesthetic
- 과장된 표정: exaggerated funny face, deadpan stare, dramatic eye roll
- 일상 배경: relatable daily office/home setting, vibrant colors
- 첫 장면: 주인공 외형 상세 + "anime style, expressive, vibrant colors, 8k"
- 2장면+: "Same character as scene 1, ..." 필수"""

    _EMPATHY_FORMAT = """{
  "title": "공감 제목 15자 이내",
  "mood": "funny|satisfying",
  "tags": ["#태그1", ... "#태그15"],
  "thumbnail_text": "썸네일 5자 이내",
  "description": "영상 설명 50자 이내",
  "script": [
    {
      "scene_number": 1,
      "text": "한국어 대사 20자 이내",
      "emotion": "funny",
      "highlight": false,
      "pause_ms": 0,
      "important_words": ["핵심단어"],
      "direction": "BGM+연출 지시 (한국어)",
      "image_prompt": "영어 장면 묘사 (English only)",
      "sfx": "",
      "sfx_volume": 0.3
    }
  ]
}
emotion 허용값: neutral, funny, surprise, shocked, excited, warm, sad, relief, tension
sfx 허용값: laugh, rimshot, boing, record_scratch, whoosh, ding, kakao_alert (없으면 "")
highlight: 반전/펀치라인에만 true. 전체의 25% 이하."""

    _EMPATHY_RULES = """[Pace] 1초당 3.5음절. 한 문장 20자 이내 엄수. 미사여구 삭제.

[대본 구조 — 10~14문장]
상황설정 (2~3문장): funny/neutral. 누구나 공감할 일상. pause_ms: 0.
예상전개 (2~3문장): neutral→funny. "당연히 이렇게 되겠지?" 기대감.
반전1 (2~3문장): surprise/shocked. 예상 빗나가는 전개. sfx: record_scratch. highlight: true.
반전2 (2~3문장): funny. 더 황당한 결말. sfx: rimshot.
공감질문 (1문장): neutral/funny. "이거 나만 그럼?" 류. pause_ms: 0.

[필수 체크]
- funny 감정 최소 40% 이상
- 같은 감정 3연속까지 허용 (comedy 특례)
- highlight: 전체의 25% 이하 (반전에만)
- ㅋㅋ 포함 문장 최소 2개
- sfx: 전체 2~4개
- CTA = 공감 질문 (구독/좋아요 금지)

[금지]
- 특정인 비하/조롱, 좋아요/구독 유도, highlight 전부 true"""

    _EMPATHY_FEWSHOT = """[예시 — 이 JSON 형식을 정확히 따라해]
{"title":"배달 시킨 나","mood":"funny","tags":["#일상","#공감","#배달","#웃김","#숏츠","#코미디","#먹방","#혼밥","#자취","#브이로그","#일상브이로그","#웃긴짤","#밈","#MZ","#개웃"],"thumbnail_text":"배달 실화","description":"배달 시켰는데 벌어진 일 ㅋㅋㅋ","script":[
{"scene_number":1,"text":"배달 시키고 누움","emotion":"neutral","highlight":false,"pause_ms":0,"important_words":["배달"],"direction":"느긋한 브금","image_prompt":"Young Korean male, messy hair, oversized t-shirt, lying on couch scrolling phone, anime style, expressive, vibrant colors, 8k, relatable messy room","sfx":"kakao_alert","sfx_volume":0.3},
{"scene_number":2,"text":"조리 시작이래 ㅋㅋ","emotion":"funny","highlight":false,"pause_ms":200,"important_words":["조리"],"direction":"브금 유지","image_prompt":"Same character as scene 1, looking at phone with exaggerated happy expression, anime style, vibrant colors, high contrast","sfx":"","sfx_volume":0.3},
{"scene_number":3,"text":"10분 뒤 다시 봄","emotion":"neutral","highlight":false,"pause_ms":200,"important_words":["10분"],"direction":"브금 유지","image_prompt":"Same character as scene 1, checking phone with impatient deadpan stare, anime style, expressive, vibrant colors","sfx":"","sfx_volume":0.3},
{"scene_number":4,"text":"아직도 조리 시작 ㅋㅋ","emotion":"funny","highlight":false,"pause_ms":300,"important_words":["아직도"],"direction":"브금 약간 긴장","image_prompt":"Same character as scene 1, dramatic eye roll in disbelief, anime style, vibrant colors, high contrast","sfx":"","sfx_volume":0.3},
{"scene_number":5,"text":"30분째 조리 시작","emotion":"funny","highlight":false,"pause_ms":200,"important_words":["30분째"],"direction":"브금 멈춤","image_prompt":"Same character as scene 1, sitting up frustrated, exaggerated angry expression, anime style, vibrant colors, 8k","sfx":"","sfx_volume":0.3},
{"scene_number":6,"text":"전화했더니","emotion":"tension","highlight":false,"pause_ms":400,"important_words":["전화"],"direction":"서스펜스 브금","image_prompt":"Same character as scene 1, holding phone to ear with intense expression, anime style, high contrast, moody lighting","sfx":"","sfx_volume":0.3},
{"scene_number":7,"text":"주문 안 들어왔대 ㅋㅋ","emotion":"shocked","highlight":true,"pause_ms":300,"important_words":["안 들어왔"],"direction":"브금 멈춤","image_prompt":"Same character as scene 1, jaw dropped in shock, phone falling, extreme close-up, anime style, vibrant colors, high contrast","sfx":"record_scratch","sfx_volume":0.5},
{"scene_number":8,"text":"배고파 죽는 중 ㅋㅋㅋ","emotion":"funny","highlight":false,"pause_ms":200,"important_words":["배고파"],"direction":"코미디 브금 IN","image_prompt":"Same character as scene 1, dramatically lying on floor, exaggerated funny hungry face, anime style, vibrant colors","sfx":"rimshot","sfx_volume":0.4},
{"scene_number":9,"text":"결국 라면 끓임 ㅋㅋ","emotion":"funny","highlight":true,"pause_ms":200,"important_words":["라면"],"direction":"브금 유지","image_prompt":"Same character as scene 1, sadly cooking ramen, defeated expression, anime style, warm vibrant colors, trendy aesthetic","sfx":"","sfx_volume":0.3},
{"scene_number":10,"text":"이거 나만 그럼?","emotion":"neutral","highlight":false,"pause_ms":0,"important_words":["나만"],"direction":"브금 페이드아웃","image_prompt":"Same character as scene 1, looking at viewer with knowing smile, anime style, vibrant colors, 8k, trendy aesthetic","sfx":"","sfx_volume":0.3}
]}
주목: highlight 10개 중 2개. 감정 5종(neutral,funny,tension,shocked). sfx 3개. ㅋㅋ 4개 문장."""

    _MYSTERY_ROLE = """너는 세상의 신비로운 잡학지식을 알려주는 미스터리 큐레이터야.
호기심 자극 → 끝까지 보게 만드는 전문가. "비행기 창문은 왜 둥글까?" 류.

[핵심 규칙 3개]
1. 첫 문장 = 15자 이내 호기심 질문 ("왜 비행기 창문은 둥글까?" "엘리베이터에 거울 왜 있을까?")
2. 감정 곡선: tension→neutral→tension→shocked→relief (서서히 고조 → 반전 팩트)
3. highlight는 반전 팩트(정답)에만 true. 전체의 20% 이하.

[말투]
- 어미: ~인데, ~거든, ~이었음, ~였대 (반말)
- 추임새: 근데, 진짜, 아 이게, 알고 보니, 실은
- 금지어: 흥미롭, 놀라운, 충격적, 알아보겠, 살펴보겠, 결론적으로
- text 한국어만. image_prompt 영어만.

[image_prompt — 영어 필수]
- 기본 키워드: Mysterious atmosphere, dark moody lighting, hyper-realistic, 4k, cinematic fog, high contrast
- 단서 장면: dark tones, mysterious shadows, dramatic silhouettes
- 반전 팩트: bright revealing light, infographic style, clean contrast
- 첫 장면: 주인공 외형 상세 + "dark moody lighting, mysterious atmosphere, 4k, cinematic fog"
- 2장면+: "Same character as scene 1, ..." 필수"""

    _MYSTERY_FORMAT = """{
  "title": "미스터리 제목 15자 이내 (의문형)",
  "mood": "scary|shocking|satisfying",
  "tags": ["#태그1", ... "#태그15"],
  "thumbnail_text": "썸네일 5자 이내",
  "description": "영상 설명 50자 이내",
  "script": [
    {
      "scene_number": 1,
      "text": "한국어 대사 20자 이내",
      "emotion": "tension",
      "highlight": false,
      "pause_ms": 0,
      "important_words": ["핵심단어"],
      "direction": "BGM+연출 지시 (한국어)",
      "image_prompt": "영어 장면 묘사 (English only)",
      "sfx": "",
      "sfx_volume": 0.3
    }
  ]
}
emotion 허용값: neutral, tension, surprise, shocked, excited, serious, whisper, relief, warm, funny
sfx 허용값: whoosh, dramatic_stinger, thunder, glass_break, ding, typing (없으면 "")
highlight: 반전 팩트에만 true. 전체의 20% 이하."""

    _MYSTERY_RULES = """[Pace] 1초당 3.5음절. 한 문장 20자 이내 엄수. 미사여구 삭제.

[대본 구조 — 10~14문장]
질문 (1~2문장): tension/surprise. 호기심 자극 질문. sfx: whoosh. pause_ms: 0.
단서1 (2~3문장): neutral→tension. 오해하기 쉬운 상식. direction: "미스터리 BGM".
단서2 (2~3문장): tension→serious. 진짜 이유에 가까워짐. 긴장감 고조.
반전팩트 (2~3문장): shocked→excited. 놀라운 진짜 이유. sfx: dramatic_stinger. highlight: true.
CTA (1문장): relief/warm. "알고 있었음?" / "이것도 궁금하면 팔로우" 류. pause_ms: 0.

[필수 체크]
- 감정 종류 최소 4종 (tension, neutral, shocked, relief 기본)
- highlight: 전체의 20% 이하 (반전 팩트에만)
- important_words: 매 문장 1~2개. 핵심 개념/수치.
- direction: 미스터리 BGM 흐름 명시
- sfx: 전체 2~3개 (질문 + 반전에만)

[금지]
- 검증 안 된 과학/역사 사실 창작, 음모론/미신 조장
- 좋아요/구독 유도, highlight 전부 true"""

    _MYSTERY_FEWSHOT = """[예시 — 이 JSON 형식을 정확히 따라해]
{"title":"엘리베이터 거울 비밀","mood":"shocking","tags":["#미스터리","#상식","#알쓸신잡","#몰랐던사실","#숏츠","#궁금","#엘리베이터","#일상","#과학","#상식퀴즈","#반전","#정보","#꿀팁","#레전드","#소름"],"thumbnail_text":"거울 왜?","description":"엘리베이터 거울의 진짜 이유 알면 소름","script":[
{"scene_number":1,"text":"엘리베이터에 거울 왜 있을까?","emotion":"tension","highlight":false,"pause_ms":0,"important_words":["엘리베이터","거울"],"direction":"미스터리 브금 시작","image_prompt":"Elevator interior with large mirror, mysterious atmosphere, dark moody lighting, cinematic fog, hyper-realistic, 4k, high contrast","sfx":"whoosh","sfx_volume":0.4},
{"scene_number":2,"text":"머리 확인하려고?","emotion":"neutral","highlight":false,"pause_ms":300,"important_words":["머리"],"direction":"브금 유지","image_prompt":"Person checking hair in elevator mirror, dark moody lighting, mysterious shadows, 4k, cinematic","sfx":"","sfx_volume":0.3},
{"scene_number":3,"text":"그럴듯한데 아님","emotion":"tension","highlight":false,"pause_ms":200,"important_words":["아님"],"direction":"브금 긴장감 상승","image_prompt":"Red X mark graphic overlay on mirror scene, dark moody lighting, mysterious atmosphere, 4k, high contrast","sfx":"","sfx_volume":0.3},
{"scene_number":4,"text":"셀카 찍으려고?","emotion":"funny","highlight":false,"pause_ms":200,"important_words":["셀카"],"direction":"브금 유지","image_prompt":"Person taking selfie in elevator mirror, dark moody lighting, mysterious atmosphere, 4k, cinematic","sfx":"","sfx_volume":0.3},
{"scene_number":5,"text":"그것도 아니거든","emotion":"tension","highlight":false,"pause_ms":300,"important_words":["아니"],"direction":"브금 서스펜스","image_prompt":"Darkening atmosphere around elevator, dramatic silhouettes, mysterious shadows, 4k, cinematic fog, high contrast","sfx":"","sfx_volume":0.3},
{"scene_number":6,"text":"진짜 이유가 소름인데","emotion":"serious","highlight":false,"pause_ms":400,"important_words":["소름"],"direction":"브금 멈춤 직전","image_prompt":"Dark elevator with single spotlight on mirror, ominous atmosphere, dark moody lighting, 4k, cinematic fog","sfx":"","sfx_volume":0.3},
{"scene_number":7,"text":"휠체어 사용자 때문임","emotion":"shocked","highlight":true,"pause_ms":300,"important_words":["휠체어"],"direction":"브금 멈춤 + 반전음","image_prompt":"Wheelchair user using mirror to see behind them, bright revealing light, clean contrast, infographic style, 4k, high contrast","sfx":"dramatic_stinger","sfx_volume":0.5},
{"scene_number":8,"text":"뒤를 못 돌아보니까","emotion":"neutral","highlight":false,"pause_ms":200,"important_words":["뒤"],"direction":"잔잔한 브금 IN","image_prompt":"Diagram showing wheelchair in elevator with arrow to mirror, bright revealing light, infographic style, 4k, clean contrast","sfx":"","sfx_volume":0.3},
{"scene_number":9,"text":"거울로 뒤를 확인하는 거임","emotion":"warm","highlight":true,"pause_ms":200,"important_words":["확인"],"direction":"따뜻한 브금","image_prompt":"Wheelchair user smiling while checking exit through mirror, warm bright lighting, 4k, cinematic, high contrast","sfx":"","sfx_volume":0.3},
{"scene_number":10,"text":"이거 알고 있었음?","emotion":"relief","highlight":false,"pause_ms":0,"important_words":["알고"],"direction":"브금 페이드아웃","image_prompt":"Person looking at viewer with curious knowing expression, soft cinematic lighting, 4k, trendy aesthetic","sfx":"","sfx_volume":0.3}
]}
주목: highlight 10개 중 2개. 감정 6종(tension,neutral,funny,serious,shocked,warm,relief). sfx 2개."""

    # ── 테마 자동 감지 키워드 ──
    _THEME_KEYWORDS = {
        "life_hack": ["꿀팁", "방법", "노하우", "비법", "절약", "가성비", "추천", "TOP", "랭킹",
                      "순위", "리뷰", "정리", "모르면 손해", "생활", "살림", "청소", "요리",
                      "지우는 법", "만드는 법", "하는 법", "기능"],
        "empathy": ["웃긴", "ㅋㅋ", "개웃", "존웃", "황당", "킹받", "밈", "짤", "공감",
                    "일상", "출근", "월요일", "귀찮", "vs", "특징", "유형", "아침",
                    "헬스장", "첫날", "일주일", "MBTI", "직장"],
        "mystery": ["미스터리", "왜", "비밀", "진실", "알고보니", "몰랐던", "이유",
                    "과학", "상식", "퀴즈", "궁금", "소름", "괴담", "둥글", "진짜",
                    "비싼", "세계에서", "우주"],
    }

    def __init__(self, config: Config):
        self.config = config
        self.theme = getattr(config, "theme", "auto")
        # v6.2: Gemini 롤백 — google_api_key 사용
        api_key = config.google_api_key
        if not api_key:
            raise ValueError("GOOGLE_API_KEY 환경변수가 필요합니다! (대본 생성: Gemini)")
        genai_flash.configure(api_key=api_key)
        self._model = genai_flash.GenerativeModel(
            self.GEMINI_MODEL,
            generation_config=genai_flash.types.GenerationConfig(
                temperature=0.4,
                top_p=0.95,
                max_output_tokens=4096,
            ),
        )

        # ★ 테마 프리셋 레지스트리 (gossip은 기존 클래스 상수 참조)
        self.THEME_PRESETS = {
            "gossip": {
                "ROLE_PROMPT": self.ROLE_PROMPT,
                "FORMAT_SPEC": self.FORMAT_SPEC,
                "CONTENT_RULES": self.CONTENT_RULES,
                "FEW_SHOT_EXAMPLES": self.FEW_SHOT_EXAMPLES,
                "padded_instruction": (
                    "이 주제로 2030 세대가 격하게 공감하는 1인칭 썰 대본을 써줘. "
                    "분노와 반전을 강조해서 작성해줘."
                ),
                "build_prompt_suffix": "위 소스를 바탕으로 분노와 반전을 강조한 1인칭 썰 형식의 숏츠 대본을 JSON으로 출력해.",
                "image_style": "Cinematic, 8k, High Contrast, Korean webtoon style, bold outlines",
                "quality_params": {
                    "min_emotion_types": 4, "max_highlight_ratio": 0.30,
                    "max_long_sentence_count": 2, "long_sentence_threshold": 12,
                    "min_sentence_count": 6, "max_first_sentence_len": 12,
                    "max_consecutive_same_emotion": 2,
                },
            },
            "life_hack": {
                "ROLE_PROMPT": self._LIFE_HACK_ROLE, "FORMAT_SPEC": self._LIFE_HACK_FORMAT,
                "CONTENT_RULES": self._LIFE_HACK_RULES, "FEW_SHOT_EXAMPLES": self._LIFE_HACK_FEWSHOT,
                "padded_instruction": (
                    "이 주제로 꿀팁 대본을 써줘. "
                    "서론 빼고 바로 '방법'부터 임팩트 있게 설명해줘. "
                    "시청자가 저장하고 싶게 만들어야 해."
                ),
                "build_prompt_suffix": "위 소스를 바탕으로 서론 없이 바로 방법부터 임팩트 있는 꿀팁 숏츠 대본을 JSON으로 출력해.",
                "image_style": "Cinematic close-up, 8k resolution, clean bright lighting, minimalist, trendy aesthetic",
                "quality_params": {
                    "min_emotion_types": 3, "max_highlight_ratio": 0.35,
                    "max_long_sentence_count": 2, "long_sentence_threshold": 12,
                    "min_sentence_count": 6, "max_first_sentence_len": 12,
                    "max_consecutive_same_emotion": 2,
                },
            },
            "empathy": {
                "ROLE_PROMPT": self._EMPATHY_ROLE, "FORMAT_SPEC": self._EMPATHY_FORMAT,
                "CONTENT_RULES": self._EMPATHY_RULES, "FEW_SHOT_EXAMPLES": self._EMPATHY_FEWSHOT,
                "padded_instruction": (
                    "이 주제로 일상 공감 대본을 써줘. "
                    "MBTI나 직장 생활 등 누구나 겪을 법한 상황을 "
                    "'내 이야기'처럼 친근하게 써줘."
                ),
                "build_prompt_suffix": "위 소스를 바탕으로 누구나 공감할 수 있는 '내 이야기' 느낌의 숏츠 대본을 JSON으로 출력해.",
                "image_style": "Anime style, vibrant colors, high contrast, expressive, trendy aesthetic",
                "quality_params": {
                    "min_emotion_types": 3, "max_highlight_ratio": 0.30,
                    "max_long_sentence_count": 2, "long_sentence_threshold": 12,
                    "min_sentence_count": 6, "max_first_sentence_len": 12,
                    "max_consecutive_same_emotion": 3, "min_funny_ratio": 0.35,
                },
            },
            "mystery": {
                "ROLE_PROMPT": self._MYSTERY_ROLE, "FORMAT_SPEC": self._MYSTERY_FORMAT,
                "CONTENT_RULES": self._MYSTERY_RULES, "FEW_SHOT_EXAMPLES": self._MYSTERY_FEWSHOT,
                "padded_instruction": (
                    "이 주제로 미스터리/상식 대본을 써줘. "
                    "처음에 궁금증을 유발하는 질문을 던지고, "
                    "끝까지 보게 만든 뒤 마지막에 결론을 내줘."
                ),
                "build_prompt_suffix": "위 소스를 바탕으로 궁금증 유발 → 끝까지 보게 만드는 미스터리 숏츠 대본을 JSON으로 출력해.",
                "image_style": "Mysterious atmosphere, dark moody lighting, hyper-realistic, 4k, cinematic fog, high contrast",
                "quality_params": {
                    "min_emotion_types": 3, "max_highlight_ratio": 0.25,
                    "max_long_sentence_count": 2, "long_sentence_threshold": 12,
                    "min_sentence_count": 6, "max_first_sentence_len": 12,
                    "max_consecutive_same_emotion": 2,
                },
            },
        }
        self._active_preset = self.THEME_PRESETS["gossip"]  # 기본값

    def _detect_theme(self, title: str) -> str:
        """주제 키워드 기반 테마 자동 감지. 매칭 안 되면 'gossip' 반환."""
        scores = {}
        for theme, keywords in self._THEME_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in title)
            if score > 0:
                scores[theme] = score
        if not scores:
            return "gossip"
        return max(scores, key=scores.get)

    def _get_preset(self, topic_title: str = "") -> dict:
        """현재 테마에 맞는 프리셋 반환. auto면 topic_title로 감지."""
        theme = self.theme
        if theme == "auto":
            theme = self._detect_theme(topic_title)
            print(f"  🎭 테마 자동 감지: '{theme}' (주제: {topic_title[:30]})")
        preset = self.THEME_PRESETS.get(theme, self.THEME_PRESETS["gossip"])
        return preset

    def _build_prompt(self, post: dict, retry_feedback: str = "") -> str:
        """3분할 프롬프트 조립: 테마별 Role + Content + Format + Few-shot + 소스 데이터"""
        # ★ 테마 프리셋 사용
        preset = self._active_preset

        comments = post.get('comments', [])
        comments_text = ""
        if isinstance(comments, list) and comments:
            comments_text = "\n## 베스트 댓글\n" + "\n".join(f"- {c}" for c in comments[:4])

        source_name = post.get('source', '커뮤니티')
        source_brand_map = {
            "natepan": "네이트판 레전드 썰", "nate_pann": "네이트판 레전드 썰",
            "네이트판": "네이트판 레전드 썰", "dcinside": "디씨 레전드",
            "dc_inside": "디씨 레전드", "디시인사이드": "디씨 레전드",
            "fmkorea": "펨코 핫글", "viral_topic": "화제글",
        }
        source_brand = source_brand_map.get(source_name.lower(), f"{source_name} 화제글")

        retry_section = ""
        if retry_feedback:
            retry_section = f"\n⚠️ [이전 대본 문제점 — 반드시 수정해서 다시 써줘]\n{retry_feedback}\n"

        # ★ image_style 강제 지시
        image_style = preset.get('image_style', '')
        image_style_section = ""
        if image_style:
            image_style_section = f"\n[image_prompt 스타일 강제]\n모든 image_prompt 끝에 반드시 포함: {image_style}\n"

        # 사용자 메시지 (시스템 프롬프트는 SHORTS_SYSTEM_PROMPT로 별도 전달)
        return f"""{preset['ROLE_PROMPT']}

{preset['FEW_SHOT_EXAMPLES']}

[출력 JSON 스키마]
{preset['FORMAT_SPEC']}

{preset['CONTENT_RULES']}
{image_style_section}
---
[소스 데이터]
출처: {source_name} | 브랜딩: "{source_brand}"
제목: {post['title']}

{post.get('content', '')[:2500]}
{comments_text}
{retry_section}
{preset['build_prompt_suffix']}"""

    def _quality_check(self, script_data: dict) -> list[str]:
        """대본 품질 검증 v3 — 테마별 파라미터 적용. 문제점 리스트 반환."""
        issues = []
        lines = script_data.get("script", [])
        if not lines:
            issues.append("script 배열이 비어있음")
            return issues

        # ★ 테마별 파라미터 로드
        qp = self._active_preset.get("quality_params", {})
        min_emotions = qp.get("min_emotion_types", 5)
        max_hl_ratio = qp.get("max_highlight_ratio", 0.30)
        max_long = qp.get("max_long_sentence_count", 2)
        long_thresh = qp.get("long_sentence_threshold", 22)
        min_sentences = qp.get("min_sentence_count", 10)
        max_first_len = qp.get("max_first_sentence_len", 15)
        max_consec = qp.get("max_consecutive_same_emotion", 2)

        n = len(lines)
        emotions = [l.get("emotion", "neutral") for l in lines]

        # 1) 같은 감정 연속 체크 (테마별: gossip 2연속, comedy 3연속)
        limit = max_consec + 1
        for i in range(len(emotions) - limit + 1):
            if len(set(emotions[i:i+limit])) == 1:
                issues.append(f"같은 감정 {limit}연속: {emotions[i]} (장면 {i+1}~{i+limit})")
                break

        # 2) 감정 종류 최소 N종
        unique_emotions = set(emotions)
        if len(unique_emotions) < min_emotions:
            issues.append(f"감정 종류 부족: {len(unique_emotions)}종 (최소 {min_emotions}종 필요) — {unique_emotions}")

        # 3) highlight 비율 체크
        highlight_count = sum(1 for l in lines if l.get("highlight") is True)
        max_highlights = max(2, int(n * max_hl_ratio))
        if highlight_count > max_highlights:
            issues.append(f"highlight 남용: {highlight_count}/{n}개 (최대 {max_highlights}개)")
        if n >= 8 and highlight_count == n:
            issues.append(f"highlight 전부 true ({n}개)")

        # 4) 긴 문장 체크
        long_count = sum(1 for l in lines if len(l.get("text", "")) > long_thresh)
        if long_count > max_long:
            issues.append(f"{long_thresh}자 초과 문장 {long_count}개 (최대 {max_long}개)")

        # 5) AI슬롭 단어 체크
        full_text = " ".join(l.get("text", "") for l in lines)
        slop_found = [w for w in self._AI_SLOP_WORDS if w in full_text]
        if len(slop_found) >= 2:
            issues.append(f"AI슬롭 단어 {len(slop_found)}개: {slop_found}")

        # 6) 영어/외국어 혼입 체크 (text 필드만)
        foreign_pattern = re.compile(r'[a-zA-Zа-яА-ЯёЁ]{3,}')
        allowed_english = {
            "CCTV", "SNS", "MZ", "GDP", "AI", "CEO", "IT", "PC", "TV", "OTT",
            "MBTI", "TMI", "BGM", "SFX", "TOP", "DNA", "USB", "LED", "DIY", "FAQ",
            # 16 MBTI 유형
            "ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
            "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ",
        }
        for l in lines:
            txt = l.get("text", "")
            foreign_matches = foreign_pattern.findall(txt)
            real_foreign = [m for m in foreign_matches if m.upper() not in allowed_english]
            if real_foreign:
                issues.append(f"외국어 혼입: {real_foreign} (장면 {l.get('scene_number', '?')})")
                break

        # 7) 첫 문장 길이
        if lines and len(lines[0].get("text", "")) > max_first_len:
            first_len = len(lines[0].get("text", ""))
            issues.append(f"첫 문장(훅) {first_len}자 — {max_first_len}자 이내 권장")

        # 8) 분량 체크
        if n < min_sentences:
            issues.append(f"문장 수 부족: {n}개 (최소 {min_sentences}개)")

        # 9) image_prompt 한국어 체크 (영어 필수)
        kr_pattern = re.compile(r'[가-힣]')
        kr_prompts = [i for i, l in enumerate(lines, 1) if kr_pattern.search(l.get("image_prompt", ""))]
        if kr_prompts:
            issues.append(f"image_prompt에 한국어 포함 (장면 {kr_prompts[:3]}). 영어로만 작성해야 함.")

        # 10) comedy 전용: funny 비율 체크
        min_funny = qp.get("min_funny_ratio", 0)
        if min_funny > 0 and n > 0:
            funny_count = sum(1 for e in emotions if e == "funny")
            if funny_count / n < min_funny:
                issues.append(f"funny 감정 부족: {funny_count}/{n} ({min_funny*100:.0f}%+ 필요)")

        return issues

    def generate(self, post: dict) -> Optional[dict]:
        """v8.0: 테마별 대본 생성. 검증 실패 시 최대 3회 재생성."""
        # ★ 테마 프리셋 결정
        self._active_preset = self._get_preset(post.get("title", ""))

        print(f"\n{'='*60}")
        print(f"📝 Stage 2: 대본 생성 (v8.0 멀티테마 프롬프트)")
        print(f"  제목: {post['title'][:40]}...")
        print(f"{'='*60}")

        content = post.get("content", "")
        title = post.get("title", "")
        is_viral = post.get("_is_viral", False)

        # ── 소스 품질 체크 (바이럴/토픽 소스는 제목 기반이므로 스킵) ──
        if not is_viral:
            if len(content) < 200:
                print(f"  ⚠️  소스 내용 부족 ({len(content)}자), 건너뜀")
                return None
            for kw in CommunityScraper.BLOCK_KEYWORDS:
                if kw in content or kw in title:
                    print(f"  🚫 차단 키워드: '{kw}' 발견 → 건너뜀")
                    return None
            spam_count = sum(1 for kw in CommunityScraper.UI_KEYWORDS if kw in content)
            if spam_count >= 2:
                print(f"  ⚠️  UI/광고 텍스트 감지 ({spam_count}개 키워드), 건너뜀")
                return None
            risk_count = sum(1 for kw in CommunityScraper.RISKY_CONTENT_KEYWORDS if kw in content or kw in title)
            if risk_count >= 1:
                print(f"  ⚠️  위험 콘텐츠 감지 ({risk_count}개): 허위정보 방지를 위해 건너뜀")
                return None
        else:
            print(f"  🔥 바이럴 소스 → 품질 필터 바이패스")

        start = time.time()
        retry_feedback = ""
        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            try:
                prompt = self._build_prompt(post, retry_feedback)
                # v6.2: Gemini 롤백 — DIRECTOR_PERSONA + 프롬프트를 합쳐 전달
                full_prompt = self.SYSTEM_PROMPT + "\n\n" + prompt
                response = self._model.generate_content(full_prompt)
                if not response.text:
                    raise ValueError("Gemini API returned empty response")
                raw = response.text
                script_data = self._extract_json(raw)

                # 정확성 검증 (원문 대조)
                script_data = self._validate_script_accuracy(script_data, post)

                # 대본 데이터 클리닝
                script_data = self._clean_script_data(script_data)

                # ★ v7.0: 품질 검증 + 재생성 루프
                quality_issues = self._quality_check(script_data)

                if not quality_issues:
                    elapsed = time.time() - start
                    n = len(script_data.get("script", []))
                    script_data["_meta"] = {
                        "time": f"{elapsed:.1f}s",
                        "model": self.GEMINI_MODEL,
                        "source": post.get("content", "")[:100],
                        "accuracy_warnings": script_data.get("_accuracy_warnings", 0),
                        "attempts": attempt,
                    }
                    print(f"  ✅ 대본 완료! ({elapsed:.1f}초, {n}문장, {attempt}회차, Gemini)")
                    return script_data

                # 검증 실패 → 재생성 준비
                print(f"  ⚠️  품질 검증 실패 (시도 {attempt}/{max_attempts}):")
                for issue in quality_issues:
                    print(f"     - {issue}")

                if attempt < max_attempts:
                    retry_feedback = "\n".join(f"- {issue}" for issue in quality_issues)
                    print(f"  🔄 피드백 포함하여 재생성...")
                else:
                    # 마지막 시도도 실패 → 그래도 사용 (완벽하지 않지만)
                    elapsed = time.time() - start
                    n = len(script_data.get("script", []))
                    script_data["_meta"] = {
                        "time": f"{elapsed:.1f}s",
                        "model": self.GEMINI_MODEL,
                        "source": post.get("content", "")[:100],
                        "accuracy_warnings": script_data.get("_accuracy_warnings", 0),
                        "attempts": attempt,
                        "quality_issues": quality_issues,
                    }
                    print(f"  ⚠️  {max_attempts}회 시도 후에도 미통과 — 최선 결과 사용 ({n}문장)")
                    return script_data

            except Exception as e:
                print(f"  ❌ Gemini API 에러 (시도 {attempt}/{max_attempts}): {e}")
                try:
                    if 'raw' in locals():
                        print(f"  🔍 Gemini 원본 (앞 300자): {raw[:300]}")
                except Exception:
                    pass
                if attempt == max_attempts:
                    return self._fallback_script(post)

        return self._fallback_script(post)

    def generate_from_topic(self, topic: str) -> Optional[dict]:
        """주제만으로 대본 생성 (바이럴/수동 모드) — 테마별 분기"""
        # ★ 테마 프리셋에서 padded_instruction 가져오기
        preset = self._get_preset(topic)
        padded = (
            f"주제: '{topic}'\n"
            f"{preset['padded_instruction']}"
        )
        fake = {
            "title": topic,
            "content": padded,
            "source": "viral_topic",
            "_is_viral": True,
        }
        return self.generate(fake)

    # ── v6.0 대본 데이터 클리닝 (image_prompt 오염 + 지시문 오염 + 필드 정규화) ──

    # 패턴 A: image_prompt 전용 키워드 (text에 있으면 오염)
    _IMG_CONTAMINATION_KW = [
        "첫 장면과 동일한 캐릭터", "동일한 캐릭터", "B급 웹툰",
        "클로즈업", "뒷모습", "배경은", "과장된 표정",
        "단순하고 굵은 선", "한국 B급", "웹툰 스타일",
        "파마머리", "꽃무늬", "블라우스", "ink outline",
        "muted warm", "realistic", "webtoon", "illustration",
    ]

    # 패턴 B: 정규식 — 연출 지시문이 text에 들어온 경우 (괄호 안 지시, 영어 프롬프트 등)
    _DIRECTIVE_REGEX = re.compile(
        r'('
        r'\(.*?(장면|캐릭터|배경|표정|클로즈업|뒷모습|조명|카메라|앵글).*?\)'  # 괄호 안 한국어 지시
        r'|'
        r'\[.*?(scene|character|background|close.?up|back\s?view).*?\]'  # 대괄호 안 영어 지시
        r'|'
        r'(?:Korean|Naver|webtoon|illustration|B급|ink|outline|muted|realistic)'  # 영어 프롬프트 키워드
        r'(?:\s*,\s*(?:Korean|Naver|webtoon|illustration|B급|ink|outline|muted|realistic)){2,}'  # 3개 이상 연속
        r')',
        re.IGNORECASE,
    )

    def _clean_script_data(self, script_data: dict) -> dict:
        """대본 JSON 후처리: 오염 제거 + 필드 정규화 + 빈 문장 제거

        3단계 클리닝:
        1) image_prompt 키워드 오염 탐지 → text 무효화
        2) 정규식으로 연출 지시문 / 영어 프롬프트 잔재 제거
        3) text/emotion/sfx 필드 정규화 + 빈 문장 제거
        """
        cleaned_count = 0

        for line in script_data.get("script", []):
            txt = line.get("text", "")
            if not txt:
                continue

            # ── Stage 1: image_prompt 키워드 오염 (기존 로직 강화) ──
            match_count = sum(1 for kw in self._IMG_CONTAMINATION_KW if kw in txt)
            if len(txt) > 20 and match_count >= 2:
                print(f"  ⚠️  [클린] image_prompt 혼입 → 제거: {txt[:50]}...")
                line["text"] = ""
                cleaned_count += 1
                continue

            # ── Stage 2: 정규식으로 연출 지시문 잔재 제거 ──
            original = txt
            txt = self._DIRECTIVE_REGEX.sub("", txt).strip()
            # 괄호/대괄호 안 지시문만 단독으로 남은 경우 전체 제거
            txt = re.sub(r'\(.*?(장면|캐릭터|배경|표정|조명).*?\)', '', txt).strip()
            txt = re.sub(r'\[.*?(scene|character|background).*?\]', '', txt, flags=re.IGNORECASE).strip()
            # text와 image_prompt가 완전히 동일하면 text 무효화
            if txt and txt == line.get("image_prompt", ""):
                txt = ""
            if txt != original:
                if not txt:
                    print(f"  ⚠️  [클린] 지시문 전체 오염 → 제거: {original[:50]}...")
                    cleaned_count += 1
                else:
                    print(f"  🔧  [클린] 지시문 부분 제거: {original[:30]}... → {txt[:30]}...")
            line["text"] = txt

            # ── Stage 3: 필드 정규화 ──
            # emotion 필드: 한국어 → 영어 매핑 + 유효하지 않으면 neutral로 교정
            valid_emotions = {
                "neutral", "tension", "surprise", "anger", "angry",
                "sad", "fun", "funny", "shock", "shocked", "relief",
                "excited", "warm", "serious", "whisper",
            }
            # ★ 한국어 emotion → 영어 매핑 (Gemini가 한국어로 뱉는 경우 대비)
            _KR_EMOTION_MAP = {
                "충격": "shocked", "놀람": "surprise", "경악": "shocked",
                "분노": "angry", "빡침": "angry", "화남": "angry",
                "슬픔": "sad", "우울": "sad", "허탈": "sad", "좌절": "sad",
                "재미": "funny", "웃김": "funny", "유머": "funny",
                "긴장": "tension", "불안": "tension", "초조": "tension",
                "감동": "warm", "따뜻": "warm", "뭉클": "warm",
                "공포": "whisper", "무서움": "whisper", "소름": "whisper",
                "현타": "sad", "체념": "sad", "한숨": "sad",
                "흥분": "excited", "설렘": "excited", "기대": "excited",
                "진지": "serious", "심각": "serious",
                "안도": "relief", "후련": "relief",
                "궁금": "tension", "절박": "tension",
            }
            emo = line.get("emotion", "neutral")
            # 콤마로 여러 감정 나열된 경우 ("슬픔, 허탈") → 첫 번째만 사용
            if "," in emo or "/" in emo:
                emo = re.split(r'[,/]', emo)[0].strip()
            # 한국어 매핑 시도
            if emo not in valid_emotions:
                mapped = _KR_EMOTION_MAP.get(emo)
                if mapped:
                    line["emotion"] = mapped
                else:
                    # 부분 매칭 (e.g. "궁금함" → "궁금" 매칭)
                    matched = False
                    for kr, en in _KR_EMOTION_MAP.items():
                        if kr in emo:
                            line["emotion"] = en
                            matched = True
                            break
                    if not matched:
                        line["emotion"] = "neutral"

            # sfx 필드: 대괄호/공백 정리 + 유사어 매핑
            sfx = str(line.get("sfx", ""))
            sfx = re.sub(r'[\[\]\s]', '', sfx).strip()
            # ★ mapping.json에 없는 SFX 태그 → 유사한 태그로 자동 변환
            _SFX_ALIAS_MAP = {
                # 드라마/액션
                "punch_hit": "punch", "hit": "punch", "slap": "punch",
                "drama_punch": "punch", "crash": "glass_break", "break": "glass_break",
                "explosion": "thunder", "boom": "thunder", "slam": "punch",
                # 반응/감정
                "deep_sigh": "gasp", "sigh": "gasp", "cry": "gasp",
                "scream": "gasp", "wow": "crowd_ooh", "ooh": "crowd_ooh",
                "surprise": "gasp", "shock": "record_scratch",
                # 전환/UI
                "fast_swoosh": "swoosh", "swipe": "swoosh", "slide": "swoosh",
                "pop": "ding", "question_pop": "ding", "alert": "kakao_alert",
                "notification": "kakao_alert", "bell": "doorbell",
                "click": "typing", "tap": "typing",
                # 코미디
                "giggle": "laugh", "lol": "laugh", "haha": "laugh",
                "comedy": "rimshot", "joke": "rimshot", "spring": "boing",
                # 기타
                "empty_stomach_growl": "boing", "growl": "boing",
                "money": "cash_register", "coin": "cash_register", "pay": "cash_register",
                "vibrate": "phone_vibrate", "phone": "phone_vibrate",
            }
            if sfx and sfx not in {"", "none", "null"}:
                sfx_lower = sfx.lower()
                if sfx_lower in _SFX_ALIAS_MAP:
                    sfx = _SFX_ALIAS_MAP[sfx_lower]
            line["sfx"] = sfx

            # sfx_volume 필드: 0.1~1.0 범위 강제
            vol = line.get("sfx_volume", 0.7)
            try:
                vol = float(vol)
                vol = max(0.1, min(1.0, vol))
            except (ValueError, TypeError):
                vol = 0.7
            line["sfx_volume"] = vol

            # important_words 필드: 리스트 보장
            iw = line.get("important_words", [])
            if isinstance(iw, str):
                iw = [w.strip() for w in iw.split(",") if w.strip()]
            elif not isinstance(iw, list):
                iw = []
            line["important_words"] = iw

        # ── 빈 text 문장 제거 ──
        before = len(script_data.get("script", []))
        script_data["script"] = [
            line for line in script_data.get("script", [])
            if line.get("text", "").strip()
        ]
        after = len(script_data.get("script", []))

        if cleaned_count > 0 or before != after:
            print(f"  🧹 클리닝 완료: {cleaned_count}건 오염 제거, "
                  f"{before}→{after}문장")

        return script_data

    def _extract_json(self, text: str) -> dict:
        # 0차 전처리: 마크다운 백틱 제거 (```json ... ``` 또는 ``` ... ```)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```\s*$", "", text)
            text = text.strip()

        # 1차: 전체 텍스트를 바로 JSON 파싱 시도
        try:
            parsed = json.loads(text)
            # ★ Gemini가 배열 [{}]로 감쌀 수 있음 → 첫 번째 dict 추출
            if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
                return parsed[0]
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        # 1차: 코드 블록에서 JSON 추출
        json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
                    return parsed[0]
                return parsed
            except json.JSONDecodeError:
                pass
        # 2차: 중괄호 매칭 (가장 바깥쪽 { } 쌍 찾기)
        depth = 0
        start_idx = -1
        for i, ch in enumerate(text):
            if ch == '{':
                if depth == 0:
                    start_idx = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start_idx >= 0:
                    try:
                        return json.loads(text[start_idx:i+1])
                    except json.JSONDecodeError:
                        start_idx = -1
                        continue
        raise ValueError("JSON 파싱 실패: 유효한 JSON을 찾을 수 없습니다")

    def _validate_script_accuracy(self, script_data: dict, post: dict) -> dict:
        """원문 대조 검증: AI가 만들어낸 허위 요소 탐지 및 제거.

        검증 항목:
        1. 원문에 없는 직접 인용(따옴표 대화) 탐지
        2. 의학/법률/금융 허위정보 패턴 탐지
        3. 출처 불명 통계/수치 탐지
        4. 원문 핵심 키워드 누락 여부 확인
        """
        source_text = post.get("content", "")
        script_lines = script_data.get("script", [])
        if not script_lines or not source_text:
            return script_data

        warnings = []
        cleaned_lines = []

        for line in script_lines:
            text = line.get("text", "")
            flagged = False

            # 1) 원문에 없는 직접 인용/대화 탐지
            quotes = re.findall(r'["\u201c\u201d](.+?)["\u201c\u201d]', text)
            for q in quotes:
                if len(q) > 5 and q not in source_text:
                    # 원문에 없는 대사 → 따옴표 제거하고 간접화
                    text = text.replace(f'"{q}"', q)
                    text = text.replace(f'\u201c{q}\u201d', q)
                    warnings.append(f"직접인용 제거: '{q[:20]}...'")

            # 2) 의학/법률/금융 허위정보 패턴
            risky_patterns = [
                (r'(\d+)%\s*(확률|가능성|치료율|생존율)', "의학 통계"),
                (r'벌금\s*\d+', "법률 수치"),
                (r'(\d+)(만원|억원|조원)', "금액"),
                (r'연구(에\s*따르면|결과|팀|진)', "미확인 연구 인용"),
                (r'전문가(에\s*따르면|들은|가)', "미확인 전문가 인용"),
            ]
            for pat, label in risky_patterns:
                match = re.search(pat, text)
                if match and match.group(0) not in source_text:
                    warnings.append(f"{label} 감지(원문 미확인): '{match.group(0)}'")
                    # 제거하지 않되, 헤지 표현으로 감쌀 수 있음
                    # 심각한 경우 라인 교체
                    if label in ("의학 통계", "미확인 연구 인용"):
                        text = re.sub(pat, '', text).strip()
                        if not text:
                            flagged = True

            # 3) 날짜/시간 조작 탐지
            date_m = re.findall(r'(\d{4})년|(\d{1,2})월\s*(\d{1,2})일', text)
            for dm in date_m:
                date_str = ''.join(dm)
                if date_str and date_str not in source_text:
                    warnings.append(f"원문에 없는 날짜: '{date_str}'")
                    # 날짜 구체화 제거
                    text = re.sub(r'\d{4}년\s*\d{1,2}월\s*\d{1,2}일', '얼마 전', text)
                    text = re.sub(r'\d{4}년', '최근', text)

            if not flagged:
                line["text"] = text
                cleaned_lines.append(line)

        if warnings:
            print(f"  🔍 정확성 검증: {len(warnings)}건 수정")
            for w in warnings[:5]:
                print(f"     ⚠️  {w}")

        # 4) 원문 핵심 키워드 포함 확인
        source_words = set(re.findall(r'[가-힣]{2,}', source_text))
        script_full = " ".join(l.get("text", "") for l in cleaned_lines)
        script_words = set(re.findall(r'[가-힣]{2,}', script_full))
        # 원문 상위 빈출 단어 중 스크립트에 포함된 비율
        common_source = [w for w in source_words if len(w) >= 3][:30]
        if common_source:
            overlap = sum(1 for w in common_source if w in script_words)
            coverage = overlap / len(common_source)
            if coverage < 0.15:
                print(f"  ⚠️  원문 키워드 반영률 낮음: {coverage:.0%} — 대본이 원문과 동떨어질 수 있음")

        script_data["script"] = cleaned_lines
        script_data["_accuracy_warnings"] = len(warnings)
        return script_data

    def _fallback_script(self, post: dict) -> dict:
        """폴백 대본: 원문 내용을 최대한 활용하여 최소 품질 보장

        ★ viral_topic/바이럴 소스일 경우 시스템 패딩 텍스트가 content에 들어오므로
           제목만으로 간결한 훅킹 대본을 생성한다.
        """
        t = post["title"][:12]
        content = post.get("content", "")
        is_viral = post.get("_is_viral", False)

        script_lines = []

        # 후킹 (항상 동일)
        script_lines.append({"text": "이거 실화냐?", "emotion": "surprise",
                             "highlight": True, "pause_ms": 300,
                             "image_prompt": "충격받은 표정의 사람 뒷모습, B급 웹툰 스타일"})
        script_lines.append({"text": t, "emotion": "tension",
                             "highlight": True, "pause_ms": 0,
                             "image_prompt": f"{t} 장면, 과장된 표정, B급 웹툰 스타일"})

        if is_viral:
            # ★ 바이럴 소스: content가 패딩 텍스트이므로 제목 기반 간결 대본
            script_lines.append({"text": "아니 진짜 이게 됨?", "emotion": "shocked",
                                 "highlight": False, "pause_ms": 200,
                                 "image_prompt": "어이없어하는 사람, B급 웹툰 스타일"})
            script_lines.append({"text": "미쳤다 ㄹㅇ", "emotion": "funny",
                                 "highlight": False, "pause_ms": 200,
                                 "image_prompt": "웃으며 고개 흔드는 사람, B급 웹툰 스타일"})
            script_lines.append({"text": "님들이면 어떡함?", "emotion": "neutral",
                                 "highlight": True, "pause_ms": 0,
                                 "image_prompt": "카메라를 보며 질문하는 표정, B급 웹툰 스타일"})
        else:
            # 원문에서 핵심 문장 추출 (마침표/줄바꿈 기준 분리)
            source_sents = [s.strip() for s in re.split(r'[.\n]', content) if len(s.strip()) > 10]

            for sent in source_sents[:8]:
                truncated = sent[:15]
                emotion = "neutral"
                if any(kw in sent for kw in ["ㅋㅋ", "웃", "재밌"]):
                    emotion = "funny"
                elif any(kw in sent for kw in ["소름", "충격", "미쳤"]):
                    emotion = "shocked"
                elif any(kw in sent for kw in ["감동", "눈물", "울"]):
                    emotion = "warm"
                script_lines.append({"text": truncated, "emotion": emotion,
                                     "highlight": False, "pause_ms": 200,
                                     "image_prompt": f"{truncated} 장면, B급 웹툰"})

            script_lines.append({"text": "어떻게 생각해?", "emotion": "neutral",
                                 "highlight": False, "pause_ms": 0,
                                 "image_prompt": "질문하는 표정, B급 웹툰 스타일"})

        return {
            "title": t,
            "mood": "funny",
            "script": script_lines,
            "tags": ["#썰", "#레전드", "#실화", "#숏츠", "#커뮤니티",
                     "#공감", "#ㅋㅋㅋ", "#반전", "#댓글", "#실화바탕",
                     "#웹툰", "#B급", "#킹받", "#사이다", "#미친"],
            "thumbnail_text": t[:5],
            "description": f"{t} - 실화 기반 썰",
        }


# ============================================================
# 🔊 Stage 3: TTS + 자막 타이밍
# ============================================================
class TTSEngine:
    """v6.0: 멀티엔진 TTS — ElevenLabs → OpenAI → edge-tts 폴백

    각 문장을 독립적으로 TTS 생성 → 정확한 길이 측정.
    ElevenLabs: 감정별 voice_settings + word-level timestamps
    OpenAI: 감정별 speed 조절
    edge-tts: 감정별 rate/pitch (무료 폴백)
    """

    # edge-tts 전용 감정별 속도/피치 매핑
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
        self._elevenlabs = None
        self._engine_order = []
        self._init_engines()

    def _init_engines(self):
        """엔진 우선순위 해결: ElevenLabs → edge-tts"""
        engine_pref = self.config.tts_engine

        if engine_pref == "auto":
            if self.config.elevenlabs_api_key:
                try:
                    from elevenlabs_tts import ElevenLabsTTS
                    self._elevenlabs = ElevenLabsTTS(
                        self.config.elevenlabs_api_key,
                        self.config.elevenlabs_voice_id,
                    )
                    self._engine_order.append("elevenlabs")
                except ImportError:
                    print("  ⚠️  elevenlabs_tts 모듈 없음 → 스킵")
            self._engine_order.append("edge")

        elif engine_pref == "elevenlabs":
            from elevenlabs_tts import ElevenLabsTTS
            self._elevenlabs = ElevenLabsTTS(
                self.config.elevenlabs_api_key,
                self.config.elevenlabs_voice_id,
            )
            self._engine_order = ["elevenlabs", "edge"]

        else:  # "edge"
            self._engine_order = ["edge"]

        print(f"  🔊 TTS 엔진 우선순위: {' → '.join(self._engine_order)}")

    async def generate(self, script_data: dict, work_dir: str) -> list[dict]:
        """v6.0: 멀티엔진 TTS 생성 — 문장별 최적 엔진 자동 선택"""
        print(f"\n{'='*60}")
        print(f"🔊 Stage 3: TTS 생성 (v6.0 멀티엔진: {' → '.join(self._engine_order)})")
        print(f"{'='*60}")

        script_lines = script_data.get("script", [])
        chunks = []
        current_ms = 0
        word_timings_all = []  # word-level 타이밍 전체 수집

        for idx, line in enumerate(script_lines):
            text = line["text"]
            emotion = line.get("emotion", "neutral")
            prosody = self.EMOTION_PROSODY.get(emotion, self.EMOTION_PROSODY["neutral"])

            # 문장 간 간격 (80ms + pause_ms)
            if idx > 0:
                pause_extra = line.get("pause_ms", 0)
                current_ms += 80 + pause_extra

            audio_path = os.path.join(work_dir, f"sent_{idx:03d}.mp3")

            try:
                # ★ 멀티엔진 디스패처
                result = await self._generate_sentence(
                    text, emotion, prosody, audio_path
                )
                duration_ms = result["duration_ms"]
                word_ts = result.get("word_timings", [])
                engine_used = result.get("engine", "unknown")

            except Exception as e:
                print(f"  ⚠️  TTS 전체 실패 [{idx}] {text}: {e}")
                duration_ms = 1500
                word_ts = []
                engine_used = "silence"
                # 무음 파일 생성
                subprocess.run([
                    FFMPEG_PATH, "-y", "-f", "lavfi",
                    "-i", f"anoisesrc=a=0.001:c=pink:r=44100:d=1.5",
                    "-c:a", "libmp3lame", "-b:a", "128k", audio_path,
                ], capture_output=True)

            # word_timings를 절대 타임라인으로 오프셋
            for wt in word_ts:
                wt["start_ms"] += current_ms
                wt["end_ms"] += current_ms
            word_timings_all.extend(word_ts)

            start_ms = current_ms
            end_ms = current_ms + duration_ms

            chunks.append({
                "index": idx,
                "text": text,
                "emotion": emotion,
                "highlight": line.get("highlight", False),
                "scene_hint": line.get("scene_hint", ""),
                "important_words": line.get("important_words", []),
                "image_prompt": line.get("image_prompt", ""),
                "audio_file": audio_path,
                "batch_idx": idx,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": duration_ms,
                "pause_ms": line.get("pause_ms", 0),
                "word_timings": word_ts,
                "sfx": re.sub(r'[\[\]]', '', str(line.get("sfx", ""))).strip(),
                "sfx_volume": line.get("sfx_volume", 0.7),
            })

            current_ms = end_ms

            emo = emotion[:3]
            marker = "⭐" if line.get("highlight") else "  "
            eng_tag = f"[{engine_used}]" if engine_used != "edge" else ""
            print(
                f"  🎙️ {marker}[{idx+1:02d}] "
                f"{eng_tag}[{emo}|{prosody['rate']}/{prosody['pitch']}] "
                f"{text} ({duration_ms}ms)"
            )

        # word_timings.json 저장
        if word_timings_all:
            timings_path = os.path.join(work_dir, "word_timings.json")
            with open(timings_path, "w", encoding="utf-8") as f:
                json.dump(word_timings_all, f, ensure_ascii=False, indent=2)
            print(f"  📝 Word timings 저장: {len(word_timings_all)}개 단어")

        total = current_ms / 1000
        print(f"\n  ✅ TTS 완료: {len(chunks)}문장, {total:.1f}초")
        return chunks

    async def _generate_sentence(
        self, text: str, emotion: str, prosody: dict, audio_path: str
    ) -> dict:
        """v6.0: 엔진 우선순위 디스패처 — 인증 실패 엔진은 세션 내 자동 블랙리스트"""
        if not hasattr(self, "_dead_engines"):
            self._dead_engines = set()  # 세션 내 인증 실패 엔진 기억

        for engine_name in self._engine_order:
            # ★ 이미 인증 실패로 죽은 엔진은 스킵 (매 문장마다 재시도 낭비 방지)
            if engine_name in self._dead_engines:
                continue

            try:
                if engine_name == "elevenlabs" and self._elevenlabs:
                    result = await self._elevenlabs.generate_sentence(
                        text, emotion, audio_path
                    )
                    result["engine"] = "elevenlabs"
                    return result

                elif engine_name == "edge":
                    result = await self._generate_edge(text, prosody, audio_path)
                    result["engine"] = "edge"
                    return result

            except Exception as e:
                err_str = str(e)
                # 인증 실패(401) → 이 세션에서 해당 엔진 영구 비활성화
                if "인증 실패" in err_str or "401" in err_str:
                    self._dead_engines.add(engine_name)
                    print(f"    ❌ {engine_name} 인증 실패 → 세션 내 비활성화")
                else:
                    print(f"    ⚠️  {engine_name} 실패: {e}")
                continue

        # 전부 실패 시 에러 throw (상위에서 무음 생성)
        raise RuntimeError("모든 TTS 엔진 실패")

    async def _generate_edge(
        self, text: str, prosody: dict, audio_path: str
    ) -> dict:
        """기존 edge-tts 로직 (폴백용 보존)"""
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

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 100:
            raise ValueError("edge-tts 빈 오디오 파일")

        duration_ms = self._get_duration_ms(audio_path)
        return {
            "audio_file": audio_path,
            "duration_ms": duration_ms,
            "word_timings": [],
        }

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
            except (OSError, ValueError) as e:
                print(f"  ⚠️  ffprobe 측정 실패: {e}")

        # 2차: ffmpeg -i 로 duration 파싱 (ffprobe 없을 때)
        try:
            r = subprocess.run(
                [FFMPEG_PATH, "-i", path, "-f", "null", "-"],
                capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", r.stderr)
            if m:
                h, mi, s, cs = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                return (h * 3600 + mi * 60 + s) * 1000 + cs * 10
        except (OSError, ValueError) as e:
            print(f"  ⚠️  ffmpeg 측정 실패: {e}")

        return 2000


# ============================================================
# 🔊 Stage 3.5: SFX 효과음 시스템
# ============================================================
class SFXManager:
    """
    SFX(효과음) 관리자 — YouShorts v6.0
    ─ assets/sfx/mapping.json 기반 태그→파일 매핑
    ─ chunks에서 SFX 이벤트 추출 → FFmpeg amix 오버레이
    ─ ★ SFX 볼륨 하드 리미터: TTS 음성 대비 최대 60%
    """

    def __init__(self, base_dir: str = ""):
        """
        Args:
            base_dir: 프로젝트 루트 (assets/sfx/ 기준점)
        """
        if not base_dir:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.sfx_dir = os.path.join(base_dir, "assets", "sfx")
        self.mapping = self._load_mapping()

    def _load_mapping(self) -> dict:
        """mapping.json 로드 → {tag: {file, volume, category}}"""
        mapping_path = os.path.join(self.sfx_dir, "mapping.json")
        if not os.path.exists(mapping_path):
            print(f"  ⚠️  SFX mapping.json 없음: {mapping_path}")
            return {}
        try:
            with open(mapping_path, "r", encoding="utf-8") as f:
                import json as _json
                data = _json.load(f)
            # 파일 존재 확인
            valid = {}
            for tag, info in data.items():
                full_path = os.path.join(self.sfx_dir, info["file"])
                if os.path.exists(full_path):
                    info["_full_path"] = full_path
                    valid[tag] = info
                else:
                    print(f"  ⚠️  SFX 파일 없음 (스킵): {full_path}")
            print(f"  🔊 SFX 로드: {len(valid)}/{len(data)}개 태그 사용 가능")
            return valid
        except Exception as e:
            print(f"  ⚠️  SFX mapping.json 로드 실패: {e}")
            return {}

    def get_sfx_path(self, tag: str) -> str:
        """태그 → SFX 파일 경로 반환 (없으면 빈 문자열)"""
        info = self.mapping.get(tag, {})
        return info.get("_full_path", "")

    def get_default_volume(self, tag: str) -> float:
        """태그 → 기본 볼륨 반환 (mapping.json에 정의된 값)"""
        info = self.mapping.get(tag, {})
        return info.get("volume", 0.5)

    def collect_sfx_from_chunks(self, chunks: list[dict]) -> list[dict]:
        """chunks에서 SFX 이벤트 추출

        Returns:
            [{
                "start_ms": int,       # 해당 문장 시작 시점
                "sfx_path": str,       # SFX 파일 경로
                "volume": float,       # 최종 볼륨 (0.0~0.6 하드 리밋)
                "tag": str,            # 원본 태그
            }]
        """
        events = []
        for chunk in chunks:
            tag = chunk.get("sfx", "").strip()
            if not tag:
                continue

            # ★ [bracket] 포맷 안전 처리: "[thunder]" → "thunder"
            tag = re.sub(r'[\[\]]', '', tag).strip()
            if not tag:
                continue

            sfx_path = self.get_sfx_path(tag)
            if not sfx_path:
                print(f"    ⚠️  SFX 태그 '{tag}' 매핑 없음 (스킵)")
                continue

            # 볼륨 결정: chunk에 지정된 값 > mapping 기본값
            raw_volume = chunk.get("sfx_volume", self.get_default_volume(tag))

            # ★★★ 하드 리미터: SFX 볼륨은 TTS 대비 최대 60% ★★★
            # TTS voice weight = 1.0 기준, SFX는 0.6 이하로 강제
            clamped_volume = min(float(raw_volume), 0.6)
            clamped_volume = max(clamped_volume, 0.05)  # 최소값

            events.append({
                "start_ms": chunk.get("start_ms", 0),
                "sfx_path": sfx_path,
                "volume": clamped_volume,
                "tag": tag,
            })

        if events:
            print(f"  🔊 SFX 이벤트 {len(events)}개 추출 "
                  f"(볼륨 리밋: 최대 60%)")

        return events

    def mix_sfx_into_audio(
        self,
        voice_path: str,
        sfx_events: list[dict],
        output_path: str,
    ) -> bool:
        """SFX 이벤트를 voice 오디오에 오버레이 (FFmpeg)

        ★ 핵심 원칙:
        - TTS voice = weight 1.0 (기준)
        - 각 SFX = weight ≤ 0.6 (하드 리밋)
        - FFmpeg amix로 다중 SFX 동시 믹싱

        Args:
            voice_path: 마스터링된 voice 오디오 (BGM 덕킹 후)
            sfx_events: collect_sfx_from_chunks() 결과
            output_path: 최종 출력 경로

        Returns:
            True if success
        """
        if not sfx_events:
            return False

        if not os.path.exists(voice_path):
            print(f"  ⚠️  SFX 믹싱: voice 파일 없음")
            return False

        # SFX 5개 제한 (FFmpeg 필터 복잡도 관리)
        if len(sfx_events) > 5:
            print(f"  ⚠️  SFX {len(sfx_events)}개 → 5개로 제한")
            sfx_events = sfx_events[:5]

        try:
            # ── FFmpeg filter_complex 빌드 ──
            # [0:a] = voice (기준)
            # [1:a], [2:a], ... = SFX 파일들
            #
            # 각 SFX에 adelay + volume 적용 후 amix로 합침
            inputs = ["-i", os.path.abspath(voice_path)]
            filter_parts = []
            mix_inputs = ["[0:a]"]  # voice는 항상 첫 번째
            weights = ["1"]  # voice weight = 1.0

            for i, evt in enumerate(sfx_events):
                sfx_idx = i + 1  # FFmpeg 입력 인덱스 (0=voice)
                inputs.extend(["-i", os.path.abspath(evt["sfx_path"])])

                delay_ms = max(0, evt["start_ms"])
                vol = evt["volume"]  # 이미 0.6 이하로 클램핑됨

                # adelay로 시작 위치 조절 + volume 조절
                filter_parts.append(
                    f"[{sfx_idx}:a]adelay={delay_ms}|{delay_ms},"
                    f"volume={vol:.2f}[sfx{i}]"
                )
                mix_inputs.append(f"[sfx{i}]")
                weights.append("1")  # 개별 volume 이미 적용됨

            # amix로 최종 믹싱
            n_inputs = len(mix_inputs)
            weight_str = " ".join(weights)
            mix_label = "".join(mix_inputs)
            filter_parts.append(
                f"{mix_label}amix=inputs={n_inputs}:duration=first"
                f":weights={weight_str}:normalize=0"
            )

            filter_complex = ";".join(filter_parts)

            cmd = [
                FFMPEG_PATH, "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100",
                os.path.abspath(output_path),
            ]

            r = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30,
            )

            if r.returncode == 0 and os.path.exists(output_path):
                size = os.path.getsize(output_path)
                if size > 1000:
                    print(f"  ✅ SFX 오버레이 완료 ({len(sfx_events)}개, "
                          f"볼륨 ≤60%)")
                    return True

            print(f"  ⚠️  SFX 믹싱 FFmpeg 실패: {r.stderr[:200] if r.stderr else 'unknown'}")
            return False

        except subprocess.TimeoutExpired:
            print(f"  ⚠️  SFX 믹싱 타임아웃 (30초)")
            return False
        except Exception as e:
            print(f"  ⚠️  SFX 믹싱 오류: {e}")
            return False

    @property
    def available_tags(self) -> list[str]:
        """사용 가능한 SFX 태그 목록"""
        return list(self.mapping.keys())


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
                 screenshots: list[str], work_dir: str,
                 scene_videos: list[dict] = None,
                 ai_images: list[dict] = None) -> str:
        """
        v7.0: 웹툰형 쇼츠 — AI 이미지 + Ken Burns + 말풍선 자막
        (ai_images 없으면 v6.2 Satisfying Video 폴백)
        """
        scene_videos = scene_videos or []
        ai_images = ai_images or []

        # 웹툰 모드 vs 비디오 모드 분기
        has_images = any(img.get("image_path") for img in ai_images)
        if has_images:
            return self._assemble_webtoon(script_data, chunks, ai_images, work_dir)

        print(f"\n{'='*60}")
        print(f"🎬 Stage 4: 영상 조립 (v6.2 Satisfying Video 모드)")
        print(f"{'='*60}")

        # chunk_idx 자동 삽입 (자막 색상 번갈아 표시용)
        for ci, chunk in enumerate(chunks):
            chunk["chunk_idx"] = ci

        # Step 1: 오디오 합치기
        concat_audio = os.path.join(work_dir, "full_audio.mp3")
        self._concat_audio(chunks, concat_audio, work_dir)

        total_ms = max(c["end_ms"] for c in chunks) + 500
        total_sec = total_ms / 1000

        # Step 2: FFmpeg 직접 조립 (프레임 렌더링 제거 → 속도 대폭 향상)
        # 배경 비디오 경로 찾기
        bg_video = None
        for sv in scene_videos:
            vp = sv.get("video_path", "")
            if vp and os.path.exists(vp):
                bg_video = vp
                break

        if not bg_video:
            # 폴백: 검정 배경 생성
            print("  ⚠️  Satisfying 배경 없음 → 검정 배경 폴백")
            bg_video = os.path.join(work_dir, "black_bg.mp4")
            cmd_bg = [
                FFMPEG_PATH, "-y",
                "-f", "lavfi", "-i",
                f"color=c=black:s={self.w}x{self.h}:r={self.config.fps}:d={total_sec + 1}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                os.path.abspath(bg_video),
            ]
            subprocess.run(cmd_bg, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)

        # Step 3: 배경 루프 + Mute + Dimming → 중간 파일
        print(f"  🔄 배경 비디오 루프 + Dimming 처리 중...")
        looped_bg = os.path.join(work_dir, "looped_bg.mp4")

        # FFmpeg: stream_loop으로 루프 + eq=brightness로 어둡게 + 약한 blur
        cmd_loop = [
            FFMPEG_PATH, "-y",
            "-stream_loop", "-1",  # 무한 루프
            "-i", os.path.abspath(bg_video),
            "-t", f"{total_sec + 0.5}",  # 전체 길이
            "-vf", (
                f"scale={self.w}:{self.h}:force_original_aspect_ratio=increase,"
                f"crop={self.w}:{self.h},"
                f"eq=brightness=-0.12:contrast=1.1,"
                f"gblur=sigma=1.5"
            ),
            "-an",  # 오디오 Mute
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", str(self.config.fps),
            os.path.abspath(looped_bg),
        ]

        result = subprocess.run(cmd_loop, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
        if result.returncode != 0:
            print(f"  ⚠️  배경 루프 실패: {result.stderr[-300:] if result.stderr else ''}")
            # 폴백: 검정 배경
            cmd_bg = [
                FFMPEG_PATH, "-y",
                "-f", "lavfi", "-i",
                f"color=c=black:s={self.w}x{self.h}:r={self.config.fps}:d={total_sec + 1}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                os.path.abspath(looped_bg),
            ]
            subprocess.run(cmd_bg, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)

        print(f"  ✅ 배경 루프 완료!")

        # Step 4: ASS 자막 파일 생성 (FFmpeg drawtext 대신 Pillow 프레임 렌더링)
        # → Pillow 렌더링이 폰트 제어에 더 유리
        frames_dir = os.path.join(work_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        # 배경 비디오에서 프레임 추출
        print(f"  🎞️  배경 프레임 추출 중...")
        bg_frames_dir = os.path.join(work_dir, "_bg_frames")
        os.makedirs(bg_frames_dir, exist_ok=True)

        bg_pattern = os.path.join(bg_frames_dir, "bg_%06d.jpg")
        cmd_extract = [
            FFMPEG_PATH, "-y",
            "-i", os.path.abspath(looped_bg),
            "-q:v", "2",
            os.path.abspath(bg_pattern),
        ]
        subprocess.run(cmd_extract, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=300)

        # 추출된 배경 프레임 로드
        bg_frame_files = sorted([f for f in os.listdir(bg_frames_dir) if f.endswith(".jpg")])
        total_frames = len(bg_frame_files)
        if total_frames == 0:
            total_frames = int(total_sec * self.config.fps)

        print(f"  🖼️  {total_frames}프레임 자막 렌더링 중 (Satisfying 스타일)...")

        # v6.0 전용 폰트 로드
        shorts_font = FontManager.get_shorts_font(int(self.config.font_size * 1.3))
        shorts_font_large = FontManager.get_shorts_font(int(self.config.font_size * 1.5))

        # v9.0: 배경 프레임 캐시 (같은 이미지 재로드 방지)
        _bg_cache = {}

        def _load_bg_frame(idx):
            if idx < len(bg_frame_files):
                bg_path = os.path.join(bg_frames_dir, bg_frame_files[idx])
                if bg_path not in _bg_cache:
                    try:
                        img = Image.open(bg_path).convert("RGB")
                        if img.size != (self.w, self.h):
                            img = img.resize((self.w, self.h), Image.LANCZOS)
                        _bg_cache[bg_path] = img
                    except Exception:
                        _bg_cache[bg_path] = None
                cached = _bg_cache.get(bg_path)
                return cached.copy() if cached else self._create_cinematic_gradient("neutral")
            return self._create_cinematic_gradient("neutral")

        # 배경 캐시 크기 제한 (메모리 절약 — 최근 60프레임만)
        cache_limit = self.config.fps * 2

        for frame_idx in range(total_frames):
            current_time_ms = (frame_idx / self.config.fps) * 1000

            # 배경 프레임 로드 (캐시 활용)
            frame = _load_bg_frame(frame_idx)

            # 캐시 크기 제한
            if len(_bg_cache) > cache_limit:
                oldest_key = next(iter(_bg_cache))
                del _bg_cache[oldest_key]

            # 현재 대사 찾기
            active_chunk = None
            for ci, chunk in enumerate(chunks):
                if chunk["start_ms"] <= current_time_ms <= chunk["end_ms"]:
                    active_chunk = chunk
                    break

            # v9.0 현대적 자막 렌더링
            if active_chunk:
                frame = self._render_subtitle(frame, active_chunk, current_time_ms)

            # 아웃트로: 마지막 2초
            remaining_sec = (total_ms - current_time_ms) / 1000
            if 0 <= remaining_sec <= 2.0:
                frame = self._render_cta_outro(frame, remaining_sec)

            # 저장 (JPEG quality 85 → 파일 크기 20% 감소, 시각 차이 무)
            frame_path = os.path.join(frames_dir, f"frame_{frame_idx:06d}.jpg")
            frame.save(frame_path, quality=85)

            # 진행률 (10초마다)
            if frame_idx % (self.config.fps * 10) == 0:
                pct = (frame_idx / max(1, total_frames)) * 100
                print(f"  📊 렌더링 진행: {pct:.0f}% ({frame_idx}/{total_frames})")

        print(f"  ✅ 프레임 렌더링 완료!")

        # Step 5: FFmpeg 최종 인코딩
        title_safe = re.sub(r'[^\w가-힣]', '_',
                            script_data.get("title", "shorts"))[:20]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"shorts_{title_safe}_{timestamp}.mp4"
        output_path = os.path.join(self.config.output_dir, output_filename)

        abs_frames_pattern = os.path.abspath(
            os.path.join(frames_dir, "frame_%06d.jpg")
        )
        abs_audio = os.path.abspath(concat_audio)
        abs_output = os.path.abspath(output_path)

        print(f"  🔧 FFmpeg CRF 인코딩 중...")

        cmd = [
            FFMPEG_PATH, "-y",
            "-framerate", str(self.config.fps),
            "-i", abs_frames_pattern,
            "-i", abs_audio,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-profile:v", "high",
            "-level", "4.1",
            "-maxrate", "8000k",
            "-bufsize", "8000k",
            "-c:a", "aac",
            "-b:a", "256k",
            "-ar", "44100",
            "-pix_fmt", "yuv420p",
            "-shortest",
            "-movflags", "+faststart",
            "-metadata", f"title={script_data.get('title', 'Shorts')}",
            abs_output,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")

        if result.returncode != 0:
            print(f"  ⚠️  FFmpeg 에러: {result.stderr[-500:] if result.stderr else 'unknown'}")
            print(f"  🔄 간소화 버전으로 재시도...")
            return self._assemble_simple_fallback(
                concat_audio, total_sec, chunks, output_path, work_dir
            )

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  ✅ 영상 완성! {output_path} ({size_mb:.1f}MB)")

        # 임시 파일 정리
        shutil.rmtree(frames_dir, ignore_errors=True)
        shutil.rmtree(bg_frames_dir, ignore_errors=True)
        if os.path.exists(looped_bg):
            os.remove(looped_bg)

        return output_path

    def _create_cinematic_gradient(self, emotion: str = "neutral") -> Image.Image:
        """v9.0: 감정별 3색 메시 그라데이션 배경 (비디오 없을 때 폴백)

        기존 2색 단순 그라데이션 → 3색 메시로 세련된 느낌.
        상단(c1) → 중간(c2) → 하단(c3) 자연스러운 전환.
        """
        # 3색 메시 그라데이션 (상단, 중간, 하단)
        EMOTION_COLORS_3 = {
            "neutral":  [(15, 15, 30), (20, 18, 35), (28, 22, 38)],
            "shocked":  [(45, 8, 15), (30, 10, 25), (15, 12, 35)],
            "excited":  [(50, 30, 5),  (40, 20, 25), (20, 15, 40)],
            "tension":  [(8, 10, 35),  (20, 8, 25),  (35, 10, 15)],
            "warm":     [(40, 25, 10), (30, 18, 20), (18, 15, 30)],
            "sad":      [(10, 15, 35), (12, 12, 30), (18, 10, 25)],
            "funny":    [(35, 30, 8),  (25, 22, 20), (15, 18, 35)],
            "serious":  [(10, 10, 18), (15, 12, 22), (22, 18, 28)],
            "angry":    [(50, 5, 5),   (35, 8, 18),  (15, 10, 30)],
            "whisper":  [(12, 12, 22), (10, 15, 28), (8, 10, 20)],
            "surprise": [(40, 15, 10), (25, 12, 28), (12, 15, 38)],
            "relief":   [(15, 25, 20), (18, 20, 28), (22, 18, 35)],
        }
        colors = EMOTION_COLORS_3.get(emotion, EMOTION_COLORS_3["neutral"])
        c1, c2, c3 = colors

        img = Image.new("RGB", (self.w, self.h))
        draw = ImageDraw.Draw(img)
        mid_point = self.h * 0.45  # 상단~중간 전환점

        for y in range(self.h):
            if y < mid_point:
                # 상단 → 중간
                ratio = y / mid_point
                r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
                g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
                b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
            else:
                # 중간 → 하단
                ratio = (y - mid_point) / (self.h - mid_point)
                r = int(c2[0] * (1 - ratio) + c3[0] * ratio)
                g = int(c2[1] * (1 - ratio) + c3[1] * ratio)
                b = int(c2[2] * (1 - ratio) + c3[2] * ratio)
            draw.line([(0, y), (self.w, y)], fill=(r, g, b))
        return img

    def _generate_ai_image(self, scene_hint: str, work_dir: str,
                            idx: int, context_text: str = "") -> Optional[str]:
        """
        v5.0: Pillow 그라데이션 배경 (Imagen 제거 — API 비용 0원)
        scene_hint에 따라 분위기별 색상 그라데이션 생성
        """
        try:
            w, h = self.config.width, self.config.height

            # scene_hint 키워드로 색상 매핑
            hint_lower = scene_hint.lower() if scene_hint else ""
            if any(k in hint_lower for k in ("공포", "horror", "dark", "소름", "미스터리")):
                c1, c2 = (15, 5, 25), (40, 10, 10)
            elif any(k in hint_lower for k in ("충격", "shock", "surprise", "반전")):
                c1, c2 = (20, 10, 5), (60, 20, 10)
            elif any(k in hint_lower for k in ("웃", "funny", "comedy", "ㅋㅋ", "밈")):
                c1, c2 = (10, 20, 30), (30, 50, 20)
            elif any(k in hint_lower for k in ("슬", "sad", "감동", "눈물")):
                c1, c2 = (10, 15, 35), (20, 20, 50)
            else:
                c1, c2 = (20, 22, 30), (35, 25, 20)

            img = Image.new("RGB", (w, h))
            for y in range(h):
                ratio = y / h
                r = int(c1[0] + (c2[0] - c1[0]) * ratio)
                g = int(c1[1] + (c2[1] - c1[1]) * ratio)
                b = int(c1[2] + (c2[2] - c1[2]) * ratio)
                for x in range(w):
                    img.putpixel((x, y), (r, g, b))

            path = os.path.join(work_dir, f"ai_bg_{idx:03d}.png")
            img.save(path, quality=85)
            print(f"    🎨 그라데이션 배경 생성: {scene_hint[:40]}...")
            return path
        except Exception as e:
            print(f"    ⚠️  배경 생성 실패: {e}")
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

        # ── 그라데이션 배경 (highlight 장면, 최대 3장) ──
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
                    except Exception as e:
                        print(f"    ⚠️  AI 이미지 처리 실패: {e}")

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
        """v9.0: CTA 개선 — 구독 유도 제거, 댓글 아이콘 + 열린 질문 강조

        숏츠에서 "좋아요/구독" 직접 유도는 역효과.
        대신 마지막 열린 질문을 크게 표시 + 댓글 아이콘으로 자연스럽게 유도.
        """
        overlay = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 페이드인 (0→1 over 0.4초)
        alpha = min(1.0, (2.0 - remaining_sec) / 0.4)

        # 댓글 아이콘 (💬) + "댓글로 알려줘" 작은 텍스트
        font_icon = FontManager.get_font(40, bold=True)
        font_hint = FontManager.get_font(24, bold=False)

        # 살짝 바운스 (1초 주기)
        bounce = 1.0 + 0.05 * math.sin((2.0 - remaining_sec) * 3.14 * 2)

        # 댓글 힌트 위치 (하단 88%)
        hint_y = int(self.h * 0.88)
        a = int(200 * alpha)

        # "💬 댓글로 알려줘" 텍스트
        hint_text = "댓글로 알려줘"
        bbox = draw.textbbox((0, 0), hint_text, font=font_hint)
        tw = bbox[2] - bbox[0]
        tx = (self.w - tw) // 2

        # 반투명 배경 필 (힌트 텍스트 주변만)
        pad = 16
        draw.rounded_rectangle(
            [(tx - pad, hint_y - pad // 2), (tx + tw + pad, hint_y + (bbox[3] - bbox[1]) + pad // 2)],
            radius=12, fill=(0, 0, 0, int(100 * alpha))
        )

        draw.text((tx, hint_y), hint_text, font=font_hint,
                   fill=(255, 255, 255, a),
                   stroke_width=2, stroke_fill=(0, 0, 0, a))

        frame = frame.convert("RGBA")
        return Image.alpha_composite(frame, overlay).convert("RGB")

    def _render_subtitle(self, frame: Image.Image, chunk: dict,
                          current_ms: float) -> Image.Image:
        """
        v10.0 자막 개선
        ─ 폰트: 기존 대비 1.4배 크게
        ─ 반투명 검정 배경박스 (opacity 0.6)
        ─ important_words: 노란색(#FFD700) + glow
        ─ highlight: 노란색(#FFD60A) + 스케일 1.15x
        ─ 위치: 화면 하단 15% 고정 (85%)
        ─ 줄바꿈: 단어 경계 기준
        ─ 애니메이션: cubic-bezier 바운스 등장
        """
        text = chunk["text"]
        start_ms = chunk["start_ms"]
        end_ms = chunk["end_ms"]
        elapsed = current_ms - start_ms
        remaining = end_ms - current_ms
        is_highlight = chunk.get("highlight", False)
        important_words = chunk.get("important_words", [])

        # ── 페이드 인/아웃 ──
        alpha = 1.0
        fade_in_ms = 120
        fade_out_ms = 80
        if elapsed < fade_in_ms:
            alpha = elapsed / fade_in_ms
        elif remaining < fade_out_ms:
            alpha = remaining / fade_out_ms
        alpha = max(0.0, min(1.0, alpha))

        # ── 폰트 (v10.0: 1.4배 크기 증가) ──
        base_font_size = int(self.config.font_size * 1.96)  # 56 * 1.96 ≈ 110px
        # 첫 자막 1.6배 (오프닝 임팩트)
        chunk_idx = chunk.get("chunk_idx", -1)
        if chunk_idx == 0:
            base_font_size = int(base_font_size * 1.6)
        if is_highlight:
            base_font_size = int(base_font_size * 1.15)
        font = FontManager.get_shorts_font(base_font_size)
        font_big = FontManager.get_shorts_font(int(base_font_size * 1.15))
        stroke_px = 4

        # ── 색상 ──
        if is_highlight:
            text_color = (255, 214, 10)       # 노란색 (#FFD60A)
        else:
            text_color = (255, 255, 255)       # 흰색
        imp_color = (255, 215, 0)              # 노란색 (#FFD700) — important_words

        has_kinetic = bool(important_words)

        # ── 줄바꿈 (단어 경계 기준) ──
        max_chars = 14
        lines = self._word_boundary_wrap(text, max_chars)

        # ── 측정 ──
        draw_temp = ImageDraw.Draw(frame)
        line_heights, line_widths = [], []
        for line in lines:
            bbox = draw_temp.textbbox((0, 0), line, font=font, stroke_width=stroke_px)
            line_widths.append(bbox[2] - bbox[0])
            line_heights.append(bbox[3] - bbox[1])

        line_gap = 10
        total_h = sum(line_heights) + (len(lines) - 1) * line_gap

        # ── 위치: 하단 85% (화면 하단 15% 고정) ──
        text_block_y = int(self.h * 0.85) - total_h

        # ── 등장 애니메이션: cubic-bezier(0.34, 1.56, 0.64, 1) 바운스 ──
        if elapsed < fade_in_ms:
            t = elapsed / fade_in_ms
            # overshoot easing: 살짝 위로 갔다 내려오는 바운스
            ease_t = 1 + 2.56 * (t - 1) ** 3 + 1.56 * (t - 1) ** 2
            ease_t = max(0.0, min(1.2, ease_t))
            slide_offset = int(40 * (1 - ease_t))
            text_block_y += slide_offset

        # ── 강조 단어 팝 효과 ──
        bounce_scale = 1.0
        if has_kinetic and 80 < elapsed < 400:
            bt = (elapsed - 80) / 320
            bounce_scale = 1.0 + 0.12 * math.sin(bt * math.pi)

        # ── 오버레이 렌더링 ──
        overlay = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        a = int(255 * alpha)
        shadow_a = int(150 * alpha)

        # ── 반투명 검정 배경박스 (opacity 0.6) ──
        max_line_w = max(line_widths) if line_widths else 0
        pad_x, pad_y = 30, 16
        box_x1 = (self.w - max_line_w) // 2 - pad_x
        box_y1 = text_block_y - pad_y
        box_x2 = (self.w + max_line_w) // 2 + pad_x
        box_y2 = text_block_y + total_h + pad_y
        box_alpha = int(153 * alpha)  # 0.6 * 255 = 153
        draw.rounded_rectangle(
            [box_x1, box_y1, box_x2, box_y2],
            radius=12, fill=(0, 0, 0, box_alpha),
        )

        # ── 텍스트 렌더링 ──
        text_y = text_block_y
        for i, line in enumerate(lines):
            segments = self._segment_important(line, important_words)
            total_seg_w = 0
            for seg_text, is_imp in segments:
                seg_font = font_big if is_imp else font
                bbox = draw_temp.textbbox((0, 0), seg_text, font=seg_font, stroke_width=stroke_px)
                total_seg_w += bbox[2] - bbox[0]

            cursor_x = (self.w - total_seg_w) // 2

            for seg_text, is_imp in segments:
                if is_imp and has_kinetic:
                    seg_font = font_big
                    seg_color = imp_color
                    y_offset = -int((bounce_scale - 1.0) * 15)
                else:
                    seg_font = font
                    seg_color = text_color
                    y_offset = 0

                seg_bbox = draw_temp.textbbox((0, 0), seg_text, font=seg_font, stroke_width=stroke_px)
                seg_w = seg_bbox[2] - seg_bbox[0]
                seg_y = text_y + y_offset

                # 1) 드롭 섀도우 (4px offset, 살짝 블러 느낌)
                draw.text((cursor_x + 3, seg_y + 3), seg_text, font=seg_font,
                           fill=(0, 0, 0, shadow_a),
                           stroke_width=2, stroke_fill=(0, 0, 0, shadow_a))

                # 2) 메인 텍스트 + 두꺼운 검정 외곽선
                draw.text((cursor_x, seg_y), seg_text, font=seg_font,
                           fill=(*seg_color, a),
                           stroke_width=stroke_px,
                           stroke_fill=(0, 0, 0, int(240 * alpha)))

                # 3) important_words glow 효과 (노란 글자에 추가 강조)
                if is_imp and has_kinetic:
                    glow_a = int(60 * alpha * bounce_scale)
                    draw.text((cursor_x, seg_y), seg_text, font=seg_font,
                               fill=(*imp_color, glow_a),
                               stroke_width=stroke_px + 2,
                               stroke_fill=(*imp_color, int(glow_a * 0.3)))

                cursor_x += seg_w

            text_y += line_heights[i] + line_gap

        frame = frame.convert("RGBA")
        frame = Image.alpha_composite(frame, overlay)
        return frame.convert("RGB")

    def _word_boundary_wrap(self, text: str, max_chars: int) -> list[str]:
        """단어 경계 기준 줄바꿈 (글자수 기준보다 자연스러움)"""
        if len(text) <= max_chars:
            return [text]

        # 한국어 조사/어미 경계에서 줄바꿈 시도
        break_chars = " .,!?은는이가을를에서도로의와과"
        mid = len(text) // 2
        best_break = mid

        for offset in range(min(7, mid)):
            for pos in [mid + offset, mid - offset]:
                if 0 < pos < len(text) and text[pos] in break_chars:
                    best_break = pos + (1 if text[pos] != " " else 0)
                    break
            else:
                continue
            break

        result = [text[:best_break].strip(), text[best_break:].strip()]
        # 3줄 이상 방지
        final = []
        for line in result:
            if len(line) > max_chars + 5:
                m = len(line) // 2
                final.append(line[:m].strip())
                final.append(line[m:].strip())
            else:
                final.append(line)
        return final[:3]

    def _assemble_webtoon(self, script_data: dict, chunks: list[dict],
                           ai_images: list[dict], work_dir: str) -> str:
        """
        v7.0 웹툰형 쇼츠 조립
        ─ 각 장면마다 AI 이미지 + Ken Burns 줌인/아웃
        ─ 말풍선 스타일 자막 (하단 30%)
        ─ 장면 전환: 페이드
        """
        print(f"\n{'='*60}")
        print(f"🎬 Stage 4: 영상 조립 (v7.0 웹툰 모드)")
        print(f"{'='*60}")

        # chunk_idx 삽입
        for ci, chunk in enumerate(chunks):
            chunk["chunk_idx"] = ci

        # Step 1: 오디오
        concat_audio = os.path.join(work_dir, "full_audio.mp3")
        self._concat_audio(chunks, concat_audio, work_dir)

        total_ms = max(c["end_ms"] for c in chunks) + 500
        total_sec = total_ms / 1000
        total_frames = int(total_sec * self.config.fps)

        # Step 2: 이미지 → 장면 타임라인 매핑
        # ai_images: [{"chunk_idx": 0, "end_idx": 2, "image_path": "..."}]
        scene_timeline = []  # [(start_ms, end_ms, image_path)]
        for img_info in ai_images:
            sidx = img_info["chunk_idx"]
            eidx = img_info["end_idx"]
            img_path = img_info.get("image_path")
            if sidx < len(chunks) and eidx < len(chunks):
                s_ms = chunks[sidx]["start_ms"]
                e_ms = chunks[eidx]["end_ms"]
                scene_timeline.append((s_ms, e_ms, img_path))
        # 빈 구간 처리: 시작 전, 끝 후
        if not scene_timeline:
            scene_timeline = [(0, total_ms, None)]

        # Step 3: 이미지 로드 + Ken Burns 프레임 렌더링
        print(f"  🖼️  {total_frames}프레임 렌더링 중 (웹툰 + Ken Burns)...")

        frames_dir = os.path.join(work_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        # 이미지 캐시
        img_cache = {}
        for st in scene_timeline:
            ipath = st[2]
            if ipath and os.path.exists(ipath) and ipath not in img_cache:
                try:
                    img = Image.open(ipath).convert("RGB")
                    img = img.resize((self.w, self.h), Image.LANCZOS)
                    img_cache[ipath] = img
                except Exception:
                    img_cache[ipath] = None

        # 장면 전환 시간 계산 (장면별 highlight/emotion 매핑)
        _scene_highlights = {}
        for img_info in ai_images:
            sidx = img_info["chunk_idx"]
            if sidx < len(chunks):
                _scene_highlights[img_info.get("image_path")] = chunks[sidx].get("highlight", False)

        prev_scene_idx = -1
        prev_frame = None

        for frame_idx in range(total_frames):
            current_ms = (frame_idx / self.config.fps) * 1000

            # 현재 장면 찾기
            current_img_path = None
            scene_start_ms = 0
            scene_end_ms = total_ms
            scene_idx = 0
            for si, (s_ms, e_ms, ipath) in enumerate(scene_timeline):
                if s_ms <= current_ms <= e_ms:
                    current_img_path = ipath
                    scene_start_ms = s_ms
                    scene_end_ms = e_ms
                    scene_idx = si
                    break

            # 배경 이미지 로드
            base_img = img_cache.get(current_img_path)
            if base_img:
                frame = base_img.copy()
            else:
                frame = self._create_cinematic_gradient(
                    self._get_current_emotion(chunks, current_ms))

            # Ken Burns 효과 (v9.0 감정 연동)
            cur_emotion = self._get_current_emotion(chunks, current_ms)
            frame = self._apply_ken_burns(frame, current_ms,
                                           scene_start_ms, scene_end_ms, scene_idx,
                                           emotion=cur_emotion)

            # ★ 장면 전환 효과 (crossfade / 흑백→컬러 / 빠른컷)
            if scene_idx != prev_scene_idx and prev_scene_idx >= 0 and prev_frame:
                elapsed_in_scene = current_ms - scene_start_ms
                is_highlight = _scene_highlights.get(current_img_path, False)

                if cur_emotion == "shocked":
                    # shocked: 빠른 컷 0.1초 (3프레임)
                    trans_ms = 100
                elif is_highlight:
                    # highlight: 흑백→컬러 전환 0.3초
                    trans_ms = 300
                else:
                    # 기본: crossfade 0.3초
                    trans_ms = 300

                if elapsed_in_scene < trans_ms:
                    blend_ratio = elapsed_in_scene / trans_ms
                    if is_highlight and cur_emotion != "shocked":
                        # 흑백→컬러: 이전 프레임을 흑백으로 변환 후 블렌드
                        from PIL import ImageOps
                        gray_prev = ImageOps.grayscale(prev_frame).convert("RGB")
                        frame = Image.blend(gray_prev, frame, blend_ratio)
                    else:
                        # 일반 crossfade
                        frame = Image.blend(prev_frame, frame, blend_ratio)

            if scene_idx != prev_scene_idx:
                prev_scene_idx = scene_idx
            prev_frame = frame.copy()

            # Dimming (이미지 위 자막 가독성)
            overlay_dim = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 50))
            frame = frame.convert("RGBA")
            frame = Image.alpha_composite(frame, overlay_dim).convert("RGB")

            # 현재 대사 찾기
            active_chunk = None
            for chunk in chunks:
                if chunk["start_ms"] <= current_ms <= chunk["end_ms"]:
                    active_chunk = chunk
                    break

            # 말풍선 자막 (하단 30%)
            if active_chunk:
                frame = self._render_balloon_subtitle(frame, active_chunk, current_ms)

            # 아웃트로
            remaining_sec = (total_ms - current_ms) / 1000
            if 0 <= remaining_sec <= 2.0:
                frame = self._render_cta_outro(frame, remaining_sec)

            # ★ 엔딩 페이드아웃: 마지막 1.5초 영상 fade to black
            if remaining_sec <= 1.5 and remaining_sec > 0:
                fade_alpha = int(255 * (1.0 - remaining_sec / 1.5))
                fade_overlay = Image.new("RGBA", (self.w, self.h), (0, 0, 0, fade_alpha))
                frame = frame.convert("RGBA")
                frame = Image.alpha_composite(frame, fade_overlay).convert("RGB")

            # 저장
            frame_path = os.path.join(frames_dir, f"frame_{frame_idx:06d}.jpg")
            frame.save(frame_path, quality=92)

            if frame_idx % (self.config.fps * 10) == 0:
                pct = (frame_idx / max(1, total_frames)) * 100
                print(f"  📊 렌더링 진행: {pct:.0f}% ({frame_idx}/{total_frames})")

        print(f"  ✅ 프레임 렌더링 완료!")

        # Step 4: FFmpeg 인코딩
        title_safe = re.sub(r'[^\w가-힣]', '_',
                            script_data.get("title", "shorts"))[:20]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"shorts_{title_safe}_{timestamp}.mp4"
        output_path = os.path.join(self.config.output_dir, output_filename)

        abs_frames = os.path.abspath(os.path.join(frames_dir, "frame_%06d.jpg"))
        abs_audio = os.path.abspath(concat_audio)
        abs_output = os.path.abspath(output_path)

        print(f"  🔧 FFmpeg CRF 인코딩 중...")
        cmd = [
            FFMPEG_PATH, "-y",
            "-framerate", str(self.config.fps),
            "-i", abs_frames,
            "-i", abs_audio,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-profile:v", "high", "-level", "4.1",
            "-maxrate", "8000k", "-bufsize", "8000k",
            "-c:a", "aac", "-b:a", "256k", "-ar", "44100",
            "-af", f"afade=t=out:st={max(0, total_sec - 1.5):.1f}:d=1.5",
            "-pix_fmt", "yuv420p", "-shortest",
            "-movflags", "+faststart",
            "-metadata", f"title={script_data.get('title', 'Shorts')}",
            abs_output,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")

        if result.returncode != 0:
            print(f"  ⚠️  FFmpeg 에러 → Satisfying 폴백")
            return self._assemble_simple_fallback(
                concat_audio, total_sec, chunks, output_path, work_dir)

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  ✅ 영상 완성! {output_path} ({size_mb:.1f}MB)")

        shutil.rmtree(frames_dir, ignore_errors=True)
        return output_path

    # ── v9.0 감정 연동 Ken Burns 모션 프로필 ──
    _MOTION_PROFILES = {
        "excited":  {"scale_start": 1.0,  "scale_end": 1.20, "pan_speed": 1.2},
        "shocked":  {"scale_start": 1.18, "scale_end": 1.0,  "pan_speed": 2.0},  # 빠른 줌아웃
        "sad":      {"scale_start": 1.08, "scale_end": 1.0,  "pan_speed": 0.4},  # 느린
        "funny":    {"scale_start": 1.0,  "scale_end": 1.10, "pan_speed": 1.0},
        "tension":  {"scale_start": 1.0,  "scale_end": 1.05, "pan_speed": 0.6},  # 미세 줌
        "angry":    {"scale_start": 1.20, "scale_end": 1.0,  "pan_speed": 2.5},  # 공격적
        "warm":     {"scale_start": 1.0,  "scale_end": 1.08, "pan_speed": 0.5},
        "whisper":  {"scale_start": 1.10, "scale_end": 1.05, "pan_speed": 0.3},
        "surprise": {"scale_start": 1.15, "scale_end": 1.0,  "pan_speed": 1.8},
        "neutral":  {"scale_start": 1.0,  "scale_end": 1.06, "pan_speed": 0.7},
        "serious":  {"scale_start": 1.0,  "scale_end": 1.04, "pan_speed": 0.5},
        "relief":   {"scale_start": 1.08, "scale_end": 1.0,  "pan_speed": 0.8},
    }

    def _apply_ken_burns(self, frame: Image.Image, current_ms: float,
                          scene_start: float, scene_end: float,
                          scene_idx: int, emotion: str = "neutral") -> Image.Image:
        """v10.0 Ken Burns: 감정 연동 줌 + 오프닝 강화"""
        scene_duration = max(scene_end - scene_start, 1)
        progress = (current_ms - scene_start) / scene_duration
        progress = max(0.0, min(1.0, progress))

        # ★ 오프닝 강화: 첫 장면 2초 줌아웃→줌인 (1.3x → 1.0x → 1.1x)
        if scene_idx == 0 and current_ms < 2000:
            t = current_ms / 2000
            # ease-in-out: 줌아웃(1.3x) → 줌인(1.05x)
            s_start = 1.30
            s_end = 1.05
            eased = 1 - (1 - t) ** 3  # ease-out cubic
            scale = s_start + (s_end - s_start) * eased
        else:
            # 감정별 모션 프로필
            profile = self._MOTION_PROFILES.get(emotion, self._MOTION_PROFILES["neutral"])
            s_start = profile["scale_start"]
            s_end = profile["scale_end"]
            eased = 1 - (1 - progress) ** 2
            scale = s_start + (s_end - s_start) * eased

        w, h = frame.size
        new_w = int(w * scale)
        new_h = int(h * scale)

        frame_scaled = frame.resize((new_w, new_h), Image.LANCZOS)

        # pan 방향 (scene_idx 기반 결정 — 랜덤 느낌이지만 재현 가능)
        pan_directions = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1)]
        pan_dx, pan_dy = pan_directions[scene_idx % len(pan_directions)]

        max_pan = int((new_w - w) * 0.4 * progress)
        left = (new_w - w) // 2 + pan_dx * max_pan
        top = (new_h - h) // 2 + pan_dy * max_pan

        # 경계 클램프
        left = max(0, min(new_w - w, left))
        top = max(0, min(new_h - h, top))

        return frame_scaled.crop((left, top, left + w, top + h))

    def _render_balloon_subtitle(self, frame: Image.Image, chunk: dict,
                                   current_ms: float) -> Image.Image:
        """v9.0 웹툰 모드 자막 — _render_subtitle과 동일 스타일 통일"""
        # 웹툰 모드도 동일한 현대적 자막 사용
        return self._render_subtitle(frame, chunk, current_ms)

    def _segment_important(self, line: str, important_words: list) -> list:
        """라인을 (text, is_important) 세그먼트로 분리"""
        if not important_words:
            return [(line, False)]
        segments = []
        remaining = line
        while remaining:
            earliest_pos = len(remaining)
            earliest_word = None
            for iw in important_words:
                pos = remaining.find(iw)
                if pos != -1 and pos < earliest_pos:
                    earliest_pos = pos
                    earliest_word = iw
            if earliest_word is None:
                segments.append((remaining, False))
                break
            if earliest_pos > 0:
                segments.append((remaining[:earliest_pos], False))
            segments.append((earliest_word, True))
            remaining = remaining[earliest_pos + len(earliest_word):]
        return segments if segments else [(line, False)]

    def _get_current_emotion(self, chunks: list, current_ms: float) -> str:
        """현재 시간의 감정 반환"""
        for c in chunks:
            if c["start_ms"] <= current_ms <= c["end_ms"]:
                return c.get("emotion", "neutral")
        return "neutral"

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
        v6.0: pydub Silence Trim + Cross-fade 믹싱
        ─ 각 문장 앞뒤 무음 자동 제거
        ─ 100ms 크로스페이드로 숨 쉴 틈 없이 연결 (틱톡 스타일)
        ─ Voice EQ + BGM + Sidechain Ducking -20dB
        """
        # ── Step 1: pydub 크로스페이드 concat ──
        raw_voice = os.path.join(work_dir, "voice_raw.mp3")

        # ── Step 1: FFmpeg로 silence trim + crossfade concat ──
        # pydub의 ffprobe 의존성 문제 회피 → FFmpeg 직접 처리
        print(f"  🔗 FFmpeg 크로스페이드 믹싱 ({len(chunks)}문장)...")

        try:
            # 각 문장 앞뒤 무음 제거 → trimmed 파일 생성
            trimmed_files = []
            for i, chunk in enumerate(chunks):
                audio_file = chunk.get("audio_file", "")
                if not audio_file or not os.path.exists(audio_file):
                    continue

                trimmed = os.path.join(work_dir, f"trimmed_{i:03d}.mp3")
                # silenceremove: 앞뒤 무음 제거 (threshold -40dB)
                cmd_trim = [
                    FFMPEG_PATH, "-y", "-i", os.path.abspath(audio_file),
                    "-af", (
                        "silenceremove=start_periods=1:start_silence=0.02:start_threshold=-40dB,"
                        "areverse,"
                        "silenceremove=start_periods=1:start_silence=0.02:start_threshold=-40dB,"
                        "areverse"
                    ),
                    "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100",
                    os.path.abspath(trimmed),
                ]
                subprocess.run(cmd_trim, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=10)

                if os.path.exists(trimmed) and os.path.getsize(trimmed) > 500:
                    trimmed_files.append(trimmed)
                else:
                    trimmed_files.append(os.path.abspath(audio_file))

            if not trimmed_files:
                raise Exception("트리밍된 파일 없음")

            # 크로스페이드 concat: FFmpeg acrossfade 필터 체인
            # 2개씩 순차 병합 (체인이 너무 길면 FFmpeg 에러)
            # → 간소화: concat + adelay로 -100ms 겹침 효과
            concat_list = os.path.join(work_dir, "concat_list.txt")
            with open(concat_list, "w", encoding="utf-8") as f:
                for i, trimmed in enumerate(trimmed_files):
                    abs_path = os.path.abspath(trimmed).replace("\\", "/")
                    f.write(f"file '{abs_path}'\n")

            # concat 후 acrossface 대신 간격 50ms로 타이트하게
            subprocess.run([
                FFMPEG_PATH, "-y", "-f", "concat", "-safe", "0",
                "-i", os.path.abspath(concat_list),
                "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100",
                os.path.abspath(raw_voice),
            ], capture_output=True, text=True, encoding="utf-8", errors="replace")

            if os.path.exists(raw_voice) and os.path.getsize(raw_voice) > 1000:
                print(f"  ✅ Silence Trim + Concat 완료")
            else:
                raise Exception("concat 결과 파일 없음")

        except Exception as e:
            print(f"  ⚠️  크로스페이드 실패 ({e}), 기본 concat 폴백...")
            concat_list = os.path.join(work_dir, "concat_list.txt")
            with open(concat_list, "w", encoding="utf-8") as f:
                for i, chunk in enumerate(chunks):
                    if i > 0:
                        pause_file = os.path.join(work_dir, f"pause_{i:03d}.mp3")
                        subprocess.run([
                            FFMPEG_PATH, "-y", "-f", "lavfi",
                            "-i", "anullsrc=r=44100:cl=mono",
                            "-t", "0.05",
                            "-c:a", "libmp3lame", "-b:a", "128k",
                            "-ar", "44100", pause_file
                        ], capture_output=True)
                        abs_pause = os.path.abspath(pause_file).replace("\\", "/")
                        f.write(f"file '{abs_pause}'\n")
                    abs_audio = os.path.abspath(chunk.get('audio_file', '')).replace("\\", "/")
                    f.write(f"file '{abs_audio}'\n")

            subprocess.run([
                FFMPEG_PATH, "-y", "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100",
                raw_voice
            ], capture_output=True, text=True, encoding="utf-8", errors="replace")

        if not os.path.exists(raw_voice):
            if chunks and os.path.exists(chunks[0].get("audio_file", "")):
                shutil.copy2(chunks[0]["audio_file"], raw_voice)
            else:
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

            if not os.path.exists(bgm_file):
                print(f"  ⚠️  BGM 생성 실패, voice만 사용")
                shutil.move(mastered_voice, output)
                return

            ducked_output = os.path.join(work_dir, "final_mix.mp3")
            abs_voice = os.path.abspath(mastered_voice)
            abs_bgm = os.path.abspath(bgm_file)

            # Sidechain: TTS 구간 BGM 30%로 감소 (attack 10ms, release 200ms)
            duck_filter = (
                "[1:a]acompressor=threshold=0.008:ratio=20:attack=10:release=200"
                ":detection=peak:link=average:level_sc=1[bgm_ducked];"
                "[0:a][bgm_ducked]amix=inputs=2:weights=1 0.15:duration=shortest"
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

        # ── Step 4: SFX 효과음 오버레이 (★ BGM 덕킹 이후 최종 단계) ──
        try:
            sfx_mgr = SFXManager()
            sfx_events = sfx_mgr.collect_sfx_from_chunks(chunks)
            if sfx_events and os.path.exists(output):
                sfx_output = os.path.join(work_dir, "final_with_sfx.mp3")
                if sfx_mgr.mix_sfx_into_audio(output, sfx_events, sfx_output):
                    shutil.move(sfx_output, output)
                else:
                    print(f"  ⚠️  SFX 믹싱 실패, SFX 없이 진행")
            elif sfx_events:
                print(f"  ⚠️  SFX 오버레이 스킵: output 파일 없음")
        except Exception as e:
            print(f"  ⚠️  SFX 시스템 오류 (무시): {e}")

        # 임시 파일 정리
        for tmp in [raw_voice, mastered_voice,
                     os.path.join(work_dir, "bgm.mp3"),
                     os.path.join(work_dir, "final_mix.mp3"),
                     os.path.join(work_dir, "final_with_sfx.mp3")]:
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
Style: Default,NanumSquareRound,58,&H00000000,&H000000FF,&H00000000,&H0000CCFF,-1,0,0,0,100,100,0,0,3,3,0,2,60,60,400,1

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
        self.viral_scraper = ViralSourceScraper()  # v5.0: 바이럴 소스
        self.stock_fetcher = StockVideoFetcher()   # v5.1: Pexels 스톡 비디오
        self.image_gen = ImageGenerator()            # v7.0: AI 이미지 생성
        self.scriptgen = ScriptGenerator(config)
        self.tts = TTSEngine(config)
        self.assembler = VideoAssembler(config)

    def _viral_to_posts(self, viral_items: list[dict]) -> list[dict]:
        """v6.0: 커뮤니티 핫글 → 실화 재구성(Reconstructive) 프롬프트 브릿지

        핵심: 제목만으로 Gemini가 커뮤니티 특유의 문체와 감성을 100% 모방하여
        실제 있었을 법한 맵고 짠 썰을 역산 재구성하도록 프롬프트를 설계.
        """

        # 소스별 문체/톤 지시
        _SOURCE_TONE = {
            "네이트판": (
                "네이트판 '톡커들의 선택' 스타일로 작성하라. "
                "시어머니/남편/시댁/직장상사/친구 같은 인간관계 갈등이 핵심이다. "
                "글쓴이가 억울하고 분한 마음으로 토로하는 1인칭 시점, "
                "구어체+반말 혼합, 감정이입 폭발하는 전개, "
                "댓글러들이 '이건 참으면 안 됨' 하고 분노할 만한 전개로 구성."
            ),
            "인스티즈": (
                "인스티즈 인기글 스타일로 작성하라. "
                "일상에서 벌어진 공감형 에피소드, 가벼운 유머와 반전, "
                "'ㅋㅋㅋ' 'ㄹㅇ' 같은 인터넷 축약어 자연스럽게 사용, "
                "10~30대가 공감하며 댓글 달고 싶어지는 톤."
            ),
            "에펨코리아": (
                "에펨코리아 베스트 스타일로 작성하라. "
                "시사 이슈든 유머든 팩트 기반으로 빠르게 전달하고, "
                "특유의 '~함' '~인듯' 끝말투, 이미지 첨부 느낌의 묘사, "
                "핵심 정보 → 반전 → 댓글 반응 예측까지 포함."
            ),
            "디시실베": (
                "디시인사이드 실시간베스트 스타일로 작성하라. "
                "자극적이고 파격적인 전개, 디시 특유의 거친 문체, "
                "'ㅋㅋㅋ' 'ㄷㄷ' '미쳤ㅋㅋ' 같은 표현 자유롭게 사용, "
                "충격적 반전이나 어이없는 결말로 마무리."
            ),
            "구글트렌드": (
                "현재 한국에서 실시간 화제인 키워드다. "
                "이 키워드가 왜 화제인지 추측해서, "
                "커뮤니티에서 돌고 있을 법한 썰 형태로 재구성하라. "
                "팩트와 추측을 섞되, 시청자가 '진짜?' 하고 반응할 전개로."
            ),
        }

        posts = []
        for item in viral_items[:self.config.crawl_count]:
            title = item.get("title", "")
            source = item.get("source", "viral")
            body = item.get("content", "")
            comments = item.get("comments", 0)
            views = item.get("views", 0)

            # 소스별 톤 지시 선택
            tone = _SOURCE_TONE.get(source, _SOURCE_TONE["인스티즈"])

            # ★ 실화 재구성 프롬프트
            padded_content = (
                f"[원본 제목] {title}\n"
                f"[출처] {source} (댓글 {comments}개, 조회 {views:,})\n"
                f"[본문] {body[:300] if body else '(본문 없음 — 제목만으로 역산 재구성 필요)'}\n\n"
                f"[대본 작성 지시]\n"
                f"{tone}\n\n"
                f"위 제목을 바탕으로 실제 {source}에 올라왔을 법한 "
                f"맵고 짠 실화 에피소드를 역산하여 재구성하라.\n"
                f"- 구체적인 디테일(장소, 대화, 상황)을 살려서 생생하게\n"
                f"- 감정 변화가 명확한 기승전결 구조\n"
                f"- 반전 또는 카타르시스 있는 전개 (단, 억지 훈훈함 금지)\n"
                f"- 시청자가 댓글을 안 달고는 못 배기는 마무리\n"
                f"- 10대~60대 전 연령대가 공감 가능한 소재로 구성\n"
            )

            posts.append({
                "title": title,
                "content": padded_content,
                "source": source,
                "url": item.get("url", ""),
                "screenshots": [],
                "_is_viral": True,
            })
        return posts

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
        elif self.config.source == "viral":
            # ── v5.0: 바이럴 소스 우선 크롤링 ──
            viral_items = self.viral_scraper.collect_all()
            if viral_items:
                posts = self._viral_to_posts(viral_items)
                print(f"\n  🔥 바이럴 소스 {len(posts)}개 선정 완료")
            else:
                print("  ⚠️  바이럴 소스 수집 실패 → 커뮤니티 폴백")
                posts = self.scraper.scrape_with_screenshots()
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
                elif post.get("_is_viral"):
                    # 바이럴 소스 → 토픽 기반 대본 생성
                    script_data = self.scriptgen.generate_from_topic(
                        post["title"]
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

                # v7.0: AI 이미지 생성 (웹툰 모드)
                ai_images = []
                try:
                    ai_images = self.image_gen.generate_scene_images(
                        script_data, work_dir
                    )
                except Exception as img_err:
                    print(f"  ⚠️  AI 이미지 생성 실패: {img_err}")

                # v5.1: Pexels 스톡 비디오 (AI 이미지 없을 때 폴백)
                scene_videos = []
                if not ai_images and self.config.use_stock_video:
                    scene_videos = self.stock_fetcher.fetch_scene_videos(
                        script_data, work_dir
                    )

                # 스톡 비디오 없으면 폴백용 스크린샷
                screenshots = post.get("screenshots", [])

                # Stage 3: TTS
                chunks = await self.tts.generate(script_data, work_dir)
                if not chunks:
                    print("  ⚠️  TTS 실패, 건너뜀")
                    continue

                # Stage 4: 영상 조립 (AI이미지 우선 → 스톡비디오 → 그라데이션)
                output_path = self.assembler.assemble(
                    script_data, chunks, screenshots, work_dir,
                    scene_videos=scene_videos,
                    ai_images=ai_images,
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
            finally:
                # work_dir 임시 파일 정리
                if os.path.exists(work_dir):
                    try:
                        shutil.rmtree(work_dir, ignore_errors=True)
                    except OSError:
                        pass

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
        description="🎬 YouTube Shorts 팩토리 v6.0 'The Viral Machine'",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python main.py                                          # 바이럴 소스 자동 (기본값)
  python main.py --source viral --count 3                 # 바이럴 소스 3개
  python main.py --source dcinside --gallery humor --count 3
  python main.py --source natepann --count 5
  python main.py --url "https://gall.dcinside.com/board/view/..."
  python main.py --topic "상견례 파토 썰" --skip-crawl
  python main.py --url "https://reddit.com/r/.../..." --video-edit  # 영상→숏츠
  python main.py --url "https://youtube.com/watch?v=..." --video-edit
  python main.py --tts-engine elevenlabs --source viral --count 1
  python main.py --tts-engine edge --topic "테스트" --skip-crawl

환경변수:
  GOOGLE_API_KEY      Gemini API 키 (필수, 무료)
  ELEVENLABS_API_KEY  ElevenLabs TTS (선택, 1순위 고품질)
  OPENAI_API_KEY      OpenAI TTS (선택, 2순위)
  GOAPI_KEY           GoAPI Midjourney (선택, 이미지 생성)
  APIFY_API_TOKEN     Apify API 토큰 (선택, 커뮤니티 크롤링 시)
        """
    )

    src = p.add_argument_group("📡 크롤링")
    src.add_argument("--source",
                     choices=["viral",
                              "natepann", "dcinside",
                              "dcinside_realtime_best", "dcinside_hit",
                              "fmkorea", "ruliweb", "instiz", "theqoo"],
                     default="viral")
    src.add_argument("--gallery", default="humor")
    src.add_argument("--count", type=int, default=3)
    src.add_argument("--url", default="")

    scr = p.add_argument_group("📝 대본")
    scr.add_argument("--topic", default="")
    scr.add_argument("--theme",
                     choices=["auto", "gossip", "life_hack", "empathy", "mystery"],
                     default="auto",
                     help="콘텐츠 테마 (auto=주제 기반 자동 감지)")
    scr.add_argument("--skip-crawl", action="store_true")
    scr.add_argument("--script-json", default="",
                     help="대본 JSON 파일 경로 (크롤링+Gemini 건너뛰고 바로 TTS→영상)")

    vid = p.add_argument_group("🎬 영상 편집 (--url과 함께 사용)")
    vid.add_argument("--video-edit", action="store_true",
                     help="URL 영상을 다운받아 하이라이트 → 숏츠 자동 변환 (yt-dlp 필요)")

    tts = p.add_argument_group("🔊 TTS")
    tts.add_argument("--tts-engine",
                     choices=["auto", "elevenlabs", "openai", "edge"],
                     default="auto",
                     help="TTS 엔진 선택 (auto=키 기반 자동, elevenlabs=1순위, openai=2순위, edge=무료)")
    tts.add_argument("--voice", default="ko-KR-InJoonNeural")
    tts.add_argument("--rate", default="+15%")
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
        theme=args.theme,
        skip_crawl=args.skip_crawl or bool(args.topic),
        tts_engine=args.tts_engine,
        tts_voice=args.voice,
        tts_rate=args.rate,
        tts_pitch=args.pitch,
        quality=args.quality,
        output_dir=args.output,
    )

    # v6.2: Gemini 롤백 — GOOGLE_API_KEY 필수
    if not config.google_api_key:
        print("❌ GOOGLE_API_KEY 환경변수 필요! (대본 + 이미지 생성)")
        print("   export GOOGLE_API_KEY='AIza...'")
        print("   (무료: https://aistudio.google.com/apikey)")
        sys.exit(1)

    # ── 수동 대본 모드 (--script-json) ──
    if args.script_json:
        script_path = os.path.abspath(args.script_json)
        if not os.path.exists(script_path):
            print(f"❌ 대본 파일 없음: {script_path}")
            sys.exit(1)

        with open(script_path, "r", encoding="utf-8") as f:
            script_data = json.load(f)

        print(f"\n{'='*60}")
        print(f"📝 수동 대본 모드: {script_data.get('title', '?')}")
        print(f"  문장: {len(script_data.get('script', []))}개")
        print(f"{'='*60}")

        work_dir = os.path.join(config.output_dir,
                                f"_manual_{datetime.now().strftime('%H%M%S')}")
        os.makedirs(work_dir, exist_ok=True)

        # v7.0: AI 이미지 생성 (웹툰 모드)
        ai_images = []
        try:
            image_gen = ImageGenerator()
            ai_images = image_gen.generate_scene_images(script_data, work_dir)
        except Exception as img_err:
            print(f"  ⚠️  AI 이미지 생성 실패: {img_err}")

        # Pexels 스톡 비디오 (AI 이미지 없을 때 폴백)
        scene_videos = []
        if not ai_images and config.use_stock_video:
            fetcher = StockVideoFetcher()
            scene_videos = fetcher.fetch_scene_videos(script_data, work_dir)

        # TTS
        tts = TTSEngine(config)
        chunks = await tts.generate(script_data, work_dir)
        if not chunks:
            print("❌ TTS 실패")
            sys.exit(1)

        # 영상 조립 (AI이미지 우선 → 스톡비디오 → 그라데이션)
        assembler = VideoAssembler(config)
        output_path = assembler.assemble(
            script_data, chunks, [], work_dir,
            scene_videos=scene_videos,
            ai_images=ai_images,
        )

        # 메타 저장
        duration_sec = max(c["end_ms"] for c in chunks) / 1000
        upload_info = {
            "title": script_data.get("title", ""),
            "description": script_data.get("description", ""),
            "tags": [t.lstrip("#") for t in script_data.get("tags", [])],
            "thumbnail_text": script_data.get("thumbnail_text", ""),
            "category": "22",
            "privacy": "public",
            "shorts": True,
            "duration_sec": duration_sec,
            "video_file": os.path.basename(output_path),
            "created": datetime.now().isoformat(),
        }
        info_path = output_path.replace(".mp4", "_upload_info.json")
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(upload_info, f, ensure_ascii=False, indent=2)

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"\n🎉 완료! {output_path} ({size_mb:.1f}MB, {duration_sec:.1f}초)")
        return

    # ── 영상 편집 모드 (--video-edit) ──
    if args.video_edit:
        if not args.url:
            print("❌ --video-edit 모드에는 --url 필수!")
            print("   python main.py --url 'https://...' --video-edit")
            sys.exit(1)

        editor = VideoAutoEditor(config)
        result = await editor.process_url_async(args.url)
        if result:
            print(f"\n🎉 영상 숏츠 변환 완료: {result}")
        else:
            print("😢 영상 편집 실패")
        return

    # ── 일반 모드 (크롤링 → 대본 → TTS → 영상) ──
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
