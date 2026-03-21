"""秦野・伊勢原: search_detail リンクをクリックして詳細ページの著者フィールド確認"""
import asyncio
import yaml
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)["libraries"]


async def check(p, name, base_url, card, pwd):
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(locale="ja-JP")
    await page.goto(f"{base_url}/webopac/login.do")
    await page.fill('input[name="userno"]', str(card))
    await page.fill('input[name="passwd"]', str(pwd))
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle")

    # usermenu.do → session 確立
    await page.goto(f"{base_url}/webopac/usermenu.do")
    try:
        await page.wait_for_function("!document.body.innerText.includes('Loading...')", timeout=15000)
    except PlaywrightTimeout:
        pass
    await page.wait_for_load_state("networkidle")

    # userlist.do?type=3 に移動
    await page.goto(f"{base_url}/webopac/userlist.do?type=3&page=1")
    await page.wait_for_load_state("networkidle")

    # 最初の search_detail リンクから biblid を抽出
    import re
    hrefs = await page.eval_on_selector_all(
        'a[href^="javascript:search_detail"]',
        "els => els.map(e => e.getAttribute('href'))"
    )
    if not hrefs:
        print(f"{name}: search_detail リンクなし")
        await browser.close()
        return

    href = hrefs[0]
    m = re.search(r"search_detail\('(\d+)'\)", href)
    if not m:
        print(f"{name}: biblid 抽出失敗: {href}")
        await browser.close()
        return

    biblid = m.group(1)
    print(f"\n{name} biblid={biblid}, JS呼び出し中...")

    # JavaScript 関数を直接実行して遷移
    await page.evaluate(f"search_detail('{biblid}')")
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeout:
        pass
    try:
        await page.wait_for_function("!document.body.innerText.includes('Loading')", timeout=10000)
    except PlaywrightTimeout:
        pass

    print(f"  遷移後URL: {page.url}")
    soup = BeautifulSoup(await page.content(), "html.parser")

    # body テキスト先頭
    body_text = soup.get_text(" ", strip=True)[:800]
    print(f"\n  body text (先頭800字):\n  {body_text}")

    # th/td
    print(f"\n  全 th/td ペア (先頭15件):")
    count = 0
    for tr in soup.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if th and td:
            print(f"    {th.get_text(strip=True)!r:20s} → {td.get_text(strip=True)[:60]!r}")
            count += 1
            if count >= 15:
                break
    if count == 0:
        print("    (th/td なし)")

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
