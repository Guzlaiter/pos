"""Stock receipts, write-offs, inventory and movement history."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...context import AppContext
from ...models import Item, User
from ...money import format_money
from ...services.catalog import STOCK_KIND_LABELS
from ...services.errors import ServiceError
from ..widgets import (
    PageHeader,
    center_window,
    error,
    make_table,
    set_cell,
    warning,
)


class StockMovementDialog(QDialog):
    def __init__(
        self,
        ctx: AppContext,
        item: Item,
        mode: str,
        user: User,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.item = item
        self.mode = mode  # in | out | set
        self.user = user
        titles = {
            "in": "Приход товара",
            "out": "Списание товара",
            "set": "Инвентаризация",
        }
        self.setWindowTitle(titles.get(mode, "Склад"))
        self.setModal(True)
        self.resize(440, 380)
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

        current = QLabel(
            f"Текущий остаток: {self.item.stock} {self.item.unit}"
        )
        current.setObjectName("InfoBanner")
        layout.addWidget(current)

        form = QFormLayout()
        form.setSpacing(10)
        self.quantity_spin = QSpinBox()
        self.quantity_spin.setRange(1 if self.mode != "set" else 0, 1_000_000)
        self.quantity_spin.setValue(
            self.item.stock if self.mode == "set" else 1
        )
        labels = {
            "in": "Количество к приходу",
            "out": "Количество к списанию",
            "set": "Фактический остаток",
        }
        form.addRow(labels.get(self.mode, "Количество"), self.quantity_spin)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Например: накладная № 42")
        form.addRow("Комментарий", self.note_edit)
        layout.addLayout(form)

        hint = QLabel(
            "Все движения сохраняются в истории склада и не удаляются."
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

    def _save(self) -> None:
        quantity = self.quantity_spin.value()
        try:
            if self.mode == "set":
                self.ctx.catalog.set_stock(
                    self.item.id, quantity, self.user.id, self.note_edit.text()
                )
            elif self.mode == "in":
                self.ctx.catalog.add_stock_movement(
                    self.item.id,
                    quantity,
                    "receipt",
                    self.user.id,
                    self.note_edit.text(),
                )
            else:
                self.ctx.catalog.add_stock_movement(
                    self.item.id,
                    -quantity,
                    "writeoff",
                    self.user.id,
                    self.note_edit.text(),
                )
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.accept()


class StockPage(QWidget):
    def __init__(self, ctx: AppContext, user: User, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.user = user
        self._items: list[Item] = []
        self._filtered: list[Item] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        header = PageHeader(
            "Склад",
            "Приход, списание и инвентаризация. Каждое движение фиксируется в истории.",
        )
        layout.addWidget(header)

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск позиции…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._render)
        filters.addWidget(self.search_edit, 1)
        self.only_selected_check = QCheckBox("История только по выбранной позиции")
        self.only_selected_check.toggled.connect(self._refresh_movements)
        filters.addWidget(self.only_selected_check)
        self.only_consumables_check = QCheckBox("Только расходники")
        self.only_consumables_check.toggled.connect(self._render)
        filters.addWidget(self.only_consumables_check)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        items_card = QFrame()
        items_card.setObjectName("Card")
        items_layout = QVBoxLayout(items_card)
        items_layout.setContentsMargins(12, 12, 12, 12)
        items_layout.setSpacing(8)
        items_title = QLabel("Остатки")
        items_title.setObjectName("SectionTitle")
        items_layout.addWidget(items_title)
        self.table = make_table(["Позиция", "Артикул", "Остаток", "Ед.", "Себестоимость", "Статус"])
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4, 5):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._refresh_movements)
        items_layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        in_button = QPushButton("Приход")
        in_button.setObjectName("PrimaryButton")
        in_button.clicked.connect(lambda: self._movement("in"))
        out_button = QPushButton("Списание")
        out_button.clicked.connect(lambda: self._movement("out"))
        set_button = QPushButton("Инвентаризация")
        set_button.clicked.connect(lambda: self._movement("set"))
        actions.addWidget(in_button)
        actions.addWidget(out_button)
        actions.addWidget(set_button)
        actions.addStretch(1)
        items_layout.addLayout(actions)
        splitter.addWidget(items_card)

        history_card = QFrame()
        history_card.setObjectName("Card")
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(12, 12, 12, 12)
        history_layout.setSpacing(8)
        history_title = QLabel("История движений")
        history_title.setObjectName("SectionTitle")
        history_layout.addWidget(history_title)
        self.movement_table = make_table(
            ["Дата", "Позиция", "Изменение", "Тип", "Пользователь", "Комментарий"]
        )
        movement_header = self.movement_table.horizontalHeader()
        movement_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        movement_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4):
            movement_header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        history_layout.addWidget(self.movement_table, 1)
        splitter.addWidget(history_card)
        splitter.setSizes([420, 260])
        layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        selected_id = self._selected_item().id if self._selected_item() else None
        self._items = self.ctx.catalog.items(include_inactive=False)
        self._render()
        if selected_id is not None:
            for row, item in enumerate(self._filtered):
                if item.id == selected_id:
                    self.table.selectRow(row)
                    break
        self._refresh_movements()

    def _render(self) -> None:
        keyword = self.search_edit.text().strip().casefold()
        threshold = self.ctx.settings.low_stock_threshold
        only_consumables = self.only_consumables_check.isChecked()
        self._filtered = [
            item
            for item in self._items
            if (not only_consumables or item.is_consumable)
            and (
                not keyword
                or keyword
                in f"{item.name} {item.sku or ''} {item.category_name or ''}".casefold()
            )
        ]
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._filtered))
        for row, item in enumerate(self._filtered):
            if not item.track_stock:
                status = "не ведётся"
                status_color = "#94a3b8"
            elif item.stock <= 0:
                status = "нет в наличии"
                status_color = "#b91c1c"
            elif item.stock <= threshold:
                status = "мало"
                status_color = "#b45309"
            else:
                status = "в наличии"
                status_color = "#15803d"
            values = [
                item.name,
                item.sku or "—",
                str(item.stock),
                item.unit,
                format_money(item.cost, self.ctx.currency),
                status,
            ]
            for column, value in enumerate(values):
                align = (
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    if column in (2, 4)
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                color = status_color if column == 5 else None
                set_cell(self.table, row, column, value, align=align, color=color)

    def _selected_item(self) -> Item | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._filtered):
            return self._filtered[row]
        return None

    def _movement(self, mode: str) -> None:
        item = self._selected_item()
        if item is None:
            warning(self, "Выберите позицию")
            return
        if not item.track_stock:
            warning(self, "Для этой позиции складской учёт не ведётся")
            return
        if StockMovementDialog(self.ctx, item, mode, self.user, parent=self).exec():
            self.refresh()

    def _refresh_movements(self) -> None:
        if not hasattr(self, "movement_table"):
            return
        only_selected = self.only_selected_check.isChecked()
        item = self._selected_item() if only_selected else None
        if only_selected and item is None:
            self.movement_table.setRowCount(0)
            return
        movements = self.ctx.catalog.stock_movements(
            limit=100, item_id=item.id if item else None
        )
        self.movement_table.setRowCount(0)
        self.movement_table.setRowCount(len(movements))
        for row, movement in enumerate(movements):
            delta = int(movement["qty"])
            values = [
                str(movement["created_at"])[:16],
                str(movement["item_name"]),
                f"{delta:+d} {movement['unit']}",
                STOCK_KIND_LABELS.get(str(movement["kind"]), str(movement["kind"])),
                str(movement["user_name"]),
                str(movement["note"] or ""),
            ]
            for column, value in enumerate(values):
                align = (
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    if column == 2
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                color = None
                if column == 2:
                    color = "#15803d" if delta > 0 else "#b91c1c"
                set_cell(self.movement_table, row, column, value, align=align, color=color)
