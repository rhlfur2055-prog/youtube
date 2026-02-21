#!/usr/bin/env python3
"""수동 대본 JSON → TTS → Pexels 비디오 배경 → 숏츠 MP4 생성"""
import os, sys, io, json, asyncio, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

# main.py에서 필요한 클래스 임포트
sys.path.insert(0, os.path.dirname(__file__))
from main import Config, TTSEngine, VideoAssembler, StockVideoFetcher

async def main():
    # 대본 로드
    script_path = os.path.join(os.path.dirname(__file__), "output", "manual_script_01.json")
    with open(script_path, "r", encoding="utf-8") as f:
        script_data = json.load(f)

    print(f"\n{'='*60}")
    print(f"📝 수동 대본 로드: {script_data['title']}")
    print(f"  문장 수: {len(script_data['script'])}개")
    print(f"{'='*60}")

    config = Config()
    work_dir = os.path.join(config.output_dir, "_manual_work")
    os.makedirs(work_dir, exist_ok=True)

    # Stage 1: Pexels 스톡 비디오 다운로드
    fetcher = StockVideoFetcher()
    scene_videos = fetcher.fetch_scene_videos(script_data, work_dir)

    # Stage 2: TTS 생성
    tts = TTSEngine(config)
    chunks = await tts.generate(script_data, work_dir)
    if not chunks:
        print("❌ TTS 실패")
        return

    # Stage 3: 영상 조립
    assembler = VideoAssembler(config)
    output_path = assembler.assemble(
        script_data, chunks, [], work_dir,
        scene_videos=scene_videos,
    )

    # 메타 저장
    duration_sec = max(c["end_ms"] for c in chunks) / 1000
    upload_info = {
        "title": script_data.get("title", ""),
        "description": script_data.get("description", ""),
        "tags": [t.lstrip("#") for t in script_data.get("tags", [])],
        "thumbnail_text": script_data.get("thumbnail_text", ""),
        "category": "22",
        "privacy": "public",
        "shorts": True,
        "duration_sec": duration_sec,
        "video_file": os.path.basename(output_path),
    }
    info_path = output_path.replace(".mp4", "_upload_info.json")
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(upload_info, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"🎉 완료! {output_path}")
    print(f"  크기: {os.path.getsize(output_path) / (1024*1024):.1f}MB")
    print(f"  길이: {duration_sec:.1f}초")
    print(f"{'='*60}")

asyncio.run(main())
