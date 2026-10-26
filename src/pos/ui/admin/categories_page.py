"""Category management."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...context import AppContext
from ...models import Category
from ...services.errors import ServiceError
from ..widgets import (
    PageHeader,
    center_window,
    confirm,
    error,
    fill_table,
    make_table,
    warning,
)

KIND_LABELS = {"any": "Любой", "product": "Товар", "service": "Услуга"}


class CategoryDialog(QDialog):
    def __init__(
        self,
        ctx: AppContext,
        category: Category | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.category = category
        self.setWindowTitle("Категория")
        self.setModal(True)
        self.resize(430, 310)
        self._build()
        center_window(self)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit(self.category.name if self.category else "")
        self.name_edit.setPlaceholderText("Например: Напитки")
        form.addRow("Название", self.name_edit)

        self.kind_combo = QComboBox()
        for key, label in KIND_LABELS.items():
            self.kind_combo.addItem(label, key)
        if self.category:
            self.kind_combo.setCurrentIndex(
                max(0, self.kind_combo.findData(self.category.kind))
            )
        form.addRow("Тип категории", self.kind_combo)

        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(-9999, 9999)
        self.sort_spin.setValue(self.category.sort_order if self.category else 0)
        form.addRow("Порядок сортировки", self.sort_spin)

        self.active_check = QCheckBox("Категория активна")
        self.active_check.setChecked(self.category.is_active if self.category else True)
        form.addRow("", self.active_check)
        layout.addLayout(form)
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
        try:
            if self.category:
                self.ctx.catalog.update_category(
                    self.category.id,
                    self.name_edit.text(),
                    self.kind_combo.currentData(),
                    self.sort_spin.value(),
                    self.active_check.isChecked(),
                )
            else:
                self.ctx.catalog.create_category(
                    self.name_edit.text(),
                    self.kind_combo.currentData(),
                    self.sort_spin.value(),
                    self.active_check.isChecked(),
                )
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.accept()


class CategoriesPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._categories: list[Category] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = PageHeader(
            "Категории",
            "Группируйте товары и услуги. Категории помогают продавцу быстрее находить позиции.",
        )
        add_button = QPushButton("Добавить категорию")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self._add)
        header.add_action(add_button)
        layout.addWidget(header)

        self.table = make_table(["Название", "Тип", "Порядок", "Активна"])
        self.table.doubleClicked.connect(self._edit_selected)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        edit_button = QPushButton("Изменить")
        edit_button.clicked.connect(self._edit_selected)
        delete_button = QPushButton("Удалить")
        delete_button.setObjectName("DangerButton")
        delete_button.clicked.connect(self._delete_selected)
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.refresh)
        actions.addWidget(edit_button)
        actions.addWidget(delete_button)
        actions.addStretch(1)
        actions.addWidget(refresh_button)
        layout.addLayout(actions)

    def refresh(self) -> None:
        self._categories = self.ctx.catalog.categories(include_inactive=True)
        fill_table(
            self.table,
            [
                [
                    category.name,
                    KIND_LABELS.get(category.kind, category.kind),
                    str(category.sort_order),
                    "да" if category.is_active else "нет",
                ]
                for category in self._categories
            ],
        )

    def _selected(self) -> Category | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._categories):
            return self._categories[row]
        return None

    def _add(self) -> None:
        if CategoryDialog(self.ctx, parent=self).exec():
            self.refresh()

    def _edit_selected(self) -> None:
        category = self._selected()
        if category is None:
            warning(self, "Выберите категорию")
            return
        if CategoryDialog(self.ctx, category, parent=self).exec():
            self.refresh()

    def _delete_selected(self) -> None:
        category = self._selected()
        if category is None:
            warning(self, "Выберите категорию")
            return
        if not confirm(
            self,
            f"Удалить категорию «{category.name}»?\n"
            "Позиции из неё останутся, но станут без категории.",
        ):
            return
        try:
            self.ctx.catalog.delete_category(category.id)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.refresh()
