"""
NEC LiCS-XP (LiCS-WebII) 系図書館スクレイパー
対応: 町田市立図書館、大和市立図書館

大和市のログインフォームフィールド (実測):
  利用者カード番号: username  (id="usrcardnumber")
  パスワード:      j_password (id="password")
  hidden: hash, gamenid, j_username, h_username
  ログインボタン: type="button" (JavaScript で submit)

大和市 ログイン後の予約ページ:
  URL: OpacLoginAction.do (ログイン後直接予約ページへリダイレクト)
  table#ItemDetaTable:
    ヘッダー行: No.(th), 資料名, 書誌種別, 受取館連絡方法, 予約日割当日, 順位, 予約状態, 取置期限, ...
    データ行:   th=行番号, td[0]=資料名+著者+出版者, td[4]=順位, td[5]=予約状態, td[6]=取置期限

大和市 貸出ページ:
  URL: WOpacMnuTopToPwdLibraryAction.do?gamen=usrlend
"""
import re
from datetime import date, datetime

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from ..models import LoanItem, ReservationItem
from .base import LibraryScraper


# ===== 町田市立 (httpx ベース) =====

class NecLicsXpScraper(LibraryScraper):
    """NEC LiCS-XP 系 OPAC スクレイパー (httpx ベース、町田市用)"""

    def __init__(self, base_url: str, card_number: str, password: str) -> None:
        super().__init__(card_number, password)
        self.base_url = base_url.rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    async def login(self) -> bool:
        top_url = self._url("licsxp-opac/WOpacMnuTopInitAction.do")
        resp = await self.client.get(top_url, params={"WebLinkFlag": "1"})
        soup = self.parse(resp.text)

        form = soup.find("form")
        if form is None:
            return False

        data: dict[str, str] = {}
        for inp in form.find_all("input"):
            name = inp.get("name", "")
            if name:
                data[name] = inp.get("value", "")

        data["username"] = self.card_number
        data["j_password"] = self.password

        action = form.get("action") or ""
        if not action:
            action = self._url("licsxp-opac/WOpacMnuTopInitAction.do")
        else:
            action = self.resolve_url(str(resp.url), action)

        resp = await self.client.post(action, data=data)
        return "ログアウト" in resp.text or "logout" in resp.text.lower()

    async def get_loans(self) -> list[LoanItem]:
        url = self._url("licsxp-opac/WOpacMnuBookListAction.do")
        resp = await self.client.get(url)
        soup = self.parse(resp.text)
        return _parse_lics_loans(soup)

    async def get_reservations(self) -> list[ReservationItem]:
        url = self._url("licsxp-opac/WOpacMnuYoyakuListAction.do")
        resp = await self.client.get(url)
        soup = self.parse(resp.text)
        return _parse_lics_reservations(soup)


class MachidaLibrary(NecLicsXpScraper):
    name = "町田市立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        super().__init__("https://www.library-machida.tokyo.jp", card_number, password)


# ===== 大和市立 (Playwright ベース) =====

BASE_YAMATO = "https://library.city.yamato.kanagawa.jp"


