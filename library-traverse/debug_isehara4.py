"""伊勢原 - portal_lendlist.doの挙動確認"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE = "https://www.is.licsre-saas.jp/isehara"
CARD = "0191452200"
PWD = "iseJH8OUX"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")

        # ログイン
        await page.goto(f"{BASE}/webopac/login.do")
        await page.fill('input[name="userno"]', CARD)
        await page.fill('input[name="passwd"]', PWD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        print(f"After login URL: {page.url}")
        print(f"Has logout: {'ログアウト' in await page.content()}")

        # usermenu.do を訪問
        await page.goto(f"{BASE}/webopac/usermenu.do")
        await page.wait_for_load_state("networkidle")
        print(f"usermenu URL: {page.url}")

        # portal_lendlist.do
        await page.goto(f"{BASE}/webopac/portal_lendlist.do")
        await page.wait_for_load_state("networkidle")
        content = await page.content()
        print(f"\nportal_lendlist.do URL: {page.url}")
        print(f"Content (500 chars): {content[:500]}")

        soup = BeautifulSoup(content, "html.parser")
        tables = soup.find_all("table")
        print(f"Tables: {len(tables)}")
        for t in tables:
            rows = t.find_all("tr")
            print(f"  Table ({len(rows)} rows)")
            for row in rows:
                print(f"    {row.get_text(strip=True)[:100]}")

        # リダイレクトされていないか確認
        print(f"\nFinal URL: {page.url}")

        await browser.close()


asyncio.run(main())
