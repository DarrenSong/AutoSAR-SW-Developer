# -*- coding: utf-8 -*-
"""Preview dialog before batch creating delegated outer ports."""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..model import ArxmlModel, Port, Prototype


def _preview_outer_name(port: Port) -> str:
    """Match ArxmlModel.queue_add_delegated_outer_port default naming."""
    direction = port.direction or "R"
    suffix = "_DG_P" if direction == "P" else "_DG_R"
    base = f"{port.name}{suffix}"
    if not base.endswith(("_DG_P", "_DG_R", "_P", "_R")):
        base = base + suffix
    return base


class BatchDelegatePreviewDialog(QDialog):
    def __init__(
        self,
        model: ArxmlModel,
        composition_path: str,
        candidates: List[Tuple[Prototype, Port]],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("批量委托预览")
        self.resize(780, 460)
        self._accepted_rows = list(candidates)
        lay = QVBoxLayout(self)
        self._summary = QLabel(
            f"将在 {model.resolve_name(composition_path)} 创建 "
            f"{len(candidates)} 个 Outer …_DG + Delegation（可取消不需要的行）："
        )
        lay.addWidget(self._summary)
        self.tbl = QTableWidget(len(candidates), 5)
        self.tbl.setHorizontalHeaderLabels(
            ["选", "Prototype", "Inner Port", "方向", "将生成 Outer"]
        )
        for i, (proto, port) in enumerate(candidates):
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            chk.setCheckState(Qt.CheckState.Checked)
            outer = _preview_outer_name(port)
            self.tbl.setItem(i, 0, chk)
            self.tbl.setItem(i, 1, QTableWidgetItem(proto.name))
            self.tbl.setItem(i, 2, QTableWidgetItem(port.name))
            self.tbl.setItem(i, 3, QTableWidgetItem(port.direction))
            self.tbl.setItem(i, 4, QTableWidgetItem(outer))
            self.tbl.item(i, 1).setData(Qt.ItemDataRole.UserRole, (proto.path, port.path))
        self.tbl.resizeColumnsToContents()
        self.tbl.itemChanged.connect(self._update_summary)
        lay.addWidget(self.tbl, 1)
        sel_bar = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_none = QPushButton("全不选")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        sel_bar.addWidget(btn_all)
        sel_bar.addWidget(btn_none)
        sel_bar.addStretch(1)
        lay.addLayout(sel_bar)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("确认创建")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _set_all(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.tbl.blockSignals(True)
        for i in range(self.tbl.rowCount()):
            chk = self.tbl.item(i, 0)
            if chk:
                chk.setCheckState(state)
        self.tbl.blockSignals(False)
        self._update_summary()

    def _update_summary(self, *_args):
        n = sum(
            1
            for i in range(self.tbl.rowCount())
            if self.tbl.item(i, 0)
            and self.tbl.item(i, 0).checkState() == Qt.CheckState.Checked
        )
        text = self._summary.text()
        # keep composition name prefix; refresh count clause
        if "创建 " in text:
            head = text.split("创建 ", 1)[0]
            self._summary.setText(
                f"{head}创建 {n}/{self.tbl.rowCount()} 个 Outer …_DG + Delegation"
                f"（可取消不需要的行）："
            )

    def selected_candidates(
        self, all_candidates: List[Tuple[Prototype, Port]]
    ) -> List[Tuple[Prototype, Port]]:
        out = []
        for i, cand in enumerate(all_candidates):
            chk = self.tbl.item(i, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                out.append(cand)
        return out
