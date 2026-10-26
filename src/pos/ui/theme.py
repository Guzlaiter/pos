"""Application-wide Qt stylesheet."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

QSS = """
* {
    outline: none;
}

QWidget {
    color: #0f172a;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}

QMainWindow, QWidget#AppRoot, QWidget#Page {
    background: #f4f6fb;
}

QFrame#Sidebar {
    background: #0f172a;
    border: none;
}

QLabel#BrandTitle {
    color: #ffffff;
    font-size: 22pt;
    font-weight: 800;
    letter-spacing: 2px;
}

QLabel#BrandSubtitle {
    color: #94a3b8;
    font-size: 9pt;
}

QLabel#NavSection {
    color: #64748b;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 12px 14px 4px 14px;
}

QPushButton#NavButton {
    color: #cbd5e1;
    background: transparent;
    border: none;
    border-radius: 9px;
    text-align: left;
    padding: 10px 14px;
    font-size: 10pt;
}

QPushButton#NavButton:hover {
    background: #1e293b;
    color: #ffffff;
}

QPushButton#NavButton:checked {
    background: #2563eb;
    color: #ffffff;
    font-weight: 600;
}

QFrame#TopBar {
    background: #ffffff;
    border-bottom: 1px solid #e5eaf2;
}

QFrame#Card, QFrame#StatCard, QWidget#Card {
    background: #ffffff;
    border: 1px solid #e5eaf2;
    border-radius: 14px;
}

QFrame#StatCardHighlight {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 14px;
}

QLabel#PageTitle {
    font-size: 20pt;
    font-weight: 700;
    color: #0f172a;
}

QLabel#PageSubtitle {
    font-size: 10pt;
    color: #64748b;
}

QLabel#SectionTitle {
    font-size: 12pt;
    font-weight: 700;
    color: #0f172a;
}

QLabel#Muted {
    color: #64748b;
    font-size: 9pt;
}

QLabel#StatTitle {
    color: #64748b;
    font-size: 9pt;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

QLabel#StatValue {
    color: #0f172a;
    font-size: 19pt;
    font-weight: 700;
}

QLabel#StatValueAccent {
    color: #2563eb;
    font-size: 19pt;
    font-weight: 700;
}

QLabel#StatHint {
    color: #94a3b8;
    font-size: 8.5pt;
}

QLabel#TotalValue {
    font-size: 26pt;
    font-weight: 800;
    color: #0f172a;
}

QLabel#ShiftOpen {
    background: #dcfce7;
    color: #166534;
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 9pt;
    font-weight: 600;
}

QLabel#ShiftClosed {
    background: #fee2e2;
    color: #991b1b;
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 9pt;
    font-weight: 600;
}

QLabel#WarningBanner {
    background: #fff7ed;
    color: #9a3412;
    border: 1px solid #fed7aa;
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 9.5pt;
}

QLabel#InfoBanner {
    background: #eff6ff;
    color: #1e40af;
    border: 1px solid #bfdbfe;
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 9.5pt;
}

QPushButton {
    background: #ffffff;
    color: #0f172a;
    border: 1px solid #d8e0ec;
    border-radius: 8px;
    padding: 8px 14px;
    min-height: 20px;
}

QPushButton:hover {
    background: #f1f6ff;
    border-color: #9dbcf7;
}

QPushButton:pressed {
    background: #e2ecff;
}

QPushButton:disabled {
    color: #94a3b8;
    background: #f1f5f9;
    border-color: #e2e8f0;
}

QPushButton#PrimaryButton {
    background: #2563eb;
    color: #ffffff;
    border: none;
    font-weight: 600;
    padding: 10px 18px;
}

QPushButton#PrimaryButton:hover {
    background: #1d4ed8;
}

QPushButton#PrimaryButton:pressed {
    background: #1e40af;
}

QPushButton#PrimaryButton:disabled {
    background: #93b4f5;
    color: #eff6ff;
}

QPushButton#SuccessButton {
    background: #16a34a;
    color: #ffffff;
    border: none;
    font-weight: 700;
    padding: 12px 18px;
}

QPushButton#SuccessButton:hover {
    background: #15803d;
}

QPushButton#SuccessButton:disabled {
    background: #9ad6af;
    color: #f0fdf4;
}

QPushButton#DangerButton {
    background: #dc2626;
    color: #ffffff;
    border: none;
    font-weight: 600;
}

QPushButton#DangerButton:hover {
    background: #b91c1c;
}

QPushButton#GhostButton {
    background: transparent;
    border: none;
    color: #475569;
    padding: 6px 8px;
}

