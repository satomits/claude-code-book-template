"""
--detail 機能のデバッグ: 詳細URL抽出 + 詳細ページ著者パース確認
川崎市立図書館 (httpx) と 秦野・伊勢原 (Playwright) を対象とする
"""
import asyncio
import yaml
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import httpx

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)["libraries"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

# ─── 川崎 (httpx) ────────────────────────────────────────────────────────────

async def debug_kawasaki():
    c = cfg.get("kawasaki", {})
    if not c:
        print("川崎: config なし")
        return
    base = "https://www.library.city.kawasaki.jp"
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        # login
        resp = await client.get(f"{base}/idcheck")
        soup = BeautifulSoup(resp.text, "lxml")
        form = next((f for f in soup.find_all("form") if "inputForm" in f.get("action", "")), None)
        if not form:
            print("川崎: ログインフォームが見つかりません")
            return
        data = {inp.get("name", ""): inp.get("value", "") for inp in form.find_all("input") if inp.get("name")}
        data["textUserId"] = str(c["card_number"])
        data["textPassword"] = str(c["password"])
        data["buttonLogin"] = "ログイン"
        from urllib.parse import urljoin
        action = urljoin(str(resp.url), form.get("action", ""))
        resp = await client.post(action, data=data)
        if "ログアウト" not in resp.text:
            print("川崎: ログイン失敗")
            return
        print("川崎: ログイン成功")

        # reservelist
        resp = await client.get(f"{base}/reservelist")
        soup = BeautifulSoup(resp.text, "lxml")
        cells = soup.find_all("div", {"class": "tablecell"})
        print(f"\n川崎 予約 tablecell 数: {len(cells)}")
        for i, cell in enumerate(cells[:2]):
            cover = cell.find("div", {"class": "cover"})
            print(f"\n  cell[{i}] cover HTML:\n{str(cover)[:500]}")
            if cover:
                a = cover.find("a")
                print(f"  → <a href>: {a['href'] if a and a.get('href') else '(なし)'}")
            item_div = cell.find("div", {"class": "item"})
            if item_div:
                print(f"  item HTML (先頭300字):\n  {str(item_div)[:300]}")


# ─── 秦野・伊勢原 (Playwright) ────────────────────────────────────────────────

async def debug_nec_saas(p, name, base_url, card, pwd):
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(locale="ja-JP")
    await page.goto(f"{base_url}/webopac/login.do")
    await page.fill('input[name="userno"]', str(card))
    await page.fill('input[name="passwd"]', str(pwd))
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle")
    if "ログアウト" not in await page.content():
        print(f"{name}: ログイン失敗")
        await browser.close()
        return

    # usermenu.do
    await page.goto(f"{base_url}/webopac/usermenu.do")
    try:
        await page.wait_for_function("!document.body.innerText.includes('Loading...')", timeout=15000)
    except PlaywrightTimeout:
        pass
    await page.wait_for_load_state("networkidle")

    # userlist.do?type=3 (予約)
    await page.goto(f"{base_url}/webopac/userlist.do?type=3&page=1")
    await page.wait_for_load_state("networkidle")
    soup = BeautifulSoup(await page.content(), "html.parser")

    table = soup.find("table", class_=lambda c: c and "searchListTbl" in " ".join(c))
    if table is None:
        table = soup.find("table")
    print(f"\n{name} userlist 予約 table: {'あり' if table else 'なし'}")
    if table:
        rows = table.find_all("tr")[1:3]
        for i, tr in enumerate(rows):
            title_td = tr.find("td", class_=lambda c: c and "tbl_long" in c)
            print(f"\n  row[{i}] tbl_long HTML:\n  {str(title_td)[:400] if title_td else '(なし)'}")
            # リンク確認
            if title_td:
                a = title_td.find("a")
                print(f"  → <a href>: {a['href'] if a and a.get('href') else '(なし)'}")

    # 貸出ページ (伊勢原は portal_lendlist.do)
    if "isehara" in base_url:
        await page.goto(f"{base_url}/webopac/portal_lendlist.do")
    else:
        # 秦野は usermenu.do の M_LENDLIST
        pass

    if "isehara" in base_url:
        await page.wait_for_load_state("networkidle")
        soup2 = BeautifulSoup(await page.content(), "html.parser")
        table2 = soup2.find("table")
        print(f"\n{name} 貸出 table: {'あり' if table2 else 'なし'}")
        if table2:
            rows2 = table2.find_all("tr")[1:3]
            for i, tr in enumerate(rows2):
                tds = tr.find_all("td")
                print(f"\n  lend row[{i}] tds数: {len(tds)}")
                for j, td in enumerate(tds[:4]):
                    a = td.find("a")
                    print(f"    td[{j}]: text={td.get_text(strip=True)[:30]!r}  href={a['href'] if a and a.get('href') else '(なし)'}")

    await browser.close()


async def main():
    # 川崎
    await debug_kawasaki()

    async with async_playwright() as p:
        c = cfg.get("hadano", {})
        if c:
            await debug_nec_saas(p, "秦野", "https://www.ip.licsre-saas.jp/hadano",
                                  c["card_number"], c["password"])
        c = cfg.get("isehara", {})
        if c:
            await debug_nec_saas(p, "伊勢原", "https://www.is.licsre-saas.jp/isehara",
                                  c["card_number"], c["password"])


asyncio.run(main())
