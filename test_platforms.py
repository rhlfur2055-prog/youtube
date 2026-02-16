import sys
sys.path.insert(0, '.')
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8',
}

import requests

def clean_html(raw):
    raw = re.sub(r'<br\s*/?>', chr(10), raw)
    raw = re.sub(r'<[^>]+>', ' ', raw)
    raw = re.sub(r'&[a-zA-Z]+;', ' ', raw)
    raw = re.sub(r'&#\d+;', ' ', raw)
    return re.sub(r'\s+', ' ', raw).strip()

platforms = {
    'fmkorea': {
        'list_url': 'https://www.fmkorea.com/best',
        'link_pattern': r'href="(/\d{8,})"',
        'base_url': 'https://www.fmkorea.com',
        'body_pattern': r'class="[^"]*xe_content[^"]*"[^>]*>(.*?)</div>',
    },
    'ruliweb': {
        'list_url': 'https://bbs.ruliweb.com/best/humor/best',
        'link_pattern': r'href="(https?://bbs\.ruliweb\.com/[^"]*read/\d+)"',
        'base_url': '',
        'body_pattern': r'class="view_content[^"]*"[^>]*>(.*?)<div\s+class="',
    },
    'theqoo': {
        'list_url': 'https://theqoo.net/hot',
        'link_pattern': r'href="(/hot/\d{5,})"',
        'base_url': 'https://theqoo.net',
        'body_pattern': r'class="[^"]*xe_content[^"]*"[^>]*>(.*?)</div>',
    },
    'natepann': {
        'list_url': 'https://pann.nate.com/talk/ranking/d',
        'link_pattern': r'href="(/talk/\d+)"',
        'base_url': 'https://pann.nate.com',
        'body_pattern': r'id="contentArea"[^>]*>(.*?)</div>',
    },
}

for name, cfg in platforms.items():
    print()
    print('=' * 60)
    print('PLATFORM: ' + name)
    print('=' * 60)
    
    try:
        r = requests.get(cfg['list_url'], headers=headers, timeout=15)
        r.encoding = 'utf-8'
        links = re.findall(cfg['link_pattern'], r.text)
        links = [l for l in links if 'comment' not in l and 'category' not in l]
        seen = set()
        unique = []
        for l in links:
            if l not in seen:
                seen.add(l)
                unique.append(l)
        links = unique
        
        print('  List page: ' + str(len(links)) + ' URLs found')
        if links:
            print('  First 3: ' + str(links[:3]))
        
        if links:
            art_url = cfg['base_url'] + links[0] if not links[0].startswith('http') else links[0]
            print('  Fetching article: ' + art_url)
            r2 = requests.get(art_url, headers=headers, timeout=15)
            r2.encoding = 'utf-8'
            
            title_m = re.search(r'<title>(.*?)</title>', r2.text)
            title = clean_html(title_m.group(1)) if title_m else 'N/A'
            print('  Title: ' + title[:60])
            
            body_m = re.search(cfg['body_pattern'], r2.text, re.DOTALL)
            if body_m:
                body = clean_html(body_m.group(1))
                print('  Body: ' + str(len(body)) + ' chars')
                print('  Preview: ' + body[:150] + '...')
            else:
                print('  Body: NOT FOUND with pattern')
                all_divs = re.findall(r'class="([^"]*(?:content|article|body|text|memo|view)[^"]*?)"', r2.text)
                print('  Available divs: ' + str(list(set(all_divs))[:10]))
    
    except Exception as e:
        print('  ERROR: ' + str(e))

print()
print('=' * 60)
print('ALL TESTS COMPLETE')
print('=' * 60)