QPushButton#GhostButton:hover {
    background: #eef2f8;
}

QPushButton#ProductButton {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 12px;
    text-align: left;
    font-weight: 600;
    color: #0f172a;
}

QPushButton#ProductButton:hover {
    background: #f8fbff;
    border-color: #2563eb;
}

QPushButton#ProductButton:disabled {
    background: #f8fafc;
    color: #94a3b8;
    border-color: #eef2f8;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {
    background: #ffffff;
    border: 1px solid #d8e0ec;
    border-radius: 8px;
    padding: 7px 10px;
    min-height: 22px;
    selection-background-color: #bfdbfe;
    selection-color: #0f172a;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid #2563eb;
}

QLineEdit::placeholder {
    color: #94a3b8;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d8e0ec;
    selection-background-color: #dbeafe;
    selection-color: #0f172a;
    padding: 4px;
}

QTableWidget, QTableView {
    background: #ffffff;
    alternate-background-color: #fafcff;
    border: 1px solid #e5eaf2;
    border-radius: 10px;
    gridline-color: #eef2f8;
    selection-background-color: #dbeafe;
    selection-color: #0f172a;
}

QTableWidget::item, QTableView::item {
    padding: 6px;
}

QHeaderView::section {
    background: #f8fafc;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    padding: 9px 8px;
    font-weight: 600;
    color: #475569;
}

QTableCornerButton::section {
    background: #f8fafc;
    border: none;
}

QTabWidget::pane {
    border: 1px solid #e5eaf2;
    border-radius: 10px;
    background: #ffffff;
    top: -1px;
}

QTabBar::tab {
    background: transparent;
    color: #64748b;
    padding: 9px 16px;
    border: none;
    border-bottom: 2px solid transparent;
}

QTabBar::tab:selected {
    color: #2563eb;
    border-bottom: 2px solid #2563eb;
    font-weight: 600;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background: #cbd5e1;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

QGroupBox {
    background: #ffffff;
    border: 1px solid #e5eaf2;
    border-radius: 12px;
    margin-top: 16px;
    padding: 16px 14px 14px 14px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    color: #334155;
    background: #f4f6fb;
}

QCheckBox, QRadioButton {
    spacing: 8px;
    color: #334155;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 17px;
    height: 17px;
}

QCheckBox::indicator {
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background: #ffffff;
}

QCheckBox::indicator:checked {
    background: #2563eb;
    border-color: #2563eb;
    image: none;
}

QCheckBox::indicator:disabled {
    background: #f1f5f9;
}

QProgressBar {
    border: none;
    background: #e2e8f0;
    border-radius: 5px;
    height: 8px;
    text-align: center;
}

QProgressBar::chunk {
    background: #2563eb;
    border-radius: 5px;
}

QToolTip {
    background: #0f172a;
    color: #ffffff;
    border: none;
    padding: 6px 8px;
    border-radius: 6px;
}

QSplitter::handle {
    background: transparent;
}

QFrame#LoginHero {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #0f172a, stop:0.55 #1e3a8a, stop:1 #2563eb);
    border: none;
}

QFrame#LoginCard {
    background: #ffffff;
    border: 1px solid #e5eaf2;
    border-radius: 18px;
}

QLabel#LoginTitle {
    font-size: 24pt;
    font-weight: 800;
    color: #0f172a;
}

QLabel#LoginSubtitle {
    font-size: 10pt;
    color: #64748b;
}

QLabel#HeroTitle {
    color: #ffffff;
    font-size: 26pt;
    font-weight: 800;
    letter-spacing: 3px;
}

QLabel#HeroSubtitle {
    color: #bfdbfe;
    font-size: 13pt;
    font-weight: 600;
}

QLabel#HeroText {
    color: #cbd5e1;
    font-size: 10pt;
}

QLabel#ErrorLabel {
    color: #b91c1c;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 9pt;
}

QLabel#Badge {
    background: #eff6ff;
    color: #1d4ed8;
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 8.5pt;
    font-weight: 600;
}

QLabel#SuccessBadge {
    background: #dcfce7;
    color: #166534;
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 8.5pt;
    font-weight: 600;
}

QDialog {
    background: #f4f6fb;
}

QMenu {
    background: #ffffff;
    border: 1px solid #d8e0ec;
    border-radius: 8px;
    padding: 6px;
}

QMenu::item {
    padding: 7px 24px 7px 12px;
    border-radius: 5px;
}

QMenu::item:selected {
    background: #eff6ff;
    color: #1d4ed8;
}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    app.setStyleSheet(QSS)
