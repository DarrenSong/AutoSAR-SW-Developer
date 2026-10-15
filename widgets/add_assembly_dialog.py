 # -*- coding: utf-8 -*-
"""Dialog to create a new ASSEMBLY-SW-CONNECTOR."""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QComboBox,
    QLineEdit,
    QLabel,
    QDialogButtonBox,
    QMessageBox,
)

from ..model import ArxmlModel


class AddAssemblyDialog(QDialog):
    def __init__(
        self,
        model: ArxmlModel,
        composition_path: str,
        parent=None,
        *,
        prefer_kind: str = "All",  # All | SR | CS
    ):
        super().__init__(parent)
        self._model = model
        self._comp = composition_path
        self.setWindowTitle("新增 Assembly 连接")
        self.resize(560, 320)

        swc = model.swc_types.get(composition_path)
        title = model.resolve_name(composition_path) if composition_path else ""
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Composition: {title}"))

        form = QFormLayout()
        self.cmb_kind = QComboBox()
        self.cmb_kind.addItem("全部 (SR + CS)", "All")
        self.cmb_kind.addItem("仅 Sender-Receiver (SR)", "SR")
        self.cmb_kind.addItem("仅 Client-Server (CS)", "CS")
        idx = {"All": 0, "SR": 1, "CS": 2}.get(prefer_kind, 0)
        self.cmb_kind.setCurrentIndex(idx)

        self.cmb_prov_proto = QComboBox()
        self.cmb_prov_port = QComboBox()
        self.cmb_req_proto = QComboBox()
        self.cmb_req_port = QComboBox()
        self.edt_name = QLineEdit()
        self._name_manual = False
        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color:#666;")
        self.lbl_hint.setWordWrap(True)

        form.addRow("端口类型:", self.cmb_kind)
        form.addRow("Provider Prototype:", self.cmb_prov_proto)
        form.addRow("Provider P-Port:", self.cmb_prov_port)
        form.addRow("Requester Prototype:", self.cmb_req_proto)
        form.addRow("Requester R-Port:", self.cmb_req_port)
        form.addRow("Connector name:", self.edt_name)
        layout.addLayout(form)
        layout.addWidget(self.lbl_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._protos = list(swc.prototypes) if swc else []
        for proto in self._protos:
            self.cmb_prov_proto.addItem(proto.name, proto.path)
            self.cmb_req_proto.addItem(proto.name, proto.path)

        self.cmb_kind.currentIndexChanged.connect(self._on_kind)
        self.cmb_prov_proto.currentIndexChanged.connect(self._on_prov_proto)
        self.cmb_req_proto.currentIndexChanged.connect(self._on_req_proto)
        self.cmb_prov_port.currentIndexChanged.connect(self._suggest_name)
        self.cmb_req_port.currentIndexChanged.connect(self._suggest_name)
        self.edt_name.textEdited.connect(lambda _t: setattr(self, "_name_manual", True))

        if self._protos:
            self._on_prov_proto(0)
            self._on_req_proto(0)
            if self.cmb_req_proto.count() > 1:
                self.cmb_req_proto.setCurrentIndex(1)

    def _kind_filter(self) -> Optional[str]:
        k = self.cmb_kind.currentData()
        return None if k == "All" else k

    def _ports_for_proto(self, proto_path: str, direction: str) -> list:
        proto = self._model.prototypes.get(proto_path)
        if not proto:
            return []
        t = self._model.swc_types.get(proto.type_ref)
        if not t:
            return []
        kf = self._kind_filter()
        out = []
        for p in t.ports:
            if p.direction != direction:
                continue
            if kf and (p.iface_kind or "SR") != kf:
                continue
            out.append(p)
        return out

    def _fill_ports(self, combo: QComboBox, proto_path: str, direction: str):
        combo.blockSignals(True)
        combo.clear()
        for p in self._ports_for_proto(proto_path, direction):
            ik = getattr(p, "iface_kind", "SR") or "SR"
            combo.addItem(f"{p.name}  [{ik}]", p.path)
        combo.blockSignals(False)
        self._suggest_name()
        self._update_hint()

    def _on_kind(self, _idx: int):
        self._name_manual = False
        self._on_prov_proto(self.cmb_prov_proto.currentIndex())
        self._on_req_proto(self.cmb_req_proto.currentIndex())

    def _on_prov_proto(self, _idx: int):
        self._fill_ports(self.cmb_prov_port, self.cmb_prov_proto.currentData() or "", "P")

    def _on_req_proto(self, _idx: int):
        self._fill_ports(self.cmb_req_port, self.cmb_req_proto.currentData() or "", "R")

    def _suggest_name(self):
        pp = self.cmb_prov_proto.currentText()
        rp = self.cmb_req_proto.currentText()
        pport = self.cmb_prov_port.currentText().split("  [")[0] if self.cmb_prov_port.currentText() else ""
        rport = self.cmb_req_port.currentText().split("  [")[0] if self.cmb_req_port.currentText() else ""
        if pp and rp and pport and rport:
            raw = f"{pp}_{pport}_{rp}_{rport}"
            safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in raw)
            if len(safe) > 120:
                safe = safe[:120]
            if not self._name_manual:
                self.edt_name.setText(safe)
        self._update_hint()

    def _update_hint(self):
        p_path = self.cmb_prov_port.currentData() or ""
        r_path = self.cmb_req_port.currentData() or ""
        p = self._model.ports.get(p_path)
        r = self._model.ports.get(r_path)
        if not p or not r:
            self.lbl_hint.setText("选择 Provider P-Port 与 Requester R-Port。")
            self.lbl_hint.setStyleSheet("color:#666;")
            return
        pk, rk = p.iface_kind or "SR", r.iface_kind or "SR"
        if pk != rk:
            self.lbl_hint.setText(f"警告: 端口类型不一致 ({pk} vs {rk})")
            self.lbl_hint.setStyleSheet("color:#e65100;")
            return
        if p.interface_ref and r.interface_ref and p.interface_ref == r.interface_ref:
            self.lbl_hint.setText(
                f"{pk} 接口匹配: {self._model.resolve_name(p.interface_ref)}"
            )
            self.lbl_hint.setStyleSheet("color:#2e7d32;")
        elif p.interface_ref and r.interface_ref:
            self.lbl_hint.setText(
                f"警告: 接口不一致\nP: {self._model.resolve_name(p.interface_ref)}\n"
                f"R: {self._model.resolve_name(r.interface_ref)}"
            )
            self.lbl_hint.setStyleSheet("color:#e65100;")
        else:
            self.lbl_hint.setText(f"类型: {pk}")
            self.lbl_hint.setStyleSheet("color:#666;")

    def _on_ok(self):
        if not self.cmb_prov_port.currentData() or not self.cmb_req_port.currentData():
            QMessageBox.warning(self, "新增 Assembly", "请选择两端端口。")
            return
        if not self.edt_name.text().strip():
            QMessageBox.warning(self, "新增 Assembly", "请填写连接器名称。")
            return
        self.accept()

    def result_values(self) -> Optional[Tuple[str, str, str, str, str]]:
        """name, prov_proto, prov_port, req_proto, req_port"""
        return (
            self.edt_name.text().strip(),
            self.cmb_prov_proto.currentData() or "",
            self.cmb_prov_port.currentData() or "",
            self.cmb_req_proto.currentData() or "",
            self.cmb_req_port.currentData() or "",
        )
