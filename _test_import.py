"""임시 임포트 테스트 스크립트."""
import sys
sys.path.insert(0, ".")

try:
    from youshorts.core.tts_engine import generate_tts, generate_fitted_tts, check_ffmpeg_available
    print("TTS import OK")

    ffmpeg = check_ffmpeg_available()
    print(f"ffmpeg path: {ffmpeg}")

    from youshorts.config.settings import get_settings
    s = get_settings()
    print(f"tts_engine: {s.tts_engine}")
    print(f"tts_voice: {s.tts_voice}")
    print(f"tts_rate: {s.tts_rate}")
    print(f"tts_pitch: {s.tts_pitch}")

    print("\nALL CHECKS PASSED")
except Exception as e:
    print(f"IMPORT FAILED: {e}")
    import traceback
    traceback.print_exc()
