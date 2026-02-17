"""
============================================================================
 youshorts 완벽한 영상 1개 생성 마스터 파이프라인
 ──────────────────────────────────────────────
 역할: 풀스택 개발자 + 숏츠 배포 전문가
 목표: 트렌드 수집 → 대본 → TTS → 자막 → 렌더링까지 1개 영상 완성

 사용법: python perfect_one_shot.py
 필요: pip install edge-tts google-generativeai requests beautifulsoup4
 환경변수: GOOGLE_API_KEY (Gemini용)
============================================================================
"""

import asyncio
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

# .env 파일 로드 (GOOGLE_API_KEY 등)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass  # python-dotenv 없으면 환경변수 직접 설정 필요

# Windows cp949 콘솔 유니코드 출력 대응
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace"
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace"
    )


# ============================================================================
# 설정
# ============================================================================
class Config:
    """프로젝트 전체 설정 - constants.py 역할"""

    # ── 경로 ──
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output"
    BGM_DIR = BASE_DIR / "data" / "bgm"
    BG_DIR = BASE_DIR / "data" / "backgrounds"
    HISTORY_FILE = BASE_DIR / "data" / "history.json"

    # ── 영상 스펙 ──
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 30
    MAX_DURATION = 59  # 숏츠 제한 60초 미만

    # ── TTS ──
    TTS_VOICE = "ko-KR-SunHiNeural"  # 여성 (남성: ko-KR-InJoonNeural)
    TTS_RATE = "+10%"   # 살짝 빠르게 (숏츠는 빠른게 좋음)
    TTS_PITCH = "+0Hz"

    # ── 자막 ──
    SUBTITLE_FONT = "Arial"
    SUBTITLE_SIZE = 20          # ASS 기준 (FFmpeg 렌더링 시 스케일됨)
    SUBTITLE_COLOR_NORMAL = "&H00FFFFFF"   # 흰색 (ASS BGR)
    SUBTITLE_COLOR_HIGHLIGHT = "&H0000FFFF"  # 노란색 (ASS BGR)
    SUBTITLE_OUTLINE = 3
    SUBTITLE_SHADOW = 2
    SUBTITLE_MARGIN_V = 120     # 하단에서 위로 마진

    # ── 품질 ──
    MIN_QUALITY_SCORE = 85
    MAX_RETRY = 3

    # ── AI 슬롭 금지어 ──
    AI_SLOP_WORDS = [
        "흥미롭", "놀라운", "충격적", "심층", "탐구", "여정",
        "알아보겠", "살펴보겠", "함께 알아", "그렇다면",
        "~인 셈이다", "~라 할 수 있", "결론적으로",
        "마무리하며", "정리하자면", "요약하자면",
    ]

    # ── FFmpeg ──
    FFMPEG_EXE = "ffmpeg"
    FFPROBE_EXE = "ffprobe"


