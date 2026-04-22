"""共通データモデル"""
from dataclasses import dataclass, field
from datetime import date


@dataclass
class LoanItem:
    """貸出中の資料"""
    title: str
    author: str = ""
    due_date: date | None = None
    is_renewable: bool = True
    renewals_done: int = 0

    def due_str(self) -> str:
        return self.due_date.strftime("%Y/%m/%d") if self.due_date else "不明"

    def overdue(self) -> bool:
        return self.due_date is not None and self.due_date < date.today()


@dataclass
class ReservationItem:
    """予約中の資料"""
    title: str
    author: str = ""
    status: str = ""          # "予約中", "準備中", "取置中" など
    position: int | None = None   # 予約順位
    available_until: date | None = None  # 取置期限
    pickup_location: str = ""     # 受取館

    def available_until_str(self) -> str:
        return self.available_until.strftime("%Y/%m/%d") if self.available_until else ""


@dataclass
class LibraryResult:
    """図書館ごとの取得結果"""
    library_id: str
    library_name: str
    loans: list[LoanItem] = field(default_factory=list)
    reservations: list[ReservationItem] = field(default_factory=list)
    error: str | None = None
    opening_hours: str = ""

    def ok(self) -> bool:
        return self.error is None
