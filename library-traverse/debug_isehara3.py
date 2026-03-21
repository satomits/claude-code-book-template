"""伊勢原 - portal_userinfo.do の内容確認"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import httpx

BASE = "https://www.is.licsre-saas.jp/isehara"
CARD = "0191452200"
PWD = "iseJH8OUX"

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0", "Accept-Language": "ja"}


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")

        await page.goto(f"{BASE}/webopac/login.do")
        await page.fill('input[name="userno"]', CARD)
        await page.fill('input[name="passwd"]', PWD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # portal_usermenu.do を確認
        await page.goto(f"{BASE}/webopac/portal_usermenu.do")
        await page.wait_for_load_state("networkidle")
        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")
        print("=== portal_usermenu.do ===")
        print(f"Title: {soup.find('title').get_text() if soup.find('title') else '?'}")
        print(content[:2000])

        # portal_userinfo.do を確認
        await page.goto(f"{BASE}/webopac/portal_userinfo.do")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(3000)
        content2 = await page.content()
        soup2 = BeautifulSoup(content2, "html.parser")
        print("\n\n=== portal_userinfo.do ===")
        print(content2[:3000])

        # userinfo.do の各タブを試す
        for path in ["/webopac/userinfo.do?tab=loan",
                     "/webopac/userinfo.do?tab=reserve",
                     "/webopac/userinfo.do?tab=lend",
                     "/webopac/userinfo.do?tabname=lend",
                     "/webopac/userinfo.do?tabname=loan",
                     "/webopac/userinfo.do?tabname=reserve",
                     "/webopac/portal_lendlist.do",
                     "/webopac/portal_reservelist.do"]:
            await page.goto(BASE + path)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(1000)
            c = await page.content()
            soup3 = BeautifulSoup(c, "html.parser")
            title = soup3.find("title")
            tables = soup3.find_all("table")
            print(f"\n{path}: title={title.get_text()[:50] if title else '?'!r} tables={len(tables)}")
            for t in tables[:2]:
                rows = t.find_all("tr")
                print(f"  Table id={t.get('id','')!r} ({len(rows)} rows)")
                for row in rows[:3]:
                    print(f"    {row.get_text(strip=True)[:100]}")

        await browser.close()


asyncio.run(main())
