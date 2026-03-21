"""
NEC LiCS-Re for SaaS 系図書館スクレイパー
対応: 秦野市立図書館、伊勢原市立図書館

ログインフォームフィールド:
  利用者番号: userno
  パスワード: passwd
  ログインボタン: button[type="submit"]

usermenu.do のポータルページにAJAX読込で表示される:
  貸出状況: div#M_LENDLIST 内 table
    列: No, タイトル, 返却期限日
  予約状況: div#M_RESERVELIST 内 table
    列: No, タイトル, 状態, 取置期限日
"""
import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from ..models import LoanItem, ReservationItem


class NecLicsSaasScraper:
    """NEC LiCS-Re for SaaS 系スクレイパー (Playwright 使用)"""

    name: str = ""

    def __init__(self, base_url: str, card_number: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.card_number = card_number
        self.password = password
        self._playwright = None
        self._browser = None
        self._page: Page | None = None
        self._portal_soup: BeautifulSoup | None = None
        self._loan_detail_urls: list[str] = []
        self._res_detail_urls: list[str] = []

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    async def __aenter__(self) -> "NecLicsSaasScraper":
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
        await page.goto(self._url("/webopac/login.do"))
        await page.fill('input[name="userno"]', self.card_number)
        await page.fill('input[name="passwd"]', self.password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        return "ログアウト" in await page.content()

    async def _load_portal(self) -> BeautifulSoup:
        if self._portal_soup is not None:
            return self._portal_soup
        page = self._page
        assert page is not None
        await page.goto(self._url("/webopac/usermenu.do"))
        try:
            await page.wait_for_function(
                "!document.body.innerText.includes('Loading...')",
                timeout=15000,
            )
        except PlaywrightTimeout:
            pass
        self._portal_soup = BeautifulSoup(await page.content(), "html.parser")
        return self._portal_soup

    async def get_loans(self) -> list[LoanItem]:
        soup = await self._load_portal()
        items, urls = _parse_lend_table(soup, self.base_url)
        self._loan_detail_urls = urls
        return items

    async def get_reservations(self) -> list[ReservationItem]:
        soup = await self._load_portal()
        items, urls = _parse_reserve_table(soup, self.base_url)
        self._res_detail_urls = urls
        return items

    async def enrich_authors(self, loans: list, reservations: list) -> None:
        """予約の詳細ページから著者名を補完する。
        search_detail(biblid) を JS 評価して searchdetail.do に遷移し、著者を取得後に戻る。
        貸出ページにはリンクがないため貸出著者は取得できない。
        """
        biblids = [b for b in self._res_detail_urls if b and b.isdigit()]
        if not biblids:
            return
        page = self._page
        assert page is not None
        # search_detail() が定義されている予約一覧ページへ移動
        await page.goto(self._url("/webopac/userlist.do?type=3&page=1"))
        await page.wait_for_load_state("networkidle")

        for item, biblid in zip(reservations, self._res_detail_urls):
            if not biblid or not biblid.isdigit() or item.author:
                continue
            try:
                await page.evaluate(f"search_detail('{biblid}')")
                await page.wait_for_load_state("networkidle")
                soup = BeautifulSoup(await page.content(), "html.parser")
                item.author = _parse_author_from_searchdetail(soup)
                await page.go_back()
                await page.wait_for_load_state("networkidle")
            except Exception:
                # 失敗したら予約一覧に戻って続行
                try:
                    await page.goto(self._url("/webopac/userlist.do?type=3&page=1"))
                    await page.wait_for_load_state("networkidle")
                except Exception:
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


def _find_title_idx(tds: list) -> int:
    """行のtdリストからタイトルセル(空でも数字でもない最初のセル)のインデックスを返す。"""
    for i, td in enumerate(tds):
        txt = _cell(td)
        if txt and not txt.isdigit():
            return i
    return -1


def _cell_detail_url(td: object, base_url: str) -> str:
    """tdセル内の <a href> をそのまま返す。
    javascript:search_detail('biblid') 形式の場合は biblid のみ返す。
    """
    if td is None:
        return ""
    a = td.find("a")  # type: ignore[union-attr]
    if not a or not a.get("href"):
        return ""
    href = a["href"]
    m = re.search(r"search_detail\('(\d+)'\)", href)
    if m:
        return m.group(1)  # biblid だけ返す
    if href.startswith("javascript:"):
        return ""
    if href.startswith("http"):
        return href
    return f"{base_url}/{href.lstrip('/')}"


def _parse_lend_rows(table: object, base_url: str) -> tuple[list[LoanItem], list[str]]:
    """貸出テーブル (列: [icon?], No, タイトル, 返却期限日) をパースする。"""
    items: list[LoanItem] = []
    urls: list[str] = []
    for tr in table.find_all("tr")[1:]:  # type: ignore[union-attr]
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        title_idx = _find_title_idx(tds)
        if title_idx < 0:
            continue
        title = _cell(tds[title_idx])
        detail_url = _cell_detail_url(tds[title_idx], base_url)
        # 返却期限: タイトル列より後の日付パターン
        due_text = ""
        for td in tds[title_idx + 1:]:
            txt = _cell(td)
            if _parse_date(txt):
                due_text = txt
                break
        items.append(LoanItem(title=title, due_date=_parse_date(due_text)))
        urls.append(detail_url)
    return items, urls


def _parse_reserve_rows(table: object, base_url: str) -> tuple[list[ReservationItem], list[str]]:
    """予約テーブル (列: [icon?], No, タイトル, 状態, 取置期限日) をパースする。"""
    items: list[ReservationItem] = []
    urls: list[str] = []
    for tr in table.find_all("tr")[1:]:  # type: ignore[union-attr]
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        title_idx = _find_title_idx(tds)
        if title_idx < 0:
            continue
        title = _cell(tds[title_idx])
        detail_url = _cell_detail_url(tds[title_idx], base_url)
        status = _cell(tds[title_idx + 1]) if len(tds) > title_idx + 1 else ""
        available_text = _cell(tds[title_idx + 2]) if len(tds) > title_idx + 2 else ""
        position: int | None = None
        m = re.search(r"(\d+)番目", status)
        if m:
            position = int(m.group(1))
        items.append(ReservationItem(
            title=title,
            status=status,
            position=position,
            available_until=_parse_date(available_text),
        ))
        urls.append(detail_url)
    return items, urls


def _parse_lend_table(soup: BeautifulSoup, base_url: str) -> tuple[list[LoanItem], list[str]]:
    """div#M_LENDLIST 内のtableから貸出情報を取得する。"""
    lend_div = soup.find("div", {"id": "M_LENDLIST"})
    if lend_div is None:
        return [], []
    table = lend_div.find("table")
    if table is None:
        return [], []
    return _parse_lend_rows(table, base_url)


def _parse_reserve_table(soup: BeautifulSoup, base_url: str) -> tuple[list[ReservationItem], list[str]]:
    """div#M_RESERVELIST 内のtableから予約情報を取得する。"""
    rsv_div = soup.find("div", {"id": "M_RESERVELIST"})
    if rsv_div is None:
        return [], []
    table = rsv_div.find("table")
    if table is None:
        return [], []
    return _parse_reserve_rows(table, base_url)


def _parse_userlist_reservations(soup: BeautifulSoup, base_url: str) -> tuple[list[ReservationItem], list[str]]:
    """userlist.do?type=3 のテーブルから予約情報を取得する。
    各行から: タイトル(td.tbl_long or span.colprttil)、状態(td.colstatus)、
    予約順位(span.colrsvodr strong)、受取館(span.colutolcs)、取置期限(span.collimitdate)
    """
    items: list[ReservationItem] = []
    urls: list[str] = []
    # class="searchListTbl" を優先
    table = soup.find("table", class_=lambda c: c and "searchListTbl" in " ".join(c))
    if table is None:
        table = soup.find("table")
    if table is None:
        return items, urls

    for tr in table.find_all("tr")[1:]:  # type: ignore[union-attr]
        # タイトル: PC版(td.tbl_long)優先、なければSP版(span.colprttil)
        title = ""
        detail_url = ""
        title_td = tr.find("td", class_=lambda c: c and "tbl_long" in c)
        if title_td:
            strong = title_td.find("strong")
            if strong:
                title = strong.get_text(strip=True)
            detail_url = _cell_detail_url(title_td, base_url)
        if not title:
            title_span = tr.find("span", class_=lambda c: c and "colprttil" in c)
            if title_span:
                strong = title_span.find("strong")
                if strong:
                    title = strong.get_text(strip=True)
                if not detail_url:
                    a = title_span.find("a")
                    if a and a.get("href"):
                        href = a["href"]
                        detail_url = href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"
        if not title:
            continue

        status_td = tr.find("td", class_="colstatus")
        status = status_td.get_text(strip=True) if status_td else ""

        pos_span = tr.find("span", class_="colrsvodr")
        position: int | None = None
        if pos_span:
            strong = pos_span.find("strong")
            if strong:
                try:
                    position = int(strong.get_text(strip=True))
                except ValueError:
                    pass

        pickup_span = tr.find("span", class_="colutolcs")
        pickup_location = pickup_span.get_text(strip=True) if pickup_span else ""

        limit_span = tr.find("span", class_="collimitdate")
        available_until = _parse_date(limit_span.get_text(strip=True)) if limit_span else None

        items.append(ReservationItem(
            title=title,
            status=status,
            position=position,
            available_until=available_until,
            pickup_location=pickup_location,
        ))
        urls.append(detail_url)
    return items, urls


def _parse_author_from_searchdetail(soup: BeautifulSoup) -> str:
    """searchdetail.do ページの <th>著者</th><td>...</td> から著者名を抽出する。
    複数著者の場合は最初の著者のみ返す（例: '石井　力重／著加藤　昌治／監修' → '石井 力重'）。
    """
    for tr in soup.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if th and td and th.get_text(strip=True) == "著者":
            raw = td.get_text(strip=True)
            # "石井　力重／著加藤　昌治／監修" → "石井 力重"
            first = raw.split("／")[0].strip().replace("\u3000", " ")
            return first
    return ""


class HadanoLibrary(NecLicsSaasScraper):
    name = "秦野市立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        super().__init__("https://www.ip.licsre-saas.jp/hadano", card_number, password)

    async def get_reservations(self) -> list[ReservationItem]:
        await self._load_portal()  # usermenu.do 訪問 + Loading待機
        page = self._page
        assert page is not None
        await page.goto(self._url("/webopac/userlist.do?type=3&page=1"))
        await page.wait_for_load_state("networkidle")
        soup = BeautifulSoup(await page.content(), "html.parser")
        items, urls = _parse_userlist_reservations(soup, self.base_url)
        self._res_detail_urls = urls
        return items


class IseharaLibrary(NecLicsSaasScraper):
    """
    伊勢原市立図書館 (NEC LiCS-Re SaaS)

    ポータルにM_LENDLIST/M_RESERVELISTが存在しないため専用エンドポイントを使用。
      貸出: /webopac/portal_lendlist.do
      予約: /webopac/userlist.do?type=3 (順位・受取館含む)
    """
    name = "伊勢原市立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        super().__init__("https://www.is.licsre-saas.jp/isehara", card_number, password)

    async def _ensure_portal_visited(self) -> None:
        if self._portal_soup is not None:
            return
        page = self._page
        assert page is not None
        await page.goto(self._url("/webopac/usermenu.do"))
        await page.wait_for_load_state("networkidle")
        self._portal_soup = BeautifulSoup(await page.content(), "html.parser")

    async def get_loans(self) -> list[LoanItem]:
        await self._ensure_portal_visited()
        page = self._page
        assert page is not None
        await page.goto(self._url("/webopac/portal_lendlist.do"))
        await page.wait_for_load_state("networkidle")
        soup = BeautifulSoup(await page.content(), "html.parser")
        table = soup.find("table")
        if table is None:
            return []
        items, urls = _parse_lend_rows(table, self.base_url)
        self._loan_detail_urls = urls
        return items

    async def get_reservations(self) -> list[ReservationItem]:
        await self._ensure_portal_visited()
        page = self._page
        assert page is not None
        await page.goto(self._url("/webopac/userlist.do?type=3&page=1"))
        await page.wait_for_load_state("networkidle")
        soup = BeautifulSoup(await page.content(), "html.parser")
        items, urls = _parse_userlist_reservations(soup, self.base_url)
        self._res_detail_urls = urls
        return items
