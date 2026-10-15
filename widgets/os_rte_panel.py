# -*- coding: utf-8 -*-
"""OS-Task / Runnable→Task overlay editor (sidecar JSON)."""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model import ArxmlModel
from ..os_rte import OsRteOverlay, OsTask, RunnableToTaskMapping


class AddOsTaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增 OS Task")
        self.resize(400, 180)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edt_name = QLineEdit()
        self.sp_prio = QSpinBox()
        self.sp_prio.setRange(0, 255)
        self.sp_prio.setValue(10)
        self.cmb_sched = QComboBox()
        self.cmb_sched.addItems(["FULL", "NON"])
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["EXTENDED", "BASIC"])
        form.addRow("Name:", self.edt_name)
        form.addRow("Priority:", self.sp_prio)
        form.addRow("Schedule:", self.cmb_sched)
        form.addRow("Type:", self.cmb_type)
        lay.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _on_ok(self):
        if not (self.edt_name.text() or "").strip():
            QMessageBox.warning(self, "OS Task", "请填写名称。")
            return
        self.accept()

    def result_task(self) -> Optional[OsTask]:
        name = (self.edt_name.text() or "").strip()
        if not name:
            return None
        return OsTask(
            name=name,
            priority=self.sp_prio.value(),
            schedule=self.cmb_sched.currentText(),
            type=self.cmb_type.currentText(),
        )


