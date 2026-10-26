"""User accounts and seller permissions."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...context import AppContext
from ...models import User
from ...services.errors import ServiceError
from ...services.users import PERMISSIONS
from ..widgets import (
    PageHeader,
    center_window,
    confirm,
    error,
    info,
    make_table,
    set_cell,
    warning,
)

ROLE_LABELS = {"admin": "Администратор", "seller": "Продавец"}


class UserDialog(QDialog):
    def __init__(
        self,
        ctx: AppContext,
        current_user: User,
        user: User | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.current_user = current_user
        self.user = user
        self.permission_checks: dict[str, QCheckBox] = {}
        self.setWindowTitle("Сотрудник")
        self.setModal(True)
        self.resize(620, 700)
        self._build()
        center_window(self)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        title = QLabel(
            "Новый сотрудник"
            if self.user is None
            else f"Изменить: {self.user.display_name}"
        )
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        self.full_name_edit = QLineEdit(self.user.full_name if self.user else "")
        self.full_name_edit.setPlaceholderText("Имя и фамилия")
        form.addRow("Имя", self.full_name_edit)

        self.username_edit = QLineEdit(self.user.username if self.user else "")
        self.username_edit.setPlaceholderText("Логин для входа")
        form.addRow("Логин *", self.username_edit)

        self.role_combo = QComboBox()
        for key, label in ROLE_LABELS.items():
            self.role_combo.addItem(label, key)
        if self.user:
            self.role_combo.setCurrentIndex(max(0, self.role_combo.findData(self.user.role)))
        self.role_combo.currentIndexChanged.connect(self._role_changed)
        form.addRow("Роль *", self.role_combo)

        self.active_check = QCheckBox("Учётная запись активна")
        self.active_check.setChecked(self.user.is_active if self.user else True)
        form.addRow("", self.active_check)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText(
            "Оставьте пустым, чтобы не менять" if self.user else "Не менее 4 символов"
        )
        form.addRow("Пароль" if self.user is None else "Новый пароль", self.password_edit)

        self.password_repeat_edit = QLineEdit()
        self.password_repeat_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_repeat_edit.setPlaceholderText("Повторите пароль")
        form.addRow("Повтор пароля", self.password_repeat_edit)
        layout.addLayout(form)

        is_self = self.user is not None and self.user.id == self.current_user.id
        if is_self:
            self.role_combo.setEnabled(False)
            self.active_check.setEnabled(False)
            note = QLabel(
                "Нельзя изменить собственную роль или отключить свою учётную запись."
            )
            note.setObjectName("InfoBanner")
            note.setWordWrap(True)
            layout.addWidget(note)

        self.permissions_group = QGroupBox("Права в режиме продавца")
        grid = QGridLayout(self.permissions_group)
        grid.setSpacing(8)
        current_permissions = self.user.permissions if self.user else frozenset()
        for index, (key, label) in enumerate(PERMISSIONS.items()):
            check = QCheckBox(label)
            check.setChecked(key in current_permissions)
            self.permission_checks[key] = check
            grid.addWidget(check, index // 2, index % 2)
        layout.addWidget(self.permissions_group)

        hint = QLabel(
            "Эти права добавляют продавцу кнопки администрирования, не открывая "
            "все разделы. Администратор всегда имеет полный доступ."
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
        self._role_changed()

    def _role_changed(self) -> None:
        self.permissions_group.setVisible(self.role_combo.currentData() == "seller")

    def _save(self) -> None:
        password = self.password_edit.text()
        if password != self.password_repeat_edit.text():
            error(self, "Пароли не совпадают")
            return
        if self.user is None and not password:
            error(self, "Задайте пароль для нового сотрудника")
            return
        permissions = {
            key for key, check in self.permission_checks.items() if check.isChecked()
        }
        try:
            if self.user is None:
                created = self.ctx.users.create_user(
                    username=self.username_edit.text(),
                    password=password,
                    full_name=self.full_name_edit.text(),
                    role=self.role_combo.currentData(),
                    permissions=permissions,
                    is_active=self.active_check.isChecked(),
                )
                self.user = created
            else:
                self.ctx.users.update_user(
                    self.user.id,
                    username=self.username_edit.text(),
                    full_name=self.full_name_edit.text(),
                    role=self.role_combo.currentData(),
                    is_active=self.active_check.isChecked(),
                    permissions=permissions,
                    password=password or None,
                    actor_id=self.current_user.id,
                )
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.accept()


class ResetPasswordDialog(QDialog):
    def __init__(self, ctx: AppContext, user: User, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.user = user
        self.setWindowTitle("Сброс пароля")
        self.setModal(True)
        self.resize(420, 280)
        self._build()
        center_window(self)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        title = QLabel(f"Новый пароль: {self.user.display_name}")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Новый пароль", self.password_edit)
        self.repeat_edit = QLineEdit()
        self.repeat_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Повторите", self.repeat_edit)
        layout.addLayout(form)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Сбросить пароль")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self._save)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        if self.password_edit.text() != self.repeat_edit.text():
            error(self, "Пароли не совпадают")
            return
        try:
            self.ctx.users.reset_password(self.user.id, self.password_edit.text())
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.accept()


class UsersPage(QWidget):
    def __init__(self, ctx: AppContext, current_user: User, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.current_user = current_user
        self._users: list[User] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = PageHeader(
            "Пользователи",
            "Администраторы видят всё. Продавцам можно выдать отдельные права "
            "администрирования прямо в режиме продавца.",
        )
        add_button = QPushButton("Добавить сотрудника")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self._add)
        header.add_action(add_button)
        layout.addWidget(header)

        self.table = make_table(["Логин", "Имя", "Роль", "Права", "Активен"])
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.doubleClicked.connect(self._edit_selected)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        edit_button = QPushButton("Изменить")
        edit_button.clicked.connect(self._edit_selected)
        toggle_button = QPushButton("Включить / отключить")
        toggle_button.clicked.connect(self._toggle_selected)
        reset_button = QPushButton("Сбросить пароль")
        reset_button.clicked.connect(self._reset_selected)
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.refresh)
        actions.addWidget(edit_button)
        actions.addWidget(toggle_button)
        actions.addWidget(reset_button)
        actions.addStretch(1)
        actions.addWidget(refresh_button)
        layout.addLayout(actions)

    def refresh(self) -> None:
        self._users = self.ctx.users.list_users()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._users))
        for row, user in enumerate(self._users):
            if user.is_admin:
                rights = "Все права"
                rights_tip = "Полный доступ администратора"
            else:
                labels = [PERMISSIONS[key] for key in sorted(user.permissions) if key in PERMISSIONS]
                rights = f"{len(labels)}: " + ", ".join(labels) if labels else "Только продажа"
                rights_tip = "\n".join(labels) or "Только экран продавца"
            values = [
                user.username,
                user.display_name,
                ROLE_LABELS.get(user.role, user.role),
                rights,
                "да" if user.is_active else "нет",
            ]
            for column, value in enumerate(values):
                item = set_cell(
                    self.table,
                    row,
                    column,
                    value,
                    color=None if user.is_active else "#94a3b8",
                )
                if column == 3:
                    item.setToolTip(rights_tip)

    def _selected(self) -> User | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._users):
            return self._users[row]
        return None

    def _add(self) -> None:
        if UserDialog(self.ctx, self.current_user, parent=self).exec():
            self.refresh()

    def _edit_selected(self) -> None:
        user = self._selected()
        if user is None:
            warning(self, "Выберите сотрудника")
            return
        if UserDialog(self.ctx, self.current_user, user, parent=self).exec():
            self.refresh()

    def _toggle_selected(self) -> None:
        user = self._selected()
        if user is None:
            warning(self, "Выберите сотрудника")
            return
        if user.id == self.current_user.id:
            error(self, "Нельзя отключить собственную учётную запись")
            return
        if user.is_active and not confirm(
            self, f"Отключить учётную запись «{user.username}»?"
        ):
            return
        try:
            self.ctx.users.update_user(
                user.id,
                username=user.username,
                full_name=user.full_name,
                role=user.role,
                is_active=not user.is_active,
                permissions=set(user.permissions),
                actor_id=self.current_user.id,
            )
        except ServiceError as exc:
            error(self, str(exc))
            return
        self.refresh()

    def _reset_selected(self) -> None:
        user = self._selected()
        if user is None:
            warning(self, "Выберите сотрудника")
            return
        if ResetPasswordDialog(self.ctx, user, parent=self).exec():
            info(self, f"Пароль для «{user.username}» изменён.")
