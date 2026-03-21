"""PDF 出力用 HTML 生成モジュール"""
from datetime import date
from html import escape

from .models import LibraryResult, LoanItem, ReservationItem


_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: 'Noto Sans JP', 'Hiragino Sans', 'Yu Gothic', sans-serif;
    font-size: 11px;
    color: #222;
    background: #fff;
    padding: 16px 20px;
}

h1 {
    font-size: 13px;
    margin-bottom: 14px;
    color: #333;
}

.library {
    border: 1px solid #888;
    border-radius: 6px;
    margin-bottom: 14px;
    overflow: hidden;
}

.library-title {
    background: #1a1a2e;
    color: #00d4ff;
    font-weight: bold;
    font-size: 12px;
    padding: 5px 12px;
    text-align: center;
}

.library-body {
    padding: 8px 12px;
}

.error {
    color: #c0392b;
    padding: 4px 0;
}

.section-title {
    font-weight: bold;
    font-size: 11px;
    color: #8e44ad;
    margin: 6px 0 4px 0;
    text-align: center;
}

.empty {
    color: #999;
    font-size: 10px;
    margin: 2px 0 6px 0;
    text-align: center;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 6px;
    table-layout: fixed;
}

th {
    font-size: 10px;
    font-weight: bold;
    color: #8e44ad;
    border-bottom: 2px solid #ccc;
    padding: 3px 6px;
    text-align: left;
    white-space: nowrap;
}

td {
    font-size: 10px;
    padding: 3px 6px;
    border-bottom: 1px solid #eee;
    vertical-align: top;
    word-break: break-all;
}

tr:last-child td { border-bottom: none; }

.col-title  { width: 34%; }
.col-author { width: 18%; }
.col-due    { width: 12%; text-align: center; white-space: nowrap; }
.col-renew  { width: 6%;  text-align: center; }
.col-status { width: 12%; text-align: center; white-space: nowrap; }
.col-pos    { width: 6%;  text-align: center; }
.col-until  { width: 12%; text-align: center; white-space: nowrap; }
.col-pickup { width: 10%; text-align: center; white-space: nowrap; }

.green  { color: #27ae60; font-weight: bold; }
.yellow { color: #d35400; }
.red    { color: #c0392b; font-weight: bold; }
.dim    { color: #999; }

.summary {
    border-top: 2px solid #555;
    padding-top: 8px;
    font-size: 11px;
    text-align: center;
}
.summary span { margin: 0 12px; }
.summary .loans  { color: #27ae60; font-weight: bold; }
.summary .res    { color: #2980b9; font-weight: bold; }
.summary .errors { color: #c0392b; font-weight: bold; }
.error-list { margin-top: 4px; color: #c0392b; font-size: 10px; }
"""


def _due_class(item: LoanItem) -> str:
    if item.due_date is None:
        return "dim"
    if item.overdue():
        return "red"
    days_left = (item.due_date - date.today()).days
    return "yellow" if days_left <= 3 else "green"


def _status_class(status: str) -> str:
    if "取置" in status or "準備完了" in status or "割当済" in status:
        return "green"
    if "準備中" in status:
        return "yellow"
    return ""


def _loans_table(loans: list[LoanItem]) -> str:
    rows = []
    for item in loans:
        cls = _due_class(item)
        due = f'<span class="{cls}">{escape(item.due_str())}</span>'
        renewable = "○" if item.is_renewable else "×"
        rows.append(
            f"<tr>"
            f'<td class="col-title">{escape(item.title)}</td>'
            f'<td class="col-author">{escape(item.author)}</td>'
            f'<td class="col-due">{due}</td>'
            f'<td class="col-renew">{renewable}</td>'
            f"</tr>"
        )
    return (
        "<table>"
        "<colgroup>"
        '<col class="col-title"><col class="col-author">'
        '<col class="col-due"><col class="col-renew">'
        "</colgroup>"
        "<thead><tr>"
        '<th class="col-title">タイトル</th>'
        '<th class="col-author">著者</th>'
        '<th class="col-due">返却期限</th>'
        '<th class="col-renew">更新</th>'
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _reservations_table(reservations: list[ReservationItem]) -> str:
    has_pickup = any(item.pickup_location for item in reservations)
    rows = []
    for item in reservations:
        cls = _status_class(item.status)
        status_cell = (
            f'<span class="{cls}">{escape(item.status)}</span>' if cls
            else f'<span class="dim">{escape(item.status)}</span>'
        )
        pos = str(item.position) if item.position is not None else ""
        until = escape(item.available_until_str())
        pickup = escape(item.pickup_location) if has_pickup else ""
        row = (
            f"<tr>"
            f'<td class="col-title">{escape(item.title)}</td>'
            f'<td class="col-author">{escape(item.author)}</td>'
            f'<td class="col-status">{status_cell}</td>'
            f'<td class="col-pos">{pos}</td>'
            f'<td class="col-until">{until}</td>'
        )
        if has_pickup:
            row += f'<td class="col-pickup">{pickup}</td>'
        row += "</tr>"
        rows.append(row)

    pickup_col = '<col class="col-pickup">' if has_pickup else ""
    pickup_th = '<th class="col-pickup">受取館</th>' if has_pickup else ""
    return (
        "<table>"
        "<colgroup>"
        '<col class="col-title"><col class="col-author">'
        '<col class="col-status"><col class="col-pos">'
        f'<col class="col-until">{pickup_col}'
        "</colgroup>"
        "<thead><tr>"
        '<th class="col-title">タイトル</th>'
        '<th class="col-author">著者</th>'
        '<th class="col-status">状態</th>'
        '<th class="col-pos">順位</th>'
        f'<th class="col-until">取置期限</th>{pickup_th}'
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def generate_pdf_html(results: list[LibraryResult]) -> str:
    sections = []
    for result in results:
        title = escape(result.library_name)
        if not result.ok():
            body = f'<p class="error">エラー: {escape(result.error or "")}</p>'
        else:
            loans_html = (
                f'<p class="section-title">貸出中</p>{_loans_table(result.loans)}'
                if result.loans
                else '<p class="empty">貸出中の資料はありません</p>'
            )
            res_html = (
                f'<p class="section-title">予約中</p>{_reservations_table(result.reservations)}'
                if result.reservations
                else '<p class="empty">予約中の資料はありません</p>'
            )
            body = loans_html + res_html

        sections.append(
            f'<div class="library">'
            f'<div class="library-title">{title}</div>'
            f'<div class="library-body">{body}</div>'
            f"</div>"
        )

    total_loans = sum(len(r.loans) for r in results if r.ok())
    total_res = sum(len(r.reservations) for r in results if r.ok())
    errors = [r for r in results if not r.ok()]
    error_rows = "".join(
        f'<div>✗ {escape(r.library_name)}: {escape(r.error or "")}</div>'
        for r in errors
    )
    summary = (
        '<div class="summary">'
        f'<span>貸出中: <span class="loans">{total_loans}</span> 冊</span>'
        f'<span>予約中: <span class="res">{total_res}</span> 件</span>'
        f'<span>エラー: <span class="errors">{len(errors)}</span> 館</span>'
        f'{"<div class=error-list>" + error_rows + "</div>" if error_rows else ""}'
        "</div>"
    )

    return (
        "<!DOCTYPE html><html lang='ja'><head>"
        "<meta charset='utf-8'>"
        f"<style>{_CSS}</style>"
        "</head><body>"
        f"{''.join(sections)}"
        f"{summary}"
        "</body></html>"
    )
