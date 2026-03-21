"""
富士通 iLis 系図書館スクレイパー
対応: 相模原市立図書館

このシステムはASP.NETでJavaScript動的生成があるためPlaywrightを使用します。

ログイン:
  URL: WwPortLogin.aspx
  フィールド: txtRiyoshaCD, txtPassWord, btnLogin (submit)
  成功後: WwPortTop.aspx

利用状況確認:
  ボタン: btnMyPort06 (利用状況確認)
  遷移先: WwJoukyou.aspx?KEY=...

貸出テーブル:  div#kas_list 内のテーブル (なければ0件)
予約テーブル:  table#dgdYoy
  列: [0]No [1]書名 [2]著者名 [3]出版者 [4]出版年 [5]分類
      [6]形態 [7]連絡日 [8]取置期限 [9]受取館 [10]予約順 [11]種別 [12]予約状況
"""
import re
from datetime import date, datetime

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from ..models import LoanItem, ReservationItem


class FujitsuIlisScraper:
    """富士通 iLis (WebiLis) 系スクレイパー (Playwright 使用)"""

    name: str = ""

    def __init__(self, base_url: str, card_number: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.card_number = card_number
        self.password = password
        self._playwright = None
        self._browser = None
        self._page: Page | None = None
        self._status_soup: BeautifulSoup | None = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    async def __aenter__(self) -> "FujitsuIlisScraper":
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
        await page.goto(self._url("/toshow/asp/WwPortLogin.aspx"))
        await page.fill('input[name="txtRiyoshaCD"]', self.card_number)
        await page.fill('input[name="txtPassWord"]', self.password)
        await page.click('input[name="btnLogin"]')
        try:
            await page.wait_for_url("**/WwPortTop.aspx", timeout=10000)
            return True
        except PlaywrightTimeout:
            return False

    async def _go_to_status_page(self) -> BeautifulSoup:
        if self._status_soup is not None:
            return self._status_soup
        page = self._page
        assert page is not None
        await page.goto(self._url("/toshow/asp/WwPortTop.aspx"))
        await page.wait_for_load_state("networkidle")
        await page.click('input[name="btnMyPort06"]')
        await page.wait_for_load_state("networkidle")
        self._status_soup = BeautifulSoup(await page.content(), "html.parser")
        return self._status_soup

    async def get_loans(self) -> list[LoanItem]:
        soup = await self._go_to_status_page()
        return _parse_ilis_loans(soup)

    async def get_reservations(self) -> list[ReservationItem]:
        soup = await self._go_to_status_page()
        return _parse_ilis_reservations(soup)

    async def enrich_authors(self, loans: list, reservations: list) -> None:
        pass

    async def logout(self) -> None:
        if self._page:
            try:
                await self._page.click('input[name="btnLogout"]', timeout=5000)
            except Exception:
                pass


def _parse_date_jp(text: str) -> date | None:
    """2026年03月19日 や 2026/03/19 などを date に変換"""
    text = text.strip()
    for fmt in ("%Y年%m月%d日", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_ilis_loans(soup: BeautifulSoup) -> list[LoanItem]:
    items: list[LoanItem] = []
    kas_div = soup.find("div", {"id": "kas_list"})
    if kas_div is None:
        return items
    # 貸出がある場合はテーブル(id=dgdKas等)が含まれる
    table = kas_div.find("table")
    if table is None:
        return items
    rows = table.find_all("tr")
    for tr in rows[1:]:  # ヘッダー行をスキップ
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        # 列構成は貸出テーブルに依存するため柔軟に対処
        # 書名: 書名を含むリンクテキストを探す
        title = ""
        for td in tds:
            a = td.find("a")
            if a:
                t = a.get_text(strip=True)
                if t and len(t) > 2:
                    title = t
                    break
        if not title:
            title = tds[1].get_text(strip=True) if len(tds) > 1 else ""
        author = tds[2].get_text(strip=True) if len(tds) > 2 else ""
        # 返却期限は "返却期限" か日付っぽい列を探す
        due_date: date | None = None
        for td in tds:
            txt = td.get_text(strip=True)
            m = re.search(r'(\d{4}年\d{2}月\d{2}日)', txt)
            if m:
                due_date = _parse_date_jp(m.group(1))
                break
        items.append(LoanItem(title=title, author=author, due_date=due_date))
    return items


def _parse_ilis_reservations(soup: BeautifulSoup) -> list[ReservationItem]:
    items: list[ReservationItem] = []
    table = soup.find("table", {"id": "dgdYoy"})
    if table is None:
        return items
    rows = table.find_all("tr")
    for tr in rows[1:]:  # ヘッダー行スキップ
        tds = tr.find_all("td")
        if len(tds) < 13:
            continue
        title = tds[1].get_text(strip=True)
        if not title:
            continue
        author = tds[2].get_text(strip=True)
        available_until_text = tds[8].get_text(strip=True)
        available_until = _parse_date_jp(available_until_text)
        pos_text = tds[10].get_text(strip=True)
        position: int | None = None
        if pos_text and pos_text != "－":
            m = re.search(r'(\d+)', pos_text)
            if m:
                position = int(m.group(1))
        kind = tds[11].get_text(strip=True)   # 種別: "予約", "順番予約"
        status = tds[12].get_text(strip=True)  # 予約状況: "取置済み", "返却待ち" など
        # 種別と状況を組み合わせてわかりやすく
        full_status = f"{kind}{status}" if kind else status
        items.append(ReservationItem(
            title=title,
            author=author,
            status=full_status,
            position=position,
            available_until=available_until,
        ))
    return items


class SagamiharaLibrary(FujitsuIlisScraper):
    name = "相模原市立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        super().__init__("https://www.lib.sagamihara.kanagawa.jp", card_number, password)
