# -*- coding: utf-8 -*-
"""Peer / cross-file counterpart list + chain report export."""
from __future__ import annotations

import csv
import os
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..model import ArxmlModel, PortPeer, SrChain


class PeerListDialog(QDialog):
    """List port peers (incl. cross-file) and jump / export."""

    jump_to = Signal(str, str)  # port_path, source (primary|peer_file)
    open_star_view = Signal(str)  # focus port_path → peer constellation graph

    def __init__(
        self,
        model: ArxmlModel,
        port_path: str,
        peers: List[PortPeer],
        *,
        chain: Optional[SrChain] = None,
        peer_model: Optional[ArxmlModel] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._model = model
        self._peer_model = peer_model
        self._port_path = port_path
        self._peers = peers
        self._chain = chain
        port = model.ports.get(port_path)
        title = model.resolve_name(port_path) if port else port_path
        self.setWindowTitle(f"对端列表 — {title}")
        self.resize(900, 420)

        lay = QVBoxLayout(self)
        n_pr = sum(
            1
            for p in peers
            if p.relation in ("assembly", "direction_pair", "cross_file")
        )
        lay.addWidget(
            QLabel(
                f"当前: {port.direction if port else '?'}-{title}  "
                f"@ {model.resolve_name(port.owner_path) if port else ''}\n"
                f"对端 {len(peers)} 个（其中 P↔R={n_pr}）"
                + (
                    f" · 对照文件: {os.path.basename(peer_model.filepath)}"
                    if peer_model and peer_model.filepath
                    else ""
                )
            )
        )

        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["来源", "关系", "对端", "路径"])
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.cellDoubleClicked.connect(self._on_dbl)
        lay.addWidget(self.tbl, 1)

        for i, p in enumerate(peers):
            self.tbl.insertRow(i)
            src = "对照文件" if p.source == "peer_file" else "本文件"
            vals = [src, p.relation, p.label, p.port_path]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, p.port_path)
                it.setData(Qt.ItemDataRole.UserRole + 1, p.source)
                self.tbl.setItem(i, c, it)
        self.tbl.resizeColumnsToContents()

        bar = QHBoxLayout()
        btn_jump = QPushButton("跳转到选中对端")
        btn_jump.clicked.connect(self._jump_selected)
        btn_star = QPushButton("打开对端图（1:N）")
        btn_star.setToolTip("同屏显示本侧 Port/SWC 与全部 P↔R 对端")
        btn_star.clicked.connect(self._open_star)
        btn_export = QPushButton("导出链路报告…")
        btn_export.setToolTip("导出当前 Port 的全链路 + 对端列表 (CSV / HTML)")
        btn_export.clicked.connect(self._export)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        bar.addWidget(btn_jump)
        bar.addWidget(btn_star)
        bar.addWidget(btn_export)
        bar.addStretch(1)
        bar.addWidget(btn_close)
        lay.addLayout(bar)

    def _open_star(self):
        self.open_star_view.emit(self._port_path)
        self.accept()

    def _jump_selected(self):
        rows = self.tbl.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "对端", "请先选中一行。")
            return
        it = self.tbl.item(rows[0].row(), 0)
        if not it:
            return
        self.jump_to.emit(
            it.data(Qt.ItemDataRole.UserRole) or "",
            it.data(Qt.ItemDataRole.UserRole + 1) or "primary",
        )
        self.accept()

    def _on_dbl(self, row: int, _col: int):
        it = self.tbl.item(row, 0)
        if not it:
            return
        self.jump_to.emit(
            it.data(Qt.ItemDataRole.UserRole) or "",
            it.data(Qt.ItemDataRole.UserRole + 1) or "primary",
        )
        self.accept()

    def _export(self):
        path, filt = QFileDialog.getSaveFileName(
            self,
            "导出链路报告",
            "sr_chain_report.csv",
            "CSV (*.csv);;HTML (*.html)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".html") or "HTML" in filt:
                if not path.lower().endswith(".html"):
                    path += ".html"
                _write_chain_html(
                    path,
                    self._model,
                    self._port_path,
                    self._chain,
                    self._peers,
                    self._peer_model,
                )
            else:
                if not path.lower().endswith(".csv"):
                    path += ".csv"
                _write_chain_csv(
                    path,
                    self._model,
                    self._port_path,
                    self._chain,
                    self._peers,
                    self._peer_model,
                )
            QMessageBox.information(self, "导出", f"已写入:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出", str(e))


def _write_chain_csv(
    path: str,
    model: ArxmlModel,
    port_path: str,
    chain: Optional[SrChain],
    peers: List[PortPeer],
    peer_model: Optional[ArxmlModel],
):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Section", "Field", "Value"])
        w.writerow(["Port", "path", port_path])
        po = model.ports.get(port_path)
        if po:
            w.writerow(["Port", "name", po.name])
            w.writerow(["Port", "direction", po.direction])
            w.writerow(["Port", "owner", po.owner_path])
        w.writerow(["File", "primary", model.filepath])
        if peer_model:
            w.writerow(["File", "peer", peer_model.filepath])
        if chain:
            for i, h in enumerate(chain.hops):
                w.writerow(
                    [
                        "Hop",
                        str(i + 1),
                        f"{h.kind}|{h.connector_name}|"
                        f"{h.from_label(model)}→{h.to_label(model)}|"
                        f"{h.composition_path}",
                    ]
                )
        for p in peers:
            w.writerow(["Peer", p.relation, f"{p.source}|{p.port_path}|{p.label}"])


def _write_chain_html(
    path: str,
    model: ArxmlModel,
    port_path: str,
    chain: Optional[SrChain],
    peers: List[PortPeer],
    peer_model: Optional[ArxmlModel],
):
    po = model.ports.get(port_path)
    title = model.resolve_name(port_path)
    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>SR Chain — {title}</title>",
        "<style>body{font-family:Segoe UI,sans-serif;margin:24px}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #ccc;padding:6px 8px;text-align:left}"
        "th{background:#f5f5f5}</style></head><body>",
        f"<h1>SR / Delegation 链路报告</h1>",
        f"<p><b>Port:</b> {po.direction if po else '?'}-{title}<br>",
        f"<b>Path:</b> {port_path}<br>",
        f"<b>File:</b> {model.filepath}</p>",
    ]
    if peer_model:
        lines.append(f"<p><b>对照文件:</b> {peer_model.filepath}</p>")
    lines.append("<h2>Hops</h2><table><tr><th>#</th><th>Kind</th>"
                 "<th>Connector</th><th>From</th><th>To</th><th>Composition</th></tr>")
    if chain:
        for i, h in enumerate(chain.hops):
            lines.append(
                f"<tr><td>{i+1}</td><td>{h.kind}</td><td>{h.connector_name}</td>"
                f"<td>{h.from_label(model)}</td><td>{h.to_label(model)}</td>"
                f"<td>{model.resolve_name(h.composition_path)}</td></tr>"
            )
    lines.append("</table><h2>Peers</h2><table><tr><th>Source</th>"
                 "<th>Relation</th><th>Label</th><th>Path</th></tr>")
    for p in peers:
        src = "对照" if p.source == "peer_file" else "本文件"
        lines.append(
            f"<tr><td>{src}</td><td>{p.relation}</td>"
            f"<td>{p.label}</td><td>{p.port_path}</td></tr>"
        )
    lines.append("</table></body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
