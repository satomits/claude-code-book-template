"""秦野ログインボタン確認・大和貸出ページ"""
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import httpx

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0", "Accept-Language": "ja"}


async def check_licsre_login_form(name, base_url):
    """LiCS-Re ログインフォームのボタン確認"""
    print(f"\n=== {name} - ログインフォーム ===")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as c:
        r = await c.get(f"{base_url}/webopac/login.do")
        soup = BeautifulSoup(r.text, "lxml")
        form = soup.find("form")
        print("All inputs in form:")
        for inp in form.find_all("input"):
            print(f"  name={inp.get('name','')!r} type={inp.get('type','')!r} value={inp.get('value','')[:30]!r}")
        print("All buttons in form:")
        for btn in form.find_all("button"):
            print(f"  name={btn.get('name','')!r} type={btn.get('type','')!r} text={btn.get_text(strip=True)!r}")


async def check_licsre_playwright2(name, base_url, card, pwd):
    """NEC LiCS-Re SaaS - 正しいセレクタでPlaywright"""
    print(f"\n=== {name} - Playwright ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")

        await page.goto(f"{base_url}/webopac/login.do")
        # ページのすべてのフォーム要素を取得
        inputs = await page.query_selector_all("input")
        for inp in inputs:
            name_val = await inp.get_attribute("name") or ""
            type_val = await inp.get_attribute("type") or ""
            value_val = await inp.get_attribute("value") or ""
            print(f"  input name={name_val!r} type={type_val!r} value={value_val[:20]!r}")

        await page.fill('input[name="userno"]', card)
        await page.fill('input[name="passwd"]', pwd)

        # ログインボタンをクリック (type="image"かもしれない)
        try:
            await page.click('input[name="loginbtn"]', timeout=3000)
        except Exception:
            try:
                await page.click('input[name="submit"]', timeout=3000)
            except Exception:
                try:
                    await page.click('button[type="submit"]', timeout=3000)
                except Exception:
                    # Enterキーで送信
                    await page.keyboard.press("Enter")

        await page.wait_for_load_state("networkidle")
        print(f"  URL after login: {page.url}")
        print(f"  Has ログアウト: {'ログアウト' in await page.content()}")

        # usermenu.do
        await page.goto(f"{base_url}/webopac/usermenu.do")
        try:
            await page.wait_for_function(
                "!document.body.innerText.includes('Loading...')",
                timeout=15000
            )
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        soup = BeautifulSoup(await page.content(), "html.parser")
        lend_div = soup.find("div", {"id": "M_LENDLIST"})
        rsv_div = soup.find("div", {"id": "M_RESERVELIST"})
        print(f"\n  M_LENDLIST:\n{str(lend_div)[:600] if lend_div else 'Not found'}")
        print(f"\n  M_RESERVELIST:\n{str(rsv_div)[:600] if rsv_div else 'Not found'}")

        await browser.close()


async def check_yamato_lend2():
    """大和市立図書館 - 貸出ページ詳細"""
    print("\n=== 大和市立図書館 - 貸出・予約詳細 ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ja-JP")
        BASE = "https://library.city.yamato.kanagawa.jp"

        await page.goto(f"{BASE}/licsxp-opac/WOpacMnuTopInitAction.do?WebLinkFlag=1")
        await page.fill('input[name="username"]', "0193777422")
        await page.fill('input[name="j_password"]', "JH8OUX")
        await page.click('input[value="ログイン"]')
        await page.wait_for_load_state("networkidle")

        # 予約ページ確認 (すでにそこにいるはず)
        soup = BeautifulSoup(await page.content(), "html.parser")
        t = soup.find("table", {"id": "ItemDetaTable"})
        if t:
            rows = t.find_all("tr")
            print(f"\nReservation table ({len(rows)} rows):")
            if rows:
                # ヘッダ行
                ths = rows[0].find_all(["th", "td"])
                print("  Headers:", [th.get_text(strip=True) for th in ths])
            for row in rows[1:2]:
                tds = row.find_all("td")
                for i, td in enumerate(tds):
                    print(f"  td[{i}]: {td.get_text(strip=True)[:80]!r}")

        # 貸出ページ
        await page.goto(f"{BASE}/licsxp-opac/WOpacMnuTopToPwdLibraryAction.do?gamen=usrlend")
        await page.wait_for_load_state("networkidle")
        print(f"\nLoan page URL: {page.url}")
        print(f"Loan page title: {await page.title()}")
        soup2 = BeautifulSoup(await page.content(), "html.parser")
        t2 = soup2.find("table", {"id": "ItemDetaTable"})
        if t2:
            rows2 = t2.find_all("tr")
            print(f"Loan table ({len(rows2)} rows)")
            if rows2:
                ths = rows2[0].find_all(["th", "td"])
                print("  Headers:", [th.get_text(strip=True) for th in ths])

        await browser.close()


async def main():
    await check_licsre_login_form("秦野市立図書館", "https://www.ip.licsre-saas.jp/hadano")
    await check_licsre_playwright2("秦野市立図書館", "https://www.ip.licsre-saas.jp/hadano", "11607553", "JH8OUX")
    await check_licsre_playwright2("伊勢原市立図書館", "https://www.is.licsre-saas.jp/isehara", "0191452200", "iseJH8OUX")
    await check_yamato_lend2()


asyncio.run(main())
