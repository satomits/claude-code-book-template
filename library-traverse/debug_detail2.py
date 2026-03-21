"""追加調査: 川崎の書名構造・秦野のAJAX・大和の貸出URL"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import httpx
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0", "Accept-Language": "ja"}


async def check_kawasaki_full_html():
    """川崎市立 - 予約リストの書名確認"""
    print("\n=== 川崎市立図書館 - reservelist全HTML ===")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as c:
        r = await c.get("https://www.library.city.kawasaki.jp/idcheck")
        soup = BeautifulSoup(r.text, "lxml")
        login_form = next((f for f in soup.find_all("form") if "inputForm" in f.get("action", "")), None)
        data = {inp["name"]: inp.get("value", "") for inp in login_form.find_all("input") if inp.get("name")}
        data["textUserId"] = "190001690055"
        data["textPassword"] = "32693269"
        data["buttonLogin"] = "ログイン"
        action = urljoin(str(r.url), login_form.get("action", ""))
        await c.post(action, data=data)

        r2 = await c.get("https://www.library.city.kawasaki.jp/reservelist")
        soup2 = BeautifulSoup(r2.text, "lxml")
        # 最初の予約アイテムの親構造を確認
        item = soup2.find("div", {"class": "item"})
        if item:
            parent = item.parent
            print(f"Parent tag: {parent.name} class={parent.get('class', '')} id={parent.get('id', '')}")
            print(f"Parent HTML (500 chars):\n{str(parent)[:1000]}")


async def check_licsre_playwright(name, base_url, card, pwd):
    """NEC LiCS-Re SaaS - Playwrightで動的コンテンツ取得"""
    print(f"\n=== {name} - Playwright ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")

        await page.goto(f"{base_url}/webopac/login.do")
        await page.fill('input[name="userno"]', card)
        await page.fill('input[name="passwd"]', pwd)
        await page.click('input[type="submit"]')
        await page.wait_for_load_state("networkidle")

        print(f"  URL after login: {page.url}")

        # usermenu.do でポータルページを確認
        await page.goto(f"{base_url}/webopac/usermenu.do")
        # Loading... が消えるまで待つ
        try:
            await page.wait_for_function(
                "!document.body.innerText.includes('Loading...')",
                timeout=15000
            )
        except Exception:
            pass
        await page.wait_for_timeout(2000)

        soup = BeautifulSoup(await page.content(), "html.parser")
        print(f"  Title: {soup.find('title').get_text() if soup.find('title') else '?'}")

        # 貸出状況モジュール
        lend_div = soup.find("div", {"id": "M_LENDLIST"})
        print(f"\n  M_LENDLIST: {str(lend_div)[:800] if lend_div else 'Not found'}")

        # 予約状況モジュール
        rsv_div = soup.find("div", {"id": "M_RESERVELIST"})
        print(f"\n  M_RESERVELIST: {str(rsv_div)[:800] if rsv_div else 'Not found'}")

        # テーブル全体
        for i, t in enumerate(soup.find_all("table")):
            rows = t.find_all("tr")
            print(f"\n  Table[{i}] id={t.get('id','')!r} ({len(rows)} rows)")
            for row in rows[:4]:
                print(f"    {row.get_text(strip=True)[:120]}")

        await browser.close()


async def check_yamato_lend():
    """大和市立図書館 - 貸出ページURL確認"""
    print("\n=== 大和市立図書館 - 貸出ページ ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")
        BASE = "https://library.city.yamato.kanagawa.jp"

        await page.goto(f"{BASE}/licsxp-opac/WOpacMnuTopInitAction.do?WebLinkFlag=1")
        await page.fill('input[name="username"]', "0193777422")
        await page.fill('input[name="j_password"]', "JH8OUX")
        await page.click('input[value="ログイン"]')
        await page.wait_for_load_state("networkidle")

        # 直接URLで貸出ページ試行
        for path in [
            "/licsxp-opac/WOpacMnuTopToPwdLibraryAction.do?gamen=usrlend",
            "/licsxp-opac/WOpacMnuTopToPwdLibraryAction.do?gamen=usrrsv",
        ]:
            await page.goto(BASE + path)
            await page.wait_for_load_state("networkidle")
            soup = BeautifulSoup(await page.content(), "html.parser")
            title = soup.find("title")
            tables = soup.find_all("table", {"id": "ItemDetaTable"})
            print(f"\n  {path}")
            print(f"  URL: {page.url}")
            print(f"  Title: {title.get_text() if title else '?'}")
            for t in tables:
                rows = t.find_all("tr")
                print(f"  Table rows: {len(rows)}")
                for row in rows[:3]:
                    tds = row.find_all(["th", "td"])
                    for i, td in enumerate(tds):
                        print(f"    [{i}] {td.get_text(strip=True)[:60]!r}")

        await browser.close()


async def main():
    await check_kawasaki_full_html()
    await check_licsre_playwright("秦野市立図書館", "https://www.ip.licsre-saas.jp/hadano", "11607553", "JH8OUX")
    await check_licsre_playwright("伊勢原市立図書館", "https://www.is.licsre-saas.jp/isehara", "0191452200", "iseJH8OUX")
    await check_yamato_lend()


asyncio.run(main())
