# 변경 사유: 비정상 파일 자동 정리 모듈 생성 (백업 없이 즉시 삭제)
"""비정상 파일 정리 유틸리티.

output/ 폴더의 비정상 MP4, 임시 작업 디렉토리, 깨진 캐시 파일 등을
자동으로 감지하고 즉시 삭제합니다. 백업하지 않습니다.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from youshorts.config.settings import Settings, get_settings
from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

# 비정상 판별 기준
MIN_VALID_MP4_SIZE = 30 * 1024 * 1024  # 30MB 미만은 비정상
MIN_VALID_DURATION = 30.0  # 30초 미만은 비정상
MIN_VALID_TTS_SIZE = 1024  # 1KB 미만 TTS는 비정상
MAX_STALE_WORK_HOURS = 24  # 24시간 이상된 _work_* 삭제
RENDER_FAIL_THRESHOLD = 22  # 렌더링 22% 이하 중단 판별


def _get_mp4_duration(file_path: str) -> float:
    """MP4 파일의 재생 시간을 ffmpeg로 측정합니다.

    Args:
        file_path: MP4 파일 경로.

    Returns:
        재생 시간 (초). 측정 실패 시 0.0 반환.
    """
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, Exception):
        ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"

    try:
        cmd = [ffmpeg_exe, "-i", file_path]
        result = subprocess.run(
            cmd, capture_output=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        if match:
            h, m, s = match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return 0.0


def _is_audio_broken(file_path: str) -> bool:
    """오디오 파일이 깨졌는지 확인합니다.

    pydub로 로드 시도하여 실패하면 깨진 파일로 판정합니다.

    Args:
        file_path: 오디오 파일 경로.

    Returns:
        깨진 파일 여부.
    """
    # 0KB 파일은 즉시 깨진 것으로 판정
    if os.path.getsize(file_path) == 0:
        return True

    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(file_path)
        # 1초 미만이면 깨진 것으로 간주
        return len(audio) < 1000
    except Exception:
        # pydub 로드 실패 → ffmpeg으로 재시도
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, Exception):
            ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"

        try:
            cmd = [ffmpeg_exe, "-i", file_path, "-f", "null", "-"]
            result = subprocess.run(
                cmd, capture_output=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            return result.returncode != 0
        except Exception:
            return True


class CleanupManager:
    """비정상 파일 정리 관리자.

    output/, cache/, temp/, __pycache__ 등에서 비정상 파일을
    감지하고 즉시 삭제합니다. 백업하지 않습니다.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """정리 관리자를 초기화합니다.

        Args:
            settings: 설정 인스턴스.
        """
        self.settings = settings or get_settings()
        self.deleted_files: list[str] = []
        self.deleted_dirs: list[str] = []
        self.total_freed: int = 0

    def clean_all(self) -> dict[str, Any]:
        """output/ 폴더의 비정상 파일을 전부 삭제합니다.

        판별 기준:
        - MP4 파일 크기 30MB 미만
        - MP4 파일 duration 30초 미만
        - 0KB 파일 전부
        - 연결된 _work_*/ 디렉토리 함께 삭제
        - 관련 메타데이터 JSON도 삭제

        Returns:
            삭제 결과 요약 딕셔너리.
        """
        output_dir = self.settings.output_dir
        if not os.path.isdir(output_dir):
            logger.info("output/ 폴더가 없습니다: %s", output_dir)
            return self._summary()

        logger.info("=" * 50)
        logger.info("비정상 파일 정리 시작: %s", output_dir)
        logger.info("=" * 50)

        # 1. output/ 내 MP4 파일 스캔
        for name in os.listdir(output_dir):
            file_path = os.path.join(output_dir, name)

            # 디렉토리는 _work_* 처리에서 별도 처리
            if os.path.isdir(file_path):
                continue

            # MP4 파일 검사
            if name.lower().endswith(".mp4"):
                self._check_and_delete_mp4(file_path)

            # 0KB 파일 즉시 삭제
            elif os.path.isfile(file_path) and os.path.getsize(file_path) == 0:
                self._delete_file(file_path, "0KB 파일")

        # 2. 삭제된 MP4에 연결된 _work_*/ 디렉토리 삭제
        self._clean_orphan_work_dirs(output_dir)

        # 3. 삭제된 MP4에 연결된 메타데이터 JSON 삭제
        self._clean_orphan_metadata(output_dir)

        logger.info("=" * 50)
        logger.info(
            "정리 완료: %d개 파일, %d개 디렉토리 삭제 (%.1f MB 확보)",
            len(self.deleted_files), len(self.deleted_dirs),
            self.total_freed / 1024 / 1024,
        )
        logger.info("=" * 50)

        return self._summary()

    def clean_temp(self) -> dict[str, Any]:
        """임시 파일 및 캐시를 정리합니다.

        - cache/tts/ 에서 깨진 오디오 파일 삭제
        - _work_*/ 중 24시간 이상된 디렉토리 삭제
        - __pycache__ 디렉토리 전부 삭제
        - temp/ 폴더 정리 (현재 렌더링 중이 아닐 때)

        Returns:
            삭제 결과 요약 딕셔너리.
        """
        logger.info("임시 파일 정리 시작")

        # 1. cache/tts/ 깨진 오디오 삭제
        cache_tts_dir = os.path.join(self.settings.data_dir, "..", "cache", "tts")
        cache_tts_dir = os.path.normpath(cache_tts_dir)
        if os.path.isdir(cache_tts_dir):
            self._clean_broken_audio(cache_tts_dir)

        # 2. 24시간 이상된 _work_* 디렉토리 삭제
        output_dir = self.settings.output_dir
        if os.path.isdir(output_dir):
            self._clean_stale_work_dirs(output_dir)

        # 3. __pycache__ 전부 삭제
        project_root = Path(self.settings.project_dir)
        self._clean_pycache(str(project_root))

        # 4. temp/ 폴더 정리
        temp_dir = self.settings.temp_dir
        if os.path.isdir(temp_dir):
            self._clean_temp_dir(temp_dir)

        logger.info(
            "임시 파일 정리 완료: %d개 파일, %d개 디렉토리 삭제 (%.1f MB 확보)",
            len(self.deleted_files), len(self.deleted_dirs),
            self.total_freed / 1024 / 1024,
        )

        return self._summary()

    def _check_and_delete_mp4(self, file_path: str) -> None:
        """MP4 파일이 비정상인지 검사하고 삭제합니다.

        Args:
            file_path: MP4 파일 경로.
        """
        file_size = os.path.getsize(file_path)
        name = os.path.basename(file_path)

        # 0KB 파일 즉시 삭제
        if file_size == 0:
            self._delete_file(file_path, "0KB MP4 파일")
            return

        # 30MB 미만 → 비정상
        if file_size < MIN_VALID_MP4_SIZE:
            self._delete_file(
                file_path,
                f"크기 미달 ({file_size / 1024 / 1024:.1f}MB < 30MB)",
            )
            return

        # duration 30초 미만 → 비정상
        duration = _get_mp4_duration(file_path)
        if 0 < duration < MIN_VALID_DURATION:
            self._delete_file(
                file_path,
                f"길이 미달 ({duration:.1f}초 < 30초)",
            )
            return

    def _clean_orphan_work_dirs(self, output_dir: str) -> None:
        """완료되지 않은 _work_*/ 디렉토리를 삭제합니다.

        Args:
            output_dir: output/ 폴더 경로.
        """
        for name in os.listdir(output_dir):
            if not name.startswith("_work_"):
                continue
            dir_path = os.path.join(output_dir, name)
            if not os.path.isdir(dir_path):
                continue
            self._delete_dir(dir_path, "임시 작업 디렉토리")

    def _clean_orphan_metadata(self, output_dir: str) -> None:
        """고아 메타데이터 JSON을 삭제합니다.

        연결된 MP4가 없는 _meta.json 파일을 삭제합니다.

        Args:
            output_dir: output/ 폴더 경로.
        """
        for name in os.listdir(output_dir):
            if not name.endswith("_meta.json"):
                continue
            # _meta.json에 대응하는 MP4 파일 확인
            mp4_name = name.replace("_meta.json", ".mp4")
            mp4_path = os.path.join(output_dir, mp4_name)
            if not os.path.exists(mp4_path):
                meta_path = os.path.join(output_dir, name)
                self._delete_file(meta_path, "고아 메타데이터 (MP4 없음)")

    def _clean_broken_audio(self, cache_dir: str) -> None:
        """깨진 오디오 파일을 삭제합니다.

        Args:
            cache_dir: 캐시 디렉토리 경로.
        """
        if not os.path.isdir(cache_dir):
            return

        for name in os.listdir(cache_dir):
            if not name.endswith((".mp3", ".wav", ".ogg")):
                continue
            file_path = os.path.join(cache_dir, name)
            if not os.path.isfile(file_path):
                continue

            file_size = os.path.getsize(file_path)

            # 0KB 즉시 삭제
            if file_size == 0:
                self._delete_file(file_path, "0KB 캐시 오디오")
                continue

            # 1KB 미만 → 비정상
            if file_size < MIN_VALID_TTS_SIZE:
                self._delete_file(file_path, f"크기 미달 ({file_size} bytes)")
                continue

            # pydub/ffmpeg로 로드 불가 → 깨진 파일
            if _is_audio_broken(file_path):
                self._delete_file(file_path, "깨진 오디오 파일")

    def _clean_stale_work_dirs(self, output_dir: str) -> None:
        """24시간 이상된 _work_* 디렉토리를 삭제합니다.

        Args:
            output_dir: output/ 폴더 경로.
        """
        now = time.time()
        cutoff = now - (MAX_STALE_WORK_HOURS * 3600)

        for name in os.listdir(output_dir):
            if not name.startswith("_work_"):
                continue
            dir_path = os.path.join(output_dir, name)
            if not os.path.isdir(dir_path):
                continue

            # 마지막 수정 시간 확인
            mtime = os.path.getmtime(dir_path)
            if mtime < cutoff:
                hours_old = (now - mtime) / 3600
                self._delete_dir(
                    dir_path,
                    f"24시간 이상 경과 ({hours_old:.0f}시간)",
                )

    def _clean_pycache(self, root_dir: str) -> None:
        """__pycache__ 디렉토리를 전부 삭제합니다.

        Args:
            root_dir: 프로젝트 루트 경로.
        """
        for dirpath, dirnames, _ in os.walk(root_dir):
            # .git 디렉토리 내부는 건너뛰기
            if ".git" in dirpath:
                continue
            for dirname in dirnames:
                if dirname == "__pycache__":
                    cache_path = os.path.join(dirpath, dirname)
                    self._delete_dir(cache_path, "__pycache__")

    def _clean_temp_dir(self, temp_dir: str) -> None:
        """temp/ 폴더의 오래된 파일을 삭제합니다.

        Args:
            temp_dir: temp/ 폴더 경로.
        """
        if not os.path.isdir(temp_dir):
            return

        now = time.time()
        # 1시간 이상된 임시 파일 삭제
        cutoff = now - 3600

        for name in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, name)
            if not os.path.isfile(file_path):
                continue

            mtime = os.path.getmtime(file_path)
            if mtime < cutoff:
                self._delete_file(file_path, "오래된 임시 파일")

    def _delete_file(self, file_path: str, reason: str) -> None:
        """파일을 즉시 삭제합니다 (백업 없음).

        Args:
            file_path: 삭제할 파일 경로.
            reason: 삭제 사유.
        """
        try:
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            os.remove(file_path)
            self.deleted_files.append(file_path)
            self.total_freed += file_size
            size_str = f"{file_size / 1024 / 1024:.1f}MB" if file_size > 1024 * 1024 else f"{file_size / 1024:.1f}KB"
            logger.info("삭제: %s (%s) [%s]", os.path.basename(file_path), size_str, reason)
        except Exception as e:
            logger.warning("삭제 실패: %s - %s", file_path, e)

    def _delete_dir(self, dir_path: str, reason: str) -> None:
        """디렉토리를 즉시 삭제합니다 (백업 없음).

        Args:
            dir_path: 삭제할 디렉토리 경로.
            reason: 삭제 사유.
        """
        try:
            # 디렉토리 크기 계산
            dir_size = 0
            for dirpath, _, filenames in os.walk(dir_path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        dir_size += os.path.getsize(fp)
                    except OSError:
                        pass

            shutil.rmtree(dir_path, ignore_errors=True)
            self.deleted_dirs.append(dir_path)
            self.total_freed += dir_size
            size_str = f"{dir_size / 1024 / 1024:.1f}MB" if dir_size > 1024 * 1024 else f"{dir_size / 1024:.1f}KB"
            logger.info("삭제 (폴더): %s (%s) [%s]", os.path.basename(dir_path), size_str, reason)
        except Exception as e:
            logger.warning("디렉토리 삭제 실패: %s - %s", dir_path, e)

    def _summary(self) -> dict[str, Any]:
        """삭제 결과 요약을 반환합니다.

        Returns:
            요약 딕셔너리.
        """
        return {
            "deleted_files": self.deleted_files,
            "deleted_dirs": self.deleted_dirs,
            "file_count": len(self.deleted_files),
            "dir_count": len(self.deleted_dirs),
            "freed_bytes": self.total_freed,
            "freed_mb": round(self.total_freed / 1024 / 1024, 1),
        }
