"""rich を使った表示モジュール"""
from datetime import date

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from .models import LibraryResult, LoanItem, ReservationItem

console = Console(record=True)


def _due_style(item: LoanItem) -> str:
    if item.due_date is None:
        return "dim"
    if item.overdue():
        return "bold red"
    days_left = (item.due_date - date.today()).days
    if days_left <= 3:
        return "yellow"
    return "green"


def print_results(results: list[LibraryResult]) -> None:
    if not results:
        console.print("[yellow]設定された図書館がありません。config.yaml を確認してください。[/yellow]")
        return

    for result in results:
        hours_tag = ""
        if result.opening_hours == "休館":
            hours_tag = " [red]休館[/red]"
        elif result.opening_hours:
            hours_tag = f" [green]{result.opening_hours}[/green]"
        title = f"[bold cyan]{result.library_name}[/bold cyan]{hours_tag}"

        if not result.ok():
            console.print(Panel(f"[red]エラー: {result.error}[/red]", title=title))
            continue

        lines: list[object] = []

        # 貸出中テーブル
        if result.loans:
            loan_table = Table(
                title="貸出中",
                box=box.SIMPLE_HEAD,
                show_header=True,
                header_style="bold magenta",
                expand=False,
            )
            loan_table.add_column("タイトル", max_width=50)
            loan_table.add_column("著者", max_width=20)
            loan_table.add_column("返却期限", justify="center", min_width=10)
            loan_table.add_column("更新", justify="center")

            for item in result.loans:
                style = _due_style(item)
                renewable = "○" if item.is_renewable else "×"
                loan_table.add_row(
                    item.title,
                    item.author,
                    f"[{style}]{item.due_str()}[/{style}]",
                    renewable,
                )
            lines.append(loan_table)
        else:
            lines.append("[dim]貸出中の資料はありません[/dim]")

        # 予約中テーブル
        if result.reservations:
            has_pickup = any(item.pickup_location for item in result.reservations)
            res_table = Table(
                title="予約中",
                box=box.SIMPLE_HEAD,
                show_header=True,
                header_style="bold magenta",
                expand=False,
            )
            res_table.add_column("タイトル", max_width=50)
            res_table.add_column("著者", max_width=20)
            res_table.add_column("状態", justify="center", min_width=8)
            res_table.add_column("順位", justify="center")
            res_table.add_column("取置期限", justify="center")
            if has_pickup:
                res_table.add_column("受取館", justify="center")

            for item in result.reservations:
                status_style = _status_style(item.status)
                pos_str = str(item.position) if item.position is not None else ""
                until_str = item.available_until_str()
                row = [
                    item.title,
                    item.author,
                    f"[{status_style}]{item.status}[/{status_style}]",
                    pos_str,
                    until_str,
                ]
                if has_pickup:
                    row.append(item.pickup_location)
                res_table.add_row(*row)
            lines.append(res_table)
        else:
            lines.append("[dim]予約中の資料はありません[/dim]")

        from rich.console import Group
        console.print(Panel(Group(*lines), title=title, expand=False))


def _status_style(status: str) -> str:
    if "取置" in status or "準備完了" in status or "割当済" in status:
        return "bold green"
    if "準備中" in status:
        return "yellow"
    return "white"


def print_summary(results: list[LibraryResult]) -> None:
    """全図書館のサマリーを1行で表示"""
    total_loans = sum(len(r.loans) for r in results if r.ok())
    total_res = sum(len(r.reservations) for r in results if r.ok())
    errors = [r for r in results if not r.ok()]

    console.rule("[bold]サマリー[/bold]")
    console.print(
        f"貸出中: [bold green]{total_loans}[/bold green] 冊  "
        f"予約中: [bold blue]{total_res}[/bold blue] 件  "
        f"エラー: [bold red]{len(errors)}[/bold red] 館"
    )
    if errors:
        for r in errors:
            console.print(f"  [red]✗[/red] {r.library_name}: {r.error}")
