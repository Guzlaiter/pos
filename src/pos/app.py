"""Application entry point, startup recovery and login/main window controller."""

from __future__ import annotations

import faulthandler
import logging
import os
import shutil
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .config import APP_NAME, APP_TITLE, AppPaths
from .context import AppContext
from .database import Database, DatabaseError
from .ui.login import LoginWindow
from .ui.main_window import MainWindow
from .ui.theme import apply_theme

logger = logging.getLogger(__name__)

_crash_stream = None


def setup_logging(paths: AppPaths) -> None:
    global _crash_stream
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        paths.log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, console], force=True)
    try:
        _crash_stream = open(paths.data_dir / "crash.log", "a", encoding="utf-8")
        faulthandler.enable(_crash_stream)
    except OSError:
        pass


def _move_corrupt_database(paths: AppPaths) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = paths.db_path.with_name(f"pos-corrupt-{stamp}.db")
    if paths.db_path.exists():
        os.replace(paths.db_path, target)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(paths.db_path) + suffix)
        if sidecar.exists():
            os.replace(sidecar, Path(str(target) + suffix))
    return target


def _open_database(paths: AppPaths) -> tuple[Database, list[str]]:
    """Open the database, verifying integrity and restoring a backup if needed."""
    db = Database(paths.db_path, paths.backup_dir)
    problem = ""
    try:
        db.connect()
        ok, message = db.quick_check()
        if ok:
            return db, []
        problem = message
    except Exception as exc:  # sqlite3.DatabaseError, DatabaseError, etc.
        problem = str(exc)
    db.close()

    latest = db.latest_backup()
    if latest is None:
        raise DatabaseError(
            "База данных повреждена, а резервных копий не найдено.\n\n"
            f"Файл: {paths.db_path}\n{problem}"
        )
    answer = QMessageBox.question(
        None,
        "Повреждение базы данных",
        "Обнаружены проблемы с базой данных.\n\n"
        f"Последняя резервная копия:\n{latest.name}\n\n"
        "Восстановить базу из этой копии? Повреждённый файл будет сохранён рядом.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if answer != QMessageBox.StandardButton.Yes:
        raise DatabaseError(
            "Запуск отменён. Восстановите базу вручную из папки backups.\n\n"
            f"Причина: {problem}"
        )
    corrupt = _move_corrupt_database(paths)
    try:
        shutil.copy2(latest, paths.db_path)
    except OSError as exc:
        raise DatabaseError(f"Не удалось восстановить резервную копию: {exc}") from exc

    restored = Database(paths.db_path, paths.backup_dir)
    try:
        restored.connect()
        ok, message = restored.quick_check()
    except Exception as exc:
        restored.close()
        raise DatabaseError(f"Восстановленная база не открывается: {exc}") from exc
    if not ok:
        restored.close()
        raise DatabaseError(
            "Восстановленная копия также повреждена. Попробуйте более старую копию.\n\n"
            f"{message}"
        )
    logger.warning("База восстановлена из %s; повреждённый файл: %s", latest, corrupt)
    return restored, [
        f"База восстановлена из резервной копии «{latest.name}». "
        f"Повреждённый файл сохранён как «{corrupt.name}»."
    ]


class AppController(QObject):
    """Owns login/main windows so a user can switch without restarting the app."""

    def __init__(self, ctx: AppContext, app: QApplication):
        super().__init__()
        self.ctx = ctx
        self.app = app
        self.login: LoginWindow | None = None
        self.main: MainWindow | None = None

    def start(self) -> None:
        self._show_login()

    def _show_login(self) -> None:
        self.login = LoginWindow(self.ctx)
        self.login.logged_in.connect(self._on_login)
        self.login.show()

    def _on_login(self, user) -> None:
        self.main = MainWindow(self.ctx, user)
        self.main.logout_requested.connect(self._on_logout)
        self.main.show()
        if self.login is not None:
            old_login = self.login
            self.login = None
            old_login.close()
            old_login.deleteLater()

    def _on_logout(self) -> None:
        old_main = self.main
        self.main = None
        # Show the login window first so Qt does not quit when the last main
        # window closes.
        self._show_login()
        if old_main is not None:
            old_main.prepare_logout()
            old_main.close()
            old_main.deleteLater()


def main() -> int:
    paths = AppPaths.create()
    setup_logging(paths)
    logger.info("Запуск POS %s; данные: %s", __version__, paths.data_dir)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(True)
    apply_theme(app)

    lock = QLockFile(str(paths.lock_path))
    lock.setStaleLockTime(5000)
    if not lock.tryLock(200):
        QMessageBox.critical(
            None,
            "POS уже запущен",
            "Обнаружен другой запущенный экземпляр программы.\n\n"
            "Закройте его и попробуйте снова. Одновременная работа двух копий "
            "с одной базой запрещена, чтобы не повредить данные.",
        )
        return 1

    def handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical(
            "Необработанная ошибка", exc_info=(exc_type, exc_value, exc_tb)
        )
        try:
            QMessageBox.critical(
                None,
                "Неожиданная ошибка",
                "Произошла ошибка. Данные о смене и продажах сохранены.\n\n"
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"Подробности записаны в {paths.log_path}",
            )
        except Exception:
            pass

    sys.excepthook = handle_exception

    try:
        db, startup_notes = _open_database(paths)
    except DatabaseError as exc:
        logger.error("Не удалось открыть базу: %s", exc)
        QMessageBox.critical(None, "Ошибка базы данных", str(exc))
        lock.unlock()
        return 1
    except Exception as exc:
        logger.exception("Не удалось открыть базу")
        QMessageBox.critical(None, "Ошибка базы данных", str(exc))
        lock.unlock()
        return 1

    ctx = AppContext.create(paths, db)
    ctx.startup_notes.extend(startup_notes)

    try:
        if ctx.settings.get_bool("backup_on_start", True) and ctx.users.count_users() > 0:
            if db.backup(tag="startup") is None:
                logger.warning("Резервная копия при запуске не создана")
    except Exception:
        logger.exception("Ошибка резервного копирования при запуске")

    app.aboutToQuit.connect(db.close)
    controller = AppController(ctx, app)
    controller.start()
    logger.info("Интерфейс запущен")
    try:
        code = app.exec()
    finally:
        db.close()
        lock.unlock()
        logger.info("Завершение работы POS")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
