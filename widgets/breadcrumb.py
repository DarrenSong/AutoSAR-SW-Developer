# -*- coding: utf-8 -*-
"""Clickable breadcrumb bar (Simulink-style hierarchy navigation)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QWidget


class BreadcrumbBar(QWidget):
    """Horizontal path: part0 › part1 › part2. Clicking a segment emits its index."""

    activated = Signal(int)  # index into parts

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parts: list[str] = []
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_parts(self, parts: list[str]):
        self._parts = list(parts)
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not parts:
            empty = QLabel("")
            self._lay.addWidget(empty, 1)
            return
        for i, name in enumerate(parts):
            if i > 0:
                sep = QLabel("›")
                sep.setStyleSheet("color:#888; padding:0 2px;")
                self._lay.addWidget(sep)
            btn = QToolButton()
            btn.setText(name or "?")
            btn.setAutoRaise(True)
            btn.setToolTip(f"跳转到: {name}" if i < len(parts) - 1 else name)
            is_last = i == len(parts) - 1
            if is_last:
                btn.setStyleSheet("QToolButton { font-weight: bold; color: #333; }")
                btn.setEnabled(False)
            else:
                btn.setStyleSheet(
                    "QToolButton { color: #1565c0; text-decoration: underline; }"
                    "QToolButton:hover { color: #0d47a1; }"
                )
                btn.clicked.connect(lambda checked=False, idx=i: self.activated.emit(idx))
            self._lay.addWidget(btn)
        self._lay.addStretch(1)

    def parts(self) -> list[str]:
        return list(self._parts)
