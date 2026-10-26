"""Main window: navigation, shift header and page orchestration."""

from __future__ import annotations

from PySide6.QtCore import QDateTime, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..models import User
from ..services.errors import ServiceError
from ..services.users import PERMISSIONS
from .admin.categories_page import CategoriesPage
from .admin.items_page import ItemsPage
from .admin.legacy_page import LegacyImportPage
from .admin.payments_page import PaymentMethodsPage
from .admin.prices_page import PricesPage
from .admin.settings_page import SettingsPage
from .admin.shifts_page import ShiftsPage
from .admin.stats_page import StatsPage
from .admin.stock_page import StockPage
from .admin.users_page import UsersPage
from .seller_page import SellerPage
from .shift_dialogs import CloseShiftDialog, OpenShiftDialog, ShiftReportDialog
from .widgets import center_window, confirm, error, info, warning


NAV_ITEMS = [
    ("sale", "🛒   Продажа", None, "РАБОТА"),
    ("products", "📦   Товары и услуги", "manage_catalog", "УПРАВЛЕНИЕ"),
    ("categories", "🏷️   Категории", "manage_catalog", None),
    ("prices", "💲   Прейскуранты", "manage_prices", None),
    ("stock", "🗃️   Склад", "manage_stock", None),
    ("payments", "💳   Способы оплаты", "manage_payment_methods", None),
    ("stats", "📊   Статистика", "view_stats", None),
    ("shifts", "🕒   Смены", "view_stats", None),
    ("users", "👥   Пользователи", "manage_users", None),
    ("import", "📥   Импорт данных", "import_data", None),
    ("settings", "⚙️   Настройки", "settings", None),
]


class MainWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(self, ctx: AppContext, user: User):
        super().__init__()
        self.ctx = ctx
        self.user = user
        self.pages: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self._closing_for_logout = False
        self._build()
        self.setWindowTitle(f"POS — {user.display_name}")
        self.resize(1360, 860)
        self.setMinimumSize(1120, 720)
        center_window(self)
        QTimer.singleShot(350, self._initial_shift_check)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._update_clock)
        self._clock.start(1000)
        self._update_clock()
        self._refresh_shift_header()

    # ------------------------------------------------------------------- build
    def _can(self, permission: str | None) -> bool:
        if permission is None:
            return True
        return self.ctx.users.has_permission(self.user, permission)

    def _build(self) -> None:
        root_widget = QWidget()
        root_widget.setObjectName("AppRoot")
        self.setCentralWidget(root_widget)
        root = QHBoxLayout(root_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        self.stack.setObjectName("Page")
        self._build_pages()
        right_layout.addWidget(self.stack, 1)
        root.addWidget(right, 1)

        status = QStatusBar()
        status.setSizeGripEnabled(False)
        status.setStyleSheet(
            "QStatusBar { background:#ffffff; color:#64748b; border-top:1px solid #e5eaf2; }"
        )
        self.setStatusBar(status)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(252)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 22, 14, 16)
        layout.setSpacing(4)

        brand = QLabel("POS")
        brand.setObjectName("BrandTitle")
        layout.addWidget(brand)
        brand_sub = QLabel("учёт продаж")
        brand_sub.setObjectName("BrandSubtitle")
        layout.addWidget(brand_sub)
        layout.addSpacing(12)

        nav_scroll = QScrollArea()
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_host = QWidget()
        nav_layout = QVBoxLayout(nav_host)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(2)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        section_done: set[str] = set()
        for key, label, permission, section in NAV_ITEMS:
            if permission == "view_stats" and key == "shifts":
                allowed = self._can("view_stats") or self._can("manage_shifts")
            else:
                allowed = self._can(permission)
            if not allowed:
                continue
            if section and section not in section_done:
                section_label = QLabel(section)
                section_label.setObjectName("NavSection")
                nav_layout.addWidget(section_label)
                section_done.add(section)
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, page_key=key: self.show_page(page_key)
            )
            self.nav_group.addButton(button)
            nav_layout.addWidget(button)
            self.nav_buttons[key] = button
        nav_layout.addStretch(1)
        nav_scroll.setWidget(nav_host)
        layout.addWidget(nav_scroll, 1)
        layout.addSpacing(10)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#1e293b;")
        layout.addWidget(line)
        layout.addSpacing(8)

        name_label = QLabel(self.user.display_name)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("color:#ffffff; font-weight:700; font-size:10.5pt;")
        layout.addWidget(name_label)
        role_bits = ["Администратор" if self.user.is_admin else "Продавец"]
        if not self.user.is_admin and self.user.permissions:
            role_bits.append(f"{len(self.user.permissions)} доп. прав")
        role_label = QLabel(" · ".join(role_bits))
        role_label.setStyleSheet("color:#94a3b8; font-size:9pt;")
        layout.addWidget(role_label)
        layout.addSpacing(6)

        logout_button = QPushButton("Сменить пользователя")
        logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_button.setStyleSheet(
            "QPushButton { color:#cbd5e1; background:transparent; border:none;"
            " text-align:left; padding:8px 10px; border-radius:7px; }"
            "QPushButton:hover { background:#1e293b; color:#ffffff; }"
        )
        logout_button.clicked.connect(self._logout)
        layout.addWidget(logout_button)
        return sidebar

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(68)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(22, 10, 22, 10)
        layout.setSpacing(12)

        caption = QLabel("Рабочее место")
        caption.setStyleSheet("font-size:11pt; font-weight:600; color:#334155;")
        layout.addWidget(caption)
        layout.addStretch(1)

        self.shift_badge = QLabel("Смена не открыта")
        self.shift_badge.setObjectName("ShiftClosed")
        layout.addWidget(self.shift_badge)

        self.shift_button = QPushButton("Открыть смену")
        self.shift_button.setObjectName("PrimaryButton")
        self.shift_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.shift_button.clicked.connect(self._toggle_shift)
        layout.addWidget(self.shift_button)

        self.clock_label = QLabel()
        self.clock_label.setObjectName("Muted")
        self.clock_label.setMinimumWidth(140)
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.clock_label)

        user_label = QLabel(self.user.display_name)
        user_label.setStyleSheet("font-weight:600; color:#0f172a;")
        layout.addWidget(user_label)
        return bar

    def _build_pages(self) -> None:
        factories = {
            "sale": lambda: SellerPage(self.ctx, self.user),
            "products": lambda: ItemsPage(self.ctx),
            "categories": lambda: CategoriesPage(self.ctx),
            "prices": lambda: PricesPage(self.ctx),
            "stock": lambda: StockPage(self.ctx, self.user),
            "payments": lambda: PaymentMethodsPage(self.ctx),
            "stats": lambda: StatsPage(self.ctx),
            "shifts": lambda: ShiftsPage(self.ctx, self.user),
            "users": lambda: UsersPage(self.ctx, self.user),
            "import": lambda: LegacyImportPage(self.ctx, self.user),
            "settings": lambda: SettingsPage(self.ctx),
        }
        for key, label, permission, _section in NAV_ITEMS:
            if permission == "view_stats" and key == "shifts":
                allowed = self._can("view_stats") or self._can("manage_shifts")
            else:
                allowed = self._can(permission)
            if not allowed:
                continue
            page = factories[key]()
            self.pages[key] = page
            self.stack.addWidget(page)
            if key == "sale":
                page.shift_requested.connect(self._open_shift)
                page.sale_completed.connect(self._sale_completed)
            elif key == "shifts":
                page.shift_changed.connect(self._shift_changed)
            elif key == "import":
                page.import_completed.connect(self._import_completed)

        if "sale" in self.pages:
            self.nav_buttons["sale"].setChecked(True)
            self.stack.setCurrentWidget(self.pages["sale"])

    # ------------------------------------------------------------------ pages
    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        button = self.nav_buttons.get(key)
        if button and not button.isChecked():
            button.setChecked(True)
        self.stack.setCurrentWidget(page)
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception as exc:  # pragma: no cover - defensive UI guard
                error(self, f"Не удалось обновить раздел: {exc}")

    def _sale_completed(self) -> None:
        self.statusBar().showMessage("Чек сохранён. Смена обновлена.", 5000)

    def _import_completed(self) -> None:
        self.statusBar().showMessage("Импорт завершён. Данные обновлены.", 8000)
        for key in ("sale", "products", "categories", "prices", "stock", "payments"):
            page = self.pages.get(key)
            refresh = getattr(page, "refresh", None)
            if callable(refresh) and page is not self.stack.currentWidget():
                try:
                    refresh()
                except Exception:
                    pass

    # ------------------------------------------------------------------ shift
    def _refresh_shift_header(self) -> None:
        shift = self.ctx.shifts.open_shift_for_user(self.user.id)
        self.current_shift = shift
        if shift is not None:
            self.shift_badge.setObjectName("ShiftOpen")
            self.shift_badge.setText(f"Смена №{shift.id} · {shift.opened_at[11:16]}")
            self.shift_button.setText("Закрыть смену")
            self.shift_button.setObjectName("DangerButton")
        else:
            self.shift_badge.setObjectName("ShiftClosed")
            self.shift_badge.setText("Смена не открыта")
            self.shift_button.setText("Открыть смену")
            self.shift_button.setObjectName("PrimaryButton")
        for widget in (self.shift_badge, self.shift_button):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _initial_shift_check(self) -> None:
        shift = self.ctx.shifts.open_shift_for_user(self.user.id)
        if shift is not None:
            self.ctx.shifts.mark_resumed(shift.id)
            self.statusBar().showMessage(
                f"Смена №{shift.id} восстановлена. Все продажи сохранены.", 12000
            )
            return
        if not confirm(
            self,
            "Смена не открыта. Открыть смену сейчас, чтобы начать продажи?",
            "Начало смены",
        ):
            return
        self._open_shift()

    def _toggle_shift(self) -> None:
        if self.ctx.shifts.open_shift_for_user(self.user.id) is None:
            self._open_shift()
        else:
            self._close_shift()

    def _open_shift(self) -> None:
        existing = self.ctx.shifts.open_shift_for_user(self.user.id)
        if existing is not None:
            info(self, f"Смена №{existing.id} уже открыта.")
            return
        dialog = OpenShiftDialog(self, self.ctx.currency)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            shift = self.ctx.shifts.open_shift(
                self.user.id, dialog.opening_cash, dialog.note
            )
        except ServiceError as exc:
            error(self, str(exc))
            return
        self._refresh_shift_header()
        self._refresh_shift_pages()
        self.statusBar().showMessage(f"Смена №{shift.id} открыта.", 6000)

    def _close_shift(self) -> None:
        shift = self.ctx.shifts.open_shift_for_user(self.user.id)
        if shift is None:
            info(self, "Нет открытой смены.")
            return
        try:
            summary = self.ctx.stats.shift_summary(shift.id)
        except ServiceError as exc:
            error(self, str(exc))
            return
        dialog = CloseShiftDialog(summary, self.ctx.currency, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self.ctx.shifts.close_shift(
                shift.id, dialog.counted_cash, self.user.id, dialog.note
            )
            closed_summary = self.ctx.stats.shift_summary(shift.id)
        except ServiceError as exc:
            error(self, str(exc))
            return
        self._refresh_shift_header()
        self._refresh_shift_pages()
        ShiftReportDialog(closed_summary, self.ctx, self).exec()

    def _shift_changed(self) -> None:
        self._refresh_shift_header()
        self._refresh_shift_pages()

    def _refresh_shift_pages(self) -> None:
        for key in ("sale", "shifts"):
            page = self.pages.get(key)
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass

    # ---------------------------------------------------------------- utility
    def _update_clock(self) -> None:
        self.clock_label.setText(
            QDateTime.currentDateTime().toString("dd.MM.yyyy  HH:mm")
        )

    def _logout(self) -> None:
        self._closing_for_logout = True
        self.logout_requested.emit()

    def prepare_logout(self) -> None:
        self._closing_for_logout = True

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._closing_for_logout:
            event.accept()
            return
        shift = self.ctx.shifts.open_shift_for_user(self.user.id)
        if shift is not None:
            if not confirm(
                self,
                f"Смена №{shift.id} останется открытой. "
                "Данные сохранятся, и смена восстановится при следующем запуске.\n\n"
                "Закрыть программу?",
                "Завершение работы",
            ):
                event.ignore()
                return
        event.accept()