# ============================================================================
# STEP 1: 트렌드 수집 - 3개 소스 병합
# ============================================================================
class TrendCollector:
    """
    트렌드 수집 전략:
    Google Trends RSS + 네이버 시그널 + 커뮤니티 핫글
    → 중복 제거 → 인기도 점수 계산 → TOP 1 선정
    """

    def __init__(self):
        self.trends = []

    # ── 1. Google Trends RSS (가장 안정적) ──
    def fetch_google_trends_rss(self) -> list[dict]:
        """RSS 피드라 API 키 불필요, IP 차단 0%"""
        import requests

        url = "https://trends.google.co.kr/trending/rss?geo=KR"
        results = []

        try:
            resp = requests.get(url, timeout=5, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0"
            })
            resp.raise_for_status()

            root = ET.fromstring(resp.text)
            ns = {"ht": "https://trends.google.co.kr/trending/rss"}

            for item in root.findall(".//item"):
                title = item.find("title")
                if title is not None and title.text:
                    traffic = item.find("ht:approx_traffic", ns)
                    traffic_num = 0
                    if traffic is not None and traffic.text:
                        traffic_num = int(
                            traffic.text.replace(",", "").replace("+", "")
                        )

                    results.append({
                        "keyword": title.text.strip(),
                        "source": "google_trends",
                        "score": traffic_num,
                    })

            print(f"  [OK] Google Trends: {len(results)}개 수집")

        except Exception as e:
            print(f"  [WARN] Google Trends 실패: {e}")

        return results

    # ── 2. 네이버 실시간 검색어 (한국 특화) ──
    def fetch_naver_signal(self) -> list[dict]:
        """네이버 데이터랩 시그널 - 한국인 실시간 관심사"""
        import requests
        from bs4 import BeautifulSoup

        results = []

        try:
            url = "https://datalab.naver.com/keyword/realtimeList.naver"

            resp = requests.get(url, timeout=5, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0",
                "Referer": "https://datalab.naver.com/",
            })

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")

                selectors = [
                    "span.item_title",
                    ".ranking_item .title",
                    "a.link_text",
                ]

                items = []
                for sel in selectors:
                    items = soup.select(sel)
                    if items:
                        break

                for i, item in enumerate(items[:20]):
                    text = item.get_text(strip=True)
                    if text and len(text) > 1:
                        results.append({
                            "keyword": text,
                            "source": "naver_signal",
                            "score": (20 - i) * 5000,
                        })

                print(f"  [OK] 네이버 시그널: {len(results)}개 수집")
            else:
                print(f"  [WARN] 네이버 시그널: HTTP {resp.status_code}")

        except Exception as e:
            print(f"  [WARN] 네이버 시그널 실패 (정상 - 비공식 API): {e}")

        return results

    # ── 3. 커뮤니티 핫글 크롤링 (제목 + 본문) ──
    def fetch_community_hot(self) -> list[dict]:
        """에펨코리아/인스티즈/네이트판 실시간 베스트 — 본문까지 수집"""
        import requests
        from bs4 import BeautifulSoup

        results = []

        communities = [
            {
                "name": "네이트판",
                "url": "https://pann.nate.com/talk/ranking",
                "title_sel": ".tlt",
                "base_url": "https://pann.nate.com",
                "body_sel": "#contentArea, .posting_area, #content",
            },
            {
                "name": "에펨코리아",
                "url": "https://www.fmkorea.com/index.php?mid=best&listStyle=list",
                "title_sel": ".title a",
                "base_url": "https://www.fmkorea.com",
                "body_sel": ".rd_body, .xe_content, article",
            },
            {
                "name": "인스티즈",
                "url": "https://www.instiz.net/pt",
                "title_sel": ".listsubject a",
                "base_url": "https://www.instiz.net",
                "body_sel": ".memo_content, .xe_content",
            },
        ]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }

        for comm in communities:
            try:
                resp = requests.get(
                    comm["url"], timeout=8, headers=headers, verify=False,
                )
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                titles = soup.select(comm["title_sel"])

                count = 0
                for i, t in enumerate(titles[:10]):
                    text = t.get_text(strip=True)
                    # 끝에 붙는 숫자(조회수) 제거
                    text = re.sub(r'\d{2,}$', '', text).strip()

                    if not text or len(text) < 5 or "[광고]" in text:
                        continue

                    # 게시글 URL 추출
                    href = t.get("href", "")
                    if href and not href.startswith("http"):
                        href = comm["base_url"] + href

                    results.append({
                        "keyword": text,
                        "source": f"community_{comm['name']}",
                        "score": (10 - i) * 3000,
                        "url": href,
                        "body": "",  # 나중에 채움
                    })
                    count += 1

                print(f"  [OK] {comm['name']}: {count}개")

            except Exception as e:
                print(f"  [WARN] {comm['name']} 실패: {e}")

        return results

    def fetch_post_body(self, url: str, selectors: str = "") -> str:
        """게시글 URL에서 본문 텍스트를 크롤링"""
        import requests
        from bs4 import BeautifulSoup

        if not url:
            return ""

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }

        try:
            resp = requests.get(url, timeout=8, headers=headers, verify=False)
            if resp.status_code != 200:
                return ""

            soup = BeautifulSoup(resp.text, "html.parser")

            # 여러 셀렉터 시도
            body_selectors = [
                "#contentArea", ".posting_area", "#content",
                ".rd_body", ".xe_content", "article",
                ".memo_content", ".post_content",
            ]

            for sel in body_selectors:
                body_el = soup.select_one(sel)
                if body_el:
                    text = body_el.get_text(separator="\n", strip=True)
                    if len(text) > 30:
                        return text[:2000]  # 최대 2000자

        except Exception:
            pass

        return ""

    # ── 통합: 3개 소스 병합 + 중복 제거 + 정렬 ──
    def collect_all(self) -> list[dict]:
        """3개 소스 합산, 같은 키워드 점수 합산"""
        print("\n" + "=" * 60)
        print("STEP 1: 트렌드 수집 (3개 소스)")
        print("=" * 60)

        all_trends = []
        all_trends.extend(self.fetch_google_trends_rss())
        all_trends.extend(self.fetch_naver_signal())
        all_trends.extend(self.fetch_community_hot())

        # 중복 키워드 합산
        merged = {}
        for t in all_trends:
            kw = t["keyword"]
            if kw in merged:
                merged[kw]["score"] += t["score"]
                merged[kw]["sources"].append(t["source"])
            else:
                merged[kw] = {
                    "keyword": kw,
                    "score": t["score"],
                    "sources": [t["source"]],
                }

        sorted_trends = sorted(
            merged.values(), key=lambda x: x["score"], reverse=True
        )

        print(f"\n  총 {len(sorted_trends)}개 트렌드 수집 완료")
        for i, t in enumerate(sorted_trends[:5]):
            sources = ", ".join(t["sources"])
            print(f"  {i + 1}. [{t['score']:,}점] {t['keyword']} ({sources})")

        return sorted_trends


