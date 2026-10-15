# -*- coding: utf-8 -*-
"""Dialogs for Internal Behavior (Runnable / TimingEvent / PortAccess) edits."""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ..model import ArxmlModel, SwcInternalBehavior


def _behaviors(model: ArxmlModel) -> List[SwcInternalBehavior]:
    out: List[SwcInternalBehavior] = []
    for blist in model.behaviors_by_swc.values():
        out.extend(blist)
    return out


class AddRunnableDialog(QDialog):
    def __init__(
        self, model: ArxmlModel, behavior_path: str = "", parent=None
    ):
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("新增 Runnable")
        self.resize(480, 200)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.cmb_beh = QComboBox()
        self.edt_name = QLineEdit()
        self.edt_symbol = QLineEdit()
        for b in _behaviors(model):
            label = f"{model.resolve_name(b.owner_swc)} / {b.name}"
            self.cmb_beh.addItem(label, b.path)
            if behavior_path and b.path == behavior_path:
                self.cmb_beh.setCurrentIndex(self.cmb_beh.count() - 1)
        form.addRow("Internal Behavior:", self.cmb_beh)
        form.addRow("Name:", self.edt_name)
        form.addRow("Symbol:", self.edt_symbol)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.edt_name.textChanged.connect(self._sync_symbol)

    def _sync_symbol(self, text: str):
        if not self.edt_symbol.isModified():
            self.edt_symbol.setText(text)

    def _on_ok(self):
        if not self.cmb_beh.currentData():
            QMessageBox.warning(self, "Runnable", "请选择 Internal Behavior。")
            return
        if not (self.edt_name.text() or "").strip():
            QMessageBox.warning(self, "Runnable", "请填写名称。")
            return
        self.accept()

    def result_values(self) -> Optional[Tuple[str, str, str]]:
        beh = self.cmb_beh.currentData() or ""
        name = (self.edt_name.text() or "").strip()
        symbol = (self.edt_symbol.text() or "").strip() or name
        if not beh or not name:
            return None
        return beh, name, symbol


class AddTimingEventDialog(QDialog):
    def __init__(
        self, model: ArxmlModel, behavior_path: str = "", parent=None
    ):
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("新增 Timing Event")
        self.resize(520, 260)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.cmb_beh = QComboBox()
        self.cmb_run = QComboBox()
        self.edt_name = QLineEdit()
        self.edt_period = QLineEdit("0.01")
        self.edt_offset = QLineEdit("0")
        for b in _behaviors(model):
            label = f"{model.resolve_name(b.owner_swc)} / {b.name}"
            self.cmb_beh.addItem(label, b.path)
            if behavior_path and b.path == behavior_path:
                self.cmb_beh.setCurrentIndex(self.cmb_beh.count() - 1)
        form.addRow("Internal Behavior:", self.cmb_beh)
        form.addRow("Runnable:", self.cmb_run)
        form.addRow("Event name:", self.edt_name)
        form.addRow("Period (s):", self.edt_period)
        form.addRow("Offset:", self.edt_offset)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.cmb_beh.currentIndexChanged.connect(self._refresh_runnables)
        self.cmb_run.currentIndexChanged.connect(self._auto_name)
        self._name_manual = False
        self.edt_name.textEdited.connect(lambda: setattr(self, "_name_manual", True))
        self._refresh_runnables()

    def _refresh_runnables(self):
        self.cmb_run.clear()
        beh_path = self.cmb_beh.currentData() or ""
        beh = next((b for b in _behaviors(self._model) if b.path == beh_path), None)
        if not beh:
            return
        for r in beh.runnables:
            self.cmb_run.addItem(r.name, r.path)
        self._auto_name()

    def _auto_name(self):
        if self._name_manual:
            return
        run = self.cmb_run.currentText() or "RE"
        self.edt_name.setText(f"Ev_{run}")

    def _on_ok(self):
        if not self.cmb_beh.currentData() or not self.cmb_run.currentData():
            QMessageBox.warning(self, "Event", "请选择 Behavior 与 Runnable。")
            return
        if not (self.edt_name.text() or "").strip():
            QMessageBox.warning(self, "Event", "请填写 Event 名称。")
            return
        self.accept()

    def result_values(self) -> Optional[Tuple[str, str, str, str, str]]:
        beh = self.cmb_beh.currentData() or ""
        run = self.cmb_run.currentData() or ""
        name = (self.edt_name.text() or "").strip()
        period = (self.edt_period.text() or "").strip() or "0.01"
        offset = (self.edt_offset.text() or "").strip() or "0"
        if not all([beh, run, name]):
            return None
        return beh, name, run, period, offset


