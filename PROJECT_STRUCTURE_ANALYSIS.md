# 🗂️ youshorts v2.0 프로젝트 구조 분석
## 전체 트리맵 & 각 파일 역할

**작성일**: 2026-02-15
**분석 대상**: youshorts v2.0.0 (YouTube Shorts 자동 생성기)

---

## 📊 **프로젝트 계층 구조**

```
youshorts/
├── 🎯 진입점 (Entry Points)
│   ├── __init__.py              # 패키지 초기화, 버전 정보
│   ├── __main__.py              # `py -m youshorts` 실행 진입점
│   └── cli.py                   # CLI 인터페이스, argparse 기반
│
├── ⚙️ 설정 (Configuration)
│   ├── config/
│   │   ├── __init__.py          # config 패키지
│   │   ├── constants.py         # 상수 (색상, 크기, 지속시간)
│   │   ├── settings.py          # Pydantic 기반 전역 설정
│   │   └── styles.py            # 대본/편집 스타일 정의
│
├── 🎬 핵심 엔진 (Core Engine)
│   ├── core/
│   │   ├── __init__.py          # core 패키지
│   │   ├── pipeline.py          # ⭐ 전체 파이프라인 오케스트레이터
│   │   ├── script_generator.py # LLM 대본 생성 (Gemini/Claude)
│   │   ├── tts_engine.py        # TTS 음성 합성 (edge-tts)
│   │   ├── tts_enhanced.py      # 🆕 향상된 TTS (ElevenLabs/OpenAI)
│   │   ├── video_downloader.py  # Pexels 영상 다운로드
│   │   ├── video_composer.py    # 영상 합성 (MoviePy)
│   │   └── metadata.py          # 메타데이터 생성 (YouTube 업로드용)
│
├── 🔍 연구/크롤링 (Research)
│   ├── research/
│   │   ├── __init__.py          # research 패키지
│   │   ├── crawler.py           # 커뮤니티 게시글 크롤러 (Apify)
│   │   └── trend_scraper.py     # YouTube 트렌드 분석
│
├── 🆕 커뮤니티 모듈 (Community)
│   ├── modules/
│   │   └── community_crawler.py # 🆕 커뮤니티 전용 크롤러 (Apify)
│
├── 🎨 렌더링 (Rendering)
│   ├── rendering/
│   │   ├── __init__.py          # rendering 패키지
│   │   ├── subtitle_engine.py   # 자막 생성 (Pillow)
│   │   └── visual_effects.py    # 시각 효과 (Ken Burns, 파티클)
│
├── ✅ 품질 관리 (Quality Assurance)
│   ├── quality/
│   │   ├── __init__.py          # quality 패키지
│   │   ├── quality_check.py     # AI 품질 체크 (Claude)
│   │   ├── originality.py       # 독창성 검증 (유사도)
│   │   └── ab_test.py           # A/B 테스트 프레임워크
│
├── 🔒 보안 (Security)
│   ├── security/
│   │   ├── __init__.py          # security 패키지
│   │   ├── secrets_manager.py   # API 키 관리 (SecretStr)
│   │   ├── validators.py        # 입력 검증
│   │   └── sanitizer.py         # XSS/SQL Injection 방어
│
└── 🛠️ 유틸리티 (Utilities)
    ├── utils/
    │   ├── __init__.py          # utils 패키지
    │   ├── logger.py            # structlog 기반 로깅
    │   ├── file_handler.py      # 파일 입출력 관리
    │   ├── fonts.py             # 폰트 로딩 (Pillow)
    │   └── retry.py             # 재시도 데코레이터
```

---

## 🎯 **1. 진입점 (Entry Points)**

### `__init__.py`
```python
# 역할: 패키지 메타데이터 정의
__version__ = "2.0.0"
__author__ = "youshorts"
```
- 패키지 버전 정보
- `from youshorts import __version__`으로 접근

