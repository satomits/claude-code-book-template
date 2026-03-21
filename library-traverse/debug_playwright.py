"""PlaywrightでLIMEDIOページの構造を確認"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="ja-JP")
        page = await context.new_page()

        BASE = "https://opac.lib.city.yokohama.lg.jp"

        # ログイン
        await page.goto(f"{BASE}/winj/opac/login.do?lang=ja")
        await page.fill('input[name="txt_usercd"]', "9023109473")
        await page.fill('input[name="txt_password"]', "yokTk4dakb$")
        await page.click('input[name="submit_btn_login"]')
        await page.wait_for_selector('text=ログアウト', timeout=10000)
        print("ログイン成功")

        # 予約ページ
        await page.goto(f"{BASE}/winj/opac/reserve-list.do?lang=ja")
        await page.wait_for_function(
            "!document.body.innerText.includes('Now Loading')",
            timeout=15000,
        )
        print("予約ページ読み込み完了")

        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")

        # テーブル確認
        tables = soup.find_all("table")
        print(f"Tables: {len(tables)}")
        for i, t in enumerate(tables):
            rows = t.find_all("tr")
            print(f"  Table[{i}]: {len(rows)} rows")
            for r in rows[:3]:
                print("    ", r.get_text(strip=True)[:100])

        # テーブルがない場合はdivやliを確認
        if not tables:
            print("\nDivs with list-like classes:")
            for d in soup.find_all("div", {"class": True}):
                cls = " ".join(d.get("class", []))
                txt = d.get_text(strip=True)
                if txt and len(txt) > 20:
                    print(f"  .{cls[:40]}: {txt[:80]}")

            # li要素
            list_items = soup.find_all("li")
            print(f"\nList items ({len(list_items)}):")
            for li in list_items[:10]:
                print(" ", li.get_text(strip=True)[:100])

        # ページのメインコンテンツ
        main = soup.find("main")
        if main:
            print("\nMain content:")
            print(main.get_text()[:500])

        await browser.close()


asyncio.run(main())
