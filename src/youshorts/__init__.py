"""YouTube Shorts 자동 생성 파이프라인.

CLI 명령 하나로 YouTube Shorts 영상을 자동 생성합니다.

파이프라인:
    대본 생성 → 품질 검사 → 독창성 체크 → TTS →
    배경 다운로드 → 영상 합성 → 메타데이터 → 히스토리 저장
"""

__version__ = "2.0.0"
__author__ = "YouShorts Team"