### `__main__.py`
```python
# 역할: 모듈 실행 진입점
if __name__ == "__main__":
    from youshorts.cli import main
    main()
```
- `py -m youshorts` 실행 시 호출
- CLI로 위임

### `cli.py` ⭐ **핵심**
```python
# 역할: CLI 인터페이스 (사용자와 시스템 사이 다리)
def main():
    parser = argparse.ArgumentParser()
    # --topic, --style, --no-pexels, --source-url 등
    args = parser.parse_args()

    # Pipeline 실행
    pipeline = Pipeline(topic=args.topic, ...)
    result = pipeline.run()
```
- **사용자 명령어 파싱**: `--topic "주제"`, `--style community`
- **배너 출력**: API 키 상태, 설정 요약
- **Pipeline 생성 및 실행**: 전체 프로세스 시작
- **결과 출력**: 완료 메시지, 파일 경로

**흐름**:
```
사용자 → CLI → Pipeline → 8단계 실행 → 최종 MP4 출력
```

---

## ⚙️ **2. 설정 (Configuration)**

### `config/constants.py`
```python
# 역할: 하드코딩된 상수 정의
BG_BLUR_RADIUS = 30
SUBTITLE_Y_RATIO = 0.75
PROGRESS_BAR_COLOR = (255, 100, 50)
```
- 영상 렌더링 관련 **고정값**
- 색상, 크기, 비율 등
- 코드 가독성 향상

### `config/settings.py` ⭐ **핵심 설정**
```python
# 역할: Pydantic 기반 전역 설정 (환경변수 자동 로드)
class Settings(BaseSettings):
    # API Keys
    anthropic_api_key: SecretStr
    pexels_api_key: SecretStr

    # Video
    video_width: int = 1080
    video_height: int = 1920

    # Background (🆕 추가됨)
    use_pexels: bool = True
    default_bg_type: str = "gradient"

    # Subtitle (🆕 추가됨)
    subtitle_font: str = "NanumSquareRoundEB"
    subtitle_font_size_max: int = 90
```
- **.env 파일 자동 로드**: API 키 관리
- **타입 검증**: Pydantic으로 자동 검증
- **싱글톤 패턴**: `get_settings()`로 전역 접근
- **시크릿 마스킹**: `SecretStr`로 로그에서 자동 숨김

**중요도**: ⭐⭐⭐⭐⭐ (모든 모듈이 참조)

### `config/styles.py`
```python
# 역할: 대본/편집 스타일 정의
STYLE_TEMPLATES = {
    "creative": ScriptStyleConfig(...),
    "community": ScriptStyleConfig(...),  # 🆕 커뮤니티 썰 스타일
}

EDIT_STYLES = ["dynamic", "cinematic", "storytelling"]
COMMUNITY_HOOKS = ["실화임. 소름 주의.", ...]
```
- 대본 생성 시 **스타일 템플릿** 제공
- 편집 스타일 목록 (Ken Burns 속도 등)
- 커뮤니티 훅 문구 (바이럴 유도)

---

## 🎬 **3. 핵심 엔진 (Core Engine)**

### `core/pipeline.py` ⭐⭐⭐ **최고 핵심**
```python
# 역할: 전체 파이프라인 오케스트레이터 (8~9단계 관리)
class Pipeline:
    def run(self) -> PipelineResult:
        # 1. 크롤링 (source_url 있으면)
        self._run_crawl()
        # 2. 대본 생성
        self._run_script_generation()
        # 3. 품질 체크
        self._run_quality_check()
        # 4. 독창성 체크
        self._run_originality_check()
        # 5. TTS 생성
        self._run_tts()
        # 6. 배경 다운로드
        self._run_background_download()
        # 7. 영상 합성
        self._run_video_composition()
        # 8. 메타데이터 생성
        self._run_metadata()
        # 9. 히스토리 저장
        self._run_save_history()
```
- **8~9단계 순차 실행**: 각 단계마다 로깅
- **에러 처리**: 한 단계 실패해도 전체 중단 안 됨
- **설정 주입**: `no_pexels=True` → `use_pexels=False` 오버라이드
- **결과 반환**: `PipelineResult` (output_path, metadata 등)

