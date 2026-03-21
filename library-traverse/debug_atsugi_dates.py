"""厚木市立図書館 - 貸出・予約の日付HTML構造確認"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE = "https://www.lib.mytownclub.com"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")
        await page.goto(f"{BASE}/winj/opac/login.do?lang=ja")
        await page.fill('input[name="txt_usercd"]', "6078520")
        await page.fill('input[name="txt_password"]', "3269")
        await page.click('input[name="submit_btn_login"]')
        await page.wait_for_selector('text=ログアウト', timeout=10000)

        # 貸出ページ
        await page.goto(f"{BASE}/winj/opac/lend-list.do?lang=ja")
        try:
            await page.wait_for_function("!document.body.innerText.includes('Now Loading')", timeout=15000)
        except Exception:
            pass
        soup = BeautifulSoup(await page.content(), "html.parser")
        reports = soup.find_all("div", {"class": "report"})
        print(f"=== 貸出ページ ({len(reports)} reports) ===")
        for i, r in enumerate(reports[:2]):
            info = r.find("div", {"class": "info"})
            print(f"\nReport[{i}] div.info HTML:")
            print(str(info)[:800] if info else "No info div")

        # 予約ページ
        await page.goto(f"{BASE}/winj/opac/reserve-list.do?lang=ja")
        try:
            await page.wait_for_function("!document.body.innerText.includes('Now Loading')", timeout=15000)
        except Exception:
            pass
        soup2 = BeautifulSoup(await page.content(), "html.parser")
        reports2 = soup2.find_all("div", {"class": "report"})
        print(f"\n=== 予約ページ ({len(reports2)} reports) ===")
        for i, r in enumerate(reports2[:3]):
            info = r.find("div", {"class": "info"})
            print(f"\nReport[{i}] div.info HTML:")
            print(str(info)[:800] if info else "No info div")

        await browser.close()

asyncio.run(main())
