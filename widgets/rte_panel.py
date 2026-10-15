# -*- coding: utf-8 -*-
"""RTE mapping panel: Events + Port Access tables (SWC Internal Behavior)."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model import ArxmlModel, SwcInternalBehavior


class RtePanel(QWidget):
    """Shows Events and Port Access for a selected SWC / Behavior / Runnable."""

    runnable_selected = Signal(str)  # runnable path
    event_selected = Signal(str)  # event path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: Optional[ArxmlModel] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#666; font-size:11px;")
        lay.addWidget(self.hint)

        lay.addWidget(QLabel("RTE Events"))
        self.ev_table = QTableWidget(0, 5)
        self.ev_table.setHorizontalHeaderLabels(
            ["Kind", "Name", "Period", "Offset", "Runnable"]
        )
        self.ev_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ev_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ev_table.setAlternatingRowColors(True)
        self.ev_table.itemSelectionChanged.connect(self._on_ev_sel)
        lay.addWidget(self.ev_table, 1)

        lay.addWidget(QLabel("Port Access (DataSend / Receive / ServerCall)"))
        self.acc_table = QTableWidget(0, 4)
        self.acc_table.setHorizontalHeaderLabels(
            ["Kind", "Port", "DataElement / Operation", "Runnable"]
        )
        self.acc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.acc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.acc_table.setAlternatingRowColors(True)
        self.acc_table.itemSelectionChanged.connect(self._on_acc_sel)
        lay.addWidget(self.acc_table, 1)

    def set_model(self, model: Optional[ArxmlModel]):
        self._model = model
        self.clear()

    def clear(self):
        self.hint.setText("")
        self.ev_table.setRowCount(0)
        self.acc_table.setRowCount(0)

    def show_swc(self, swc_path: str):
        if not self._model:
            self.clear()
            return
        behaviors = self._model.behaviors_of_swc(swc_path)
        if not behaviors:
            self.clear()
            self.hint.setText("该 Application SWC 无 SWC-INTERNAL-BEHAVIOR。")
            return
        empty = all(b.is_empty for b in behaviors)
        if empty:
            self.hint.setText(
                "导出中 Internal Behavior 为空壳（无有效 SHORT-NAME / REF）。"
                "界面仍列出节点，但 Event→Runnable→Port 映射不可用。"
            )
        else:
            n_r = sum(len(b.runnables) for b in behaviors)
            n_e = sum(len(b.events) for b in behaviors)
            self.hint.setText(
                f"Internal Behavior ×{len(behaviors)} · "
                f"Runnables={n_r} · Events={n_e}"
            )
        self._fill_from_behaviors(behaviors)

    def show_behavior(self, behavior_path: str):
        if not self._model:
            self.clear()
            return
        beh = None
        for blist in self._model.behaviors_by_swc.values():
            for b in blist:
                if b.path == behavior_path:
                    beh = b
                    break
        if not beh:
            self.clear()
            return
        if beh.is_empty:
            self.hint.setText(
                f"IB「{beh.name}」为空壳（无有效 SHORT-NAME / REF）。"
            )
        else:
            self.hint.setText(f"IB: {beh.name}  ({beh.path})")
        self._fill_from_behaviors([beh])

    def show_runnable(self, runnable_path: str):
        if not self._model:
            self.clear()
            return
        r = self._model.runnables.get(runnable_path)
        if not r:
            self.clear()
            return
        # events that trigger this runnable
        events = [
            self._model.rte_events[p]
            for p in r.triggered_by
            if p in self._model.rte_events
        ]
        self.hint.setText(
            f"Runnable: {r.name}"
            + (f"  symbol={r.symbol}" if r.symbol else "")
            + f"  · triggered by {len(events)} event(s)"
        )
        self._fill_events(events)
        self._fill_accesses(r.accesses, default_runnable=r.name)

    def show_port(self, port_path: str):
        """List runnables that access this port."""
        if not self._model:
            self.clear()
            return
        runnables = self._model.runnables_accessing_port(port_path)
        accesses = self._model.accesses_by_port.get(port_path, [])
        pname = self._model.resolve_name(port_path)
        if not runnables:
            self.hint.setText(
                f"Port「{pname}」：无 Runnable 通过 VARIABLE-ACCESS / ServerCall 访问"
                "（空壳 IB 时通常为 0）。"
            )
            self.ev_table.setRowCount(0)
            self.acc_table.setRowCount(0)
            return
        self.hint.setText(
            f"访问 Port「{pname}」的 Runnable：{', '.join(r.name for r in runnables)}"
        )
        # events for those runnables
        events = []
        seen = set()
        for r in runnables:
            for ep in r.triggered_by:
                if ep in seen:
                    continue
                seen.add(ep)
                ev = self._model.rte_events.get(ep)
                if ev:
                    events.append(ev)
        self._fill_events(events)
        self._fill_accesses(accesses)

    def _fill_from_behaviors(self, behaviors: List[SwcInternalBehavior]):
        events = []
        accesses = []
        for b in behaviors:
            events.extend(b.events)
            for r in b.runnables:
                accesses.extend(r.accesses)
        self._fill_events(events)
        self._fill_accesses(accesses)

    def _fill_events(self, events):
        self.ev_table.setRowCount(0)
        if not self._model:
            return
        for ev in events:
            row = self.ev_table.rowCount()
            self.ev_table.insertRow(row)
            run_name = ""
            if ev.start_on_runnable_ref:
                run_name = self._model.resolve_name(ev.start_on_runnable_ref)
            vals = [
                ev.kind,
                ev.name or "(empty)",
                ev.period or "",
                ev.offset or "",
                run_name,
            ]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, ev.path)
                if col == 4 and ev.start_on_runnable_ref:
                    item.setData(Qt.ItemDataRole.UserRole + 1, ev.start_on_runnable_ref)
                self.ev_table.setItem(row, col, item)
        self.ev_table.resizeColumnsToContents()

    def _fill_accesses(self, accesses, default_runnable: str = ""):
        self.acc_table.setRowCount(0)
        if not self._model:
            return
        for acc in accesses:
            row = self.acc_table.rowCount()
            self.acc_table.insertRow(row)
            port_n = (
                self._model.resolve_name(acc.port_ref) if acc.port_ref else "(empty)"
            )
            target = acc.data_element_ref or acc.operation_ref or ""
            target_n = self._model.resolve_name(target) if target else ""
            run_n = default_runnable
            if not run_n and acc.runnable_path:
                run_n = self._model.resolve_name(acc.runnable_path)
            vals = [acc.access_kind, port_n, target_n, run_n]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, acc.runnable_path)
                if acc.port_ref:
                    item.setData(Qt.ItemDataRole.UserRole + 1, acc.port_ref)
                self.acc_table.setItem(row, col, item)
        self.acc_table.resizeColumnsToContents()

    def _on_ev_sel(self):
        items = self.ev_table.selectedItems()
        if not items:
            return
        path = items[0].data(Qt.ItemDataRole.UserRole) or ""
        if path:
            self.event_selected.emit(path)
        run_ref = items[0].data(Qt.ItemDataRole.UserRole + 1) or ""
        if run_ref:
            self.runnable_selected.emit(run_ref)

    def _on_acc_sel(self):
        items = self.acc_table.selectedItems()
        if not items:
            return
        run_path = items[0].data(Qt.ItemDataRole.UserRole) or ""
        if run_path:
            self.runnable_selected.emit(run_path)
