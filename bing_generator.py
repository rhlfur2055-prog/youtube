"""
Bing Image Creator (DALL-E 3) 자동화 모듈
─ Selenium으로 Bing Image Creator 제어
─ Chrome 유저 프로필 사용 → 로그인 상태 유지
─ 프롬프트 입력 → 이미지 생성 → 고화질 다운로드
─ 4장 생성 중 첫 번째 다운로드
"""

import os
import sys
import time
import re
import glob
import requests
import traceback
from io import BytesIO
from PIL import Image

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class BingImageCreator:
    """
    Bing Image Creator (DALL-E 3) Selenium 자동화
    ─ Chrome 유저 프로필로 로그인 유지
    ─ 프롬프트 → 이미지 4장 생성 → 첫 번째 고화질 다운로드
    """

    BING_URL = "https://www.bing.com/images/create"

    def __init__(self, chrome_profile_dir=None):
        """
        Args:
            chrome_profile_dir: Chrome 유저 프로필 경로 (None이면 기본값 사용)
        """
        self.driver = None
        self.chrome_profile_dir = chrome_profile_dir or self._default_chrome_profile()
        self._initialized = False

    def _default_chrome_profile(self) -> str:
        """기본 Chrome 유저 프로필 경로"""
        return os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Google", "Chrome", "User Data"
        )

    def _init_driver(self):
        """Chrome WebDriver 초기화 (유저 프로필 사용)"""
        if self.driver:
            return

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")

        # Chrome 유저 프로필 사용 (로그인 쿠키 유지)
        if os.path.exists(self.chrome_profile_dir):
            options.add_argument(f"--user-data-dir={self.chrome_profile_dir}")
            options.add_argument("--profile-directory=Default")

        # 필수 옵션
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1280,900")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # webdriver-manager로 자동 chromedriver 설치
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
        except Exception:
            service = Service()  # PATH에서 찾기

        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        self._initialized = True
        print("    [Bing] Chrome 브라우저 시작됨")

    def generate_image(self, prompt: str, save_path: str,
                       timeout: int = 90, max_retries: int = 3) -> bool:
        """
        Bing Image Creator로 이미지 1장 생성 + 다운로드 (최대 3회 재시도)

        Args:
            prompt: 영어 이미지 프롬프트
            save_path: 저장 경로 (.jpg)
            timeout: 생성 대기 시간 (초)
            max_retries: 최대 재시도 횟수

        Returns:
            성공 여부
        """
        for attempt in range(1, max_retries + 1):
            try:
                self._init_driver()

                # 1. Bing Image Creator 페이지 이동
                self.driver.get(self.BING_URL)
                time.sleep(3)

                # 로그인 확인
                if not self._check_login():
                    print("    [Bing] Microsoft 로그인 필요! Chrome에서 먼저 bing.com에 로그인해주세요.")
                    return False

                # 2. 프롬프트 입력
                if not self._input_prompt(prompt):
                    if attempt < max_retries:
                        print(f"    [Bing] 재시도 {attempt}/{max_retries}...")
                        time.sleep(3)
                        continue
                    return False

                # 3. 생성 대기 + 이미지 추출
                image_url = self._wait_and_extract(timeout)
                if not image_url:
                    if attempt < max_retries:
                        print(f"    [Bing] 재시도 {attempt}/{max_retries}...")
                        time.sleep(3)
                        continue
                    return False

                # 4. 고화질 다운로드 + 1080x1920 리사이즈
                if self._download_and_resize(image_url, save_path):
                    return True

                if attempt < max_retries:
                    print(f"    [Bing] 다운로드 실패, 재시도 {attempt}/{max_retries}...")
                    time.sleep(3)

            except Exception as e:
                print(f"    [Bing] 에러 ({attempt}/{max_retries}): {str(e)[:100]}")
                if attempt < max_retries:
                    time.sleep(3)

        print(f"    [Bing] {max_retries}회 모두 실패")
        return False

    def _check_login(self) -> bool:
        """Microsoft 계정 로그인 상태 확인"""
        try:
            time.sleep(2)

            # 방법 1: 프롬프트 입력창이 있으면 로그인 된 것
            try:
                prompt_input = self.driver.find_element(
                    By.CSS_SELECTOR, "#sb_form_q, textarea[name='q'], input[id='sb_form_q']"
                )
                if prompt_input:
                    return True
            except NoSuchElementException:
                pass

            # 방법 2: URL 기반 체크
            current_url = self.driver.current_url
            if "/create" in current_url and "login" not in current_url.lower():
                return True

            # 방법 3: 로그인 버튼 존재 여부
            try:
                login_btn = self.driver.find_element(By.CSS_SELECTOR, "a[href*='login']")
                if login_btn:
                    return False
            except NoSuchElementException:
                # 로그인 버튼 없음 = 이미 로그인
                return True

            return False
        except Exception:
            return True  # 에러 시 일단 진행

    def _input_prompt(self, prompt: str) -> bool:
        """프롬프트 입력 + 생성 시작"""
        try:
            wait = WebDriverWait(self.driver, 15)

            # 프롬프트 입력창 찾기 (여러 selector 시도)
            selectors = [
                "#sb_form_q",
                "textarea[name='q']",
                "input[name='q']",
                "#create_sb_form_q",
                "textarea.b_searchboxInput",
            ]

            prompt_input = None
            for sel in selectors:
                try:
                    prompt_input = wait.until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                    )
                    if prompt_input:
                        break
                except TimeoutException:
                    continue

            if not prompt_input:
                print("    [Bing] 프롬프트 입력창을 찾을 수 없음")
                return False

            # 기존 텍스트 클리어 + 프롬프트 입력
            prompt_input.clear()
            time.sleep(0.3)
            prompt_input.send_keys(prompt)
            time.sleep(0.5)

            # 생성 버튼 클릭 또는 Enter
            try:
                create_btn = self.driver.find_element(
                    By.CSS_SELECTOR, "#create_btn_c, #sb_form_go, button[type='submit']"
                )
                create_btn.click()
            except NoSuchElementException:
                prompt_input.send_keys(Keys.RETURN)

            print(f"    [Bing] 프롬프트 전송: {prompt[:60]}...")
            return True

        except Exception as e:
            print(f"    [Bing] 프롬프트 입력 실패: {str(e)[:80]}")
            return False

    def _wait_and_extract(self, timeout: int = 90) -> str:
        """이미지 생성 대기 + 첫 번째 이미지 URL 추출"""
        print(f"    [Bing] 이미지 생성 대기 중... (최대 {timeout}초)")

        start = time.time()
        while time.time() - start < timeout:
            time.sleep(3)

            # 로딩 중인지 확인
            try:
                # 생성 완료: 이미지 그리드가 나타남
                images = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    ".img_cont img, .imgpt img, .mimg, img.mimg"
                )

                # URL에 /images/create/async/ 가 포함되면 아직 생성중
                current_url = self.driver.current_url
                if "/create/async/" in current_url:
                    elapsed = int(time.time() - start)
                    if elapsed % 10 == 0:
                        print(f"    [Bing] 생성 중... ({elapsed}초)")
                    continue

                # 이미지가 로드되었는지 확인
                if images:
                    for img in images:
                        src = img.get_attribute("src") or ""
                        if src and ("th.bing.com" in src or "tse" in src):
                            # 고화질 URL로 변환
                            hq_url = self._to_high_quality_url(src)
                            print(f"    [Bing] 이미지 발견!")
                            return hq_url

                # 대안: 링크에서 이미지 찾기
                links = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "a.iusc, a[m*='murl'], .img_cont a"
                )
                for link in links:
                    href = link.get_attribute("href") or ""
                    m_attr = link.get_attribute("m") or ""

                    # m 속성에서 이미지 URL 추출
                    if "murl" in m_attr:
                        import json
                        try:
                            m_data = json.loads(m_attr)
                            if "murl" in m_data:
                                print(f"    [Bing] 이미지 발견! (m attr)")
                                return m_data["murl"]
                        except json.JSONDecodeError:
                            pass

                    # href에서 직접 이미지 URL
                    if "mediaurl=" in href:
                        import urllib.parse
                        parsed = urllib.parse.parse_qs(
                            urllib.parse.urlparse(href).query
                        )
                        if "mediaurl" in parsed:
                            url = urllib.parse.unquote(parsed["mediaurl"][0])
                            return url

            except Exception:
                pass

            # 에러 메시지 체크
            try:
                error_el = self.driver.find_element(
                    By.CSS_SELECTOR, ".gil_err_mt, .error_text, #gilen_son"
                )
                if error_el and error_el.text:
                    print(f"    [Bing] 생성 에러: {error_el.text[:80]}")
                    return None
            except NoSuchElementException:
                pass

        print(f"    [Bing] 타임아웃 ({timeout}초)")
        return None

    def _to_high_quality_url(self, url: str) -> str:
        """썸네일 URL → 고화질 URL 변환"""
        # th.bing.com/th/id/... → 원본 크기
        if "th.bing.com" in url:
            # w=, h= 파라미터 제거하여 원본 크기 요청
            url = re.sub(r'[&?]w=\d+', '', url)
            url = re.sub(r'[&?]h=\d+', '', url)
            # qlt(품질) 최대로
            if "qlt=" not in url:
                sep = "&" if "?" in url else "?"
                url += f"{sep}qlt=100"
        return url

    def _download_and_resize(self, url: str, save_path: str) -> bool:
        """이미지 다운로드 + 1080x1920 리사이즈"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code != 200 or len(resp.content) < 5000:
                print(f"    [Bing] 다운로드 실패: status={resp.status_code}")
                return False

            img = Image.open(BytesIO(resp.content)).convert("RGB")

            # 9:16 세로 비율로 크롭 후 리사이즈
            target_w, target_h = 1080, 1920
            target_ratio = target_w / target_h  # 0.5625

            w, h = img.size
            current_ratio = w / h

            if current_ratio > target_ratio:
                # 이미지가 더 넓음 → 좌우 크롭
                new_w = int(h * target_ratio)
                left = (w - new_w) // 2
                img = img.crop((left, 0, left + new_w, h))
            elif current_ratio < target_ratio:
                # 이미지가 더 높음 → 상하 크롭
                new_h = int(w / target_ratio)
                top = (h - new_h) // 2
                img = img.crop((0, top, w, top + new_h))

            img = img.resize((target_w, target_h), Image.LANCZOS)
            img.save(save_path, quality=95)
            return True

        except Exception as e:
            print(f"    [Bing] 리사이즈 실패: {str(e)[:80]}")
            return False

    def close(self):
        """브라우저 종료"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self._initialized = False


def test_bing_creator():
    """테스트: Bing Image Creator로 이미지 1장 생성"""
    creator = BingImageCreator()
    try:
        prompt = (
            "A high-quality scene from a Korean webtoon, manhwa style, "
            "4k, vibrant colors, dramatic lighting, "
            "A young Korean office worker at a company dinner, "
            "Korean BBQ restaurant with green soju bottles, "
            "samgyeopsal grilling on charcoal, smoke rising, "
            "the new hire looking confident while older colleagues look shocked"
        )
        save_path = os.path.join(
            os.path.dirname(__file__), "output", "_test_bing_dalle3.jpg"
        )
        print("Bing Image Creator 테스트 시작...")
        success = creator.generate_image(prompt, save_path)
        if success:
            size = os.path.getsize(save_path) / 1024
            print(f"\n성공! {save_path} ({size:.0f}KB)")
        else:
            print("\n실패!")
    finally:
        creator.close()


if __name__ == "__main__":
    test_bing_creator()
