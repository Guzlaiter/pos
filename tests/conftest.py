from __future__ import annotations

import pytest

from pos.config import AppPaths
from pos.context import AppContext
from pos.database import Database


@pytest.fixture()
def paths(tmp_path):
    return AppPaths.create(tmp_path / "data")


@pytest.fixture()
def ctx(paths):
    db = Database(paths.db_path, paths.backup_dir)
    db.connect()
    context = AppContext.create(paths, db)
    try:
        yield context
    finally:
        db.close()


@pytest.fixture()
def admin(ctx):
    return ctx.users.create_user("admin", "admin123", "Администратор", role="admin")


@pytest.fixture()
def seller(ctx):
    return ctx.users.create_user(
        "seller",
        "seller123",
        "Продавец",
        role="seller",
        permissions={"view_stats"},
    )
