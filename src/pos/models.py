"""Domain models used by services and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class User:
    id: int
    username: str
    full_name: str
    role: str
    is_active: bool
    permissions: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def display_name(self) -> str:
        return self.full_name or self.username


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    kind: str
    sort_order: int
    is_active: bool


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    sku: str | None
    kind: str
    category_id: int | None
    category_name: str | None
    price: int
    cost: int
    unit: str
    track_stock: bool
    is_active: bool
    is_consumable: bool = False
    stock: int = 0

    @property
    def is_service(self) -> bool:
        return self.kind == "service"

    @property
    def is_sellable(self) -> bool:
        return self.is_active and not self.is_consumable


@dataclass(frozen=True)
class PaymentMethod:
    id: int
    name: str
    kind: str
    affects_cash: bool
    is_active: bool
    sort_order: int


@dataclass(frozen=True)
class PriceList:
    id: int
    name: str
    is_active: bool
    item_count: int = 0


@dataclass(frozen=True)
class Shift:
    id: int
    user_id: int
    user_name: str
    opened_at: str
    closed_at: str | None
    status: str
    opening_cash: int
    closing_cash: int | None
    expected_cash: int | None
    cash_difference: int | None
    note: str | None
    closed_by_user_id: int | None = None

    @property
    def is_open(self) -> bool:
        return self.status == "open"


@dataclass(frozen=True)
class PaymentStat:
    method_name: str
    kind: str
    amount: int
    count: int


@dataclass(frozen=True)
class ItemStat:
    item_id: int | None
    name: str
    qty: int
    revenue: int
    profit: int


@dataclass(frozen=True)
class DailyPoint:
    date: str
    revenue: int
    profit: int


@dataclass(frozen=True)
class ShiftSummary:
    shift: Shift
    revenue: int
    profit: int
    sales_count: int
    items_sold: int
    avg_check: int
    payments: list[PaymentStat]
    top_items: list[ItemStat]
    cash_expected: int
    cash_counted: int | None
    cash_difference: int | None
    month_revenue: int
    month_profit: int
    month_top_profit: ItemStat | None
    month_top_revenue: ItemStat | None
    low_stock: list[Item] = field(default_factory=list)


@dataclass(frozen=True)
class PeriodStats:
    start: str
    end: str
    revenue: int
    profit: int
    sales_count: int
    items_sold: int
    avg_check: int
    top_items: list[ItemStat]
    payments: list[PaymentStat]
    daily: list[DailyPoint]
    top_profit: ItemStat | None
    top_revenue: ItemStat | None
    categories: list[tuple[str, int, int]]


@dataclass(frozen=True)
class SaleLineInput:
    item_id: int
    qty: int
    unit_price: int | None = None


@dataclass(frozen=True)
class SaleLine:
    item_id: int | None
    name: str
    kind: str
    qty: int
    unit_price: int
    cost: int
    line_total: int


@dataclass(frozen=True)
class PaymentInput:
    method_id: int
    amount: int


@dataclass(frozen=True)
class SalePayment:
    method_name: str
    method_kind: str
    amount: int


@dataclass(frozen=True)
class Sale:
    id: int
    number: str
    shift_id: int
    user_id: int
    user_name: str
    status: str
    subtotal: int
    discount: int
    total: int
    note: str | None
    created_at: str
    lines: list[SaleLine] = field(default_factory=list)
    payments: list[SalePayment] = field(default_factory=list)