class YamatoLibrary:
    """大和市立図書館スクレイパー (Playwright 使用、JavaScriptログイン)"""

    name = "大和市立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        self.card_number = card_number
        self.password = password
        self._playwright = None
        self._browser = None
        self._page: Page | None = None

    async def __aenter__(self) -> "YamatoLibrary":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        context = await self._browser.new_context(
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await context.new_page()
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def login(self) -> bool:
        page = self._page
        assert page is not None
        await page.goto(f"{BASE_YAMATO}/licsxp-opac/WOpacMnuTopInitAction.do?WebLinkFlag=1")
        await page.fill('input[name="username"]', self.card_number)
        await page.fill('input[name="j_password"]', self.password)
        await page.click('input[value="ログイン"]')
        await page.wait_for_load_state("networkidle")
        return "ログアウト" in await page.content()

    async def get_loans(self) -> list[LoanItem]:
        page = self._page
        assert page is not None
        await page.goto(f"{BASE_YAMATO}/licsxp-opac/WOpacMnuTopToPwdLibraryAction.do?gamen=usrlend")
        await page.wait_for_load_state("networkidle")
        soup = BeautifulSoup(await page.content(), "html.parser")
        return _parse_yamato_loans(soup)

    async def get_reservations(self) -> list[ReservationItem]:
        page = self._page
        assert page is not None
        # ログイン直後にすでに予約ページにいるが、念のため直接ナビゲート
        await page.goto(f"{BASE_YAMATO}/licsxp-opac/WOpacMnuTopToPwdLibraryAction.do?gamen=usrrsv")
        await page.wait_for_load_state("networkidle")
        soup = BeautifulSoup(await page.content(), "html.parser")
        return _parse_yamato_reservations(soup)

    async def enrich_authors(self, loans: list, reservations: list) -> None:
        pass

    async def logout(self) -> None:
        if self._page:
            try:
                await self._page.click('text=ログアウト', timeout=5000)
            except Exception:
                pass


def _parse_date(text: str) -> date | None:
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _cell(td: object) -> str:
    return td.get_text(strip=True) if td else ""  # type: ignore[union-attr]


def _split_yamato_resource(text: str) -> tuple[str, str]:
    """
    大和市の資料名フィールド (td[0]) を書名と著者名に分割する。
    形式: "書名　サブタイトル　著者名／著　出版者" (全角スペース区切り)
    """
    parts = text.split("\u3000")  # 全角スペースで分割
    title = parts[0] if parts else text
    author = ""
    for part in parts[1:]:
        if "著" in part or "編" in part or "訳" in part:
            author = re.sub(r"[／/][著編訳].*$", "", part).strip()
            break
    return title, author


def _parse_yamato_reservations(soup: BeautifulSoup) -> list[ReservationItem]:
    """table#ItemDetaTable から予約情報を取得する。"""
    items: list[ReservationItem] = []
    table = soup.find("table", {"id": "ItemDetaTable"})
    if table is None:
        return items
    rows = table.find_all("tr")
    for tr in rows[1:]:  # ヘッダー行スキップ
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        # ヘッダー列(th)が No. で、td[0] から資料名
        resource = _cell(tds[0])
        if not resource:
            continue
        title, author = _split_yamato_resource(resource)
        pos_text = _cell(tds[4]) if len(tds) > 4 else ""
        status = _cell(tds[5]) if len(tds) > 5 else ""
        available_text = _cell(tds[6]) if len(tds) > 6 else ""
        position: int | None = None
        if pos_text and pos_text not in ("ー", "-", ""):
            m = re.search(r"(\d+)", pos_text)
            if m:
                position = int(m.group(1))
        items.append(ReservationItem(
            title=title,
            author=author,
            status=status,
            position=position,
            available_until=_parse_date(available_text),
        ))
    return items


def _parse_yamato_loans(soup: BeautifulSoup) -> list[LoanItem]:
    """貸出テーブルから貸出情報を取得する。"""
    items: list[LoanItem] = []
    table = (
        soup.find("table", {"id": "ItemDetaTable"})
        or soup.find("table", {"class": "list"})
    )
    if table is None:
        return items
    rows = table.find_all("tr")
    # ヘッダー行から返却期日の列を特定する
    due_col: int | None = None
    if rows:
        headers = [th.get_text(strip=True) for th in rows[0].find_all("th")]
        for idx, h in enumerate(headers):
            if "返却" in h:
                # th の No. 列は th なので td のインデックスは 1 つずれる
                due_col = idx - 1
                break
    for tr in rows[1:]:  # ヘッダー行スキップ
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        resource = _cell(tds[0])
        if not resource:
            continue
        title, author = _split_yamato_resource(resource)
        due_date: date | None = None
        if due_col is not None and due_col < len(tds):
            due_date = _parse_date(_cell(tds[due_col]))
        if due_date is None:
            # フォールバック: 2番目の日付を返却期日として使う
            dates_found = 0
            for td in tds[1:]:
                d = _parse_date(_cell(td))
                if d:
                    dates_found += 1
                    if dates_found == 2:
                        due_date = d
                        break
            # 日付が1つしかなければそれを使う
            if due_date is None and dates_found == 0:
                for td in tds[1:]:
                    d = _parse_date(_cell(td))
                    if d:
                        due_date = d
                        break
        items.append(LoanItem(title=title, author=author, due_date=due_date))
    return items


# ===== 旧 httpx ベース用パーサ (町田市用) =====

def _parse_lics_loans(soup: object) -> list[LoanItem]:
    items: list[LoanItem] = []
    table = (
        soup.find("table", {"class": re.compile(r"list", re.I)})  # type: ignore[union-attr]
        or soup.find("table", {"summary": re.compile(r"貸出", re.I)})
        or soup.find("table")
    )
    if table is None:
        return items
    for tr in table.find_all("tr")[1:]:  # type: ignore[union-attr]
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        title = _cell(tds[0])
        if not title:
            continue
        author = _cell(tds[1]) if len(tds) > 1 else ""
        due_text = _cell(tds[2]) if len(tds) > 2 else ""
        renewable = tr.find("input", {"type": re.compile(r"checkbox|submit", re.I)}) is not None
        items.append(LoanItem(title=title, author=author, due_date=_parse_date(due_text), is_renewable=renewable))
    return items


def _parse_lics_reservations(soup: object) -> list[ReservationItem]:
    items: list[ReservationItem] = []
    table = (
        soup.find("table", {"class": re.compile(r"list", re.I)})  # type: ignore[union-attr]
        or soup.find("table", {"summary": re.compile(r"予約", re.I)})
        or soup.find("table")
    )
    if table is None:
        return items
    for tr in table.find_all("tr")[1:]:  # type: ignore[union-attr]
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        title = _cell(tds[0])
        if not title:
            continue
        author = _cell(tds[1]) if len(tds) > 1 else ""
        status = _cell(tds[2]) if len(tds) > 2 else ""
        pos_text = _cell(tds[3]) if len(tds) > 3 else ""
        position: int | None = None
        m = re.search(r"(\d+)", pos_text)
        if m:
            position = int(m.group(1))
        items.append(ReservationItem(title=title, author=author, status=status, position=position))
    return items
