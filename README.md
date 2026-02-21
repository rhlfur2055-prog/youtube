# 🎬 YouTube Shorts 팩토리 v6.0

> 자동화된 바이럴 YouTube Shorts 영상 생성 시스템

## 📋 프로젝트 소개

커뮤니티 베스트 글을 크롤링하여 자동으로 쇼츠 영상을 생성하는 올인원 파이프라인입니다.
바이럴 소스 수집 → AI 대본 생성 → TTS 음성 합성 → 영상 조립까지 완전 자동화되어 있습니다.

### ✨ 주요 기능

- 🔍 **멀티플랫폼 크롤링**: 디시인사이드, 에펨코리아, 루리웹, 인스티즈, 더쿠, 네이트판 등
- 🤖 **AI 대본 생성**: Gemini 2.0 Flash를 활용한 100만뷰 후킹 대본 자동 생성
- 🎤 **고품질 TTS**: ElevenLabs/OpenAI/Edge-TTS 지원 (감정 태그 포함)
- 🎨 **자동 배경 생성**: 분위기별 그라데이션 배경 이미지 생성
- 🎥 **영상 조립**: FFmpeg 기반 Dynamic Blur + Ken Burns + 자막 + BGM
- 📊 **SEO 최적화**: 제목, 설명, 태그 자동 생성
- 🚀 **대량 생산**: topics.txt 기반 배치 생성 지원

## 📂 프로젝트 구조

```
C:\tool\yousohrts\
│
├── 🔒 설정 파일
│   ├── .env              ← API 키 (절대 공유 금지)
│   ├── .env.example       ← API 키 템플릿
│   ├── .gitignore
│   ├── README.md
│   └── requirements.txt   ← Python 패키지 목록
│
├── 🚀 메인 실행 스크립트
│   ├── main.py            ← 메인 진입점 (바이럴 소스/URL/주제 기반 생성)
│   ├── perfect_one_shot.py ← 원샷 영상 생성 (단일 주제 완벽 생성)
│   ├── mass_produce.py    ← 대량 생산 (topics.txt 기반 배치)
│   └── auto_produce.bat   ← 자동 실행 배치 파일
│
├── 🎨 생성/TTS 모듈
│   ├── bing_generator.py   ← Bing 이미지 생성
│   ├── goapi_midjourney.py ← Midjourney API (GoAPI)
│   ├── elevenlabs_tts.py   ← ElevenLabs 음성 합성
│   ├── openai_tts.py       ← OpenAI TTS
│   ├── generate_sfx.py     ← 효과음 생성
│   └── preview_images.py   ← 이미지 미리보기
│
├── 🧪 테스트/수동 스크립트
│   ├── _analyze_blacklist.py  ← 블랙리스트 분석
│   ├── _crawl_trends.py       ← 트렌드 크롤링 테스트
│   ├── _run_manual_safe.py    ← 수동 안전 실행
│   ├── _run_manual_script.py  ← 수동 스크립트 실행
│   ├── _test_gemini.py        ← Gemini API 테스트
│   └── _test_tts.py           ← TTS 테스트
│
├── 📂 리소스 폴더
│   ├── assets/sfx/        ← 효과음 (comedy/drama/korean/reactions/transitions)
│   ├── data/
│   │   ├── backgrounds/   ← 배경 이미지
│   │   ├── bgm/           ← 배경 음악
│   │   ├── fonts/         ← 폰트 파일
│   │   └── scripts/       ← 스크립트 데이터
│   ├── stories/           ← 생성된 스토리 데이터
│   └── src/youshorts/     ← 소스 패키지
│
├── 📂 작업 폴더 (자동 생성/정리)
│   ├── cache/tts/         ← TTS 캐시 (재사용)
│   ├── temp/              ← 임시 파일 (frames 등)
│   ├── logs/              ← 실행 로그
│   ├── output/            ← 최종 영상 출력
│   └── tests/             ← 테스트 코드
│
└── 📄 기타
    └── topics.txt         ← 대량 생산용 주제 목록
```

## 🚀 설치 방법

### 1. Python 환경 준비
```bash
# Python 3.10+ 필요
python --version
```

### 2. 패키지 설치
```bash
pip install -r requirements.txt
```

### 3. FFmpeg 설치 (필수)
```bash
# Windows (Chocolatey)
choco install ffmpeg

# macOS (Homebrew)
brew install ffmpeg

# Linux (Ubuntu/Debian)
sudo apt install ffmpeg
```

