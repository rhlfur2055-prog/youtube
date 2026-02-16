"""YouTube Shorts 자동 업로드 모듈.

YouTube Data API v3를 사용하여 생성된 Shorts를 자동 업로드합니다.
OAuth2 인증 플로우를 지원하며, 토큰 캐싱으로 재인증 없이 사용 가능합니다.

주요 기능:
- OAuth2 인증 (브라우저 플로우 → 토큰 저장)
- 영상 업로드 (제목/설명/태그/카테고리 자동 설정)
- 예약 업로드 (scheduledStartTime 설정)
- 3회 재시도 (네트워크 에러 대응)
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from typing import Any

from youshorts.utils.logger import get_logger

logger = get_logger(__name__)

# YouTube API 스코프
_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# 업로드 재시도 설정
_MAX_RETRIES = 3
_RETRY_DELAY = 10  # 초


class YouTubeUploader:
    """YouTube Shorts 업로더.

    OAuth2 인증을 통해 YouTube에 영상을 업로드합니다.
    YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET 환경변수 필요.
    """

    def __init__(self, settings: Any = None) -> None:
        """업로더를 초기화합니다.

        Args:
            settings: 설정 인스턴스.
        """
        from dotenv import load_dotenv
        load_dotenv()

        self.client_id = os.getenv("YOUTUBE_CLIENT_ID", "")
        self.client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "")
        self.data_dir = "data"
        if settings and hasattr(settings, "data_dir"):
            self.data_dir = settings.data_dir

        self.token_path = os.path.join(self.data_dir, "youtube_token.json")
        self.credentials = None
        self.service = None

        # 간소화 모드 (API 키만)
        self.api_key_only = not (self.client_id and self.client_secret)
        if self.api_key_only:
            logger.warning(
                "YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET 미설정 - "
                "업로드 불가 (인증 필요). setup_youtube_auth.py 실행 필요."
            )

    def authenticate(self) -> bool:
        """YouTube API 인증을 수행합니다.

        1. 저장된 토큰 파일이 있으면 로드
        2. 토큰 만료 시 리프레시
        3. 토큰 없으면 브라우저 OAuth2 플로우

        Returns:
            인증 성공 여부.
        """
        if self.api_key_only:
            logger.error("OAuth2 인증 정보 없음. 업로드 불가.")
            return False

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None

            # 1. 저장된 토큰 로드
            if os.path.exists(self.token_path):
                creds = Credentials.from_authorized_user_file(
                    self.token_path, _SCOPES
                )
                logger.info("저장된 YouTube 토큰 로드 완료")

            # 2. 토큰 리프레시
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    logger.info("YouTube 토큰 리프레시 완료")
                except Exception as e:
                    logger.warning("토큰 리프레시 실패: %s - 재인증 필요", e)
                    creds = None

            # 3. 새 인증 플로우
            if not creds or not creds.valid:
                client_config = {
                    "installed": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                }
                flow = InstalledAppFlow.from_client_config(
                    client_config, _SCOPES
                )
                creds = flow.run_local_server(port=0)
                logger.info("YouTube OAuth2 인증 완료")

                # 토큰 저장
                os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
                with open(self.token_path, "w") as f:
                    f.write(creds.to_json())
                logger.info("YouTube 토큰 저장: %s", self.token_path)

            self.credentials = creds
            self.service = build("youtube", "v3", credentials=creds)
            return True

        except ImportError as e:
            logger.error(
                "YouTube API 패키지 미설치: %s. "
                "pip install google-auth-oauthlib google-api-python-client",
                e,
            )
            return False
        except Exception as e:
            logger.error("YouTube 인증 실패: %s", e)
            return False

    def upload_short(
        self,
        mp4_path: str,
        metadata: dict[str, Any],
        privacy: str = "public",
    ) -> str | None:
        """Shorts 영상을 YouTube에 업로드합니다.

        Args:
            mp4_path: MP4 파일 경로.
            metadata: 메타데이터 딕셔너리.
            privacy: 공개 설정 (public/private/unlisted).

        Returns:
            업로드된 영상 URL (실패 시 None).
        """
        if not self.service:
            if not self.authenticate():
                return None

        # 제목 처리 (50자 이내 + #Shorts)
        title = metadata.get("title", "쇼츠")[:46]
        if "#Shorts" not in title and "#shorts" not in title:
            title = f"{title} #Shorts"

        # 설명 처리
        description = metadata.get("description", "")
        if not description:
            description = self._build_description(metadata)

        # 태그 (최대 20개)
        tags = metadata.get("tags", [])[:20]

        # 카테고리
        category_id = metadata.get("category", "22")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
                "defaultLanguage": "ko",
                "defaultAudioLanguage": "ko",
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
                "madeForKids": False,
            },
        }

        # 3회 재시도
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                from googleapiclient.http import MediaFileUpload

                media = MediaFileUpload(
                    mp4_path,
                    mimetype="video/mp4",
                    resumable=True,
                    chunksize=10 * 1024 * 1024,  # 10MB 청크
                )

                request = self.service.videos().insert(
                    part="snippet,status",
                    body=body,
                    media_body=media,
                )

                logger.info(
                    "YouTube 업로드 시작: '%s' (%s)",
                    title, os.path.basename(mp4_path),
                )

                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        pct = int(status.progress() * 100)
                        logger.info("업로드 진행: %d%%", pct)

                video_id = response["id"]
                video_url = f"https://youtube.com/shorts/{video_id}"
                logger.info("업로드 완료: %s", video_url)
                return video_url

            except Exception as e:
                logger.warning(
                    "업로드 실패 (시도 %d/%d): %s",
                    attempt, _MAX_RETRIES, e,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY)

        logger.error("YouTube 업로드 최종 실패: %s", os.path.basename(mp4_path))
        return None

    def upload_with_schedule(
        self,
        mp4_path: str,
        metadata: dict[str, Any],
        scheduled_time: datetime | None = None,
        interval_hours: int = 4,
        video_index: int = 0,
    ) -> str | None:
        """예약 업로드를 수행합니다.

        private로 업로드 후 scheduledStartTime 설정.

        Args:
            mp4_path: MP4 파일 경로.
            metadata: 메타데이터 딕셔너리.
            scheduled_time: 공개 예정 시간 (None이면 자동 계산).
            interval_hours: 영상 간 공개 간격 (시간).
            video_index: 영상 순번 (0부터).

        Returns:
            업로드된 영상 URL (실패 시 None).
        """
        if not self.service:
            if not self.authenticate():
                return None

        # 공개 시간 계산
        if scheduled_time is None:
            base_time = datetime.utcnow().replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            if base_time < datetime.utcnow():
                base_time += timedelta(days=1)
            scheduled_time = base_time + timedelta(
                hours=interval_hours * video_index
            )

        # 제목 처리
        title = metadata.get("title", "쇼츠")[:46]
        if "#Shorts" not in title:
            title = f"{title} #Shorts"

        description = metadata.get("description", "")
        if not description:
            description = self._build_description(metadata)

        tags = metadata.get("tags", [])[:20]
        category_id = metadata.get("category", "22")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
                "defaultLanguage": "ko",
                "defaultAudioLanguage": "ko",
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": scheduled_time.strftime("%Y-%m-%dT%H:%M:%S.0Z"),
                "selfDeclaredMadeForKids": False,
            },
        }

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                from googleapiclient.http import MediaFileUpload

                media = MediaFileUpload(
                    mp4_path, mimetype="video/mp4", resumable=True,
                )

                request = self.service.videos().insert(
                    part="snippet,status",
                    body=body,
                    media_body=media,
                )

                logger.info(
                    "예약 업로드 시작: '%s' → %s",
                    title, scheduled_time.strftime("%Y-%m-%d %H:%M"),
                )

                response = None
                while response is None:
                    status, response = request.next_chunk()

                video_id = response["id"]
                video_url = f"https://youtube.com/shorts/{video_id}"
                logger.info(
                    "예약 업로드 완료: %s (공개: %s)",
                    video_url, scheduled_time.strftime("%m/%d %H:%M"),
                )
                return video_url

            except Exception as e:
                logger.warning(
                    "예약 업로드 실패 (시도 %d/%d): %s",
                    attempt, _MAX_RETRIES, e,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY)

        logger.error("예약 업로드 최종 실패: %s", os.path.basename(mp4_path))
        return None

    def _build_description(self, metadata: dict[str, Any]) -> str:
        """메타데이터에서 설명문을 생성합니다."""
        parts = [
            metadata.get("title", ""),
            "",
            "---",
            "이 영상은 AI 도구를 활용하여 제작되었습니다.",
            "대본 구성, 분석, 의견은 크리에이터의 독창적 관점입니다.",
            "",
        ]
        hashtags = metadata.get("hashtags", [])
        if hashtags:
            parts.append(" ".join(hashtags))
        return "\n".join(parts)
