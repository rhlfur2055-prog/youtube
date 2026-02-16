# YouShorts v4.0 - 5만 구독자급 엔진 개편 계획

## 검증 완료된 리소스
- **Imagen 4.0** (`google-genai` SDK) - 이미지 생성 테스트 성공 (1MB급 고퀄)
- **Gemini 2.0 Flash** - 텍스트 생성 작동 확인
- **Claude Sonnet** - 대본 생성 (기존)
- **edge-tts** - HyunsuNeural 감정별 prosody (기존)
- **FFmpeg** - 2-pass 인코딩 + 오디오 필터 (기존)
- **Pillow** - 프레임별 렌더링 (기존)

## 수정 대상: `main.py` (단일 파일, 현재 ~1872줄)

---

## 모듈 1: 비주얼 엔진 - Dynamic Blur & Focus + Imagen AI

### 변경 대상: `VideoAssembler._prepare_backgrounds()` (L1346) + 새 메서드 추가

**구현:**
1. `_prepare_dynamic_backgrounds()` 신규 메서드
   - 스크린샷 원본을 **1.5배 확대 + GaussianBlur(15px)** 처리 → 감성 배경
   - 그 위에 **원본 스크린샷을 중앙 배치** (80% 크기) + 외곽선(3px white) + 드롭쉐도우
   - 기존 `_prepare_backgrounds()`를 교체

2. `_generate_ai_backgrounds()` 신규 메서드
   - script의 scene_hint 분석 → highlight=True인 장면 2~3개 추출
   - Imagen 4.0 API로 1080x1920 이미지 생성 (장면당 1장)
   - 해당 프레임 구간에서 AI 이미지로 배경 교체
   - 실패 시 기존 스크린샷 블러 폴백

3. `Config`에 추가:
   - `google_api_key: str` (.env GOOGLE_API_KEY)
   - `use_ai_bg: bool = True`

### FFmpeg 변경 없음 (프레임 렌더링 단계에서 처리)

---

## 모듈 2: 자막 시스템 - High-Retention Captions

### 변경 대상: `_render_subtitle()` (L1410) 전면 재작성

**구현:**
1. **자막 위치**: 화면 중앙 하단 (y=65%) → 더 크고 가독성 좋게
2. **기본 폰트**: 크기 56px, 볼드
3. **highlight 처리**:
   - 텍스트 색상 → **노란색 (#FFFF00)**
   - 크기 **1.2배 스케일** (56→67px)
   - 배경 박스도 1.2배 확대
4. **애니메이션 효과**:
   - 등장: 0→100% scale (150ms ease-out) - 자막이 커지면서 등장
   - 유지: 미세한 bounce 효과 (highlight만)
   - 퇴장: 100→0% alpha (100ms fade-out)
5. **텍스트 렌더링 개선**:
   - 외곽선(stroke) 3px 검정 → 어떤 배경에서도 가독성
   - 그림자 강화 (4px offset, blur)

### `EMOTION_STYLES` 수정:
- highlight=True면 text_color를 (255,255,0)으로 강제 오버라이드
- 배경 박스 opacity 220→240 (더 불투명)

---

## 모듈 3: 오디오 마스터링 - Professional Ducking & EQ

### 변경 대상: `_concat_audio()` (L1536) 전면 재작성

**구현:**
1. **BGM 생성**: FFmpeg `anoisesrc`로 로우파이 앰비언트 배경음 생성
   - `anoisesrc=c=pink:r=44100` + `lowpass=f=800` + `volume=0.15`
   - 전체 영상 길이만큼 생성

2. **Auto-Ducking**: FFmpeg `sidechaincompress` 필터
   - 보이스 트랙이 있는 구간: BGM → -20dB
   - 문장 사이 공백(300ms+): BGM 원래 볼륨으로 복귀
   - 구현: `[voice][bgm]sidechaincompress=threshold=0.02:ratio=10:attack=50:release=300`

3. **Voice Post-processing** (기존 강화):
   ```
   acompressor=threshold=-18dB:ratio=4:attack=5:release=50,
   equalizer=f=200:t=q:w=1:g=3,
   equalizer=f=3000:t=q:w=0.8:g=2,
   equalizer=f=5000:t=q:w=1:g=1,
   loudnorm=I=-14:TP=-1:LRA=9
   ```
   - 베이스 부스트 강화 (g=2→3)
   - 고음역 선명도 추가 (5kHz)
   - 라우드니스 -16→-14 LUFS (더 큰 소리)
   - LRA 11→9 (다이나믹 레인지 축소 = 스마트폰 최적화)

4. **최종 믹싱**: voice(마스터링 완료) + bgm(더킹 완료) → 합성

---

## 모듈 4: 알고리즘 최적화 파이프라인

### 4-1. 후킹 대본 (ScriptGenerator.SYSTEM_PROMPT 개편)

**변경:**
- 3초 후킹 강화: "지금 난리 난 OO 사건" 패턴
- 베스트 댓글 활용 지시 추가
- 대화형 구조 강제 ("여러분은 어떻게 생각하세요?")
- 끝맺음: "더 많은 반응은 댓글로!" + 구독 유도 멘트

### 4-2. 공백 축소 (TTSEngine + VideoAssembler)

**변경:**
- 배치 간 pause: 150ms → 100ms (20% 감소)
- pause_ms 최대값: 800ms → 600ms
- 문장 간 최소 간격: 50ms (빈틈 없는 텐션)

### 4-3. 구독 유도 엔딩 (VideoAssembler)

**변경:**
- 마지막 1.5초에 자동으로 "구독" + "좋아요" 아이콘 + 텍스트 오버레이
- "더 보고 싶으면 구독!" 텍스트 렌더링
- 빨간색 구독 버튼 시각적 장치

### 4-4. upload_info.json (ShortsFactory.run)

**변경:**
- Claude API로 SEO 최적화 제목/설명/태그 15개 자동 생성
- 별도 API 호출 추가 (대본 생성 후)
- 출력 형식:
```json
{
  "title": "어그로성 제목 (30자 이내)",
  "description": "영상 설명 + 해시태그",
  "tags": ["태그1", ..., "태그15"],
  "thumbnail_text": "썸네일 텍스트",
  "category": "22",
  "privacy": "public",
  "shorts": true
}
```

---

## 구현 순서

1. **Config 확장** + import 추가 (google.genai)
2. **모듈 4-1**: ScriptGenerator 프롬프트 개편 (가장 독립적)
3. **모듈 2**: 자막 시스템 재작성 (_render_subtitle)
4. **모듈 1**: 비주얼 엔진 (AI 배경 + Dynamic Blur)
5. **모듈 3**: 오디오 마스터링 (_concat_audio 재작성)
6. **모듈 4-2,3,4**: 공백 축소 + 엔딩 + upload_info
7. **통합 테스트**: `python main.py --source dcinside --gallery humor --count 1`