### 4. 환경변수 설정
```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 편집하여 API 키 입력
```

**필수 API 키:**
- `GOOGLE_API_KEY`: Gemini API 키 (무료) - [발급받기](https://aistudio.google.com/apikey)

**선택 API 키 (고품질 TTS/이미지):**
- `ELEVENLABS_API_KEY`: ElevenLabs TTS (1순위 고품질)
- `ELEVENLABS_VOICE_ID`: ElevenLabs 음성 ID
- `OPENAI_API_KEY`: OpenAI TTS (2순위)
- `GOAPI_KEY`: Midjourney 이미지 생성
- `APIFY_API_TOKEN`: 크롤링 (없어도 폴백 작동)

## 💡 사용법

### 기본 사용 (바이럴 소스 자동 크롤링)
```bash
python main.py
```

### 특정 소스에서 여러 개 생성
```bash
# 디시인사이드 실시간 베스트 5개
python main.py --source dcinside_realtime_best --count 5

# 에펨코리아 베스트 3개
python main.py --source fmkorea --count 3

# 네이트판 베스트 5개
python main.py --source natepann --count 5
```

### URL 직접 입력
```bash
python main.py --url "https://gall.dcinside.com/board/view/?id=..."
```

### 주제 직접 입력 (크롤링 없이)
```bash
python main.py --topic "상견례 파토 실화" --skip-crawl
```

### 대량 생산 (topics.txt 기반)
```bash
# topics.txt에 주제 목록 작성 (한 줄에 하나씩)
python mass_produce.py
```

### 원샷 완벽 생성
```bash
python perfect_one_shot.py
```

### 자동 배치 실행 (Windows)
```batch
auto_produce.bat
```

## 🎯 지원하는 크롤링 소스

- `viral`: YouTube Trending + Google Trends + HackerNews (기본값)
- `dcinside_realtime_best`: 디시인사이드 실시간 베스트
- `dcinside_concept`: 디시인사이드 개념글
- `fmkorea`: 에펨코리아 베스트
- `ruliweb`: 루리웹 베스트
- `instiz`: 인스티즈 베스트
- `theqoo`: 더쿠 베스트
- `natepann`: 네이트판 베스트

## 📊 출력 파일

생성된 영상은 `output/` 폴더에 저장됩니다:

```
output/
├── shorts_제목_20240221_083617.mp4  ← 최종 영상
└── upload_info.json                  ← 업로드 정보 (제목/설명/태그)
```

## 🎨 파이프라인 구조

```
[바이럴 소스 수집]
  ↓
[Gemini AI 대본 생성]
  ↓
[TTS 음성 합성] (ElevenLabs/OpenAI/Edge-TTS)
  ↓
[배경 이미지 생성] (Pillow 그라데이션)
  ↓
[영상 조립] (FFmpeg: 자막 + BGM + 효과)
  ↓
[출력] MP4 + upload_info.json
```

## ⚙️ 기술 스택

- **AI**: Google Gemini 2.0 Flash
- **TTS**: ElevenLabs, OpenAI TTS, Edge-TTS
- **영상**: FFmpeg, Pillow (Python Imaging Library)
- **크롤링**: Requests, BeautifulSoup4, Apify (선택)
- **언어**: Python 3.10+

## 📝 주요 의존성

```
edge-tts>=6.1.0                    # TTS 기본 엔진
google-generativeai>=0.8.0         # Gemini AI
requests>=2.31.0                   # HTTP 요청
beautifulsoup4>=4.12.0             # HTML 파싱
python-dotenv>=1.0.0               # 환경변수 관리
Pillow>=10.0.0                     # 이미지 처리
elevenlabs>=1.0.0                  # 고품질 TTS (선택)
openai>=1.0.0                      # OpenAI TTS (선택)
```

## 🔒 보안 주의사항

⚠️ **절대 공유 금지:**
- `.env` 파일 (API 키 포함)
- `cache/` 폴더 (개인 TTS 캐시)
- `output/` 폴더 (생성된 영상)

✅ **Git에 포함되는 파일:**
- `.env.example` (템플릿만)
- 소스 코드 (`.py` 파일)
- 리소스 파일 (`assets/`, `data/`)

## 📜 라이선스

개인 프로젝트 - 상업적 사용 시 주의 필요 (API 약관 확인)

## 🤝 기여

이슈 및 PR은 언제나 환영합니다!

---

**Made with ❤️ by Claude & Human**
