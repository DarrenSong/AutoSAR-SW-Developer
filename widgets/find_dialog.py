# -*- coding: utf-8 -*-
"""Find results list (jump to path/kind) — fuzzy match aligned with tree filter."""
from __future__ import annotations

import re
from typing import List, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..model import ArxmlModel

Hit = Tuple[str, str, str]  # kind, path, label


def _norm(s: str) -> str:
    return re.sub(r"[_\-/\s]+", "", (s or "").lower())


def _camel_initials(s: str) -> str:
    parts = re.findall(
        r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+",
        (s or "").replace("_", " ").replace("-", " ").replace("/", " "),
    )
    if not parts:
        return _norm(s)[:8]
    return "".join(p[0] for p in parts if p).lower()


def _is_subsequence(query: str, text: str) -> bool:
    if not query:
        return True
    it = iter(text)
    return all(ch in it for ch in query)


def fuzzy_match(query: str, *parts: str) -> bool:
    """Same rules as ModelTree._match (substring / tokens / ignore _ / initials / subseq)."""
    q = (query or "").strip().lower()
    if not q:
        return True
    blob = " ".join(p for p in parts if p).lower()
    if not blob:
        return False
    if q in blob:
        return True
    tokens = [t for t in re.split(r"[\s,;]+", q) if t]
    if len(tokens) > 1 and all(t in blob for t in tokens):
        return True
    nq, nblob = _norm(q), _norm(blob)
    if nq and nq in nblob:
        return True
    if len(tokens) > 1 and all(_norm(t) in nblob for t in tokens):
        return True
    initials = "".join(_camel_initials(p) for p in parts if p)
    if nq and (nq == initials or nq in initials):
        return True
    if 2 <= len(nq) <= 12 and _is_subsequence(nq, nblob):
        return True
    return False


def search_model(model: ArxmlModel, query: str, limit: int = 500) -> List[Hit]:
    q = (query or "").strip()
    if not model or not q:
        return []
    hits: List[Hit] = []

    def add(kind: str, path: str, label: str):
        if len(hits) >= limit:
            return
        if fuzzy_match(q, label, path):
            hits.append((kind, path, label))

    for path, swc in model.swc_types.items():
        kind = "composition" if swc.kind == "COMPOSITION" else "swc"
        add(kind, path, swc.name)
    for path, port in model.ports.items():
        add("port", path, f"{port.direction}-{port.name}")
    for path, proto in model.prototypes.items():
        add("prototype", path, proto.name)
    for path, iface in model.interfaces.items():
        add("sr_interface", path, iface.name)
        for de in iface.data_elements:
            add("sr_data_element", de.path or path, f"{iface.name}.{de.name}")
    for path, cs in model.cs_interfaces.items():
        add("cs_interface", path, cs.name)
    for path, adt in model.adts.items():
        add("adt", path, adt.name)
    for path, idt in model.idts.items():
        add("idt", path, idt.name)
    for path, bt in model.base_types.items():
        add("base_type", path, bt.name)
    for path, r in model.runnables.items():
        add("runnable", path, r.name)
    for path, ev in model.rte_events.items():
        add("rte_event", path, ev.name)
    for dm in model.data_mappings:
        add("data_mapping", dm.path, dm.name)

    # Ports with Assembly 1:N (handy for 对端图测试)
    if fuzzy_match(q, "1n", "fanout", "一对多"):
        from collections import defaultdict

        p_to_rs = defaultdict(set)
        for a in model.assemblies:
            if a.provider_port_ref and a.requester_port_ref:
                p_to_rs[a.provider_port_ref].add(a.requester_port_ref)
        for pp, rs in p_to_rs.items():
            if len(rs) >= 2 and len(hits) < limit:
                port = model.ports.get(pp)
                label = f"1:N P-{port.name if port else pp} (N={len(rs)})"
                hits.append(("port", pp, label))
    return hits


class FindDialog(QDialog):
    jump_to = Signal(str, str)  # path, kind

    def __init__(self, model: ArxmlModel, parent=None, initial: str = ""):
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("查找")
        self.resize(720, 480)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.edt = QLineEdit(initial)
        self.edt.setPlaceholderText("模糊: 子串 / 分词 / 缩写 / 输入 1n 列一对多 Port…")
        self.edt.setToolTip(
            "与左树过滤相同规则；关键字「1n」列出 Assembly 一对多的 P-Port"
        )
        self.edt.returnPressed.connect(self._search)
        btn = QPushButton("搜索")
        btn.clicked.connect(self._search)
        bar.addWidget(QLabel("关键字:"))
        bar.addWidget(self.edt, 1)
        bar.addWidget(btn)
        lay.addLayout(bar)
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["Kind", "Name", "Path"])
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.cellDoubleClicked.connect(self._on_dbl)
        lay.addWidget(self.tbl, 1)
        self.lbl = QLabel("")
        lay.addWidget(self.lbl)
        if initial:
            self._search()

    def _search(self):
        hits = search_model(self._model, self.edt.text())
        self.tbl.setRowCount(len(hits))
        for i, (kind, path, label) in enumerate(hits):
            self.tbl.setItem(i, 0, QTableWidgetItem(kind))
            it = QTableWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, path)
            it.setData(Qt.ItemDataRole.UserRole + 1, kind)
            self.tbl.setItem(i, 1, it)
            self.tbl.setItem(i, 2, QTableWidgetItem(path))
        self.tbl.resizeColumnsToContents()
        self.lbl.setText(f"{len(hits)} 条结果")

    def _on_dbl(self, row: int, _col: int):
        it = self.tbl.item(row, 1)
        if not it:
            return
        path = it.data(Qt.ItemDataRole.UserRole) or ""
        kind = it.data(Qt.ItemDataRole.UserRole + 1) or ""
        if path:
            self.jump_to.emit(path, kind)
