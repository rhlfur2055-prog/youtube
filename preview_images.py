"""이미지 미리보기 생성 스크립트 — 영상 조립 전에 이미지만 먼저 생성"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import Config, ScriptGenerator, ImageGenerator

def preview(topic: str):
    print(f"\n🎬 이미지 미리보기 모드: {topic}")
    print("=" * 60)

    # 1) 대본 생성
    config = Config()
    sg = ScriptGenerator(config)
    script_data = sg.generate_from_topic(topic)

    if not script_data or not script_data.get("script"):
        print("❌ 대본 생성 실패")
        return

    print(f"\n📋 대본 ({len(script_data['script'])}문장, mood={script_data.get('mood', '?')}):")
    for i, line in enumerate(script_data["script"]):
        text = line.get("text", "")
        emo = line.get("emotion", "")
        img = line.get("image_prompt", "")[:40]
        sfx = line.get("sfx", "")
        print(f"  [{i+1:02d}] [{emo:8s}] {text}  | img: {img}... | sfx: {sfx}")

    # 2) 이미지 생성
    work_dir = os.path.join("output", "_preview")
    os.makedirs(work_dir, exist_ok=True)

    ig = ImageGenerator()
    results = ig.generate_scene_images(script_data, work_dir)

    # 3) 결과 출력
    print(f"\n✅ 이미지 {len(results)}장 생성 완료!")
    print(f"📁 위치: {os.path.abspath(work_dir)}")
    for r in results:
        p = r.get("image_path", "")
        print(f"  → {os.path.basename(p)}")

    # 4) 이미지 경로 목록 출력 (Claude가 읽을 수 있게)
    images_dir = os.path.join(work_dir, "_scene_images")
    if os.path.exists(images_dir):
        files = sorted(f for f in os.listdir(images_dir) if f.endswith(('.jpg', '.webp', '.png')))
        print(f"\n🖼️  미리보기 이미지 파일들:")
        for f in files:
            print(f"  {os.path.join(images_dir, f)}")

if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "회사 회식에서 신입사원이 부장님 술잔 뺏어서 원샷한 썰"
    preview(topic)
