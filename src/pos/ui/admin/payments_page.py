"""Payment method configuration."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...context import AppContext
from ...models import PaymentMethod
from ...services.errors import ServiceError
from ...services.payments import PAYMENT_KIND_LABELS
from ..widgets import (
    PageHeader,
    center_window,
    confirm,
    error,
    fill_table,
    make_table,
    warning,
)


class PaymentMethodDialog(QDialog):
    def __init__(
        self,
        ctx: AppContext,
        method: PaymentMethod | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.method = method
        self.setWindowTitle("Способ оплаты")
        self.setModal(True)
        self.resize(440, 390)
        self._build()
        center_window(self)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        title = QLabel("Новый способ оплаты" if self.method is None else "Изменить способ оплаты")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit(self.method.name if self.method else "")
        self.name_edit.setPlaceholderText("Например: Наличные")
        form.addRow("Название *", self.name_edit)

        self.kind_combo = QComboBox()
        for key, label in PAYMENT_KIND_LABELS.items():
            self.kind_combo.addItem(label, key)
        if self.method:
            self.kind_combo.setCurrentIndex(
                max(0, self.kind_combo.findData(self.method.kind))
            )
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        form.addRow("Тип", self.kind_combo)

        self.cash_check = QCheckBox("Учитывать в наличных при закрытии смены")
        self.cash_check.setChecked(self.method.affects_cash if self.method else False)
        form.addRow("", self.cash_check)

        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(-9999, 9999)
        self.sort_spin.setValue(self.method.sort_order if self.method else 10)
        form.addRow("Порядок сортировки", self.sort_spin)

        self.active_check = QCheckBox("Способ доступен продавцу")
        self.active_check.setChecked(self.method.is_active if self.method else True)
        form.addRow("", self.active_check)
        layout.addLayout(form)

        hint = QLabel(
            "Наличные с включённым флажком «учитывать в кассе» участвуют "
            "в расчёте ожидаемой суммы при закрытии смены. Остальные способы "
            "на кассу не влияют."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Сохранить")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self._save)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _kind_changed(self) -> None:
        if self.kind_combo.currentData() == "cash":
            self.cash_check.setChecked(True)

    def _save(self) -> None:
        values = dict(
            name=self.name_edit.text(),
            kind=self.kind_combo.currentData(),
            affects_cash=self.cash_check.isChecked(),
            sort_order=self.sort_spin.value(),
            is_active=self.active_check.isChecked(),
        )
        try:
            if self.method is None:
                self.ctx.payments.create_method(**values)
            else:
                self.ctx.payments.update_method(self.method.id, **values)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.accept()


class PaymentMethodsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._methods: list[PaymentMethod] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = PageHeader(
            "Способы оплаты",
            "Настройте список способов, которые видит продавец. Порядок влияет на экран оплаты.",
        )
        add_button = QPushButton("Добавить способ")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self._add)
        header.add_action(add_button)
        layout.addWidget(header)

        hint = QLabel(
            "Оплату можно разделить между несколькими способами. "
            "Например: 300 ₽ по QR-коду и остальное наличными."
        )
        hint.setObjectName("InfoBanner")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = make_table(
            ["Название", "Тип", "Учитывать в кассе", "Порядок", "Активен"]
        )
        self.table.doubleClicked.connect(self._edit_selected)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        edit_button = QPushButton("Изменить")
        edit_button.clicked.connect(self._edit_selected)
        toggle_button = QPushButton("Включить / отключить")
        toggle_button.clicked.connect(self._toggle_selected)
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.refresh)
        actions.addWidget(edit_button)
        actions.addWidget(toggle_button)
        actions.addStretch(1)
        actions.addWidget(refresh_button)
        layout.addLayout(actions)

    def refresh(self) -> None:
        self._methods = self.ctx.payments.list_methods(include_inactive=True)
        fill_table(
            self.table,
            [
                [
                    method.name,
                    PAYMENT_KIND_LABELS.get(method.kind, method.kind),
                    "да" if method.affects_cash else "нет",
                    str(method.sort_order),
                    "да" if method.is_active else "нет",
                ]
                for method in self._methods
            ],
        )

    def _selected(self) -> PaymentMethod | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._methods):
            return self._methods[row]
        return None

    def _add(self) -> None:
        if PaymentMethodDialog(self.ctx, parent=self).exec():
            self.refresh()

    def _edit_selected(self) -> None:
        method = self._selected()
        if method is None:
            warning(self, "Выберите способ оплаты")
            return
        if PaymentMethodDialog(self.ctx, method, parent=self).exec():
            self.refresh()

    def _toggle_selected(self) -> None:
        method = self._selected()
        if method is None:
            warning(self, "Выберите способ оплаты")
            return
        if method.is_active and not confirm(
            self, f"Отключить способ оплаты «{method.name}»?"
        ):
            return
        try:
            self.ctx.payments.set_active(method.id, not method.is_active)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.refresh()
