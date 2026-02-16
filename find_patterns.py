import requests
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8',
}

# 1. Ruliweb - best humor list + article
print("="*60)
print("RULIWEB")
print("="*60)
r = requests.get('https://bbs.ruliweb.com/best/humor/best', headers=headers, timeout=15)
r.encoding = 'utf-8'
links = re.findall(r'href="(https?://bbs\.ruliweb\.com/[^"]*read/\d+)"', r.text)
# Get titles too
title_links = re.findall(r'<a[^>]*href="(https?://bbs\.ruliweb\.com/[^"]*read/\d+)"[^>]*class="[^"]*deco[^"]*"[^>]*>(.*?)</a>', r.text, re.DOTALL)
if not title_links:
    title_links = re.findall(r'<a[^>]*href="(https?://bbs\.ruliweb\.com/[^"]*read/\d+)"[^>]*>(.*?)</a>', r.text, re.DOTALL)
for href, title in title_links[:3]:
    t = re.sub(r'<[^>]+>', '', title).strip()
    if t and len(t) > 3:
        print(f'  {href} -> {t[:60]}')

# Fetch first article and look for all div classes that might contain body
if links:
    # Try a humor board link specifically
    humor_links = [l for l in links if '/humor/' in l or '/community/' in l or '/best/' in l]
    art_url = humor_links[0] if humor_links else links[0]
    print(f'  Fetching: {art_url}')
    r2 = requests.get(art_url, headers=headers, timeout=15)
    r2.encoding = 'utf-8'
    # List all div class names that contain "content" or "view" or "article" or "board"
    div_classes = re.findall(r'<div[^>]*class="([^"]*(?:content|view|article|board|text|body)[^"]*)"', r2.text)
    print(f'  Div classes with content/view/article/board/text/body:')
    for dc in set(div_classes):
        print(f'    .{dc}')
    # Try view_content broader
    body_m = re.search(r'class="view_content"[^>]*>(.*?)<div\s+class="', r2.text, re.DOTALL)
    if body_m:
        body_text = re.sub(r'<[^>]+>', ' ', body_m.group(1)).strip()
        body_text = re.sub(r'\s+', ' ', body_text)
        print(f'  view_content ({len(body_text)} chars): {body_text[:300]}')

# 2. Instiz - fetch article body
print("\n" + "="*60)
print("INSTIZ")
print("="*60)
r = requests.get('https://www.instiz.net/pt', headers=headers, timeout=15)
r.encoding = 'utf-8'
links = re.findall(r'href="(?:https?://www\.instiz\.net)?(/pt/\d+)[^"]*"', r.text)
print(f'  Found {len(links)} article links')
if links:
    art_url = 'https://www.instiz.net' + links[0]
    print(f'  Fetching: {art_url}')
    r2 = requests.get(art_url, headers=headers, timeout=15)
    r2.encoding = 'utf-8'
    div_classes = re.findall(r'<div[^>]*class="([^"]*(?:content|view|article|board|text|body|memo)[^"]*)"', r2.text)
    print(f'  Div classes:')
    for dc in set(div_classes):
        print(f'    .{dc}')
    # Try memo_content or similar
    body_m = re.search(r'class="[^"]*memo_content[^"]*"[^>]*>(.*?)</div>', r2.text, re.DOTALL)
    if body_m:
        bt = re.sub(r'<[^>]+>', ' ', body_m.group(1)).strip()[:300]
        print(f'  memo_content: {bt}')
    # Also try to find title
    title_m = re.search(r'<title>(.*?)</title>', r2.text)
    print(f'  Title: {title_m.group(1)[:80] if title_m else "N/A"}')

# 3. Theqoo - fetch article body
print("\n" + "="*60)
print("THEQOO")
print("="*60)
r = requests.get('https://theqoo.net/hot', headers=headers, timeout=15)
r.encoding = 'utf-8'
links = re.findall(r'href="(/hot/\d+)"', r.text)
links = [l for l in links if 'comment' not in l and 'category' not in l]
print(f'  Found {len(links)} article links')
if links:
    art_url = 'https://theqoo.net' + links[0]
    print(f'  Fetching: {art_url}')
    r2 = requests.get(art_url, headers=headers, timeout=15)
    r2.encoding = 'utf-8'
    div_classes = re.findall(r'<div[^>]*class="([^"]*(?:content|view|article|board|text|body|document)[^"]*)"', r2.text)
    print(f'  Div classes:')
    for dc in set(div_classes):
        print(f'    .{dc}')
    # Try xe_content (XE CMS based)
    body_m = re.search(r'class="xe_content"[^>]*>(.*?)</div>', r2.text, re.DOTALL)
    if body_m:
        bt = re.sub(r'<[^>]+>', ' ', body_m.group(1)).strip()
        bt = re.sub(r'\s+', ' ', bt)
        print(f'  xe_content ({len(bt)} chars): {bt[:300]}')
    title_m = re.search(r'<title>(.*?)</title>', r2.text)
    print(f'  Title: {title_m.group(1)[:80] if title_m else "N/A"}')
