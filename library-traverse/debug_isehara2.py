"""伊勢原 - M_LENDLIST/M_RESERVELIST が取得できない原因調査"""
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

        await page.goto(f"{BASE}/webopac/login.do")
        await page.fill('input[name="userno"]', CARD)
        await page.fill('input[name="passwd"]', PWD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        await page.goto(f"{BASE}/webopac/usermenu.do")
        await page.wait_for_load_state("networkidle")

        # 5秒待機
        await page.wait_for_timeout(5000)

        # "Loading..." が残っているか確認
        content = await page.content()
        print(f"Has 'Loading...': {'Loading...' in content}")

        # M_LENDLIST/M_RESERVELIST の内容
        soup = BeautifulSoup(content, "html.parser")
        for div_id in ["M_LENDLIST", "M_RESERVELIST"]:
            div = soup.find("div", {"id": div_id})
            if div:
                print(f"\n{div_id} content (first 1000 chars):")
                print(str(div)[:1000])
            else:
                print(f"\n{div_id}: Not found in HTML")

        # ページ内のすべてのiframe確認
        iframes = await page.query_selector_all("iframe")
        print(f"\nIframes: {len(iframes)}")
        for iframe in iframes:
            src = await iframe.get_attribute("src")
            print(f"  src={src!r}")

        # ネットワークリクエストをキャプチャして再試行
        print("\n--- Monitoring network requests ---")
        requests_seen = []
        page.on("request", lambda req: requests_seen.append(req.url))

        await page.reload()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(5000)

        # AJAX エンドポイント候補
        for url in requests_seen:
            if any(k in url for k in ["lend", "loan", "reserve", "module", "portal", "comp"]):
                print(f"  {url}")

        content2 = await page.content()
        soup2 = BeautifulSoup(content2, "html.parser")
        for div_id in ["M_LENDLIST", "M_RESERVELIST"]:
            div = soup2.find("div", {"id": div_id})
            if div:
                print(f"\n[Reload] {div_id}:")
                print(str(div)[:1000])

        await browser.close()


asyncio.run(main())
