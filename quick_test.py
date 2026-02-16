#!/usr/bin/env python3
"""빠른 양산 테스트 스크립트."""

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from youshorts.config.settings import get_settings
from youshorts.core.pipeline import Pipeline
from youshorts.utils.logger import setup_logging

def main():
    """빠른 테스트 실행."""
    print("=" * 60)
    print("youshorts 양산 체제 검증 테스트")
    print("=" * 60)

    # 로깅 설정
    settings = get_settings()
    setup_logging(level=20, log_dir=settings.logs_dir)  # INFO level

    # TTS 엔진 설정 (legacy = 빠름)
    object.__setattr__(settings, "tts_engine", "legacy")

    # 테스트 주제
    topic = "재미있는 실화"

    print(f"\n주제: {topic}")
    print(f"스타일: creative")
    print(f"TTS: legacy (edge-tts)\n")

    try:
        # 파이프라인 실행
        pipeline = Pipeline(
            topic=topic,
            style="creative",
            no_pexels=True,  # 빠른 테스트를 위해 그라데이션 사용
            settings=settings,
        )

        result = pipeline.run()

        # 결과 출력
        print("\n" + "=" * 60)
        if result.success:
            print("✓ 테스트 성공!")
            print(f"  영상: {result.output_path}")
            print(f"  제목: {result.metadata.get('title', topic)}")
            print(f"  길이: {result.tts_duration:.1f}초")
            print(f"  품질: {result.quality_score}/100")
            print(f"  편집: {result.edit_style}")
            print("=" * 60)
            return 0
        else:
            print("✗ 테스트 실패")
            print("=" * 60)
            return 1

    except Exception as e:
        print(f"\n✗ 에러 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