# ============================================================================
# STEP 1.5: 뉴스 보강 - 팩트 기반 대본 원료
# ============================================================================
class NewsCollector:
    """트렌드 키워드 → Google News RSS + 네이버 뉴스 → 팩트 원료"""

    def fetch_google_news_rss(self, keyword: str) -> list[dict]:
        """Google News RSS - API 키 없이 키워드 검색"""
        import requests

        results = []
        try:
            url = (
                f"https://news.google.com/rss/search?"
                f"q={keyword}&hl=ko&gl=KR&ceid=KR:ko"
            )
            resp = requests.get(url, timeout=5)
            root = ET.fromstring(resp.text)

            for item in root.findall(".//item")[:5]:
                title = item.find("title")
                desc = item.find("description")
                if title is not None:
                    results.append({
                        "title": title.text or "",
                        "desc": (desc.text or "")[:200],
                        "source": "google_news",
                    })

            print(f"  [OK] Google News: {len(results)}건")
        except Exception as e:
            print(f"  [WARN] Google News 실패: {e}")

        return results

    def fetch_naver_news(self, keyword: str) -> list[dict]:
        """네이버 뉴스 크롤링 - 한국 뉴스 커버리지 최고"""
        import requests
        from bs4 import BeautifulSoup

        results = []
        try:
            url = f"https://search.naver.com/search.naver?where=news&query={keyword}"
            resp = requests.get(url, timeout=5, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0",
            })

            soup = BeautifulSoup(resp.text, "html.parser")
            news_items = soup.select(".news_tit") or soup.select("a.news_tit")

            for item in news_items[:5]:
                results.append({
                    "title": item.get_text(strip=True),
                    "desc": "",
                    "source": "naver_news",
                })

            print(f"  [OK] 네이버 뉴스: {len(results)}건")
        except Exception as e:
            print(f"  [WARN] 네이버 뉴스 실패: {e}")

        return results

    def collect_news(self, keyword: str) -> list[dict]:
        """두 소스 합산"""
        print(f"\n  뉴스 수집: '{keyword}'")
        news = []
        news.extend(self.fetch_google_news_rss(keyword))
        news.extend(self.fetch_naver_news(keyword))
        return news


