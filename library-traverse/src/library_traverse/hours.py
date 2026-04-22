"""図書館の開館時間・休館日判定モジュール"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import jpholiday


JST = timezone(timedelta(hours=9))


@dataclass
class LibraryHours:
    """図書館の開館時間定義"""
    weekday_open: str           # 平日開館 "9:30"
    weekday_close: str          # 平日閉館 "20:00"
    weekend_open: str           # 土日祝開館 "9:30"
    weekend_close: str          # 土日祝閉館 "18:00"
    closed_weekdays: list[int] = field(default_factory=list)   # 休館曜日 (0=月)
    closed_monthly: list[tuple[int, int]] = field(default_factory=list)  # (第n, 曜日) 月次休館
    closed_last_weekday: int | None = None  # 最終X曜日が休館 (0=月)
    year_end_close: tuple[int, int] = (12, 29)  # 年末休館開始
    year_start_open: tuple[int, int] = (1, 5)   # 年始開館


# 各図書館の開館時間データ
HOURS_DATA: dict[str, LibraryHours] = {
    "sagamihara": LibraryHours(
        weekday_open="9:30", weekday_close="20:00",
        weekend_open="9:30", weekend_close="18:00",
        closed_weekdays=[0],           # 月曜休館
        closed_monthly=[(2, 3)],       # 第2木曜
    ),
    "kawasaki": LibraryHours(
        weekday_open="9:30", weekday_close="19:00",
        weekend_open="9:30", weekend_close="17:00",
        closed_monthly=[(3, 0)],       # 第3月曜
    ),
    "yokohama": LibraryHours(
        weekday_open="9:30", weekday_close="19:00",
        weekend_open="9:30", weekend_close="17:00",
    ),
    "kanagawa_pref": LibraryHours(
        weekday_open="9:00", weekday_close="19:00",
        weekend_open="9:00", weekend_close="17:00",
        closed_weekdays=[0],           # 月曜休館
        closed_monthly=[(2, 3)],       # 第2木曜
    ),
    "machida": LibraryHours(
        weekday_open="10:00", weekday_close="20:00",
        weekend_open="10:00", weekend_close="17:00",
        closed_weekdays=[0],           # 月曜休館
        closed_monthly=[(2, 3)],       # 第2木曜
    ),
    "ebina": LibraryHours(
        weekday_open="9:00", weekday_close="21:00",
        weekend_open="9:00", weekend_close="21:00",
        # 年中無休
        year_end_close=(12, 32),  # 実質なし
        year_start_open=(1, 1),
    ),
    "hadano": LibraryHours(
        weekday_open="9:00", weekday_close="19:00",
        weekend_open="9:00", weekend_close="17:00",
        closed_weekdays=[0],           # 月曜休館
        closed_last_weekday=4,         # 最終金曜
    ),
    "yamato": LibraryHours(
        weekday_open="9:00", weekday_close="21:00",
        weekend_open="9:00", weekend_close="20:00",
        # 12/31-1/1のみ休館
        year_end_close=(12, 31),
        year_start_open=(1, 2),
    ),
    "isehara": LibraryHours(
        weekday_open="9:00", weekday_close="19:00",
        weekend_open="9:00", weekend_close="17:00",
        closed_weekdays=[0],           # 月曜休館
        closed_monthly=[(1, 2)],       # 第1水曜
    ),
    "atsugi": LibraryHours(
        weekday_open="9:00", weekday_close="19:00",
        weekend_open="9:00", weekend_close="19:00",
        closed_monthly=[(1, 3), (3, 0)],  # 第1木曜, 第3月曜
    ),
}


def _nth_weekday_of_month(year: int, month: int, n: int, weekday: int) -> date:
    """月の第n X曜日の日付を返す。n=1で第1、n=2で第2...。"""
    first = date(year, month, 1)
    # 最初のX曜日を求める
    diff = (weekday - first.weekday()) % 7
    first_target = first + timedelta(days=diff)
    return first_target + timedelta(weeks=n - 1)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """月の最終X曜日の日付を返す。"""
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)
    diff = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=diff)


def _is_year_end_holiday(d: date, hours: LibraryHours) -> bool:
    """年末年始の休館日かどうか。"""
    ye_m, ye_d = hours.year_end_close
    ys_m, ys_d = hours.year_start_open
    # 年末側
    if d.month == ye_m and d.day >= ye_d:
        return True
    # 年始側
    if d.month == ys_m and d.day < ys_d:
        return True
    return False


def _is_weekend_or_holiday(d: date) -> bool:
    """土日または祝日かどうか。"""
    return d.weekday() >= 5 or jpholiday.is_holiday(d)


def get_today_hours(library_id: str) -> str:
    """本日の開館時間を返す。休館日なら '休館' を返す。"""
    hours = HOURS_DATA.get(library_id)
    if hours is None:
        return ""

    today = datetime.now(JST).date()
    return _get_hours_for_date(today, hours)


def _get_hours_for_date(d: date, hours: LibraryHours) -> str:
    """指定日の開館時間を返す。"""
    # 年末年始チェック
    if _is_year_end_holiday(d, hours):
        return "休館"

    # 曜日休館チェック
    if d.weekday() in hours.closed_weekdays:
        return "休館"

    # 月次休館チェック（第n X曜日）
    for n, weekday in hours.closed_monthly:
        target = _nth_weekday_of_month(d.year, d.month, n, weekday)
        if d == target:
            return "休館"

    # 最終X曜日休館チェック
    if hours.closed_last_weekday is not None:
        target = _last_weekday_of_month(d.year, d.month, hours.closed_last_weekday)
        if d == target:
            return "休館"

    # 開館時間を返す
    if _is_weekend_or_holiday(d):
        return f"{hours.weekend_open}-{hours.weekend_close}"
    return f"{hours.weekday_open}-{hours.weekday_close}"