**의존성**:
```
Pipeline → script_generator → tts_engine → video_downloader → video_composer
```

### `core/script_generator.py` ⭐ **대본 생성**
```python
# 역할: LLM으로 대본 생성 (Gemini 우선, Claude 폴백)
def generate_script(topic: str, style: str) -> dict:
    # 1. 프롬프트 구성
    prompt = _build_prompt(topic, angle, hook_style, style)

    # 2. Gemini API 호출
    response = genai.generate_content(prompt)

    # 3. JSON 파싱
    script = json.loads(response.text)
    # {"title": "...", "full_text": "...", "emotion_tags": [...]}
```
- **프롬프트 엔지니어링**: 스타일별 템플릿 적용
- **LLM 선택**: Gemini (무료) → Claude (백업)
- **JSON 파싱**: 구조화된 대본 반환
- **감정 태그 생성**: 10종 감정 자동 태깅

### `core/tts_engine.py` (기존)
```python
# 역할: edge-tts 기반 음성 합성
def generate_fitted_tts(text, target_duration):
    # 1. edge-tts로 음성 생성
    audio_path = asyncio.run(_generate_tts_async(...))

    # 2. 속도 조절 (ffmpeg atempo)
    audio_path = _adjust_speed_ffmpeg(audio_path, speed_factor)

    # 3. 무음 삽입 (pause)
    audio_path = _insert_sentence_pauses(audio_path, pause_ms)

    # 4. WordBoundary → 자막 타이밍
    word_groups = _build_word_groups_from_timings(...)
```
- **무료 TTS**: Microsoft edge-tts 사용
- **속도 조절**: 59초 맞추기
- **타이밍 추출**: WordBoundary 이벤트 → 자막용
- **문제점**: 감정 제어 불가 (D등급)

### `core/tts_enhanced.py` 🆕 **향상된 TTS**
```python
# 역할: ElevenLabs/OpenAI/edge-tts 다중 제공자 지원
class EnhancedTTSEngine:
    def generate_sentence(self, text, emotion):
        params = EMOTION_PARAMS[emotion]  # stability, style, speed

        if provider == ELEVENLABS:
            return self._generate_elevenlabs(text, params)
        elif provider == OPENAI:
            return self._generate_openai(text, params)
        else:
            return self._generate_edge(text, params)  # 폴백
```
- **감정별 파라미터**: 10종 감정 → 음성 톤 변화
- **문장별 TTS**: 각 문장 개별 생성 → 결합
- **마스터링**: -14 LUFS, 컴프레서, EQ
- **자동 폴백**: API 실패 시 하위 제공자 사용

### `core/video_downloader.py`
```python
# 역할: Pexels API로 배경 영상 다운로드
def download_backgrounds(keywords, count=4):
    # use_pexels=False면 바로 그라데이션
    if not settings.use_pexels:
        return _generate_gradient_fallbacks(count, theme)

    # Pexels API 검색
    for keyword in keywords:
        videos = _search_pexels_videos(keyword, api_key)
        for video in videos:
            url = _get_best_video_url(video, min_width=1080)
            _download_video(url, output_path)
```
- **Pexels API 연동**: 1080p 이상 영상 검색
- **그라데이션 폴백**: API 실패 시 PNG 생성
- **커뮤니티 테마**: horror/funny/shocking 등 색상 매핑

