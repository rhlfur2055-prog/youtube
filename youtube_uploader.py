"""YouTube Shorts 자동 업로드 스크립트

- output/ 내 *_upload_info.json 탐색
- .env에서 YOUTUBE_CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN 읽기
- shorts: true면 제목에 #Shorts 추가
- uploaded_history.json으로 중복 업로드 방지

실행: py youtube_uploader.py
"""

import json
import os
import glob
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
HISTORY_PATH = ROOT / "uploaded_history.json"


def load_history():
    if not HISTORY_PATH.exists():
        return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_youtube_service():
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("ERROR: .env에 YOUTUBE_CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN을 설정하세요.")
        print("  py get_youtube_token.py 로 토큰을 발급받으세요.")
        return None

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )

    return build("youtube", "v3", credentials=credentials)


def upload_video(youtube, info_path):
    from googleapiclient.http import MediaFileUpload

    with open(info_path, "r", encoding="utf-8") as f:
        info = json.load(f)

    video_file = OUTPUT_DIR / info["video_file"]
    if not video_file.exists():
        print(f"  SKIP: 영상 파일 없음 - {info['video_file']}")
        return None

    title = (info.get("title") or "Untitled").strip()
    if info.get("shorts", False) and "#Shorts" not in title:
        title = f"{title} #Shorts"

    description = (info.get("description") or "").strip()
    tags = [t.lstrip("#").strip() for t in info.get("tags", []) if t]
    category = str(info.get("category", "22"))
    privacy = (info.get("privacy") or "public").lower()
    if privacy not in ("public", "private", "unlisted"):
        privacy = "public"

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": category,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_file), mimetype="video/mp4", resumable=True, chunksize=1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    print(f"  업로드 중: {title}")
    response = None
    retries = 0
    while response is None and retries <= 5:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"  진행률: {int(status.progress() * 100)}%")
        except Exception as e:
            retries += 1
            if retries > 5:
                print(f"  ERROR: 업로드 실패 - {e}")
                return None
            time.sleep(2 ** retries)

    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"
    print(f"  완료: {url}")

    return {
        "video_id": video_id,
        "url": url,
        "title": title,
        "file": info["video_file"],
        "info_path": str(info_path),
    }


def main():
    youtube = get_youtube_service()
    if not youtube:
        return

    history = load_history()
    uploaded_files = {h["file"] for h in history if isinstance(h, dict)}

    info_files = sorted(glob.glob(str(OUTPUT_DIR / "*_upload_info.json")))
    if not info_files:
        print("업로드할 영상이 없습니다. (output/*_upload_info.json)")
        return

    pending = []
    for f in info_files:
        with open(f, "r", encoding="utf-8") as fh:
            info = json.load(fh)
        if info.get("video_file") not in uploaded_files:
            pending.append(f)

    if not pending:
        print("모든 영상이 이미 업로드되었습니다.")
        return

    print(f"업로드 대기: {len(pending)}개\n")

    for info_path in pending:
        name = os.path.basename(info_path).replace("_upload_info.json", "")
        print(f"[{name}]")
        result = upload_video(youtube, info_path)
        if result:
            history.append(result)
            save_history(history)
        print()

    uploaded_count = len([h for h in history if isinstance(h, dict)])
    print(f"총 {uploaded_count}개 업로드 완료.")


if __name__ == "__main__":
    main()
