import requests
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8',
}

# 1. Instiz - find link patterns
print("="*60)
print("INSTIZ - HTML analysis")
print("="*60)
r = requests.get('https://www.instiz.net/pt', headers=headers, timeout=15)
r.encoding = 'utf-8'
# Find all href patterns with numbers
all_hrefs = re.findall(r'href="([^"]*)"', r.text)
numbered_hrefs = [h for h in all_hrefs if re.search(r'\d{4,}', h)]
unique_patterns = list(set(numbered_hrefs))[:20]
for h in sorted(unique_patterns):
    print(f'  {h}')

# Also look for common list item patterns
rows = re.findall(r'(.{0,300}instiz\.net/pt.{0,300})', r.text)
if rows:
    for i, row in enumerate(rows[:3]):
        print(f'\n  --- INSTIZ ROW {i} ---')
        print(f'  {row[:200]}')

# 2. Theqoo - find link patterns  
print("\n" + "="*60)
print("THEQOO - HTML analysis")
print("="*60)
r = requests.get('https://theqoo.net/hot', headers=headers, timeout=15)
r.encoding = 'utf-8'
all_hrefs = re.findall(r'href="([^"]*)"', r.text)
numbered_hrefs = [h for h in all_hrefs if re.search(r'\d{5,}', h)]
unique_patterns = list(set(numbered_hrefs))[:20]
for h in sorted(unique_patterns):
    print(f'  {h}')

# 3. FMKorea - fetch individual article body structure
print("\n" + "="*60)
print("FMKOREA - individual article")
print("="*60)
r = requests.get('https://www.fmkorea.com/best', headers=headers, timeout=15)
r.encoding = 'utf-8'
# Get first article URL
links = re.findall(r'href="(/\d{8,})"', r.text)
if links:
    art_url = 'https://www.fmkorea.com' + links[0]
    print(f'  Fetching: {art_url}')
    r2 = requests.get(art_url, headers=headers, timeout=15)
    r2.encoding = 'utf-8'
    # Find body content div
    body_m = re.search(r'<div\s+class="document_[^"]*"[^>]*>(.*?)</div>\s*</div>', r2.text, re.DOTALL)
    if body_m:
        body_text = re.sub(r'<[^>]+>', ' ', body_m.group(1)).strip()
        print(f'  Body text ({len(body_text)} chars): {body_text[:300]}')
    else:
        # Try xe_content
        body_m = re.search(r'class="xe_content"[^>]*>(.*?)</div>', r2.text, re.DOTALL)
        if body_m:
            body_text = re.sub(r'<[^>]+>', ' ', body_m.group(1)).strip()
            print(f'  xe_content ({len(body_text)} chars): {body_text[:300]}')
        else:
            print(f'  Body not found with known patterns')
    # Title
    title_m = re.search(r'<title>(.*?)</title>', r2.text)
    print(f'  Title: {title_m.group(1)[:80] if title_m else "N/A"}')

# 4. Ruliweb - fetch individual article body
print("\n" + "="*60)
print("RULIWEB - individual article")
print("="*60)
r = requests.get('https://bbs.ruliweb.com/best/humor/best', headers=headers, timeout=15)
r.encoding = 'utf-8'
links = re.findall(r'href="(https?://bbs\.ruliweb\.com/[^"]*read/\d+)"', r.text)
if links:
    art_url = links[0]
    print(f'  Fetching: {art_url}')
    r2 = requests.get(art_url, headers=headers, timeout=15)
    r2.encoding = 'utf-8'
    # Find body
    body_m = re.search(r'<div\s+class="view_content"[^>]*>(.*?)</div>', r2.text, re.DOTALL)
    if body_m:
        body_text = re.sub(r'<[^>]+>', ' ', body_m.group(1)).strip()
        print(f'  Body ({len(body_text)} chars): {body_text[:300]}')
    else:
        body_m = re.search(r'class="board_main_content"[^>]*>(.*?)</div>', r2.text, re.DOTALL)
        if body_m:
            body_text = re.sub(r'<[^>]+>', ' ', body_m.group(1)).strip()
            print(f'  board_main_content ({len(body_text)} chars): {body_text[:300]}')
        else:
            print(f'  Body not found')
    title_m = re.search(r'<title>(.*?)</title>', r2.text)
    print(f'  Title: {title_m.group(1)[:80] if title_m else "N/A"}')