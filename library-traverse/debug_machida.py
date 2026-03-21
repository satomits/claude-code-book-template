"""町田市立図書館 - OPAC URL調査"""
import asyncio
import httpx
from bs4 import BeautifulSoup

BASE = "https://www.library-machida.tokyo.jp"

CANDIDATES = [
    "/",
    "/opac/",
    "/licsxp-opac/",
    "/webopac/",
    "/mylibrary/",
    "/mypage/",
]


async def main():
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # トップページのリンクを確認
        print(f"=== TOP PAGE ===")
        resp = await client.get(BASE)
        print(f"Status: {resp.status_code}  URL: {resp.url}")
        soup = BeautifulSoup(resp.text, "html.parser")
        print("Links:")
        for a in soup.find_all("a", href=True):
            txt = a.get_text(strip=True)
            href = a["href"]
            if txt and any(k in txt or k in href.lower() for k in ["opac", "mypage", "マイページ", "蔵書", "検索", "login", "ログイン"]):
                print(f"  {txt!r} -> {href}")

        # 候補URLを試す
        print("\n=== Candidate URLs ===")
        for path in CANDIDATES:
            try:
                r = await client.get(f"{BASE}{path}", timeout=10)
                print(f"{path} -> {r.status_code} ({r.url})")
            except Exception as e:
                print(f"{path} -> ERROR: {e}")


asyncio.run(main())
