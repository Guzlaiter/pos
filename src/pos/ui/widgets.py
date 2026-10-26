"""Shared UI widgets and helpers."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..money import format_money
from ..models import DailyPoint


# --------------------------------------------------------------------- helpers
def info(parent: QWidget | None, text: str, title: str = "POS") -> None:
    QMessageBox.information(parent, title, text)


def error(parent: QWidget | None, text: str, title: str = "Ошибка") -> None:
    QMessageBox.critical(parent, title, text)


def warning(parent: QWidget | None, text: str, title: str = "Внимание") -> None:
    QMessageBox.warning(parent, title, text)


def confirm(parent: QWidget | None, text: str, title: str = "Подтверждение") -> bool:
    answer = QMessageBox.question(
        parent,
        title,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def center_window(widget: QWidget) -> None:
    screen = QApplication.primaryScreen()
    if screen is None:
        return
    geometry = widget.frameGeometry()
    geometry.moveCenter(screen.availableGeometry().center())
    widget.move(geometry.topLeft())


# -------------------------------------------------------------------- money UI
class MoneySpinBox(QDoubleSpinBox):
    """A money input that stores and returns integer cents."""

    def __init__(self, parent: QWidget | None = None, maximum_cents: int = 10**11):
        super().__init__(parent)
        self.setDecimals(2)
        self.setRange(0, maximum_cents / 100)
        self.setSingleStep(1.0)
        self.setGroupSeparatorShown(True)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)

    def cents(self) -> int:
        return int(
            (Decimal(str(self.value())) * 100).to_integral_value(rounding=ROUND_HALF_UP)
        )

    def set_cents(self, cents: int) -> None:
        self.setValue(max(0, int(cents)) / 100)


# ------------------------------------------------------------------ primitives
class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        text_layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("PageSubtitle")
            subtitle_label.setWordWrap(True)
            text_layout.addWidget(subtitle_label)
        layout.addLayout(text_layout, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)


class StatCard(QFrame):
    def __init__(
        self,
        title: str,
        value: str = "—",
        hint: str = "",
        *,
        accent: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("StatCardHighlight" if accent else "StatCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("StatTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValueAccent" if accent else "StatValue")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("StatHint")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.hint_label)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_value(self, value: str, hint: str | None = None) -> None:
        self.value_label.setText(value)
        if hint is not None:
            self.hint_label.setText(hint)


class Badge(QLabel):
    def __init__(self, text: str = "", success: bool = False, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("SuccessBadge" if success else "Badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_state(self, text: str, success: bool) -> None:
        self.setText(text)
        self.setObjectName("SuccessBadge" if success else "Badge")
        self.style().unpolish(self)
        self.style().polish(self)


class BarChart(QWidget):
    """Small dependency-free revenue-by-day chart."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._points: list[DailyPoint] = []
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, points: list[DailyPoint]) -> None:
        self._points = points
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        points = self._points
        if not points or not any(point.revenue > 0 for point in points):
            painter.setPen(QPen(QColor("#94a3b8")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Нет продаж за выбранный период")
            return

        values = [max(0, point.revenue) for point in points]
        max_value = max(values) or 1
        left = rect.left() + 64
        right = rect.right()
        top = rect.top() + 16
        bottom = rect.bottom() - 28
        chart_width = max(1, right - left)
        chart_height = max(1, bottom - top)

        # Horizontal grid with money labels.
        font = QFont(self.font())
        font.setPointSize(8)
        painter.setFont(font)
        for step in range(5):
            fraction = step / 4
            y = int(bottom - chart_height * fraction)
            painter.setPen(QPen(QColor("#eef2f8"), 1))
            painter.drawLine(left, y, right, y)
            painter.setPen(QPen(QColor("#94a3b8")))
            label = format_money(int(max_value * fraction), with_currency=False)
            painter.drawText(0, y - 9, left - 8, 18, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)

        count = len(values)
        slot = chart_width / max(1, count)
        bar_width = max(3.0, min(26.0, slot * 0.62))
        label_every = max(1, count // 12)
        for index, value in enumerate(values):
            height = int(chart_height * (value / max_value)) if value else 0
            x = int(left + slot * index + (slot - bar_width) / 2)
            bar_rect = (x, bottom - height, int(bar_width), height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#2563eb" if value else "#e2e8f0"))
            painter.drawRoundedRect(*bar_rect, 3, 3)
            if index % label_every == 0 or index == count - 1:
                painter.setPen(QPen(QColor("#64748b")))
                label = points[index].date[8:10] if len(points[index].date) >= 10 else points[index].date
                painter.drawText(
                    int(left + slot * index),
                    bottom + 6,
                    int(slot),
                    18,
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    label,
                )


def make_table(headers: list[str], *, stretch_last: bool = True) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.horizontalHeader().setStretchLastSection(stretch_last)
    table.horizontalHeader().setHighlightSections(False)
    table.verticalHeader().setDefaultSectionSize(36)
    return table


def set_cell(
    table: QTableWidget,
    row: int,
    column: int,
    text: str,
    *,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    color: str | None = None,
    bold: bool = False,
) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(align)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color:
        item.setForeground(QColor(color))
    if bold:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
    table.setItem(row, column, item)
    return item


def fill_table(table: QTableWidget, rows: list[list[str]], *, align_right: set[int] | None = None) -> None:
    align_right = align_right or set()
    table.setRowCount(0)
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            align = (
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                if column in align_right
                else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            set_cell(table, row_index, column, str(value), align=align)


class TextDocumentDialog(QDialog):
    """Monospace receipt/report viewer with print, copy and save actions."""

    def __init__(
        self,
        title: str,
        text: str,
        *,
        default_path: Path | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 640)
        self._default_path = default_path
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(text)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        editor.setFont(font)
        layout.addWidget(editor, 1)

        buttons = QHBoxLayout()
        print_button = QPushButton("Печать")
        print_button.setObjectName("PrimaryButton")
        print_button.clicked.connect(self._print)
        save_button = QPushButton("Сохранить в файл")
        save_button.clicked.connect(self._save)
        copy_button = QPushButton("Копировать")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(text))
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(print_button)
        buttons.addWidget(save_button)
        buttons.addWidget(copy_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _print(self) -> None:
        try:
            from PySide6.QtGui import QTextDocument
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        except ImportError:
            error(self, "Модуль печати недоступен")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            document = QTextDocument()
            document.setPlainText(self._text_from_editor())
            font = QFont("Consolas", 9)
            document.setDefaultFont(font)
            try:
                document.print_(printer)
            except Exception as exc:  # pragma: no cover - depends on printer
                error(self, f"Не удалось отправить документ на печать:\n{exc}")

    def _text_from_editor(self) -> str:
        editors = self.findChildren(QPlainTextEdit)
        return editors[0].toPlainText() if editors else ""

    def _save(self) -> None:
        default = str(self._default_path) if self._default_path else "receipt.txt"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Сохранить", default, "Текстовый файл (*.txt)"
        )
        if not filename:
            return
        try:
            Path(filename).write_text(self._text_from_editor(), encoding="utf-8")
        except OSError as exc:
            error(self, f"Не удалось сохранить файл:\n{exc}")
            return
        info(self, "Файл сохранён")


def today_qdate() -> QDate:
    return QDate.currentDate()
