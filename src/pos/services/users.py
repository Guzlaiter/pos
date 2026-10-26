"""Users, authentication and permissions."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from ..database import Database
from ..models import User
from ..security import hash_password, verify_password
from .errors import AuthError, ValidationError

MIN_PASSWORD_LENGTH = 4

# Permission keys used by sellers and by navigation filtering.
PERMISSIONS: dict[str, str] = {
    "manage_catalog": "Товары, услуги и категории",
    "manage_prices": "Прейскуранты",
    "manage_stock": "Склад",
    "manage_payment_methods": "Способы оплаты",
    "view_stats": "Статистика и смены",
    "manage_shifts": "Закрытие чужих смен",
    "import_data": "Импорт из старой базы",
    "manage_users": "Пользователи",
    "settings": "Настройки",
}

ADMIN_PERMISSIONS = frozenset(PERMISSIONS)


class UserService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ read
    def count_users(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM users"))

    def count_active_admins(self, exclude_user_id: int | None = None) -> int:
        if exclude_user_id is None:
            return int(
                self.db.scalar(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
                )
            )
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1 AND id<>?",
                (exclude_user_id,),
            )
        )

    def _permissions(self, user_id: int) -> frozenset[str]:
        rows = self.db.query(
            "SELECT permission FROM user_permissions WHERE user_id=?", (user_id,)
        )
        return frozenset(row["permission"] for row in rows)

    def _from_row(self, row: sqlite3.Row, permissions: frozenset[str]) -> User:
        return User(
            id=int(row["id"]),
            username=str(row["username"]),
            full_name=str(row["full_name"] or ""),
            role=str(row["role"]),
            is_active=bool(row["is_active"]),
            permissions=permissions,
        )

    def get_user(self, user_id: int) -> User | None:
        row = self.db.query_one("SELECT * FROM users WHERE id=?", (user_id,))
        if row is None:
            return None
        return self._from_row(row, self._permissions(user_id))

    def list_users(self) -> list[User]:
        rows = self.db.query("SELECT * FROM users ORDER BY role, full_name, username")
        perms: dict[int, set[str]] = defaultdict(set)
        for item in self.db.query("SELECT user_id, permission FROM user_permissions"):
            perms[int(item["user_id"])].add(str(item["permission"]))
        return [
            self._from_row(row, frozenset(perms[int(row["id"])]))
            for row in rows
        ]

    @staticmethod
    def has_permission(user: User, permission: str) -> bool:
        if not user.is_active:
            return False
        if user.is_admin:
            return True
        return permission in user.permissions

    def permissions_for(self, user: User) -> frozenset[str]:
        return ADMIN_PERMISSIONS if user.is_admin else user.permissions

    # ------------------------------------------------------------------ auth
    def authenticate(self, username: str, password: str) -> User:
        username = (username or "").strip()
        if not username or not password:
            raise AuthError("Введите логин и пароль")
        row = self.db.query_one(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        )
        if row is None or not verify_password(password, str(row["password_hash"])):
            raise AuthError("Неверный логин или пароль")
        if not bool(row["is_active"]):
            raise AuthError("Пользователь отключён. Обратитесь к администратору.")
        user = self._from_row(row, self._permissions(int(row["id"])))
        return user

    # ----------------------------------------------------------------- write
    def _validate_username(self, username: str) -> str:
        username = (username or "").strip()
        if len(username) < 2:
            raise ValidationError("Логин должен содержать минимум 2 символа")
        if any(ch.isspace() for ch in username):
            raise ValidationError("Логин не должен содержать пробелы")
        return username

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"Пароль должен содержать минимум {MIN_PASSWORD_LENGTH} символа"
            )

    def _normalize_permissions(self, permissions: set[str] | frozenset[str] | None) -> set[str]:
        unknown = set(permissions or set()) - set(PERMISSIONS)
        if unknown:
            raise ValidationError(f"Неизвестные права: {', '.join(sorted(unknown))}")
        return set(permissions or set())

    def create_user(
        self,
        username: str,
        password: str,
        full_name: str,
        role: str = "seller",
        permissions: set[str] | frozenset[str] | None = None,
        is_active: bool = True,
    ) -> User:
        username = self._validate_username(username)
        self._validate_password(password)
        if role not in ("admin", "seller"):
            raise ValidationError("Некорректная роль")
        perms = self._normalize_permissions(permissions)
        if role == "admin":
            perms = set()
        try:
            with self.db.transaction():
                cursor = self.db.execute(
                    "INSERT INTO users(username, password_hash, full_name, role, is_active) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        username,
                        hash_password(password),
                        (full_name or "").strip(),
                        role,
                        int(bool(is_active)),
                    ),
                )
                user_id = int(cursor.lastrowid)
                self._replace_permissions(user_id, perms)
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Пользователь «{username}» уже существует") from exc
        user = self.get_user(user_id)
        assert user is not None
        return user

    def _replace_permissions(self, user_id: int, permissions: set[str]) -> None:
        self.db.execute("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
        if permissions:
            self.db.executemany(
                "INSERT INTO user_permissions(user_id, permission) VALUES (?, ?)",
                [(user_id, p) for p in sorted(permissions)],
            )

    def update_user(
        self,
        user_id: int,
        *,
        username: str,
        full_name: str,
        role: str,
        is_active: bool,
        permissions: set[str] | frozenset[str] | None = None,
        password: str | None = None,
        actor_id: int | None = None,
    ) -> User:
        username = self._validate_username(username)
        if role not in ("admin", "seller"):
            raise ValidationError("Некорректная роль")
        perms = self._normalize_permissions(permissions)
        if role == "admin":
            perms = set()
        current = self.get_user(user_id)
        if current is None:
            raise ValidationError("Пользователь не найден")

        if actor_id is not None and actor_id == user_id:
            if not is_active:
                raise ValidationError("Нельзя отключить собственную учётную запись")
            if current.role == "admin" and role != "admin":
                raise ValidationError("Нельзя снять с себя права администратора")
        if current.role == "admin" and current.is_active and (
            role != "admin" or not is_active
        ):
            if self.count_active_admins(exclude_user_id=user_id) == 0:
                raise ValidationError("В системе должен остаться хотя бы один администратор")
        if password:
            self._validate_password(password)

        try:
            with self.db.transaction():
                self.db.execute(
                    "UPDATE users SET username=?, full_name=?, role=?, is_active=? "
                    "WHERE id=?",
                    (
                        username,
                        (full_name or "").strip(),
                        role,
                        int(bool(is_active)),
                        user_id,
                    ),
                )
                if password:
                    self.db.execute(
                        "UPDATE users SET password_hash=? WHERE id=?",
                        (hash_password(password), user_id),
                    )
                self._replace_permissions(user_id, perms)
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Логин «{username}» уже занят") from exc

        updated = self.get_user(user_id)
        assert updated is not None
        return updated

    def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        row = self.db.query_one("SELECT password_hash FROM users WHERE id=?", (user_id,))
        if row is None:
            raise ValidationError("Пользователь не найден")
        if not verify_password(old_password, str(row["password_hash"])):
            raise ValidationError("Текущий пароль указан неверно")
        self._validate_password(new_password)
        with self.db.transaction():
            self.db.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (hash_password(new_password), user_id),
            )

    def reset_password(self, user_id: int, new_password: str) -> None:
        self._validate_password(new_password)
        with self.db.transaction():
            self.db.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (hash_password(new_password), user_id),
            )

    def get_or_create_default_admin(self, username: str, password: str, full_name: str) -> User:
        if self.count_users():
            raise ValidationError("В системе уже есть пользователи")
        return self.create_user(username, password, full_name, role="admin")