# ============================================================================
# STEP 2: 대본 생성 (Gemini -> OpenAI 폴백)
# ============================================================================
class ScriptGenerator:
    """Gemini 2.0 Flash (무료, 1순위) -> GPT-4o-mini (유료, 2순위 폴백)"""

    PROMPT_TEMPLATE = """너는 에펨코리아 인기글을 읽어주는 유튜브 쇼츠 나레이터야.

규칙:
1. 아래 [원글 내용]을 20대 남성 말투로 읽어주기만 해. 절대 새로 지어내지 마.
2. 원글에 없는 내용 추가 금지. 팩트만 전달.
3. 첫 문장: "야 이거 실화임" 또는 "아니 이게 말이 돼?" 중 하나로 시작
4. 마지막 문장: "ㄹㅇ 레전드ㅋㅋ" 또는 "소름돋음ㄷㄷ" 중 하나로 끝
5. 문장당 최대 15자. 짧게 끊어.
6. "여러분", 사람이름, "경제학", "딜레마", **볼드**, "마무리하며" 전부 금지
7. 원글 body의 핵심 사실을 80% 이상 포함해야 함
8. 전체 대본 200~350자

{source_section}
주제: {topic}

[절대 금지 - 위반 시 대본 폐기]
- 사람 이름 (김서연, 박준호 등) -> "걔", "그놈", "사장", "알바생"으로 대체
- "여러분", "선택은?", "어떻게 생각해?", "의견을 남겨주세요"
- "경제학", "딜레마", "철학", "마무리하며", "결론적으로"
- "안녕하세요", "오늘은", "흥미로운", "살펴보겠습니다"
- **볼드**, 숫자/통계 지어내기, 이모지

[출력 형식 - 반드시 JSON]
{{
  "title": "숏츠 제목 (20자 이내, 이모지 금지, ㅋㅋ나 ㄷㄷ 사용 OK)",
  "tts_script": "TTS로 읽을 대본 전문",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "description": "유튜브 설명란 (2줄)"
}}"""

    def _build_prompt(self, topic: str, source_text: str) -> str:
        """프롬프트 생성 — 원글 본문이 있으면 [원글 내용]으로 전달"""
        if source_text:
            source_section = f"[원글 내용]\n{source_text[:2000]}"
        else:
            source_section = "[원글 내용]\n(본문 수집 실패 — 주제만으로 팩트 기반 대본 작성)"

        return self.PROMPT_TEMPLATE.format(
            topic=topic,
            source_section=source_section,
        )

    def _call_gemini(self, topic: str, source_text: str) -> Optional[dict]:
        """Gemini 2.0 Flash - 무료, 1순위"""
        try:
            import google.generativeai as genai

            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                print("  [WARN] GOOGLE_API_KEY 없음 -> 폴백")
                return None

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")

            prompt = self._build_prompt(topic, source_text)

            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.9,
                    max_output_tokens=1024,
                ),
            )

            # JSON 추출 (마크다운 코드블록 + 불완전 JSON 대응)
            text = response.text
            text = re.sub(r"```json\s*", "", text)
            text = re.sub(r"```\s*", "", text)
            text = text.strip()

            # JSON 객체 부분만 추출 ({...} 찾기)
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                text = json_match.group(0)

            # 제어 문자 제거
            text = re.sub(r'[\x00-\x1f]', ' ', text)
            text = text.replace('\n', '\\n')

            result = json.loads(text)
            print("  [OK] Gemini 대본 생성 성공")
            return result

        except Exception as e:
            print(f"  [WARN] Gemini 실패: {e}")
            return None

    def _call_openai(self, topic: str, source_text: str) -> Optional[dict]:
        """GPT-4o-mini - 유료, 2순위 폴백"""
        try:
            import openai

            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                return None

            client = openai.OpenAI(api_key=api_key)

            prompt = self._build_prompt(topic, source_text)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[{
                    "role": "user",
                    "content": prompt,
                }],
                temperature=0.9,
            )

            result = json.loads(response.choices[0].message.content)
            print("  [OK] OpenAI 대본 생성 성공")
            return result

        except Exception as e:
            print(f"  [WARN] OpenAI 실패: {e}")
            return None

    def _quality_check(self, script_data: dict) -> int:
        """품질 채점 (100점 만점, 감점 방식)"""
        score = 100
        reasons = []

        text = script_data.get("tts_script", "")
        title = script_data.get("title", "")

        # 1. 길이 체크 (프롬프트: 200~350자)
        if len(text) < 200:
            score -= 20
            reasons.append(f"너무 짧음 ({len(text)}자)")
        elif len(text) > 400:
            score -= 15
            reasons.append(f"너무 김 ({len(text)}자)")

        # 2. AI 슬롭 체크
        for word in Config.AI_SLOP_WORDS:
            if word in text:
                score -= 15
                reasons.append(f"AI슬롭: '{word}'")

        # 3. 실명 체크
        name_pattern = r"[김이박최정강조윤장임][가-힣]{1,2}(?:씨|님|이|가|을|를)"
        if re.search(name_pattern, text):
            score -= 20
            reasons.append("실명 포함 의심")

        # 4. 제목 길이
        if len(title) > 20:
            score -= 10
            reasons.append(f"제목 너무 김 ({len(title)}자)")

        # 5. 이모지 체크
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]"
        )
        if emoji_pattern.search(title) or emoji_pattern.search(text):
            score -= 10
            reasons.append("이모지 포함")

        # 6. 금지어 체크 (프롬프트 위반)
        banned = ["여러분", "어떻게 생각해", "의견을 남겨", "선택은?",
                  "경제학", "딜레마", "마무리하며", "결론적으로",
                  "안녕하세요", "오늘은", "살펴보겠"]
        for word in banned:
            if word in text:
                score -= 15
                reasons.append(f"금지어: '{word}'")

        # 7. 커뮤니티 마커 없으면 감점
        markers = ["ㅋㅋ", "ㄷㄷ", "ㄹㅇ", "ㅎㅎ", "실화", "미친", "레전드"]
        if not any(m in text for m in markers):
            score -= 10
            reasons.append("커뮤니티 말투 부족")

        score = max(0, score)

        if reasons:
            print(f"  품질: {score}점 (감점: {', '.join(reasons)})")
        else:
            print(f"  품질: {score}점 - 완벽")

        return score

    def _post_process(self, script_data: dict) -> dict:
        """후처리: AI 슬롭 제거 + 볼드 제거"""
        text = script_data.get("tts_script", "")

        # 볼드/마크다운 제거
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)

        # AI 슬롭 단어 교체
        replacements = {
            "흥미롭": "재밌",
            "놀라운": "대박인",
            "충격적": "미친",
            "심층": "진짜",
            "탐구": "파헤치",
            "알아보겠": "얘기해볼",
            "살펴보겠": "봐볼",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)

        script_data["tts_script"] = text
        return script_data

    def generate(self, topic: str, source_text: str = "") -> dict:
        """대본 생성 메인 - 품질 85점 이상까지 최대 3회, 실패 시 최선의 결과 사용"""
        print("\n" + "=" * 60)
        print("STEP 2: 대본 생성 (Gemini -> OpenAI 폴백)")
        print("=" * 60)

        if source_text:
            print(f"  원글 본문: {len(source_text)}자 전달")
        else:
            print("  [WARN] 원글 본문 없음 — 주제만으로 생성")

        best_result = None
        best_score = 0

        for attempt in range(Config.MAX_RETRY):
            print(f"\n  시도 {attempt + 1}/{Config.MAX_RETRY}")

            result = self._call_gemini(topic, source_text)
            if result is None:
                result = self._call_openai(topic, source_text)

            if result is None:
                print("  [ERROR] LLM 전부 실패")
                continue

            result = self._post_process(result)
            score = self._quality_check(result)

            # 최선의 결과 저장
            if score > best_score:
                best_score = score
                best_result = result.copy()
                best_result["quality_score"] = score

            if score >= Config.MIN_QUALITY_SCORE:
                result["quality_score"] = score
                print(f"\n  [OK] 대본 확정! (점수: {score})")
                print(f"  제목: {result.get('title', 'N/A')}")
                print(f"  길이: {len(result.get('tts_script', ''))}자")
                return result

            print(f"  [FAIL] {score}점 < {Config.MIN_QUALITY_SCORE}점 -> 재생성")

        # 3회 모두 미달이면 최선의 결과 사용 (100자 이상이면)
        if best_result and len(best_result.get("tts_script", "")) >= 100:
            print(f"\n  [WARN] 3회 미달 -> 최선의 결과 사용 ({best_score}점)")
            return best_result

        raise RuntimeError("대본 생성 실패: 3회 모두 품질 미달")


