"""横浜貸出ページの構造を解析"""
import asyncio
import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0", "Accept-Language": "ja"}
BASE = "https://opac.lib.city.yokohama.lg.jp"


async def main():
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as c:
        r = await c.get(f"{BASE}/winj/opac/login.do", params={"lang": "ja"})
        soup = BeautifulSoup(r.text, "lxml")
        form = soup.find("form")
        data = {inp["name"]: inp.get("value", "") for inp in form.find_all("input") if inp.get("name")}
        data["txt_usercd"] = "9023109473"
        data["txt_password"] = "yokTk4dakb$"
        data["submit_btn_login"] = "ログイン"
        await c.post(urljoin(str(r.url), form.get("action", "")), data=data)

        r3 = await c.get(f"{BASE}/winj/opac/lend-list.do", params={"lang": "ja"})

        # iframeを探す
        soup3 = BeautifulSoup(r3.text, "html.parser")
        for iframe in soup3.find_all("iframe"):
            print("iframe:", iframe.attrs)

        # data-url等の属性
        for elem in soup3.find_all(True):
            for k, v in elem.attrs.items():
                if ("data-" in k or "url" in k.lower()) and isinstance(v, str) and ".do" in v:
                    print(f"{elem.name}[{k}]={v}")

        # 生HTMLでパターン検索
        iframes_raw = re.findall(r'iframe[^>]*src=["\']([^"\']+)["\']', r3.text, re.I)
        print("Raw iframes:", iframes_raw)

        data_urls = re.findall(r'data-(?:url|src|href|content)=["\']([^"\']+)["\']', r3.text, re.I)
        print("Data URLs:", data_urls)

        # HTMLの「content」要素
        content_div = soup3.find("div", {"id": re.compile(r"content|main|body", re.I)})
        if content_div:
            print("Content div:", content_div.get_text()[:200])

        # reserveページのhid_session取得
        r4 = await c.get(f"{BASE}/winj/opac/reserve-list.do", params={"lang": "ja"})
        soup4 = BeautifulSoup(r4.text, "html.parser")
        hid_form = soup4.find("form", {"action": re.compile(r"reserve")})
        if hid_form:
            session = hid_form.find("input", {"name": "hid_session"})
            if session:
                print("hid_session:", session.get("value", "")[:20])
                # セッションを使ってAJAXリクエストを試みる
                sess_val = session.get("value", "")
                for path in [
                    "/winj/opac/reserve-list-detail.do",
                    f"/winj/opac/reserve-list.do?hid_session={sess_val}",
                ]:
                    try:
                        r5 = await c.post(
                            BASE + path.split("?")[0],
                            data={"hid_session": sess_val, "lang": "ja"},
                            headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
                        )
                        print(f"AJAX {path.split('?')[0]} -> {r5.status_code}")
                        soup5 = BeautifulSoup(r5.text, "html.parser")
                        print("  Tables:", len(soup5.find_all("table")))
                        title = soup5.find("title")
                        print("  Title:", title.get_text() if title else "?")
                        print("  Text:", soup5.get_text()[:200])
                    except Exception as e:
                        print(f"  {path}: {e}")


asyncio.run(main())
