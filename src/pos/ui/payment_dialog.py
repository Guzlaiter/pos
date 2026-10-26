"""Payment dialog supporting split payments across methods."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models import PaymentInput, PaymentMethod
from ..money import format_money
from .widgets import MoneySpinBox, center_window


class PaymentDialog(QDialog):
    def __init__(
        self,
        total: int,
        methods: list[PaymentMethod],
        currency: str = "₽",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.total = int(total)
        self.currency = currency
        self.methods = methods
        self._inputs: dict[int, MoneySpinBox] = {}
        self._updating = False
        self.payments: list[PaymentInput] = []
        self.setWindowTitle("Оплата")
        self.resize(500, 560)
        self.setModal(True)
        self._build()
        center_window(self)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("Оплата чека")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        total_label = QLabel(format_money(self.total, self.currency))
        total_label.setObjectName("TotalValue")
        total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(total_label)

        hint = QLabel(
            "Можно разделить оплату между несколькими способами. "
            "Например: 300 на QR и остальное наличными."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(190)
        inner = QWidget()
        self.form = QFormLayout(inner)
        self.form.setContentsMargins(4, 4, 4, 4)
        self.form.setSpacing(10)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        if not self.methods:
            empty = QLabel("Нет активных способов оплаты. Обратитесь к администратору.")
            empty.setObjectName("WarningBanner")
            empty.setWordWrap(True)
            self.form.addRow(empty)
        for method in self.methods:
            spin = MoneySpinBox(maximum_cents=max(self.total, 1))
            spin.valueChanged.connect(self._update_remaining)
            self._inputs[method.id] = spin
            label = QLabel(method.name)
            label.setStyleSheet("font-weight: 600;")
            self.form.addRow(label, spin)
        scroll.setWidget(inner)
        card_layout.addWidget(scroll)
        layout.addWidget(card, 1)

        self.remaining_label = QLabel()
        self.remaining_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.remaining_label.setStyleSheet("font-size: 12pt; font-weight: 700;")
        layout.addWidget(self.remaining_label)

        quick = QHBoxLayout()
        self.cash_button = QPushButton("Остаток наличными")
        self.cash_button.clicked.connect(self._fill_cash_remainder)
        reset_button = QPushButton("Сбросить")
        reset_button.clicked.connect(self._reset)
        quick.addWidget(self.cash_button)
        quick.addWidget(reset_button)
        quick.addStretch(1)
        layout.addLayout(quick)

        buttons = QHBoxLayout()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        self.pay_button = QPushButton("Оплатить")
        self.pay_button.setObjectName("SuccessButton")
        self.pay_button.setMinimumWidth(180)
        self.pay_button.clicked.connect(self._accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.pay_button)
        layout.addLayout(buttons)

        # Convenience: prefill the whole amount to a cash method (or the first one).
        if self.methods:
            target = next(
                (m for m in self.methods if m.affects_cash), self.methods[0]
            )
            self._inputs[target.id].set_cents(self.total)
        self._update_remaining()

    def _update_remaining(self) -> None:
        if self._updating:
            return
        allocated = sum(spin.cents() for spin in self._inputs.values())
        remaining = self.total - allocated
        if remaining > 0:
            self.remaining_label.setText(
                f"Осталось распределить: {format_money(remaining, self.currency)}"
            )
            self.remaining_label.setStyleSheet(
                "font-size: 12pt; font-weight: 700; color: #b45309;"
            )
        elif remaining < 0:
            self.remaining_label.setText(
                f"Превышение: {format_money(-remaining, self.currency)}"
            )
            self.remaining_label.setStyleSheet(
                "font-size: 12pt; font-weight: 700; color: #b91c1c;"
            )
        else:
            self.remaining_label.setText("Сумма распределена полностью")
            self.remaining_label.setStyleSheet(
                "font-size: 12pt; font-weight: 700; color: #15803d;"
            )
        self.pay_button.setEnabled(remaining == 0 and bool(self._inputs))
        self.pay_button.setText(
            f"Оплатить {format_money(self.total, self.currency)}"
            if self.total
            else "Завершить"
        )

    def _fill_cash_remainder(self) -> None:
        if not self._inputs:
            return
        allocated = sum(spin.cents() for spin in self._inputs.values())
        remaining = self.total - allocated
        if remaining <= 0:
            return
        method_id = next(
            (m.id for m in self.methods if m.affects_cash), self.methods[0].id
        )
        spin = self._inputs[method_id]
        self._updating = True
        spin.set_cents(spin.cents() + remaining)
        self._updating = False
        self._update_remaining()

    def _reset(self) -> None:
        self._updating = True
        for spin in self._inputs.values():
            spin.set_cents(0)
        self._updating = False
        self._update_remaining()

    def _accept(self) -> None:
        allocated = sum(spin.cents() for spin in self._inputs.values())
        if allocated != self.total:
            return
        self.payments = [
            PaymentInput(method_id=method_id, amount=spin.cents())
            for method_id, spin in self._inputs.items()
            if spin.cents() > 0
        ]
        self.accept()
