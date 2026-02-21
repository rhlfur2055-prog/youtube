#!/usr/bin/env python3
"""
crawl_trends.py — 트렌드 크롤링 → topics.txt 자동 채우기

7개 소스(Google Trends RSS, 네이버, YouTube, 네이트판, 디시, 에펨, 인스티즈)에서
실시간 트렌드를 수집하고, 블랙리스트/부스트/중복제거를 거쳐
topics.txt에 숏츠 주제를 어펜드한다.

Usage:
    python crawl_trends.py                    # 기본: 10개 수집
    python crawl_trends.py --count 5          # 5개만
    python crawl_trends.py --dry-run          # 출력만, 저장 안 함
    python crawl_trends.py --no-gemini        # AI 평가 스킵
    python crawl_trends.py --source google    # 특정 소스만
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ── Windows UTF-8 강제 ──
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

import requests
from bs4 import BeautifulSoup

# ============================================================
# 상수
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
TOPICS_FILE = BASE_DIR / "topics.txt"
HISTORY_FILE = BASE_DIR / "data" / "topic_history.json"

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)
_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# ── 블랙리스트 (170+ 금지어) ──
BLACKLIST = [
    # 정치
    "국회", "대통령", "탄핵", "여당", "야당", "민주당", "국민의힘",
    "총선", "선거", "후보", "정당", "의원", "청와대", "정부",
    "외교", "북한", "한미", "정상회담", "국방", "안보",
    "친노", "친문", "친윤", "좌파", "우파", "진보", "보수",
    "이재명", "윤석열", "한동훈", "이낙연", "손학규",
    "똥파리", "손가혁", "문빠", "윤빠", "국짐", "민짜",
    "핵협상", "속보", "긴급",
    # 경제
    "금리", "환율", "증시", "코스피", "코스닥", "주가", "GDP",
    "물가", "인플레이션", "기준금리", "한은", "국채",
    # 사건사고
    "사망", "사고", "화재", "지진", "태풍", "폭발", "추모",
    "유족", "희생", "참사", "실종", "붕괴",
    # 법률
    "재판", "판결", "구속", "기소", "검찰", "경찰", "수사",
    "피의자", "혐의", "체포", "송치",
    # 행정
    "국무회의", "예산", "법안", "조례", "감사원", "규제",
    # 커뮤니티 잡글
    "공지", "통합", "체험단", "모집", "이벤트", "광고", "제휴",
    "스포", "질문드립니다", "질문있습니다", "문의", "안내",
    "구인", "구직", "팝니다", "삽니다", "한줄평", "설문",
    # 숏츠 부적합
    "밥상", "명절", "시어머니", "며느리",
    "택시", "심쿵", "로맨스",
    # 시즌/명절
    "설날", "새해", "추석", "한가위", "크리스마스", "성탄절",
    "발렌타인", "화이트데이", "어버이날", "스승의날",
    "졸업식", "입학식", "수능", "수능날",
    # 광고/스팸
    "텔레그램", "단톡방", "카톡방", "오픈채팅",
    "비트코인", "가상화폐", "코인", "NFT",
    "투자", "수익률", "원금보장",
    "무료나눔", "선착순", "할인코드",
    # 의료/건강 허위정보
    "암 치료", "특효약", "민간요법", "자가진단",
    "병원에서 안 알려주는", "의사가 숨기는",
    # 성인/부적절
    "후방주의", "19금", "은꼴",
    # 추가 정치 은어
    "정치인", "국정감사", "헌재", "헌법재판소", "계엄",
    "시위", "집회", "데모", "찬성", "반대표",
    "임명", "탄핵안", "불체포", "특검",
    # 추가 사건사고
    "학대", "폭행", "성폭행", "성범죄", "살인",
    "납치", "테러", "자살", "극단적 선택",
    # 추가 광고/스팸
    "리워드", "앱테크", "돈벌기", "재택부업",
    "당일입금", "간편대출", "저금리대출",
    # 종교 논쟁
    "신천지", "사이비", "이단",
    # 혐오
    "한남", "한녀", "페미", "래디컬",
    # v6.2: 숏츠 부적합 추가 — 자극적 낚시/가십/밈 반복 방지
    "남편", "아내", "불륜", "열애", "코스프레",
    "탈영", "괴담", "실화냐", "충격",
]

# ── 바이럴 부스트 키워드 (차등 점수) ──
# 조회수 폭발 키워드 → +20,000점
BOOST_TIER1 = [
    "실화", "충격", "소름", "반전", "모르는", "꿀팁", "비밀",
]
# 관심 유발 키워드 → +10,000점
BOOST_TIER2 = [
    "왜", "어떻게", "진짜", "레전드",
]
# 기존 범용 부스트 → +20,000점
BOOST_KEYWORDS = [
    "대박", "미쳤", "논란",
    "후기", "먹방", "게임", "리뷰",
    "아이돌", "드라마", "영화", "웹툰",
    "밈", "챌린지", "핫", "터짐", "난리",
    "비교", "랭킹", "순위", "VS", "TOP",
    "해봄", "써봄", "사봄", "가봄",
    "월급", "퇴사", "야근", "자취", "월세", "전세",
    "사회초년생", "직장상사", "꼰대", "MZ", "워라밸",
    "연봉", "이직", "알바", "면접", "취준",
    "썸", "소개팅", "결혼", "축의금", "청첩장",
    "연애", "재테크", "고백", "적금", "청약",
]

# ── 숏츠 폭발력 카테고리 (조회수 100만+ 실적 기반) ──
VIRAL_CATEGORIES = {
    "공포_미스터리": {
        "keywords": [
            "공포", "귀신", "심령", "미스터리", "소름", "무서운", "괴담",
            "호러", "폐건물", "도시전설", "납골당", "저주",
        ],
        "boost": 50000,
    },
    "놀라운_사실": {
        "keywords": [
            "충격", "알고보니", "진실", "몰랐던", "비밀", "반전",
            "실화", "레전드", "역대급", "미쳤", "경악",
        ],
        "boost": 45000,
    },
    "문화충격_반응": {
        "keywords": [
            "외국인", "문화충격", "반응", "한국", "해외", "리액션",
            "충격받", "놀란", "차이점", "비교문화",
        ],
        "boost": 45000,
    },
    "밈_유머": {
        "keywords": [
            "밈", "짤", "ㅋㅋ", "웃긴", "개웃", "존웃", "킹받",
            "빡침", "어이없", "황당", "해프닝", "웃참",
        ],
        "boost": 40000,
    },
    "비교_랭킹": {
        "keywords": [
            "비교", "VS", "랭킹", "순위", "TOP", "1위",
            "최고", "최악", "차이", "어떤게", "뭐가",
        ],
        "boost": 40000,
    },
    "꿀팁_라이프핵": {
        "keywords": [
            "꿀팁", "방법", "노하우", "핵꿀", "개꿀", "팁",
            "가성비", "알뜰", "저렴", "아끼는", "절약",
        ],
        "boost": 35000,
    },
    "게임_애니": {
        "keywords": [
            "게임", "롤", "발로란트", "마크", "원신", "애니",
            "원피스", "귀멸", "나루토", "주술회전", "진격",
        ],
        "boost": 35000,
    },
}

# ── 숏츠 부적합 감점 패턴 ──
BORING_PENALTIES = [
    (r"남친|여친|남자친구|여자친구|설거지|시댁|시어머니|결혼식", -30000, "연애/결혼 일상"),
    (r"회사|직장|퇴근|출근|야근|상사|선배|신입", -20000, "직장 일상"),
    (r"다이어트|식단|운동|헬스", -15000, "다이어트 일상"),
    (r"카페|맛집|디저트|빵집", -15000, "카페/맛집 일상"),
    (r"열애|결별|소속사|컴백|앨범|팬싸", -10000, "연예 단순뉴스"),
]

# ── 커뮤니티 잡글 패턴 ──
JUNK_PATTERNS = [
    "?", "질문", "뭘까", "어떻게", "하는건가", "드립니다",
    "중요", "변경 권장", "규칙", "카테고리",
    "댓글부탁", "조언", "부탁드려", "문의드",
]


# ============================================================
# TrendSource: 7개 소스 크롤러
# ============================================================

class TrendSource:
    """트렌드 수집 — 각 메서드는 실패 시 빈 리스트 반환"""

    @staticmethod
    def fetch_google_trends_rss() -> list[dict]:
        """Google Trends KR RSS — 무인증, IP 차단 0%"""
        results = []
        try:
            resp = requests.get(
                "https://trends.google.co.kr/trending/rss?geo=KR",
                timeout=10,
                headers={"User-Agent": _DESKTOP_UA},
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            ns = {"ht": "https://trends.google.co.kr/trending/rss"}

            for idx, item in enumerate(root.findall(".//item")):
                title = item.find("title")
                if title is None or not title.text:
                    continue
                traffic = item.find("ht:approx_traffic", ns)
                traffic_num = 0
                if traffic is not None and traffic.text:
                    traffic_num = int(
                        traffic.text.replace(",", "").replace("+", "")
                    )
                if traffic_num == 0:
                    traffic_num = max(50000 - idx * 3000, 10000)
                results.append({
                    "keyword": title.text.strip(),
                    "source": "google_trends",
                    "score": traffic_num * 2,  # v6.2: 가중치 2배
                })
            print(f"  [OK] Google Trends: {len(results)}개 수집")
        except Exception as e:
            print(f"  [WARN] Google Trends 실패: {e}")
        return results

    @staticmethod
    def fetch_naver_realtime() -> list[dict]:
        """네이버 트렌드 수집 (급상승 검색어 2021년 폐지 대응)

        안정적 대체 소스 2가지:
        1) 네이버 뉴스 랭킹 (popularDay) — 많이 본 뉴스 제목
        2) 네이버 자동완성 API — 실시간 인기 검색 키워드
        """
        results = []

        # 1) 네이버 뉴스 랭킹 — 가장 안정적인 트렌드 소스
        try:
            resp = requests.get(
                "https://news.naver.com/main/ranking/popularDay.naver",
                timeout=10,
                headers={
                    "User-Agent": _DESKTOP_UA,
                    "Accept-Language": "ko-KR,ko;q=0.9",
                    "Referer": "https://news.naver.com/",
                },
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # 랭킹 기사 제목: 여러 셀렉터 시도 (네이버 구조 변경 대비)
                titles = (
                    soup.select("a.list_title")
                    or soup.select(".rankingnews_list a")
                    or soup.select("strong.list_title")
                    or soup.select("a[href*='article']")
                )
                count = 0
                for i, t in enumerate(titles[:30]):
                    text = t.get_text(strip=True)
                    # 너무 짧거나 네비게이션 링크 제외
                    if not text or len(text) < 8 or len(text) > 100:
                        continue
                    results.append({
                        "keyword": text,
                        "source": "naver_news",
                        "score": max(45000 - count * 2000, 5000),
                    })
                    count += 1
                    if count >= 15:
                        break
                if count:
                    print(f"  [OK] 네이버 뉴스 랭킹: {count}개")
        except Exception as e:
            print(f"  [WARN] 네이버 뉴스 랭킹 실패: {e}")

        # 2) 네이버 자동완성 API — 실시간 인기 키워드 (JSON, 안정적)
        try:
            seeds = ["요즘", "실시간", "핫한", "화제", "난리"]
            suggest_count = 0
            for seed in seeds:
                url = (
                    f"https://ac.search.naver.com/nx/ac"
                    f"?q={seed}&con=1&frm=nv&ans=2&r_format=json"
                    f"&r_enc=UTF-8&r_unicode=0&t_koreng=1&run=2&rev=4&q_enc=UTF-8"
                )
                resp = requests.get(
                    url, timeout=8,
                    headers={"User-Agent": _DESKTOP_UA, "Referer": "https://www.naver.com/"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [[]])[0] if data.get("items") else []
                    for i, item in enumerate(items[:5]):
                        if isinstance(item, list) and item:
                            kw = item[0]
                        elif isinstance(item, str):
                            kw = item
                        else:
                            continue
                        if kw and len(kw) > 1 and kw != seed:
                            results.append({
                                "keyword": kw,
                                "source": "naver_suggest",
                                "score": (5 - i) * 4000,
                            })
                            suggest_count += 1
            if suggest_count:
                print(f"  [OK] 네이버 자동완성: {suggest_count}개")
        except Exception as e:
            print(f"  [WARN] 네이버 자동완성 실패: {e}")

        # 중복 제거
        seen = set()
        deduped = []
        for r in results:
            key = r["keyword"][:15]
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        results = deduped

        if results:
            print(f"  [OK] 네이버 합계: {len(results)}개 수집")
        else:
            print(f"  [WARN] 네이버 수집 실패")
        return results

    @staticmethod
    def fetch_youtube_trending() -> list[dict]:
        """YouTube 트렌딩 — Tier1: ytInitialData, Tier2: 자동완성 폴백"""
        results = []

        # Tier 1: ytInitialData 추출
        try:
            resp = requests.get(
                "https://www.youtube.com/feed/trending?gl=KR&hl=ko",
                timeout=15,
                headers={
                    "User-Agent": _DESKTOP_UA,
                    "Accept-Language": "ko-KR,ko;q=0.9",
                },
            )
            if resp.status_code == 200:
                # <script>var ytInitialData = {...};</script> 에서 JSON 추출
                m = re.search(
                    r'var\s+ytInitialData\s*=\s*(\{.*?\});\s*</script>',
                    resp.text,
                    re.DOTALL,
                )
                if m:
                    data = json.loads(m.group(1))
                    # 탭 구조에서 비디오 렌더러 추출
                    tabs = (
                        data.get("contents", {})
                        .get("twoColumnBrowseResultsRenderer", {})
                        .get("tabs", [])
                    )
                    for tab in tabs:
                        tab_content = (
                            tab.get("tabRenderer", {})
                            .get("content", {})
                            .get("sectionListRenderer", {})
                            .get("contents", [])
                        )
                        for section in tab_content:
                            items = (
                                section.get("itemSectionRenderer", {})
                                .get("contents", [{}])[0]
                                .get("shelfRenderer", {})
                                .get("content", {})
                                .get("expandedShelfContentsRenderer", {})
                                .get("items", [])
                            )
                            for idx, vi in enumerate(items[:20]):
                                renderer = vi.get("videoRenderer", {})
                                title = renderer.get("title", {}).get("runs", [{}])
                                if title:
                                    title_text = title[0].get("text", "")
                                    if title_text and len(title_text) > 3:
                                        # 조회수 추출
                                        view_text = renderer.get(
                                            "viewCountText", {}
                                        ).get("simpleText", "")
                                        view_count = 0
                                        vm = re.search(r'([\d,]+)', view_text)
                                        if vm:
                                            view_count = int(
                                                vm.group(1).replace(",", "")
                                            )
                                        results.append({
                                            "keyword": title_text,
                                            "source": "youtube_trending",
                                            "score": max(
                                                view_count // 100,
                                                (20 - idx) * 3000,
                                            ) * 2,  # v6.2: 가중치 2배
                                        })
                    if results:
                        print(f"  [OK] YouTube Trending (ytInitialData): {len(results)}개")
        except Exception as e:
            print(f"  [WARN] YouTube ytInitialData 실패: {e}")

        # Tier 2: 자동완성 폴백
        if not results:
            try:
                seeds = [
                    "한국인이라면", "직장인 공감", "요즘 난리난",
                    "실제로 있었던", "충격적인 사실", "알고보면",
                    "모르면 손해", "요즘 유행",
                ]
                for seed in seeds:
                    url = (
                        "https://suggestqueries-clients6.youtube.com"
                        f"/complete/search?client=youtube&hl=ko&gl=kr&q={seed}"
                    )
                    resp = requests.get(url, timeout=8, headers={"User-Agent": _DESKTOP_UA})
                    if resp.status_code == 200:
                        # JSONP 형식: window.google.ac.h([...])
                        text = resp.text
                        m = re.search(r'\[.*\]', text, re.DOTALL)
                        if m:
                            try:
                                arr = json.loads(m.group(0))
                                if len(arr) > 1 and isinstance(arr[1], list):
                                    for i, suggestion in enumerate(arr[1][:5]):
                                        if isinstance(suggestion, list) and suggestion:
                                            kw = suggestion[0]
                                            if isinstance(kw, str) and len(kw) > 2:
                                                results.append({
                                                    "keyword": kw,
                                                    "source": "youtube_suggest",
                                                    "score": (5 - i) * 5000 * 2,  # v6.2: 가중치 2배
                                                })
                            except json.JSONDecodeError:
                                pass
                if results:
                    print(f"  [OK] YouTube 자동완성 폴백: {len(results)}개")
            except Exception as e:
                print(f"  [WARN] YouTube 자동완성 실패: {e}")

        if not results:
            print(f"  [WARN] YouTube 수집 실패")
        return results

    @staticmethod
    def fetch_natepann() -> list[dict]:
        """네이트판 명예의전당 + 오늘의판 (모바일)"""
        results = []
        urls = [
            "https://m.pann.nate.com/talk/ranking",
            "https://m.pann.nate.com/talk/today",
        ]
        try:
            for page_url in urls:
                try:
                    resp = requests.get(
                        page_url,
                        headers={"User-Agent": _MOBILE_UA},
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")

                    for a_tag in soup.select("a"):
                        href = a_tag.get("href", "")
                        if "/talk/" not in href:
                            continue
                        talk_match = re.search(r'/talk/(\d{6,})', href)
                        if not talk_match:
                            continue

                        raw = a_tag.get_text(strip=True)
                        if not raw or len(raw) < 10 or len(raw) > 120:
                            continue

                        title_raw = re.sub(r'^\d{1,2}', '', raw)

                        comments = 0
                        cm = re.search(r'\((\d{1,5})\)', title_raw)
                        if cm:
                            comments = int(cm.group(1))

                        views = 0
                        vm = re.search(r'조회([\d,]+)', title_raw)
                        if vm:
                            views = int(vm.group(1).replace(",", ""))

                        recommends = 0
                        rm = re.search(r'추천(\d+)', title_raw)
                        if rm:
                            recommends = int(rm.group(1))

                        title = title_raw
                        for pat in [r'\(\d{1,5}\)', r'조회[\d,]+', r'\|?추천\d+']:
                            title = re.sub(pat, '', title)
                        title = title.strip()

                        if not title or len(title) < 3:
                            continue

                        score = comments * 3 + views // 100 + recommends * 2
                        results.append({
                            "keyword": title,
                            "source": "natepann",
                            "score": score,
                            "url": f"https://m.pann.nate.com/talk/{talk_match.group(1)}",
                        })
                except Exception:
                    continue

            # 중복 제거
            seen = set()
            deduped = []
            for r in results:
                key = r["keyword"][:20]
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
            results = deduped
            print(f"  [OK] 네이트판: {len(results)}개")
        except Exception as e:
            print(f"  [WARN] 네이트판 실패: {e}")
        return results

    @staticmethod
    def fetch_dcinside() -> list[dict]:
        """디시인사이드 실시간베스트 (모바일)"""
        results = []
        try:
            resp = requests.get(
                "https://m.dcinside.com/board/dcbest",
                headers={"User-Agent": _MOBILE_UA},
                timeout=10,
            )
            if resp.status_code != 200:
                print(f"  [WARN] 디시 실베 HTTP {resp.status_code}")
                return results

            soup = BeautifulSoup(resp.text, "html.parser")

            for a_tag in soup.select("a.lt"):
                raw = a_tag.get_text(strip=True)
                if not raw or len(raw) < 10:
                    continue

                href = a_tag.get("href", "")
                if "/board/dcbest/" not in href:
                    continue

                if any(kw in raw for kw in ["갤러리 이용 안내", "이용안내", "공지", "소개"]):
                    continue

                title = raw
                views = 0
                recommends = 0

                gal_match = re.search(r'(?:이미지)?\[.+?\]', title)
                if gal_match:
                    title = title[gal_match.end():]

                vm = re.search(r'조회\s*([\d,]+)', title)
                if vm:
                    views = int(vm.group(1).replace(",", ""))
                rm = re.search(r'추천\s*(\d+)', title)
                if rm:
                    recommends = int(rm.group(1))

                for pattern in [
                    r'ㅇㅇ(?:\([\d.]+\))?\s*\d{1,2}:\d{2}',
                    r'[a-zA-Z가-힣]+\d{1,2}:\d{2}',
                    r'\d{1,2}:\d{2}',
                    r'조회\s*[\d,]+',
                    r'추천\s*\d+',
                ]:
                    cut = re.search(pattern, title)
                    if cut:
                        title = title[:cut.start()]
                title = re.sub(r'ㅇㅇ$', '', title).strip()
                title = re.sub(r'\d{1,3}$', '', title).strip()
                title = re.sub(
                    r'\.(jpg|gif|png|jpeg)$', '', title, flags=re.IGNORECASE,
                ).strip()

                if not title or len(title) < 5:
                    continue

                score = recommends * 2 + views // 200
                results.append({
                    "keyword": title,
                    "source": "dcinside",
                    "score": score,
                    "url": (
                        href if href.startswith("http")
                        else f"https://m.dcinside.com{href}"
                    ),
                })

            # 중복 제거
            seen = set()
            deduped = []
            for r in results:
                key = r["keyword"][:20]
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
            results = deduped
            print(f"  [OK] 디시 실베: {len(results)}개")
        except Exception as e:
            print(f"  [WARN] 디시 실베 실패: {e}")
        return results

    @staticmethod
    def fetch_ruliweb() -> list[dict]:
        """루리웹 베스트 유머 — 봇차단 없음, 안정적

        셀렉터:
        - 제목: a.subject_link > strong
        - 댓글: span.num_reply (괄호 포함)
        - 조회: td.hit
        - 추천: td.recomd
        """
        results = []
        try:
            resp = requests.get(
                "https://bbs.ruliweb.com/best/humor",
                timeout=10,
                headers={
                    "User-Agent": _DESKTOP_UA,
                    "Accept-Language": "ko-KR,ko;q=0.9",
                },
            )
            if resp.status_code != 200:
                print(f"  [WARN] 루리웹 HTTP {resp.status_code}")
                return results

            soup = BeautifulSoup(resp.text, "html.parser")

            for tr in soup.select("tbody tr"):
                # 제목
                title_el = tr.select_one("a.subject_link strong")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title or len(title) < 5 or len(title) > 100:
                    continue

                # 링크
                link_el = tr.select_one("a.subject_link")
                href = link_el.get("href", "") if link_el else ""
                if not href.startswith("http"):
                    href = "https://bbs.ruliweb.com" + href

                # 댓글수: span.num_reply → "(126)"
                comments = 0
                cmt_el = tr.select_one("span.num_reply")
                if cmt_el:
                    cm = re.search(r'(\d+)', cmt_el.get_text())
                    if cm:
                        comments = int(cm.group(1))

                # 조회수
                views = 0
                hit_el = tr.select_one("td.hit")
                if hit_el:
                    try:
                        views = int(hit_el.get_text(strip=True).replace(",", ""))
                    except (ValueError, TypeError):
                        pass

                # 추천수
                recommends = 0
                rec_el = tr.select_one("td.recomd")
                if rec_el:
                    try:
                        recommends = int(rec_el.get_text(strip=True).replace(",", ""))
                    except (ValueError, TypeError):
                        pass

                score = comments * 3 + views // 100 + recommends * 2
                results.append({
                    "keyword": title,
                    "source": "ruliweb",
                    "score": score,
                    "url": href,
                })

            # 중복 제거
            seen = set()
            deduped = []
            for r in results:
                key = r["keyword"][:20]
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
            results = deduped
            print(f"  [OK] 루리웹: {len(results)}개")
        except Exception as e:
            print(f"  [WARN] 루리웹 실패: {e}")
        return results

    @staticmethod
    def fetch_instiz() -> list[dict]:
        """인스티즈 인기글"""
        results = []
        try:
            resp = requests.get(
                "https://www.instiz.net/pt?page=1",
                headers={"User-Agent": _DESKTOP_UA},
                timeout=10,
            )
            if resp.status_code != 200:
                print(f"  [WARN] 인스티즈 HTTP {resp.status_code}")
                return results

            soup = BeautifulSoup(resp.text, "html.parser")

            for subj in soup.select(".listsubject"):
                a_tag = subj.select_one("a")
                if not a_tag:
                    continue

                href = a_tag.get("href", "")
                if not href.startswith("http"):
                    href = "https://www.instiz.net" + href

                comments = 0
                cmt_span = subj.select_one("span.cmt3, span.cmt2, span.cmt1")
                if cmt_span:
                    try:
                        comments = int(cmt_span.get_text(strip=True))
                    except (ValueError, TypeError):
                        pass

                raw_text = a_tag.get_text(strip=True)
                if not raw_text or len(raw_text) < 5:
                    continue

                if cmt_span:
                    cmt_text = cmt_span.get_text(strip=True)
                    title = raw_text.replace(cmt_text, '').strip()
                    if comments > 0:
                        title = re.sub(rf'\s*{comments}\s*$', '', title).strip()
                else:
                    cm = re.search(r'(\d{2,5})$', raw_text)
                    if cm:
                        comments = int(cm.group(1))
                        title = raw_text[:cm.start()].strip()
                    else:
                        title = raw_text

                # 잔재 정리
                title = re.sub(r'\d{1,2}:\d{2}[lL]?조회.*$', '', title).strip()
                title = re.sub(r'\d{1,2}:\d{2}[lL]?$', '', title).strip()
                title = re.sub(r'[lL]조회\s*\d*$', '', title).strip()
                title = re.sub(r'\.jpg\s*\d*$', '', title).strip()
                title = re.sub(r'\.png\s*\d*$', '', title).strip()

                if not title or len(title) < 3:
                    continue

                score = comments * 3
                results.append({
                    "keyword": title,
                    "source": "instiz",
                    "score": score,
                    "url": href,
                })

            print(f"  [OK] 인스티즈: {len(results)}개")
        except Exception as e:
            print(f"  [WARN] 인스티즈 실패: {e}")
        return results


# ============================================================
# TrendFilter: 필터링 + 점수 + 중복제거
# ============================================================

class TrendFilter:
    """수집된 트렌드를 필터링·점수화·중복제거"""

    @staticmethod
    def apply_blacklist(trends: list[dict]) -> list[dict]:
        """블랙리스트 + 영어 과다 + 짧은 키워드 제거"""
        filtered = []
        blocked = 0
        for t in trends:
            kw = t["keyword"]
            # 블랙리스트
            if any(bw in kw for bw in BLACKLIST):
                blocked += 1
                continue
            # 영어 비율 50% 이상이면 제거
            eng_chars = sum(1 for c in kw if c.isascii() and c.isalpha())
            if len(kw) > 3 and eng_chars / len(kw) > 0.5:
                blocked += 1
                continue
            # 너무 짧은 키워드 (2글자 이하)
            clean_kw = re.sub(r'[^가-힣a-zA-Z0-9]', '', kw)
            if len(clean_kw) < 3:
                blocked += 1
                continue
            filtered.append(t)
        if blocked:
            print(f"  [FILTER] 블랙리스트: {blocked}개 제거")
        return filtered

    @staticmethod
    def apply_junk_filter(trends: list[dict]) -> list[dict]:
        """커뮤니티 잡글 제거 (질문/공지/짧은 제목)"""
        pre = len(trends)
        filtered = [
            t for t in trends
            if not (
                t.get("source", "") in ("natepann", "dcinside", "ruliweb", "instiz")
                and (
                    len(t["keyword"]) < 10
                    or any(jp in t["keyword"] for jp in JUNK_PATTERNS)
                )
            )
        ]
        removed = pre - len(filtered)
        if removed:
            print(f"  [FILTER] 잡글: {removed}개 제거")
        return filtered

    @staticmethod
    def apply_boost_scoring(trends: list[dict]) -> list[dict]:
        """바이럴 키워드 차등 부스트 + Google Trends 출처 보너스"""
        for t in trends:
            kw = t["keyword"]
            # Tier1: 조회수 폭발 키워드 → +20,000점
            t1 = sum(1 for bk in BOOST_TIER1 if bk in kw)
            if t1:
                t["score"] += t1 * 20000
            # Tier2: 관심 유발 키워드 → +10,000점
            t2 = sum(1 for bk in BOOST_TIER2 if bk in kw)
            if t2:
                t["score"] += t2 * 10000
            # 기존 범용 부스트 → +20,000점
            t3 = sum(1 for bk in BOOST_KEYWORDS if bk in kw)
            if t3:
                t["score"] += t3 * 20000
            # Google Trends 출처 보너스 → +30,000점
            if t.get("source") == "google_trends":
                t["score"] += 30000
        return trends

    @staticmethod
    def apply_category_boost(trends: list[dict]) -> list[dict]:
        """숏츠 폭발력 카테고리 부스트 +35000~+50000"""
        for t in trends:
            kw = t["keyword"]
            best_boost = 0
            best_cat = ""
            for cat_name, cat_info in VIRAL_CATEGORIES.items():
                match_count = sum(1 for ck in cat_info["keywords"] if ck in kw)
                if match_count > 0 and cat_info["boost"] > best_boost:
                    best_boost = cat_info["boost"]
                    best_cat = cat_name
            if best_boost:
                t["score"] += best_boost
                t["_viral_category"] = best_cat
        return trends

    @staticmethod
    def apply_boring_penalty(trends: list[dict]) -> list[dict]:
        """숏츠 부적합 감점 — 일상잡담 -10000~-30000"""
        for t in trends:
            kw = t["keyword"]
            for pat, penalty, _label in BORING_PENALTIES:
                if re.search(pat, kw):
                    t["score"] += penalty
                    break
        return trends

    @staticmethod
    def deduplicate_session(trends: list[dict]) -> list[dict]:
        """세션 내 중복 제거 (첫 20자 기준) + 점수 합산"""
        merged: dict[str, dict] = {}
        for t in trends:
            key = t["keyword"][:20]
            if key in merged:
                merged[key]["score"] += t["score"]
                src = t.get("source", "")
                if src and src not in merged[key].get("_sources", []):
                    merged[key].setdefault("_sources", []).append(src)
            else:
                merged[key] = dict(t)
                merged[key]["_sources"] = [t.get("source", "")]
        result = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        deduped = len(trends) - len(result)
        if deduped:
            print(f"  [DEDUP] 세션 내 중복: {deduped}개 합산")
        return result

    @staticmethod
    def deduplicate_with_history(trends: list[dict]) -> list[dict]:
        """topic_history.json 대조 — 최근 200개와 첫 20자 비교"""
        past_titles: list[str] = []
        try:
            if HISTORY_FILE.exists():
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    past_titles = json.load(f)
        except Exception:
            pass

        if not past_titles:
            return trends

        past_keys = set(t[:20] for t in past_titles)
        filtered = []
        skipped = 0
        for t in trends:
            key = t["keyword"][:20]
            if key in past_keys:
                skipped += 1
                continue
            filtered.append(t)
        if skipped:
            print(f"  [DEDUP] 히스토리 중복: {skipped}개 스킵")
        return filtered

    @staticmethod
    def deduplicate_with_topics(trends: list[dict]) -> list[dict]:
        """기존 topics.txt에 이미 있는 주제 제거"""
        existing: set[str] = set()
        try:
            if TOPICS_FILE.exists():
                with open(TOPICS_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            existing.add(line[:20])
        except Exception:
            pass

        if not existing:
            return trends

        filtered = []
        skipped = 0
        for t in trends:
            key = t["keyword"][:20]
            if key in existing:
                skipped += 1
                continue
            filtered.append(t)
        if skipped:
            print(f"  [DEDUP] topics.txt 중복: {skipped}개 스킵")
        return filtered


# ============================================================
# GeminiConverter: AI 평가 + 숏츠 주제문 변환
# ============================================================

class GeminiConverter:
    """Gemini Flash로 바이럴 평가 + 키워드→숏츠 주제문 변환"""

    @staticmethod
    def _get_model():
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            return None
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            return genai.GenerativeModel("gemini-2.0-flash")
        except Exception as e:
            print(f"  [WARN] Gemini 초기화 실패: {e}")
            return None

    @classmethod
    def evaluate_viral_potential(cls, trends: list[dict]) -> list[dict]:
        """상위 15개 AI 평가 — 70점+ 만 통과"""
        if not trends:
            return trends

        model = cls._get_model()
        if model is None:
            print("  [WARN] GOOGLE_API_KEY 없음 -- Gemini 평가 스킵")
            return trends

        candidates = trends[:15]
        titles_text = "\n".join(
            f"{i+1}. [{c.get('source', '?')}] {c['keyword']}"
            for i, c in enumerate(candidates)
        )

        # v7.0: 조회수 3가지 핵심 기준으로 평가
        prompt = f"""숏츠 조회수 기준 3가지로만 평가해줘:

