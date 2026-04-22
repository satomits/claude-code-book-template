"""モバイルフレンドリーなHTML出力モジュール"""
from datetime import date, datetime, timezone, timedelta
from html import escape

from .models import LibraryResult


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, 'Hiragino Sans', 'Yu Gothic', sans-serif;
    font-size: 15px;
    color: #222;
    background: #f4f4f8;
    padding: 12px;
    max-width: 640px;
    margin: 0 auto;
}

h1 {
    font-size: 18px;
    font-weight: bold;
    margin-bottom: 4px;
    color: #1a1a2e;
}

.updated {
    font-size: 12px;
    color: #888;
    margin-bottom: 14px;
}

.library {
    background: #fff;
    border-radius: 12px;
    margin-bottom: 14px;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.1);
}

.library-header {
    padding: 10px 14px;
    font-weight: bold;
    font-size: 14px;
    background: #1a1a2e;
    color: #fff;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.library-header .counts {
    font-size: 12px;
    font-weight: normal;
    opacity: 0.8;
}

.library-error {
    padding: 10px 14px;
    color: #c0392b;
    font-size: 13px;
    background: #fff5f5;
}

.section-label {
    padding: 6px 14px;
    font-size: 12px;
    font-weight: bold;
    color: #555;
    background: #f9f9fb;
    border-top: 1px solid #eee;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.item {
    padding: 10px 14px;
    border-top: 1px solid #f0f0f0;
}

.item-title {
    font-size: 14px;
    line-height: 1.4;
    margin-bottom: 4px;
}

.item-meta {
    font-size: 12px;
    color: #777;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
}

.badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: bold;
}

.badge-due        { background: #e8f5e9; color: #2e7d32; }
.badge-due-soon   { background: #fff8e1; color: #f57f17; }
.badge-overdue    { background: #ffebee; color: #c62828; }
.badge-status     { background: #e3f2fd; color: #1565c0; }
.badge-position   { background: #f3e5f5; color: #6a1b9a; }
.badge-hours      { background: #e8f5e9; color: #2e7d32; font-size: 11px; padding: 2px 7px; border-radius: 10px; }
.badge-closed     { background: #ffebee; color: #c62828; font-size: 11px; padding: 2px 7px; border-radius: 10px; }

.no-items {
    padding: 10px 14px;
    font-size: 13px;
    color: #aaa;
    border-top: 1px solid #f0f0f0;
}
"""


def _due_badge(due: date | None) -> str:
    if due is None:
        return ""
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST).date()
    days = (due - today).days
    fmt = due.strftime("%Y/%m/%d")
    if days < 0:
        return f'<span class="badge badge-overdue">返却期限切れ {fmt}</span>'
    if days <= 3:
        return f'<span class="badge badge-due-soon">返却期限 {fmt}（あと{days}日）</span>'
    return f'<span class="badge badge-due">返却期限 {fmt}</span>'


def generate_html(results: list[LibraryResult]) -> str:
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST).strftime("%Y/%m/%d %H:%M 更新")
    body_parts: list[str] = []

    for r in results:
        total_loans = len(r.loans)
        total_res = len(r.reservations)
        counts = f"貸出 {total_loans} / 予約 {total_res}"

        hours_badge = ""
        if r.opening_hours == "休館":
            hours_badge = ' <span class="badge-closed">休館</span>'
        elif r.opening_hours:
            hours_badge = f' <span class="badge-hours">{escape(r.opening_hours)}</span>'

        parts = [
            f'<div class="library">',
            f'<div class="library-header">'
            f'{escape(r.library_name)}{hours_badge}'
            f'<span class="counts">{counts}</span>'
            f'</div>',
        ]

        if r.error:
            parts.append(f'<div class="library-error">⚠ {escape(r.error)}</div>')
        else:
            # 貸出
            parts.append('<div class="section-label">貸出中</div>')
            if r.loans:
                for loan in r.loans:
                    author = f'<span>{escape(loan.author)}</span>' if loan.author else ""
                    due = _due_badge(loan.due_date)
                    parts.append(
                        f'<div class="item">'
                        f'<div class="item-title">{escape(loan.title)}</div>'
                        f'<div class="item-meta">{author}{due}</div>'
                        f'</div>'
                    )
            else:
                parts.append('<div class="no-items">なし</div>')

            # 予約
            parts.append('<div class="section-label">予約中</div>')
            if r.reservations:
                for res in r.reservations:
                    author = f'<span>{escape(res.author)}</span>' if res.author else ""
                    status = f'<span class="badge badge-status">{escape(res.status)}</span>' if res.status else ""
                    pos = f'<span class="badge badge-position">{res.position}位</span>' if res.position else ""
                    avail = (
                        f'<span>取置期限 {res.available_until.strftime("%Y/%m/%d")}</span>'
                        if res.available_until else ""
                    )
                    parts.append(
                        f'<div class="item">'
                        f'<div class="item-title">{escape(res.title)}</div>'
                        f'<div class="item-meta">{author}{status}{pos}{avail}</div>'
                        f'</div>'
                    )
            else:
                parts.append('<div class="no-items">なし</div>')

        parts.append('</div>')
        body_parts.append("\n".join(parts))

    body = "\n".join(body_parts)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>図書館状況</title>
<style>{_CSS}</style>
</head>
<body>
<h1>図書館状況</h1>
<p class="updated">{now}</p>
{body}
</body>
</html>"""
