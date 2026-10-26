from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from pos.ui.login import LoginWindow
from pos.ui.main_window import NAV_ITEMS, MainWindow
from pos.ui.admin.items_page import ItemDialog
from pos.ui.payment_dialog import PaymentDialog
from pos.ui.seller_page import SellerPage


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_first_run_setup_creates_admin(qt_app, ctx):
    window = LoginWindow(ctx)
    assert window._setup_mode
    window.full_name_edit.setText("Иван Петров")
    window.username_edit.setText("boss")
    window.password_edit.setText("secret1")
    window.password_repeat_edit.setText("secret1")

    created = []
    window.logged_in.connect(created.append)
    window.primary_button.click()

    assert len(created) == 1
    assert created[0].username == "boss"
    assert created[0].role == "admin"
    assert window.error_label.isHidden()
    window.close()


def test_main_window_opens_every_permitted_page(qt_app, ctx, admin):
    ctx.catalog.create_item(
        name="Кофе", kind="product", price=15000, cost=6000, initial_stock=5, user_id=admin.id
    )
    ctx.shifts.open_shift(admin.id, opening_cash=0)

    window = MainWindow(ctx, admin)
    try:
        expected = {key for key, _label, permission, _section in NAV_ITEMS}
        assert set(window.pages) == expected
        assert set(window.nav_buttons) == expected
        for key in expected:
            window.show_page(key)
            assert window.stack.currentWidget() is window.pages[key]
        assert "sale" in window.pages
    finally:
        window.prepare_logout()
        window.close()


def test_seller_navigation_respects_permissions(qt_app, ctx, seller):
    window = MainWindow(ctx, seller)
    try:
        assert set(window.pages) == {"sale", "stats", "shifts"}
        assert "products" not in window.nav_buttons
    finally:
        window.prepare_logout()
        window.close()

    plain = ctx.users.create_user("plain", "plain123", "Продавец без прав")
    window = MainWindow(ctx, plain)
    try:
        assert set(window.pages) == {"sale"}
        assert set(window.nav_buttons) == {"sale"}
    finally:
        window.prepare_logout()
        window.close()


def test_seller_cart_and_split_payment_dialog(qt_app, ctx, seller):
    item = ctx.catalog.create_item(
        name="Кофе",
        kind="product",
        price=15000,
        cost=5000,
        initial_stock=10,
        user_id=seller.id,
    )
    paper = ctx.catalog.create_item(
        name="Бумага",
        kind="product",
        cost=250,
        initial_stock=100,
        user_id=seller.id,
        is_consumable=True,
    )
    ctx.shifts.open_shift(seller.id, opening_cash=0)

    page = SellerPage(ctx, seller)
    try:
        assert paper.id not in page._items
        page.add_to_cart(item)
        assert page.cart == {item.id: 1}
        assert page._cart_total() == 15000
        assert page.pay_button.isEnabled()
        assert page.shift_warning.isHidden()

        page._change_selected(1)
        assert page.cart[item.id] == 2
        assert page._cart_total() == 30000
        assert "2" in page.count_badge.text()

        methods = ctx.payments.list_methods()
        dialog = PaymentDialog(30000, methods, ctx.currency)
        cash = next(method for method in methods if method.affects_cash)
        qr = next(method for method in methods if method.kind == "qr")
        dialog._inputs[cash.id].set_cents(10000)
        dialog._inputs[qr.id].set_cents(20000)
        assert dialog.pay_button.isEnabled()
        dialog.pay_button.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert sum(payment.amount for payment in dialog.payments) == 30000
        assert len(dialog.payments) == 2
    finally:
        page.close()


def test_item_dialog_edits_service_consumables(qt_app, ctx, admin):
    paper = ctx.catalog.create_item(
        name="Бумага",
        kind="product",
        cost=250,
        unit="лист",
        initial_stock=100,
        user_id=admin.id,
        is_consumable=True,
    )
    service = ctx.catalog.create_item(
        name="Копия",
        kind="service",
        price=500,
        user_id=admin.id,
        consumables=[(paper.id, 2)],
    )
    dialog = ItemDialog(ctx, service)
    try:
        assert not dialog.recipe_box.isHidden()
        assert dialog._collect_consumables() == [(paper.id, 2)]

        product = ctx.catalog.get_item(paper.id)
        assert product is not None
        product_dialog = ItemDialog(ctx, product)
        try:
            assert product_dialog.recipe_box.isHidden()
            assert product_dialog.consumable_check.isChecked()
            assert not product_dialog.track_check.isEnabled()
        finally:
            product_dialog.close()
    finally:
        dialog.close()
