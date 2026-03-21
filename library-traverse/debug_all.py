"""各図書館の貸出・予約ページの実際のデータを調査"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import httpx
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0", "Accept-Language": "ja"}


async def check_atsugi():
    """厚木市立図書館 - 予約ページの状態・順位確認"""
    print("\n" + "="*60)
    print("=== 厚木市立図書館 (LIMEDIO) ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")
        BASE = "https://www.lib.mytownclub.com"
        await page.goto(f"{BASE}/winj/opac/login.do?lang=ja")
        await page.fill('input[name="txt_usercd"]', "6078520")
        await page.fill('input[name="txt_password"]', "3269")
        await page.click('input[name="submit_btn_login"]')
        await page.wait_for_selector('text=ログアウト', timeout=10000)

        await page.goto(f"{BASE}/winj/opac/reserve-list.do?lang=ja")
        await page.wait_for_function("!document.body.innerText.includes('Now Loading')", timeout=15000)
        soup = BeautifulSoup(await page.content(), "html.parser")

        # 最初のreportのflex divを確認
        for i, report in enumerate(soup.find_all("div", {"class": "report"})):
            title = report.find("span", {"class": "title"})
            flex = report.find("div", style=lambda s: s and "flex" in s)
            print(f"\nReport[{i}]:")
            print(f"  title: {title.get_text(strip=True)[:40] if title else '?'!r}")
            if flex:
                print(f"  flex div HTML: {str(flex)[:300]}")
            else:
                # flexがない場合
                for div in report.find_all("div"):
                    txt = div.get_text(strip=True)
                    if txt and any(k in txt for k in ["予約", "準備", "取置", "位", "番"]):
                        print(f"  info div: {str(div)[:300]}")
                        break
            if i >= 2:
                break
        await browser.close()


async def check_kawasaki():
    """川崎市立図書館 - ログイン後の貸出・予約ページ確認"""
    print("\n" + "="*60)
    print("=== 川崎市立図書館 ===")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as c:
        r = await c.get("https://www.library.city.kawasaki.jp/idcheck")
        soup = BeautifulSoup(r.text, "lxml")
        login_form = next((f for f in soup.find_all("form") if "inputForm" in f.get("action", "")), None)
        if not login_form:
            print("  Login form not found")
            return
        data = {inp["name"]: inp.get("value", "") for inp in login_form.find_all("input") if inp.get("name")}
        data["textUserId"] = "190001690055"
        data["textPassword"] = "32693269"
        data["buttonLogin"] = "ログイン"
        action = urljoin(str(r.url), login_form.get("action", ""))
        r2 = await c.post(action, data=data)
        print(f"  Login response: {r2.status_code}, URL: {r2.url}")
        print(f"  Has ログアウト: {'ログアウト' in r2.text}")
        soup2 = BeautifulSoup(r2.text, "lxml")
        title = soup2.find("title")
        print(f"  Title: {title.get_text() if title else '?'}")
        # ログイン後のリンク確認
        if "ログアウト" in r2.text:
            for url in ["/mypage/lending", "/mypage/reservation", "/mypage", "/user/lending", "/user/reservation"]:
                r3 = await c.get(f"https://www.library.city.kawasaki.jp{url}")
                soup3 = BeautifulSoup(r3.text, "lxml")
                title3 = soup3.find("title")
                print(f"  {url} -> {r3.status_code} {title3.get_text()[:40] if title3 else '?'}")


async def check_nec_lics(name: str, base_url: str, card: str, pwd: str):
    """NEC LiCS-Re SaaS / LiCS-XP の貸出・予約ページ確認"""
    print("\n" + "="*60)
    print(f"=== {name} ===")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as c:
        # LiCS-Re SaaS
        if "licsre" in base_url:
            login_url = f"{base_url}/webopac/login.do"
        else:
            login_url = f"{base_url}/licsxp-opac/WOpacMnuTopInitAction.do"

        r = await c.get(login_url, params={"WebLinkFlag": "1"} if "licsxp" in base_url else {})
        soup = BeautifulSoup(r.text, "lxml")
        form = soup.find("form")
        if not form:
            print("  No form found")
            return
        data = {inp["name"]: inp.get("value", "") for inp in form.find_all("input") if inp.get("name")}

        if "licsre" in base_url:
            data["userno"] = card
            data["passwd"] = pwd
            action = urljoin(str(r.url), form.get("action", "login.do"))
        else:
            data["username"] = card
            data["j_password"] = pwd
            action = urljoin(str(r.url), form.get("action", "") or login_url)

        r2 = await c.post(action, data=data)
        print(f"  Login: {r2.status_code} URL:{r2.url}")
        print(f"  Has ログアウト: {'ログアウト' in r2.text}")

        if "ログアウト" not in r2.text:
            # パスワードが違うのかも
            print("  Login failed - checking page title")
            soup2 = BeautifulSoup(r2.text, "lxml")
            print(f"  Title: {soup2.find('title').get_text()[:50] if soup2.find('title') else '?'}")
            return

        # ログイン成功した場合の貸出・予約ページを探す
        if "licsre" in base_url:
            for path in ["/webopac/userinfo/loan.do", "/webopac/userinfo/reserve.do",
                         "/webopac/lending.do", "/webopac/reservation.do"]:
                r3 = await c.get(base_url + path)
                soup3 = BeautifulSoup(r3.text, "lxml")
                title3 = soup3.find("title")
                tables = soup3.find_all("table")
                print(f"  {path} -> {r3.status_code} | title={title3.get_text()[:40] if title3 else '?'} | tables={len(tables)}")
                if tables:
                    rows = tables[0].find_all("tr")
                    for row in rows[:3]:
                        print(f"    {row.get_text(strip=True)[:100]}")
        else:
            for path in ["/licsxp-opac/WOpacMnuBookListAction.do",
                         "/licsxp-opac/WOpacMnuYoyakuListAction.do"]:
                r3 = await c.get(base_url + path)
                soup3 = BeautifulSoup(r3.text, "lxml")
                title3 = soup3.find("title")
                tables = soup3.find_all("table")
                print(f"  {path} -> {r3.status_code} | title={title3.get_text()[:40] if title3 else '?'} | tables={len(tables)}")
                if tables:
                    rows = tables[0].find_all("tr")
                    for row in rows[:3]:
                        print(f"    {row.get_text(strip=True)[:100]}")


async def check_kanagawa_pref():
    """神奈川県立図書館 - LIMEDIO"""
    print("\n" + "="*60)
    print("=== 神奈川県立図書館 (LIMEDIO) ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")
        BASE = "https://www.klnet.pref.kanagawa.jp"
        await page.goto(f"{BASE}/winj/opac/login.do?lang=ja")
        await page.fill('input[name="txt_usercd"]', "267818")
        await page.fill('input[name="txt_password"]', "kanTk4dakb$")
        await page.click('input[name="submit_btn_login"]')

        try:
            await page.wait_for_selector('text=ログアウト', timeout=8000)
            print("  Login: OK")
        except Exception:
            print("  Login: FAILED")
            title = await page.title()
            print(f"  Page title: {title}")
            await browser.close()
            return

        # 予約・貸出確認
        for path in ["/winj/opac/reserve-list.do?lang=ja", "/winj/opac/lend-list.do?lang=ja"]:
            await page.goto(BASE + path)
            try:
                await page.wait_for_function("!document.body.innerText.includes('Now Loading')", timeout=12000)
            except Exception:
                pass
            soup = BeautifulSoup(await page.content(), "html.parser")
            reports = soup.find_all("div", {"class": "report"})
            print(f"  {path.split('/')[-1]} -> {len(reports)} reports, URL={page.url}")
            if reports:
                title_span = reports[0].find("span", {"class": "title"})
                print(f"    First: {title_span.get_text(strip=True)[:50] if title_span else '?'}")

        await browser.close()


async def main():
    await check_atsugi()
    await check_kawasaki()
    await check_nec_lics("秦野市立図書館", "https://www.ip.licsre-saas.jp/hadano", "11607553", "JH8OUX")
    await check_nec_lics("伊勢原市立図書館", "https://www.is.licsre-saas.jp/isehara", "0191452200", "iseJH8OUX")
    await check_nec_lics("大和市立図書館", "https://library.city.yamato.kanagawa.jp", "0193777422", "JH8OUX")
    await check_kanagawa_pref()


asyncio.run(main())
