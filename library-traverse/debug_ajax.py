"""横浜市立図書館のAJAXエンドポイントを探す"""
import asyncio
import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0", "Accept-Language": "ja"}
BASE = "https://opac.lib.city.yokohama.lg.jp"


async def main():
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as c:
        # ログイン
        r = await c.get(f"{BASE}/winj/opac/login.do", params={"lang": "ja"})
        soup = BeautifulSoup(r.text, "lxml")
        form = soup.find("form")
        data = {inp["name"]: inp.get("value", "") for inp in form.find_all("input") if inp.get("name")}
        data["txt_usercd"] = "9023109473"
        data["txt_password"] = "yokTk4dakb$"
        data["submit_btn_login"] = "ログイン"
        await c.post(urljoin(str(r.url), form.get("action", "")), data=data)

        r3 = await c.get(f"{BASE}/winj/opac/reserve-list.do", params={"lang": "ja"})
        soup3 = BeautifulSoup(r3.text, "html.parser")

        # JS内のURLを探す
        print("=== JS内の .do URL ===")
        for script in soup3.find_all("script"):
            txt = script.get_text()
            matches = re.findall(r'["\']([^"\']*\.do[^"\']*)["\']', txt)
            for m in set(matches):
                if "winj" in m or "opac" in m:
                    print("  ", m)

        # 外部JSファイルのリスト
        print("\n=== 外部JSファイル ===")
        for s in soup3.find_all("script", src=True):
            print("  ", s["src"])

        # FormのhiddenフィールドとPageFormの内容
        print("\n=== Forms ===")
        for f in soup3.find_all("form"):
            print("  action:", f.get("action"))
            for inp in f.find_all("input"):
                n, v = inp.get("name", ""), inp.get("value", "")
                if n:
                    print(f"    {inp.get('type','text'):10} {n:30} = {v[:50]!r}")

        # 予約リスト API を試す
        print("\n=== API エンドポイント試行 ===")
        for path in [
            "/winj/opac/reserve-list-content.do",
            "/winj/opac/my-reserve-list.do",
            "/winj/api/reserve-list",
        ]:
            try:
                r4 = await c.get(BASE + path, params={"lang": "ja"})
                print(f"  {path} -> {r4.status_code}")
            except Exception as e:
                print(f"  {path} -> ERROR: {e}")


asyncio.run(main())
