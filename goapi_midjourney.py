"""
GoAPI Midjourney 브릿지 — YouShorts v6.0
─ Midjourney API를 GoAPI 써드파티로 연동
─ --sref (스타일 레퍼런스) + --cref (캐릭터 레퍼런스) + --cw 100 (의상 고정)
─ ★ 파라미터는 반드시 프롬프트 가장 마지막에 배치 (씹힘 방지)
─ 첫 이미지 URL 자동 저장 → 이후 장면에 자동 주입
─ 3회 재시도 + 예외 시 폴백(Bing/Replicate)으로 안전 전환
"""

import os
import time
import requests
from io import BytesIO
from PIL import Image


class GoAPIMidjourney:
    """GoAPI Midjourney bridge — async image generation with style/character reference."""

    IMAGINE_URL = "https://api.goapi.ai/mj/v2/imagine"
    FETCH_URL = "https://api.goapi.ai/mj/v2/fetch"

    MAX_RETRIES = 3
    POLL_INTERVAL = 5  # 초
    POLL_MAX_ATTEMPTS = 24  # 24 * 5 = 120초 타임아웃

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._first_image_url = None  # --sref / --cref 주입용

    # ── 퍼블릭 API ──

    def generate_image(
        self,
        prompt: str,
        save_path: str,
        style_ref: str = None,
        char_ref: str = None,
        timeout: int = 120,
    ) -> bool:
        """Midjourney 이미지 생성 (GoAPI 브릿지).

        Args:
            prompt: 이미지 프롬프트 (영어)
            save_path: 로컬 저장 경로 (.jpg)
            style_ref: --sref URL (스타일 일관성)
            char_ref: --cref URL (캐릭터 일관성)
            timeout: 최대 대기 시간 (초)

        Returns:
            True if success
        """
        # ★ 프롬프트 빌드: 파라미터는 가장 마지막에 강제 배치
        final_prompt = self._build_mj_prompt(prompt, style_ref, char_ref)

        for attempt in range(self.MAX_RETRIES):
            try:
                task_id = self._submit_imagine(final_prompt)
                if not task_id:
                    raise RuntimeError("GoAPI task_id 반환 실패")

                image_url = self._poll_result(task_id, timeout)
                if not image_url:
                    raise RuntimeError(f"GoAPI 결과 없음 (task: {task_id})")

                success = self._download_and_crop(image_url, save_path)
                if success:
                    # ★ 첫 이미지 URL 저장 (이후 --sref/--cref용)
                    if not self._first_image_url:
                        self._first_image_url = image_url
                        print(f"    📌 첫 이미지 URL 저장 (캐릭터 레퍼런스용)")
                    return True
                else:
                    raise RuntimeError("이미지 다운로드/크롭 실패")

            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    wait = 5 * (attempt + 1)
                    print(f"    ⚠️  GoAPI 재시도 {attempt + 1}/{self.MAX_RETRIES} "
                          f"({wait}초 후): {e}")
                    time.sleep(wait)
                else:
                    print(f"    ❌ GoAPI {self.MAX_RETRIES}회 실패: {e}")
                    return False

        return False

    @property
    def first_image_url(self) -> str:
        """첫 이미지 URL (--sref/--cref 주입용)"""
        return self._first_image_url or ""

    def reset_session(self):
        """새 영상 시작 시 호출 — 캐릭터 레퍼런스 리셋"""
        self._first_image_url = None

    # ── 내부 구현 ──

    def _build_mj_prompt(
        self,
        base_prompt: str,
        style_ref: str = None,
        char_ref: str = None,
    ) -> str:
        """Midjourney 프롬프트 빌드.

        ★★★ 핵심 규칙: --sref, --cref, --cw 파라미터는 반드시
        프롬프트 문자열의 '가장 마지막'에 배치해야 Midjourney가 인식한다.
        프롬프트가 너무 길면 파라미터가 무시될 수 있으므로
        base_prompt는 200자 이내로 제한.
        """
        # 프롬프트 길이 제한 (파라미터 씹힘 방지)
        if len(base_prompt) > 200:
            base_prompt = base_prompt[:200].rstrip(", ")

        # 기본 파라미터
        parts = [base_prompt, "--ar 9:16", "--v 6.1"]

        # ★ 스타일/캐릭터 레퍼런스는 가장 마지막에 강제 배치
        if style_ref:
            parts.append(f"--sref {style_ref}")
        if char_ref:
            parts.append(f"--cref {char_ref}")
            parts.append("--cw 100")  # ★ 캐릭터 의상까지 100% 고정

        return " ".join(parts)

    def _submit_imagine(self, prompt: str) -> str:
        """GoAPI /imagine 요청 제출 → task_id 반환"""
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "prompt": prompt,
            "process_mode": "fast",
            "webhook_endpoint": "",
            "webhook_secret": "",
        }

        resp = requests.post(
            self.IMAGINE_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )

        if resp.status_code == 401:
            raise ValueError("GoAPI 키 무효 (401 Unauthorized)")
        if resp.status_code == 429:
            raise RuntimeError("GoAPI 요청 한도 초과 (429)")
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"GoAPI imagine 오류 {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        task_id = data.get("task_id", "")

        if not task_id:
            # 일부 GoAPI 응답 형식 대응
            task_id = data.get("data", {}).get("task_id", "")

        return task_id

    def _poll_result(self, task_id: str, timeout: int) -> str:
        """GoAPI /fetch 폴링 → 완료 시 이미지 URL 반환

        Returns:
            이미지 URL string, 또는 None (타임아웃/실패)
        """
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

        max_polls = min(self.POLL_MAX_ATTEMPTS, timeout // self.POLL_INTERVAL)
        start_time = time.time()

        for i in range(max_polls):
            if time.time() - start_time > timeout:
                print(f"    ⏱️  GoAPI 타임아웃 ({timeout}초)")
                return None

            time.sleep(self.POLL_INTERVAL)

            try:
                resp = requests.post(
                    self.FETCH_URL,
                    headers=headers,
                    json={"task_id": task_id},
                    timeout=10,
                )

                if resp.status_code != 200:
                    continue

                data = resp.json()
                status = data.get("status", "")

                # GoAPI 상태값 대응 (API 버전에 따라 다를 수 있음)
                if status in ("finished", "completed", "succeeded"):
                    # 이미지 URL 추출 (다양한 응답 형식 대응)
                    image_url = (
                        data.get("task_result", {}).get("image_url", "")
                        or data.get("output", {}).get("image_url", "")
                        or data.get("image_url", "")
                    )

                    # 4장 그리드 중 첫 번째 선택 (upscale 필요 시)
                    if not image_url:
                        images = (
                            data.get("task_result", {}).get("image_urls", [])
                            or data.get("output", {}).get("image_urls", [])
                        )
                        if images:
                            image_url = images[0]

                    if image_url:
                        return image_url
                    else:
                        print(f"    ⚠️  GoAPI 성공했으나 이미지 URL 없음")
                        return None

                elif status in ("failed", "error"):
                    error_msg = data.get("error", {}).get("message", "알 수 없는 오류")
                    print(f"    ❌ GoAPI 생성 실패: {error_msg}")
                    return None

                elif status in ("pending", "processing", "running"):
                    if i % 4 == 0:  # 20초마다 로그
                        elapsed = int(time.time() - start_time)
                        print(f"    ⏳ GoAPI 생성 중... ({elapsed}초 경과)")

            except requests.exceptions.Timeout:
                continue
            except Exception as e:
                print(f"    ⚠️  GoAPI 폴링 오류: {e}")
                continue

        return None

    def _download_and_crop(self, image_url: str, save_path: str) -> bool:
        """이미지 다운로드 + 9:16 크롭 + 1080x1920 리사이즈

        Returns:
            True if success
        """
        try:
            resp = requests.get(image_url, timeout=60)
            if resp.status_code != 200:
                print(f"    ⚠️  이미지 다운로드 실패: HTTP {resp.status_code}")
                return False

            if len(resp.content) < 5000:
                print(f"    ⚠️  이미지 크기 너무 작음: {len(resp.content)} bytes")
                return False

            img = Image.open(BytesIO(resp.content)).convert("RGB")
            w, h = img.size

            # 9:16 비율로 크롭
            target_ratio = 9 / 16
            current_ratio = w / h

            if current_ratio > target_ratio:
                # 너무 넓음 → 좌우 크롭
                new_w = int(h * target_ratio)
                left = (w - new_w) // 2
                img = img.crop((left, 0, left + new_w, h))
            elif current_ratio < target_ratio:
                # 너무 높음 → 상하 크롭
                new_h = int(w / target_ratio)
                top = (h - new_h) // 2
                img = img.crop((0, top, w, top + new_h))

            # 1080x1920으로 리사이즈
            img = img.resize((1080, 1920), Image.LANCZOS)
            img.save(save_path, "JPEG", quality=95)

            return True

        except Exception as e:
            print(f"    ❌ 이미지 처리 오류: {e}")
            return False

    def close(self):
        """리소스 정리 (GoAPI는 HTTP only라 별도 정리 불필요)"""
        pass
