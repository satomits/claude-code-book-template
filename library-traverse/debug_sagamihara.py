"""相模原 利用状況ページの全テーブルID確認"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE = "https://www.lib.sagamihara.kanagawa.jp"
CARD = "87854188"
PASS = "JH8OUX"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")

        await page.goto(f"{BASE}/toshow/asp/WwPortLogin.aspx")
        await page.fill('input[name="txtRiyoshaCD"]', CARD)
        await page.fill('input[name="txtPassWord"]', PASS)
        await page.click('input[name="btnLogin"]')
        await page.wait_for_load_state("networkidle")
        await page.click('input[name="btnMyPort06"]')
        await page.wait_for_load_state("networkidle")

        soup = BeautifulSoup(await page.content(), "html.parser")

        # 全テーブルとそのID
        print("=== All tables ===")
        for t in soup.find_all("table"):
            print(f"id={t.get('id','')!r} class={t.get('class','')} rows={len(t.find_all('tr'))}")

        # IDを持つ全要素
        print("\n=== Elements with id ===")
        for elem in soup.find_all(id=True):
            iid = elem.get("id", "")
            if any(k in iid.lower() for k in ["kas", "yoy", "loan", "res", "grid", "dg", "list"]):
                print(f"  {elem.name} id={iid!r}: {elem.get_text(strip=True)[:60]}")

        # 予約テーブルの正確な構造（最初の3行）
        yoy_table = soup.find("table", {"id": "dgdYoy"})
        if yoy_table:
            print("\n=== dgdYoy table columns (row 0) ===")
            rows = yoy_table.find_all("tr")
            if rows:
                tds = rows[0].find_all(["th", "td"])
                for i, td in enumerate(tds):
                    print(f"  [{i}] {td.get_text(strip=True)!r}")

            print("\n=== Row 1 raw ===")
            if len(rows) > 1:
                tds = rows[1].find_all("td")
                for i, td in enumerate(tds):
                    print(f"  [{i}] {td.get_text(strip=True)[:60]!r}")

        await browser.close()


asyncio.run(main())
