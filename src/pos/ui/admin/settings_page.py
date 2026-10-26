"""Application settings and database maintenance."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ...context import AppContext
from ...services.errors import ServiceError
from ..widgets import PageHeader, error, info, warning


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = PageHeader(
            "Настройки",
            "Реквизиты для чека, валюта, низкий остаток и резервные копии.",
        )
        layout.addWidget(header)

        content = QHBoxLayout()
        content.setSpacing(14)

        form_card = QFrame()
        form_card.setObjectName("Card")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(18, 16, 18, 16)
        form_layout.setSpacing(10)
        form_title = QLabel("Организация и чек")
        form_title.setObjectName("SectionTitle")
        form_layout.addWidget(form_title)

        form = QFormLayout()
        form.setSpacing(10)
        self.company_edit = QLineEdit()
        form.addRow("Название организации", self.company_edit)
        self.address_edit = QLineEdit()
        form.addRow("Адрес", self.address_edit)
        self.phone_edit = QLineEdit()
        form.addRow("Телефон", self.phone_edit)
        self.currency_edit = QLineEdit()
        self.currency_edit.setMaxLength(4)
        self.currency_edit.setMaximumWidth(90)
        form.addRow("Валюта", self.currency_edit)
        self.footer_edit = QPlainTextEdit()
        self.footer_edit.setMaximumHeight(80)
        form.addRow("Текст внизу чека", self.footer_edit)
        self.low_stock_spin = QSpinBox()
        self.low_stock_spin.setRange(0, 100_000)
        form.addRow("Порог низкого остатка", self.low_stock_spin)
        form_layout.addLayout(form)

        hint = QLabel(
            "Название, адрес и телефон печатаются в шапке чека. "
            "Валюта используется во всём интерфейсе."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        form_layout.addWidget(hint)

        save_button = QPushButton("Сохранить настройки")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save)
        form_layout.addWidget(save_button)
        form_layout.addStretch(1)
        content.addWidget(form_card, 2)

        right = QVBoxLayout()
        right.setSpacing(14)

        backup_card = QFrame()
        backup_card.setObjectName("Card")
        backup_layout = QVBoxLayout(backup_card)
        backup_layout.setContentsMargins(18, 16, 18, 16)
        backup_layout.setSpacing(10)
        backup_title = QLabel("Резервные копии и база данных")
        backup_title.setObjectName("SectionTitle")
        backup_layout.addWidget(backup_title)
        self.db_path_label = QLabel()
        self.db_path_label.setObjectName("Muted")
        self.db_path_label.setWordWrap(True)
        self.db_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        backup_layout.addWidget(self.db_path_label)
        self.version_label = QLabel()
        self.version_label.setObjectName("Muted")
        backup_layout.addWidget(self.version_label)

        form2 = QFormLayout()
        self.backup_keep_spin = QSpinBox()
        self.backup_keep_spin.setRange(3, 200)
        form2.addRow("Хранить копий", self.backup_keep_spin)
        self.backup_on_start = QCheckBox("Копия при каждом запуске")
        form2.addRow("", self.backup_on_start)
        backup_layout.addLayout(form2)

        backup_buttons = QHBoxLayout()
        backup_button = QPushButton("Создать копию")
        backup_button.setObjectName("PrimaryButton")
        backup_button.clicked.connect(self._backup)
        check_button = QPushButton("Проверить целостность")
        check_button.clicked.connect(self._integrity)
        folder_button = QPushButton("Папка данных")
        folder_button.clicked.connect(self._open_folder)
        backup_buttons.addWidget(backup_button)
        backup_buttons.addWidget(check_button)
        backup_buttons.addWidget(folder_button)
        backup_layout.addLayout(backup_buttons)

        note = QLabel(
            "Копия создаётся автоматически при открытии и закрытии смены, "
            "а также перед импортом из старой базы. Формат SQLite."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        backup_layout.addWidget(note)
        right.addWidget(backup_card)

        reliability = QFrame()
        reliability.setObjectName("Card")
        reliability_layout = QVBoxLayout(reliability)
        reliability_layout.setContentsMargins(18, 16, 18, 16)
        reliability_layout.setSpacing(8)
        reliability_title = QLabel("Надёжность смен")
        reliability_title.setObjectName("SectionTitle")
        reliability_layout.addWidget(reliability_title)
        reliability_text = QLabel(
            "Продажи записываются одной транзакцией с режимом synchronous=FULL. "
            "Смена не хранит счётчики: отчёт всегда пересчитывается по сохранённым "
            "чекам. Если питание отключится, после запуска смена останется открытой "
            "и продолжится с прежними данными."
        )
        reliability_text.setWordWrap(True)
        reliability_text.setObjectName("Muted")
        reliability_layout.addWidget(reliability_text)
        right.addWidget(reliability)
        right.addStretch(1)
        content.addLayout(right, 1)
        layout.addLayout(content, 1)

    def refresh(self) -> None:
        settings = self.ctx.settings.all()
        self.company_edit.setText(settings.get("company_name", ""))
        self.address_edit.setText(settings.get("company_address", ""))
        self.phone_edit.setText(settings.get("company_phone", ""))
        self.currency_edit.setText(settings.get("currency", "₽"))
        self.footer_edit.setPlainText(settings.get("receipt_footer", ""))
        try:
            self.low_stock_spin.setValue(int(settings.get("low_stock_threshold", "5")))
            self.backup_keep_spin.setValue(int(settings.get("backup_keep", "20")))
        except ValueError:
            self.low_stock_spin.setValue(5)
            self.backup_keep_spin.setValue(20)
        self.backup_on_start.setChecked(
            settings.get("backup_on_start", "1") in {"1", "true", "yes", "да"}
        )
        self.db_path_label.setText(f"База данных: {self.ctx.paths.db_path}")
        self.version_label.setText(
            f"Версия приложения: {__version__}   ·   Схема БД: {self.ctx.db.schema_version}"
        )

    def _save(self) -> None:
        if not self.company_edit.text().strip():
            warning(self, "Укажите название организации")
            return
        try:
            self.ctx.settings.set_many(
                {
                    "company_name": self.company_edit.text().strip(),
                    "company_address": self.address_edit.text().strip(),
                    "company_phone": self.phone_edit.text().strip(),
                    "currency": self.currency_edit.text().strip() or "₽",
                    "receipt_footer": self.footer_edit.toPlainText().strip(),
                    "low_stock_threshold": self.low_stock_spin.value(),
                    "backup_keep": self.backup_keep_spin.value(),
                    "backup_on_start": 1 if self.backup_on_start.isChecked() else 0,
                }
            )
        except ServiceError as exc:
            error(self, str(exc))
            return
        info(self, "Настройки сохранены")

    def _backup(self) -> None:
        path = self.ctx.db.backup(tag="manual")
        if path is None:
            error(self, "Не удалось создать резервную копию. Подробности в логе.")
            return
        info(self, f"Резервная копия создана:\n{path}")

    def _integrity(self) -> None:
        ok, message = self.ctx.db.integrity_check()
        if ok:
            info(self, "Проверка целостности пройдена: база данных в порядке.")
        else:
            error(self, f"Обнаружены проблемы с базой данных:\n{message}")

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.paths.data_dir)))
