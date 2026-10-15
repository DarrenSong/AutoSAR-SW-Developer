# -*- coding: utf-8 -*-
"""Consistency check report dialog with batch fix."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..checks import CheckIssue, run_consistency_checks, summarize_issues
from ..model import ArxmlModel
from ..os_rte import OsRteOverlay


class CheckDialog(QDialog):
    jump_to = Signal(str, str)  # path, kind
    about_to_fix = Signal(int, str)  # count, target primary|peer|mixed
    fixes_applied = Signal(int)  # count

    def __init__(
        self,
        model: ArxmlModel,
        parent=None,
        peer_model: ArxmlModel | None = None,
        os_rte: OsRteOverlay | None = None,
    ):
        super().__init__(parent)
        self._model = model
        self._peer_model = peer_model
        self._os_rte = os_rte
        self._all: List[CheckIssue] = []
        self.setWindowTitle("一致性检查")
        self.resize(980, 540)
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.cmb_sev = QComboBox()
        self.cmb_sev.addItem("全部", "all")
        self.cmb_sev.addItem("仅 Error", "error")
        self.cmb_sev.addItem("Error+Warning", "warning")
        self.cmb_sev.addItem("仅 Info", "info")
        self.cmb_sev.addItem("可修复", "fixable")
        self.cmb_sev.currentIndexChanged.connect(self._fill)
        btn = QPushButton("重新检查")
        btn.clicked.connect(self._run)
        btn_fix = QPushButton("应用勾选的修复")
        btn_fix.setToolTip(
            "对可修复项执行建议操作；对照文件项写到 peer（需 Save peer）"
        )
        btn_fix.clicked.connect(self._apply_fixes)
        btn_all = QPushButton("全选可修复")
        btn_all.clicked.connect(self._select_all_fixable)
        bar.addWidget(QLabel("级别:"))
        bar.addWidget(self.cmb_sev)
        bar.addWidget(btn)
        bar.addWidget(btn_all)
        bar.addWidget(btn_fix)
        bar.addStretch(1)
        self.lbl = QLabel("")
        bar.addWidget(self.lbl)
        lay.addLayout(bar)

        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(
            ["修复", "Severity", "Category", "Target", "Message", "Path"]
        )
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.cellDoubleClicked.connect(self._on_dbl)
        lay.addWidget(self.tbl, 1)

        tip = QLabel(
            "双击跳转 · 勾选「修复」后应用"
            "（删除坏 Assembly/Delegation、悬空 Data Mapping；"
            "Target=peer 写入对照文件）"
        )
        tip.setStyleSheet("color:#666;")
        lay.addWidget(tip)

        self._run()

    def _run(self):
        self._all = run_consistency_checks(
            self._model, peer_model=self._peer_model, os_rte=self._os_rte
        )
        n_fix = sum(1 for i in self._all if i.fix_action)
        peer_note = " +对照" if self._peer_model else ""
        os_note = " +OsRTE" if self._os_rte and (self._os_rte.tasks or self._os_rte.mappings) else ""
        self.lbl.setText(
            summarize_issues(self._all) + f"  Fixable={n_fix}{peer_note}{os_note}"
        )
        self._fill()

    def _visible_rows(self) -> List[CheckIssue]:
        mode = self.cmb_sev.currentData()
        rows = self._all
        if mode == "error":
            rows = [i for i in self._all if i.severity == "error"]
        elif mode == "warning":
            rows = [i for i in self._all if i.severity in ("error", "warning")]
        elif mode == "info":
            rows = [i for i in self._all if i.severity == "info"]
        elif mode == "fixable":
            rows = [i for i in self._all if i.fix_action]
        return rows

    def _fill(self):
        rows = self._visible_rows()
        self.tbl.setRowCount(0)
        colors = {
            "error": QColor("#c62828"),
            "warning": QColor("#ef6c00"),
            "info": QColor("#546e7a"),
        }
        for issue in rows:
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            if issue.fix_action:
                chk.setCheckState(Qt.CheckState.Unchecked)
                chk.setToolTip(issue.fix_label or issue.fix_action)
            else:
                chk.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                chk.setText("—")
            chk.setData(Qt.ItemDataRole.UserRole, issue)
            self.tbl.setItem(row, 0, chk)
            vals = [
                issue.severity,
                issue.category,
                issue.fix_target or "primary",
                issue.message,
                issue.path,
            ]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, issue.path)
                item.setData(Qt.ItemDataRole.UserRole + 1, issue.kind)
                if col == 0:
                    item.setForeground(colors.get(issue.severity, QColor("#333")))
                self.tbl.setItem(row, col + 1, item)
        self.tbl.resizeColumnsToContents()

    def _select_all_fixable(self):
        for row in range(self.tbl.rowCount()):
            item = self.tbl.item(row, 0)
            if not item:
                continue
            issue = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(issue, CheckIssue) and issue.fix_action:
                item.setCheckState(Qt.CheckState.Checked)

    def _target_model(self, issue: CheckIssue) -> ArxmlModel | None:
        if (issue.fix_target or "primary") == "peer":
            return self._peer_model
        return self._model

    def _apply_fixes(self):
        selected: List[CheckIssue] = []
        for row in range(self.tbl.rowCount()):
            item = self.tbl.item(row, 0)
            if not item or item.checkState() != Qt.CheckState.Checked:
                continue
            issue = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(issue, CheckIssue) and issue.fix_action:
                selected.append(issue)
        if not selected:
            QMessageBox.information(self, "修复", "未勾选任何可修复项。")
            return
        targets = {(i.fix_target or "primary") for i in selected}
        target_label = (
            "mixed" if len(targets) > 1 else next(iter(targets))
        )
        ans = QMessageBox.question(
            self,
            "应用修复",
            f"将对 {len(selected)} 项执行修复（多为删除坏连接）。\n"
            f"目标: {target_label}\n"
            "内存立即生效，需 File→Save / Save peer 写回。继续？",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.about_to_fix.emit(len(selected), target_label)
        applied = 0
        for issue in selected:
            m = self._target_model(issue)
            if not m:
                continue
            if issue.fix_action == "delete_connector":
                m.queue_delete_connector(
                    issue.path,
                    issue.fix_connector_name or issue.path.rsplit("/", 1)[-1],
                    issue.fix_composition,
                    issue.fix_connector_kind or "assembly",
                )
                applied += 1
            elif issue.fix_action == "delete_data_mapping":
                err = m.queue_delete_data_mapping(
                    issue.fix_connector_name or issue.path
                )
                if not err:
                    applied += 1
        self.fixes_applied.emit(applied)
        QMessageBox.information(self, "修复", f"已排队 {applied} 处修复。")
        self._run()

    def _on_dbl(self, row: int, col: int):
        if col == 0:
            return
        item = self.tbl.item(row, 1)
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole) or ""
        kind = item.data(Qt.ItemDataRole.UserRole + 1) or ""
        if path and kind:
            self.jump_to.emit(path, kind)
