# -*- coding: utf-8 -*-
"""Dialogs for System Data Mapping add / edit."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

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

from ..model import ArxmlModel, DataMapping


class AddDataMappingDialog(QDialog):
    def __init__(self, model: ArxmlModel, parent=None):
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("新增 Data Mapping")
        self.resize(620, 360)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("将 Prototype.Port.DataElement 映射到 System / I-Signal。")
        )

        form = QFormLayout()
        self.cmb_set = QComboBox()
        self.cmb_kind = QComboBox()
        self.cmb_proto = QComboBox()
        self.cmb_port = QComboBox()
        self.cmb_de = QComboBox()
        self.cmb_signal = QComboBox()
        self.edt_name = QLineEdit()
        self._name_manual = False

        self.cmb_kind.addItem("SR → System Signal", "SR-TO-SIGNAL")
        self.cmb_kind.addItem("SR → I-Signal", "SR-TO-I-SIGNAL")

        for sp in model.system_mapping_sets:
            self.cmb_set.addItem(model.resolve_name(sp) or sp, sp)

        # all prototypes under compositions
        for proto in sorted(model.prototypes.values(), key=lambda p: p.name):
            owner = model.resolve_name(proto.owner_path) if proto.owner_path else ""
            label = f"{proto.name}" + (f" @{owner}" if owner else "")
            self.cmb_proto.addItem(label, proto.path)

        form.addRow("SYSTEM-MAPPING:", self.cmb_set)
        form.addRow("Kind:", self.cmb_kind)
        form.addRow("Prototype:", self.cmb_proto)
        form.addRow("Port:", self.cmb_port)
        form.addRow("DataElement:", self.cmb_de)
        form.addRow("Signal:", self.cmb_signal)
        form.addRow("Mapping name:", self.edt_name)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.cmb_proto.currentIndexChanged.connect(self._refresh_ports)
        self.cmb_port.currentIndexChanged.connect(self._refresh_data_elements)
        self.cmb_kind.currentIndexChanged.connect(self._refresh_signals)
        self.cmb_de.currentIndexChanged.connect(self._auto_name)
        self.cmb_signal.currentIndexChanged.connect(self._auto_name)
        self.edt_name.textEdited.connect(lambda: setattr(self, "_name_manual", True))

        self._refresh_ports()
        self._refresh_signals()

    def _refresh_ports(self):
        self.cmb_port.clear()
        proto = self._model.prototypes.get(self.cmb_proto.currentData() or "")
        if not proto:
            self._refresh_data_elements()
            return
        swc = self._model.swc_types.get(proto.type_ref)
        if not swc:
            self._refresh_data_elements()
            return
        for p in swc.ports:
            if p.iface_kind and p.iface_kind not in ("SR", "OTHER", ""):
                continue
            self.cmb_port.addItem(f"{p.direction}-{p.name}", p.path)
        self._refresh_data_elements()

    def _refresh_data_elements(self):
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

    def _refresh_signals(self):
        self.cmb_signal.clear()
        kind = self.cmb_kind.currentData() or "SR-TO-SIGNAL"
        src: Dict[str, str] = (
            self._model.i_signals
            if kind == "SR-TO-I-SIGNAL"
            else self._model.system_signals
        )
        for path, name in sorted(src.items(), key=lambda x: x[1]):
            self.cmb_signal.addItem(name, path)
        self._auto_name()

    def _auto_name(self):
        if self._name_manual:
            return
        proto = self._model.prototypes.get(self.cmb_proto.currentData() or "")
        port = self._model.ports.get(self.cmb_port.currentData() or "")
        de_name = self.cmb_de.currentText() or ""
        sig = self.cmb_signal.currentText() or ""
        if not (proto and port and de_name):
            return
        self.edt_name.setText(f"Map_{proto.name}_{port.name}_{de_name}")
        if sig and not self.edt_name.text():
            self.edt_name.setText(f"Map_{sig}")

    def _on_ok(self):
        if not self.cmb_set.currentData():
            QMessageBox.warning(self, "Mapping", "没有可用的 SYSTEM-MAPPING。")
            return
        if not all(
            [
                self.cmb_proto.currentData(),
                self.cmb_port.currentData(),
                self.cmb_de.currentData(),
                self.cmb_signal.currentData(),
            ]
        ):
            QMessageBox.warning(self, "Mapping", "请选择完整的字段。")
            return
        if not (self.edt_name.text() or "").strip():
            QMessageBox.warning(self, "Mapping", "请填写映射名称。")
            return
        self.accept()

    def result_values(
        self,
    ) -> Optional[Tuple[str, str, str, str, str, str, str]]:
        name = (self.edt_name.text() or "").strip()
        set_path = self.cmb_set.currentData() or ""
        kind = self.cmb_kind.currentData() or "SR-TO-SIGNAL"
        proto = self.cmb_proto.currentData() or ""
        port = self.cmb_port.currentData() or ""
        de = self.cmb_de.currentData() or ""
        sig = self.cmb_signal.currentData() or ""
        if not all([name, set_path, proto, port, de, sig]):
            return None
        return set_path, name, kind, proto, port, de, sig


class EditDataMappingDialog(QDialog):
    """Rebind signal and/or rename an existing mapping."""

    def __init__(self, model: ArxmlModel, dm: DataMapping, parent=None):
        super().__init__(parent)
        self._model = model
        self._dm = dm
        self.setWindowTitle(f"编辑 Mapping: {dm.name}")
        self.resize(520, 220)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"{dm.kind}\n"
                f"Component: {model.resolve_name(dm.component_ref)}\n"
                f"Port: {model.resolve_name(dm.port_ref)}  "
                f"DE: {model.resolve_name(dm.data_element_ref)}"
            )
        )
        form = QFormLayout()
        self.edt_name = QLineEdit(dm.name)
        self.cmb_signal = QComboBox()
        use_i = dm.kind == "SR-TO-I-SIGNAL" or (
            dm.signal_ref in model.i_signals
        )
        src = model.i_signals if use_i else model.system_signals
        cur_idx = 0
        for i, (path, name) in enumerate(sorted(src.items(), key=lambda x: x[1])):
            self.cmb_signal.addItem(name, path)
            if path == dm.signal_ref:
                cur_idx = i
        if self.cmb_signal.count():
            self.cmb_signal.setCurrentIndex(cur_idx)
        form.addRow("Name:", self.edt_name)
        form.addRow("Signal:", self.cmb_signal)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_values(self) -> Tuple[str, str]:
        return (
            (self.edt_name.text() or "").strip(),
            self.cmb_signal.currentData() or "",
        )
