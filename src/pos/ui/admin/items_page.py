"""Catalog items: products and services."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...context import AppContext
from ...models import Item
from ...money import format_money
from ...services.errors import ServiceError
from ..widgets import (
    MoneySpinBox,
    PageHeader,
    center_window,
    confirm,
    error,
    make_table,
    set_cell,
    warning,
)

KIND_LABELS = {"product": "Товар", "service": "Услуга"}


class ItemDialog(QDialog):
    def __init__(
        self,
        ctx: AppContext,
        item: Item | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.item = item
        self.setWindowTitle("Позиция каталога")
        self.setModal(True)
        self.resize(640, 800)
        self._build()
        center_window(self)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("Новая позиция" if self.item is None else f"Изменить: {self.item.name}")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.name_edit = QLineEdit(self.item.name if self.item else "")
        self.name_edit.setPlaceholderText("Например: Кофе латте 300 мл")
        form.addRow("Название *", self.name_edit)

        self.sku_edit = QLineEdit(self.item.sku if self.item and self.item.sku else "")
        self.sku_edit.setPlaceholderText("Необязательно, но полезно для сканера")
        form.addRow("Артикул", self.sku_edit)

        self.kind_combo = QComboBox()
        for key, label in KIND_LABELS.items():
            self.kind_combo.addItem(label, key)
        if self.item:
            self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(self.item.kind)))
        self.kind_combo.currentIndexChanged.connect(self._reload_categories)
        form.addRow("Тип *", self.kind_combo)

        self.category_combo = QComboBox()
        form.addRow("Категория", self.category_combo)

        self.price_spin = MoneySpinBox()
        if self.item:
            self.price_spin.set_cents(self.item.price)
        form.addRow("Цена продажи *", self.price_spin)

        self.cost_spin = MoneySpinBox()
        if self.item:
            self.cost_spin.set_cents(self.item.cost)
        form.addRow("Себестоимость", self.cost_spin)

        self.unit_edit = QLineEdit(self.item.unit if self.item else "шт")
        form.addRow("Единица измерения", self.unit_edit)

        self.track_check = QCheckBox("Вести складской учёт")
        self.track_check.setChecked(self.item.track_stock if self.item else True)
        self.track_check.toggled.connect(self._update_stock_controls)
        form.addRow("", self.track_check)

        self.consumable_check = QCheckBox(
            "Это расходник (материал для услуг, не продаётся)"
        )
        self.consumable_check.setChecked(self.item.is_consumable if self.item else False)
        self.consumable_check.toggled.connect(self._update_stock_controls)
        form.addRow("", self.consumable_check)

        self.stock_label = QLabel("Начальный остаток")
        self.initial_stock_spin = QSpinBox()
        self.initial_stock_spin.setRange(0, 1_000_000)
        self.initial_stock_spin.setValue(0)
        form.addRow(self.stock_label, self.initial_stock_spin)

        if self.item and self.item.track_stock:
            current = QLabel(
                f"Текущий остаток: {self.item.stock} {self.item.unit}. "
                "Изменяйте его в разделе «Склад»."
            )
            current.setObjectName("Muted")
            current.setWordWrap(True)
            form.addRow("", current)

        self.active_check = QCheckBox("Позиция доступна для продажи")
        self.active_check.setChecked(self.item.is_active if self.item else True)
        form.addRow("", self.active_check)

        layout.addLayout(form)

        self.recipe_box = self._build_recipe_box()
        layout.addWidget(self.recipe_box)
        if self.item is not None and self.item.kind == "service":
            for consumable, qty in self.ctx.catalog.service_consumables(self.item.id):
                self._add_recipe_row(consumable.id, qty)

        hint = QLabel(
            "* — обязательные поля. Себестоимость нужна для расчёта прибыли. "
            "Расходники услуги списываются со склада автоматически при продаже."
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

        self._reload_categories()
        self._update_stock_controls()

    def _build_recipe_box(self) -> QGroupBox:
        self._consumables = self.ctx.catalog.consumable_items(include_inactive=True)
        box = QGroupBox("Расходники услуги")
        box.setMaximumHeight(250)
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        hint = QLabel(
            "Укажите, сколько материала списывать за одну единицу услуги. "
            "Один расходник можно добавить в несколько услуг — склад общий."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.recipe_scroll = QScrollArea()
        self.recipe_scroll.setWidgetResizable(True)
        self.recipe_scroll.setMinimumHeight(90)
        self.recipe_host = QWidget()
        self.recipe_rows_layout = QVBoxLayout(self.recipe_host)
        self.recipe_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.recipe_rows_layout.setSpacing(6)
        self.recipe_rows_layout.addStretch(1)
        self.recipe_scroll.setWidget(self.recipe_host)
        layout.addWidget(self.recipe_scroll, 1)

        add_button = QPushButton("Добавить расходник")
        add_button.clicked.connect(self._add_recipe_row)
        add_button.setEnabled(bool(self._consumables))
        layout.addWidget(add_button)

        if not self._consumables:
            empty = QLabel(
                "Расходников пока нет. Создайте товар и отметьте его как расходник."
            )
            empty.setObjectName("WarningBanner")
            empty.setWordWrap(True)
            layout.addWidget(empty)
        return box

    def _add_recipe_row(self, item_id: int | None = None, qty: int = 1) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        combo = QComboBox()
        combo.addItem("— выберите расходник —", None)
        for consumable in self._consumables:
            label = consumable.name
            if not consumable.is_active:
                label += " (отключён)"
            combo.addItem(label, consumable.id)
        index = combo.findData(item_id)
        combo.setCurrentIndex(max(0, index))
        row_layout.addWidget(combo, 1)

        caption = QLabel("на 1 ед.")
        caption.setObjectName("Muted")
        row_layout.addWidget(caption)

        spin = QSpinBox()
        spin.setRange(1, 1_000_000)
        spin.setValue(max(1, int(qty)))
        spin.setMaximumWidth(100)
        row_layout.addWidget(spin)

        remove = QPushButton("Удалить")
        remove.clicked.connect(lambda: self._remove_recipe_row(row))
        row_layout.addWidget(remove)

        # Keep the stretch item last so the rows stay at the top.
        self.recipe_rows_layout.insertWidget(
            max(0, self.recipe_rows_layout.count() - 1), row
        )

    def _remove_recipe_row(self, row: QWidget) -> None:
        self.recipe_rows_layout.removeWidget(row)
        row.deleteLater()

    def _collect_consumables(self) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        for index in range(self.recipe_rows_layout.count()):
            row = self.recipe_rows_layout.itemAt(index).widget()
            if row is None:
                continue
            combo = row.findChild(QComboBox)
            spin = row.findChild(QSpinBox)
            if combo is None or spin is None:
                continue
            item_id = combo.currentData()
            if item_id is None:
                continue
            result.append((int(item_id), spin.value()))
        return result

    def _reload_categories(self) -> None:
        current = self.category_combo.currentData() if self.category_combo.count() else None
        if self.item and self.category_combo.count() == 0:
            current = self.item.category_id
        kind = self.kind_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("Без категории", None)
        for category in self.ctx.catalog.categories(include_inactive=False):
            if category.kind in ("any", kind):
                self.category_combo.addItem(category.name, category.id)
        index = self.category_combo.findData(current)
        self.category_combo.setCurrentIndex(max(0, index))
        self.category_combo.blockSignals(False)

    def _update_stock_controls(self) -> None:
        is_product = self.kind_combo.currentData() == "product"
        is_service = self.kind_combo.currentData() == "service"
        self.consumable_check.setEnabled(is_product)
        if not is_product and self.consumable_check.isChecked():
            self.consumable_check.blockSignals(True)
            self.consumable_check.setChecked(False)
            self.consumable_check.blockSignals(False)
        if not is_product:
            self.track_check.setChecked(False)
        is_consumable = is_product and self.consumable_check.isChecked()
        if is_consumable:
            self.track_check.setChecked(True)
        self.track_check.setEnabled(is_product and not is_consumable)
        self.active_check.setText(
            "Позиция активна"
            if is_consumable
            else "Позиция доступна для продажи"
        )
        initial_visible = self.item is None and is_product and self.track_check.isChecked()
        self.stock_label.setVisible(initial_visible)
        self.initial_stock_spin.setVisible(initial_visible)
        if hasattr(self, "recipe_box"):
            self.recipe_box.setVisible(is_service)

    def _save(self) -> None:
        kind = self.kind_combo.currentData()
        is_consumable = self.consumable_check.isChecked()
        if is_consumable:
            kind = "product"
        values = dict(
            name=self.name_edit.text(),
            sku=self.sku_edit.text(),
            kind=kind,
            category_id=self.category_combo.currentData(),
            price=self.price_spin.cents(),
            cost=self.cost_spin.cents(),
            unit=self.unit_edit.text(),
            track_stock=self.track_check.isChecked(),
            is_active=self.active_check.isChecked(),
            is_consumable=is_consumable,
            consumables=self._collect_consumables() if kind == "service" else [],
        )
        try:
            if self.item is None:
                self.ctx.catalog.create_item(
                    **values, initial_stock=self.initial_stock_spin.value()
                )
            else:
                self.ctx.catalog.update_item(self.item.id, **values)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.accept()


class ItemsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._items: list[Item] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = PageHeader(
            "Товары и услуги",
            "Каталог позиций, цены и себестоимость. Расходники не показываются "
            "продавцу, а их остаток списывается при продаже услуг.",
        )
        add_button = QPushButton("Добавить позицию")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self._add)
        header.add_action(add_button)
        layout.addWidget(header)

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по названию или артикулу…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._render)
        filters.addWidget(self.search_edit, 1)
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Все типы", None)
        self.kind_combo.addItem("Товары", "product")
        self.kind_combo.addItem("Услуги", "service")
        self.kind_combo.addItem("Расходники", "consumable")
        self.kind_combo.currentIndexChanged.connect(self._render)
        filters.addWidget(self.kind_combo)
        self.show_inactive = QCheckBox("Показать отключённые")
        self.show_inactive.toggled.connect(self._render)
        filters.addWidget(self.show_inactive)
        layout.addLayout(filters)

        self.table = make_table(
            ["Артикул", "Название", "Тип", "Категория", "Цена", "Себестоимость", "Остаток", "Активна"]
        )
        header_view = self.table.horizontalHeader()
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5, 6, 7):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._edit_selected)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        edit_button = QPushButton("Изменить")
        edit_button.clicked.connect(self._edit_selected)
        toggle_button = QPushButton("Включить / отключить")
        toggle_button.clicked.connect(self._toggle_selected)
        delete_button = QPushButton("Удалить")
        delete_button.setObjectName("DangerButton")
        delete_button.clicked.connect(self._delete_selected)
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.refresh)
        actions.addWidget(edit_button)
        actions.addWidget(toggle_button)
        actions.addWidget(delete_button)
        actions.addStretch(1)
        actions.addWidget(refresh_button)
        layout.addLayout(actions)

    def refresh(self) -> None:
        self._items = self.ctx.catalog.items(include_inactive=True)
        self._render()

    def _render(self) -> None:
        keyword = self.search_edit.text().strip().casefold()
        kind = self.kind_combo.currentData()
        show_inactive = self.show_inactive.isChecked()
        low_threshold = self.ctx.settings.low_stock_threshold
        filtered: list[Item] = []
        for item in self._items:
            if not show_inactive and not item.is_active:
                continue
            if kind == "consumable":
                if not item.is_consumable:
                    continue
            elif kind:
                if item.kind != kind or item.is_consumable:
                    continue
            if keyword:
                haystack = f"{item.name} {item.sku or ''} {item.category_name or ''}".casefold()
                if keyword not in haystack:
                    continue
            filtered.append(item)

        self.table.setRowCount(0)
        self.table.setRowCount(len(filtered))
        for row, item in enumerate(filtered):
            stock_text = "—"
            stock_color = None
            if item.kind == "product":
                stock_text = f"{item.stock} {item.unit}"
                if item.track_stock and item.stock <= low_threshold:
                    stock_color = "#b91c1c"
            values = [
                item.sku or "—",
                item.name,
                "Расходник" if item.is_consumable else KIND_LABELS.get(item.kind, item.kind),
                item.category_name or "—",
                format_money(item.price, self.ctx.currency),
                format_money(item.cost, self.ctx.currency),
                stock_text,
                "да" if item.is_active else "нет",
            ]
            for column, value in enumerate(values):
                color = None
                if column == 6 and stock_color:
                    color = stock_color
                if not item.is_active:
                    color = "#94a3b8"
                align = (
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    if column in (4, 5, 6)
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                set_cell(self.table, row, column, value, align=align, color=color)
            self.table.item(row, 1).setToolTip(item.name)
        # Keep filtered items aligned with table rows for selection handling.
        self._filtered = filtered

    def _selected(self) -> Item | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        filtered = getattr(self, "_filtered", [])
        if 0 <= row < len(filtered):
            return filtered[row]
        return None

    def _add(self) -> None:
        if ItemDialog(self.ctx, parent=self).exec():
            self.refresh()

    def _edit_selected(self) -> None:
        item = self._selected()
        if item is None:
            warning(self, "Выберите позицию")
            return
        if ItemDialog(self.ctx, item, parent=self).exec():
            self.refresh()

    def _toggle_selected(self) -> None:
        item = self._selected()
        if item is None:
            warning(self, "Выберите позицию")
            return
        try:
            self.ctx.catalog.set_item_active(item.id, not item.is_active)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.refresh()

    def _delete_selected(self) -> None:
        item = self._selected()
        if item is None:
            warning(self, "Выберите позицию")
            return
        if not confirm(
            self,
            f"Удалить позицию «{item.name}»?\n"
            "Если она уже использовалась в продажах, удаление будет запрещено.",
        ):
            return
        try:
            self.ctx.catalog.delete_item(item.id)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.refresh()
