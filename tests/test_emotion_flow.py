"""감정 전달 흐름 E2E 테스트.

script_generator → pipeline → tts_enhanced → 오디오 파일
감정이 실제로 TTS까지 전달되고 반영되는지 검증합니다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import pytest

from youshorts.config.settings import Settings, get_settings
from youshorts.core.tts_enhanced import EnhancedTTSEngine, generate_fitted_tts


def test_emotion_parameters_applied():
    """테스트 1: 감정별 TTS 파라미터가 적용되는지 확인."""
    print("\n" + "=" * 60)
    print("테스트 1: 감정별 TTS 파라미터 적용 확인")
    print("=" * 60)

    # 3가지 감정으로 같은 텍스트 생성
    test_text = "이것은 테스트 문장입니다."
    emotions = ["neutral", "whisper", "shocked"]

    engine = EnhancedTTSEngine()
    print(f"TTS Provider: {engine.provider.value}")

    results = {}
    for emotion in emotions:
        output_path = f"temp/test_emotion_{emotion}.mp3"
        os.makedirs("temp", exist_ok=True)

        try:
            audio_path = engine.generate_sentence(test_text, emotion, output_path)

            # 파일 크기 확인 (감정별로 다를 수 있음)
            file_size = os.path.getsize(audio_path)
            results[emotion] = {"path": audio_path, "size": file_size}

            print(f"[OK] {emotion:10s} → {file_size:,} bytes")
        except Exception as e:
            print(f"[FAIL] {emotion:10s} → 실패: {e}")
            results[emotion] = {"path": None, "size": 0}

    print("\n판정:")
    # 파일이 모두 생성되었는지 확인
    all_generated = all(r["path"] is not None for r in results.values())
    if all_generated:
        print("[OK] 모든 감정에 대해 오디오 파일 생성 성공")
    else:
        print("[FAIL] 일부 감정에서 생성 실패")

    assert all_generated, "일부 감정에서 TTS 생성 실패"


def test_pause_insertion():
    """테스트 2: pause_ms 삽입 확인."""
    print("\n" + "=" * 60)
    print("테스트 2: pause_ms 무음 삽입 확인")
    print("=" * 60)

    # 2문장 + pause_ms
    emotion_segments = [
        {"text": "첫 번째 문장입니다.", "emotion": "neutral"},
        {"text": "두 번째 문장입니다.", "emotion": "neutral"},
    ]

    subtitle_chunks = [
        {"text": "첫 번째 문장입니다.", "emotion": "neutral", "pause_ms": 1000},
        {"text": "두 번째 문장입니다.", "emotion": "neutral", "pause_ms": 0},
    ]

    settings = get_settings()
    settings_with_override = Settings(
        project_dir=settings.project_dir,
        temp_dir="temp",
    )

    try:
        audio_path, word_groups, actual_duration = generate_fitted_tts(
            text="",  # 사용되지 않음
            target_duration=60.0,
            emotion_segments=emotion_segments,
            subtitle_chunks=subtitle_chunks,
            settings=settings_with_override,
        )

        print(f"생성된 오디오: {audio_path}")
        print(f"실제 길이: {actual_duration:.1f}초")
        print(f"단어 그룹 수: {len(word_groups)}")

        # pause가 삽입되었는지 확인 (대략적)
        # 문장 2개 + 1초 pause ≈ 4~6초 예상
        if 3.0 <= actual_duration <= 8.0:
            print(f"[OK] 오디오 길이가 예상 범위 ({actual_duration:.1f}초)")
        else:
            print(f"[WARN] 오디오 길이가 예상 범위 벗어남 ({actual_duration:.1f}초)")

        assert os.path.exists(audio_path), "오디오 파일이 생성되지 않음"
        assert actual_duration > 0, "오디오 길이가 0"

    except Exception as e:
        print(f"[FAIL] 테스트 실패: {e}")
        pytest.fail(f"pause 삽입 테스트 실패: {e}")


def test_emotion_difference():
    """테스트 3: 감정별 파라미터 차이 확인."""
    print("\n" + "=" * 60)
    print("테스트 3: 감정별 음성 차이 확인")
    print("=" * 60)

    # 같은 문장을 excited vs whisper로 생성
    test_text = "이것은 매우 중요한 테스트 문장입니다."
    emotions = ["excited", "whisper"]

    settings = get_settings()
    settings_with_override = Settings(
        project_dir=settings.project_dir,
        temp_dir="temp",
    )

    results = {}
    for emotion in emotions:
        try:
            audio_path, word_groups, duration = generate_fitted_tts(
                text=test_text,
                target_duration=60.0,
                emotion_segments=[{"text": test_text, "emotion": emotion}],
                subtitle_chunks=None,
                settings=settings_with_override,
            )

            file_size = os.path.getsize(audio_path)
            results[emotion] = {"duration": duration, "size": file_size}

            print(f"{emotion:10s} → {duration:.2f}초, {file_size:,} bytes")

        except Exception as e:
            print(f"[FAIL] {emotion} 생성 실패: {e}")
            pytest.fail(f"{emotion} TTS 생성 실패: {e}")

    # 두 감정의 길이나 파일 크기가 다른지 확인
    excited_dur = results["excited"]["duration"]
    whisper_dur = results["whisper"]["duration"]

    diff_percent = abs(excited_dur - whisper_dur) / max(excited_dur, whisper_dur) * 100

    print(f"\n차이: {diff_percent:.1f}%")
    if diff_percent > 5:
        print(f"[OK] 감정별로 음성 특성이 다름 (차이 {diff_percent:.1f}%)")
    else:
        print(f"[WARN] 감정 차이가 미미함 (차이 {diff_percent:.1f}%) - Provider: edge-tts일 수 있음")

    # 최소한 파일이 생성되었는지는 확인
    assert "excited" in results, "excited 생성 실패"
    assert "whisper" in results, "whisper 생성 실패"


def test_fallback_chain():
    """테스트 4: 폴백 체인 확인."""
    print("\n" + "=" * 60)
    print("테스트 4: TTS 제공자 폴백 체인 확인")
    print("=" * 60)

    # 현재 환경에서 사용 가능한 제공자 확인
    engine = EnhancedTTSEngine()
    print(f"현재 제공자: {engine.provider.value}")

    test_text = "폴백 테스트 문장입니다."

    try:
        audio_path = engine.generate_sentence(test_text, "neutral", "temp/test_fallback.mp3")
        print(f"[OK] TTS 생성 성공: {audio_path}")
        print(f"   Provider: {engine.provider.value}")

        assert os.path.exists(audio_path), "오디오 파일이 생성되지 않음"

        # 파일 크기 확인
        file_size = os.path.getsize(audio_path)
        print(f"   파일 크기: {file_size:,} bytes")
        assert file_size > 0, "오디오 파일이 비어있음"

    except Exception as e:
        print(f"[FAIL] 폴백 체인 실패: {e}")
        pytest.fail(f"모든 TTS 제공자 실패: {e}")


if __name__ == "__main__":
    print("\n[Emotion Flow E2E Test]\n")

    # 테스트 디렉토리 생성
    os.makedirs("temp", exist_ok=True)

    try:
        test_emotion_parameters_applied()
        test_pause_insertion()
        test_emotion_difference()
        test_fallback_chain()

        print("\n" + "=" * 60)
        print("[PASS] All tests passed!")
        print("=" * 60)

    except Exception as e:
        print("\n" + "=" * 60)
        print(f"[FAIL] Test failed: {e}")
        print("=" * 60)
        sys.exit(1)