### `core/video_composer.py` ⭐ **영상 합성**
```python
# 역할: MoviePy로 모든 요소 합성
def compose(bg_paths, tts_path, words, script, ...):
    # 1. 배경 (Ken Burns + 크로스 디졸브)
    background = _build_background(bg_paths, ...)

    # 2. 어둡게 오버레이
    overlay = _build_overlay(...)

    # 3. 타이틀 바 (슬라이드인)
    title_bar = create_title_bar(script["title"])

    # 4. 자막 (WordBoundary 기반)
    subtitle_clips = _build_subtitle_clips(words, ...)

    # 5. BGM (덕킹)
    bgm = _load_bgm(bgm_dir)

    # 6. 레이어 합성
    final = CompositeVideoClip([background, overlay, title, subtitles, ...])

    # 7. 렌더링
    final.write_videofile(output_path, fps=30, codec="libx264")
```
- **8개 레이어 합성**: 배경/오버레이/타이틀/자막/프로그레스바 등
- **Ken Burns 효과**: 배경 영상에 줌 적용
- **크로스 디졸브**: 1초 페이드 전환
- **BGM 덕킹**: TTS 음성 구간에서 BGM 자동 감소

### `core/metadata.py`
```python
# 역할: YouTube 업로드용 메타데이터 생성
def generate_metadata(script, output_path, ...):
    # 1. 해시태그 자동 생성
    hashtags = _extract_keywords(script["full_text"])

    # 2. 설명 생성
    description = f"{script['full_text']}\n\n{' '.join(hashtags)}"

    # 3. JSON 저장
    metadata = {
        "title": script["title"],
        "description": description,
        "tags": hashtags,
        "category": "22",  # People & Blogs
    }
    json.dump(metadata, open(meta_path, "w"))
```
- **자동 해시태그**: TF-IDF 키워드 추출
- **YouTube API 준비**: 업로드에 필요한 모든 정보
- **AI 공시**: 메타데이터에 AI 사용 명시

---

## 🔍 **4. 연구/크롤링 (Research)**

### `research/crawler.py` ⭐ **커뮤니티 크롤러**
```python
# 역할: Apify로 커뮤니티 게시글 크롤링 + 스크린샷
def crawl_community_post_with_screenshots(url):
    # 1. Apify website-content-crawler 호출
    post_data = _run_apify_crawler(url, selectors)

    # 2. 텍스트 기반 스크린샷 생성
    screenshots = _generate_text_screenshots(post_data["content"])

    # 3. 감정 테마 자동 감지
    theme = _detect_theme(post_data["content"])  # horror/funny/...
```
- **5개 플랫폼 지원**: 네이트판, 디시, 에펨, 더쿠, 인스티즈
- **CSS 셀렉터 자동 매핑**: 도메인별 최적화
- **스크린샷 배경**: 배경 영상 대신 텍스트 스크린샷 사용
- **테마 감지**: 공포/유머/감동 자동 분류

### `research/trend_scraper.py`
```python
# 역할: YouTube 트렌드 분석
def suggest_topics(region="KR", count=10):
    # YouTube Data API v3
    trending_videos = youtube.videos().list(
        part="snippet",
        chart="mostPopular",
        regionCode=region
    )
```
- **트렌드 주제 추천**: `--suggest-topics` 명령
- **경쟁 채널 분석**: `--competitor URL` 명령
- **자동 주제 선정**: `--auto-topic` 플래그

### `modules/community_crawler.py` 🆕 **추가 크롤러**
```python
# 역할: 독립적인 커뮤니티 크롤러 (research/crawler.py와 중복)
class CommunityCrawler:
    def fetch_post(self, url):
        # Apify Cheerio Scraper 사용
        # 플랫폼별 셀렉터 매핑
```
- **기능**: `research/crawler.py`와 유사
- **차이점**: 스크린샷 없이 텍스트만 크롤링
- **용도**: 대안 구현 (선택 가능)

---

## 🎨 **5. 렌더링 (Rendering)**

