"""秦野・伊勢原 - userlist.do?type=3 のHTML詳細確認"""
import asyncio
import yaml
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)["libraries"]


async def check(p, name, base, card, pwd):
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(locale="ja-JP")
    await page.goto(f"{base}/webopac/login.do")
    await page.fill('input[name="userno"]', str(card))
    await page.fill('input[name="passwd"]', str(pwd))
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle")

    # usermenu.do を先に訪問（セッション確立）
    await page.goto(f"{base}/webopac/usermenu.do")
    try:
        await page.wait_for_function(
            "!document.body.innerText.includes('Loading...')", timeout=15000)
    except PlaywrightTimeout:
        pass
    await page.wait_for_load_state("networkidle")

    await page.goto(f"{base}/webopac/userlist.do?type=3&page=1")
    await page.wait_for_load_state("networkidle")

    soup = BeautifulSoup(await page.content(), "html.parser")
    print(f"\n{'='*60}\n{name} userlist.do?type=3")

    tables = soup.find_all("table")
    for ti, table in enumerate(tables):
        header = table.find("tr")
        if not header:
            continue
        ths = header.find_all(["th", "td"])
        col_names = [th.get_text(strip=True) for th in ths]
        if not any(k in " ".join(col_names) for k in ["タイトル", "状態"]):
            continue
        print(f"\nTable[{ti}] cols ({len(ths)}): {col_names}")
        for i, tr in enumerate(table.find_all("tr")[1:4]):
            tds = tr.find_all("td")
            if not tds:
                continue
            print(f"\n  Row[{i}] HTML:")
            print(str(tr)[:2000])

    await browser.close()


async def main():
    async with async_playwright() as p:
        c = cfg.get("hadano", {})
        if c:
            await check(p, "秦野", "https://www.ip.licsre-saas.jp/hadano",
                       c["card_number"], c["password"])
        c = cfg.get("isehara", {})
        if c:
            await check(p, "伊勢原", "https://www.is.licsre-saas.jp/isehara",
                       c["card_number"], c["password"])


asyncio.run(main())
