"""Login window and first-run administrator setup."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..services.errors import ServiceError
from .widgets import center_window


class LoginWindow(QWidget):
    logged_in = Signal(object)

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self._setup_mode = ctx.users.count_users() == 0
        self.setObjectName("AppRoot")
        self.setWindowTitle("POS — вход")
        self.resize(1060, 660)
        self.setMinimumSize(900, 600)
        self._build()
        center_window(self)
        self._focus_first()

    # ------------------------------------------------------------------- build
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_hero(), 5)
        root.addWidget(self._build_form_panel(), 6)

    def _build_hero(self) -> QWidget:
        hero = QFrame()
        hero.setObjectName("LoginHero")
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(56, 56, 56, 48)
        layout.setSpacing(12)

        brand = QLabel("POS")
        brand.setObjectName("HeroTitle")
        layout.addWidget(brand)

        title = QLabel("Продажи, склад и смены\nв одном приложении")
        title.setObjectName("HeroSubtitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        layout.addSpacing(24)
        features = [
            "Минимальный экран продавца",
            "Оплата несколькими способами",
            "Надёжные смены и резервные копии",
            "Склад, прейскуранты и категории",
            "Статистика и прибыль по позициям",
            "Импорт базы из старой версии",
        ]
        for feature in features:
            label = QLabel(f"✓   {feature}")
            label.setObjectName("HeroText")
            layout.addWidget(label)

        layout.addStretch(1)

        note = QLabel(
            "Данные хранятся локально в SQLite.\n"
            "Смена восстанавливается автоматически после сбоя."
        )
        note.setObjectName("HeroText")
        note.setWordWrap(True)
        layout.addWidget(note)

        version = QLabel("версия 0.1.0")
        version.setObjectName("HeroText")
        layout.addWidget(version)
        return hero

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(56, 40, 56, 40)
        outer.addStretch(1)

        card = QFrame()
        card.setObjectName("LoginCard")
        card.setMaximumWidth(470)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 34, 36, 30)
        layout.setSpacing(12)

        title = QLabel("Первый запуск" if self._setup_mode else "Вход в систему")
        title.setObjectName("LoginTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Создайте учётную запись администратора."
            if self._setup_mode
            else "Введите данные продавца или администратора."
        )
        subtitle.setObjectName("LoginSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(6)

        self.error_label = QLabel()
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        if self._setup_mode:
            self.full_name_edit = QLineEdit()
            self.full_name_edit.setPlaceholderText("Например: Иван Петров")
            self._field(layout, "Имя и фамилия", self.full_name_edit)
            self.username_edit = QLineEdit()
            self.username_edit.setPlaceholderText("admin")
            self._field(layout, "Логин администратора", self.username_edit)
            self.password_edit = QLineEdit()
            self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.password_edit.setPlaceholderText("Не менее 4 символов")
            self._field(layout, "Пароль", self.password_edit)
            self.password_repeat_edit = QLineEdit()
            self.password_repeat_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._field(layout, "Повторите пароль", self.password_repeat_edit)
            self.show_password = QCheckBox("Показать пароль")
            self.show_password.toggled.connect(self._toggle_password)
            layout.addWidget(self.show_password)
            hint = QLabel(
                "Способы оплаты и базовый прейскурант будут созданы автоматически. "
                "Их можно изменить в разделе «Администрирование»."
            )
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            button = QPushButton("Создать администратора и войти")
            button.setObjectName("PrimaryButton")
            button.setMinimumHeight(44)
            button.clicked.connect(self._create_admin)
            self.primary_button = button
            layout.addWidget(button)
            for widget in (
                self.full_name_edit,
                self.username_edit,
                self.password_edit,
                self.password_repeat_edit,
            ):
                widget.returnPressed.connect(self._create_admin)
        else:
            self.username_edit = QLineEdit()
            self.username_edit.setPlaceholderText("Логин")
            self._field(layout, "Логин", self.username_edit)
            self.password_edit = QLineEdit()
            self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.password_edit.setPlaceholderText("Пароль")
            self._field(layout, "Пароль", self.password_edit)
            self.show_password = QCheckBox("Показать пароль")
            self.show_password.toggled.connect(self._toggle_password)
            layout.addWidget(self.show_password)
            button = QPushButton("Войти")
            button.setObjectName("PrimaryButton")
            button.setMinimumHeight(44)
            button.clicked.connect(self._login)
            self.primary_button = button
            layout.addWidget(button)
            self.username_edit.returnPressed.connect(self._login)
            self.password_edit.returnPressed.connect(self._login)

        if self.ctx.startup_notes:
            note = QLabel("\n".join(self.ctx.startup_notes))
            note.setObjectName("InfoBanner")
            note.setWordWrap(True)
            layout.addWidget(note)

        layout.addSpacing(4)
        path_label = QLabel(f"База данных: {self.ctx.paths.db_path}")
        path_label.setObjectName("Muted")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

        footer = QLabel("© POS 2026 · локальное приложение")
        footer.setObjectName("Muted")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(footer)
        return panel

    @staticmethod
    def _field(layout: QVBoxLayout, label: str, widget: QWidget) -> None:
        caption = QLabel(label)
        caption.setStyleSheet("font-weight: 600; color: #334155;")
        layout.addWidget(caption)
        layout.addWidget(widget)

    def _focus_first(self) -> None:
        if self._setup_mode:
            self.full_name_edit.setFocus()
        else:
            self.username_edit.setFocus()

    def _toggle_password(self, shown: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self.password_edit.setEchoMode(mode)
        if hasattr(self, "password_repeat_edit"):
            self.password_repeat_edit.setEchoMode(mode)

    # ------------------------------------------------------------------ actions
    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _login(self) -> None:
        self.error_label.hide()
        self.primary_button.setEnabled(False)
        try:
            user = self.ctx.users.authenticate(
                self.username_edit.text(), self.password_edit.text()
            )
        except ServiceError as exc:
            self._show_error(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive
            self._show_error(f"Ошибка входа: {exc}")
            return
        finally:
            self.primary_button.setEnabled(True)
        self.logged_in.emit(user)

    def _create_admin(self) -> None:
        self.error_label.hide()
        password = self.password_edit.text()
        if password != self.password_repeat_edit.text():
            self._show_error("Пароли не совпадают")
            return
        self.primary_button.setEnabled(False)
        try:
            user = self.ctx.users.create_user(
                username=self.username_edit.text(),
                password=password,
                full_name=self.full_name_edit.text(),
                role="admin",
            )
        except ServiceError as exc:
            self._show_error(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive
            self._show_error(f"Не удалось создать администратора: {exc}")
            return
        finally:
            self.primary_button.setEnabled(True)
        self.logged_in.emit(user)
