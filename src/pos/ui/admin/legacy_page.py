"""Legacy database import wizard: pick file, tables, map columns, import."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...context import AppContext
from ...models import User
from ...services.errors import ServiceError
from ...services.legacy import (
    TARGETS,
    FieldSpec,
    ImportOptions,
    LegacyImportService,
    LegacySource,
    TableInfo,
    guess_target,
    suggest_mapping,
    target_spec,
)
from ..widgets import (
    PageHeader,
    confirm,
    error,
    fill_table,
    info,
    make_table,
    warning,
)


class MappingEditor(QWidget):
    """Column mapping for one source table."""

    def __init__(
        self,
        ctx: AppContext,
        source: LegacySource,
        table: TableInfo,
        target: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.source = source
        self.table_info = table
        self.target = target
        self.spec = target_spec(target)
        self._combos: dict[str, QComboBox] = {}
        self._build()
        self._apply_mapping(suggest_mapping(target, table.columns))

    # ------------------------------------------------------------------- build
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel(
            f"Таблица «{self.table_info.name}»  →  {self.spec.label}"
        )
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            f"Строк: {self.table_info.row_count}. Сопоставьте поля старой базы "
            "с полями новой. Обязательные поля отмечены *."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        tools = QHBoxLayout()
        auto_button = QPushButton("Автоопределение")
        auto_button.clicked.connect(self._auto_map)
        preview_button = QPushButton("Предпросмотр 20 строк")
        preview_button.clicked.connect(self.preview)
        tools.addWidget(auto_button)
        tools.addWidget(preview_button)
        tools.addStretch(1)
        self.status_label = QLabel()
        self.status_label.setObjectName("Muted")
        tools.addWidget(self.status_label)
        layout.addLayout(tools)

        self.fields_table = QTableWidget(0, 2)
        self.fields_table.setHorizontalHeaderLabels(["Поле новой базы", "Откуда взять"])
        self.fields_table.verticalHeader().setVisible(False)
        self.fields_table.setShowGrid(False)
        self.fields_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fields_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.fields_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.fields_table.verticalHeader().setDefaultSectionSize(38)
        self.fields_table.setMaximumHeight(290)
        layout.addWidget(self.fields_table)

        options = QGroupBox("Параметры импорта")
        options_layout = QHBoxLayout(options)
        options_layout.setSpacing(14)
        self.price_units_combo = QComboBox()
        self.price_units_combo.addItem("Цены в рублях", "rub")
        self.price_units_combo.addItem("Цены уже в копейках", "cents")
        price_label = QLabel("Единицы цен:")
        options_layout.addWidget(price_label)
        options_layout.addWidget(self.price_units_combo)
        self.update_check = QCheckBox("Обновлять существующие")
        self.update_check.setChecked(True)
        options_layout.addWidget(self.update_check)
        self.stock_check = QCheckBox("Импортировать остатки")
        self.stock_check.setChecked(True)
        options_layout.addWidget(self.stock_check)
        options_layout.addStretch(1)
        options.setVisible(self.target == "item")
        layout.addWidget(options)

        preview_title = QLabel("Предпросмотр результата")
        preview_title.setObjectName("SectionTitle")
        layout.addWidget(preview_title)
        self.preview_table = make_table(["Пока нет данных"])
        self.preview_table.setMinimumHeight(170)
        layout.addWidget(self.preview_table, 1)

        self._build_field_rows()

    def _build_field_rows(self) -> None:
        fields = self.spec.fields
        self.fields_table.setRowCount(len(fields))
        for row, field in enumerate(fields):
            label = field.label + (" *" if field.required else "")
            item = QTableWidgetItem(label)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.fields_table.setItem(row, 0, item)

            combo = QComboBox()
            combo.addItem("— не задано —", "")
            for column in self.table_info.columns:
                combo.addItem(f"Колонка: {column}", f"col:{column}")
            for constant_label, constant_value in field.constants:
                combo.addItem(f"Значение: {constant_label}", constant_value)
            self.fields_table.setCellWidget(row, 1, combo)
            self._combos[field.key] = combo

    # ------------------------------------------------------------------ mapping
    def _apply_mapping(self, mapping: dict[str, str]) -> None:
        for key, combo in self._combos.items():
            value = mapping.get(key, "")
            index = combo.findData(value)
            if index < 0:
                index = 0
            combo.setCurrentIndex(index)

    def _auto_map(self) -> None:
        self._apply_mapping(suggest_mapping(self.target, self.table_info.columns))
        self.status_label.setText("Сопоставление обновлено")

    def _current_mapping(self) -> dict[str, str]:
        return {key: combo.currentData() or "" for key, combo in self._combos.items()}

    def options(self) -> ImportOptions:
        return ImportOptions(
            price_units=self.price_units_combo.currentData() or "rub",
            update_existing=self.update_check.isChecked(),
            import_stock=self.stock_check.isChecked(),
        )

    def validate(self) -> str | None:
        mapping = self._current_mapping()
        for field in self.spec.fields:
            if field.required and not mapping.get(field.key):
                return f"Не сопоставлено обязательное поле «{field.label}»"
        if not mapping.get("name"):
            return "Не сопоставлено поле «Название»"
        return None

    # ---------------------------------------------------------------- preview
    def preview(self) -> None:
        problem = self.validate()
        if problem:
            warning(self, problem)
            return
        try:
            rows = self.source.read_rows(self.table_info.name, limit=20)
            headers, lines = self.ctx.legacy.preview(
                self.target, rows, self._current_mapping(), self.options()
            )
        except ServiceError as exc:
            error(self, str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive
            error(self, f"Ошибка предпросмотра: {exc}")
            return
        self.preview_table.clear()
        self.preview_table.setColumnCount(len(headers))
        self.preview_table.setHorizontalHeaderLabels(headers)
        self.preview_table.setRowCount(0)
        fill_table(self.preview_table, lines, align_right=set(range(len(headers))))
        self.preview_table.resizeColumnsToContents()
        self.preview_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.status_label.setText(f"Показано {len(lines)} строк")


class LegacyImportPage(QWidget):
    import_completed = Signal()

    def __init__(self, ctx: AppContext, user: User, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.user = user
        self.source: LegacySource | None = None
        self.tables: list[TableInfo] = []
        self.editors: list[MappingEditor] = []
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = PageHeader(
            "Импорт из старой базы",
            "Откройте файл SQLite или CSV, выберите таблицы и сопоставьте старые "
            "колонки с полями новой системы. Перед импортом создаётся резервная копия.",
        )
        layout.addWidget(header)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_step_one())
        self.stack.addWidget(self._build_step_two())
        layout.addWidget(self.stack, 1)

    # ------------------------------------------------------------------ step 1
    def _build_step_one(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        source_card = QFrame()
        source_card.setObjectName("Card")
        source_layout = QVBoxLayout(source_card)
        source_layout.setContentsMargins(16, 14, 16, 14)
        source_layout.setSpacing(8)
        source_title = QLabel("1. Файл старой программы")
        source_title.setObjectName("SectionTitle")
        source_layout.addWidget(source_title)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Выберите файл .db, .sqlite, .sqlite3 или .csv")
        row.addWidget(self.path_edit, 1)
        browse_button = QPushButton("Открыть файл…")
        browse_button.setObjectName("PrimaryButton")
        browse_button.clicked.connect(self._browse)
        row.addWidget(browse_button)
        source_layout.addLayout(row)
        self.file_info = QLabel(
            "Поддерживаются базы SQLite и CSV. Файл открывается только для чтения — "
            "старая база не изменяется."
        )
        self.file_info.setObjectName("Muted")
        self.file_info.setWordWrap(True)
        source_layout.addWidget(self.file_info)
        layout.addWidget(source_card)

        tables_card = QFrame()
        tables_card.setObjectName("Card")
        tables_layout = QVBoxLayout(tables_card)
        tables_layout.setContentsMargins(16, 14, 16, 14)
        tables_layout.setSpacing(8)
        table_title = QLabel("2. Таблицы и назначение")
        table_title.setObjectName("SectionTitle")
        tables_layout.addWidget(table_title)
        self.tables_table = QTableWidget(0, 4)
        self.tables_table.setHorizontalHeaderLabels(
            ["", "Таблица", "Строк", "Импортировать как"]
        )
        self.tables_table.verticalHeader().setVisible(False)
        self.tables_table.setShowGrid(False)
        self.tables_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tables_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.tables_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.tables_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.tables_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.tables_table.verticalHeader().setDefaultSectionSize(42)
        tables_layout.addWidget(self.tables_table, 1)

        actions = QHBoxLayout()
        self.check_all_button = QPushButton("Выбрать все")
        self.check_all_button.clicked.connect(lambda: self._set_all_checks(True))
        uncheck_button = QPushButton("Снять все")
        uncheck_button.clicked.connect(lambda: self._set_all_checks(False))
        next_button = QPushButton("Далее: сопоставление →")
        next_button.setObjectName("PrimaryButton")
        next_button.clicked.connect(self._to_step_two)
        actions.addWidget(self.check_all_button)
        actions.addWidget(uncheck_button)
        actions.addStretch(1)
        actions.addWidget(next_button)
        tables_layout.addLayout(actions)
        layout.addWidget(tables_card, 1)
        return page

    def _browse(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Файл старой базы",
            "",
            "Базы данных (*.db *.sqlite *.sqlite3 *.csv);;SQLite (*.db *.sqlite *.sqlite3);;CSV (*.csv);;Все файлы (*.*)",
        )
        if not filename:
            return
        try:
            source = LegacySource(filename)
            tables = source.tables()
        except ServiceError as exc:
            error(self, str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive
            error(self, f"Не удалось прочитать файл: {exc}")
            return
        self.source = source
        self.tables = tables
        self.path_edit.setText(str(Path(filename)))
        self.file_info.setText(
            f"Файл: {Path(filename).name}   ·   таблиц: {len(tables)}   ·   "
            "доступ только для чтения"
        )
        self._fill_tables()

    def _fill_tables(self) -> None:
        self.tables_table.setRowCount(0)
        self.tables_table.setRowCount(len(self.tables))
        for row, table in enumerate(self.tables):
            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
            )
            check.setCheckState(
                Qt.CheckState.Checked if table.row_count else Qt.CheckState.Unchecked
            )
            self.tables_table.setItem(row, 0, check)

            name_item = QTableWidgetItem(table.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tables_table.setItem(row, 1, name_item)

            count_item = QTableWidgetItem(str(table.row_count))
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.tables_table.setItem(row, 2, count_item)

            combo = QComboBox()
            combo.addItem("— не импортировать —", "")
            for key, spec in TARGETS.items():
                combo.addItem(spec.label, key)
            guess = guess_target(table.name)
            if guess:
                combo.setCurrentIndex(combo.findData(guess))
            self.tables_table.setCellWidget(row, 3, combo)

    def _set_all_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.tables_table.rowCount()):
            item = self.tables_table.item(row, 0)
            if item:
                item.setCheckState(state)

    # ------------------------------------------------------------------ step 2
    def _build_step_two(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        back_button = QPushButton("← Назад к таблицам")
        back_button.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        top.addWidget(back_button)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("Muted")
        top.addWidget(self.summary_label)
        top.addStretch(1)
        import_button = QPushButton("Импортировать")
        import_button.setObjectName("PrimaryButton")
        import_button.clicked.connect(self._run_import)
        top.addWidget(import_button)
        layout.addLayout(top)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(180)
        self.report.setPlaceholderText("Результат импорта появится здесь.")
        layout.addWidget(self.report)
        return page

    def _to_step_two(self) -> None:
        if self.source is None:
            warning(self, "Сначала выберите файл")
            return
        selected: list[tuple[TableInfo, str]] = []
        for row in range(self.tables_table.rowCount()):
            check = self.tables_table.item(row, 0)
            if check is None or check.checkState() != Qt.CheckState.Checked:
                continue
            combo = self.tables_table.cellWidget(row, 3)
            target = combo.currentData() if isinstance(combo, QComboBox) else ""
            if not target:
                warning(
                    self,
                    f"Для таблицы «{self.tables[row].name}» не выбрано назначение.",
                )
                return
            selected.append((self.tables[row], target))
        if not selected:
            warning(self, "Выберите хотя бы одну таблицу")
            return

        self.tabs.clear()
        self.editors.clear()
        for table, target in selected:
            editor = MappingEditor(self.ctx, self.source, table, target, self)
            self.editors.append(editor)
            self.tabs.addTab(editor, f"{table.name} → {target_spec(target).label}")
        self.summary_label.setText(
            f"Выбрано таблиц: {len(selected)}. Проверьте сопоставление и нажмите «Импортировать»."
        )
        self.report.clear()
        self.stack.setCurrentIndex(1)

    def _run_import(self) -> None:
        if not self.editors:
            warning(self, "Нет выбранных таблиц")
            return
        for editor in self.editors:
            problem = editor.validate()
            if problem:
                self.tabs.setCurrentWidget(editor)
                warning(self, problem)
                return
        if not confirm(
            self,
            "Импортировать выбранные таблицы?\n\n"
            "Перед импортом автоматически создаётся резервная копия. "
            "Существующие позиции с совпадающим артикулом или названием будут обновлены.",
        ):
            return

        self.report.clear()
        lines: list[str] = []
        failures = 0
        for editor in self.editors:
            try:
                result = self.ctx.legacy.import_table(
                    editor.source,
                    editor.table_info.name,
                    editor.target,
                    editor._current_mapping(),
                    editor.options(),
                    self.user.id,
                )
            except ServiceError as exc:
                failures += 1
                lines.append(
                    f"=== {editor.table_info.name} → {editor.target} ===\n"
                    f"ОШИБКА: {exc}\n"
                )
                continue
            except Exception as exc:  # pragma: no cover - defensive
                failures += 1
                lines.append(
                    f"=== {editor.table_info.name} → {editor.target} ===\n"
                    f"НЕОЖИДАННАЯ ОШИБКА: {exc}\n"
                )
                continue
            lines.append(
                f"=== {editor.table_info.name} → {target_spec(editor.target).label} ===\n"
                f"{result.summary()}\n"
            )
            for message in result.errors[:20]:
                lines.append(f"  · {message}\n")
            if len(result.errors) > 20:
                lines.append(f"  … ещё ошибок: {len(result.errors) - 20}\n")
        self.report.setPlainText("".join(lines))
        self.import_completed.emit()
        if failures:
            error(
                self,
                f"Импорт завершён с ошибками ({failures} таблиц). Подробности ниже.",
            )
        else:
            info(self, "Импорт завершён. Подробности в отчёте ниже.")
