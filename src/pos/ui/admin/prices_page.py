"""Price lists management."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...context import AppContext
from ...models import Item, PriceList
from ...money import format_money
from ...services.errors import ServiceError
from ..widgets import (
    MoneySpinBox,
    PageHeader,
    center_window,
    confirm,
    error,
    info,
    make_table,
    set_cell,
    warning,
)


class PriceOverrideDialog(QDialog):
    def __init__(
        self,
        ctx: AppContext,
        price_list_id: int,
        item: Item,
        override: int | None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.price_list_id = price_list_id
        self.item = item
        self.override = override
        self.setWindowTitle("Цена в прейскуранте")
        self.setModal(True)
        self.resize(440, 300)
        self._build()
        center_window(self)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        title = QLabel(self.item.name)
        title.setObjectName("SectionTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        base = QLabel(format_money(self.item.price, self.ctx.currency))
        base.setStyleSheet("font-weight: 600;")
        form.addRow("Базовая цена", base)

        self.use_base = QCheckBox("Использовать базовую цену (без индивидуальной)")
        self.use_base.setChecked(self.override is None)
        form.addRow("", self.use_base)

        self.price_spin = MoneySpinBox()
        self.price_spin.set_cents(
            self.override if self.override is not None else self.item.price
        )
        form.addRow("Цена в прейскуранте", self.price_spin)
        self.use_base.toggled.connect(self._toggle)
        layout.addLayout(form)

        hint = QLabel(
            "Активный прейскурант применяется на экране продавца. "
            "Изменение цены не затрагивает уже оформленные чеки."
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
        self._toggle(self.use_base.isChecked())

    def _toggle(self, checked: bool) -> None:
        self.price_spin.setEnabled(not checked)

    def _save(self) -> None:
        value = None if self.use_base.isChecked() else self.price_spin.cents()
        try:
            self.ctx.catalog.set_price_list_item(
                self.price_list_id, self.item.id, value
            )
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.accept()


class PricesPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._lists: list[PriceList] = []
        self._rows: list[tuple[Item, int | None]] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = PageHeader(
            "Прейскуранты",
            "Базовые цены и индивидуальные цены для отдельных прейскурантов. "
            "Активный прейскурант видит продавец.",
        )
        add_button = QPushButton("Создать прейскурант")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self._add)
        header.add_action(add_button)
        layout.addWidget(header)

        content = QHBoxLayout()
        content.setSpacing(14)

        left = QFrame()
        left.setObjectName("Card")
        left.setFixedWidth(310)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)
        left_title = QLabel("Списки")
        left_title.setObjectName("SectionTitle")
        left_layout.addWidget(left_title)
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._load_items)
        left_layout.addWidget(self.list_widget, 1)

        self.activate_button = QPushButton("Сделать активным")
        self.activate_button.setObjectName("PrimaryButton")
        self.activate_button.clicked.connect(self._activate)
        left_layout.addWidget(self.activate_button)
        list_actions = QHBoxLayout()
        rename_button = QPushButton("Переименовать")
        rename_button.clicked.connect(self._rename)
        delete_button = QPushButton("Удалить")
        delete_button.setObjectName("DangerButton")
        delete_button.clicked.connect(self._delete)
        list_actions.addWidget(rename_button)
        list_actions.addWidget(delete_button)
        left_layout.addLayout(list_actions)
        content.addWidget(left)

        right = QFrame()
        right.setObjectName("Card")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 14, 16, 14)
        right_layout.setSpacing(10)
        self.name_label = QLabel("Прейскурант")
        self.name_label.setObjectName("SectionTitle")
        right_layout.addWidget(self.name_label)
        self.hint_label = QLabel()
        self.hint_label.setObjectName("Muted")
        self.hint_label.setWordWrap(True)
        right_layout.addWidget(self.hint_label)

        self.table = make_table(["Позиция", "Базовая цена", "Цена в прейскуранте"])
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._edit_price)
        right_layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        edit_button = QPushButton("Изменить цену")
        edit_button.clicked.connect(self._edit_price)
        clear_button = QPushButton("Сбросить индивидуальные цены")
        clear_button.clicked.connect(self._clear_overrides)
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.refresh)
        actions.addWidget(edit_button)
        actions.addWidget(clear_button)
        actions.addStretch(1)
        actions.addWidget(refresh_button)
        right_layout.addLayout(actions)
        content.addWidget(right, 1)
        layout.addLayout(content, 1)

    def refresh(self) -> None:
        selected_id = self._current_id()
        self._lists = self.ctx.catalog.list_price_lists()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for price_list in self._lists:
            label = price_list.name
            if price_list.is_active:
                label += "   ★ активный"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, price_list.id)
            if price_list.is_active:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.list_widget.addItem(item)
        target_row = 0
        if selected_id is not None:
            for row in range(self.list_widget.count()):
                if self.list_widget.item(row).data(Qt.ItemDataRole.UserRole) == selected_id:
                    target_row = row
                    break
        if self.list_widget.count():
            self.list_widget.setCurrentRow(target_row)
        self.list_widget.blockSignals(False)
        self._load_items()

    def _current_id(self) -> int | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.ItemDataRole.UserRole))

    def _current_list(self) -> PriceList | None:
        current_id = self._current_id()
        return next((entry for entry in self._lists if entry.id == current_id), None)

    def _load_items(self, *_args) -> None:
        price_list = self._current_list()
        if price_list is None:
            self.table.setRowCount(0)
            self.name_label.setText("Прейскурант")
            return
        self.name_label.setText(price_list.name)
        self.hint_label.setText(
            "★ активный — цены этого списка используются на экране продавца."
            if price_list.is_active
            else "Прейскурант не активен: продавец видит цены активного списка."
        )
        self.activate_button.setEnabled(not price_list.is_active)
        self._rows = self.ctx.catalog.price_list_items(price_list.id)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows))
        for row, (item, override) in enumerate(self._rows):
            set_cell(self.table, row, 0, item.name)
            set_cell(
                self.table,
                row,
                1,
                format_money(item.price, self.ctx.currency),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            set_cell(
                self.table,
                row,
                2,
                format_money(override, self.ctx.currency)
                if override is not None
                else "базовая",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color="#1d4ed8" if override is not None else "#94a3b8",
                bold=override is not None,
            )

    def _selected_item(self) -> tuple[Item, int | None] | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "Новый прейскурант", "Название:")
        if not ok or not name.strip():
            return
        try:
            price_list = self.ctx.catalog.create_price_list(name)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.refresh()
        for row in range(self.list_widget.count()):
            if self.list_widget.item(row).data(Qt.ItemDataRole.UserRole) == price_list.id:
                self.list_widget.setCurrentRow(row)
                break

    def _rename(self) -> None:
        price_list = self._current_list()
        if price_list is None:
            warning(self, "Выберите прейскурант")
            return
        name, ok = QInputDialog.getText(
            self, "Переименовать", "Название:", text=price_list.name
        )
        if not ok:
            return
        try:
            self.ctx.catalog.rename_price_list(price_list.id, name)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        price_list = self._current_list()
        if price_list is None:
            warning(self, "Выберите прейскурант")
            return
        if not confirm(self, f"Удалить прейскурант «{price_list.name}»?"):
            return
        try:
            self.ctx.catalog.delete_price_list(price_list.id)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.refresh()

    def _activate(self) -> None:
        price_list = self._current_list()
        if price_list is None:
            return
        try:
            self.ctx.catalog.set_active_price_list(price_list.id)
        except ServiceError as exc:
            error(self, str(exc))
            return
        info(self, f"Прейскурант «{price_list.name}» теперь активен.")
        self.refresh()

    def _edit_price(self) -> None:
        price_list = self._current_list()
        selected = self._selected_item()
        if price_list is None or selected is None:
            warning(self, "Выберите позицию")
            return
        item, override = selected
        if PriceOverrideDialog(
            self.ctx, price_list.id, item, override, parent=self
        ).exec():
            self._load_items()

    def _clear_overrides(self) -> None:
        price_list = self._current_list()
        if price_list is None:
            return
        if not confirm(
            self,
            "Убрать все индивидуальные цены в этом прейскуранте?\n"
            "Все позиции будут использовать базовые цены.",
        ):
            return
        try:
            self.ctx.catalog.clear_price_list_overrides(price_list.id)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self._load_items()
