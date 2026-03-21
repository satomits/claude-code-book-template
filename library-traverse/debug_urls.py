"""ログイン後の正しいURLを各館から探す"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import httpx
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0", "Accept-Language": "ja"}


def find_nav_links(soup, keywords=("貸出", "予約", "利用", "マイ", "返却")):
    for a in soup.find_all("a", href=True):
        txt = a.get_text(strip=True)
        href = a["href"]
        if any(k in txt for k in keywords) and href not in ("#", "javascript:void(0)"):
            print(f"    {txt!r:30} -> {href}")


async def check_kawasaki_logged_in():
    print("\n=== 川崎市立図書館 ===")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as c:
        r = await c.get("https://www.library.city.kawasaki.jp/idcheck")
        soup = BeautifulSoup(r.text, "lxml")
        login_form = next((f for f in soup.find_all("form") if "inputForm" in f.get("action", "")), None)
        data = {inp["name"]: inp.get("value", "") for inp in login_form.find_all("input") if inp.get("name")}
        data["textUserId"] = "190001690055"
        data["textPassword"] = "32693269"
        data["buttonLogin"] = "ログイン"
        action = urljoin(str(r.url), login_form.get("action", ""))
        r2 = await c.post(action, data=data)
        soup2 = BeautifulSoup(r2.text, "lxml")
        print(f"  URL: {r2.url}")
        find_nav_links(soup2)
        # すべてのリンクを表示
        print("  All links:")
        for a in soup2.find_all("a", href=True):
            txt = a.get_text(strip=True)
            href = a["href"]
            if txt and "javascript" not in href and "#" not in href:
                print(f"    {txt!r:30} -> {href}")


async def check_nec_lics_saas_links(name, base_url, card, pwd):
    print(f"\n=== {name} ===")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as c:
        r = await c.get(f"{base_url}/webopac/login.do")
        soup = BeautifulSoup(r.text, "lxml")
        form = soup.find("form")
        data = {inp["name"]: inp.get("value", "") for inp in form.find_all("input") if inp.get("name")}
        data["userno"] = card
        data["passwd"] = pwd
        action = urljoin(str(r.url), form.get("action", "login.do"))
        r2 = await c.post(action, data=data)
        soup2 = BeautifulSoup(r2.text, "lxml")
        print(f"  URL after login: {r2.url}")
        print(f"  Title: {soup2.find('title').get_text()[:50] if soup2.find('title') else '?'}")
        find_nav_links(soup2)

        # リダイレクト先を確認
        top_url = base_url + "/webopac/index.do"
        r3 = await c.get(top_url)
        soup3 = BeautifulSoup(r3.text, "lxml")
        print(f"  Index page: {r3.status_code} {soup3.find('title').get_text()[:40] if soup3.find('title') else '?'}")
        find_nav_links(soup3)

        # 全リンク探索
        for path in ["/webopac/", "/webopac/top.do", "/webopac/menu.do", "/webopac/mypage.do",
                     "/webopac/userinfo.do", "/webopac/user/top.do"]:
            r4 = await c.get(base_url + path)
            if r4.status_code == 200 and len(r4.text) > 100:
                soup4 = BeautifulSoup(r4.text, "lxml")
                title4 = soup4.find("title")
                print(f"  {path} -> {r4.status_code} | {title4.get_text()[:40] if title4 else '?'}")
                if "ログアウト" in r4.text:
                    find_nav_links(soup4)


async def check_yamato_links():
    print("\n=== 大和市立図書館 ===")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as c:
        base_url = "https://library.city.yamato.kanagawa.jp"
        r = await c.get(f"{base_url}/licsxp-opac/WOpacMnuTopInitAction.do?WebLinkFlag=1")
        soup = BeautifulSoup(r.text, "lxml")
        form = soup.find("form")
        data = {inp["name"]: inp.get("value", "") for inp in form.find_all("input") if inp.get("name")}
        data["username"] = "0193777422"
        data["j_password"] = "JH8OUX"
        action = urljoin(str(r.url), form.get("action", "") or f"{base_url}/licsxp-opac/WOpacMnuTopInitAction.do")
        r2 = await c.post(action, data=data)
        soup2 = BeautifulSoup(r2.text, "lxml")
        print(f"  URL after login: {r2.url}")
        print(f"  Title: {soup2.find('title').get_text()[:50] if soup2.find('title') else '?'}")
        find_nav_links(soup2, ("貸出", "予約", "利用状況", "マイ", "返却", "Riy", "Yoy"))
        print("  All .do links:")
        for a in soup2.find_all("a", href=True):
            if ".do" in a["href"] or ".aspx" in a["href"]:
                print(f"    {a.get_text(strip=True)!r:25} -> {a['href']}")
        # ボタン
        for btn in soup2.find_all("input", {"type": ["submit", "button"]}):
            name = btn.get("name", "")
            val = btn.get("value", "")
            if any(k in val for k in ["貸出", "予約", "利用", "返却"]):
                print(f"  Button: {val!r} name={name!r}")


async def check_atsugi_report_html():
    print("\n=== 厚木市立図書館 - report HTML詳細 ===")
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
        reports = soup.find_all("div", {"class": "report"})
        print(f"  Reports: {len(reports)}")
        if reports:
            print("\n  First report full HTML:")
            print(str(reports[0])[:3000])
        await browser.close()


async def main():
    await check_kawasaki_logged_in()
    await check_nec_lics_saas_links("秦野市立図書館", "https://www.ip.licsre-saas.jp/hadano", "11607553", "JH8OUX")
    await check_nec_lics_saas_links("伊勢原市立図書館", "https://www.is.licsre-saas.jp/isehara", "0191452200", "iseJH8OUX")
    await check_yamato_links()
    await check_atsugi_report_html()


asyncio.run(main())
