#!/usr/bin/env python3
"""실시간 트렌드 크롤링 → 숏츠 주제 선정"""
import requests, re, json, io, sys
import xml.etree.ElementTree as ET

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("beautifulsoup4 필요: pip install beautifulsoup4")
    sys.exit(1)

UA_M = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
UA_D = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

all_results = []

# ── 1. Google Trends KR ──
print("=" * 60)
print("  [1] Google Trends KR (실시간 급상승)")
print("=" * 60)
try:
    resp = requests.get(
        "https://trends.google.co.kr/trending/rss?geo=KR",
        timeout=10, headers={"User-Agent": "Mozilla/5.0"},
    )
    if resp.status_code == 200:
        root = ET.fromstring(resp.text)
        for i, item in enumerate(root.findall(".//item")[:15]):
            t = item.find("title")
            if t is not None and t.text:
                print(f"  #{i+1:2d}  {t.text}")
                all_results.append({"title": t.text, "source": "구글트렌드", "comments": 0, "score": 100 - i * 5})
except Exception as e:
    print(f"  FAIL: {e}")

# ── 2. 네이트판 ──
print()
print("=" * 60)
print("  [2] 네이트판 명예의전당 + 오늘의판")
print("=" * 60)
try:
    seen = set()
    for url in ["https://m.pann.nate.com/talk/ranking", "https://m.pann.nate.com/talk/today"]:
        resp = requests.get(url, headers={"User-Agent": UA_M}, timeout=10)
        if resp.status_code != 200:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("a"):
            href = a.get("href", "")
            if "/talk/" not in href:
                continue
            m = re.search(r"/talk/(\d{6,})", href)
            if not m:
                continue
            raw = a.get_text(strip=True)
            if not raw or len(raw) < 10:
                continue
            title = re.sub(r"^\d{1,2}", "", raw)
            cmt = 0
            cm = re.search(r"\((\d{1,5})\)", title)
            if cm:
                cmt = int(cm.group(1))
            for p in [r"\(\d{1,5}\)", r"조회[\d,]+", r"\|?추천\d+"]:
                title = re.sub(p, "", title)
            title = title.strip()
            if not title or len(title) < 5 or title[:15] in seen:
                continue
            seen.add(title[:15])
            all_results.append({"title": title, "source": "네이트판", "comments": cmt, "score": cmt * 3})
    np_items = [x for x in all_results if x["source"] == "네이트판"]
    np_items.sort(key=lambda x: x["comments"], reverse=True)
    for i, x in enumerate(np_items[:10]):
        print(f"  #{i+1:2d}  {x['title'][:55]}  (댓글:{x['comments']})")
except Exception as e:
    print(f"  FAIL: {e}")

# ── 3. 디시 실베 ──
print()
print("=" * 60)
print("  [3] 디시인사이드 실시간베스트")
print("=" * 60)
try:
    resp = requests.get("https://m.dcinside.com/board/dcbest", headers={"User-Agent": UA_M}, timeout=10)
    if resp.status_code == 200:
        soup = BeautifulSoup(resp.text, "html.parser")
        cnt = 0
        seen_dc = set()
        for a in soup.select("a.lt"):
            raw = a.get_text(strip=True)
            if not raw or len(raw) < 10:
                continue
            href = a.get("href", "")
            if "/board/dcbest/" not in href:
                continue
            title = raw
            gal = re.search(r"(?:이미지)?\[.+?\]", title)
            if gal:
                title = title[gal.end():]
            for p in [r"ㅇㅇ(?:\([\d.]+\))?\d{1,2}:\d{2}", r"조회\s*[\d,]+", r"추천\s*\d+"]:
                c = re.search(p, title)
                if c:
                    title = title[:c.start()]
            title = title.strip()
            if not title or len(title) < 5 or title[:15] in seen_dc:
                continue
            seen_dc.add(title[:15])
            if cnt < 10:
                print(f"  #{cnt+1:2d}  {title[:55]}")
                all_results.append({"title": title, "source": "디시실베", "comments": 0, "score": 80 - cnt * 5})
                cnt += 1
except Exception as e:
    print(f"  FAIL: {e}")

# ── 4. 에펨코리아 ──
print()
print("=" * 60)
print("  [4] 에펨코리아 베스트")
print("=" * 60)
try:
    resp = requests.get("https://m.fmkorea.com/best", headers={"User-Agent": UA_M}, timeout=10)
    if resp.status_code == 200:
        soup = BeautifulSoup(resp.text, "html.parser")
        cnt = 0
        seen_fm = set()
        for a in soup.select("a"):
            txt = a.get_text(strip=True)
            if not txt or len(txt) < 8 or len(txt) > 80:
                continue
            cmt = 0
            cm = re.search(r"\[(\d{1,5})\]$", txt)
            if cm:
                cmt = int(cm.group(1))
                t = txt[:cm.start()].strip()
            else:
                t = txt
            if not t or len(t) < 8 or t[:15] in seen_fm:
                continue
            seen_fm.add(t[:15])
            if cnt < 10:
                print(f"  #{cnt+1:2d}  {t[:55]}  (댓글:{cmt})")
                all_results.append({"title": t, "source": "에펨코리아", "comments": cmt, "score": cmt * 3})
                cnt += 1
except Exception as e:
    print(f"  FAIL: {e}")

# ── 블랙리스트 필터 ──
BLACKLIST = [
    "국회", "대통령", "탄핵", "여당", "야당", "민주당", "국민의힘", "총선", "선거",
    "이재명", "윤석열", "한동훈", "검찰", "경찰", "수사", "재판", "판결", "구속",
    "사망", "사고", "화재", "지진", "태풍", "폭발", "추모", "실종", "참사",
    "금리", "환율", "증시", "코스피", "주가", "비트코인", "코인",
    "공지", "이벤트", "광고", "모집", "텔레그램", "후방주의", "19금",
    "정당", "의원", "청와대", "외교", "북한",
]

BOOST = ["레전드", "실화", "대박", "미쳤", "소름", "반전", "후기", "밈", "터짐", "난리",
         "꿀팁", "ㅋㅋ", "비교", "랭킹", "TOP", "챌린지"]

filtered = []
for item in all_results:
    title = item["title"]
    if any(bw in title for bw in BLACKLIST):
        continue
    # 부스트 점수
    boost = sum(5 for bw in BOOST if bw in title)
    item["score"] += boost
    filtered.append(item)

# 점수 정렬
filtered.sort(key=lambda x: x["score"], reverse=True)

# ── 최종 TOP 15 ──
print()
print("=" * 60)
print("  [최종] 숏츠 주제 추천 TOP 15 (블랙리스트 필터 + 바이럴 점수)")
print("=" * 60)
for i, item in enumerate(filtered[:15]):
    src = item["source"]
    score = item["score"]
    cmt = item["comments"]
    emoji = {"네이트판": "🔥", "디시실베": "⚡", "에펨코리아": "🌐", "구글트렌드": "📈"}.get(src, "📌")
    metric = f"댓글:{cmt}" if cmt else f"점수:{score}"
    print(f"  {emoji} #{i+1:2d}  [{src:6s}]  {item['title'][:50]}  ({metric})")
