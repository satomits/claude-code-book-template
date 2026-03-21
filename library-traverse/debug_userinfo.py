"""秦野・伊勢原・大和の利用照会ページ構造調査"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import httpx
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0", "Accept-Language": "ja"}


async def check_licsre_userinfo(name, base_url, card, pwd):
    print(f"\n=== {name} (/webopac/userinfo.do) ===")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as c:
        r = await c.get(f"{base_url}/webopac/login.do")
        soup = BeautifulSoup(r.text, "lxml")
        form = soup.find("form")
        data = {inp["name"]: inp.get("value", "") for inp in form.find_all("input") if inp.get("name")}
        data["userno"] = card
        data["passwd"] = pwd
        action = urljoin(str(r.url), form.get("action", "login.do"))
        await c.post(action, data=data)

        r2 = await c.get(f"{base_url}/webopac/userinfo.do")
        soup2 = BeautifulSoup(r2.text, "lxml")
        print(f"  Status: {r2.status_code}")
        print(f"  Title: {soup2.find('title').get_text()[:50] if soup2.find('title') else '?'}")

        # テーブル構造
        tables = soup2.find_all("table")
        print(f"  Tables: {len(tables)}")
        for i, t in enumerate(tables[:3]):
            rows = t.find_all("tr")
            if rows:
                print(f"  Table[{i}] ({len(rows)} rows):")
                for row in rows[:5]:
                    print(f"    {row.get_text(strip=True)[:100]}")

        # リンク（貸出・予約ページへ）
        print("  Links:")
        for a in soup2.find_all("a", href=True):
            txt = a.get_text(strip=True)
            href = a["href"]
            if txt and any(k in txt for k in ["貸出", "予約", "延長", "取消"]):
                print(f"    {txt!r:20} -> {href}")

        # usermenu.doを確認
        r3 = await c.get(f"{base_url}/webopac/usermenu.do")
        soup3 = BeautifulSoup(r3.text, "lxml")
        print(f"\n  usermenu.do:")
        print(f"  Title: {soup3.find('title').get_text()[:50] if soup3.find('title') else '?'}")
        for a in soup3.find_all("a", href=True):
            txt = a.get_text(strip=True)
            href = a["href"]
            if txt and ".do" in href:
                print(f"    {txt!r:20} -> {href}")


async def check_yamato_playwright():
    print("\n=== 大和市立図書館 (Playwright) ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")
        BASE = "https://library.city.yamato.kanagawa.jp"

        await page.goto(f"{BASE}/licsxp-opac/WOpacMnuTopInitAction.do?WebLinkFlag=1")
        # JavaScriptログインボタンをクリック
        await page.fill('input[name="username"]', "0193777422")
        await page.fill('input[name="j_password"]', "JH8OUX")
        # type="button"のログインボタン
        await page.click('input[value="ログイン"]')
        await page.wait_for_load_state("networkidle")

        print(f"  URL after login: {page.url}")
        print(f"  Title: {await page.title()}")
        print(f"  Has ログアウト: {'ログアウト' in await page.content()}")

        soup = BeautifulSoup(await page.content(), "html.parser")
        print("  All nav links:")
        for a in soup.find_all("a", href=True):
            txt = a.get_text(strip=True)
            href = a["href"]
            if txt and any(k in txt for k in ["貸出", "予約", "利用", "マイ", "返却"]):
                print(f"    {txt!r:25} -> {href}")

        # ボタン確認
        for btn in soup.find_all("input", {"type": ["submit", "button"]}):
            val = btn.get("value", "")
            name = btn.get("name", "")
            if val and val not in ["検索", "クリア", "キャンセル", ""]:
                print(f"  Button: {val!r} name={name!r}")

        await browser.close()


async def check_kawasaki_pages():
    print("\n=== 川崎市立図書館 (rentallist/reservelist) ===")
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

        for path in ["/rentallist", "/reservelist"]:
            r2 = await c.get(f"https://www.library.city.kawasaki.jp{path}")
            soup2 = BeautifulSoup(r2.text, "lxml")
            title = soup2.find("title")
            tables = soup2.find_all("table")
            print(f"\n  {path}: {r2.status_code} | {title.get_text()[:50] if title else '?'}")
            print(f"  Tables: {len(tables)}")
            for i, t in enumerate(tables[:2]):
                rows = t.find_all("tr")
                if rows:
                    print(f"  Table[{i}] ({len(rows)} rows):")
                    for row in rows[:5]:
                        print(f"    {row.get_text(strip=True)[:100]}")
            # divベースの場合
            if not tables:
                for div in soup2.find_all("div", {"class": True}):
                    cls = " ".join(div.get("class", []))
                    txt = div.get_text(strip=True)
                    if txt and len(txt) > 10 and any(k in cls for k in ["list", "item", "loan", "reserve", "rental"]):
                        print(f"  div.{cls[:30]}: {txt[:80]}")


async def main():
    await check_kawasaki_pages()
    await check_licsre_userinfo("秦野市立図書館", "https://www.ip.licsre-saas.jp/hadano", "11607553", "JH8OUX")
    await check_licsre_userinfo("伊勢原市立図書館", "https://www.is.licsre-saas.jp/isehara", "0191452200", "iseJH8OUX")
    await check_yamato_playwright()


asyncio.run(main())
