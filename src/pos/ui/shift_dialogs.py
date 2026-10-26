"""Shift open/close/report dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..models import ShiftSummary
from ..money import format_money
from ..services.receipts import build_shift_report
from .widgets import (
    MoneySpinBox,
    StatCard,
    TextDocumentDialog,
    center_window,
    fill_table,
    make_table,
)


class OpenShiftDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, currency: str = "₽"):
        super().__init__(parent)
        self.currency = currency
        self.setWindowTitle("Открытие смены")
        self.setModal(True)
        self.resize(450, 300)
        self.opening_cash = 0
        self.note = ""
        self._build()
        center_window(self)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("Открыть смену")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        info_label = QLabel(
            "Укажите разменную сумму в кассе. Смена будет восстановлена "
            "автоматически, если программа закроется или отключится питание."
        )
        info_label.setObjectName("InfoBanner")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        caption = QLabel("Разменная сумма на начало смены")
        caption.setStyleSheet("font-weight: 600;")
        layout.addWidget(caption)
        self.cash_spin = MoneySpinBox()
        layout.addWidget(self.cash_spin)

        caption = QLabel("Комментарий (необязательно)")
        caption.setStyleSheet("font-weight: 600;")
        layout.addWidget(caption)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Например: утренняя смена")
        layout.addWidget(self.note_edit)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        open_button = QPushButton("Открыть смену")
        open_button.setObjectName("PrimaryButton")
        open_button.clicked.connect(self._accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(open_button)
        layout.addLayout(buttons)

    def _accept(self) -> None:
        self.opening_cash = self.cash_spin.cents()
        self.note = self.note_edit.text().strip()
        self.accept()


class CloseShiftDialog(QDialog):
    def __init__(
        self,
        summary: ShiftSummary,
        currency: str = "₽",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.summary = summary
        self.currency = currency
        self.setWindowTitle("Закрытие смены")
        self.setModal(True)
        self.resize(520, 500)
        self.counted_cash = summary.cash_expected
        self.note = ""
        self._build()
        center_window(self)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)

        title = QLabel(f"Закрыть смену №{self.summary.shift.id}")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        info = QLabel(
            "Пересчитайте наличные в кассе и укажите фактическую сумму. "
            "После закрытия будет показан отчёт за смену."
        )
        info.setObjectName("InfoBanner")
        info.setWordWrap(True)
        layout.addWidget(info)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        rows = [
            ("Выручка за смену", format_money(self.summary.revenue, self.currency)),
            ("Чеков", str(self.summary.sales_count)),
            ("Размен на начало", format_money(self.summary.shift.opening_cash, self.currency)),
            ("Ожидалось наличных", format_money(self.summary.cash_expected, self.currency)),
        ]
        for index, (label, value) in enumerate(rows):
            caption = QLabel(label)
            caption.setObjectName("Muted")
            value_label = QLabel(value)
            value_label.setStyleSheet("font-weight: 600; font-size: 11pt;")
            grid.addWidget(caption, index, 0)
            grid.addWidget(value_label, index, 1, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(grid)

        caption = QLabel("Фактически в кассе")
        caption.setStyleSheet("font-weight: 700;")
        layout.addWidget(caption)
        self.cash_spin = MoneySpinBox()
        self.cash_spin.set_cents(self.summary.cash_expected)
        self.cash_spin.valueChanged.connect(self._update_difference)
        layout.addWidget(self.cash_spin)

        self.difference_label = QLabel()
        self.difference_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.difference_label.setStyleSheet("font-size: 11pt; font-weight: 700;")
        layout.addWidget(self.difference_label)

        caption = QLabel("Комментарий (необязательно)")
        caption.setStyleSheet("font-weight: 600;")
        layout.addWidget(caption)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setMaximumHeight(70)
        self.note_edit.setPlaceholderText("Например: недостача 50 ₽ — уточняется")
        layout.addWidget(self.note_edit)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        close_button = QPushButton("Закрыть смену")
        close_button.setObjectName("DangerButton")
        close_button.clicked.connect(self._accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self._update_difference()

    def _update_difference(self) -> None:
        difference = self.cash_spin.cents() - self.summary.cash_expected
        if difference == 0:
            text = "Расхождений нет"
            color = "#15803d"
        elif difference > 0:
            text = f"Излишек: {format_money(difference, self.currency)}"
            color = "#b45309"
        else:
            text = f"Недостача: {format_money(-difference, self.currency)}"
            color = "#b91c1c"
        self.difference_label.setText(text)
        self.difference_label.setStyleSheet(
            f"font-size: 11pt; font-weight: 700; color: {color};"
        )

    def _accept(self) -> None:
        self.counted_cash = self.cash_spin.cents()
        self.note = self.note_edit.toPlainText().strip()
        self.accept()


class ShiftReportDialog(QDialog):
    def __init__(
        self,
        summary: ShiftSummary,
        ctx: AppContext,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.summary = summary
        self.ctx = ctx
        self.currency = ctx.currency
        self.setWindowTitle(f"Отчёт по смене №{summary.shift.id}")
        self.resize(940, 760)
        self._build()
        center_window(self)

    def _build(self) -> None:
        summary = self.summary
        shift = summary.shift
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(f"Смена №{shift.id} · {shift.user_name}")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        status = QLabel("Открыта" if shift.is_open else "Закрыта")
        status.setObjectName("ShiftOpen" if shift.is_open else "ShiftClosed")
        header.addWidget(status)
        layout.addLayout(header)

        dates = QLabel(f"Открыта: {shift.opened_at}    ·    Закрыта: {shift.closed_at or '—'}")
        dates.setObjectName("Muted")
        layout.addWidget(dates)

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        card_data = [
            ("Выручка", format_money(summary.revenue, self.currency), f"{summary.sales_count} чеков"),
            ("Прибыль", format_money(summary.profit, self.currency), "выручка минус себестоимость"),
            ("Средний чек", format_money(summary.avg_check, self.currency), f"{summary.items_sold} ед. продано"),
            ("Наличные", format_money(summary.cash_expected, self.currency), "ожидалось в кассе"),
        ]
        for index, (card_title, value, hint) in enumerate(card_data):
            cards.addWidget(StatCard(card_title, value, hint), 0, index)
        layout.addLayout(cards)

        cash = QFrame()
        cash.setObjectName("Card")
        cash_layout = QHBoxLayout(cash)
        cash_layout.setContentsMargins(14, 10, 14, 10)
        cash_layout.addWidget(QLabel(f"Размен: {format_money(shift.opening_cash, self.currency)}"))
        cash_layout.addStretch(1)
        if summary.cash_counted is not None:
            difference = summary.cash_difference or 0
            diff_text = format_money(difference, self.currency)
            color = "#15803d" if difference == 0 else ("#b45309" if difference > 0 else "#b91c1c")
            label = QLabel(
                f"Фактически в кассе: {format_money(summary.cash_counted, self.currency)}"
                f"    ·    Расхождение: <span style='color:{color}; font-weight:700'>{diff_text}</span>"
            )
            label.setTextFormat(Qt.TextFormat.RichText)
        else:
            label = QLabel("Смена ещё открыта — касса не пересчитана")
        cash_layout.addWidget(label)
        layout.addWidget(cash)

        month = QFrame()
        month.setObjectName("Card")
        month_layout = QHBoxLayout(month)
        month_layout.setContentsMargins(16, 12, 16, 12)
        month_title = QLabel("За месяц")
        month_title.setObjectName("SectionTitle")
        month_layout.addWidget(month_title)
        month_layout.addSpacing(12)
        month_layout.addWidget(
            QLabel(f"Выручка: <b>{format_money(summary.month_revenue, self.currency)}</b>")
        )
        month_layout.addWidget(
            QLabel(f"Прибыль: <b>{format_money(summary.month_profit, self.currency)}</b>")
        )
        if summary.month_top_profit:
            item = summary.month_top_profit
            month_layout.addWidget(
                QLabel(
                    "Самая прибыльная позиция: "
                    f"<b>{item.name}</b> ({format_money(item.profit, self.currency)})"
                )
            )
        month_layout.addStretch(1)
        layout.addWidget(month)

        tables = QHBoxLayout()
        tables.setSpacing(12)

        top_card = QFrame()
        top_card.setObjectName("Card")
        top_layout = QVBoxLayout(top_card)
        top_layout.setContentsMargins(14, 12, 14, 12)
        top_title = QLabel("Топ позиций по прибыли")
        top_title.setObjectName("SectionTitle")
        top_layout.addWidget(top_title)
        self.top_table = make_table(["Позиция", "Кол-во", "Выручка", "Прибыль"])
        self.top_table.setMinimumHeight(220)
        fill_table(
            self.top_table,
            [
                [
                    item.name,
                    str(item.qty),
                    format_money(item.revenue, self.currency),
                    format_money(item.profit, self.currency),
                ]
                for item in summary.top_items[:10]
            ],
            align_right={1, 2, 3},
        )
        top_layout.addWidget(self.top_table)
        tables.addWidget(top_card, 3)

        pay_card = QFrame()
        pay_card.setObjectName("Card")
        pay_layout = QVBoxLayout(pay_card)
        pay_layout.setContentsMargins(14, 12, 14, 12)
        pay_title = QLabel("Оплаты")
        pay_title.setObjectName("SectionTitle")
        pay_layout.addWidget(pay_title)
        self.pay_table = make_table(["Способ", "Операций", "Сумма"])
        self.pay_table.setMinimumHeight(220)
        fill_table(
            self.pay_table,
            [
                [
                    payment.method_name,
                    str(payment.count),
                    format_money(payment.amount, self.currency),
                ]
                for payment in summary.payments
            ],
            align_right={1, 2},
        )
        pay_layout.addWidget(self.pay_table)
        tables.addWidget(pay_card, 2)
        layout.addLayout(tables, 1)

        if summary.low_stock:
            low = QLabel(
                "Низкий остаток: "
                + ", ".join(f"{item.name} ({item.stock})" for item in summary.low_stock[:6])
            )
            low.setObjectName("WarningBanner")
            low.setWordWrap(True)
            layout.addWidget(low)

        buttons = QHBoxLayout()
        print_button = QPushButton("Печать отчёта")
        print_button.clicked.connect(self._print)
        close_button = QPushButton("Закрыть")
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(print_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _print(self) -> None:
        text = build_shift_report(self.summary, self.ctx.settings)
        dialog = TextDocumentDialog(
            f"Отчёт по смене №{self.summary.shift.id}",
            text,
            default_path=self.ctx.paths.receipt_dir
            / f"shift-{self.summary.shift.id}.txt",
            parent=self,
        )
        dialog.exec()
