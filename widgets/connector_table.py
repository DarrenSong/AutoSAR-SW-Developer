# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QCheckBox,
    QPushButton,
    QComboBox,
)

from ..model import ArxmlModel, AssemblyConnector, DelegationConnector


class ConnectorTables(QWidget):
    # conn_id, kind (assembly|delegation), focus_ref (port/proto path clicked, may be "")
    row_selected = Signal(str, str, str)
    add_assembly_requested = Signal()
    add_delegation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: Optional[ArxmlModel] = None
        self._comp_path = ""
        self._filter_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by name / port / proto…")
        self.filter_edit.textChanged.connect(self.refresh)
        self.chk_selection_only = QCheckBox("Filter by selection")
        self.chk_selection_only.setToolTip("只显示与左侧树/图选中项相关的连接")
        self.chk_selection_only.stateChanged.connect(self.refresh)
        self.cmb_iface = QComboBox()
        self.cmb_iface.addItem("SR+CS", "All")
        self.cmb_iface.addItem("SR only", "SR")
        self.cmb_iface.addItem("CS only", "CS")
        self.cmb_iface.setToolTip("按端口接口类型过滤 Assembly")
        self.cmb_iface.currentIndexChanged.connect(self.refresh)
        self.btn_add_asm = QPushButton("新增 Assembly…")
        self.btn_add_asm.setToolTip("在当前 Composition 中新建 Assembly 连接（Ctrl+N）")
        self.btn_add_asm.clicked.connect(self.add_assembly_requested.emit)
        self.btn_add_del = QPushButton("新增 Delegation…")
        self.btn_add_del.setToolTip("在当前 Composition 中新建 Delegation（Ctrl+D）")
        self.btn_add_del.clicked.connect(self.add_delegation_requested.emit)
        bar.addWidget(QLabel("Search:"))
        bar.addWidget(self.filter_edit, 1)
        bar.addWidget(self.chk_selection_only)
        bar.addWidget(self.cmb_iface)
        bar.addWidget(self.btn_add_asm)
        bar.addWidget(self.btn_add_del)
        layout.addLayout(bar)

        self.tabs = QTabWidget()
        self.tbl_asm = QTableWidget(0, 7)
        self.tbl_asm.setHorizontalHeaderLabels(
            ["Name", "Kind", "Provider Proto", "P-Port", "Requester Proto", "R-Port", "Interface"]
        )
        self.tbl_asm.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_asm.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tbl_asm.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_asm.itemSelectionChanged.connect(lambda: self._emit_sel(self.tbl_asm, "assembly"))
        self.tbl_asm.cellClicked.connect(lambda r, c: self._emit_cell(self.tbl_asm, "assembly", r, c))

        self.tbl_del = QTableWidget(0, 5)
        self.tbl_del.setHorizontalHeaderLabels(
            ["Name", "Outer Port", "Inner Proto", "Inner Port", "Dir"]
        )
        self.tbl_del.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_del.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tbl_del.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_del.itemSelectionChanged.connect(lambda: self._emit_sel(self.tbl_del, "delegation"))
        self.tbl_del.cellClicked.connect(lambda r, c: self._emit_cell(self.tbl_del, "delegation", r, c))

        self.tabs.addTab(self.tbl_asm, "Assembly")
        self.tabs.addTab(self.tbl_del, "Delegation")
        layout.addWidget(self.tabs)

        self._asm_rows: List[AssemblyConnector] = []
        self._del_rows: List[DelegationConnector] = []

    def set_model(self, model: Optional[ArxmlModel]):
        self._model = model
        self.refresh()

    def set_composition(self, path: str):
        self._comp_path = path or ""
        self.refresh()

    def set_selection_filter(self, path: str):
        self._filter_path = path or ""
        if self.chk_selection_only.isChecked():
            self.refresh()

    def refresh(self):
        self.tbl_asm.setRowCount(0)
        self.tbl_del.setRowCount(0)
        self._asm_rows = []
        self._del_rows = []
        if not self._model or not self._comp_path:
            self.tabs.setTabText(0, "Assembly")
            self.tabs.setTabText(1, "Delegation")
            return

        q = self.filter_edit.text().strip().lower()
        sel = self._filter_path if self.chk_selection_only.isChecked() else ""
        iface_f = self.cmb_iface.currentData() if hasattr(self, "cmb_iface") else "All"

        asms = self._model.assemblies_by_comp.get(self._comp_path, [])
        for a in asms:
            if sel and sel not in (
                a.provider_proto_ref,
                a.requester_proto_ref,
                a.provider_port_ref,
                a.requester_port_ref,
                a.path,
            ):
                continue
            akind = self._model.assembly_iface_kind(a)
            if iface_f == "SR" and akind not in ("SR",):
                continue
            if iface_f == "CS" and akind not in ("CS",):
                continue
            blob = " ".join(
                [
                    a.name,
                    akind,
                    a.provider_proto_ref,
                    a.provider_port_ref,
                    a.requester_proto_ref,
                    a.requester_port_ref,
                ]
            ).lower()
            if q and q not in blob:
                continue
            self._asm_rows.append(a)

        dels = self._model.delegations_by_comp.get(self._comp_path, [])
        for d in dels:
            if sel and sel not in (
                d.outer_port_ref,
                d.inner_proto_ref,
                d.inner_port_ref,
                d.path,
            ):
                continue
            blob = " ".join(
                [d.name, d.outer_port_ref, d.inner_proto_ref, d.inner_port_ref]
            ).lower()
            if q and q not in blob:
                continue
            self._del_rows.append(d)

        # Assembly: 0 name, 1 kind, 2 provider proto, 3 P-port, 4 requester proto, 5 R-port, 6 iface
        self.tbl_asm.setRowCount(len(self._asm_rows))
        for i, a in enumerate(self._asm_rows):
            iface = ""
            p = self._model.ports.get(a.provider_port_ref)
            akind = self._model.assembly_iface_kind(a)
            if p:
                if akind == "CS" and p.interface_ref in self._model.cs_interfaces:
                    iface = self._model.cs_interfaces[p.interface_ref].name
                elif p.interface_ref in self._model.interfaces:
                    iface = self._model.interfaces[p.interface_ref].name
            vals = [
                a.name,
                akind,
                self._model.resolve_name(a.provider_proto_ref),
                self._model.resolve_name(a.provider_port_ref),
                self._model.resolve_name(a.requester_proto_ref),
                self._model.resolve_name(a.requester_port_ref),
                iface,
            ]
            focus_refs = [
                "",
                "",
                a.provider_proto_ref,
                a.provider_port_ref,
                a.requester_proto_ref,
                a.requester_port_ref,
                "",
            ]
            conn_id = a.path or a.name
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, conn_id)
                item.setData(Qt.ItemDataRole.UserRole + 1, focus_refs[c])
                self.tbl_asm.setItem(i, c, item)

        # Delegation: 0 name, 1 outer, 2 inner proto, 3 inner port, 4 dir
        self.tbl_del.setRowCount(len(self._del_rows))
        for i, d in enumerate(self._del_rows):
            vals = [
                d.name,
                self._model.resolve_name(d.outer_port_ref),
                self._model.resolve_name(d.inner_proto_ref),
                self._model.resolve_name(d.inner_port_ref),
                d.inner_direction,
            ]
            focus_refs = [
                "",
                d.outer_port_ref,
                d.inner_proto_ref,
                d.inner_port_ref,
                "",
            ]
            conn_id = d.path or d.name
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, conn_id)
                item.setData(Qt.ItemDataRole.UserRole + 1, focus_refs[c])
                self.tbl_del.setItem(i, c, item)

        self.tabs.setTabText(0, f"Assembly ({len(self._asm_rows)})")
        self.tabs.setTabText(1, f"Delegation ({len(self._del_rows)})")
        self.tbl_asm.resizeColumnsToContents()
        self.tbl_del.resizeColumnsToContents()

    def _emit_sel(self, table: QTableWidget, kind: str):
        rows = table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        item = table.item(row, 0)
        if item:
            self.row_selected.emit(item.data(Qt.ItemDataRole.UserRole) or "", kind, "")

    def _emit_cell(self, table: QTableWidget, kind: str, row: int, col: int):
        item = table.item(row, col)
        if not item:
            return
        conn_id = item.data(Qt.ItemDataRole.UserRole) or ""
        focus = item.data(Qt.ItemDataRole.UserRole + 1) or ""
        self.row_selected.emit(conn_id, kind, focus)

    def selected_connector(self) -> Optional[tuple]:
        """Return (conn_id, kind, name, composition_path) or None."""
        tab = self.tabs.currentIndex()
        if tab == 0:
            table, kind, rows_src = self.tbl_asm, "assembly", self._asm_rows
        else:
            table, kind, rows_src = self.tbl_del, "delegation", self._del_rows
        rows = table.selectionModel().selectedRows() if table.selectionModel() else []
        if not rows:
            return None
        r = rows[0].row()
        if r < 0 or r >= len(rows_src):
            return None
        obj = rows_src[r]
        return (obj.path or obj.name, kind, obj.name, obj.composition_path)

    def export_csv(self, path: str):
        import csv

        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["type", "name", "a", "b", "c", "d", "e"])
            for a in self._asm_rows:
                w.writerow(
                    [
                        "assembly",
                        a.name,
                        a.provider_proto_ref,
                        a.provider_port_ref,
                        a.requester_proto_ref,
                        a.requester_port_ref,
                        "",
                    ]
                )
            for d in self._del_rows:
                w.writerow(
                    [
                        "delegation",
                        d.name,
                        d.outer_port_ref,
                        d.inner_proto_ref,
                        d.inner_port_ref,
                        d.inner_direction,
                        "",
                    ]
                )
