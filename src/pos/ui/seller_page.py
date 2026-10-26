"""Minimal seller screen: catalog, cart, receipt preview and payment."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..models import Item, SaleLineInput, User
from ..money import format_money
from ..services.errors import ServiceError
from ..services.receipts import build_preview_receipt, build_sale_receipt
from .payment_dialog import PaymentDialog
from .widgets import (
    PageHeader,
    TextDocumentDialog,
    confirm,
    error,
    info,
    make_table,
    set_cell,
    warning,
)


class SellerPage(QWidget):
    sale_completed = Signal()
    shift_requested = Signal()

    def __init__(self, ctx: AppContext, user: User, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.user = user
        self.cart: dict[int, int] = {}
        self._items: dict[int, Item] = {}
        self._filtered: list[Item] = []
        self._row_items: list[int] = []
        self._columns = 4
        self._build()
        self.refresh()

    # ------------------------------------------------------------------- build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        header = PageHeader(
            "Продажа", "Выберите товар или услугу, затем подготовьте чек к оплате."
        )
        self.shift_badge = QLabel("Смена не открыта")
        self.shift_badge.setObjectName("ShiftClosed")
        header.add_action(self.shift_badge)
        root.addWidget(header)

        filters = QHBoxLayout()
        filters.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Поиск товара или услуги по названию или артикулу…"
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._render_grid)
        self.search_edit.returnPressed.connect(self._search_enter)
        filters.addWidget(self.search_edit, 1)

        self.category_combo = QComboBox()
        self.category_combo.setMinimumWidth(220)
        self.category_combo.currentIndexChanged.connect(self._render_grid)
        filters.addWidget(self.category_combo)
        root.addLayout(filters)

        content = QHBoxLayout()
        content.setSpacing(14)

        catalog_card = QFrame()
        catalog_card.setObjectName("Card")
        catalog_layout = QVBoxLayout(catalog_card)
        catalog_layout.setContentsMargins(8, 8, 8, 8)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(6, 6, 6, 6)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.grid_host)
        catalog_layout.addWidget(self.scroll)
        content.addWidget(catalog_card, 3)

        content.addWidget(self._build_cart(), 2)
        root.addLayout(content, 1)

    def _build_cart(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumWidth(390)
        card.setMaximumWidth(500)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("Текущий чек")
        title.setObjectName("SectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.count_badge = QLabel("0 поз.")
        self.count_badge.setObjectName("Badge")
        title_row.addWidget(self.count_badge)
        layout.addLayout(title_row)

        self.shift_warning = QLabel()
        self.shift_warning.setObjectName("WarningBanner")
        self.shift_warning.setWordWrap(True)
        self.shift_warning.hide()
        layout.addWidget(self.shift_warning)

        self.cart_table = make_table(["Позиция", "Цена", "Кол-во", "Сумма"], stretch_last=False)
        self.cart_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.cart_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in (1, 2, 3):
            self.cart_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.cart_table.setMinimumHeight(240)
        layout.addWidget(self.cart_table, 1)

        actions = QHBoxLayout()
        self.plus_button = QPushButton("+")
        self.plus_button.setFixedWidth(42)
        self.plus_button.setToolTip("Увеличить количество")
        self.plus_button.clicked.connect(lambda: self._change_selected(1))
        self.minus_button = QPushButton("−")
        self.minus_button.setFixedWidth(42)
        self.minus_button.setToolTip("Уменьшить количество")
        self.minus_button.clicked.connect(lambda: self._change_selected(-1))
        remove_button = QPushButton("Удалить")
        remove_button.clicked.connect(self._remove_selected)
        clear_button = QPushButton("Очистить")
        clear_button.setObjectName("GhostButton")
        clear_button.clicked.connect(self._clear_cart)
        actions.addWidget(self.plus_button)
        actions.addWidget(self.minus_button)
        actions.addWidget(remove_button)
        actions.addStretch(1)
        actions.addWidget(clear_button)
        layout.addLayout(actions)

        totals = QHBoxLayout()
        total_caption = QLabel("К оплате")
        total_caption.setObjectName("Muted")
        totals.addWidget(total_caption)
        totals.addStretch(1)
        self.total_label = QLabel(format_money(0, self.ctx.currency))
        self.total_label.setObjectName("TotalValue")
        totals.addWidget(self.total_label)
        layout.addLayout(totals)

        self.preview_button = QPushButton("Предварительный чек")
        self.preview_button.clicked.connect(self._preview_receipt)
        layout.addWidget(self.preview_button)

        self.pay_button = QPushButton("Оплатить")
        self.pay_button.setObjectName("SuccessButton")
        self.pay_button.setMinimumHeight(52)
        self.pay_button.clicked.connect(self._pay)
        layout.addWidget(self.pay_button)
        return card

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        keyword = self.search_edit.text()
        current_category = self.category_combo.currentData()
        categories = self.ctx.catalog.categories(include_inactive=False)
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("Все категории", None)
        for category in categories:
            self.category_combo.addItem(category.name, category.id)
        index = self.category_combo.findData(current_category)
        self.category_combo.setCurrentIndex(max(0, index))
        self.category_combo.blockSignals(False)

        items = self.ctx.catalog.sellable_items()
        self._items = {item.id: item for item in items}
        self._filtered = items
        # Drop unavailable cart rows and clamp quantities to current stock.
        for item_id in list(self.cart):
            item = self._items.get(item_id)
            if item is None:
                self.cart.pop(item_id, None)
                continue
            if item.track_stock and item.stock <= 0:
                self.cart.pop(item_id, None)
            elif item.track_stock:
                self.cart[item_id] = min(self.cart[item_id], item.stock)
        self.search_edit.blockSignals(True)
        self.search_edit.setText(keyword)
        self.search_edit.blockSignals(False)
        self._render_grid()
        self._render_cart()
        self._update_shift_state()

    def _update_shift_state(self) -> None:
        shift = self.ctx.shifts.open_shift_for_user(self.user.id)
        if shift is not None:
            self.shift_badge.setObjectName("ShiftOpen")
            self.shift_badge.setText(f"Смена №{shift.id} открыта")
            self.shift_warning.hide()
        else:
            self.shift_badge.setObjectName("ShiftClosed")
            self.shift_badge.setText("Смена не открыта")
            self.shift_warning.setText(
                "Смена не открыта. Откройте смену кнопкой в верхней панели, "
                "чтобы принимать оплату."
            )
            self.shift_warning.show()
        self.shift_badge.style().unpolish(self.shift_badge)
        self.shift_badge.style().polish(self.shift_badge)
        self._update_pay_button(shift is not None)

    def _update_pay_button(self, shift_open: bool | None = None) -> None:
        if shift_open is None:
            shift_open = self.ctx.shifts.open_shift_for_user(self.user.id) is not None
        self.pay_button.setEnabled(bool(self.cart) and shift_open)
        self.preview_button.setEnabled(bool(self.cart))

    # ------------------------------------------------------------------- grid
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not hasattr(self, "scroll") or not hasattr(self, "_items"):
            return
        width = max(300, self.scroll.viewport().width())
        columns = max(2, min(6, width // 210))
        if columns != self._columns:
            self._columns = columns
            self._render_grid()

    def _category_matches(self, item: Item) -> bool:
        category_id = self.category_combo.currentData()
        return category_id is None or item.category_id == category_id

    def _matches(self, item: Item, keyword: str) -> bool:
        if not keyword:
            return True
        needle = keyword.casefold()
        haystack = " ".join(
            part for part in (item.name, item.sku or "", item.category_name or "") if part
        ).casefold()
        return needle in haystack

    def _render_grid(self) -> None:
        if not hasattr(self, "grid"):
            return
        while self.grid.count():
            entry = self.grid.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()

        keyword = self.search_edit.text().strip()
        self._filtered = [
            item
            for item in self._items.values()
            if self._category_matches(item) and self._matches(item, keyword)
        ]
        if not self._filtered:
            empty = QLabel("Ничего не найдено. Измените запрос или категорию.")
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(120)
            self.grid.addWidget(empty, 0, 0, 1, max(1, self._columns))
            return

        for index, item in enumerate(self._filtered):
            button = QPushButton()
            button.setObjectName("ProductButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(88)
            name = item.name if len(item.name) <= 34 else item.name[:33] + "…"
            if item.track_stock:
                stock_text = f"{item.stock} {item.unit}"
                if item.stock <= 0:
                    stock_text = "нет в наличии"
            else:
                stock_text = "услуга"
            button.setText(
                f"{name}\n{format_money(item.price, self.ctx.currency)}   ·   {stock_text}"
            )
            tooltip = (
                f"{item.name}\n{format_money(item.price, self.ctx.currency)}"
                f"\nОстаток: {item.stock if item.track_stock else '—'}"
            )
            if item.sku:
                tooltip += f"\nАртикул: {item.sku}"
            if item.category_name:
                tooltip += f"\nКатегория: {item.category_name}"
            button.setToolTip(tooltip)
            button.setEnabled(not item.track_stock or item.stock > 0)
            button.clicked.connect(lambda checked=False, it=item: self.add_to_cart(it))
            row, column = divmod(index, max(1, self._columns))
            self.grid.addWidget(button, row, column)
        for column in range(max(1, self._columns)):
            self.grid.setColumnStretch(column, 1)

    # ------------------------------------------------------------------- cart
    def add_to_cart(self, item: Item) -> None:
        if item.track_stock:
            in_cart = self.cart.get(item.id, 0)
            if in_cart >= item.stock:
                warning(
                    self,
                    f"На складе доступно только {item.stock} {item.unit} позиции "
                    f"«{item.name}».",
                )
                return
        self.cart[item.id] = self.cart.get(item.id, 0) + 1
        self._render_cart()

    def _selected_item_id(self) -> int | None:
        rows = self.cart_table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            if 0 <= row < len(self._row_items):
                return self._row_items[row]
        if len(self._row_items) == 1:
            return self._row_items[0]
        return None

    def _change_selected(self, delta: int) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            info(self, "Выберите позицию в чеке")
            return
        item = self._items.get(item_id)
        current = self.cart.get(item_id, 0)
        new_value = current + delta
        if new_value <= 0:
            self.cart.pop(item_id, None)
        else:
            if item is not None and item.track_stock and new_value > item.stock:
                warning(
                    self,
                    f"На складе доступно только {item.stock} {item.unit}.",
                )
                return
            self.cart[item_id] = new_value
        self._render_cart()

    def _remove_selected(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            info(self, "Выберите позицию в чеке")
            return
        self.cart.pop(item_id, None)
        self._render_cart()

    def _clear_cart(self) -> None:
        if self.cart and confirm(self, "Очистить текущий чек?"):
            self.cart.clear()
            self._render_cart()

    def _cart_rows(self) -> list[tuple[Item, int, int]]:
        rows: list[tuple[Item, int, int]] = []
        for item_id, qty in self.cart.items():
            item = self._items.get(item_id)
            if item is None:
                continue
            rows.append((item, qty, item.price * qty))
        return rows

    def _cart_total(self) -> int:
        return sum(total for _, _, total in self._cart_rows())

    def _render_cart(self) -> None:
        rows = self._cart_rows()
        self._row_items = [item.id for item, _, _ in rows]
        self.cart_table.setRowCount(0)
        self.cart_table.setRowCount(len(rows))
        for index, (item, qty, total) in enumerate(rows):
            set_cell(
                self.cart_table,
                index,
                0,
                item.name,
            ).setToolTip(item.name)
            set_cell(
                self.cart_table,
                index,
                1,
                format_money(item.price, self.ctx.currency),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            set_cell(
                self.cart_table,
                index,
                2,
                str(qty),
                align=Qt.AlignmentFlag.AlignCenter,
            )
            set_cell(
                self.cart_table,
                index,
                3,
                format_money(total, self.ctx.currency),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                bold=True,
            )
        count = sum(qty for qty in self.cart.values())
        self.count_badge.setText(f"{count} ед. · {len(rows)} поз.")
        total = self._cart_total()
        self.total_label.setText(format_money(total, self.ctx.currency))
        self._update_pay_button()
        if rows:
            self.cart_table.selectRow(len(rows) - 1)

    # ----------------------------------------------------------------- receipt
    def _preview_receipt(self) -> None:
        rows = self._cart_rows()
        if not rows:
            info(self, "Чек пуст")
            return
        lines = [
            (item.name, qty, item.price, total) for item, qty, total in rows
        ]
        text = build_preview_receipt(
            lines, self._cart_total(), self.user.display_name, self.ctx.settings
        )
        TextDocumentDialog("Предварительный просмотр чека", text, parent=self).exec()

    def _search_enter(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        query_folded = query.casefold()
        exact = next(
            (
                item
                for item in self._items.values()
                if (item.sku or "").casefold() == query_folded
            ),
            None,
        )
        if exact is not None:
            if exact.track_stock and exact.stock <= 0:
                warning(self, "Товара нет в наличии")
                return
            self.add_to_cart(exact)
            self.search_edit.clear()
            return
        if len(self._filtered) == 1:
            self.add_to_cart(self._filtered[0])
            self.search_edit.clear()

    # ----------------------------------------------------------------- payment
    def _pay(self) -> None:
        rows = self._cart_rows()
        if not rows:
            info(self, "Чек пуст")
            return
        shift = self.ctx.shifts.open_shift_for_user(self.user.id)
        if shift is None:
            warning(self, "Сначала откройте смену.")
            self.shift_requested.emit()
            return
        total = self._cart_total()
        payments = []
        if total > 0:
            methods = self.ctx.payments.list_methods()
            if not methods:
                error(self, "Нет активных способов оплаты. Обратитесь к администратору.")
                return
            dialog = PaymentDialog(total, methods, self.ctx.currency, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            payments = dialog.payments
        try:
            sale = self.ctx.sales.create_sale(
                user_id=self.user.id,
                shift_id=shift.id,
                lines=[
                    SaleLineInput(item_id=item.id, qty=qty, unit_price=item.price)
                    for item, qty, _ in rows
                ],
                payments=payments,
            )
        except ServiceError as exc:
            error(self, str(exc))
            self.refresh()
            return
        except Exception as exc:  # pragma: no cover - defensive
            error(self, f"Не удалось оформить продажу: {exc}")
            return

        self.cart.clear()
        self.refresh()
        self.sale_completed.emit()
        text = build_sale_receipt(sale, self.ctx.settings)
        TextDocumentDialog(
            f"Чек № {sale.number}",
            text,
            default_path=self.ctx.paths.receipt_dir / f"receipt-{sale.number}.txt",
            parent=self,
        ).exec()
