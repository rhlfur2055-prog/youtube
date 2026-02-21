"""
ElevenLabs TTS 모듈 — YouShorts v6.0
─ 감정별 voice_settings 동적 조절 (stability, similarity_boost, style)
─ Word-level timestamps (character alignment → 한국어 어절 후처리)
─ 최대 3회 Retry + 지수 백오프
─ 모델: eleven_multilingual_v2 (한국어 최적)
"""

import os
import re
import time
import base64
import asyncio
import requests
from typing import Optional


class ElevenLabsTTS:
    """ElevenLabs TTS with word-level timestamps and emotion-based voice switching."""

    BASE_URL = "https://api.elevenlabs.io/v1"
    MODEL_ID = "eleven_multilingual_v2"
    MAX_RETRIES = 4
    RETRY_DELAYS = [2, 8, 25, 60]  # 지수 백오프 (초) — 429에서 최대 95초 버팀

    # ── 감정별 voice_settings ──
    # stability: 낮을수록 감정적/가변적, 높을수록 차분/일관적
    # similarity_boost: 원본 음성 유사도
    # style: 0.0=중립, 1.0=감정 극대화
    EMOTION_SETTINGS = {
        "neutral":  {"stability": 0.50, "similarity_boost": 0.75, "style": 0.0},
        "tension":  {"stability": 0.40, "similarity_boost": 0.80, "style": 0.6},
        "surprise": {"stability": 0.30, "similarity_boost": 0.70, "style": 0.8},
        "anger":    {"stability": 0.30, "similarity_boost": 0.80, "style": 0.7},
        "angry":    {"stability": 0.30, "similarity_boost": 0.80, "style": 0.7},
        "sad":      {"stability": 0.70, "similarity_boost": 0.80, "style": 0.5},
        "fun":      {"stability": 0.30, "similarity_boost": 0.60, "style": 0.9},
        "funny":    {"stability": 0.30, "similarity_boost": 0.60, "style": 0.9},
        "shock":    {"stability": 0.25, "similarity_boost": 0.70, "style": 0.8},
        "shocked":  {"stability": 0.25, "similarity_boost": 0.70, "style": 0.8},
        "relief":   {"stability": 0.60, "similarity_boost": 0.70, "style": 0.3},
        "excited":  {"stability": 0.20, "similarity_boost": 0.70, "style": 1.0},
        "warm":     {"stability": 0.60, "similarity_boost": 0.80, "style": 0.4},
        "serious":  {"stability": 0.60, "similarity_boost": 0.80, "style": 0.2},
        "whisper":  {"stability": 0.80, "similarity_boost": 0.90, "style": 0.3},
    }

    def __init__(self, api_key: str, default_voice_id: str = ""):
        self.api_key = api_key
        self.default_voice_id = default_voice_id
        self._resolved_voice_id = ""

    # ── 퍼블릭 API ──

    async def generate_sentence(
        self, text: str, emotion: str, output_path: str
    ) -> dict:
        """한 문장의 TTS를 생성하고 word-level 타이밍을 반환한다.

        Args:
            text: 한국어 문장
            emotion: 감정 키 (neutral, angry, funny 등)
            output_path: 출력 MP3 경로

        Returns:
            {
                "audio_file": str,
                "duration_ms": int,
                "word_timings": [{"word": str, "start_ms": int, "end_ms": int}, ...]
            }
        """
        if not self._resolved_voice_id:
            self._resolved_voice_id = await self._resolve_voice_id()

        voice_id = self._resolved_voice_id
        settings = self._get_voice_settings(emotion)

        # v6.0 지수 백오프: 401은 즉시 포기, 429는 장기 대기 후 재시도
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._api_call_with_timestamps(
                        text, voice_id, settings, output_path
                    ),
                )
                return result
            except ValueError as e:
                # 401 Unauthorized → API 키 자체가 무효, 재시도 무의미
                raise RuntimeError(f"ElevenLabs 인증 실패 (재시도 안 함): {e}")
            except Exception as e:
                last_error = e
                err_str = str(e)
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAYS[attempt]
                    # 429는 서버가 rate-limit 풀릴 때까지 길게 대기
                    if "429" in err_str:
                        delay = max(delay, 15 * (attempt + 1))  # 15, 30, 45, 60초
                    print(f"    ⚠️  ElevenLabs 재시도 {attempt + 1}/{self.MAX_RETRIES} "
                          f"({delay}초 후): {e}")
                    await asyncio.sleep(delay)

        raise RuntimeError(
            f"ElevenLabs API {self.MAX_RETRIES}회 실패: {last_error}"
        )

    # ── 내부 구현 ──

    def _api_call_with_timestamps(
        self, text: str, voice_id: str, settings: dict, output_path: str
    ) -> dict:
        """동기 HTTP 호출: /text-to-speech/{voice_id}/with-timestamps

        Returns:
            {"audio_file", "duration_ms", "word_timings"}
        """
        url = f"{self.BASE_URL}/text-to-speech/{voice_id}/with-timestamps"

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "text": text,
            "model_id": self.MODEL_ID,
            "voice_settings": {
                "stability": settings["stability"],
                "similarity_boost": settings["similarity_boost"],
                "style": settings["style"],
                "use_speaker_boost": True,
            },
            "output_format": "mp3_44100_128",
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=30)

        if resp.status_code == 401:
            raise ValueError("ElevenLabs API 키 무효 (401 Unauthorized)")
        if resp.status_code == 429:
            raise RuntimeError("ElevenLabs 요청 한도 초과 (429 Too Many Requests)")
        if resp.status_code != 200:
            raise RuntimeError(
                f"ElevenLabs API 오류 {resp.status_code}: "
                f"{resp.text[:200]}"
            )

        data = resp.json()

        # 1) 오디오 디코딩 + 저장
        audio_b64 = data.get("audio_base64", "")
        if not audio_b64:
            raise ValueError("ElevenLabs 응답에 audio_base64 없음")

        audio_bytes = base64.b64decode(audio_b64)
        if len(audio_bytes) < 500:
            raise ValueError(f"오디오 크기 너무 작음: {len(audio_bytes)} bytes")

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        # 2) alignment → word_timings 변환
        alignment = data.get("alignment", {})
        chars = alignment.get("characters", [])
        char_starts = alignment.get("character_start_times_seconds", [])
        char_ends = alignment.get("character_end_times_seconds", [])

        word_timings = self._aggregate_word_timings(
            text, chars, char_starts, char_ends
        )

        # 3) 전체 duration 계산
        if char_ends:
            duration_ms = int(max(char_ends) * 1000)
        else:
            duration_ms = self._measure_duration_fallback(output_path)

        return {
            "audio_file": output_path,
            "duration_ms": duration_ms,
            "word_timings": word_timings,
        }

    def _aggregate_word_timings(
        self,
        original_text: str,
        chars: list,
        char_starts: list,
        char_ends: list,
    ) -> list[dict]:
        """character-level alignment → 한국어 어절 단위 word_timings 변환

        ★ 핵심 후처리:
        - 단순 공백 분할이 아닌, 한국어 어절(조사 포함) 기준으로 자연스럽게 묶음
        - "시어머니가" → 1개 어절 (조사 '가' 분리 안 함)
        - "근데 진짜" → 2개 어절 ("근데", "진짜")
        - 문장부호(.,!?)는 직전 어절에 붙임
        """
        if not chars or not char_starts or not char_ends:
            return []

        # 안전 체크: 길이 맞추기
        min_len = min(len(chars), len(char_starts), len(char_ends))
        chars = chars[:min_len]
        char_starts = char_starts[:min_len]
        char_ends = char_ends[:min_len]

        # Step 1: 원문을 어절 단위로 분할 (공백 기준)
        eojeol_list = self._split_eojeol(original_text)

        # Step 2: 각 어절의 시작/끝 character index 매핑
        word_timings = []
        char_idx = 0

        for eojeol in eojeol_list:
            if not eojeol.strip():
                continue

            # 공백 스킵 (alignment에 공백이 포함될 수 있음)
            while char_idx < min_len and chars[char_idx] in (" ", "\t", "\n"):
                char_idx += 1

            if char_idx >= min_len:
                break

            # 이 어절에 해당하는 character 범위 찾기
            eojeol_start_idx = char_idx
            matched_chars = 0
            eojeol_clean = eojeol.replace(" ", "")

            for ci in range(char_idx, min_len):
                c = chars[ci]
                if c in (" ", "\t", "\n"):
                    continue
                matched_chars += 1
                if matched_chars >= len(eojeol_clean):
                    char_idx = ci + 1
                    break
            else:
                char_idx = min_len

            # 시작/끝 시간 추출
            valid_starts = [
                char_starts[i] for i in range(eojeol_start_idx, min(char_idx, min_len))
                if i < min_len and chars[i] not in (" ", "\t", "\n")
            ]
            valid_ends = [
                char_ends[i] for i in range(eojeol_start_idx, min(char_idx, min_len))
                if i < min_len and chars[i] not in (" ", "\t", "\n")
            ]

            if valid_starts and valid_ends:
                word_timings.append({
                    "word": eojeol.strip(),
                    "start_ms": int(min(valid_starts) * 1000),
                    "end_ms": int(max(valid_ends) * 1000),
                })

        return word_timings

    @staticmethod
    def _split_eojeol(text: str) -> list[str]:
        """한국어 텍스트를 자연스러운 어절 단위로 분할

        ★ 한국어 특성 반영:
        - 공백 기준 기본 분할
        - 문장부호(.,!?ㅋㅎ)는 직전 어절에 붙임
        - 1글자 조사만 단독으로 떨어지면 직전 어절에 합침
        """
        # 기본 공백 분할
        raw_parts = text.split()
        if not raw_parts:
            return []

        # 문장부호만으로 구성된 조각은 직전에 합치기
        merged = []
        for part in raw_parts:
            if merged and re.match(r'^[.,!?\~\-ㅋㅎㅠㅜ]+$', part):
                # 문장부호만 → 직전 어절에 합침
                merged[-1] += part
            elif merged and len(part) == 1 and re.match(r'^[은는이가을를에서도의로와과]$', part):
                # 단독 조사 → 직전 어절에 합침
                merged[-1] += part
            else:
                merged.append(part)

        return merged

    def _get_voice_settings(self, emotion: str) -> dict:
        """감정 키 → voice_settings 반환 (없으면 neutral 폴백)"""
        return self.EMOTION_SETTINGS.get(
            emotion,
            self.EMOTION_SETTINGS["neutral"]
        )

    async def _resolve_voice_id(self) -> str:
        """voice_id 확정: 설정값 → API 자동 검색 → 하드코딩 폴백"""

        # 1) 사용자 지정 voice_id
        if self.default_voice_id:
            return self.default_voice_id

        # 2) API에서 한국어 가능한 음성 자동 검색
        try:
            voice_id = await asyncio.get_event_loop().run_in_executor(
                None, self._find_korean_voice
            )
            if voice_id:
                return voice_id
        except Exception as e:
            print(f"    ⚠️  ElevenLabs 음성 검색 실패: {e}")

        # 3) 글로벌 기본값 (Adam — multilingual 지원)
        return "pNInz6obpgDQGcFmaJgB"

    def _find_korean_voice(self) -> Optional[str]:
        """ElevenLabs API에서 한국어 지원 음성 ID 자동 검색"""
        url = f"{self.BASE_URL}/voices"
        headers = {"xi-api-key": self.api_key}

        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None

        voices = resp.json().get("voices", [])

        # 한국어 라벨이 있는 음성 우선
        for voice in voices:
            labels = voice.get("labels", {})
            lang = labels.get("language", "").lower()
            if "korean" in lang or "한국" in lang or "ko" in lang:
                print(f"    🎤 ElevenLabs 한국어 음성 발견: "
                      f"{voice['name']} ({voice['voice_id']})")
                return voice["voice_id"]

        # 내 음성 라이브러리에서 첫 번째 반환
        if voices:
            v = voices[0]
            print(f"    🎤 ElevenLabs 기본 음성 사용: "
                  f"{v['name']} ({v['voice_id']})")
            return v["voice_id"]

        return None

    @staticmethod
    def _measure_duration_fallback(audio_path: str) -> int:
        """ffprobe 없이 MP3 파일 길이 추정 (파일 크기 기반)

        MP3 128kbps → 약 16KB/초
        """
        try:
            size = os.path.getsize(audio_path)
            return int((size / 16000) * 1000)  # bytes → ms
        except Exception:
            return 2000  # 2초 폴백
