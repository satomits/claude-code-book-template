"""各図書館のログインフォームを調査するデバッグスクリプト"""
import asyncio
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9",
}

LIBRARIES = {
    "sagamihara": "https://www.lib.sagamihara.kanagawa.jp/toshow/asp/WwPortLogin.aspx",
    "kawasaki":   "https://www.library.city.kawasaki.jp/idcheck",
    "yokohama":   "https://opac.lib.city.yokohama.lg.jp/winj/opac/login.do?lang=ja",
    "kanagawa_pref": "https://www.klnet.pref.kanagawa.jp/winj/opac/login.do?lang=ja",
    "machida":    "https://www.library.city.machida.tokyo.jp/licsxp-opac/WOpacMnuTopInitAction.do?WebLinkFlag=1",
    "ebina":      "https://ebina.city-library.jp/mypage/login",
    "hadano":     "https://www.ip.licsre-saas.jp/hadano/webopac/login.do",
    "yamato":     "https://library.city.yamato.kanagawa.jp/licsxp-opac/WOpacMnuTopInitAction.do?WebLinkFlag=1",
    "isehara":    "https://www.is.licsre-saas.jp/isehara/webopac/login.do",
    "atsugi":     "https://www.lib.mytownclub.com/winj/opac/login.do?lang=ja",
}

async def inspect_form(name: str, url: str):
    print(f"\n{'='*60}")
    print(f"[{name}] {url}")
    try:
        async with httpx.AsyncClient(
            headers=HEADERS,
            follow_redirects=True,
            timeout=20.0,
            verify=False,
        ) as client:
            resp = await client.get(url)
            print(f"  Status: {resp.status_code}  Final URL: {resp.url}")
            soup = BeautifulSoup(resp.text, "lxml")

            forms = soup.find_all("form")
            print(f"  Forms found: {len(forms)}")

            for i, form in enumerate(forms):
                print(f"  Form[{i}] action={form.get('action','(none)')} method={form.get('method','get')}")
                inputs = form.find_all("input")
                for inp in inputs:
                    t = inp.get("type","text")
                    n = inp.get("name","")
                    v = inp.get("value","")
                    iid = inp.get("id","")
                    if t == "hidden" and len(v) > 40:
                        v = v[:40] + "..."
                    print(f"    <input type={t!r:12} name={n!r:30} id={iid!r:30} value={v!r}")

                # select要素も確認
                for sel in form.find_all("select"):
                    print(f"    <select name={sel.get('name','')!r} id={sel.get('id','')!r}>")
    except Exception as e:
        print(f"  ERROR: {e}")

async def main():
    import sys
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(LIBRARIES.keys())
    for name in targets:
        if name in LIBRARIES:
            await inspect_form(name, LIBRARIES[name])

if __name__ == "__main__":
    asyncio.run(main())
