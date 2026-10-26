"""Sales statistics and profitability analytics."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...context import AppContext
from ...money import format_money
from ...services.stats import MONTH_NAMES
from ..widgets import (
    BarChart,
    PageHeader,
    StatCard,
    fill_table,
    make_table,
)

MARGIN = 24


class StatsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, 20, MARGIN, 20)
        layout.setSpacing(12)

        header = PageHeader(
            "Статистика",
            "Выручка за месяц, прибыль, самые выгодные позиции и структура оплат.",
        )
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.refresh)
        header.add_action(refresh_button)
        layout.addWidget(header)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        period_label = QLabel("Период")
        period_label.setObjectName("Muted")
        filters.addWidget(period_label)
        self.month_combo = QComboBox()
        for index, name in enumerate(MONTH_NAMES, start=1):
            self.month_combo.addItem(name, index)
        self.month_combo.setCurrentIndex(date.today().month - 1)
        self.month_combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.month_combo)
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(date.today().year)
        self.year_spin.valueChanged.connect(self.refresh)
        filters.addWidget(self.year_spin)
        self.today_label = QLabel()
        self.today_label.setObjectName("Badge")
        filters.addWidget(self.today_label)
        filters.addStretch(1)
        layout.addLayout(filters)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.revenue_card = StatCard("Выручка за месяц", accent=True)
        self.profit_card = StatCard("Прибыль за месяц")
        self.checks_card = StatCard("Чеков")
        self.avg_card = StatCard("Средний чек")
        self.items_card = StatCard("Продано единиц")
        for card in (
            self.revenue_card,
            self.profit_card,
            self.checks_card,
            self.avg_card,
            self.items_card,
        ):
            cards.addWidget(card)
        layout.addLayout(cards)

        highlights = QHBoxLayout()
        highlights.setSpacing(10)
        self.top_profit_card = StatCard(
            "Самая прибыльная позиция", "—", "по сумме прибыли за месяц", accent=True
        )
        self.top_revenue_card = StatCard(
            "Лидер по выручке", "—", "по сумме продаж за месяц"
        )
        self.today_card = StatCard("Сегодня", "—", "выручка · чеки")
        highlights.addWidget(self.top_profit_card, 2)
        highlights.addWidget(self.top_revenue_card, 2)
        highlights.addWidget(self.today_card, 1)
        layout.addLayout(highlights)

        chart_card = QFrame()
        chart_card.setObjectName("Card")
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(16, 12, 16, 10)
        chart_layout.setSpacing(4)
        chart_title = QLabel("Выручка по дням")
        chart_title.setObjectName("SectionTitle")
        chart_layout.addWidget(chart_title)
        self.chart = BarChart()
        self.chart.setMinimumHeight(180)
        self.chart.setMaximumHeight(240)
        chart_layout.addWidget(self.chart)
        layout.addWidget(chart_card)

        self.tabs = QTabWidget()
        self.items_table = make_table(["Позиция", "Кол-во", "Выручка", "Прибыль", "Маржа"])
        self.items_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in (1, 2, 3, 4):
            self.items_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.tabs.addTab(self.items_table, "Позиции")

        self.payments_table = make_table(["Способ оплаты", "Операций", "Сумма", "Доля"])
        self.payments_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in (1, 2, 3):
            self.payments_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.tabs.addTab(self.payments_table, "Оплаты")

        self.categories_table = make_table(["Категория", "Выручка", "Прибыль"])
        self.categories_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in (1, 2):
            self.categories_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.tabs.addTab(self.categories_table, "Категории")
        layout.addWidget(self.tabs, 1)

        self.low_stock_label = QLabel()
        self.low_stock_label.setObjectName("WarningBanner")
        self.low_stock_label.setWordWrap(True)
        self.low_stock_label.hide()
        layout.addWidget(self.low_stock_label)

    def refresh(self) -> None:
        year = self.year_spin.value()
        month = int(self.month_combo.currentData() or date.today().month)
        stats = self.ctx.stats.month_stats(year, month)
        today = self.ctx.stats.today_stats()
        currency = self.ctx.currency

        self.revenue_card.set_value(
            format_money(stats.revenue, currency),
            f"сегодня: {format_money(today.revenue, currency)}",
        )
        self.profit_card.set_value(
            format_money(stats.profit, currency),
            f"сегодня: {format_money(today.profit, currency)}",
        )
        self.checks_card.set_value(
            str(stats.sales_count), f"сегодня: {today.sales_count}"
        )
        self.avg_card.set_value(format_money(stats.avg_check, currency), "за месяц")
        self.items_card.set_value(str(stats.items_sold), "за месяц")
        self.today_label.setText(
            f"Сегодня: {format_money(today.revenue, currency)} · {today.sales_count} чеков"
        )

        if stats.top_profit:
            item = stats.top_profit
            self.top_profit_card.set_value(
                item.name,
                f"{format_money(item.profit, currency)} · {item.qty} ед.",
            )
        else:
            self.top_profit_card.set_value("Нет продаж", "за выбранный месяц")
        if stats.top_revenue:
            item = stats.top_revenue
            self.top_revenue_card.set_value(
                item.name,
                f"{format_money(item.revenue, currency)} · {item.qty} ед.",
            )
        else:
            self.top_revenue_card.set_value("Нет продаж", "за выбранный месяц")
        self.today_card.set_value(
            format_money(today.revenue, currency),
            f"{today.sales_count} чеков · {today.items_sold} ед.",
        )

        self.chart.set_data(stats.daily)

        item_rows = []
        for item in stats.top_items[:50]:
            margin = (item.profit / item.revenue * 100) if item.revenue else 0
            item_rows.append(
                [
                    item.name,
                    str(item.qty),
                    format_money(item.revenue, currency),
                    format_money(item.profit, currency),
                    f"{margin:.1f}%",
                ]
            )
        fill_table(self.items_table, item_rows, align_right={1, 2, 3, 4})

        payment_rows = []
        for payment in stats.payments:
            share = (payment.amount / stats.revenue * 100) if stats.revenue else 0
            payment_rows.append(
                [
                    payment.method_name,
                    str(payment.count),
                    format_money(payment.amount, currency),
                    f"{share:.1f}%",
                ]
            )
        fill_table(self.payments_table, payment_rows, align_right={1, 2, 3})

        fill_table(
            self.categories_table,
            [
                [
                    category,
                    format_money(revenue, currency),
                    format_money(profit, currency),
                ]
                for category, revenue, profit in stats.categories
            ],
            align_right={1, 2},
        )

        low_stock = self.ctx.catalog.low_stock_items()
        if low_stock:
            preview = ", ".join(f"{item.name} ({item.stock})" for item in low_stock[:8])
            self.low_stock_label.setText(f"Низкий остаток: {preview}")
            self.low_stock_label.show()
        else:
            self.low_stock_label.hide()
