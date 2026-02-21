"""
OpenAI TTS 모듈 — YouShorts v6.0
─ tts-1-hd 모델, 한국어 자연스러운 음성
─ 감정별 speed 파라미터 동적 조절
─ Word timestamps 미지원 (문장 레벨만)
─ 최대 3회 Retry + 지수 백오프
"""

import os
import time
import asyncio
import requests


class OpenAITTS:
    """OpenAI TTS (tts-1-hd) with emotion-based speed control."""

    BASE_URL = "https://api.openai.com/v1/audio/speech"
    MAX_RETRIES = 4
    RETRY_DELAYS = [2, 8, 25, 60]  # 지수 백오프 — 429에서 최대 95초 버팀

    # ── 감정별 speed 매핑 (0.25 ~ 4.0) ──
    EMOTION_SPEED = {
        "neutral":  1.00,
        "tension":  1.10,
        "surprise": 0.95,
        "anger":    1.05,
        "angry":    1.05,
        "sad":      0.90,
        "fun":      1.10,
        "funny":    1.10,
        "shock":    0.90,
        "shocked":  0.90,
        "relief":   1.00,
        "excited":  1.15,
        "warm":     0.95,
        "serious":  1.00,
        "whisper":  0.85,
    }

    # 한국어 추천 음성
    VOICES = ["nova", "alloy", "shimmer", "echo", "fable", "onyx"]

    def __init__(
        self,
        api_key: str,
        voice: str = "nova",
        model: str = "tts-1-hd",
    ):
        self.api_key = api_key
        self.voice = voice if voice in self.VOICES else "nova"
        self.model = model

    async def generate_sentence(
        self, text: str, emotion: str, output_path: str
    ) -> dict:
        """한 문장의 TTS를 생성한다.

        Word-level timestamps는 미지원 (OpenAI TTS 한계).
        Duration은 ffprobe 또는 파일 크기 기반으로 측정.

        Returns:
            {
                "audio_file": str,
                "duration_ms": int,
                "word_timings": []
            }
        """
        speed = self._get_speed(emotion)

        # v6.0 지수 백오프: 401은 즉시 포기, 429는 장기 대기 후 재시도
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._api_call(text, speed, output_path),
                )
                return result
            except ValueError as e:
                # 401 Unauthorized → API 키 자체가 무효, 재시도 무의미
                raise RuntimeError(f"OpenAI 인증 실패 (재시도 안 함): {e}")
            except Exception as e:
                last_error = e
                err_str = str(e)
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAYS[attempt]
                    # 429 Rate Limit → 서버 쿨다운까지 길게 대기
                    if "429" in err_str:
                        delay = max(delay, 15 * (attempt + 1))  # 15, 30, 45, 60초
                    print(f"    ⚠️  OpenAI TTS 재시도 {attempt + 1}/{self.MAX_RETRIES} "
                          f"({delay}초 후): {e}")
                    await asyncio.sleep(delay)

        raise RuntimeError(f"OpenAI TTS {self.MAX_RETRIES}회 실패: {last_error}")

    def _api_call(self, text: str, speed: float, output_path: str) -> dict:
        """동기 HTTP 호출: POST /v1/audio/speech"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "speed": speed,
            "response_format": "mp3",
        }

        resp = requests.post(
            self.BASE_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )

        if resp.status_code == 401:
            raise ValueError("OpenAI API 키 무효 (401 Unauthorized)")
        if resp.status_code == 429:
            raise RuntimeError("OpenAI 요청 한도 초과 (429 Too Many Requests)")
        if resp.status_code != 200:
            raise RuntimeError(
                f"OpenAI TTS 오류 {resp.status_code}: {resp.text[:200]}"
            )

        # 오디오 저장
        audio_bytes = resp.content
        if len(audio_bytes) < 500:
            raise ValueError(f"오디오 크기 너무 작음: {len(audio_bytes)} bytes")

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        # Duration 측정 (파일 크기 기반 추정)
        duration_ms = self._estimate_duration(output_path)

        return {
            "audio_file": output_path,
            "duration_ms": duration_ms,
            "word_timings": [],  # OpenAI TTS는 word timestamps 미지원
        }

    def _get_speed(self, emotion: str) -> float:
        """감정 키 → speed 파라미터 (0.25~4.0)"""
        speed = self.EMOTION_SPEED.get(emotion, 1.0)
        return max(0.25, min(4.0, speed))

    @staticmethod
    def _estimate_duration(audio_path: str) -> int:
        """MP3 파일 길이 추정

        1순위: ffprobe (정확)
        2순위: 파일 크기 기반 (MP3 128kbps ≈ 16KB/초)
        """
        # ffprobe 시도
        try:
            import subprocess
            # FFPROBE_PATH가 전역에 있을 수 있으나, 독립 모듈이므로 직접 탐색
            for probe_name in ["ffprobe", "ffprobe.exe"]:
                try:
                    result = subprocess.run(
                        [probe_name, "-v", "quiet", "-show_entries",
                         "format=duration", "-of",
                         "default=noprint_wrappers=1:nokey=1",
                         audio_path],
                        capture_output=True, text=True, timeout=5,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        return int(float(result.stdout.strip()) * 1000)
                except FileNotFoundError:
                    continue
        except Exception:
            pass

        # 파일 크기 기반 추정 (128kbps MP3)
        try:
            size = os.path.getsize(audio_path)
            return int((size / 16000) * 1000)
        except Exception:
            return 2000
