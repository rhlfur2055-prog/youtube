#!/usr/bin/env python3
"""수동 대본 실행기 (에러 캡처 버전)"""
import traceback
try:
    import os, sys, io, json, asyncio, warnings
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    warnings.filterwarnings("ignore")

    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

    sys.path.insert(0, os.path.dirname(__file__))
    print("[1] Importing main modules...")
    from main import Config, TTSEngine, VideoAssembler, StockVideoFetcher
    print("[2] Imports OK")

    async def main():
        script_path = os.path.join(os.path.dirname(__file__), "output", "manual_script_01.json")
        with open(script_path, "r", encoding="utf-8") as f:
            script_data = json.load(f)
        print(f"[3] Script loaded: {script_data['title']} ({len(script_data['script'])} lines)")

        config = Config()
        work_dir = os.path.join(config.output_dir, "_manual_work")
        os.makedirs(work_dir, exist_ok=True)
        print("[4] Config OK, work_dir created")

        fetcher = StockVideoFetcher()
        print(f"[5] Pexels API key: {'YES' if fetcher.api_key else 'NO'}")
        scene_videos = fetcher.fetch_scene_videos(script_data, work_dir)
        print(f"[6] Scene videos: {len(scene_videos)}")

        tts = TTSEngine(config)
        chunks = await tts.generate(script_data, work_dir)
        if not chunks:
            print("[FAIL] TTS failed")
            return
        print(f"[7] TTS OK: {len(chunks)} chunks")

        assembler = VideoAssembler(config)
        output_path = assembler.assemble(
            script_data, chunks, [], work_dir,
            scene_videos=scene_videos,
        )
        print(f"[8] Output: {output_path}")
        print(f"[9] Size: {os.path.getsize(output_path) / (1024*1024):.1f}MB")

    asyncio.run(main())
    print("[DONE]")

except Exception as e:
    print(f"[ERROR] {type(e).__name__}: {e}")
    traceback.print_exc()
