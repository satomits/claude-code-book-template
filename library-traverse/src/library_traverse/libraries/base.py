"""図書館スクレイパーの基底クラス"""
from abc import ABC, abstractmethod
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


class LibraryScraper(ABC):
    """スクレイパーの基底クラス。各図書館システムはこれを継承する。"""

    name: str = ""
    verify_ssl: bool = True

    def __init__(self, card_number: str, password: str) -> None:
        self.card_number = card_number
        self.password = password
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "LibraryScraper":
        self._client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=30.0,
            verify=self.verify_ssl,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use 'async with' context manager")
        return self._client

    def parse(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def resolve_url(self, current_url: str, action: str) -> str:
        """フォームの action 属性を絶対 URL に解決する。"""
        if not action or action == "(none)":
            return current_url
        if action.startswith("http"):
            return action
        return urljoin(str(current_url), action)

    @abstractmethod
    async def login(self) -> bool:
        """ログインする。成功すれば True を返す。"""

    @abstractmethod
    async def get_loans(self) -> list:
        """貸出中の資料一覧を返す。"""

    @abstractmethod
    async def get_reservations(self) -> list:
        """予約中の資料一覧を返す。"""

    async def enrich_authors(self, loans: list, reservations: list) -> None:
        """詳細ページから著者名を補完する（--detail 時のみ呼ばれる）。"""

    async def logout(self) -> None:
        """ログアウトする（省略可）。"""
