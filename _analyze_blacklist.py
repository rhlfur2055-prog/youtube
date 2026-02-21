import sys, io, os, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv(".env")
except: pass

import requests
from bs4 import BeautifulSoup

MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"

TOPIC_BLACKLIST = ['국회', '대통령', '탄핵', '여당', '야당', '민주당', '국민의힘', '총선', '선거', '후보', '정당', '의원', '청와대', '정부', '외교', '북한', '한미', '정상회담', '국방', '안보', '친노', '친문', '친윤', '좌파', '우파', '진보', '보수', '이재명', '윤석열', '한동훈', '이낙연', '손학규', '핵협상', '속보', '긴급', '금리', '환율', '증시', '코스피', '코스닥', '주가', 'GDP', '물가', '인플레이션', '기준금리', '한은', '국채', '사망', '사고', '화재', '지진', '태풍', '폭발', '추모', '유족', '희생', '참사', '실종', '붕괴', '재판', '판결', '구속', '기소', '검찰', '경찰', '수사', '피의자', '혈의', '체포', '송치', '국무회의', '예산', '법안', '조례', '감사원', '규제', '공지', '통합', '체험단', '모집', '이벤트', '광고', '제휴', '스포', '질문드립니다', '질문있습니다', '문의', '안내', '구인', '구직', '팝니다', '삽니다', '한줄평', '설문', '밥상', '명절', '시어머니', '며느리', '택시', '심쿡', '로맨스', '설날', '새해', '추석', '한가위', '크리스마스', '성탄절', '텔레그램', '단톡방', '카톡방', '오픈채팅', '비트코인', '가상화폐', '코인', 'NFT', '투자', '수익률', '원금보장', '무료나눔', '선착순', '할인코드', '암 치료', '특효약', '민간요법', '자가진단', '후방주의', '19금', '은꼴']

BOOST_KEYWORDS = ['레전드', '실화', '대박', '미쳤', '소름', '논란', '반전', '후기', '먹방', '게임', '리뷰', '밈', '챌린지', '핫', '터짐', '난리', '비교', '랭킹', '순위', 'VS', 'TOP', '꽀팁', '해봄', '써봄', '사봄', '가봄', '월급', '퇴사', '야근', '자취', '월세', '전세', '사회초년생', '직장상사', '꼼대', 'MZ', '워라밸', '연봉', '이직', '알바', '면접', '취준', '썬', '소개팅', '결혼', '축의금', '청첩장', '연애', '재테크', '고백', '적금', '청약']

all_titles = []
# Nate Pann
try:
    resp = requests.get('https://m.pann.nate.com/talk/ranking', headers={'User-Agent': MOBILE_UA}, timeout=10)
    soup = BeautifulSoup(resp.text, 'html.parser')
    for a_tag in soup.select('a'):
        href = a_tag.get('href', '')
        if '/talk/' not in href: continue
        if not re.search(r'/talk/(\d{6,})', href): continue
        raw = a_tag.get_text(strip=True)
        if not raw or len(raw) < 10: continue
        title = re.sub(r'^\d{1,2}', '', raw)
        for pat in [r'\(\d{1,5}\)', r'조회[\d,]+', r'\|?추천\d+']:
            title = re.sub(pat, '', title).strip()
        if title and len(title) > 3:
            all_titles.append(('네이트판', title[:60]))
except Exception as e:
    print(f'[Nate error] {e}')

# DC Inside
try:
    resp = requests.get('https://m.dcinside.com/board/dcbest', headers={'User-Agent': MOBILE_UA}, timeout=10)
    soup = BeautifulSoup(resp.text, 'html.parser')
    for a_tag in soup.select('a.lt'):
        raw = a_tag.get_text(strip=True)
        if not raw or len(raw) < 10: continue
        href = a_tag.get('href', '')
        if '/board/dcbest/' not in href: continue
        title = raw
        gal_match = re.search(r'(?:이미지)?\[.+?\]', title)
        if gal_match: title = title[gal_match.end():]
        for pattern in [r'ㅇㅇ(?:\([\d.]+\))?\d{1,2}:\d{2}', r'조회\s*[\d,]+', r'추천\s*\d+']:
            cut = re.search(pattern, title)
            if cut: title = title[:cut.start()]
        title = title.strip()
        if title and len(title) > 5:
            all_titles.append(('디시실베', title[:60]))
except Exception as e:
    print(f'[DC error] {e}')

# FM Korea
try:
    resp = requests.get('https://m.fmkorea.com/best', headers={'User-Agent': MOBILE_UA}, timeout=10)
    soup = BeautifulSoup(resp.text, 'html.parser')
    seen_fm = set()
    for a_tag in soup.select('a'):
        txt = a_tag.get_text(strip=True)
        if not txt or len(txt) < 8 or len(txt) > 80: continue
        cm = re.search(r'\[(\d{1,5})\]$', txt)
        title = txt[:cm.start()].strip() if cm else txt
        key = title[:20]
        if key in seen_fm or len(title) < 8: continue
        seen_fm.add(key)
        all_titles.append(('에펨코리아', title[:60]))
except Exception as e:
    print(f'[FM error] {e}')

# Deduplicate
seen = set()
unique = []
for src, title in all_titles:
    key = title[:20]
    if key not in seen:
        seen.add(key)
        unique.append((src, title))

total = len(unique)
print(f'총 수집: {total}개')
print()

blocked = []
passed = []
for src, title in unique:
    hit = None
    for kw in TOPIC_BLACKLIST:
        if kw in title:
            hit = kw
            break
    if hit:
        blocked.append((src, title, hit))
    else:
        passed.append((src, title))

print('=' * 70)
print(f'블랙리스트 차단: {len(blocked)}개 / {total}개 ({len(blocked)/max(1,total)*100:.0f}%)')
print('=' * 70)
for src, title, kw in blocked[:15]:
    print(f'  [차단] [{src}] {title[:50]}  (키워드: {kw})')

print()
print('=' * 70)
print(f'통과: {len(passed)}개 / {total}개 ({len(passed)/max(1,total)*100:.0f}%)')
print('=' * 70)

scored = []
for src, title in passed:
    boost = sum(1 for kw in BOOST_KEYWORDS if kw in title)
    scored.append((src, title, boost))
scored.sort(key=lambda x: x[2], reverse=True)

boosted = [x for x in scored if x[2] > 0]
noboosted = [x for x in scored if x[2] == 0]

print(f'부스트 키워드 매칭: {len(boosted)}개')
for src, title, boost in boosted[:10]:
    matched = [kw for kw in BOOST_KEYWORDS if kw in title]
    print(f'  [+{boost}] [{src}] {title[:50]}  (매칭: {chr(44).join(matched)})')

print()
print(f'부스트 없음 (일반 주제): {len(noboosted)}개')
for src, title, boost in noboosted[:10]:
    print(f'  [  0] [{src}] {title[:50]}')

print()
print('=' * 70)
print('진단 요약')
print('=' * 70)
print(f'  총 수집: {total}개')
print(f'  블랙리스트 차단: {len(blocked)}개 ({len(blocked)/max(1,total)*100:.0f}%)')
print(f'  통과: {len(passed)}개')
print(f'  부스트 매칭: {len(boosted)}개 ({len(boosted)/max(1,len(passed))*100:.0f}%)')
print(f'  무부스트: {len(noboosted)}개')

if len(boosted) < 3:
    print(f'  [경고] 부스트 매칭 주제가 3개 미만! 바이럴 소재 부족')
if len(passed) < 5:
    print(f'  [경고] 통과 주제가 5개 미만! 블랙리스트 과도 or 크롤링 부족')
