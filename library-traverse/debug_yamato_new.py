"""大和市立図書館 新システム（2026年11月〜）の構造調査

公開リポジトリのActionsログに出力されるため、個人情報（カード番号・書名・氏名）は
一切出力しない。出力するのは URL / 要素の name・id・type / 表の見出しと行数だけ。
"""
import asyncio
import re
import sys
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

sys.path.insert(0, "src")
from library_traverse.config import load_config  # noqa: E402

TOP = "https://library.city.yamato.kanagawa.jp/licsxp-opac/WOpacMnuTopInitAction.do?WebLinkFlag=1"
KEYWORDS = ["ログイン", "ログアウト", "マイページ", "貸出", "予約", "利用", "返却", "照会", "状況"]


def short(url: str) -> str:
    u = urlsplit(url)
    return f"{u.netloc}{u.path}" + (f"?{u.query}" if u.query else "")


async def dump(page, label: str) -> None:
    print(f"\n----- {label} -----")
    print(f"URL: {short(page.url)}")
    print(f"title: {await page.title()}")
    print(f"frames: {[short(f.url) for f in page.frames]}")
    html = await page.content()
    print(f"has ログアウト: {'ログアウト' in html}")
    soup = BeautifulSoup(html, "html.parser")
    for i, form in enumerate(soup.find_all("form")):
        print(f"form[{i}] id={form.get('id')!r} name={form.get('name')!r} "
              f"action={form.get('action')!r} method={form.get('method')!r}")
        for inp in form.find_all(["input", "button", "select"]):
            t = inp.get("type", inp.name)
            val = inp.get("value", "") if t in ("submit", "button") else ""
            txt = inp.get_text(strip=True) if inp.name == "button" else ""
            print(f"   <{inp.name}> type={t!r} name={inp.get('name')!r} id={inp.get('id')!r} "
                  f"class={inp.get('class')!r} value={val!r} text={txt!r} onclick={inp.get('onclick')!r}")
    # form外のinput/button
    for inp in soup.find_all(["input", "button"]):
        if inp.find_parent("form") is None and inp.get("type") != "hidden":
            print(f"   (no form) <{inp.name}> type={inp.get('type')!r} name={inp.get('name')!r} "
                  f"id={inp.get('id')!r} text={inp.get_text(strip=True)[:20]!r} onclick={inp.get('onclick')!r}")
    for a in soup.find_all("a"):
        txt = a.get_text(strip=True)
        if txt and len(txt) < 30 and any(k in txt for k in KEYWORDS):
            print(f"   link {txt!r} href={a.get('href')!r} onclick={a.get('onclick')!r} id={a.get('id')!r}")
    for i, table in enumerate(soup.find_all("table")):
        rows = table.find_all("tr")
        heads = [th.get_text(" ", strip=True)[:15] for th in table.find_all("th")][:20]
        tdcounts = sorted({len(tr.find_all("td")) for tr in rows})
        print(f"table[{i}] id={table.get('id')!r} class={table.get('class')!r} rows={len(rows)} "
              f"td_per_row={tdcounts} th={heads}")
    # 表以外のリスト型（div/ul）で並んでいる可能性もあるので、class名の頻度を出す
    classes: dict[str, int] = {}
    for el in soup.find_all(class_=True):
        for c in el.get("class", []):
            classes[c] = classes.get(c, 0) + 1
    top = sorted(classes.items(), key=lambda x: -x[1])[:40]
    print(f"frequent classes: {top}")
    # 日付っぽい文字列の数（中身は出さない）
    n_dates = len(re.findall(r"20\d\d[/年.-]\d{1,2}[/月.-]\d{1,2}", soup.get_text()))
    print(f"date-like strings: {n_dates}")


async def main() -> None:
    creds = load_config()["yamato"]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="ja-JP")
        page = await ctx.new_page()
        page.set_default_timeout(30000)
        reqs: list[str] = []
        page.on("request", lambda r: reqs.append(f"{r.method} {urlsplit(r.url).path}")
                if "yamato" in r.url and r.resource_type in ("document", "xhr", "fetch") else None)

        await page.goto(TOP)
        await page.wait_for_load_state("networkidle")
        await dump(page, "TOP")

        # ログイン画面へ（リンク or ボタン）
        for sel in ["text=ログイン", "text=マイページ", "text=利用照会"]:
            loc = page.locator(sel).first
            if await loc.count():
                print(f"\n>> click {sel}")
                try:
                    await loc.click()
                    await page.wait_for_load_state("networkidle")
                    await dump(page, f"after click {sel}")
                except Exception as e:  # noqa: BLE001
                    print(f"   click failed: {type(e).__name__}")
                if await page.locator('input[type="password"]').count():
                    break

        pw = page.locator('input[type="password"]:visible').first
        if not await pw.count():
            print("\n!! visible password input not found")
        else:
            # パスワード欄の直前の可視テキスト入力を利用者番号欄とみなす
            user = page.locator('input[type="text"]:visible, input[type="tel"]:visible, input[type="number"]:visible, input:not([type]):visible')
            n = await user.count()
            print(f"\nvisible text inputs: {n}")
            for i in range(n):
                el = user.nth(i)
                print(f"   [{i}] name={await el.get_attribute('name')!r} id={await el.get_attribute('id')!r} "
                      f"placeholder={await el.get_attribute('placeholder')!r}")
            await user.last.fill(creds["card_number"]) if n else None
            await pw.fill(creds["password"])
            clicked = False
            for sel in ['button:has-text("ログイン"):visible', 'input[value="ログイン"]:visible',
                        'a:has-text("ログイン"):visible', '[type="submit"]:visible']:
                loc = page.locator(sel).first
                if await loc.count():
                    print(f">> login click {sel}")
                    await loc.click()
                    clicked = True
                    break
            if not clicked:
                await pw.press("Enter")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)
            await dump(page, "AFTER LOGIN")

            for label in ["貸出", "予約"]:
                loc = page.locator(f'a:has-text("{label}"):visible').first
                if await loc.count():
                    print(f"\n>> click link containing {label}: text={(await loc.inner_text())[:20]!r}")
                    try:
                        await loc.click()
                        await page.wait_for_load_state("networkidle")
                        await page.wait_for_timeout(1500)
                        await dump(page, f"PAGE {label}")
                        await page.go_back()
                        await page.wait_for_load_state("networkidle")
                    except Exception as e:  # noqa: BLE001
                        print(f"   failed: {type(e).__name__}")

        print("\n----- requests (document/xhr) -----")
        seen = set()
        for r in reqs:
            if r not in seen:
                seen.add(r)
                print(r)
        await browser.close()


asyncio.run(main())