### `rendering/subtitle_engine.py`
```python
# 역할: Pillow로 자막 이미지 생성
def create_subtitle_image(text, video_width, ...):
    # 1. 폰트 로드
    font = ImageFont.truetype("NanumSquare.ttf", 70)

    # 2. 이미지 생성 (RGBA)
    img = Image.new("RGBA", (video_width, height), (0,0,0,0))
    draw = ImageDraw.Draw(img)

    # 3. 텍스트 그리기 (외곽선 + 본문)
    draw.text((x, y), text, font=font, fill="white", stroke_width=5)
```
- **자막 이미지 생성**: 투명 배경 PNG
- **외곽선(stroke)**: 가독성 보장
- **자동 줄바꿈**: 10-12글자 단위
- **WordBoundary 타이밍**: TTS 동기화

### `rendering/visual_effects.py`
```python
# 역할: 시각 효과 생성 (아이콘, 파티클 등)
def generate_visual_effects_for_script(script, duration):
    # 감정 태그 → 이모지 매핑
    effects = []
    for emotion in script["emotion_tags"]:
        icon = _get_emotion_icon(emotion)  # 😱 🔥 💕 등
        effects.append({"icon": icon, "timestamp": ...})
```
- **감정 이모지**: 좌상단에 감정 아이콘
- **파티클 효과**: 충격 장면에 파티클 (선택적)
- **타이밍 동기화**: TTS 감정 변화와 일치

---

## ✅ **6. 품질 관리 (Quality Assurance)**

### `quality/quality_check.py`
```python
# 역할: Claude AI로 대본 품질 체크
def check_quality(script: dict, use_ai=False):
    # 1. 규칙 기반 체크 (빠름)
    score = _rule_based_check(script)  # 길이, 구조 등

    # 2. AI 심층 체크 (선택적, --quality-ai)
    if use_ai:
        ai_result = _ai_quality_check(script)  # Claude API
        score = (score + ai_result["score"]) / 2
```
- **규칙 기반 체크**: 길이, 구조, 금지어 검증
- **AI 심층 체크**: Claude API로 품질 평가
- **점수**: 0~100점 (75점 이상 합격)

### `quality/originality.py`
```python
# 역할: 유사도 검증 (AI Slop 방지)
def check_originality(script, history):
    # 1. 히스토리 로드
    past_scripts = load_history()

    # 2. 유사도 계산 (TF-IDF)
    similarities = [calculate_similarity(script, past) for past in past_scripts]

    # 3. 중복 판정
    if max(similarities) > 0.7:
        return False, "기존 영상과 70% 유사"
```
- **중복 방지**: 과거 대본과 유사도 비교
- **유튜브 정책 준수**: AI Slop 방지
- **임계값**: 70% 이상 유사 시 재생성

### `quality/ab_test.py`
```python
# 역할: A/B 테스트 프레임워크
def select_ab_styles(base_style):
    # 2가지 스타일 조합 생성
    return {
        "A": {"script_style": "creative", "edit_style": "dynamic"},
        "B": {"script_style": "humorous", "edit_style": "energetic"}
    }
```
- **2개 버전 생성**: 같은 주제, 다른 스타일
- **성과 비교**: YouTube Analytics API 연동
- **자동 최적화**: 승리 스타일 기본값 업데이트

---

## 🔒 **7. 보안 (Security)**

### `security/secrets_manager.py`
```python
# 역할: API 키 안전 관리
class SecretsManager:
    @staticmethod
    def get_secret_value(secret: SecretStr) -> str:
        # SecretStr → 실제 문자열 변환
        return secret.get_secret_value() if secret else ""

    @staticmethod
    def validate_anthropic_key(key: str) -> bool:
        # API 키 형식 검증
        return key.startswith("sk-ant-")
```
- **SecretStr 관리**: Pydantic SecretStr 래핑
- **로그 마스킹**: 자동으로 키 숨김 (`***`)
- **검증**: API 키 형식 체크

### `security/validators.py`
```python
# 역할: 입력 검증
def validate_topic(topic: str) -> bool:
    # 금지어 체크
    if any(bad in topic for bad in BLACKLIST):
        return False

    # 길이 체크
    if len(topic) > 100:
        return False
```
- **입력 검증**: SQL Injection, XSS 방어
- **금지어 필터**: 유해 콘텐츠 차단
- **길이 제한**: DoS 방어

