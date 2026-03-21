"""
川崎市立図書館スクレイパー (Apache Wicket 独自系)

ログインフォームフィールド:
  利用者ID: textUserId
  パスワード: textPassword
  送信ボタン: buttonLogin
  フォーム action: ./login?1-1.-inputForm  (Wicket URL)

貸出ページ: /rentallist
  貸出なし: "貸出資料はありません"

予約ページ: /reservelist
  構造: div.tablecell > div.cover > img[alt=書名] + div.item > dl (dt/dd ペア)
  フィールド: 受取場所, 予約日, 予約状況, 順位, 連絡方法
"""
import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import LoanItem, ReservationItem
from .base import LibraryScraper

BASE_URL = "https://www.library.city.kawasaki.jp"


class KawasakiLibrary(LibraryScraper):
    name = "川崎市立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        super().__init__(card_number, password)
        self._loan_detail_urls: list[str] = []
        self._res_detail_urls: list[str] = []

    async def login(self) -> bool:
        # /idcheck は /login?1 にリダイレクトされる
        resp = await self.client.get(f"{BASE_URL}/idcheck")
        soup = self.parse(resp.text)

        # action に "inputForm" を含むものがログインフォーム
        login_form = None
        for form in soup.find_all("form"):
            action = form.get("action", "")
            if "inputForm" in action:
                login_form = form
                break

        if login_form is None:
            return False

        data: dict[str, str] = {}
        for inp in login_form.find_all("input"):
            name = inp.get("name", "")
            if name:
                data[name] = inp.get("value", "")

        data["textUserId"] = self.card_number
        data["textPassword"] = self.password
        data["buttonLogin"] = "ログイン"

        action = self.resolve_url(str(resp.url), login_form.get("action", ""))
        resp = await self.client.post(action, data=data)
        return "ログアウト" in resp.text or "logout" in resp.text.lower()

    async def get_loans(self) -> list[LoanItem]:
        resp = await self.client.get(f"{BASE_URL}/rentallist")
        soup = self.parse(resp.text)
        items, urls = _parse_loans(soup)
        self._loan_detail_urls = urls
        return items

    async def get_reservations(self) -> list[ReservationItem]:
        resp = await self.client.get(f"{BASE_URL}/reservelist")
        soup = self.parse(resp.text)
        items, urls = _parse_reservations(soup)
        self._res_detail_urls = urls
        return items

    async def enrich_authors(self, loans: list, reservations: list) -> None:
        for item, url in zip(loans, self._loan_detail_urls):
            if url and not item.author:
                try:
                    resp = await self.client.get(url)
                    item.author = _parse_author_from_detail(self.parse(resp.text))
                except Exception:
                    pass
        for item, url in zip(reservations, self._res_detail_urls):
            if url and not item.author:
                try:
                    resp = await self.client.get(url)
                    item.author = _parse_author_from_detail(self.parse(resp.text))
                except Exception:
                    pass


def _parse_date(text: str) -> date | None:
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _dl_map(item_div: object) -> dict[str, str]:
    """div.item 内の <dl><dt>キー</dt><dd>値</dd></dl> をdictに変換する。"""
    result: dict[str, str] = {}
    for dl in item_div.find_all("dl"):  # type: ignore[union-attr]
        dt = dl.find("dt")
        dd = dl.find("dd")
        if dt and dd:
            result[dt.get_text(strip=True)] = dd.get_text(strip=True)
    return result


def _cover_detail_url(cover: object) -> str:
    """div.cover の <a href> から詳細ページの絶対 URL を返す。"""
    a = cover.find("a")  # type: ignore[union-attr]
    if a and a.get("href"):
        return urljoin(BASE_URL, a["href"])
    return ""


def _parse_loans(soup: BeautifulSoup) -> tuple[list[LoanItem], list[str]]:
    items: list[LoanItem] = []
    urls: list[str] = []
    cells = soup.find_all("div", {"class": "tablecell"})
    for cell in cells:
        cover = cell.find("div", {"class": "cover"})
        if cover is None:
            continue
        img = cover.find("img")
        title = img["alt"] if img and img.get("alt") else ""
        if not title:
            continue
        detail_url = _cover_detail_url(cover)
        item_div = cell.find("div", {"class": "item"})
        fields = _dl_map(item_div) if item_div else {}
        author = (
            fields.get("著者") or fields.get("著者名") or
            fields.get("著者等") or fields.get("著者・編者") or ""
        )
        due_text = fields.get("返却期限", "") or fields.get("期限", "")
        if not due_text:
            for p in cell.find_all("p"):
                m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日|\d{4}/\d{1,2}/\d{1,2})', p.get_text())
                if m:
                    due_text = m.group(1)
                    break
        items.append(LoanItem(title=title, author=author, due_date=_parse_date(due_text)))
        urls.append(detail_url)
    return items, urls


def _parse_reservations(soup: BeautifulSoup) -> tuple[list[ReservationItem], list[str]]:
    items: list[ReservationItem] = []
    urls: list[str] = []
    cells = soup.find_all("div", {"class": "tablecell"})
    for cell in cells:
        cover = cell.find("div", {"class": "cover"})
        if cover is None:
            continue
        img = cover.find("img")
        title = img["alt"] if img and img.get("alt") else ""
        if not title:
            continue
        detail_url = _cover_detail_url(cover)

        item_div = cell.find("div", {"class": "item"})
        fields = _dl_map(item_div) if item_div else {}

        author = (
            fields.get("著者") or fields.get("著者名") or
            fields.get("著者等") or fields.get("著者・編者") or ""
        )
        status = fields.get("予約状況", "")
        pos_text = fields.get("順位", "")
        position: int | None = None
        if pos_text:
            m = re.search(r"(\d+)", pos_text)
            if m:
                position = int(m.group(1))

        available_until_text = fields.get("取置期限", "") or fields.get("期限", "")
        available_until = _parse_date(available_until_text)

        items.append(ReservationItem(
            title=title,
            author=author,
            status=status,
            position=position,
            available_until=available_until,
        ))
        urls.append(detail_url)
    return items, urls


def _parse_author_from_detail(soup: BeautifulSoup) -> str:
    """詳細ページの HTML から著者名を抽出する。"""
    # パターン1: <dl><dt>著者...</dt><dd>値</dd></dl>
    for dl in soup.find_all("dl"):
        dt = dl.find("dt")
        dd = dl.find("dd")
        if dt and dd and "著者" in dt.get_text():
            text = dd.get_text(strip=True)
            if text:
                return text
    # パターン2: <tr><th>著者...</th><td>値</td></tr>
    for tr in soup.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if th and td and "著者" in th.get_text():
            text = td.get_text(strip=True)
            if text:
                return text
    return ""
