"""Sales statistics: shift reports and period analytics."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from ..database import Database
from ..models import (
    DailyPoint,
    ItemStat,
    PaymentStat,
    PeriodStats,
    Shift,
    ShiftSummary,
)
from .catalog import CatalogService
from .errors import ValidationError
from .shifts import ShiftService

MONTH_NAMES = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]


def month_range(year: int, month: int) -> tuple[str, str]:
    if not 1 <= month <= 12:
        raise ValidationError("Некорректный месяц")
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def day_range(day: date) -> tuple[str, str]:
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


class StatsService:
    def __init__(
        self,
        db: Database,
        shifts: ShiftService | None = None,
        catalog: CatalogService | None = None,
    ):
        self.db = db
        self.shifts = shifts or ShiftService(db)
        self.catalog = catalog or CatalogService(db)

    # ------------------------------------------------------------- aggregates
    @staticmethod
    def _where(start: str | None, end: str | None, shift_id: int | None) -> tuple[str, list[Any]]:
        clauses = ["s.status='completed'"]
        params: list[Any] = []
        if shift_id is not None:
            clauses.append("s.shift_id=?")
            params.append(shift_id)
        if start is not None:
            clauses.append("s.created_at >= ?")
            params.append(start)
        if end is not None:
            clauses.append("s.created_at < ?")
            params.append(end)
        return " AND ".join(clauses), params

    def _totals(
        self, start: str | None, end: str | None, shift_id: int | None = None
    ) -> tuple[int, int, int, int]:
        where, params = self._where(start, end, shift_id)
        row = self.db.query_one(
            f"""
            SELECT COUNT(DISTINCT s.id) AS sales_count,
                   COALESCE(SUM(si.line_total), 0) AS revenue,
                   COALESCE(SUM((si.unit_price - si.cost) * si.qty), 0) AS profit,
                   COALESCE(SUM(si.qty), 0) AS items_sold
            FROM sales s
            JOIN sale_items si ON si.sale_id = s.id
            WHERE {where}
            """,
            params,
        )
        if row is None:
            return 0, 0, 0, 0
        return (
            int(row["revenue"]),
            int(row["profit"]),
            int(row["sales_count"]),
            int(row["items_sold"]),
        )

    def _top_items(
        self,
        start: str | None,
        end: str | None,
        shift_id: int | None = None,
        *,
        order: str = "profit",
        limit: int = 20,
    ) -> list[ItemStat]:
        where, params = self._where(start, end, shift_id)
        order_sql = "profit DESC" if order == "profit" else "revenue DESC"
        rows = self.db.query(
            f"""
            SELECT si.item_id,
                   MAX(si.name_snapshot) AS name,
                   SUM(si.qty) AS qty,
                   SUM(si.line_total) AS revenue,
                   SUM((si.unit_price - si.cost) * si.qty) AS profit
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            WHERE {where}
            GROUP BY si.item_id, si.name_snapshot
            ORDER BY {order_sql}, revenue DESC
            LIMIT ?
            """,
            [*params, int(limit)],
        )
        return [
            ItemStat(
                item_id=int(row["item_id"]) if row["item_id"] is not None else None,
                name=str(row["name"]),
                qty=int(row["qty"] or 0),
                revenue=int(row["revenue"] or 0),
                profit=int(row["profit"] or 0),
            )
            for row in rows
        ]

    def _payments(
        self, start: str | None, end: str | None, shift_id: int | None = None
    ) -> list[PaymentStat]:
        where, params = self._where(start, end, shift_id)
        rows = self.db.query(
            f"""
            SELECT sp.method_name, sp.method_kind,
                   SUM(sp.amount) AS amount, COUNT(*) AS cnt
            FROM sale_payments sp
            JOIN sales s ON s.id = sp.sale_id
            WHERE {where}
            GROUP BY sp.method_name, sp.method_kind
            ORDER BY amount DESC
            """,
            params,
        )
        return [
            PaymentStat(
                method_name=str(row["method_name"]),
                kind=str(row["method_kind"]),
                amount=int(row["amount"] or 0),
                count=int(row["cnt"] or 0),
            )
            for row in rows
        ]

    def _daily(self, start: str, end: str) -> list[DailyPoint]:
        rows = self.db.query(
            """
            SELECT date(s.created_at) AS day,
                   COALESCE(SUM(si.line_total), 0) AS revenue,
                   COALESCE(SUM((si.unit_price - si.cost) * si.qty), 0) AS profit
            FROM sales s
            JOIN sale_items si ON si.sale_id = s.id
            WHERE s.status='completed' AND s.created_at >= ? AND s.created_at < ?
            GROUP BY day
            ORDER BY day
            """,
            (start, end),
        )
        return [
            DailyPoint(
                date=str(row["day"]),
                revenue=int(row["revenue"] or 0),
                profit=int(row["profit"] or 0),
            )
            for row in rows
        ]

    def _categories(
        self, start: str | None, end: str | None
    ) -> list[tuple[str, int, int]]:
        where, params = self._where(start, end, None)
        rows = self.db.query(
            f"""
            SELECT COALESCE(c.name, 'Без категории') AS category,
                   SUM(si.line_total) AS revenue,
                   SUM((si.unit_price - si.cost) * si.qty) AS profit
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            LEFT JOIN items i ON i.id = si.item_id
            LEFT JOIN categories c ON c.id = i.category_id
            WHERE {where}
            GROUP BY category
            ORDER BY revenue DESC
            """,
            params,
        )
        return [
            (str(row["category"]), int(row["revenue"] or 0), int(row["profit"] or 0))
            for row in rows
        ]

    # ------------------------------------------------------------------ public
    def period_stats(self, start: str, end: str) -> PeriodStats:
        revenue, profit, sales_count, items_sold = self._totals(start, end)
        top_by_profit = self._top_items(start, end, order="profit", limit=30)
        top_by_revenue = self._top_items(start, end, order="revenue", limit=1)
        return PeriodStats(
            start=start,
            end=end,
            revenue=revenue,
            profit=profit,
            sales_count=sales_count,
            items_sold=items_sold,
            avg_check=revenue // sales_count if sales_count else 0,
            top_items=top_by_profit,
            payments=self._payments(start, end),
            daily=self._daily(start, end),
            top_profit=top_by_profit[0] if top_by_profit else None,
            top_revenue=top_by_revenue[0] if top_by_revenue else None,
            categories=self._categories(start, end),
        )

    def month_stats(self, year: int, month: int) -> PeriodStats:
        start, end = month_range(year, month)
        stats = self.period_stats(start, end)
        # Fill every day of the month so the chart has a stable timeline.
        existing = {point.date: point for point in stats.daily}
        days_in_month = (datetime(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)).day
        daily = []
        for day_num in range(1, days_in_month + 1):
            key = date(year, month, day_num).isoformat()
            point = existing.get(key)
            if point is None:
                daily.append(DailyPoint(date=key, revenue=0, profit=0))
            else:
                daily.append(point)
        return PeriodStats(
            start=stats.start,
            end=stats.end,
            revenue=stats.revenue,
            profit=stats.profit,
            sales_count=stats.sales_count,
            items_sold=stats.items_sold,
            avg_check=stats.avg_check,
            top_items=stats.top_items,
            payments=stats.payments,
            daily=daily,
            top_profit=stats.top_profit,
            top_revenue=stats.top_revenue,
            categories=stats.categories,
        )

    def today_stats(self) -> PeriodStats:
        start, end = day_range(date.today())
        return self.period_stats(start, end)

    def shift_summary(self, shift_id: int) -> ShiftSummary:
        shift = self.shifts.get(shift_id)
        if shift is None:
            raise ValidationError("Смена не найдена")
        revenue, profit, sales_count, items_sold = self._totals(None, None, shift_id)
        payments = self._payments(None, None, shift_id)
        top_items = self._top_items(None, None, shift_id, order="profit", limit=30)
        cash_expected = self.shifts.expected_cash(shift_id)

        closed_at = shift.closed_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        closed_dt = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
        month_start, month_end = month_range(closed_dt.year, closed_dt.month)
        month_revenue, month_profit, _, _ = self._totals(month_start, month_end)
        month_top_profit = self._top_items(
            month_start, month_end, order="profit", limit=1
        )
        month_top_revenue = self._top_items(
            month_start, month_end, order="revenue", limit=1
        )

        return ShiftSummary(
            shift=shift,
            revenue=revenue,
            profit=profit,
            sales_count=sales_count,
            items_sold=items_sold,
            avg_check=revenue // sales_count if sales_count else 0,
            payments=payments,
            top_items=top_items,
            cash_expected=cash_expected,
            cash_counted=shift.closing_cash,
            cash_difference=shift.cash_difference,
            month_revenue=month_revenue,
            month_profit=month_profit,
            month_top_profit=month_top_profit[0] if month_top_profit else None,
            month_top_revenue=month_top_revenue[0] if month_top_revenue else None,
            low_stock=self.catalog.low_stock_items(),
        )

    def available_years(self) -> list[int]:
        rows = self.db.query(
            "SELECT DISTINCT substr(created_at, 1, 4) AS y FROM sales "
            "WHERE status='completed' ORDER BY y DESC"
        )
        years = {int(row["y"]) for row in rows if str(row["y"]).isdigit()}
        years.add(date.today().year)
        return sorted(years, reverse=True)

    def shifts_overview(self, limit: int = 200) -> list:
        """Shift rows enriched with revenue/profit, for the shifts table."""
        return self.db.query(
            """
            SELECT s.*,
                   COALESCE(NULLIF(u.full_name, ''), u.username) AS user_name,
                   COUNT(DISTINCT sa.id) AS sales_count,
                   COALESCE(SUM(si.qty), 0) AS items_sold,
                   COALESCE(SUM(si.line_total), 0) AS revenue,
                   COALESCE(SUM((si.unit_price - si.cost) * si.qty), 0) AS profit
            FROM shifts s
            JOIN users u ON u.id = s.user_id
            LEFT JOIN sales sa ON sa.shift_id = s.id AND sa.status='completed'
            LEFT JOIN sale_items si ON si.sale_id = sa.id
            GROUP BY s.id
            ORDER BY s.id DESC
            LIMIT ?
            """,
            (int(limit),),
        )