# ============================================================================
# STEP 3: TTS 생성 - edge-tts + 단어별 타이밍
# ============================================================================
class TTSEngine:
    """
    edge-tts 핵심: communicate().stream()의 WordBoundary 이벤트에서
    각 단어의 시작시간/지속시간을 수집 -> 자막 싱크에 사용
    """

    async def generate_with_timing(
        self, text: str, output_mp3: str
    ) -> list[dict]:
        """edge-tts로 음성 생성 + 단어별 타이밍 수집"""
        import edge_tts

        word_timings = []

        communicate = edge_tts.Communicate(
            text=text,
            voice=Config.TTS_VOICE,
            rate=Config.TTS_RATE,
            pitch=Config.TTS_PITCH,
        )

        with open(output_mp3, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])

                elif chunk["type"] == "WordBoundary":
                    word_timings.append({
                        "word": chunk["text"],
                        "start_ms": chunk["offset"] // 10000,
                        "end_ms": (chunk["offset"] + chunk["duration"]) // 10000,
                    })

        print(f"  [OK] TTS 생성: {output_mp3}")
        print(f"  단어 타이밍: {len(word_timings)}개 단어 수집")

        if word_timings:
            total_ms = word_timings[-1]["end_ms"]
            print(f"  총 길이: {total_ms / 1000:.1f}초")

            if total_ms > Config.MAX_DURATION * 1000:
                print(f"  [WARN] {Config.MAX_DURATION}초 초과!")

        return word_timings

    def generate(self, text: str, output_mp3: str) -> list[dict]:
        """동기 래퍼"""
        print("\n" + "=" * 60)
        print("STEP 3: TTS 생성 (edge-tts + 단어별 타이밍)")
        print("=" * 60)

        return asyncio.run(
            self.generate_with_timing(text, output_mp3)
        )


# ============================================================================
# STEP 4: 단어별 하이라이트 자막 (ASS 형식)
# ============================================================================
class SubtitleGenerator:
    """
    ASS 형식 단어별 하이라이트
    현재 말하는 단어 = 노란색, 나머지 = 흰색
    """

    def _group_words_into_lines(
        self, word_timings: list[dict], max_chars: int = 15
    ) -> list[dict]:
        """단어들을 자막 줄로 그룹화 (한 줄 max_chars 글자)"""
        lines = []
        current_line = []
        current_chars = 0

        for wt in word_timings:
            word = wt["word"].strip()
            if not word:
                continue

            if current_chars + len(word) > max_chars and current_line:
                lines.append({
                    "words": current_line.copy(),
                    "start_ms": current_line[0]["start_ms"],
                    "end_ms": current_line[-1]["end_ms"],
                })
                current_line = []
                current_chars = 0

            current_line.append(wt)
            current_chars += len(word) + 1

        if current_line:
            lines.append({
                "words": current_line,
                "start_ms": current_line[0]["start_ms"],
                "end_ms": current_line[-1]["end_ms"],
            })

        return lines

    def _ms_to_ass_time(self, ms: int) -> str:
        """밀리초 -> ASS 타임코드 (H:MM:SS.CC)"""
        h = ms // 3600000
        m = (ms % 3600000) // 60000
        s = (ms % 60000) // 1000
        cs = (ms % 1000) // 10
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def generate_ass(
        self, word_timings: list[dict], output_ass: str
    ) -> str:
        """ASS 자막 파일 생성 - 단어별 하이라이트"""
        lines = self._group_words_into_lines(word_timings)

        # ASS 헤더
        ass_content = f"""[Script Info]
Title: youshorts subtitles
ScriptType: v4.00+
PlayResX: {Config.WIDTH}
PlayResY: {Config.HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{Config.SUBTITLE_FONT},{Config.SUBTITLE_SIZE},{Config.SUBTITLE_COLOR_NORMAL},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{Config.SUBTITLE_OUTLINE},{Config.SUBTITLE_SHADOW},2,40,40,{Config.SUBTITLE_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        for line in lines:
            words_in_line = line["words"]

            for wi, current_word in enumerate(words_in_line):
                start = self._ms_to_ass_time(current_word["start_ms"])

                if wi + 1 < len(words_in_line):
                    end = self._ms_to_ass_time(
                        words_in_line[wi + 1]["start_ms"]
                    )
                else:
                    end = self._ms_to_ass_time(current_word["end_ms"])

                text_parts = []
                for wj, w in enumerate(words_in_line):
                    word_text = w["word"].strip()
                    if not word_text:
                        continue

                    if wj == wi:
                        text_parts.append(
                            f"{{\\c{Config.SUBTITLE_COLOR_HIGHLIGHT}"
                            f"\\b1}}{word_text}{{\\r}}"
                        )
                    else:
                        text_parts.append(
                            f"{{\\c{Config.SUBTITLE_COLOR_NORMAL}"
                            f"}}{word_text}{{\\r}}"
                        )

                dialogue_text = " ".join(text_parts)
                ass_content += (
                    f"Dialogue: 0,{start},{end},Default,,0,0,0,,"
                    f"{dialogue_text}\n"
                )

        with open(output_ass, "w", encoding="utf-8") as f:
            f.write(ass_content)

        print(f"  [OK] ASS 자막 생성: {output_ass}")
        print(f"  {len(lines)}개 줄, 단어별 하이라이트 적용")

        return output_ass

    def generate_ass_from_chunks(
        self, script: str, duration_sec: float, output_ass: str
    ) -> str:
        """
        WordBoundary가 0개일 때 (한국어 edge-tts 제한) 폴백:
        텍스트를 균등 분할하여 청크 기반 하이라이트 생성
        현재 청크 = 노란색, 다음 청크 = 흰색 프리뷰
        """
        # 문장 단위로 분할
        sentences = re.split(r'(?<=[.!?。])\s*', script)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            sentences = [script]

        # 각 문장을 15자 이내 청크로 분할
        chunks = []
        for sent in sentences:
            while len(sent) > 15:
                # 공백 기준으로 자르기
                cut_pos = sent[:15].rfind(" ")
                if cut_pos <= 0:
                    cut_pos = 15
                chunks.append(sent[:cut_pos].strip())
                sent = sent[cut_pos:].strip()
            if sent:
                chunks.append(sent)

        if not chunks:
            chunks = [script[:15]]

        # 균등 시간 배분
        chunk_duration_ms = int((duration_sec * 1000) / len(chunks))

        # ASS 헤더
        ass_content = f"""[Script Info]
