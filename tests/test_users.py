from __future__ import annotations

import pytest

from pos.services.errors import AuthError, ValidationError


def test_authenticate_and_permissions(ctx, admin, seller):
    assert admin.is_admin
    assert ctx.users.has_permission(admin, "manage_users")
    assert not ctx.users.has_permission(seller, "manage_users")
    assert ctx.users.has_permission(seller, "view_stats")
    authenticated = ctx.users.authenticate("SELLER", "seller123")
    assert authenticated.id == seller.id
    assert authenticated.permissions == frozenset({"view_stats"})


def test_bad_password(ctx, seller):
    with pytest.raises(AuthError):
        ctx.users.authenticate("seller", "wrong")
    with pytest.raises(AuthError):
        ctx.users.authenticate("unknown", "seller123")


def test_inactive_cannot_login(ctx, seller):
    ctx.users.update_user(
        seller.id,
        username=seller.username,
        full_name=seller.full_name,
        role=seller.role,
        is_active=False,
        permissions=set(seller.permissions),
        actor_id=999,
    )
    with pytest.raises(AuthError):
        ctx.users.authenticate("seller", "seller123")


def test_last_admin_protected(ctx, admin):
    with pytest.raises(ValidationError):
        ctx.users.update_user(
            admin.id,
            username=admin.username,
            full_name="x",
            role="seller",
            is_active=True,
            actor_id=999,
        )


def test_self_deactivation_protected(ctx, admin):
    with pytest.raises(ValidationError):
        ctx.users.update_user(
            admin.id,
            username=admin.username,
            full_name=admin.full_name,
            role="admin",
            is_active=False,
            actor_id=admin.id,
        )


def test_password_change(ctx, seller):
    ctx.users.change_password(seller.id, "seller123", "newpass")
    assert ctx.users.authenticate("seller", "newpass").id == seller.id
    with pytest.raises(ValidationError):
        ctx.users.change_password(seller.id, "wrong", "another")


def test_duplicate_username(ctx, seller):
    with pytest.raises(ValidationError):
        ctx.users.create_user("seller", "1234", "Другой", role="seller")
