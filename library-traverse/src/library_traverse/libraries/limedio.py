"""
LIMEDIO (iLisfiera/リコー製) 系図書館スクレイパー
対応: 横浜市立図書館、神奈川県立図書館、厚木市立図書館

このシステムはデータをJavaScriptで動的レンダリングするため
Playwright (Chromium) を使用します。

ログインフォームフィールド:
  利用者CD: txt_usercd
  パスワード: txt_password
  送信ボタン: submit_btn_login

HTML構造:
  各アイテムは <div class="report"> の中にある
  タイトル: h4.link-image a span.title
  著者等:   div.column.info p:first-child
  状態/期限: div.column.info の後続 <p> や <div>
"""
import re
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from ..models import LoanItem, ReservationItem


class LimediasScraper:
    """LIMEDIO 系 OPAC スクレイパー (Playwright 使用)"""

    name: str = ""

    def __init__(self, base_url: str, card_number: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.card_number = card_number
        self.password = password
        self._playwright = None
        self._browser = None
        self._page: Page | None = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    async def __aenter__(self) -> "LimediasScraper":
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
        await page.goto(self._url("/winj/opac/login.do?lang=ja"))
        await page.fill('input[name="txt_usercd"]', self.card_number)
        await page.fill('input[name="txt_password"]', self.password)
        await page.click('input[name="submit_btn_login"]')
        try:
            await page.wait_for_selector('text=ログアウト', timeout=10000)
            return True
        except PlaywrightTimeout:
            return False

    async def _load_page(self, url: str) -> BeautifulSoup:
        """ページを読み込み、JavaScriptレンダリング完了後にHTMLを返す。"""
        page = self._page
        assert page is not None
        await page.goto(url)
        try:
            await page.wait_for_function(
                "!document.body.innerText.includes('Now Loading')",
                timeout=15000,
            )
        except PlaywrightTimeout:
            pass
        return BeautifulSoup(await page.content(), "html.parser")

    async def get_loans(self) -> list[LoanItem]:
        # LIMEDIO は lend-list.do から reserve-list.do にリダイレクトする（貸出があっても）
        # リダイレクト後のページには貸出と予約が混在するため、返却期限の有無で区別する
        soup = await self._load_page(self._url("/winj/opac/lend-list.do?lang=ja"))
        return _parse_limedio_loans(soup)

    async def get_reservations(self) -> list[ReservationItem]:
        soup = await self._load_page(self._url("/winj/opac/reserve-list.do?lang=ja"))
        return _parse_limedio_reservations(soup)

    async def enrich_authors(self, loans: list, reservations: list) -> None:
        pass

    async def logout(self) -> None:
        if self._page:
            try:
                await self._page.click('text=ログアウト', timeout=5000)
            except Exception:
                pass


def _clean(text: str) -> str:
    """HTML テキストの余分な空白・改行を除去する。"""
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\s*--\s*', '', text)
    return text


def _parse_date(text: str) -> date | None:
    # YYYY.MM.DD 形式にも対応
    text = text.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _extract_title(report: object) -> str:
    span = report.find("span", {"class": "title"})  # type: ignore[union-attr]
    if span:
        return _clean(span.get_text())
    return ""


def _extract_author(report: object) -> str:
    """div.column.info の最初の <p> から著者名を取得する。"""
    info = report.find("div", {"class": "info"})  # type: ignore[union-attr]
    if info is None:
        # class="column info" のdivを探す
        for d in report.find_all("div"):  # type: ignore[union-attr]
            classes = d.get("class", [])
            if "info" in classes:
                info = d
                break
    if info:
        p = info.find("p")
        if p:
            parts = [_clean(s) for s in p.get_text().split("--") if _clean(s)]
            return parts[0] if parts else ""
    return ""


_DUE_DATE_RE = re.compile(r'返却(?:期限日?|予定日)[：:]\s*([\d./年月日\-]+)')


def _parse_limedio_loans(soup: BeautifulSoup) -> list[LoanItem]:
    items: list[LoanItem] = []
    reports = soup.find_all("div", {"class": "report"})
    for report in reports:
        title = _extract_title(report)
        if not title:
            continue

        # 返却期限がないものは貸出アイテムではない（予約等）→ スキップ
        # reserve-list に混在する予約アイテムを除外するために必須
        full_text = report.get_text()
        m = _DUE_DATE_RE.search(full_text)
        if not m:
            continue

        author = _extract_author(report)
        due_date = _parse_date(m.group(1))
        items.append(LoanItem(title=title, author=author, due_date=due_date))
    return items


def _parse_limedio_reservations(soup: BeautifulSoup) -> list[ReservationItem]:
    items: list[ReservationItem] = []
    reports = soup.find_all("div", {"class": "report"})
    for report in reports:
        title = _extract_title(report)
        if not title:
            continue

        # 返却期限があるものは貸出アイテム（reserve-list混在分）→ スキップ
        if _DUE_DATE_RE.search(report.get_text()):
            continue

        author = _extract_author(report)

        status = ""
        position: int | None = None

        # 方法1: <div style="display: flex;"> 内の <p> から取得 (横浜・神奈川県立)
        flex_div = report.find("div", style=lambda s: s and "flex" in s)
        if flex_div:
            status_p = flex_div.find("p")
            if status_p:
                raw = status_p.get_text()
                parts = [p.strip() for p in raw.split() if p.strip()]
                if parts:
                    status = parts[0]
                m = re.search(r'(\d+)位', raw)
                if m:
                    position = int(m.group(1))

        # 方法2: span[class*="icon-"] から状態取得 (厚木)
        if not status:
            icon_span = report.find("span", class_=re.compile(r"^icon-"))
            if icon_span:
                status = icon_span.get_text(strip=True)

        # 順位: レポート全体の "X位" パターン
        if position is None:
            m = re.search(r'(\d+)位', report.get_text())
            if m:
                position = int(m.group(1))

        # 取置期限: div.column.info の3番目の<p>内の日付
        # (2番目の<p>には予約日が入るので除外)
        available_until: date | None = None
        info = report.find("div", {"class": "info"})
        if info:
            ps = info.find_all("p", recursive=False)
            # p[0]=著者情報, p[1]=予約日+受取館, p[2]=状態+取置期限
            target_ps = ps[2:] if len(ps) >= 3 else ps
        else:
            target_ps = []
        for p in target_ps:
            txt = p.get_text()
            m2 = re.search(r'取置期限[：:]\s*([\d./年月日]+)', txt)
            if m2:
                available_until = _parse_date(m2.group(1))
                break
            m3 = re.search(r'(\d{4}/\d{2}/\d{2})', txt)
            if m3:
                available_until = _parse_date(m3.group(1))
                break

        # 「予約棚」ステータスの日付は棚に置かれた日のため、取置期限は+7日
        if available_until is not None and "棚" in status:
            available_until = available_until + timedelta(days=7)

        items.append(ReservationItem(
            title=title,
            author=author,
            status=status,
            position=position,
            available_until=available_until,
        ))
    return items


class YokohamaLibrary(LimediasScraper):
    name = "横浜市立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        super().__init__("https://opac.lib.city.yokohama.lg.jp", card_number, password)


class KanagawaPrefLibrary(LimediasScraper):
    name = "神奈川県立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        super().__init__("https://www.klnet.pref.kanagawa.jp", card_number, password)


class AtsugiLibrary(LimediasScraper):
    name = "厚木市立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        super().__init__("https://www.lib.mytownclub.com", card_number, password)


class MachidaLibrary(LimediasScraper):
    name = "町田市立図書館"

    def __init__(self, card_number: str, password: str) -> None:
        super().__init__("https://opc.library-machida.tokyo.jp", card_number, password)