### `security/sanitizer.py`
```python
# 역할: 텍스트 정제
def sanitize_html(text: str) -> str:
    # HTML 태그 제거
    return re.sub(r"<[^>]+>", "", text)
```
- **HTML 이스케이프**: XSS 방어
- **특수문자 제거**: 안전한 파일명 생성

---

## 🛠️ **8. 유틸리티 (Utilities)**

### `utils/logger.py`
```python
# 역할: structlog 기반 로깅
def get_logger(name: str):
    return structlog.get_logger(name)
```
- **구조화 로깅**: JSON 포맷 로그
- **컨텍스트 추가**: 파이프라인 단계 자동 기록
- **파일 저장**: `logs/youshorts.log`

### `utils/file_handler.py`
```python
# 역할: 파일 입출력 관리
def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)
```
- **디렉토리 생성**: 자동으로 경로 생성
- **안전한 삭제**: 임시 파일 정리
- **경로 검증**: 존재 여부 체크

### `utils/fonts.py`
```python
# 역할: 폰트 로딩 (Pillow)
def load_font(font_name: str, size: int):
    # 시스템 폰트 경로 탐색
    for path in FONT_PATHS:
        font_path = os.path.join(path, f"{font_name}.ttf")
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
```
- **폰트 자동 로딩**: 시스템 경로 탐색
- **폴백**: 기본 폰트로 자동 전환
- **크기 조절**: 동적 크기 계산

### `utils/retry.py`
```python
# 역할: 재시도 데코레이터
@retry(max_attempts=3, backoff_factor=2.0)
def api_call():
    # API 호출
```
- **자동 재시도**: 3회, 지수 백오프
- **에러 캐치**: 일시적 오류 복구
- **로깅**: 재시도 횟수 기록

---

## 🔄 **전체 데이터 흐름**

```
┌─────────────────────────────────────────────────────────┐
│                   사용자 입력                             │
│  py -m youshorts --topic "주제" --style community        │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│               CLI (cli.py)                               │
│  • argparse로 명령어 파싱                                 │
│  • 설정 로드 (settings.py)                               │
│  • Pipeline 객체 생성                                     │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│           Pipeline (pipeline.py) ⭐⭐⭐                    │
│  오케스트레이터 - 8~9단계 순차 실행                        │
└──────────────────┬──────────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┬──────────────┬─────────────┐
    │              │              │              │             │
    ▼              ▼              ▼              ▼             ▼
┌────────┐  ┌────────────┐  ┌──────────┐  ┌───────────┐  ┌────────┐
│크롤링   │  │대본 생성    │  │품질 체크  │  │TTS 생성    │  │배경 DL │
│(선택)   │→ │Gemini/     │→ │규칙/AI   │→ │edge-tts/  │→ │Pexels/ │
│crawler │  │Claude      │  │quality   │  │enhanced   │  │gradient│
└────────┘  └────────────┘  └──────────┘  └───────────┘  └────────┘
                                                                │
    ┌───────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│         영상 합성 (video_composer.py) ⭐⭐                │
│  • 배경 + 오버레이 + 타이틀 + 자막 + BGM                   │
│  • MoviePy 레이어 합성                                     │
│  • Ken Burns, 크로스 디졸브                                │
└──────────────────┬──────────────────────────────────────┘
                   │
    ┌──────────────┴──────────────┐
    │                             │
    ▼                             ▼
┌───────────┐              ┌────────────┐
│메타데이터  │              │히스토리    │
│metadata   │              │저장        │
└───────────┘              └────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│              최종 출력 (output/)                          │
│  • shorts_제목_타임스탬프.mp4                             │
│  • shorts_제목_타임스탬프_meta.json                       │
│  • shorts_제목_타임스탬프_upload_info.json               │
└─────────────────────────────────────────────────────────┘
```

