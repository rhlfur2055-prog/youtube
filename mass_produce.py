#!/usr/bin/env python3
"""
=============================================================
🏭 YouTube Shorts 대량 생산 v6.0
=============================================================
main.py를 subprocess로 반복 호출하여 숏츠를 자동 대량 생산.

v6.0 신규:
  ─ topics.txt 큐: 라인별 주제를 순차 소화 (완료 시 자동 삭제)
  ─ stories/ 폴더: 사전 준비된 script.json 자동 소화
  ─ --tts-engine 전달: auto / elevenlabs / openai / edge
  ─ --daemon 모드: 크롤링 큐 자동 리필 + 무한 루프
  ─ 크롤링 소스: 커뮤니티 4소스 (viral 통합)

AI 슬롭 방지:
  ─ 하루 최대 생산 제한 (기본 10개)
  ─ TTS 음성 로테이션 (3개 음성)
  ─ 영상 간 최소 60초 딜레이
  ─ 24시간 최대 런타임 안전장치

사용법:
  python mass_produce.py                              # 바이럴 크롤링 3개
  python mass_produce.py --count 5                    # 5개 생산
  python mass_produce.py --count 3 --topic "AI 혁명"  # 고정 주제 3개
  python mass_produce.py --topics-file topics.txt     # 큐 파일에서 주제 소화
  python mass_produce.py --stories-dir stories/       # script.json 소화
  python mass_produce.py --daemon                     # 무한 루프 (크롤링 자동)
  python mass_produce.py --tts-engine elevenlabs      # TTS 엔진 지정
  python mass_produce.py --delay 180                  # 3분 간격
  python mass_produce.py --clean                      # 비정상 파일 정리
=============================================================
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import random
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, date
from pathlib import Path

# Windows CP949 인코딩 에러 방지
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# ============================================================
# 설정
# ============================================================
SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable
OUTPUT_DIR = SCRIPT_DIR / "output"
LOG_DIR = SCRIPT_DIR / "logs"
HISTORY_FILE = SCRIPT_DIR / "data" / "mass_produce_history.json"

# TTS 음성 로테이션 (AI 슬롭 방지 — edge-tts 무료 음성 3개)
EDGE_TTS_VOICES = [
    "ko-KR-InJoonNeural",   # 남성 (차분한)
    "ko-KR-HyunsuNeural",   # 남성 (에너지)
    "ko-KR-SunHiNeural",    # 여성 (밝은)
]

# 크롤링 소스 (v6.0: 커뮤니티 4소스 기반)
VALID_SOURCES = ["viral", "natepann", "instiz", "fmkorea", "dcinside"]


# ============================================================
# 히스토리 관리 (하루 생산량 추적)
# ============================================================
def _load_history() -> dict:
    """생산 히스토리 로드"""
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"daily": {}, "total": 0}


def _save_history(history: dict) -> None:
    """생산 히스토리 저장"""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _get_today_count(history: dict) -> int:
    """오늘 생산 개수"""
    today = date.today().isoformat()
    return history.get("daily", {}).get(today, 0)


def _increment_today(history: dict) -> None:
    """오늘 생산 카운트 +1"""
    today = date.today().isoformat()
    if "daily" not in history:
        history["daily"] = {}
    history["daily"][today] = history["daily"].get(today, 0) + 1
    history["total"] = history.get("total", 0) + 1


# ============================================================
# topics.txt 큐 관리
# ============================================================
def _load_topics_queue(path: str) -> list[str]:
    """topics.txt에서 주제 목록 로드 (빈 줄/주석 제외)"""
    topics = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    topics.append(line)
    except FileNotFoundError:
        print(f"  ⚠️  {path} 파일 없음")
    return topics


def _pop_topic_from_file(path: str) -> str | None:
    """topics.txt에서 첫 번째 주제를 가져오고 파일에서 제거"""
    topics = _load_topics_queue(path)
    if not topics:
        return None

    topic = topics[0]
    remaining = topics[1:]

    # 남은 항목들로 파일 다시 쓰기
    with open(path, "w", encoding="utf-8") as f:
        for t in remaining:
            f.write(t + "\n")

    return topic


# ============================================================
# stories/ 폴더 관리
# ============================================================
def _find_story_jsons(stories_dir: str) -> list[str]:
    """stories/ 폴더에서 처리할 script.json 파일 목록 반환"""
    pattern = os.path.join(stories_dir, "*.json")
    files = sorted(glob.glob(pattern))
    return files


def _archive_story(json_path: str) -> None:
    """처리 완료된 script.json을 stories/_done/으로 이동"""
    done_dir = os.path.join(os.path.dirname(json_path), "_done")
    os.makedirs(done_dir, exist_ok=True)
    dest = os.path.join(done_dir, os.path.basename(json_path))
    # 중복 방지
    if os.path.exists(dest):
        base, ext = os.path.splitext(os.path.basename(json_path))
        dest = os.path.join(done_dir, f"{base}_{int(time.time())}{ext}")
    shutil.move(json_path, dest)
    print(f"  📦 아카이브: {os.path.basename(json_path)} → _done/")


# ============================================================
# 단일 영상 생산
# ============================================================
def run_single(
    source: str,
    topic: str | None,
    script_json: str | None,
    voice: str,
    tts_engine: str,
    output_dir: str,
    index: int,
) -> tuple[bool, str]:
    """단일 영상을 생산합니다.

    Args:
        source: 크롤링 소스 (viral, natepann 등)
        topic: 수동 주제 (None이면 자동 크롤링)
        script_json: 사전 준비된 script.json 경로 (None이면 자동 생성)
        voice: edge-tts 음성
        tts_engine: TTS 엔진 (auto/elevenlabs/openai/edge)
        output_dir: 출력 경로
        index: 현재 인덱스

    Returns:
        (성공 여부, 출력 경로 또는 에러 메시지)
    """
    mode_label = "📜 script.json" if script_json else (f"📝 주제: {topic}" if topic else f"🌐 크롤링: {source}")
    print(f"\n{'─' * 60}")
    print(f"  [{index + 1}] 영상 생산 시작")
    print(f"  모드: {mode_label}")
    print(f"  TTS: {tts_engine} | 음성: {voice}")
    print(f"{'─' * 60}")

    # 커맨드 구성
    script = str(SCRIPT_DIR / "main.py")
    cmd = [PYTHON, script]

    if script_json:
        # script.json 모드 (크롤링+Gemini 스킵)
        cmd.extend(["--script-json", script_json])
    elif topic:
        # 주제 지정 모드
        cmd.extend([
            "--topic", topic,
            "--skip-crawl",
            "--count", "1",
        ])
    else:
        # 자동 크롤링 모드
        cmd.extend([
            "--source", source,
            "--count", "1",
        ])

    # 공통 옵션
    cmd.extend([
        "--voice", voice,
        "--tts-engine", tts_engine,
        "--output", output_dir,
    ])

    start_t = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900,  # 15분 타임아웃 (GoAPI Midjourney 폴링 감안)
            cwd=str(SCRIPT_DIR),
            encoding="utf-8",
            errors="replace",
        )

        elapsed = time.time() - start_t

        if result.returncode == 0:
            print(f"  ✅ 성공! ({elapsed:.1f}초)")

            # stdout에서 MP4 경로 찾기
            mp4_files = []
            for line in result.stdout.split("\n"):
                if ".mp4" in line and ("📁" in line or "output" in line.lower()):
                    parts = line.strip().split()
                    for p in parts:
                        if ".mp4" in p:
                            mp4_path = p.strip("()")
                            if os.path.exists(mp4_path):
                                mp4_files.append(mp4_path)

            if mp4_files:
                size_mb = os.path.getsize(mp4_files[0]) / 1024 / 1024
                print(f"  📁 {mp4_files[0]} ({size_mb:.1f}MB)")
                return True, mp4_files[0]
            return True, f"완료 ({elapsed:.1f}초)"
        else:
            print(f"  ❌ 실패 (exit={result.returncode}, {elapsed:.1f}초)")
            # 에러 출력 마지막 10줄
            stderr_lines = result.stderr.strip().split("\n")[-10:]
            for line in stderr_lines:
                print(f"     {line}")
            # stdout에서도 에러 힌트 추출
            stdout_errors = [l for l in result.stdout.split("\n") if "❌" in l or "Error" in l]
            for line in stdout_errors[-3:]:
                print(f"     {line.strip()}")
            return False, f"exit={result.returncode}"

    except subprocess.TimeoutExpired:
        print(f"  ⏰ 타임아웃 (15분 초과)")
        return False, "timeout"
    except Exception as e:
        print(f"  ❌ 에러: {e}")
        return False, str(e)


# ============================================================
# 대량 생산 메인 루프
# ============================================================
def mass_produce(
    count: int,
    source: str,
    topic: str | None,
    topics_file: str | None,
    stories_dir: str | None,
    tts_engine: str,
    delay: int,
    max_retries: int,
    max_per_day: int,
    daemon: bool,
) -> None:
    """대량 생산 메인 로직.

    우선순위:
    1. stories_dir → script.json 소화
    2. topics_file → topics.txt 큐 소화
    3. topic → 고정 주제 반복
    4. source → 자동 크롤링
    """
    history = _load_history()
    today_count = _get_today_count(history)

    # 하루 제한 체크
    remaining = max_per_day - today_count
    if remaining <= 0:
        print(f"⚠️  오늘 이미 {today_count}개 생산 (최대 {max_per_day}개) → 내일 다시 실행")
        return

    output_dir = str(OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    # ── 작업 큐 구성 ──
    job_queue: list[dict] = []

    # 1순위: stories/ 폴더의 script.json
    if stories_dir:
        story_files = _find_story_jsons(stories_dir)
        for sf in story_files:
            job_queue.append({"mode": "story", "script_json": sf, "topic": None})
        if story_files:
            print(f"  📚 stories/ 큐: {len(story_files)}개 script.json 발견")

    # 2순위: topics.txt 큐
    if topics_file and os.path.exists(topics_file):
        topics_list = _load_topics_queue(topics_file)
        for t in topics_list:
            job_queue.append({"mode": "topic", "script_json": None, "topic": t})
        if topics_list:
            print(f"  📋 topics.txt 큐: {len(topics_list)}개 주제 발견")

    # 3순위: 고정 주제 or 자동 크롤링
    if not job_queue:
        if topic:
            for _ in range(count):
                job_queue.append({"mode": "topic", "script_json": None, "topic": topic})
        else:
            for _ in range(count):
                job_queue.append({"mode": "crawl", "script_json": None, "topic": None})

    # 하루 제한 적용
    actual_count = min(len(job_queue), remaining)
    if actual_count < len(job_queue):
        print(f"  ⚠️  큐 {len(job_queue)}개 → {actual_count}개로 제한 (오늘 잔여: {remaining}개)")
    job_queue = job_queue[:actual_count]

    print(f"\n{'=' * 60}")
    print(f"🏭 YouTube Shorts 대량 생산 v6.0")
    print(f"{'=' * 60}")
    print(f"  목표: {actual_count}개")
    print(f"  소스: {source}")
    print(f"  TTS: {tts_engine}")
    print(f"  딜레이: {delay}초")
    print(f"  재시도: {max_retries}회")
    print(f"  하루 제한: {max_per_day}개 (오늘: {today_count}개 완료)")
    if daemon:
        print(f"  🔄 데몬 모드: 큐 소진 시 크롤링 자동 리필")
    print(f"{'=' * 60}")

    produced = 0
    failed = 0
    results = []
    MAX_RUNTIME = 24 * 3600  # 24시간
    run_start = time.time()

    try:
        job_idx = 0
        while job_idx < len(job_queue):
            # 런타임 안전장치
            if time.time() - run_start > MAX_RUNTIME:
                print(f"\n⚠️  24시간 최대 런타임 초과 → 안전 종료")
                break

            # 하루 제한 실시간 체크 (날짜 넘어갈 수 있으므로)
            history = _load_history()
            if _get_today_count(history) >= max_per_day:
                print(f"\n⚠️  오늘 하루 제한 도달 ({max_per_day}개) → 종료")
                break

            job = job_queue[job_idx]

            # TTS 음성 로테이션
            voice = EDGE_TTS_VOICES[job_idx % len(EDGE_TTS_VOICES)]

            # 재시도 루프
            success = False
            for attempt in range(1, max_retries + 1):
                if attempt > 1:
                    retry_delay = min(delay * attempt, 300)
                    print(f"  🔄 재시도 {attempt}/{max_retries} ({retry_delay}초 후)")
                    time.sleep(retry_delay)

                try:
                    success, result_info = run_single(
                        source=source,
                        topic=job["topic"],
                        script_json=job.get("script_json"),
                        voice=voice,
                        tts_engine=tts_engine,
                        output_dir=output_dir,
                        index=job_idx,
                    )
                except Exception as e:
                    print(f"  ❌ run_single 예외: {e}")
                    traceback.print_exc()
                    success = False
                    result_info = str(e)

                if success:
                    produced += 1
                    _increment_today(history)
                    _save_history(history)
                    results.append({
                        "index": job_idx + 1,
                        "status": "success",
                        "mode": job["mode"],
                        "info": result_info,
                    })

                    # story 모드 → 완료된 json 아카이브
                    if job["mode"] == "story" and job.get("script_json"):
                        _archive_story(job["script_json"])

                    # topics.txt 모드 → 처리된 주제 파일에서 제거
                    if job["mode"] == "topic" and topics_file:
                        _pop_topic_from_file(topics_file)

                    break

            if not success:
                failed += 1
                results.append({
                    "index": job_idx + 1,
                    "status": "failed",
                    "mode": job["mode"],
                    "info": result_info,
                })
                print(f"  💀 {max_retries}회 재시도 실패")

            # 진행 상황
            remain = len(job_queue) - job_idx - 1
            print(f"\n  📊 진행: {produced}개 성공 / {failed}개 실패 / {remain}개 남음")

            # 딜레이 (마지막 아이템 제외)
            if job_idx < len(job_queue) - 1:
                actual_delay = max(delay, 60)
                print(f"  ⏳ {actual_delay}초 대기...")
                time.sleep(actual_delay)

            job_idx += 1

            # ── 데몬 모드: 큐 소진 시 크롤링으로 자동 리필 ──
            if daemon and job_idx >= len(job_queue):
                # 하루 제한 체크
                history = _load_history()
                if _get_today_count(history) >= max_per_day:
                    print(f"\n⚠️  데몬: 하루 제한 도달 → 다음 날까지 1시간 대기...")
                    time.sleep(3600)
                    continue

                print(f"\n🔄 데몬: 큐 소진 → 크롤링 자동 리필 (3개)")
                for _ in range(3):
                    job_queue.append({"mode": "crawl", "script_json": None, "topic": None})

                # topics.txt 리로드 (외부에서 추가될 수 있음)
                if topics_file and os.path.exists(topics_file):
                    new_topics = _load_topics_queue(topics_file)
                    for t in new_topics:
                        job_queue.append({"mode": "topic", "script_json": None, "topic": t})
                    if new_topics:
                        print(f"  📋 topics.txt에서 {len(new_topics)}개 주제 추가")

                # stories/ 리로드
                if stories_dir:
                    new_stories = _find_story_jsons(stories_dir)
                    for sf in new_stories:
                        # 이미 큐에 있는지 체크
                        existing = {j.get("script_json") for j in job_queue}
                        if sf not in existing:
                            job_queue.append({"mode": "story", "script_json": sf, "topic": None})
                    if new_stories:
                        print(f"  📚 stories/에서 {len(new_stories)}개 script.json 추가")

    except KeyboardInterrupt:
        print(f"\n\n⚠️  사용자 중단 (Ctrl+C)")

    # ── 최종 리포트 ──
    elapsed = time.time() - run_start
    print(f"\n{'=' * 60}")
    print(f"📊 대량 생산 최종 리포트")
    print(f"{'=' * 60}")
    print(f"  ⏱️  총 소요: {elapsed:.0f}초 ({elapsed/60:.1f}분)")
    print(f"  ✅ 성공: {produced}개")
    print(f"  ❌ 실패: {failed}개")
    if produced + failed > 0:
        rate = produced / (produced + failed) * 100
        print(f"  📈 성공률: {rate:.0f}%")
    print(f"  📁 출력: {output_dir}")
    print(f"{'=' * 60}")

    # 결과 로그 저장
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"mass_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({
            "version": "v6.0",
            "timestamp": datetime.now().isoformat(),
            "count_requested": actual_count,
            "produced": produced,
            "failed": failed,
            "elapsed_sec": round(elapsed, 1),
            "source": source,
            "tts_engine": tts_engine,
            "daemon": daemon,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"  📋 로그: {log_path}")


# ============================================================
# 🧹 정리 유틸
# ============================================================
def clean_output(clean_all: bool = False) -> None:
    """비정상 출력 파일 정리"""
    output_dir = str(OUTPUT_DIR)
    if not os.path.exists(output_dir):
        print("📁 output/ 디렉토리 없음")
        return

    removed = 0

    # 비정상 MP4 삭제 (0KB 또는 100KB 미만)
    for mp4 in glob.glob(os.path.join(output_dir, "*.mp4")):
        size = os.path.getsize(mp4)
        if size < 100 * 1024:  # 100KB 미만 → 비정상
            os.remove(mp4)
            print(f"  🗑️  삭제: {os.path.basename(mp4)} ({size/1024:.0f}KB)")
            removed += 1

    if clean_all:
        # 임시 작업 디렉토리 삭제
        for work in glob.glob(os.path.join(output_dir, "_work_*")):
            if os.path.isdir(work):
                shutil.rmtree(work, ignore_errors=True)
                print(f"  🗑️  삭제: {os.path.basename(work)}/")
                removed += 1

        # __pycache__ 삭제
        for cache in glob.glob(os.path.join(str(SCRIPT_DIR), "**/__pycache__"), recursive=True):
            if os.path.isdir(cache):
                shutil.rmtree(cache, ignore_errors=True)
                removed += 1

        # _screenshots 삭제
        ss_dir = os.path.join(output_dir, "_screenshots")
        if os.path.isdir(ss_dir):
            shutil.rmtree(ss_dir, ignore_errors=True)
            removed += 1

    print(f"\n  정리 완료: {removed}개 항목 삭제")


# ============================================================
# CLI
# ============================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="🏭 YouTube Shorts 대량 생산 v6.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python mass_produce.py                                 # 바이럴 크롤링 3개
  python mass_produce.py --count 5                       # 5개 생산
  python mass_produce.py --count 3 --topic "AI 혁명"     # 고정 주제 3개
  python mass_produce.py --topics-file topics.txt        # 큐 파일에서 순차 소화
  python mass_produce.py --stories-dir stories/          # script.json 소화
  python mass_produce.py --daemon                        # 무한 루프 데몬
  python mass_produce.py --tts-engine elevenlabs         # TTS 엔진 지정
  python mass_produce.py --clean                         # 비정상 파일 정리
  python mass_produce.py --clean-all                     # 전체 정리
        """
    )

    prod = parser.add_argument_group("🏭 생산")
    prod.add_argument("-c", "--count", type=int, default=3,
                      help="생성할 영상 개수 (기본 3)")
    prod.add_argument("--source", default="viral",
                      choices=VALID_SOURCES,
                      help="크롤링 소스 (기본: viral)")
    prod.add_argument("-t", "--topic", default=None,
                      help="영상 주제 (미지정 시 자동 선정)")
    prod.add_argument("--topics-file", default=None,
                      help="주제 큐 파일 경로 (라인별 1주제, 처리 후 자동 삭제)")
    prod.add_argument("--stories-dir", default=None,
                      help="사전 준비된 script.json 폴더 (처리 후 _done/으로 이동)")

    tts = parser.add_argument_group("🔊 TTS")
    tts.add_argument("--tts-engine", default="auto",
                     choices=["auto", "elevenlabs", "openai", "edge"],
                     help="TTS 엔진 (기본: auto = ElevenLabs→OpenAI→edge)")

    ctrl = parser.add_argument_group("⚙️  제어")
    ctrl.add_argument("-d", "--delay", type=int, default=60,
                      help="영상 간 대기 시간 초 (기본 60, 최소 60)")
    ctrl.add_argument("--max-retries", type=int, default=3,
                      help="실패 시 최대 재시도 (기본 3)")
    ctrl.add_argument("--max-per-day", type=int, default=10,
                      help="하루 최대 생산 (기본 10)")
    ctrl.add_argument("--daemon", action="store_true",
                      help="무한 루프 데몬 모드 (큐 소진 시 크롤링 자동 리필)")

    util = parser.add_argument_group("🧹 정리")
    util.add_argument("--clean", action="store_true",
                      help="비정상 파일(100KB 미만 MP4) 삭제")
    util.add_argument("--clean-all", action="store_true",
                      help="비정상 + 임시파일 전부 삭제")

    args = parser.parse_args()

    # 정리 모드
    if args.clean or args.clean_all:
        clean_output(clean_all=args.clean_all)
        return

    # topics.txt 기본 경로 자동 탐색
    topics_file = args.topics_file
    if topics_file is None:
        default_topics = SCRIPT_DIR / "topics.txt"
        if default_topics.exists():
            topics_file = str(default_topics)
            print(f"  📋 자동 감지: {topics_file}")

    # stories/ 기본 경로 자동 탐색
    stories_dir = args.stories_dir
    if stories_dir is None:
        default_stories = SCRIPT_DIR / "stories"
        if default_stories.exists() and any(default_stories.glob("*.json")):
            stories_dir = str(default_stories)
            print(f"  📚 자동 감지: {stories_dir}")

    # 대량 생산
    mass_produce(
        count=args.count,
        source=args.source,
        topic=args.topic,
        topics_file=topics_file,
        stories_dir=stories_dir,
        tts_engine=args.tts_engine,
        delay=args.delay,
        max_retries=args.max_retries,
        max_per_day=args.max_per_day,
        daemon=args.daemon,
    )


if __name__ == "__main__":
    main()
