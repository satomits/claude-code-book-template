"""
海老名市立図書館スクレイパー (CCC/TRC 独自 Vue.js SPA)

ログイン:
  URL: /mypage/
  アコーディオン「貸出券をご利用の方」を開く → #username / #password 入力 → ボタンクリック
  ログイン完了: .p-mypage-login が hidden になり /mypage/menu/ へ遷移

貸出: /mypage/lending-status/
  ローディング: .vld-overlay.is-active が消えるまで待機
  各アイテム: li > div.p-mypage-book
    タイトル: h3.c-book-info-simple__title > a
    著者: dl内 dt「著者：」対応 dd
    日付テーブル: table.p-mypage-book-status → th「返却予定日」対応 td

予約: /mypage/reservation-list/
  同上ローディング待機
  日付テーブル: th「順番・状態」→状態/順位, th「取置期限」→取置期限日
"""
import re
from datetime import date, datetime

from bs4 import BeautifulSoup, NavigableString, Comment
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from ..models import LoanItem, ReservationItem

BASE_URL = "https://ebina.city-library.jp"


class EbinaLibrary:
    name = "海老名市立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        self.card_number = card_number
        self.password = password
        self._playwright = None
        self._browser = None
        self._page: Page | None = None

    async def __aenter__(self) -> "EbinaLibrary":
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
        await page.goto(f"{BASE_URL}/mypage/", timeout=60000)
        await page.wait_for_load_state("networkidle")
        # アコーディオンを開く
        await page.click('text=貸出券をご利用の方')
        await page.wait_for_selector('#username', state='visible', timeout=5000)
        await page.fill('#username', self.card_number)
        await page.fill('#password', self.password)
        # ログインボタンクリック
        btn = page.locator('.p-mypage-login__body button, .p-mypage-login__body input[type="submit"]').first
        if await btn.count() > 0:
            await btn.click()
        else:
            await page.locator('#password').press('Enter')
        # ログインフォームが消えたら成功
        try:
            await page.wait_for_selector('.p-mypage-login', state='hidden', timeout=15000)
            return True
        except PlaywrightTimeout:
            return False

    async def _load_page(self, path: str) -> BeautifulSoup:
        page = self._page
        assert page is not None
        await page.goto(f"{BASE_URL}{path}", timeout=30000)
        # Vue.js ローディングスピナーが消えるまで待つ
        try:
            await page.wait_for_function(
                "!document.querySelector('.vld-overlay.is-active')",
                timeout=20000,
            )
        except PlaywrightTimeout:
            pass
        return BeautifulSoup(await page.content(), "html.parser")

    async def get_loans(self) -> list[LoanItem]:
        soup = await self._load_page("/mypage/lending-status/")
        return _parse_loans(soup)

    async def get_reservations(self) -> list[ReservationItem]:
        soup = await self._load_page("/mypage/reservation-list/")
        return _parse_reservations(soup)

    async def enrich_authors(self, loans: list, reservations: list) -> None:
        pass

    async def logout(self) -> None:
        if self._page:
            try:
                await self._page.click('button.-logout', timeout=5000)
            except Exception:
                pass


def _parse_date(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _get_title(book_div: object) -> str:
    h3 = book_div.find("h3", class_="c-book-info-simple__title")  # type: ignore[union-attr]
    if h3:
        a = h3.find("a")
        if a:
            # span (叢書名等) を除いた最初のテキストノードのみ
            for child in a.children:
                if isinstance(child, NavigableString) and not isinstance(child, Comment):
                    text = child.strip()
                    if text:
                        return text
            return a.get_text(strip=True)
    return ""


def _get_author(book_div: object) -> str:
    dl = book_div.find("dl", class_="c-book-info-simple__def")  # type: ignore[union-attr]
    if dl:
        for item in dl.find_all("div", class_="c-book-info-simple__def-item"):
            dt = item.find("dt")
            dd = item.find("dd")
            if dt and dd and "著者" in dt.get_text():
                return dd.get_text(strip=True)
    return ""


def _get_status_table(book_div: object) -> dict[str, str]:
    """table.p-mypage-book-status の th→td マッピングを返す"""
    result: dict[str, str] = {}
    table = book_div.find("table", class_="p-mypage-book-status")  # type: ignore[union-attr]
    if table:
        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th and td:
                result[th.get_text(strip=True)] = td.get_text(strip=True)
    return result


def _parse_loans(soup: BeautifulSoup) -> list[LoanItem]:
    items: list[LoanItem] = []
    for book_div in soup.find_all("div", class_="p-mypage-book"):
        title = _get_title(book_div)
        if not title:
            continue
        author = _get_author(book_div)
        status_map = _get_status_table(book_div)
        due_text = status_map.get("返却予定日", "")
        items.append(LoanItem(title=title, author=author, due_date=_parse_date(due_text)))
    return items


def _parse_reservations(soup: BeautifulSoup) -> list[ReservationItem]:
    items: list[ReservationItem] = []
    for book_div in soup.find_all("div", class_="p-mypage-book"):
        title = _get_title(book_div)
        if not title:
            continue
        author = _get_author(book_div)
        status_map = _get_status_table(book_div)

        # 「予約状況」列から状態と順位を取得
        status_raw = status_map.get("予約状況", "") or status_map.get("順番・状態", "") or status_map.get("状態", "")
        status = status_raw
        position: int | None = None
        m = re.search(r"(\d+)番目", status_raw)
        if m:
            position = int(m.group(1))
        else:
            m2 = re.search(r"^(\d+)$", status_raw.strip())
            if m2:
                position = int(m2.group(1))

        available_text = status_map.get("取置期限", "")
        items.append(ReservationItem(
            title=title,
            author=author,
            status=status,
            position=position,
            available_until=_parse_date(available_text),
        ))
    return items