---

## 📊 **모듈 간 의존성 그래프**

```
settings.py (전역 설정)
    ↓
    ├→ cli.py (CLI)
    │   ↓
    │   Pipeline (오케스트레이터)
    │       ↓
    │       ├→ crawler.py (커뮤니티 크롤링)
    │       ├→ script_generator.py (대본 생성)
    │       │       ↓
    │       │       ├→ styles.py (스타일 템플릿)
    │       │       └→ LLM API (Gemini/Claude)
    │       ├→ quality_check.py (품질 체크)
    │       ├→ originality.py (독창성 체크)
    │       ├→ tts_engine.py / tts_enhanced.py (TTS)
    │       │       ↓
    │       │       └→ edge-tts / ElevenLabs / OpenAI
    │       ├→ video_downloader.py (배경 다운로드)
    │       │       ↓
    │       │       └→ Pexels API / gradient generator
    │       ├→ video_composer.py (영상 합성)
    │       │       ↓
    │       │       ├→ subtitle_engine.py (자막)
    │       │       ├→ visual_effects.py (효과)
    │       │       └→ MoviePy (렌더링)
    │       ├→ metadata.py (메타데이터)
    │       └→ file_handler.py (히스토리 저장)
    │
    ├→ logger.py (로깅)
    ├→ secrets_manager.py (API 키)
    └→ validators.py (검증)
```

---

## 🎯 **핵심 파일 TOP 5**

### 1. `pipeline.py` ⭐⭐⭐⭐⭐
- **역할**: 전체 파이프라인 오케스트레이터
- **중요도**: 최고 (모든 흐름의 중심)
- **의존**: 거의 모든 모듈 의존

### 2. `settings.py` ⭐⭐⭐⭐⭐
- **역할**: 전역 설정 관리
- **중요도**: 최고 (모든 모듈이 참조)
- **의존**: 독립적 (최상위)

### 3. `video_composer.py` ⭐⭐⭐⭐
- **역할**: 영상 합성 (최종 MP4 생성)
- **중요도**: 매우 높음
- **의존**: MoviePy, 자막, BGM 등

### 4. `script_generator.py` ⭐⭐⭐⭐
- **역할**: LLM 대본 생성
- **중요도**: 매우 높음 (콘텐츠의 핵심)
- **의존**: Gemini/Claude API

### 5. `cli.py` ⭐⭐⭐⭐
- **역할**: 사용자 인터페이스
- **중요도**: 높음 (진입점)
- **의존**: Pipeline, settings

---

## 🆕 **최근 추가된 기능**

### 커뮤니티 크롤러 기능
- `modules/community_crawler.py` (새로 생성)
- `research/crawler.py` (스크린샷 지원 강화)
- `--source-url` CLI 옵션

### 그라데이션 배경
- `settings.py`: `BG_GRADIENTS`, `BG_GRADIENTS_COMMUNITY`
- `video_downloader.py`: `_generate_gradient_fallbacks()`
- `video_composer.py`: `_generate_gradient_background()`
- `--no-pexels` CLI 옵션

### Enhanced TTS
- `tts_enhanced.py` (새로 생성)
- ElevenLabs / OpenAI / edge-tts 다중 지원
- 감정별 파라미터 매핑 (10종)
- 마스터링 파이프라인 (-14 LUFS)

---

## 📈 **프로젝트 통계**

- **총 Python 파일**: 35개
- **총 라인 수**: ~8,000줄 (추정)
- **핵심 모듈**: 7개 (pipeline, script, tts, video, downloader, composer, metadata)
- **지원 API**: 6개 (Gemini, Claude, Pexels, YouTube, Apify, ElevenLabs)
- **테스트 커버리지**: 42/43 passed (97.7%)

---

**작성자**: Claude Sonnet 4.5
**분석 완료**: 2026-02-15 21:00
