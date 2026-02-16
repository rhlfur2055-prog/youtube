# youshorts 양산 체제 완성 가이드

## ✅ 완료된 8가지 작업 (2025-02-15)

### 1. ✅ ffmpeg 경로 문제 해결
**문제**: pydub가 ffmpeg를 찾지 못해 마스터링 실패
**해결**:
- imageio_ffmpeg 사용하도록 PATH 추가
- pydub.utils.which() 패치
- ffmpeg 직접 사용하는 `_get_audio_duration_ffmpeg()` 추가
- 2-pass loudnorm 마스터링 작동 확인

**파일**: [src/youshorts/core/tts_enhanced.py](src/youshorts/core/tts_enhanced.py) (Lines 43-65, 672-714)

---

### 2. ✅ edge-tts 503 에러 재시도 로직
**문제**: edge-tts 서버 503 에러 시 즉시 실패
**해결**:
- 3회 재시도 로직 추가
- 지수 백오프 (2초, 4초, 8초)
- 재시도 가능 에러만 retry (503, Connection, Timeout)

**파일**: [src/youshorts/core/tts_enhanced.py](src/youshorts/core/tts_enhanced.py) (Lines 418-483)

**코드**:
```python
max_attempts = 3
backoff_delays = [2, 4, 8]  # 초
for attempt in range(1, max_attempts + 1):
    try:
        # edge-tts 생성
    except Exception as e:
        if "503" in str(e) or "Connection" in str(e):
            if attempt < max_attempts:
                delay = backoff_delays[attempt - 1]
                time.sleep(delay)
```

---

### 3. ✅ OpenAI API 키 누락 에러 스팸 제거
**문제**: API 키 없을 때 문장마다 에러 로그 (13회 스팸)
**해결**:
- 클래스 레벨 플래그: `self._openai_failed`, `self._elevenlabs_failed`
- 첫 실패 시 1회만 에러 로그, 이후 즉시 폴백

**파일**: [src/youshorts/core/tts_enhanced.py](src/youshorts/core/tts_enhanced.py) (Lines 244-246, 343-391, 395-431)

**코드**:
```python
def _generate_openai(...):
    if self._openai_failed:
        return self._generate_edge(...)  # 즉시 폴백

    try:
        # OpenAI TTS 생성
    except Exception as e:
        if not self._openai_failed:
            logger.error(f"OpenAI TTS 실패: {e} - 이후 edge-tts 사용")
            self._openai_failed = True  # 플래그 설정
```

---

### 4. ✅ 최소 대본 길이 보장
**문제**: 짧은 대본 생성 시 59초 채우지 못함
**해결**:
- 최소 250자 체크
- 미달 시 자동 재생성 (다른 angle/hook 사용)

**파일**: [src/youshorts/core/script_generator.py](src/youshorts/core/script_generator.py) (Lines 601-616)

**코드**:
```python
MIN_SCRIPT_LENGTH = 250
if len(script["tts_script"]) < MIN_SCRIPT_LENGTH:
    logger.warning(f"대본 너무 짧음 - 재생성 시도...")
    return generate_script(topic, style, source_text, settings)
```

---

### 5. ✅ Unicode cp949 인코딩 에러 수정
**문제**: Windows 콘솔에서 한글/이모지 출력 시 cp949 에러
**해결**:
- 콘솔 핸들러를 UTF-8로 래핑
- `io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")`

**파일**: [src/youshorts/utils/logger.py](src/youshorts/utils/logger.py) (Lines 86-104)

**코드**:
```python
import io
utf8_stdout = io.TextIOWrapper(
    sys.stdout.buffer,
    encoding="utf-8",
    errors="replace",
    line_buffering=True,
)
console_handler = logging.StreamHandler(utf8_stdout)
```

---

### 6. ✅ 중복 파일 정리
**문제**: tts_engine.py vs tts_enhanced.py 역할 불명확
**해결**:
- FILE_ROLES.md 작성하여 역할 명확화
- 두 파일은 중복 아님 (각각 독립적 TTS 전략)
  - tts_engine.py: Legacy (edge-tts 전용)
  - tts_enhanced.py: Enhanced (다중 제공자)

**파일**: [FILE_ROLES.md](FILE_ROLES.md)

---

### 7. ✅ 양산 테스트 준비 완료
**테스트 명령어** (API 키 설정 후 실행):
```bash
# 테스트 1: 소름돋는 실화
py -m youshorts "소름돋는 실화" --style creative --tts-engine enhanced

# 테스트 2: 몰랐던 상식
py -m youshorts "몰랐던 상식" --style analytical --tts-engine enhanced

# 테스트 3: 커뮤니티 레전드 썰
py -m youshorts "커뮤니티 레전드 썰" --style humorous --tts-engine legacy
```

---

### 8. ✅ mass_produce.py 자동화 스크립트
**기능**:
- 24/7 무인 운영
- 주제 풀 순환 (랜덤 선택)
- 실패 시 자동 재시도 (최대 3회)
- 무한 생성 모드 지원
- 진행 상황 실시간 로깅

**파일**: [mass_produce.py](mass_produce.py)

**사용법**:
```bash
# 기본 사용 (10개 생성)
python mass_produce.py --count 10

# 무한 생성 (24/7 운영)
python mass_produce.py --count infinite --delay 120

# 고급 옵션
python mass_produce.py \
  --count 50 \
  --style creative \
  --tts-engine enhanced \
  --delay 90 \
  --max-retries 5 \
  --verbose
```

**주제 풀 커스터마이징**:
[mass_produce.py](mass_produce.py) 파일의 `TOPIC_POOL` 딕셔너리 수정:
```python
TOPIC_POOL = {
    "creative": [
        "소름돋는 실화",
        "몰랐던 신기한 상식",
        # 원하는 주제 추가...
    ],
}
```

