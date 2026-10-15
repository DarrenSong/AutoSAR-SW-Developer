# -*- coding: utf-8 -*-
"""Dialog to export one or more SWCs as standalone ARXML (with deps)."""
from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..extract_swc import list_extractable_swcs, build_index
from ..model import ArxmlModel


class ExportSwcDialog(QDialog):
    def __init__(
        self,
        model: ArxmlModel,
        parent=None,
        *,
        preselect_path: str = "",
    ):
        super().__init__(parent)
        self._model = model
        self._index = None
        self._root = None
        self.setWindowTitle("导出 SWC ARXML（含依赖）")
        self.resize(640, 480)
        lay = QVBoxLayout(self)

        tip = QLabel(
            "按 SWC 导出独立 ARXML：包含该 SWC 本体及引用闭包中的 "
            "Interface / ADT / IDT / CompuMethod / DataConstr / BaseType / "
            "Unit / Constant / DataTypeMappingSet 等（逻辑同 extract_swc.py）。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#555;")
        lay.addWidget(tip)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("过滤 SWC 名称…")
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)

        self.lst = QListWidget()
        self.lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lay.addWidget(self.lst, 1)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("输出目录:"))
        self.out_dir = QLineEdit()
        default_dir = ""
        if model.filepath:
            base = os.path.splitext(os.path.basename(model.filepath))[0]
            default_dir = os.path.join(
                os.path.dirname(model.filepath) or ".", base + "_swc_split"
            )
        self.out_dir.setText(default_dir)
        path_row.addWidget(self.out_dir, 1)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse)
        path_row.addWidget(btn_browse)
        lay.addLayout(path_row)

        self.chk_validate = QCheckBox("导出后自动规范校验（较慢）")
        self.chk_validate.setChecked(False)
        lay.addWidget(self.chk_validate)
        self.chk_peer = QCheckBox("合并对照文件 REF 闭包（若已打开 peer）")
        self.chk_peer.setChecked(True)
        lay.addWidget(self.chk_peer)

        self.lbl = QLabel("")
        lay.addWidget(self.lbl)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("导出选中")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btn_all = QPushButton("全选 Application SWC")
        btn_all.clicked.connect(self._select_all)
        bar = QHBoxLayout()
        bar.addWidget(btn_all)
        bar.addStretch(1)
        lay.addLayout(bar)
        lay.addWidget(btns)

        self._all_rows: List[tuple] = []
        self._load()
        if preselect_path:
            self._preselect(preselect_path)

    def _load(self):
        import xml.etree.ElementTree as ET

        src = self._model.filepath
        if not src or not os.path.isfile(src):
            self.lbl.setText("无有效源 ARXML 路径")
            return
        try:
            tree = ET.parse(src)
            self._root = tree.getroot()
            self._index, _ = build_index(self._root)
            self._all_rows = list_extractable_swcs(self._index)
        except Exception as e:
            self.lbl.setText(f"索引失败: {e}")
            return
        self.lbl.setText(f"可导出 Atomic SWC: {len(self._all_rows)} 个")
        self._apply_filter()

    def _apply_filter(self):
        q = (self.filter.text() or "").strip().lower()
        self.lst.clear()
        for path, name, _elem in self._all_rows:
            if q and q not in name.lower() and q not in path.lower():
                continue
            item = QListWidgetItem(f"{name}    ({path})")
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setData(Qt.ItemDataRole.UserRole + 1, name)
            self.lst.addItem(item)

    def _preselect(self, path: str):
        for i in range(self.lst.count()):
            item = self.lst.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setSelected(True)
                self.lst.scrollToItem(item)
                break

    def _select_all(self):
        self.lst.selectAll()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def selected_swc_paths(self) -> List[str]:
        return [
            i.data(Qt.ItemDataRole.UserRole)
            for i in self.lst.selectedItems()
            if i.data(Qt.ItemDataRole.UserRole)
        ]

    def output_directory(self) -> str:
        return (self.out_dir.text() or "").strip()

    def validate_after_export(self) -> bool:
        return self.chk_validate.isChecked()

    def use_peer_closure(self) -> bool:
        return self.chk_peer.isChecked()