class AddOsMappingDialog(QDialog):
    def __init__(
        self,
        model: ArxmlModel,
        overlay: OsRteOverlay,
        task_name: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._model = model
        self._overlay = overlay
        self.setWindowTitle("Map Runnable → Task")
        self.resize(520, 240)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.cmb_task = QComboBox()
        for t in overlay.tasks:
            self.cmb_task.addItem(t.name, t.name)
            if task_name and t.name == task_name:
                self.cmb_task.setCurrentIndex(self.cmb_task.count() - 1)
        self.cmb_proto = QComboBox()
        for path in sorted(model.prototypes.keys()):
            p = model.prototypes[path]
            label = f"{p.name}  ({model.resolve_name(p.type_ref)})"
            self.cmb_proto.addItem(label, path)
        self.cmb_run = QComboBox()
        self.sp_pos = QSpinBox()
        self.sp_pos.setRange(0, 999)
        form.addRow("Task:", self.cmb_task)
        form.addRow("SWC Prototype:", self.cmb_proto)
        form.addRow("Runnable:", self.cmb_run)
        form.addRow("Position:", self.sp_pos)
        lay.addLayout(form)
        tip = QLabel("Prototype 的 type → Internal Behavior → Runnables")
        tip.setStyleSheet("color:#666;")
        lay.addWidget(tip)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.cmb_proto.currentIndexChanged.connect(self._fill_runnables)
        self._fill_runnables()

    def _fill_runnables(self):
        self.cmb_run.clear()
        proto_path = self.cmb_proto.currentData() or ""
        proto = self._model.prototypes.get(proto_path)
        if not proto:
            return
        for beh in self._model.behaviors_of_swc(proto.type_ref):
            for r in beh.runnables:
                label = r.name or r.path
                if r.symbol:
                    label += f"  [{r.symbol}]"
                self.cmb_run.addItem(label, r.path)

    def _on_ok(self):
        if not self.cmb_task.currentData():
            QMessageBox.warning(self, "Mapping", "请选择 Task。")
            return
        if not self.cmb_proto.currentData():
            QMessageBox.warning(self, "Mapping", "请选择 Prototype。")
            return
        if not self.cmb_run.currentData():
            QMessageBox.warning(self, "Mapping", "请选择 Runnable。")
            return
        self.accept()

    def result_mapping(self) -> Optional[RunnableToTaskMapping]:
        task = self.cmb_task.currentData() or ""
        proto = self.cmb_proto.currentData() or ""
        run = self.cmb_run.currentData() or ""
        if not task or not proto or not run:
            return None
        return RunnableToTaskMapping(
            task=task,
            swc_prototype=proto,
            runnable=run,
            position=self.sp_pos.value(),
        )


class OsRtePanel(QWidget):
    """Left: Tasks; Right: Mappings for selected task."""

    changed = Signal()
    jump_to = Signal(str, str)  # path, kind
    save_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: Optional[ArxmlModel] = None
        self._overlay: Optional[OsRteOverlay] = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.hint = QLabel("侧车 OS/RTE Mapping（非 ECUC）")
        self.hint.setStyleSheet("color:#666; font-size:11px;")
        lay.addWidget(self.hint)

        bar = QHBoxLayout()
        self.btn_add_task = QPushButton("Add Task")
        self.btn_del_task = QPushButton("Delete Task")
        self.btn_add_map = QPushButton("Map Runnable")
        self.btn_del_map = QPushButton("Delete Mapping")
        self.btn_save = QPushButton("Save Mapping…")
        for b in (
            self.btn_add_task,
            self.btn_del_task,
            self.btn_add_map,
            self.btn_del_map,
            self.btn_save,
        ):
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)

        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("OS Tasks"))
        self.task_table = QTableWidget(0, 4)
        self.task_table.setHorizontalHeaderLabels(
            ["Name", "Priority", "Schedule", "Type"]
        )
        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.task_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.task_table.itemSelectionChanged.connect(self._on_task_sel)
        ll.addWidget(self.task_table, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Runnable → Task Mappings"))
        self.map_table = QTableWidget(0, 4)
        self.map_table.setHorizontalHeaderLabels(
            ["Position", "Prototype", "Runnable", "Task"]
        )
        self.map_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.map_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.map_table.cellDoubleClicked.connect(self._on_map_dbl)
        rl.addWidget(self.map_table, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)

        self.btn_add_task.clicked.connect(self._add_task)
        self.btn_del_task.clicked.connect(self._del_task)
        self.btn_add_map.clicked.connect(self._add_map)
        self.btn_del_map.clicked.connect(self._del_map)
        self.btn_save.clicked.connect(self.save_requested.emit)

    def set_context(
        self, model: Optional[ArxmlModel], overlay: Optional[OsRteOverlay]
    ):
        self._model = model
        self._overlay = overlay
        self.refresh()

    def refresh(self):
        ov = self._overlay
        dirty = " *" if ov and ov.dirty else ""
        path = (ov.source_path if ov else "") or "(未保存)"
        n_t = len(ov.tasks) if ov else 0
        n_m = len(ov.mappings) if ov else 0
        self.hint.setText(
            f"侧车 OS/RTE Mapping{dirty}  Tasks={n_t} Mappings={n_m}\n{path}"
        )
        self.task_table.setRowCount(0)
        self.map_table.setRowCount(0)
        if not ov:
            return
        self.task_table.setRowCount(len(ov.tasks))
        for i, t in enumerate(ov.tasks):
            self.task_table.setItem(i, 0, QTableWidgetItem(t.name))
            self.task_table.setItem(i, 1, QTableWidgetItem(str(t.priority)))
            self.task_table.setItem(i, 2, QTableWidgetItem(t.schedule))
            self.task_table.setItem(i, 3, QTableWidgetItem(t.type))
        if ov.tasks:
            self.task_table.selectRow(0)
        else:
            self._fill_maps("")

    def _selected_task(self) -> str:
        rows = self.task_table.selectionModel().selectedRows()
        if not rows:
            return ""
        it = self.task_table.item(rows[0].row(), 0)
        return it.text() if it else ""

    def _on_task_sel(self):
        self._fill_maps(self._selected_task())

    def _fill_maps(self, task_name: str):
        self.map_table.setRowCount(0)
        if not self._overlay or not self._model:
            return
        maps = (
            self._overlay.mappings_by_task(task_name)
            if task_name
            else list(self._overlay.mappings)
        )
        maps = sorted(maps, key=lambda m: (m.position, m.runnable))
        self.map_table.setRowCount(len(maps))
        for i, m in enumerate(maps):
            proto_n = self._model.resolve_name(m.swc_prototype)
            run_n = self._model.resolve_name(m.runnable)
            items = [
                QTableWidgetItem(str(m.position)),
                QTableWidgetItem(proto_n),
                QTableWidgetItem(run_n),
                QTableWidgetItem(m.task),
            ]
            for c, it in enumerate(items):
                if c == 1:
                    it.setData(Qt.ItemDataRole.UserRole, m.swc_prototype)
                if c == 2:
                    it.setData(Qt.ItemDataRole.UserRole, m.runnable)
                self.map_table.setItem(i, c, it)

    def _add_task(self):
        if not self._overlay:
            return
        dlg = AddOsTaskDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        task = dlg.result_task()
        if not task:
            return
        err = self._overlay.add_task(task)
        if err:
            QMessageBox.warning(self, "OS Task", err)
            return
        self.refresh()
        self.changed.emit()

    def _del_task(self):
        if not self._overlay:
            return
        name = self._selected_task()
        if not name:
            return
        n_maps = len(self._overlay.mappings_by_task(name))
        ans = QMessageBox.question(
            self,
            "Delete Task",
            f"删除 Task「{name}」及关联的 {n_maps} 条 Mapping？",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._overlay.remove_task(name)
        self.refresh()
        self.changed.emit()

    def _add_map(self):
        if not self._overlay or not self._model:
            return
        if not self._overlay.tasks:
            QMessageBox.information(self, "Mapping", "请先新增 OS Task。")
            return
        dlg = AddOsMappingDialog(
            self._model, self._overlay, self._selected_task(), self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        m = dlg.result_mapping()
        if not m:
            return
        err = self._overlay.add_mapping(m)
        if err:
            QMessageBox.warning(self, "Mapping", err)
            return
        self.refresh()
        # reselect task
        for i in range(self.task_table.rowCount()):
            it = self.task_table.item(i, 0)
            if it and it.text() == m.task:
                self.task_table.selectRow(i)
                break
        self.changed.emit()

    def _del_map(self):
        if not self._overlay:
            return
        rows = self.map_table.selectionModel().selectedRows()
        if not rows:
            return
        r = rows[0].row()
        proto_it = self.map_table.item(r, 1)
        run_it = self.map_table.item(r, 2)
        task_it = self.map_table.item(r, 3)
        if not proto_it or not run_it or not task_it:
            return
        proto = proto_it.data(Qt.ItemDataRole.UserRole) or ""
        run = run_it.data(Qt.ItemDataRole.UserRole) or ""
        task = task_it.text()
        err = self._overlay.remove_mapping(task, proto, run)
        if err:
            QMessageBox.warning(self, "Mapping", err)
            return
        self._fill_maps(self._selected_task())
        self.changed.emit()

    def _on_map_dbl(self, row: int, _col: int):
        run_it = self.map_table.item(row, 2)
        if not run_it:
            return
        path = run_it.data(Qt.ItemDataRole.UserRole) or ""
        if path:
            self.jump_to.emit(path, "runnable")