Title: youshorts subtitles
ScriptType: v4.00+
PlayResX: {Config.WIDTH}
PlayResY: {Config.HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{Config.SUBTITLE_FONT},{Config.SUBTITLE_SIZE},{Config.SUBTITLE_COLOR_NORMAL},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{Config.SUBTITLE_OUTLINE},{Config.SUBTITLE_SHADOW},2,40,40,{Config.SUBTITLE_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        yellow = "{\\c&H0000FFFF&\\b1}"
        white = "{\\c&H00FFFFFF&\\b0}"
        reset = "{\\r}"

        for i, chunk in enumerate(chunks):
            start_ms = i * chunk_duration_ms
            end_ms = (i + 1) * chunk_duration_ms
            start = self._ms_to_ass_time(start_ms)
            end = self._ms_to_ass_time(end_ms)

            if i + 1 < len(chunks):
                combined = f"{yellow}{chunk}{reset}\\N{white}{chunks[i + 1]}{reset}"
            else:
                combined = f"{yellow}{chunk}{reset}"

            ass_content += (
                f"Dialogue: 0,{start},{end},Default,,0,0,0,,"
                f"{combined}\n"
            )

        with open(output_ass, "w", encoding="utf-8") as f:
            f.write(ass_content)

        print(f"  [OK] ASS 자막 생성 (청크 기반 폴백): {output_ass}")
        print(f"  {len(chunks)}개 청크, 현재=노란/다음=흰색")

        return output_ass


# ============================================================================
# STEP 5: 배경 영상 + BGM + 렌더링
# ============================================================================
class VideoRenderer:
    """
    렌더링 전략:
    1. 로컬 subway_surfers 배경 (랜덤 시작점)
    2. TTS + BGM(15% 볼륨) 오디오 믹싱
    3. ASS 자막 번인
    4. 전부 FFmpeg CLI 한 줄로 처리
    """

    def _find_ffmpeg(self) -> str:
        """ffmpeg 경로 탐색"""
        # imageio_ffmpeg 우선
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
        # PATH에서 탐색
        return Config.FFMPEG_EXE

    def _find_ffprobe(self) -> str:
        """ffprobe 경로 탐색"""
        try:
            import imageio_ffmpeg
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")
            if os.path.exists(ffprobe_path):
                return ffprobe_path
        except ImportError:
            pass
        return Config.FFPROBE_EXE

    def _get_background_video(self) -> Optional[str]:
        """로컬 배경 영상 랜덤 선택 (하위 디렉토리 포함)"""
        bg_dir = Config.BG_DIR
        if not bg_dir.exists():
            print(f"  [WARN] 배경 폴더 없음: {bg_dir}")
            return None

        # 하위 디렉토리까지 재귀 탐색
        videos = list(bg_dir.rglob("*.mp4"))
        if not videos:
            print("  [WARN] 배경 영상 없음")
            return None

        selected = random.choice(videos)
        print(f"  배경 선택: {selected.name}")
        return str(selected)

    def _get_random_bgm(self) -> Optional[str]:
        """BGM 랜덤 선택 (없으면 None)"""
        bgm_dir = Config.BGM_DIR
        if not bgm_dir.exists():
            return None

        bgms = list(bgm_dir.glob("*.mp3"))
        if not bgms:
            return None

        selected = random.choice(bgms)
        print(f"  BGM 선택: {selected.name}")
        return str(selected)

    def _get_video_duration(self, video_path: str) -> float:
        """FFprobe로 영상/오디오 길이 확인"""
        ffprobe = self._find_ffprobe()
        try:
            result = subprocess.run(
                [
                    ffprobe, "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0", video_path,
                ],
                capture_output=True, text=True, timeout=10,
            )
            return float(result.stdout.strip())
        except Exception:
            return 300  # 기본값 5분

    def render(
        self,
        tts_mp3: str,
        ass_subtitle: str,
        output_mp4: str,
    ) -> str:
        """최종 렌더링 - FFmpeg"""
        print("\n" + "=" * 60)
        print("STEP 5: FFmpeg 렌더링")
        print("=" * 60)

        ffmpeg = self._find_ffmpeg()
        bg_video = self._get_background_video()
        bgm_mp3 = self._get_random_bgm()

        # TTS 길이 확인
        tts_duration = self._get_video_duration(tts_mp3)
        target_duration = min(tts_duration + 1.5, Config.MAX_DURATION)

        # 배경 영상 랜덤 시작점 계산
        random_start = 0
        if bg_video:
            bg_duration = self._get_video_duration(bg_video)
            max_start = max(0, bg_duration - target_duration - 5)
            random_start = random.uniform(0, max_start) if max_start > 0 else 0

        # ── FFmpeg 명령어 조립 ──
        cmd = [ffmpeg, "-y"]

        # 입력 1: 배경 영상
        if bg_video:
            cmd.extend(["-ss", f"{random_start:.1f}", "-i", bg_video])
        else:
            cmd.extend([
                "-f", "lavfi", "-i",
                f"color=c=black:s={Config.WIDTH}x{Config.HEIGHT}:"
                f"r={Config.FPS}:d={target_duration}",
            ])

        # 입력 2: TTS 오디오
        cmd.extend(["-i", tts_mp3])

        # 입력 3: BGM (있으면)
        input_idx_bgm = None
        if bgm_mp3:
            cmd.extend(["-i", bgm_mp3])
            input_idx_bgm = 2

        # ── 필터 체인 조립 ──
        video_filters = []

        # 9:16 크롭
        video_filters.append("crop=ih*9/16:ih:(iw-ih*9/16)/2:0")
        # 스케일
        video_filters.append(f"scale={Config.WIDTH}:{Config.HEIGHT}")

        # ASS 자막 번인 (상대 경로 temp/sub.ass — Windows FFmpeg 호환)
        if os.path.exists(ass_subtitle):
            import shutil
            os.makedirs("temp", exist_ok=True)
            safe_sub = os.path.join("temp", "sub.ass")
            shutil.copy2(ass_subtitle, safe_sub)
            safe_sub_escaped = safe_sub.replace("\\", "/")
            video_filters.append(f"ass='{safe_sub_escaped}'")

        video_filter_str = ",".join(video_filters)

        # 오디오 필터: TTS + BGM 믹싱
        if input_idx_bgm is not None:
            audio_filter = (
                f"[{input_idx_bgm}:a]volume=0.15,aloop=loop=-1:size=2e+09[bgm];"
                f"[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            cmd.extend([
                "-filter_complex",
                f"[0:v]{video_filter_str}[vout];{audio_filter}",
                "-map", "[vout]",
                "-map", "[aout]",
            ])
        else:
            cmd.extend([
                "-vf", video_filter_str,
                "-map", "0:v",
                "-map", "1:a",
            ])

        # 출력 설정
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{target_duration:.1f}",
            "-shortest",
            output_mp4,
        ])

        print(f"  렌더링 시작...")
        print(f"  목표 길이: {target_duration:.1f}초")
        if bg_video:
            print(f"  배경 랜덤 시작: {random_start:.1f}초")

        result = subprocess.run(cmd, capture_output=True, timeout=300)

        if result.returncode == 0 and os.path.exists(output_mp4):
            size_mb = os.path.getsize(output_mp4) / (1024 * 1024)
            print(f"  [OK] 렌더링 완료: {output_mp4}")
            print(f"  파일 크기: {size_mb:.1f}MB")
            return output_mp4
        else:
            stderr = result.stderr.decode("utf-8", errors="ignore")
            print(f"  [ERROR] 렌더링 실패:")
            print(f"  {stderr[-500:]}")
            raise RuntimeError("FFmpeg 렌더링 실패")