1. 첫 2초 안에 궁금증 유발 가능한가? (0~33점)
2. 끝까지 안 보면 손해인 느낌인가? (0~33점)
3. 댓글/공유 욕구가 생기는가? (0~34점)

[즉시 탈락 = 0점]
- 정치/선거/종교/가십/단순 뉴스

대상:
{titles_text}

출력: 반드시 JSON만 출력. 설명/백틱 없이.
{{"scores": [85, 72, 45, ...]}}

scores 배열의 길이는 반드시 {len(candidates)}개여야 한다."""

        try:
            import google.generativeai as genai
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=500,
                    response_mime_type="application/json",
                ),
            )
            if response.text:
                data = json.loads(response.text)
                scores = data.get("scores", [])
                if isinstance(scores, list) and len(scores) == len(candidates):
                    passed = []
                    rejected = []
                    # 게임/애니 감점 키워드
                    _GAME_ANIME_KW = [
                        "게임", "롤", "발로란트", "마크", "원신",
                        "애니", "원피스", "귀멸", "나루토", "주술회전",
                        "진격", "아르세우스", "포켓몬", "젤다", "닌텐도",
                        "스팀", "플스", "엑박", "LOL", "배그",
                    ]
                    # 일반인 공감 가점 키워드
                    _EMPATHY_KW = [
                        "공감", "직장", "회사", "월급", "자취",
                        "알바", "출근", "퇴근", "현실", "특징",
                        "유형", "요즘", "사회초년생", "20대", "30대",
                        "한국인", "모르면 손해", "꿀팁",
                    ]

                    for item, gemini_score in zip(candidates, scores):
                        s = (
                            int(gemini_score)
                            if isinstance(gemini_score, (int, float))
                            else 50
                        )
                        # 게임/애니 감점 (-30)
                        kw = item["keyword"]
                        if any(gk in kw for gk in _GAME_ANIME_KW):
                            s = max(s - 30, 0)
                        # 일반인 공감 가점 (+20)
                        if any(ek in kw for ek in _EMPATHY_KW):
                            s = min(s + 20, 100)

                        item["_gemini_score"] = s
                        if s >= 70:
                            item["score"] += s * 100
                            passed.append(item)
                        else:
                            rejected.append(item)
                    print(
                        f"  [AI] Gemini 평가: {len(passed)}개 통과"
                        f" / {len(rejected)}개 탈락"
                    )
                    for p in passed[:5]:
                        print(f"    [PASS {p['_gemini_score']}] {p['keyword'][:40]}")
                    for r in rejected[:3]:
                        print(f"    [FAIL {r['_gemini_score']}] {r['keyword'][:40]}")
                    rest = trends[15:]
                    return passed + rest
                else:
                    print(
                        f"  [WARN] Gemini 응답 길이 불일치"
                        f" ({len(scores)} vs {len(candidates)}) -- 스킵"
                    )
        except Exception as e:
            print(f"  [WARN] Gemini 평가 실패: {e} -- 기존 점수 사용")
        return trends

    @classmethod
    def convert_to_shorts_topics(cls, keywords: list[str]) -> list[str]:
        """키워드 목록 → 숏츠 주제문 변환 (한 번의 API 호출)"""
        if not keywords:
            return keywords

        model = cls._get_model()
        if model is None:
            print("  [WARN] GOOGLE_API_KEY 없음 -- 주제문 변환 스킵")
            return keywords

        kw_text = "\n".join(f"{i+1}. {kw}" for i, kw in enumerate(keywords))

        prompt = f"""너는 유튜브 숏츠 기획 전문가다.