class AddPortAccessDialog(QDialog):
    def __init__(
        self, model: ArxmlModel, runnable_path: str = "", parent=None
    ):
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("新增 Port Access")
        self.resize(560, 280)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.cmb_run = QComboBox()
        self.cmb_kind = QComboBox()
        self.cmb_port = QComboBox()
        self.cmb_de = QComboBox()
        self.edt_name = QLineEdit()
        self._name_manual = False

        self.cmb_kind.addItem("SEND (DataSendPoint)", "SEND")
        self.cmb_kind.addItem("RECEIVE (DataReceivePoint)", "RECEIVE")

        for r in sorted(model.runnables.values(), key=lambda x: x.name):
            owner = model.resolve_name(r.owner_swc)
            self.cmb_run.addItem(f"{r.name} @{owner}", r.path)
            if runnable_path and r.path == runnable_path:
                self.cmb_run.setCurrentIndex(self.cmb_run.count() - 1)

        form.addRow("Runnable:", self.cmb_run)
        form.addRow("Access kind:", self.cmb_kind)
        form.addRow("Port:", self.cmb_port)
        form.addRow("DataElement:", self.cmb_de)
        form.addRow("Access name:", self.edt_name)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.cmb_run.currentIndexChanged.connect(self._refresh_ports)
        self.cmb_kind.currentIndexChanged.connect(self._refresh_ports)
        self.cmb_port.currentIndexChanged.connect(self._refresh_de)
        self.cmb_de.currentIndexChanged.connect(self._auto_name)
        self.edt_name.textEdited.connect(lambda: setattr(self, "_name_manual", True))
        self._refresh_ports()

    def _refresh_ports(self):
        self.cmb_port.clear()
        r = self._model.runnables.get(self.cmb_run.currentData() or "")
        kind = self.cmb_kind.currentData() or "SEND"
        want_dir = "P" if kind == "SEND" else "R"
        if not r:
            self._refresh_de()
            return
        swc = self._model.swc_types.get(r.owner_swc)
        if not swc:
            self._refresh_de()
            return
        for p in swc.ports:
            if p.direction != want_dir:
                continue
            if p.iface_kind and p.iface_kind not in ("SR", "OTHER", ""):
                continue
            self.cmb_port.addItem(f"{p.direction}-{p.name}", p.path)
        self._refresh_de()

    def _refresh_de(self):
        self.cmb_de.clear()
        port = self._model.ports.get(self.cmb_port.currentData() or "")
        if not port or not port.interface_ref:
            self._auto_name()
            return
        iface = self._model.interfaces.get(port.interface_ref)
        if not iface:
            self._auto_name()
            return
        for de in iface.data_elements:
            self.cmb_de.addItem(de.name, de.path)
        self._auto_name()

    def _auto_name(self):
        if self._name_manual:
            return
        kind = self.cmb_kind.currentData() or "SEND"
        port = self._model.ports.get(self.cmb_port.currentData() or "")
        de = self.cmb_de.currentText() or ""
        if not port or not de:
            return
        prefix = "DSP" if kind == "SEND" else "DRP"
        self.edt_name.setText(f"{prefix}_{port.name}_{de}")

    def _on_ok(self):
        if not all(
            [
                self.cmb_run.currentData(),
                self.cmb_port.currentData(),
                self.cmb_de.currentData(),
            ]
        ):
            QMessageBox.warning(self, "Port Access", "请选择完整字段。")
            return
        self.accept()

    def result_values(self) -> Optional[Tuple[str, str, str, str, str]]:
        run = self.cmb_run.currentData() or ""
        kind = self.cmb_kind.currentData() or "SEND"
        port = self.cmb_port.currentData() or ""
        de = self.cmb_de.currentData() or ""
        name = (self.edt_name.text() or "").strip()
        if not all([run, port, de]):
            return None
        return run, kind, port, de, name


class RebindEventRunnableDialog(QDialog):
    def __init__(self, model: ArxmlModel, event_path: str, parent=None):
        super().__init__(parent)
        self._model = model
        self._ev = model.rte_events.get(event_path)
        self.setWindowTitle("重绑定 Event → Runnable")
        self.resize(480, 160)
        layout = QVBoxLayout(self)
        if self._ev:
            layout.addWidget(
                QLabel(f"Event: {self._ev.name} ({self._ev.kind})")
            )
        form = QFormLayout()
        self.cmb_run = QComboBox()
        beh = None
        if self._ev:
            for b in _behaviors(model):
                if b.path == self._ev.behavior_path:
                    beh = b
                    break
        runs = beh.runnables if beh else list(model.runnables.values())
        cur = 0
        for i, r in enumerate(runs):
            self.cmb_run.addItem(r.name, r.path)
            if self._ev and r.path == self._ev.start_on_runnable_ref:
                cur = i
        if self.cmb_run.count():
            self.cmb_run.setCurrentIndex(cur)
        form.addRow("Runnable:", self.cmb_run)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_runnable(self) -> str:
        return self.cmb_run.currentData() or ""
