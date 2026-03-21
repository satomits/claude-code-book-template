"""メインエントリーポイント"""
import sys
from pathlib import Path

import anyio

from .config import load_config
from .display import console, print_results, print_summary
from .libraries import LIBRARY_REGISTRY
from .models import LibraryResult
from .ndl import enrich_authors_via_ndl


async def fetch_library(lib_id: str, creds: dict[str, str], detail: bool = False) -> LibraryResult:
    """1図書館のデータを取得する。エラーは LibraryResult.error に格納。"""
    scraper_cls = LIBRARY_REGISTRY.get(lib_id)
    if scraper_cls is None:
        return LibraryResult(
            library_id=lib_id,
            library_name=lib_id,
            error=f"未対応の図書館ID: {lib_id}",
        )

    scraper = scraper_cls(**creds)
    result = LibraryResult(library_id=lib_id, library_name=scraper.name)

    try:
        async with scraper:
            logged_in = await scraper.login()
            if not logged_in:
                result.error = "ログイン失敗（カード番号またはパスワードを確認してください）"
                return result

            result.loans = await scraper.get_loans()
            result.reservations = await scraper.get_reservations()
            await scraper.logout()
    except Exception as e:  # noqa: BLE001
        result.error = str(e) or repr(e)

    return result


async def main_async(config_path: Path | None = None, detail: bool = False) -> list[LibraryResult]:
    try:
        libraries = load_config(config_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if not libraries:
        console.print(
            "[yellow]有効な図書館設定がありません。"
            "config.yaml でいずれかの図書館のコメントを外し、"
            "カード番号とパスワードを設定してください。[/yellow]"
        )
        sys.exit(1)

    console.print(f"[bold]{len(libraries)} 館のデータを取得中...[/bold]")

    results: list[LibraryResult] = []

    # 並列取得
    async with anyio.create_task_group() as tg:
        result_slots: dict[str, LibraryResult | None] = {lib_id: None for lib_id in libraries}

        async def _fetch(lib_id: str, creds: dict[str, str]) -> None:
            result_slots[lib_id] = await fetch_library(lib_id, creds, detail)

        for lib_id, creds in libraries.items():
            tg.start_soon(_fetch, lib_id, creds)

    results = [result_slots[lib_id] for lib_id in libraries if result_slots[lib_id] is not None]  # type: ignore[misc]

    if detail:
        console.print("[bold]NDL APIで著者名を補完中...[/bold]")
        all_items = [
            item
            for r in results
            for item in (*r.loans, *r.reservations)
        ]
        await enrich_authors_via_ndl(all_items)

    print_results(results)
    print_summary(results)
    return results


async def save_as_pdf(results: list[LibraryResult], path: Path) -> None:
    """CSS テーブル形式の HTML を生成して PDF に変換する (Playwright 使用)。"""
    from .pdf_export import generate_pdf_html
    from playwright.async_api import async_playwright
    html = generate_pdf_html(results)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html, wait_until="networkidle")
        await page.pdf(path=str(path), format="A4", print_background=True)
        await browser.close()


def run() -> None:
    """CLI エントリーポイント"""
    # Windows では Playwright のサブプロセス通信に ProactorEventLoop が必要
    if sys.platform == "win32":
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    args = sys.argv[1:]
    pdf_path: Path | None = None
    config_path: Path | None = None
    detail = False

    i = 0
    while i < len(args):
        if args[i] == "--pdf":
            i += 1
            pdf_path = Path(args[i] if i < len(args) else "library_status.pdf")
        elif args[i] == "--detail":
            detail = True
        else:
            config_path = Path(args[i])
        i += 1

    results = anyio.run(main_async, config_path, detail)

    if pdf_path is not None and results:
        anyio.run(save_as_pdf, results, pdf_path)
        print(f"PDF saved: {pdf_path}")


if __name__ == "__main__":
    run()