# ============================================================================
# STEP 6: 생성 이력 저장 (중복 방지)
# ============================================================================
class HistoryManager:
    """history.json으로 중복 방지"""

    def __init__(self):
        self.history_file = Config.HISTORY_FILE
        self._ensure_file()

    def _ensure_file(self):
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_file.exists():
            self.history_file.write_text("[]", encoding="utf-8")

    def _load(self) -> list[dict]:
        try:
            return json.loads(
                self.history_file.read_text(encoding="utf-8")
            )
        except Exception:
            return []

    def is_duplicate(self, topic: str) -> bool:
        """Jaccard 유사도로 중복 체크 (80% 이상이면 중복)"""
        history = self._load()

        for h in history:
            prev_topic = h.get("topic", "")
            set_a = set(topic)
            set_b = set(prev_topic)
            if not set_a or not set_b:
                continue
            overlap = len(set_a & set_b) / len(set_a | set_b)
            if overlap > 0.8:
                return True

        return False

    def save(self, topic: str, title: str, output_file: str):
        history = self._load()
        history.append({
            "topic": topic,
            "title": title,
            "file": output_file,
            "date": datetime.now().isoformat(),
        })
        self.history_file.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  [OK] 이력 저장 완료 (총 {len(history)}건)")


# ============================================================================
# 메인 파이프라인 - 영상 1개 완벽 생성
# ============================================================================
def make_one_perfect_short():
    """
    youshorts 완벽한 영상 1개 생성 파이프라인

    1. 트렌드 수집 (Google+네이버+커뮤니티)
    2. 뉴스 보강 (팩트 원료)
    3. 대본 생성 (Gemini->OpenAI, 3회 재시도)
    4. TTS 생성 (edge-tts + 단어별 타이밍)
    5. 자막 생성 (ASS 단어별 하이라이트)
    6. 렌더링 (FFmpeg: 배경+TTS+BGM+자막)
    7. 이력 저장 (중복 방지)
    """

    start_time = time.time()

    print("\n" + "=" * 60)
    print("  youshorts - 완벽한 영상 1개 생성 시작")
    print("=" * 60)

    # 작업 디렉토리 생성
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = Config.OUTPUT_DIR / f"session_{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # ── STEP 1: 트렌드 수집 ──
    trend_collector = TrendCollector()
    trends = trend_collector.collect_all()

    if not trends:
        print("\n  [WARN] 트렌드 수집 실패 -> 기본 주제 사용")
        trends = [{"keyword": "요즘 편의점 신상 꿀조합", "score": 0}]

    # 중복 체크
    history = HistoryManager()
    selected_trend = None
    for t in trends:
        if not history.is_duplicate(t["keyword"]):
            selected_trend = t
            break

    if not selected_trend:
        selected_trend = trends[0]

    selected_topic = selected_trend["keyword"]
    print(f"\n  선정된 주제: {selected_topic}")

    # ── STEP 1.5: 본문 크롤링 (커뮤니티 게시글이면 URL에서 본문 수집) ──
    source_text = ""
    post_url = selected_trend.get("url", "")
    if post_url and "community_" in selected_trend.get("source", ""):
        print(f"\n  본문 크롤링 시도: {post_url[:80]}...")
        source_text = trend_collector.fetch_post_body(post_url)
        if source_text:
            print(f"  [OK] 본문 수집: {len(source_text)}자")
        else:
            print("  [WARN] 본문 수집 실패 — 뉴스로 보강")

    # 본문이 없으면 뉴스에서 팩트 원료 수집
    if not source_text:
        news_collector = NewsCollector()
        news = news_collector.collect_news(selected_topic)
        # 뉴스 제목들을 source_text로 합침
        if news:
            source_text = "\n".join(
                [f"- {n['title']}: {n.get('desc', '')}" for n in news[:5]]
            )

    # ── STEP 2: 대본 생성 ──
    script_gen = ScriptGenerator()
    script_data = script_gen.generate(selected_topic, source_text)

    # 대본 저장
    script_file = work_dir / "script.json"
    script_file.write_text(
        json.dumps(script_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ── STEP 3: TTS 생성 ──
    tts_engine = TTSEngine()
    tts_mp3 = str(work_dir / "tts.mp3")
    word_timings = tts_engine.generate(
        script_data["tts_script"], tts_mp3
    )

    # 타이밍 저장
    timing_file = work_dir / "word_timings.json"
    timing_file.write_text(
        json.dumps(word_timings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ── STEP 4: 자막 생성 ──
    print("\n" + "=" * 60)
    print("STEP 4: 단어별 하이라이트 자막 (ASS)")
    print("=" * 60)

    subtitle_gen = SubtitleGenerator()
    ass_file = str(work_dir / "subtitles.ass")

    if word_timings:
        # 단어별 타이밍 있음 -> 진짜 워드 하이라이트
        subtitle_gen.generate_ass(word_timings, ass_file)
    else:
        # 한국어 edge-tts WordBoundary 미지원 -> 청크 기반 폴백
        tts_duration = 40.0  # 기본값
        try:
            renderer = VideoRenderer()
            tts_duration = renderer._get_video_duration(tts_mp3)
        except Exception:
            pass
        subtitle_gen.generate_ass_from_chunks(
            script_data["tts_script"], tts_duration, ass_file
        )

    # ── STEP 5: 렌더링 ──
    safe_title = re.sub(r'[\\/*?:"<>|()!\[\]{}]', '', script_data["title"])
    safe_title = safe_title.replace(" ", "_")[:30]  # 최대 30자
    output_filename = f"shorts_{safe_title}_{timestamp}.mp4"
    output_mp4 = str(work_dir / output_filename)

    renderer = VideoRenderer()
    final_video = renderer.render(tts_mp3, ass_file, output_mp4)

    # ── STEP 6: 이력 저장 ──
    print("\n" + "=" * 60)
    print("STEP 6: 이력 저장")
    print("=" * 60)
    history.save(selected_topic, script_data["title"], final_video)

    # ── 완료 ──
    elapsed = time.time() - start_time

    print("\n" + "=" * 60)
    print(f"  영상 생성 완료!")
    print(f"  파일: {final_video}")
    print(f"  제목: {script_data['title']}")
    print(f"  품질: {script_data.get('quality_score', 'N/A')}점")
    print(f"  소요시간: {elapsed:.1f}초")
    print(f"  태그: {', '.join(script_data.get('tags', []))}")
    print("=" * 60)

    return {
        "video": final_video,
        "title": script_data["title"],
        "description": script_data.get("description", ""),
        "tags": script_data.get("tags", []),
        "quality_score": script_data.get("quality_score", 0),
        "elapsed_seconds": elapsed,
    }


# ============================================================================
# 실행
# ============================================================================
if __name__ == "__main__":
    result = make_one_perfect_short()
