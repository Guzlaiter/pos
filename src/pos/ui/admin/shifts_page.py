"""Shift list, reports and administrative shift closing."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...context import AppContext
from ...models import User
from ...money import format_money
from ...services.errors import ServiceError
from ..shift_dialogs import CloseShiftDialog, OpenShiftDialog, ShiftReportDialog
from ..widgets import (
    PageHeader,
    confirm,
    error,
    info,
    make_table,
    set_cell,
    warning,
)


class ShiftsPage(QWidget):
    shift_changed = Signal()

    def __init__(self, ctx: AppContext, user: User, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.user = user
        self._rows: list = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = PageHeader(
            "Смены",
            "Открытие, закрытие и отчёты. Каждая смена восстанавливается после сбоя; "
            "закрывать чужие смены может администратор или сотрудник с правом «Закрытие чужих смен».",
        )
        open_button = QPushButton("Открыть смену")
        open_button.setObjectName("PrimaryButton")
        open_button.clicked.connect(self._open_shift)
        header.add_action(open_button)
        layout.addWidget(header)

        self.open_info = QLabel()
        self.open_info.setObjectName("InfoBanner")
        self.open_info.setWordWrap(True)
        layout.addWidget(self.open_info)

        self.table = make_table(
            [
                "№",
                "Продавец",
                "Открыта",
                "Закрыта",
                "Статус",
                "Чеков",
                "Выручка",
                "Прибыль",
                "Касса",
                "Расхождение",
            ]
        )
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5, 6, 7, 8, 9):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._show_report)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        report_button = QPushButton("Отчёт по смене")
        report_button.clicked.connect(self._show_report)
        close_button = QPushButton("Закрыть смену")
        close_button.setObjectName("DangerButton")
        close_button.clicked.connect(self._close_shift)
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.refresh)
        actions.addWidget(report_button)
        actions.addWidget(close_button)
        actions.addStretch(1)
        actions.addWidget(refresh_button)
        layout.addLayout(actions)

    def refresh(self) -> None:
        self._rows = self.ctx.stats.shifts_overview(limit=200)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows))
        currency = self.ctx.currency
        for row, shift in enumerate(self._rows):
            is_open = str(shift["status"]) == "open"
            status = "Открыта" if is_open else "Закрыта"
            closing_cash = (
                format_money(int(shift["closing_cash"]), currency)
                if shift["closing_cash"] is not None
                else "—"
            )
            difference = shift["cash_difference"]
            difference_text = (
                format_money(int(difference), currency) if difference is not None else "—"
            )
            values = [
                str(shift["id"]),
                str(shift["user_name"]),
                str(shift["opened_at"])[:16],
                str(shift["closed_at"])[:16] if shift["closed_at"] else "—",
                status,
                str(int(shift["sales_count"] or 0)),
                format_money(int(shift["revenue"] or 0), currency),
                format_money(int(shift["profit"] or 0), currency),
                closing_cash,
                difference_text,
            ]
            for column, value in enumerate(values):
                align = (
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    if column in (5, 6, 7, 8, 9)
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                color = None
                if column == 4:
                    color = "#15803d" if is_open else "#64748b"
                if column == 9 and difference not in (None, 0):
                    color = "#b45309" if int(difference) > 0 else "#b91c1c"
                set_cell(self.table, row, column, value, align=align, color=color)

        own_shift = self.ctx.shifts.open_shift_for_user(self.user.id)
        if own_shift:
            self.open_info.setText(
                f"Ваша смена №{own_shift.id} открыта с {own_shift.opened_at}. "
                "Продажи идут в неё."
            )
        else:
            self.open_info.setText(
                "У вас нет открытой смены. Чтобы начать продажи, откройте смену."
            )

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _open_shift(self) -> None:
        existing = self.ctx.shifts.open_shift_for_user(self.user.id)
        if existing:
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
        self.shift_changed.emit()
        self.refresh()
        info(self, f"Смена №{shift.id} открыта.")

    def _close_shift(self) -> None:
        selected = self._selected()
        if selected is None:
            own = self.ctx.shifts.open_shift_for_user(self.user.id)
            if own is None:
                warning(self, "Выберите смену")
                return
            shift_id = own.id
        else:
            shift_id = int(selected["id"])
        shift = self.ctx.shifts.get(shift_id)
        if shift is None:
            error(self, "Смена не найдена")
            return
        if not shift.is_open:
            warning(self, "Смена уже закрыта")
            return
        if shift.user_id != self.user.id and not self.ctx.users.has_permission(
            self.user, "manage_shifts"
        ):
            error(self, "Нет права закрывать смены других сотрудников")
            return
        if shift.user_id != self.user.id:
            if not confirm(
                self,
                f"Закрыть смену №{shift.id} продавца {shift.user_name}?",
            ):
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
        self.shift_changed.emit()
        self.refresh()
        ShiftReportDialog(closed_summary, self.ctx, self).exec()

    def _show_report(self) -> None:
        selected = self._selected()
        if selected is None:
            warning(self, "Выберите смену")
            return
        try:
            summary = self.ctx.stats.shift_summary(int(selected["id"]))
        except ServiceError as exc:
            error(self, str(exc))
            return
        ShiftReportDialog(summary, self.ctx, self).exec()
