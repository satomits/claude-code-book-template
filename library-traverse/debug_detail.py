"""ページ詳細構造調査 - 川崎・秦野・伊勢原・大和"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import httpx
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0", "Accept-Language": "ja"}


async def check_kawasaki_item_structure():
    """川崎市立 - div.itemの詳細構造"""
    print("\n=== 川崎市立図書館 - div.item 詳細 ===")
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

        # 貸出リスト
        r2 = await c.get("https://www.library.city.kawasaki.jp/rentallist")
        soup2 = BeautifulSoup(r2.text, "lxml")
        print("\n--- /rentallist ---")
        items = soup2.find_all("div", {"class": "item"})
        print(f"div.item count: {len(items)}")
        if items:
            print("First item HTML (truncated):")
            print(str(items[0])[:1000])
        else:
            # 他の構造を探す
            for div in soup2.find_all("div", {"class": True}):
                cls = " ".join(div.get("class", []))
                txt = div.get_text(strip=True)
                if txt and len(txt) > 5:
                    print(f"  div.{cls[:40]}: {txt[:100]}")

        # 予約リスト
        r3 = await c.get("https://www.library.city.kawasaki.jp/reservelist")
        soup3 = BeautifulSoup(r3.text, "lxml")
        print("\n--- /reservelist ---")
        items3 = soup3.find_all("div", {"class": "item"})
        print(f"div.item count: {len(items3)}")
        if items3:
            print("First item HTML:")
            print(str(items3[0])[:1500])


async def check_licsre_usermenu(name, base_url, card, pwd):
    """NEC LiCS-Re SaaS - usermenu.doの完全HTML"""
    print(f"\n=== {name} - usermenu.do 詳細 ===")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as c:
        r = await c.get(f"{base_url}/webopac/login.do")
        soup = BeautifulSoup(r.text, "lxml")
        form = soup.find("form")
        data = {inp["name"]: inp.get("value", "") for inp in form.find_all("input") if inp.get("name")}
        data["userno"] = card
        data["passwd"] = pwd
        action = urljoin(str(r.url), form.get("action", "login.do"))
        await c.post(action, data=data)

        r2 = await c.get(f"{base_url}/webopac/usermenu.do")
        soup2 = BeautifulSoup(r2.text, "lxml")
        print(f"Title: {soup2.find('title').get_text() if soup2.find('title') else '?'}")
        print(f"Has ログアウト: {'ログアウト' in r2.text}")

        # テーブル全て
        for i, t in enumerate(soup2.find_all("table")):
            rows = t.find_all("tr")
            print(f"\n  Table[{i}] id={t.get('id','')!r} class={t.get('class','')!r} ({len(rows)} rows)")
            for row in rows[:5]:
                print(f"    {row.get_text(strip=True)[:120]}")

        # 貸出・予約関連のdiv
        print("\n  Divs with loan/reserve content:")
        for div in soup2.find_all("div"):
            cls = " ".join(div.get("class", []))
            iid = div.get("id", "")
            txt = div.get_text(strip=True)
            if any(k in txt for k in ["貸出", "予約", "返却", "取置"]) and len(txt) < 300:
                print(f"  div id={iid!r} class={cls[:30]!r}: {txt[:150]}")

        # 貸出・予約URLを試す
        for path in ["/webopac/mypage.do", "/webopac/loan.do", "/webopac/reserve.do",
                     "/webopac/loanlist.do", "/webopac/reservelist.do",
                     "/webopac/userinfo.do?mode=list", "/webopac/userloan.do",
                     "/webopac/userreserve.do"]:
            r3 = await c.get(base_url + path)
            if r3.status_code == 200 and "ログアウト" in r3.text:
                soup3 = BeautifulSoup(r3.text, "lxml")
                title3 = soup3.find("title")
                tables3 = soup3.find_all("table")
                print(f"\n  {path} -> {r3.status_code} | {title3.get_text()[:50] if title3 else '?'} | tables={len(tables3)}")
                for t in tables3[:2]:
                    rows = t.find_all("tr")
                    print(f"    Table id={t.get('id','')!r} ({len(rows)} rows)")
                    for row in rows[:3]:
                        print(f"      {row.get_text(strip=True)[:100]}")


async def check_yamato_detail():
    """大和市立図書館 - ログイン後の詳細ページ構造"""
    print("\n=== 大和市立図書館 - 詳細調査 ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")
        BASE = "https://library.city.yamato.kanagawa.jp"

        await page.goto(f"{BASE}/licsxp-opac/WOpacMnuTopInitAction.do?WebLinkFlag=1")
        await page.fill('input[name="username"]', "0193777422")
        await page.fill('input[name="j_password"]', "JH8OUX")
        await page.click('input[value="ログイン"]')
        await page.wait_for_load_state("networkidle")

        print(f"URL after login: {page.url}")
        print(f"Title: {await page.title()}")

        soup = BeautifulSoup(await page.content(), "html.parser")

        # 予約テーブル
        print("\n--- Tables ---")
        for i, t in enumerate(soup.find_all("table")):
            rows = t.find_all("tr")
            print(f"Table[{i}] id={t.get('id','')!r} ({len(rows)} rows)")
            for row in rows[:4]:
                print(f"  {row.get_text(strip=True)[:120]}")

        # 予約状況ページをクリック
        print("\n--- Clicking 予約状況 ---")
        try:
            await page.evaluate("toUsrRsv(1)")
            await page.wait_for_load_state("networkidle")
            print(f"URL: {page.url}")
            print(f"Title: {await page.title()}")
            soup2 = BeautifulSoup(await page.content(), "html.parser")
            for i, t in enumerate(soup2.find_all("table")):
                rows = t.find_all("tr")
                print(f"Table[{i}] id={t.get('id','')!r} ({len(rows)} rows)")
                for row in rows[:4]:
                    print(f"  {row.get_text(strip=True)[:120]}")
        except Exception as e:
            print(f"  Error: {e}")

        # 貸出状況ページをクリック
        print("\n--- Clicking 貸出状況 ---")
        try:
            await page.evaluate("toUsrLend(1)")
            await page.wait_for_load_state("networkidle")
            print(f"URL: {page.url}")
            print(f"Title: {await page.title()}")
            soup3 = BeautifulSoup(await page.content(), "html.parser")
            for i, t in enumerate(soup3.find_all("table")):
                rows = t.find_all("tr")
                print(f"Table[{i}] id={t.get('id','')!r} ({len(rows)} rows)")
                for row in rows[:4]:
                    print(f"  {row.get_text(strip=True)[:120]}")
        except Exception as e:
            print(f"  Error: {e}")

        await browser.close()


async def main():
    await check_kawasaki_item_structure()
    await check_licsre_usermenu("秦野市立図書館", "https://www.ip.licsre-saas.jp/hadano", "11607553", "JH8OUX")
    await check_licsre_usermenu("伊勢原市立図書館", "https://www.is.licsre-saas.jp/isehara", "0191452200", "iseJH8OUX")
    await check_yamato_detail()


asyncio.run(main())