아래 트렌드 키워드/제목을 "유튜브 숏츠 영상 제목"으로 변환해.

변환 규칙:
1. 한국어 구어체 (반말 OK, 격식체 금지)
2. 15~30자 사이
3. 호기심/궁금증 유발 (질문형, 반전 암시, 충격 암시)
4. 클릭을 부르는 숏츠 제목 스타일
5. 이모지 금지
6. "알아보겠습니다", "살펴보겠습니다" 같은 AI투 금지

키워드:
{kw_text}

반드시 아래 JSON 형식으로만 답해:
{{"topics": ["변환된 제목1", "변환된 제목2", ...]}}

topics 배열 길이는 반드시 {len(keywords)}개. JSON만 출력."""

        try:
            import google.generativeai as genai
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=1000,
                    response_mime_type="application/json",
                ),
            )
            if response.text:
                data = json.loads(response.text)
                topics = data.get("topics", [])
                if isinstance(topics, list) and len(topics) == len(keywords):
                    print(f"  [AI] 주제문 변환 완료: {len(topics)}개")
                    for i, (orig, conv) in enumerate(zip(keywords, topics)):
                        print(f"    {i+1}. {orig[:25]} -> {conv}")
                    return topics
                else:
                    print(
                        f"  [WARN] 변환 응답 길이 불일치"
                        f" ({len(topics)} vs {len(keywords)}) -- 원본 사용"
                    )
        except Exception as e:
            print(f"  [WARN] 주제문 변환 실패: {e} -- 원본 키워드 사용")
        return keywords


# ============================================================
# 저장
# ============================================================

def save_topics(topics: list[str]) -> None:
    """topics.txt에 어펜드 (주석 헤더 유지)"""
    # 기존 파일이 없으면 헤더 포함 생성
    if not TOPICS_FILE.exists():
        with open(TOPICS_FILE, "w", encoding="utf-8") as f:
            f.write("# ============================================================\n")
            f.write("# YouShorts v6.0 - 주제 큐 파일\n")
            f.write("# ============================================================\n")
            f.write("# 한 줄에 하나의 주제를 작성하세요.\n")
            f.write("# mass_produce.py가 위에서부터 순차적으로 소화합니다.\n")
            f.write("# 처리된 주제는 자동으로 삭제됩니다.\n")
            f.write("# '#'으로 시작하는 줄은 주석입니다.\n")
            f.write("# ============================================================\n")

    with open(TOPICS_FILE, "a", encoding="utf-8") as f:
        for topic in topics:
            f.write(topic + "\n")

    print(f"\n  [SAVE] topics.txt에 {len(topics)}개 주제 추가 완료")
    print(f"  [PATH] {TOPICS_FILE}")


def save_topic_history(keywords: list[str]) -> None:
    """topic_history.json 업데이트 (최대 200개 유지)"""
    past: list[str] = []
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                past = json.load(f)
    except Exception:
        pass

    past = keywords + past
    past = past[:200]

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(past, f, ensure_ascii=False, indent=2)

    print(f"  [SAVE] topic_history.json 업데이트 ({len(past)}개 보관)")


# ============================================================
# 메인
# ============================================================

def collect_trends(source_filter: str | None = None) -> list[dict]:
    """소스별 트렌드 수집 — 각 소스 실패 허용"""
    print("\n" + "=" * 60)
    print("STEP 1: 트렌드 수집")
    print("=" * 60)

    # v6.2: 네이트판/디시/인스티즈 제외 — 낚시성·커뮤니티 잡글 과다
    source_map = {
        "google": TrendSource.fetch_google_trends_rss,
        "naver": TrendSource.fetch_naver_realtime,
        "youtube": TrendSource.fetch_youtube_trending,
        # "natepann": TrendSource.fetch_natepann,    # 제외
        # "dcinside": TrendSource.fetch_dcinside,    # 제외
        "ruliweb": TrendSource.fetch_ruliweb,
        # "instiz": TrendSource.fetch_instiz,        # 제외
    }

    all_trends: list[dict] = []

    if source_filter:
        key = source_filter.lower()
        if key in source_map:
            all_trends.extend(source_map[key]())
        else:
            print(f"  [ERROR] 알 수 없는 소스: {key}")
            print(f"  [INFO] 사용 가능: {', '.join(source_map.keys())}")
            return []
    else:
        for name, fetcher in source_map.items():
            try:
                all_trends.extend(fetcher())
            except Exception as e:
                print(f"  [WARN] {name} 수집 실패: {e}")

    print(f"\n  총 {len(all_trends)}개 수집 완료 (필터 전)")
    return all_trends


def filter_and_score(trends: list[dict]) -> list[dict]:
    """필터 → 부스트 → 감점 → 중복제거 → 정렬"""
    print("\n" + "=" * 60)
    print("STEP 2: 필터링 + 점수화")
    print("=" * 60)

    f = TrendFilter
    trends = f.apply_blacklist(trends)
    trends = f.apply_junk_filter(trends)
    trends = f.apply_boost_scoring(trends)
    trends = f.apply_category_boost(trends)
    trends = f.apply_boring_penalty(trends)
    trends = f.deduplicate_session(trends)
    trends = f.deduplicate_with_history(trends)
    trends = f.deduplicate_with_topics(trends)

    # 최종 정렬
    trends.sort(key=lambda x: x.get("score", 0), reverse=True)

    print(f"\n  필터 후 {len(trends)}개 트렌드")
    for i, t in enumerate(trends[:10]):
        cat = t.get("_viral_category", "")
        cat_str = f" [{cat}]" if cat else ""
        sources = ", ".join(t.get("_sources", [t.get("source", "?")]))
        print(f"  {i+1}. [{t['score']:,}점]{cat_str} {t['keyword'][:45]} ({sources})")

    return trends


def main():
    parser = argparse.ArgumentParser(
        description="트렌드 크롤링 -> topics.txt 자동 채우기",
    )
    parser.add_argument(
        "--count", type=int, default=10,
        help="수집할 주제 개수 (기본: 10)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="출력만, topics.txt 저장 안 함",
    )
    parser.add_argument(
        "--no-gemini", action="store_true",
        help="Gemini AI 평가/변환 스킵",
    )
    parser.add_argument(
        "--source", type=str, default=None,
        help="특정 소스만 (google/naver/youtube/natepann/dcinside/ruliweb/instiz)",
    )
    parser.add_argument(
        "--auto", action="store_true",
        help="원클릭: 크롤링 → topics.txt → mass_produce.py 자동 실행",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("crawl_trends.py -- 트렌드 -> topics.txt")
    print("=" * 60)
    print(f"  목표: {args.count}개 | dry-run: {args.dry_run}"
          f" | gemini: {not args.no_gemini}")
    if args.source:
        print(f"  소스 필터: {args.source}")

    # 1) 수집
    trends = collect_trends(args.source)
    if not trends:
        print("\n  [ERROR] 수집된 트렌드 0개 -- 종료")
        sys.exit(1)

    # 2) 필터 + 점수
    trends = filter_and_score(trends)
    if not trends:
        print("\n  [ERROR] 필터 후 트렌드 0개 -- 종료")
        sys.exit(1)

    # 3) Gemini 평가 (선택)
    if not args.no_gemini:
        print("\n" + "=" * 60)
        print("STEP 3: Gemini AI 평가")
        print("=" * 60)
        trends = GeminiConverter.evaluate_viral_potential(trends)
        trends.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 4) TOP 3 출력 후 상위 N개 선택 (최소 3개 보장)
    top3 = trends[:3]
    print("\n" + "=" * 60)
    print("TOP 3 주제 (점수순)")
    print("=" * 60)
    for i, t in enumerate(top3):
        cat = t.get("_viral_category", "")
        cat_str = f" [{cat}]" if cat else ""
        print(f"  🏆 {i+1}위. [{t['score']:,}점]{cat_str} {t['keyword'][:50]}")

    # 최소 3개 + 요청 개수만큼 선택
    select_count = max(3, args.count)
    selected = trends[:select_count]
    keywords = [t["keyword"] for t in selected]

    # 5) Gemini 주제문 변환 (선택)
    if not args.no_gemini:
        print("\n" + "=" * 60)
        print("STEP 4: 숏츠 주제문 변환")
        print("=" * 60)
        topics = GeminiConverter.convert_to_shorts_topics(keywords)
    else:
        topics = keywords

    # 6) 최종 결과
    print("\n" + "=" * 60)
    print(f"FINAL: 최종 {len(topics)}개 주제")
    print("=" * 60)
    for i, topic in enumerate(topics):
        print(f"  {i+1}. {topic}")

    # 7) 저장
    if args.dry_run:
        print("\n  [DRY-RUN] 저장 스킵")
    else:
        save_topics(topics)
        save_topic_history(keywords)

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)

    # 8) --auto: 크롤링 후 바로 mass_produce.py 실행
    if args.auto and not args.dry_run:
        import subprocess

        print("\n" + "=" * 60)
        print("AUTO: mass_produce.py 자동 실행")
        print("=" * 60)

        cmd = [
            sys.executable, str(BASE_DIR / "mass_produce.py"),
            "--count", str(args.count),
            "--topics-file", str(TOPICS_FILE),
            "--delay", "120",
        ]
        print(f"  CMD: {' '.join(cmd)}")
        subprocess.run(cmd)


if __name__ == "__main__":
    main()
