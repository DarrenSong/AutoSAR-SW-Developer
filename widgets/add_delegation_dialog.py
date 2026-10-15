# -*- coding: utf-8 -*-
"""Dialog to create a new DELEGATION-SW-CONNECTOR."""
from __future__ import annotations

from typing import Optional, Tuple

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

from ..model import ArxmlModel


class AddDelegationDialog(QDialog):
    def __init__(self, model: ArxmlModel, composition_path: str, parent=None):
        super().__init__(parent)
        self._model = model
        self._comp = composition_path
        self.setWindowTitle("新增 Delegation 连接")
        self.resize(560, 280)

        swc = model.swc_types.get(composition_path)
        title = model.resolve_name(composition_path) if composition_path else ""
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Composition: {title}"))
        layout.addWidget(
            QLabel("将 Composition 外端口 委托到 内部 Prototype 同向端口。")
        )

        form = QFormLayout()
        self.cmb_outer = QComboBox()
        self.cmb_inner_proto = QComboBox()
        self.cmb_inner_port = QComboBox()
        self.edt_name = QLineEdit()
        self._name_manual = False
        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color:#666;")
        self.lbl_hint.setWordWrap(True)

        form.addRow("Outer Port:", self.cmb_outer)
        form.addRow("Inner Prototype:", self.cmb_inner_proto)
        form.addRow("Inner Port:", self.cmb_inner_port)
        form.addRow("Connector name:", self.edt_name)
        layout.addLayout(form)
        layout.addWidget(self.lbl_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._outers = list(swc.ports) if swc else []
        for p in self._outers:
            self.cmb_outer.addItem(f"{p.direction}-{p.name}", p.path)

        self._protos = list(swc.prototypes) if swc else []
        for proto in self._protos:
            self.cmb_inner_proto.addItem(proto.name, proto.path)

        self.cmb_outer.currentIndexChanged.connect(self._refresh_inner_ports)
        self.cmb_inner_proto.currentIndexChanged.connect(self._refresh_inner_ports)
        self.cmb_inner_port.currentIndexChanged.connect(self._auto_name)
        self.edt_name.textEdited.connect(lambda: setattr(self, "_name_manual", True))

        self._refresh_inner_ports()

    def _refresh_inner_ports(self):
        self.cmb_inner_port.clear()
        outer_path = self.cmb_outer.currentData()
        proto_path = self.cmb_inner_proto.currentData()
        outer = self._model.ports.get(outer_path) if outer_path else None
        proto = self._model.prototypes.get(proto_path) if proto_path else None
        if not outer or not proto:
            self._auto_name()
            return
        t = self._model.swc_types.get(proto.type_ref)
        if not t:
            self._auto_name()
            return
        for p in t.ports:
            if p.direction != outer.direction:
                continue
            label = f"{p.direction}-{p.name}"
            if outer.interface_ref and p.interface_ref == outer.interface_ref:
                label += " ✓"
            self.cmb_inner_port.addItem(label, p.path)
        self._update_hint()
        self._auto_name()

    def _update_hint(self):
        outer = self._model.ports.get(self.cmb_outer.currentData() or "")
        inner = self._model.ports.get(self.cmb_inner_port.currentData() or "")
        if not outer or not inner:
            self.lbl_hint.setText("")
            return
        ok_if = (
            outer.interface_ref
            and inner.interface_ref
            and outer.interface_ref == inner.interface_ref
        )
        if ok_if:
            self.lbl_hint.setText(
                f"接口匹配: {self._model.resolve_name(outer.interface_ref)}"
            )
            self.lbl_hint.setStyleSheet("color:#2e7d32;")
        else:
            self.lbl_hint.setText(
                "警告: 内外接口不同或缺失（仍可创建，建议核对）。"
            )
            self.lbl_hint.setStyleSheet("color:#c62828;")

    def _auto_name(self):
        self._update_hint()
        if self._name_manual:
            return
        outer = self._model.ports.get(self.cmb_outer.currentData() or "")
        proto = self._model.prototypes.get(self.cmb_inner_proto.currentData() or "")
        inner = self._model.ports.get(self.cmb_inner_port.currentData() or "")
        if not (outer and proto and inner):
            return
        self.edt_name.setText(
            f"{proto.name}_{inner.name}_to_{outer.name}_DG"
        )

    def _on_ok(self):
        if not self.cmb_outer.currentData() or not self.cmb_inner_port.currentData():
            QMessageBox.warning(self, "Delegation", "请选择 Outer 与 Inner 端口。")
            return
        if not (self.edt_name.text() or "").strip():
            QMessageBox.warning(self, "Delegation", "请填写连接器名称。")
            return
        self.accept()

    def result_values(self) -> Optional[Tuple[str, str, str, str]]:
        name = (self.edt_name.text() or "").strip()
        outer = self.cmb_outer.currentData() or ""
        proto = self.cmb_inner_proto.currentData() or ""
        inner = self.cmb_inner_port.currentData() or ""
        if not all([name, outer, proto, inner]):
            return None
        return name, outer, proto, inner
