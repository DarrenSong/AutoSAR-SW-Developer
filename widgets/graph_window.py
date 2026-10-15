# -*- coding: utf-8 -*-
"""Detached graph window — sync with main or navigate independently."""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..graph_builder import (
    CompositionGraph,
    build_composition_graph,
    build_sr_chain_graph,
    build_swc_type_graph,
)
from ..model import ArxmlModel, SrChain
from .breadcrumb import BreadcrumbBar
from .composition_scene import CompositionView

if TYPE_CHECKING:
    pass


class GraphWindow(QMainWindow):
    """
    Pop-out graph viewer.

    - sync_with_main=True: mirrors MainWindow graph; navigation forwarded via signals.
    - sync_with_main=False: owns composition path + nav stack (independent session).
    """

    # Forwarded when syncing with main (or always for node/edge so main can update props)
    node_clicked = Signal(str, str)
    edge_clicked = Signal(str, str)
    drill_into = Signal(str)
    nav_back = Signal()
    crumb_activated = Signal(int)
    open_child_window = Signal(str)  # composition type path
    closed = Signal(object)  # self

    def __init__(
        self,
        model: Optional[ArxmlModel] = None,
        *,
        title: str = "Graph",
        sync_with_main: bool = True,
        composition_path: str = "",
        nav_stack: Optional[List[str]] = None,
        view_mode: str = "composition",
        swc_path: str = "",
        show_sr: bool = True,
        show_cs: bool = True,
        limit_ports: bool = False,
        show_delegation: bool = True,
        nest_preview: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.resize(1100, 750)

        self._model = model
        self._sync = sync_with_main
        self._current_comp = composition_path
        self._current_swc = swc_path
        self._view_mode = view_mode  # composition | swc | chain
        self._nav_stack: list[str] = list(nav_stack or [])
        self._chain: Optional[SrChain] = None
        self._pending_focus: list[str] = []

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        bar = QHBoxLayout()
        self.btn_back = QToolButton()
        self.btn_back.setText("← 返回上层")
        self.btn_back.clicked.connect(self._on_back)
        bar.addWidget(self.btn_back)

        self.crumb = BreadcrumbBar()
        self.crumb.activated.connect(self._on_crumb)
        bar.addWidget(self.crumb, 1)

        self.chk_sr = QCheckBox("SR")
        self.chk_sr.setChecked(show_sr)
        self.chk_sr.stateChanged.connect(self._options_changed)
        bar.addWidget(self.chk_sr)
        self.chk_cs = QCheckBox("CS")
        self.chk_cs.setChecked(show_cs)
        self.chk_cs.stateChanged.connect(self._options_changed)
        bar.addWidget(self.chk_cs)
        self.chk_limit = QCheckBox("Limit")
        self.chk_limit.setChecked(limit_ports)
        self.chk_limit.stateChanged.connect(self._options_changed)
        bar.addWidget(self.chk_limit)
        self.chk_deleg = QCheckBox("Delegation")
        self.chk_deleg.setChecked(show_delegation)
        self.chk_deleg.stateChanged.connect(self._options_changed)
        bar.addWidget(self.chk_deleg)
        self.chk_nest = QCheckBox("嵌套预览")
        self.chk_nest.setChecked(nest_preview)
        self.chk_nest.setToolTip("勾选后在子 Composition 框内预览下一层 Prototype（默认关=仅当前层）")
        self.chk_nest.stateChanged.connect(self._options_changed)
        bar.addWidget(self.chk_nest)
        if sync_with_main:
            # Options controlled by main window toolbar
            for chk in (
                self.chk_sr,
                self.chk_cs,
                self.chk_limit,
                self.chk_deleg,
                self.chk_nest,
            ):
                chk.setEnabled(False)
                chk.setToolTip("同步主窗：请在主窗口工具栏切换显示选项")

        self.btn_open_child = QToolButton()
        self.btn_open_child.setText("新窗口打开选中…")
        self.btn_open_child.setToolTip(
            "对选中的子 Composition：在独立窗口打开（也可右键 / Ctrl+双击）"
        )
        self.btn_open_child.clicked.connect(self._open_selected_child)
        bar.addWidget(self.btn_open_child)

        mode = QLabel("同步主窗" if sync_with_main else "独立会话")
        mode.setStyleSheet("color:#666; font-size:11px;")
        bar.addWidget(mode)
        root.addLayout(bar)

        tip = QLabel(
            "双击子 Composition 进入 · Ctrl+双击 / 右键 → 新窗口打开 · 点击面包屑跳级"
        )
        tip.setStyleSheet("color:#666; font-size:11px;")
        root.addWidget(tip)

        self.view = CompositionView()
        self.view.node_clicked.connect(self._on_node)
        self.view.edge_clicked.connect(self._on_edge)
        self.view.drill_into.connect(self._on_drill)
        self.view.open_in_new_window.connect(self._emit_open_child)
        root.addWidget(self.view, 1)

        self._selected_drill: str = ""

        act_back = QAction("Back", self)
        act_back.setShortcut(QKeySequence("Alt+Left"))
        act_back.triggered.connect(self._on_back)
        self.addAction(act_back)

        if not sync_with_main and model and composition_path:
            self.reload()
        elif not sync_with_main and model and swc_path:
            self.reload()

    def set_model(self, model: Optional[ArxmlModel]):
        self._model = model
        if not model:
            self.view.set_graph(CompositionGraph(composition_path=""))
            return
        if not self._sync:
            self.reload()

    def mirror_graph(
        self,
        graph: CompositionGraph,
        *,
        crumb_parts: Optional[List[str]] = None,
        can_back: bool = False,
        focus_ids: Optional[List[str]] = None,
    ):
        """Used by MainWindow when this window is in sync mode."""
        if not self._sync:
            return
        self.view.set_graph(graph)
        if crumb_parts is not None:
            self.crumb.set_parts(crumb_parts)
        self.btn_back.setEnabled(can_back)
        if focus_ids:
            resolved = []
            for ref in focus_ids:
                nid = self.view.resolve_node_id(ref)
                if nid:
                    resolved.append(nid)
            if resolved:
                self.view.highlight_connection(None, resolved, focus=True)

    def sync_options_from(
        self,
        *,
        show_sr: bool,
        show_cs: bool,
        limit_ports: bool,
        show_delegation: bool,
        nest_preview: bool,
    ):
        for chk, val in (
            (self.chk_sr, show_sr),
            (self.chk_cs, show_cs),
            (self.chk_limit, limit_ports),
            (self.chk_deleg, show_delegation),
            (self.chk_nest, nest_preview),
        ):
            chk.blockSignals(True)
            chk.setChecked(val)
            chk.blockSignals(False)

    def port_kinds(self) -> Set[str]:
        kinds: Set[str] = set()
        if self.chk_sr.isChecked():
            kinds.add("SR")
        if self.chk_cs.isChecked():
            kinds.add("CS")
        return kinds or {"SR", "CS"}

    def nest_preview(self) -> bool:
        return self.chk_nest.isChecked()

    def reload(self):
        """Rebuild graph for independent sessions."""
        if self._sync or not self._model:
            return
        show_ports = self.chk_sr.isChecked() or self.chk_cs.isChecked()
        kinds = self.port_kinds()
        if self._view_mode == "chain" and self._chain:
            g = build_sr_chain_graph(self._model, self._chain)
        elif self._view_mode == "swc" and self._current_swc:
            g = build_swc_type_graph(
                self._model,
                self._current_swc,
                show_ports=show_ports,
                limit_ports=self.chk_limit.isChecked(),
                port_kinds=kinds,
            )
        elif self._current_comp:
            g = build_composition_graph(
                self._model,
                self._current_comp,
                show_delegation=self.chk_deleg.isChecked(),
                show_sr_ports=show_ports,
                limit_ports=self.chk_limit.isChecked(),
                nest_preview=self.chk_nest.isChecked(),
                port_kinds=kinds,
            )
        else:
            g = CompositionGraph(composition_path="")
        self.view.set_graph(g)
        self._update_crumb()
        focus = self._pending_focus
        self._pending_focus = []
        if focus:
            resolved = []
            for ref in focus:
                nid = self.view.resolve_node_id(ref)
                if nid:
                    resolved.append(nid)
            if resolved:
                self.view.highlight_connection(None, resolved, focus=True)

    def navigate_to(
        self,
        composition_path: str,
        *,
        push: bool = False,
        focus_ids: Optional[List[str]] = None,
    ):
        if self._sync:
            self.drill_into.emit(composition_path)
            return
        if not self._model or not composition_path:
            return
        swc = self._model.swc_types.get(composition_path)
        if not swc or swc.kind != "COMPOSITION":
            return
        if push and self._current_comp and self._current_comp != composition_path:
            self._nav_stack.append(self._current_comp)
        self._view_mode = "composition"
        self._current_swc = ""
        self._current_comp = composition_path
        self._pending_focus = list(focus_ids or [])
        self.setWindowTitle(f"Graph · {swc.name}")
        self.reload()

    def _update_crumb(self):
        if not self._model:
            self.crumb.set_parts([])
            self.btn_back.setEnabled(False)
            return
        if self._view_mode == "chain":
            name = ""
            if self._chain:
                name = self._model.resolve_name(self._chain.start_port)
            self.crumb.set_parts([f"链路: {name}"])
            self.btn_back.setEnabled(True)
            return
        if self._view_mode == "swc" and self._current_swc:
            self.crumb.set_parts([self._model.resolve_name(self._current_swc)])
            self.btn_back.setEnabled(bool(self._nav_stack))
            return
        parts = [self._model.resolve_name(p) for p in self._nav_stack]
        if self._current_comp:
            parts.append(self._model.resolve_name(self._current_comp))
        self.crumb.set_parts(parts)
        self.btn_back.setEnabled(bool(self._nav_stack))

    def _options_changed(self):
        if self._sync:
            # Main will pick up options on next rebuild if we emit — reload via signal not needed;
            # parent may listen; for sync windows just rebuild mirror by asking parent isn't wired.
            # Independent enough: emit nothing; main owns options. Local options only affect
            # independent windows. For sync, change nest on main.
            return
        self.reload()

    def _on_node(self, node_id: str, kind: str):
        self._selected_drill = ""
        if self.view._graph:
            for n in self.view._graph.nodes:
                if n.id == node_id:
                    self._selected_drill = (
                        n.drill_path
                        or (n.type_ref if n.kind in ("proto_comp", "nested_child") else "")
                    )
                    break
        self.node_clicked.emit(node_id, kind)

    def _on_edge(self, edge_id: str, kind: str):
        self.edge_clicked.emit(edge_id, kind)

    def _on_drill(self, type_path: str):
        if self._sync:
            self.drill_into.emit(type_path)
        else:
            self.navigate_to(type_path, push=True)

    def _on_back(self):
        if self._sync:
            self.nav_back.emit()
            return
        if self._view_mode == "chain":
            self._view_mode = "composition"
            self._chain = None
            self.reload()
            return
        if not self._nav_stack:
            return
        parent = self._nav_stack.pop()
        self._current_comp = parent
        self._view_mode = "composition"
        self.reload()

    def _on_crumb(self, index: int):
        if self._sync:
            self.crumb_activated.emit(index)
            return
        if index < 0 or index >= len(self._nav_stack):
            return
        # jump: keep stack up to index, current = that path
        target = self._nav_stack[index]
        self._nav_stack = self._nav_stack[:index]
        self._current_comp = target
        self._view_mode = "composition"
        self.reload()

    def _emit_open_child(self, type_path: str):
        if type_path:
            self.open_child_window.emit(type_path)

    def _open_selected_child(self):
        path = self._selected_drill
        if not path and self._model and self._current_comp:
            QMessageBox.information(
                self,
                "新窗口",
                "请先单击选中一个子 Composition（橙色框），或对其 Ctrl+双击 / 右键。",
            )
            return
        if path:
            self.open_child_window.emit(path)

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)
