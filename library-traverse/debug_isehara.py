"""伊勢原市立図書館 - 貸出・予約ページ探索"""
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
        print(f"URL after login: {page.url}")

        # usermenu.do のすべてのコンテンツを確認
        await page.goto(f"{BASE}/webopac/usermenu.do")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(3000)

        soup = BeautifulSoup(await page.content(), "html.parser")
        print(f"Title: {soup.find('title').get_text() if soup.find('title') else '?'}")

        # すべてのテーブル
        for i, t in enumerate(soup.find_all("table")):
            rows = t.find_all("tr")
            print(f"\nTable[{i}] id={t.get('id','')!r} ({len(rows)} rows)")
            for row in rows[:4]:
                print(f"  {row.get_text(strip=True)[:120]}")

        # テーブルがない場合はdivを確認
        print("\n--- Main content divs ---")
        main = soup.find("div", {"id": "main"}) or soup.find("div", {"id": "contentsContainer"})
        if main:
            print(str(main)[:2000])

        # 直接貸出・予約ページを試す
        for path in [
            "/webopac/myloan.do",
            "/webopac/myreserve.do",
            "/webopac/loanlist.do",
            "/webopac/reservelist.do",
            "/webopac/userinfo.do",
            "/webopac/mypage.do",
        ]:
            try:
                await page.goto(BASE + path)
                await page.wait_for_load_state("networkidle")
                title = await page.title()
                has_logout = "ログアウト" in await page.content()
                soup2 = BeautifulSoup(await page.content(), "html.parser")
                tables = soup2.find_all("table")
                print(f"\n  {path} -> URL:{page.url.split('/')[-1]} title={title[:40]!r} tables={len(tables)} logout={has_logout}")
                for t in tables[:2]:
                    rows = t.find_all("tr")
                    print(f"    Table id={t.get('id','')!r} ({len(rows)} rows)")
                    for row in rows[:3]:
                        print(f"      {row.get_text(strip=True)[:100]}")
            except Exception as e:
                print(f"  {path} -> Error: {e}")

        await browser.close()


asyncio.run(main())