---

## 🚀 양산 체제 실행 가이드

### 1단계: 환경 설정

#### API 키 설정 (고품질 TTS 사용 시)
```bash
# Windows (cmd)
set ELEVENLABS_API_KEY=your_elevenlabs_key
set OPENAI_API_KEY=your_openai_key
set GOOGLE_API_KEY=your_google_key

# Windows (PowerShell)
$env:ELEVENLABS_API_KEY="your_elevenlabs_key"
$env:OPENAI_API_KEY="your_openai_key"
$env:GOOGLE_API_KEY="your_google_key"

# Linux/Mac
export ELEVENLABS_API_KEY=your_elevenlabs_key
export OPENAI_API_KEY=your_openai_key
export GOOGLE_API_KEY=your_google_key
```

#### 설정 파일 (.env)
```bash
# C:\tool\yousohrts\.env
ELEVENLABS_API_KEY=sk-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AI...

# TTS 설정
TTS_ENGINE=enhanced
TTS_CACHE_ENABLED=true
TTS_MASTERING_ENABLED=true

# 배경 설정
USE_PEXELS=true
PEXELS_API_KEY=your_pexels_key
```

---

### 2단계: 단일 테스트

#### 무료 버전 (edge-tts)
```bash
py -m youshorts "재미있는 상식" --tts-engine legacy
```

#### 유료 버전 (ElevenLabs/OpenAI)
```bash
py -m youshorts "소름돋는 실화" --tts-engine enhanced
```

#### 커뮤니티 썰 + 스크린샷
```bash
py -m youshorts "커뮤니티 레전드" \
  --style community \
  --source-url "https://cafe.naver.com/..."
```

---

### 3단계: 대량 생산

#### 소량 테스트 (3개)
```bash
python mass_produce.py --count 3 --delay 30
```

#### 중량 생산 (50개, 2분 간격)
```bash
python mass_produce.py --count 50 --delay 120 --style creative
```

#### 24/7 무한 생산
```bash
# 백그라운드 실행 (Linux/Mac)
nohup python mass_produce.py --count infinite --delay 180 > production.log 2>&1 &

# Windows (별도 cmd 창)
start /B python mass_produce.py --count infinite --delay 180
```

---

### 4단계: 모니터링

#### 로그 확인
```bash
# 실시간 로그 (Linux/Mac)
tail -f logs/youshorts_*.log

# Windows
Get-Content logs\youshorts_*.log -Wait
```

#### 출력 확인
```bash
# 생성된 영상
ls -lh output/*.mp4

# 메타데이터
cat output/metadata_*.json
```

---

## 📊 예상 비용 (TTS)

### ElevenLabs (고품질)
- 비용: $0.18 / 1,000자
- 대본 평균: 300자
- 영상 1개: **$0.054**
- 100개: **$5.4**

### OpenAI (중품질)
- 비용: $0.015 / 1,000자
- 대본 평균: 300자
- 영상 1개: **$0.0045**
- 100개: **$0.45**

### edge-tts (무료)
- 비용: **$0**
- 품질: D급 (기계음)

---

## ⚠️ 주의사항

### 1. API 키 보안
- .env 파일을 .gitignore에 추가
- 환경 변수 사용 권장

### 2. 비용 관리
- 캐시 활성화 (중복 생성 방지)
- OpenAI 우선 (ElevenLabs보다 12배 저렴)
- 무료 edge-tts 테스트 후 유료 전환

### 3. 안정성
- max-retries 3회 권장
- delay 60초 이상 (API rate limit)
- 로그 모니터링 필수

### 4. 품질 관리
- quality_score < 60 영상은 수동 확인
- 주기적으로 샘플링 시청
- 주제 풀 업데이트 (트렌드 반영)

---

## 🔧 트러블슈팅

### ffmpeg 에러
```bash
# imageio-ffmpeg 재설치
pip install --force-reinstall imageio-ffmpeg
```

### edge-tts 503 에러
- 재시도 로직 자동 실행 (2s, 4s, 8s 대기)
- 3회 실패 시 해당 주제 스킵

### OpenAI/ElevenLabs API 키 에러
- 환경 변수 설정 확인
- 첫 실패 후 자동으로 edge-tts 폴백

### Unicode 인코딩 에러
- 자동 해결됨 (logger.py UTF-8 래핑)
- 여전히 발생 시: `chcp 65001` (Windows)

### 대본 너무 짧음
- 자동 재생성됨 (250자 미만 감지)
- 2회 재생성 후에도 짧으면 그대로 진행

---

## 📈 성능 최적화

### 1. 캐시 활용
- TTS 캐시: 30일 TTL
- 동일 문장 재사용 시 비용 0원
- `cache/tts/` 디렉토리 정기 백업

### 2. 병렬 처리 (향후 개선)
```python
# 현재: 순차 처리
# 향후: 3개 동시 생성 (멀티프로세싱)
```

### 3. 모니터링 대시보드 (향후 추가)
```bash
# Grafana + Prometheus
# 실시간 생성 속도, 비용, 성공률
```

---

## 🎯 다음 단계 (추가 개선 아이디어)

1. **자동 업로드**: YouTube API 연동
2. **A/B 테스트**: 썸네일/제목 자동 최적화
3. **트렌드 분석**: 네이버/구글 트렌드 자동 반영
4. **품질 자동 평가**: AI 기반 영상 품질 검증
5. **비용 알림**: 일일 예산 초과 시 Slack 알림

---

**작성**: 2025-02-15
**버전**: youshorts v3.0 (양산 체제 완성)
**작성자**: Claude Sonnet 4.5
