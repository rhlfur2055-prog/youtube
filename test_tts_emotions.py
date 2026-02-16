"""TTS 감정 비교 테스트 스크립트.

3가지 감정(neutral, whisper, shocked)으로 같은 문장을 생성하여
음성 톤 변화를 확인합니다.
"""

from youshorts.core.tts_enhanced import EnhancedTTSEngine

# 테스트 문장
TEST_TEXT = "그날 밤, 그는 평소처럼 모텔에 들어갔다. 그런데 카톡을 열어본 순간, 모든 것이 거짓이었다는 걸 알게 됐다."

# 테스트 감정
EMOTIONS = ["neutral", "whisper", "shocked"]


def main():
    """메인 테스트 함수."""
    print("=" * 60)
    print("   TTS 감정 비교 테스트")
    print("=" * 60)
    print()

    engine = EnhancedTTSEngine()
    print(f"현재 TTS 제공자: {engine.provider.value}")
    print(f"테스트 문장: {TEST_TEXT[:50]}...")
    print()

    results = []

    for emotion in EMOTIONS:
        print(f"[{emotion}] 생성 중...")
        try:
            output_path = f"test_{emotion}.mp3"
            audio_path = engine.generate_sentence(
                TEST_TEXT,
                emotion=emotion,
                output_path=output_path,
            )
            results.append((emotion, audio_path, "✅ 성공"))
            print(f"  → {audio_path}")
        except Exception as e:
            results.append((emotion, "", f"❌ 실패: {e}"))
            print(f"  → 실패: {e}")
        print()

    # 결과 요약
    print("=" * 60)
    print("   테스트 결과 요약")
    print("=" * 60)
    for emotion, path, status in results:
        print(f"  {emotion:10s} : {status}")
        if path:
            print(f"             → {path}")
    print()

    # 비교 가이드
    print("=" * 60)
    print("   음성 비교 방법")
    print("=" * 60)
    print("1. 생성된 MP3 파일을 순서대로 재생")
    print("2. neutral → whisper → shocked 순서로 들어보기")
    print("3. 톤, 속도, 감정 표현 차이 확인")
    print()
    print("[기대 결과]")
    print("  neutral : 평범한 톤, 일정한 속도")
    print("  whisper : 낮은 톤, 느린 속도, 긴장감")
    print("  shocked : 높은 톤, 빠른 속도, 놀람 표현")
    print()

    # 제공자별 기대치
    if engine.provider.value == "elevenlabs":
        print("✅ ElevenLabs: 감정 차이가 명확하게 들림")
    elif engine.provider.value == "openai":
        print("⚠️ OpenAI: 감정 차이가 약간 들림 (속도 위주)")
    else:
        print("❌ edge-tts: 감정 차이가 거의 없음 (속도만 변화)")

    print("=" * 60)


if __name__ == "__main__":
    main()
