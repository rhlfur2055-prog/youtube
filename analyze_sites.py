import requests
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8',
}

sites = {
    'fmkorea': 'https://www.fmkorea.com/best',
    'ruliweb': 'https://bbs.ruliweb.com/best/humor/best',
    'instiz': 'https://www.instiz.net/pt',
    'theqoo': 'https://theqoo.net/hot',
    'natepann': 'https://pann.nate.com/talk/ranking/d',
}

for name, url in sites.items():
    print(f'\n{"="*60}')
    print(f'SITE: {name} -- {url}')
    print(f'{"="*60}')
    try:
        r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        r.encoding = 'utf-8'
        print(f'Status: {r.status_code}, URL: {r.url}')
        print(f'Content length: {len(r.text)}')

        links = None

        # Find article links
        if name == 'fmkorea':
            links = re.findall(r'<a[^>]*href="(/[^"]*\d{8,}[^"]*)"[^>]*class="[^"]*hotdeal_var8[^"]*"[^>]*>(.*?)</a>', r.text, re.DOTALL)
            if not links:
                links = re.findall(r'<a[^>]*href="(/\d{8,})"[^>]*>(.*?)</a>', r.text, re.DOTALL)
            if not links:
                # broader search
                links = re.findall(r'href="(/\d{5,}[^"]*)"', r.text)
                print(f'  URL patterns found: {links[:5]}')
            else:
                for href, title in links[:3]:
                    t = re.sub(r'<[^>]+>', '', title).strip()
                    print(f'  {href} -> {t[:50]}')

        elif name == 'ruliweb':
            links = re.findall(r'<a[^>]*href="(https?://bbs\.ruliweb\.com/[^"]*read/\d+)"[^>]*>(.*?)</a>', r.text, re.DOTALL)
            if not links:
                links = re.findall(r'href="([^"]*ruliweb[^"]*read/\d+)"', r.text)
                print(f'  URL patterns found: {links[:5]}')
            else:
                for href, title in links[:3]:
                    t = re.sub(r'<[^>]+>', '', title).strip()
                    print(f'  {href} -> {t[:50]}')

        elif name == 'instiz':
            links = re.findall(r'href="(/pt/\d+)"', r.text)
            if not links:
                links = re.findall(r'href="(/pt\d+)"', r.text)
            print(f'  URL patterns found: {links[:5]}')

        elif name == 'theqoo':
            links = re.findall(r'href="(https?://theqoo\.net/[^"]*\d{8,}[^"]*)"', r.text)
            if not links:
                links = re.findall(r'href="(/[^"]*\d{5,}[^"]*)"', r.text)
            print(f'  URL patterns found: {links[:5]}')

        elif name == 'natepann':
            links = re.findall(r'href="(/talk/\d+)"', r.text)
            print(f'  URL patterns found: {links[:5]}')

        # Check for article body patterns (for individual article pages)
        print(f'  Total links found: {len(links) if links else 0}')

    except Exception as e:
        print(f'  ERROR: {e}')
