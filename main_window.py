# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import tempfile
from html import escape as _html_esc
from typing import Optional
from urllib.parse import parse_qs, quote, unquote

from PySide6.QtCore import Qt, QThread, Signal, QSettings, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QSplitter,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QFileDialog,
    QMessageBox,
    QProgressBar,
    QCheckBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QInputDialog,
    QApplication,
    QToolButton,
    QComboBox,
    QPushButton,
)

from .connect_logic import plan_connection
from .graph_builder import (
    build_composition_graph,
    build_peer_star_graph,
    build_swc_type_graph,
    build_sr_chain_graph,
)
from .model import ArxmlModel, SrChain, SrHop
from .parser import ArxmlParser
from .spec_validate import SpecValidateResult, hop_dir_label, validate_arxml_spec
from .undo_stack import UndoStack, format_model_scale
from .writer import save_arxml, write_pending_snapshot
from .widgets.add_assembly_dialog import AddAssemblyDialog
from .widgets.add_delegation_dialog import AddDelegationDialog
from .widgets.breadcrumb import BreadcrumbBar
from .widgets.check_dialog import CheckDialog
from .widgets.composition_scene import CompositionView
from .widgets.connector_table import ConnectorTables
from .widgets.edit_data_mapping_dialog import (
    AddDataMappingDialog,
    EditDataMappingDialog,
)
from .widgets.edit_ib_dialog import (
    AddPortAccessDialog,
    AddRunnableDialog,
    AddTimingEventDialog,
    RebindEventRunnableDialog,
)
from .extract_swc import (
    extract_all_swcs,
    extract_composition_to_file,
    extract_swc_to_file,
    extract_system_slice_to_file,
    list_system_slice_paths,
    build_index,
)
from .peer_chain import build_cross_file_chain, collect_pr_orphan_rows, format_cross_chain
from .project_config import ProjectConfig, load_project_config, save_project_config
from .widgets.batch_delegate_preview import BatchDelegatePreviewDialog
from .widgets.export_swc_dialog import ExportSwcDialog
from .widgets.find_dialog import FindDialog
from .widgets.graph_window import GraphWindow
from .widgets.help_dialog import HelpDialog
from .widgets.peer_dialog import PeerListDialog
from .os_rte import (
    OsRteOverlay,
    default_os_rte_path,
    empty_overlay,
    export_os_rte_csv,
    import_os_rte_csv,
    load_os_rte,
    save_os_rte,
)
from .rte_codegen import generate_rte_skeleton
from .widgets.os_rte_panel import OsRtePanel
from .widgets.rte_panel import RtePanel
from .widgets.spec_validate_dialog import SpecValidateDialog
from .widgets.tree_view import ModelTree


class ParseWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, filepath: str):
        super().__init__()
        self.filepath = filepath

    def run(self):
        try:
            parser = ArxmlParser(progress=lambda m: self.progress.emit(m))
            model = parser.parse(self.filepath)
            self.finished_ok.emit(model)
        except Exception as e:
            self.failed.emit(str(e))


class SpecValidateWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        filepath: str,
        *,
        include_pending_model=None,
        scope_prefix: str = "",
    ):
        super().__init__()
        self.filepath = filepath
        self.include_pending_model = include_pending_model
        self.scope_prefix = scope_prefix or ""
        self._cancelled = False
        self._tmp_path = ""

    def cancel(self):
        self._cancelled = True

    def run(self):
        tmp = None
        try:
            path = self.filepath
            model = self.include_pending_model
            if model is not None and getattr(model, "is_dirty", lambda: False)():
                fd, tmp = tempfile.mkstemp(suffix=".arxml", prefix="arxml_pending_")
                os.close(fd)
                ok, msg = write_pending_snapshot(model, tmp)
                if not ok:
                    if not self._cancelled:
                        self.failed.emit(f"无法写出 pending 快照: {msg}")
                    return
                path = tmp
                self._tmp_path = tmp
            if self._cancelled:
                return
            r = validate_arxml_spec(
                path,
                cancel_check=lambda: self._cancelled,
                progress_cb=lambda m: self.progress.emit(str(m)[:160]),
                scope_prefix=self.scope_prefix,
            )
            if self._cancelled and "cancelled" not in (r.detail or ""):
                return
            if tmp:
                r.detail = (r.detail or "") + " (含未保存 pending)"
                r.filepath = self.filepath
            self.finished_ok.emit(r)
        except Exception as e:
            if not self._cancelled:
                self.failed.emit(str(e))
        finally:
            if tmp and os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ARXML Composition / Port Viewer")
        self.resize(1400, 900)
        self._model: Optional[ArxmlModel] = None
        self._current_comp = ""
        self._current_swc = ""  # Application SWC type path when in type view
        self._view_mode = "composition"  # composition | swc | chain | peers
        self._peer_star_port = ""  # focus port for peer constellation view (pre-lift OK)
        self._peer_star_expand: set[int] = set()  # expanded peer chain indices
        self._nav_stack: list[str] = []  # breadcrumb of composition paths
        self._worker: Optional[ParseWorker] = None
        self._settings = QSettings("x_arxml", "arxml_viewer")
        self._pending_focus: list[str] = []
        self._trace_port = ""  # port being traced
        self._chains: list[SrChain] = []
        self._chain_index = 0
        self._return_view = ("composition", "")  # mode, path when leaving chain view
        self._graph_windows: list[GraphWindow] = []
        self._sync_graph_window: Optional[GraphWindow] = None
        self._last_sel_path = ""
        self._last_sel_kind = ""
        self._peer_model: Optional[ArxmlModel] = None
        self._chain_model_source = "primary"  # primary | peer_file
        self._undo = UndoStack()
        self._peer_undo = UndoStack()
        self._validate_worker: Optional[SpecValidateWorker] = None
        self._last_spec_result: Optional[SpecValidateResult] = None
        self._validate_on_open = True
        self._auto_show_spec_dialog = True
        self._pending_peer_after_load = ""
        self._os_rte: OsRteOverlay = empty_overlay()
        self._os_rte_dlg = None  # QDialog hosting OsRtePanel
        self._validate_defer_timer = QTimer(self)
        self._validate_defer_timer.setSingleShot(True)
        self._validate_defer_timer.timeout.connect(
            lambda: self.run_spec_validate(force_dialog=False, include_pending=False)
        )

        self._build_ui()
        self._build_menu()
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(200)
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.status.addPermanentWidget(self.progress)
        # Offer to reopen last primary+peer pair (P3)
        last = self._settings.value("last_primary", "") or ""
        if last and os.path.isfile(last):
            QTimer.singleShot(300, lambda: self._offer_reopen_last(last))

    def _offer_reopen_last(self, path: str):
        if self._model:
            return
        ans = QMessageBox.question(
            self,
            "最近文件",
            f"重新打开上次文件？\n{path}",
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.load_file(path)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        self.btn_back = QToolButton()
        self.btn_back.setText("← 返回上层")
        self.btn_back.setEnabled(False)
        self.btn_back.clicked.connect(self._nav_back)
        toolbar.addWidget(self.btn_back)
        self.crumb = BreadcrumbBar()
        self.crumb.activated.connect(self._on_crumb_activated)
        toolbar.addWidget(self.crumb, 1)
        self.chk_sr_ports = QCheckBox("SR ports")
        self.chk_sr_ports.setChecked(True)
        self.chk_sr_ports.setToolTip("图上显示 Sender-Receiver 端口（绿/红）")
        self.chk_sr_ports.stateChanged.connect(self._reload_graph)
        toolbar.addWidget(self.chk_sr_ports)
        self.chk_cs_ports = QCheckBox("CS ports")
        self.chk_cs_ports.setChecked(True)
        self.chk_cs_ports.setToolTip("图上显示 Client-Server 端口（紫色）")
        self.chk_cs_ports.stateChanged.connect(self._reload_graph)
        toolbar.addWidget(self.chk_cs_ports)
        self.chk_limit_ports = QCheckBox("Limit ports")
        self.chk_limit_ports.setToolTip(
            "勾选后每侧只画少量端口（有连接的优先），其余显示 +N；"
            "大文件打开时会自动建议勾选"
        )
        self.chk_limit_ports.setChecked(
            self._settings.value("limit_ports", False, type=bool)
        )
        self.chk_limit_ports.stateChanged.connect(self._on_limit_ports_toggled)
        toolbar.addWidget(self.chk_limit_ports)
        self.chk_delegation = QCheckBox("Show delegation edges")
        self.chk_delegation.setChecked(True)
        self.chk_delegation.stateChanged.connect(self._reload_graph)
        toolbar.addWidget(self.chk_delegation)
        self.chk_nest_preview = QCheckBox("嵌套预览")
        self.chk_nest_preview.setChecked(False)
        self.chk_nest_preview.setToolTip(
            "默认关闭：仅画当前层（Simulink 风格）。勾选后在子 Composition 内预览下一层 Prototype"
        )
        self.chk_nest_preview.stateChanged.connect(self._reload_graph)
        toolbar.addWidget(self.chk_nest_preview)
        self.chk_rte_access = QCheckBox("Show RTE Access")
        self.chk_rte_access.setChecked(True)
        self.chk_rte_access.setToolTip(
            "Application SWC 类型图：显示 Runnable→Port Access 边（大文件可关）"
        )
        self.chk_rte_access.stateChanged.connect(self._reload_graph)
        toolbar.addWidget(self.chk_rte_access)
        self.btn_view_struct = QPushButton("结构图")
        self.btn_view_struct.setCheckable(True)
        self.btn_view_struct.setChecked(True)
        self.btn_view_struct.setToolTip("显示 Composition / SWC 结构框图")
        self.btn_view_struct.clicked.connect(lambda: self._set_view_kind("struct"))
        toolbar.addWidget(self.btn_view_struct)
        self.btn_view_chain = QPushButton("链路图")
        self.btn_view_chain.setCheckable(True)
        self.btn_view_chain.setToolTip("显示当前 SR Port 的 Assembly/Delegation 全链路")
        self.btn_view_chain.clicked.connect(lambda: self._set_view_kind("chain"))
        toolbar.addWidget(self.btn_view_chain)
        self.btn_view_peers = QPushButton("对端图")
        self.btn_view_peers.setCheckable(True)
        self.btn_view_peers.setToolTip(
            "1:N：本侧嵌套链路图 + 各对端嵌套链路图并排（同「链路图」风格，非扁平列表）"
        )
        self.btn_view_peers.clicked.connect(lambda: self._set_view_kind("peers"))
        toolbar.addWidget(self.btn_view_peers)
        self.btn_popout = QPushButton("弹出图")
        self.btn_popout.setToolTip("将当前图形在独立窗口中打开（与主窗同步导航）")
        self.btn_popout.clicked.connect(self.popout_graph_window)
        toolbar.addWidget(self.btn_popout)
        self.chk_split = QCheckBox("分屏对照")
        self.chk_split.setToolTip("左侧结构图 + 右侧链路图同时显示")
        self.chk_split.stateChanged.connect(self._on_split_toggled)
        toolbar.addWidget(self.chk_split)
        self.chk_connect = QCheckBox("连线模式")
        self.chk_connect.setToolTip(
            "勾选后从图上 Port 拖到另一 Port 创建连接；"
            "也可不勾选，按住 Shift 拖线。P→R=Assembly，外↔内同向=Delegation"
        )
        self.chk_connect.stateChanged.connect(self._on_connect_mode)
        toolbar.addWidget(self.chk_connect)
        self.lbl_file = QLabel("No file loaded")
        toolbar.addWidget(self.lbl_file)
        root.addLayout(toolbar)

        tip = QLabel(
            "提示：Shift/连线模式拖 Port 建连 · 分屏对照 · Find/检查/重命名 · "
            "Ctrl+N Assembly · Ctrl+D Delegation"
        )
        tip.setStyleSheet("color:#666; font-size:11px;")
        root.addWidget(tip)

        main_split = QSplitter(Qt.Orientation.Horizontal)

        self.tree = ModelTree()
        self.tree.selection_path.connect(self._on_tree_select)
        self.tree.export_swc_requested.connect(self.export_swc_arxml_one)
        main_split.addWidget(self.tree)

        center_split = QSplitter(Qt.Orientation.Vertical)
        self.graph_host = QSplitter(Qt.Orientation.Horizontal)
        self.graph = CompositionView()
        self.graph.node_clicked.connect(self._on_graph_node)
        self.graph.edge_clicked.connect(self._on_graph_edge)
        self.graph.drill_into.connect(self._drill_into)
        self.graph.open_in_new_window.connect(self.open_composition_in_new_window)
        self.graph.connect_ports.connect(self._on_connect_ports)
        self.graph.navigate_to_port.connect(self._navigate_to_port)
        self.graph.export_swc_requested.connect(self.export_swc_arxml_one)
        self.graph.peer_lookup = self._peer_lookup_for_menu
        self.graph_chain_view = CompositionView()
        self.graph_chain_view.node_clicked.connect(self._on_graph_node)
        self.graph_chain_view.edge_clicked.connect(self._on_graph_edge)
        self.graph_chain_view.navigate_to_port.connect(self._navigate_to_port)
        self.graph_chain_view.export_swc_requested.connect(self.export_swc_arxml_one)
        self.graph_chain_view.peer_lookup = self._peer_lookup_for_menu
        self.graph_chain_view.hide()
        self.graph_host.addWidget(self.graph)
        self.graph_host.addWidget(self.graph_chain_view)
        self.graph_host.setStretchFactor(0, 1)
        self.graph_host.setStretchFactor(1, 1)
        center_split.addWidget(self.graph_host)

        self.tables = ConnectorTables()
        self.tables.row_selected.connect(self._on_table_row)
        self.tables.add_assembly_requested.connect(lambda: self.add_assembly_connector("All"))
        self.tables.add_delegation_requested.connect(self.add_delegation_connector)
        center_split.addWidget(self.tables)
        center_split.setStretchFactor(0, 3)
        center_split.setStretchFactor(1, 2)
        main_split.addWidget(center_split)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("Properties"))
        self.detail = QTextBrowser()
        self.detail.setReadOnly(True)
        self.detail.setOpenLinks(False)
        self.detail.setOpenExternalLinks(False)
        self.detail.anchorClicked.connect(self._on_detail_link)
        rv.addWidget(self.detail, 2)
        rv.addWidget(QLabel("Port 全链路 (SR/CS · 跳数含方向)"))
        chain_bar = QHBoxLayout()
        chain_bar.addWidget(QLabel("实例/路径:"))
        self.cmb_chain = QComboBox()
        self.cmb_chain.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_chain.currentIndexChanged.connect(self._on_chain_combo)
        chain_bar.addWidget(self.cmb_chain, 1)
        self.btn_show_chain = QPushButton("打开链路图")
        self.btn_show_chain.clicked.connect(lambda: self._set_view_kind("chain"))
        chain_bar.addWidget(self.btn_show_chain)
        self.btn_show_peers = QPushButton("打开对端图")
        self.btn_show_peers.setToolTip("本侧 + 全部 P↔R 对端同屏（1:N）")
        self.btn_show_peers.clicked.connect(lambda: self._set_view_kind("peers"))
        chain_bar.addWidget(self.btn_show_peers)
        self.btn_peers = QPushButton("对端列表…")
        self.btn_peers.setToolTip("本文件 + 对照文件的 P/R / Delegation / 链路对端")
        self.btn_peers.clicked.connect(self.show_peer_list)
        chain_bar.addWidget(self.btn_peers)
        self.btn_jump_peer = QPushButton("跳转 P↔R 对端")
        self.btn_jump_peer.setToolTip(
            "优先跳 Assembly/同名_P↔_R/对照文件反向口；"
            "没有时才退到链路另一端或委托同向端"
        )
        self.btn_jump_peer.clicked.connect(self.jump_chain_peer)
        chain_bar.addWidget(self.btn_jump_peer)
        rv.addLayout(chain_bar)
        self.sr_table = QTableWidget(0, 7)
        self.sr_table.setHorizontalHeaderLabels(
            ["#", "Kind", "方向", "Connector", "From", "To", "Composition"]
        )
        self.sr_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sr_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sr_table.itemSelectionChanged.connect(self._on_sr_hop_select)
        self.sr_table.cellDoubleClicked.connect(self._on_sr_hop_locate)
        rv.addWidget(self.sr_table, 2)
        rv.addWidget(QLabel("RTE 映射 (Event → Runnable → Port)"))
        self.rte_panel = RtePanel()
        rv.addWidget(self.rte_panel, 2)
        main_split.addWidget(right)

        main_split.setStretchFactor(0, 2)
        main_split.setStretchFactor(1, 5)
        main_split.setStretchFactor(2, 2)
        root.addWidget(main_split, 1)

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")
        act_open = QAction("&Open ARXML…", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self.open_file)
        file_menu.addAction(act_open)

        self.recent_menu = file_menu.addMenu("Recent")
        self._rebuild_recent_menu()

        act_peer = QAction("Open &peer ARXML (对照)…", self)
        act_peer.setToolTip("加载第二份 ARXML（如 ZCUP）用于跨文件 P↔R 对端匹配")
        act_peer.triggered.connect(self.open_peer_file)
        file_menu.addAction(act_peer)
        act_clear_peer = QAction("Clear peer ARXML", self)
        act_clear_peer.triggered.connect(self.clear_peer_file)
        file_menu.addAction(act_clear_peer)
        act_save_peer = QAction("Save peer ARXML…", self)
        act_save_peer.setToolTip("将对照文件的 pending 修改写回对照 ARXML")
        act_save_peer.triggered.connect(self.save_peer_arxml_file)
        file_menu.addAction(act_save_peer)
        act_swap_peer = QAction("Swap: open peer as primary…", self)
        act_swap_peer.setToolTip("把对照文件切成主文件编辑（原主文件可再作对照）")
        act_swap_peer.triggered.connect(self.swap_peer_as_primary)
        file_menu.addAction(act_swap_peer)

        file_menu.addSeparator()
        act_val = QAction("Validate AUTOSAR…", self)
        act_val.setShortcut(QKeySequence("Ctrl+Shift+V"))
        act_val.setToolTip(
            "校验已保存文件：arxml_schema_validator + AUTOSAR_00046.xsd\n"
            "含 XSD / 语义 / Vector 40329 N:M"
        )
        act_val.triggered.connect(
            lambda: self.run_spec_validate(force_dialog=True, include_pending=False)
        )
        file_menu.addAction(act_val)
        act_val_pend = QAction("Validate with pending edits…", self)
        act_val_pend.setToolTip(
            "先将未保存修改写出临时快照再校验（不改磁盘源文件）"
        )
        act_val_pend.triggered.connect(
            lambda: self.run_spec_validate(force_dialog=True, include_pending=True)
        )
        file_menu.addAction(act_val_pend)
        act_val_scope = QAction("Validate current Composition/SWC…", self)
        act_val_scope.setToolTip(
            "全量跑引擎后，结果过滤为当前 Composition 或选中 SWC 路径相关项"
        )
        act_val_scope.triggered.connect(self.run_spec_validate_scoped)
        file_menu.addAction(act_val_scope)
        act_val_cancel = QAction("Cancel validation", self)
        act_val_cancel.setShortcut(QKeySequence("Ctrl+Shift+C"))
        act_val_cancel.triggered.connect(self.cancel_spec_validate)
        file_menu.addAction(act_val_cancel)
        self.act_validate_on_open = QAction("Validate on open (deferred)", self)
        self.act_validate_on_open.setCheckable(True)
        self.act_validate_on_open.setChecked(
            self._settings.value("validate_on_open", True, type=bool)
        )
        self.act_validate_on_open.setToolTip(
            "打开后空闲约 1.2s 再后台校验，可随时 Cancel validation"
        )
        self.act_validate_on_open.toggled.connect(self._on_validate_on_open_toggled)
        file_menu.addAction(self.act_validate_on_open)
        self._validate_on_open = self.act_validate_on_open.isChecked()

        act_export = QAction("Export connectors CSV…", self)
        act_export.triggered.connect(self.export_csv)
        file_menu.addAction(act_export)
        act_export_swc = QAction("Export SWC(s) ARXML…（多选到目录）", self)
        act_export_swc.setToolTip(
            "打开列表多选若干 Application SWC，批量导出到一个目录（每 SWC 一个文件，含依赖）"
        )
        act_export_swc.triggered.connect(self.export_swc_arxml)
        file_menu.addAction(act_export_swc)
        act_export_swc_cur = QAction("Export current SWC ARXML…（单个文件）", self)
        act_export_swc_cur.setShortcut(QKeySequence("Ctrl+Shift+E"))
        act_export_swc_cur.setToolTip(
            "导出当前选中的那一个 SWC 到指定路径；也可在左树/图上右键 SWC 直接导出"
        )
        act_export_swc_cur.triggered.connect(self.export_current_swc_arxml)
        file_menu.addAction(act_export_swc_cur)
        act_export_comp = QAction("Export current Composition slice…", self)
        act_export_comp.setToolTip("导出当前 Composition（含 REF 闭包）")
        act_export_comp.triggered.connect(self.export_current_composition_slice)
        file_menu.addAction(act_export_comp)
        act_export_sys = QAction("Export SYSTEM / Mapping slice…", self)
        act_export_sys.setToolTip("导出 SYSTEM 或 SYSTEM-MAPPING 切片")
        act_export_sys.triggered.connect(self.export_system_slice)
        file_menu.addAction(act_export_sys)

        act_img = QAction("Save graph as image…", self)
        act_img.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_img.triggered.connect(self.save_graph_image)
        file_menu.addAction(act_img)

        file_menu.addSeparator()
        act_save = QAction("&Save ARXML", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self.save_arxml_file)
        file_menu.addAction(act_save)
        act_save_as = QAction("Save ARXML &As…", self)
        act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        act_save_as.triggered.connect(self.save_arxml_as)
        file_menu.addAction(act_save_as)
        act_open_osrte = QAction("Open OS/RTE Mapping…", self)
        act_open_osrte.setToolTip("打开侧车 <stem>.os_rte.json")
        act_open_osrte.triggered.connect(self.open_os_rte_mapping)
        file_menu.addAction(act_open_osrte)
        act_save_osrte = QAction("Save OS/RTE Mapping", self)
        act_save_osrte.setToolTip("保存 OsTask / Runnable→Task 侧车 JSON")
        act_save_osrte.triggered.connect(self.save_os_rte_mapping)
        file_menu.addAction(act_save_osrte)

        file_menu.addSeparator()
        act_quit = QAction("&Quit", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        edit_menu = self.menuBar().addMenu("&Edit")
        act_undo = QAction("&Undo last edit", self)
        act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        act_undo.triggered.connect(self.undo_last_edit)
        edit_menu.addAction(act_undo)
        act_redo = QAction("&Redo", self)
        act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        act_redo.triggered.connect(self.redo_last_edit)
        edit_menu.addAction(act_redo)
        act_undo_peer = QAction("Undo peer edit", self)
        act_undo_peer.setToolTip("撤销对照文件上的编辑（与主文件 Undo 分栈）")
        act_undo_peer.triggered.connect(self.undo_peer_edit)
        edit_menu.addAction(act_undo_peer)
        act_redo_peer = QAction("Redo peer edit", self)
        act_redo_peer.triggered.connect(self.redo_peer_edit)
        edit_menu.addAction(act_redo_peer)
        act_find = QAction("&Find…", self)
        act_find.setShortcut(QKeySequence.StandardKey.Find)
        act_find.triggered.connect(self.find_path)
        edit_menu.addAction(act_find)
        act_check = QAction("Consistency &check…", self)
        act_check.setShortcut(QKeySequence("Ctrl+Shift+C"))
        act_check.triggered.connect(self.run_consistency_check)
        edit_menu.addAction(act_check)
        edit_menu.addSeparator()
        act_add_asm = QAction("Add Assembly connector…", self)
        act_add_asm.setShortcut(QKeySequence("Ctrl+N"))
        act_add_asm.triggered.connect(lambda: self.add_assembly_connector("All"))
        edit_menu.addAction(act_add_asm)
        act_add_cs = QAction("Add CS Assembly…", self)
        act_add_cs.setToolTip("仅列出 Client-Server 端口")
        act_add_cs.triggered.connect(lambda: self.add_assembly_connector("CS"))
        edit_menu.addAction(act_add_cs)
        act_add_del = QAction("Add Delegation connector…", self)
        act_add_del.setShortcut(QKeySequence("Ctrl+D"))
        act_add_del.triggered.connect(self.add_delegation_connector)
        edit_menu.addAction(act_add_del)
        act_ren = QAction("Rename selected connector…", self)
        act_ren.triggered.connect(self.rename_selected_connector)
        edit_menu.addAction(act_ren)
        act_del = QAction("Delete selected connector…", self)
        act_del.triggered.connect(self.delete_selected_connector)
        edit_menu.addAction(act_del)
        edit_menu.addSeparator()
        act_ren_obj = QAction("Rename selected object…", self)
        act_ren_obj.setShortcut(QKeySequence("F2"))
        act_ren_obj.setToolTip(
            "重命名当前选中的 Port / ADT / IDT / SR-IF / Runnable / Event"
        )
        act_ren_obj.triggered.connect(self.rename_selected_object)
        edit_menu.addAction(act_ren_obj)

        edit_menu.addSeparator()
        act_add_map = QAction("Add Data Mapping…", self)
        act_add_map.triggered.connect(self.add_data_mapping)
        edit_menu.addAction(act_add_map)
        act_edit_map = QAction("Edit selected Data Mapping…", self)
        act_edit_map.triggered.connect(self.edit_selected_data_mapping)
        edit_menu.addAction(act_edit_map)
        act_del_map = QAction("Delete selected Data Mapping…", self)
        act_del_map.triggered.connect(self.delete_selected_data_mapping)
        edit_menu.addAction(act_del_map)

        edit_menu.addSeparator()
        act_add_run = QAction("Add Runnable…", self)
        act_add_run.triggered.connect(self.add_runnable)
        edit_menu.addAction(act_add_run)
        act_sym = QAction("Set Runnable Symbol…", self)
        act_sym.triggered.connect(self.set_runnable_symbol)
        edit_menu.addAction(act_sym)
        act_add_ev = QAction("Add Timing Event…", self)
        act_add_ev.triggered.connect(self.add_timing_event)
        edit_menu.addAction(act_add_ev)
        act_add_init = QAction("Add Init Event…", self)
        act_add_init.triggered.connect(self.add_init_event)
        edit_menu.addAction(act_add_init)
        act_add_dre = QAction("Add DataReceived Event…", self)
        act_add_dre.triggered.connect(self.add_data_received_event)
        edit_menu.addAction(act_add_dre)
        act_period = QAction("Set Event Period…", self)
        act_period.triggered.connect(self.set_event_period)
        edit_menu.addAction(act_period)
        act_rebind = QAction("Rebind Event → Runnable…", self)
        act_rebind.triggered.connect(self.rebind_event_runnable)
        edit_menu.addAction(act_rebind)
        act_add_acc = QAction("Add Port Access…", self)
        act_add_acc.triggered.connect(self.add_port_access)
        edit_menu.addAction(act_add_acc)
        act_del_ib = QAction("Delete selected IB object…", self)
        act_del_ib.setToolTip("删除选中的 Runnable / Event / Port Access")
        act_del_ib.triggered.connect(self.delete_selected_ib_object)
        edit_menu.addAction(act_del_ib)

        edit_menu.addSeparator()
        act_add_sig = QAction("Add System Signal…", self)
        act_add_sig.triggered.connect(self.add_system_signal)
        edit_menu.addAction(act_add_sig)
        act_add_port = QAction("Add Port…", self)
        act_add_port.triggered.connect(self.add_port)
        edit_menu.addAction(act_add_port)
        act_add_dg = QAction("Add Delegated Outer Port…", self)
        act_add_dg.setToolTip("创建 Composition 外端口(…_DG_P/_R) + Delegation")
        act_add_dg.triggered.connect(self.add_delegated_outer_port)
        edit_menu.addAction(act_add_dg)
        act_batch_dg = QAction("Batch add Delegated Outer Ports…", self)
        act_batch_dg.setToolTip(
            "当前 Composition 内：为尚未委托出去的内口批量生成 _DG + Delegation"
        )
        act_batch_dg.triggered.connect(self.batch_add_delegated_outer_ports)
        edit_menu.addAction(act_batch_dg)
        act_new_sys = QAction("Create SYSTEM / Mapping Set stub…", self)
        act_new_sys.triggered.connect(self.create_system_mapping_stub)
        edit_menu.addAction(act_new_sys)
        act_peers = QAction("Show port peers…", self)
        act_peers.setShortcut(QKeySequence("Ctrl+Shift+P"))
        act_peers.triggered.connect(self.show_peer_list)
        edit_menu.addAction(act_peers)

        view_menu = self.menuBar().addMenu("&View")
        act_fit = QAction("Fit graph", self)
        act_fit.triggered.connect(lambda: self.graph.fitInView(
            self.graph.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
        ))
        view_menu.addAction(act_fit)
        act_split = QAction("Split structure / chain", self)
        act_split.setCheckable(True)
        act_split.triggered.connect(lambda checked: self.chk_split.setChecked(checked))
        self.act_split = act_split
        view_menu.addAction(act_split)
        act_back = QAction("Back to parent composition", self)
        act_back.setShortcut(QKeySequence("Alt+Left"))
        act_back.triggered.connect(self._nav_back)
        view_menu.addAction(act_back)
        act_pop = QAction("Pop out graph window", self)
        act_pop.setShortcut(QKeySequence("Ctrl+Shift+G"))
        act_pop.triggered.connect(self.popout_graph_window)
        view_menu.addAction(act_pop)
        act_child = QAction("Open composition in new window…", self)
        act_child.setToolTip("对图上选中的子 Composition 在独立窗口打开")
        act_child.triggered.connect(self._open_selected_composition_window)
        view_menu.addAction(act_child)

        tools_menu = self.menuBar().addMenu("&Tools")
        act_osrte = QAction("OS/RTE Mapping…", self)
        act_osrte.setToolTip(
            "浏览/编辑轻量 OsTask 与 Runnable→Task（侧车 JSON，非 ECUC）"
        )
        act_osrte.triggered.connect(self.show_os_rte_mapping)
        tools_menu.addAction(act_osrte)
        act_osrte_csv_in = QAction("Import OS/RTE Mapping CSV…", self)
        act_osrte_csv_in.triggered.connect(self.import_os_rte_csv_file)
        tools_menu.addAction(act_osrte_csv_in)
        act_osrte_csv_out = QAction("Export OS/RTE Mapping CSV…", self)
        act_osrte_csv_out.triggered.connect(self.export_os_rte_csv_file)
        tools_menu.addAction(act_osrte_csv_out)
        act_rte_gen = QAction("Generate RTE skeleton (C)…", self)
        act_rte_gen.setToolTip(
            "按侧车 Task/Mapping 生成 Rte_Task_*.c / Rte_Tasks.h（最小骨架，非完整 RTE）"
        )
        act_rte_gen.triggered.connect(self.generate_rte_skeleton_files)
        tools_menu.addAction(act_rte_gen)

        help_menu = self.menuBar().addMenu("&Help")
        act_help = QAction("Quick help / 速查…", self)
        act_help.setShortcut(QKeySequence("F1"))
        act_help.triggered.connect(self.show_help)
        help_menu.addAction(act_help)
        act_pr_csv = QAction("Export P↔R orphan report CSV…", self)
        act_pr_csv.triggered.connect(self.export_pr_orphan_csv)
        help_menu.addAction(act_pr_csv)
        act_save_proj = QAction("Save project config (.arxml_viewer.json)", self)
        act_save_proj.triggered.connect(self.save_project_config_file)
        help_menu.addAction(act_save_proj)

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        recent = self._settings.value("recent", [])
        if not isinstance(recent, list):
            recent = []
        for path in recent[:10]:
            act = QAction(path, self)
            act.triggered.connect(lambda checked=False, p=path: self.load_file(p))
            self.recent_menu.addAction(act)

    def _push_recent(self, path: str):
        recent = self._settings.value("recent", [])
        if not isinstance(recent, list):
            recent = []
        path = os.path.abspath(path)
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self._settings.setValue("recent", recent[:10])
        self._rebuild_recent_menu()

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ARXML", "", "ARXML (*.arxml);;All (*.*)"
        )
        if path:
            self.load_file(path)

    def load_file(self, path: str):
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Open", f"File not found:\n{path}")
            return
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "Busy", "Already parsing a file.")
            return
        self.cancel_spec_validate()
        self.lbl_file.setText(os.path.basename(path))
        self.status.showMessage(f"Parsing {path}…")
        self.progress.show()
        self._worker = ParseWorker(path)
        self._worker.progress.connect(self._on_parse_progress)
        self._worker.finished_ok.connect(self._on_parsed)
        self._worker.failed.connect(self._on_parse_fail)
        self._worker.start()

    def _on_parse_progress(self, msg: str):
        self.status.showMessage(msg)
        QApplication.processEvents()

    def _on_parsed(self, model: ArxmlModel):
        self.progress.hide()
        self._model = model
        self._undo.clear()
        self._peer_undo.clear()
        self._push_recent(model.filepath)
        self._settings.setValue("last_primary", model.filepath)
        self.tree.set_model(model)
        self.tables.set_model(model)
        self.rte_panel.set_model(model)
        self._load_os_rte_for_model(model)
        for win in list(self._graph_windows):
            try:
                win.set_model(model)
            except RuntimeError:
                pass
        cs_ports = sum(1 for p in model.ports.values() if p.iface_kind == "CS")
        n_beh, n_run, n_ev, n_ok = model.rte_summary()
        rte_note = f"RTE-IB={n_beh}/{n_ok}ok RE={n_run} Ev={n_ev}"
        if n_beh and n_ok == 0:
            rte_note += " (IB empty stubs)"
        prim, rec, arr, n_idt, n_base = model.adt_summary()
        adt_note = f"ADT={prim}+{rec}+{arr} IDT={n_idt} Base={n_base}"
        stats = (
            f"Compositions={len(model.composition_paths())} "
            f"AppSWC={len(model.application_paths())} "
            f"Assembly={len(model.assemblies)} "
            f"Delegation={len(model.delegations)} "
            f"Ports={len(model.ports)} "
            f"SR-IF={len(model.interfaces)} "
            f"CS-IF={len(model.cs_interfaces)} "
            f"CS-Ports={cs_ports} "
            f"{adt_note} "
            f"{rte_note}"
        )
        scale = format_model_scale(model)
        self.status.showMessage(f"{stats}  |  {scale}")
        self._nav_stack = []
        self._update_title()
        # Project config + auto Limit ports for large files
        cfg = load_project_config(model.filepath) if model.filepath else None
        if cfg:
            if cfg.limit_ports and not self.chk_limit_ports.isChecked():
                self.chk_limit_ports.blockSignals(True)
                self.chk_limit_ports.setChecked(True)
                self.chk_limit_ports.blockSignals(False)
            if cfg.peer and os.path.isfile(cfg.peer):
                peer_path = cfg.peer
            else:
                peer_path = self._settings.value("last_peer", "") or ""
        else:
            peer_path = self._settings.value("last_peer", "") or ""
        n_ports = len(model.ports)
        if n_ports >= 800 and not self.chk_limit_ports.isChecked():
            ans = QMessageBox.question(
                self,
                "大文件",
                f"检测到 Ports={n_ports}，建议开启 Limit ports 以加速绘图。\n是否开启？",
            )
            if ans == QMessageBox.StandardButton.Yes:
                self.chk_limit_ports.setChecked(True)
        # auto select first root composition
        if model.root_compositions:
            self._select_composition(model.root_compositions[0], push=False)
        elif model.composition_paths():
            self._select_composition(model.composition_paths()[0], push=False)
        if (
            peer_path
            and os.path.isfile(peer_path)
            and os.path.normcase(peer_path) != os.path.normcase(model.filepath or "")
        ):
            ans = QMessageBox.question(
                self,
                "对照文件",
                f"对照文件:\n{peer_path}\n\n是否加载？",
            )
            if ans == QMessageBox.StandardButton.Yes:
                self._load_peer_path(peer_path, quiet=True)
        self._maybe_attach_pending_peer()
        # AUTOSAR 规范校验：延后启动，减轻打开后立刻二次全量解析卡顿
        if self._validate_on_open:
            self.status.showMessage("将在空闲后自动规范校验…（可 File→Cancel validation）")
            self._validate_defer_timer.start(1200)

    def _on_parse_fail(self, err: str):
        self.progress.hide()
        QMessageBox.critical(self, "Parse error", err)
        self.status.showMessage("Parse failed")

    def _breadcrumb_parts(self) -> list[str]:
        if not self._model:
            return []
        if self._view_mode == "chain" and self._trace_port:
            pname = self._model.resolve_name(self._trace_port)
            n = len(self._chains)
            return [f"SR Chain · {pname} ({self._chain_index + 1}/{max(n, 1)})"]
        if self._view_mode == "swc" and self._current_swc:
            return ["SWC", self._model.resolve_name(self._current_swc)]
        parts = [self._model.resolve_name(p) for p in self._nav_stack]
        if self._current_comp:
            parts.append(self._model.resolve_name(self._current_comp))
        return parts

    def _update_breadcrumb(self):
        parts = self._breadcrumb_parts()
        self.crumb.set_parts(parts)
        if self._view_mode == "chain":
            self.btn_back.setEnabled(True)
        else:
            self.btn_back.setEnabled(bool(self._nav_stack))

    def _on_crumb_activated(self, index: int):
        """Jump to breadcrumb segment (Simulink-style)."""
        if self._view_mode == "chain":
            self._set_view_kind("struct")
            return
        if self._view_mode == "swc":
            # only "SWC" / name — ignore
            return
        if index < 0 or index >= len(self._nav_stack):
            return
        target = self._nav_stack[index]
        self._nav_stack = self._nav_stack[:index]
        self._current_comp = ""
        self._select_composition(target, push=False)
        self.status.showMessage(f"跳转到: {self._model.resolve_name(target)}")

    def _sync_view_buttons(self):
        is_chain = self._view_mode == "chain"
        is_peers = self._view_mode == "peers"
        self.btn_view_chain.setChecked(is_chain)
        self.btn_view_peers.setChecked(is_peers)
        self.btn_view_struct.setChecked(not is_chain and not is_peers)

    def _select_composition(self, path: str, push: bool = False, focus_ids: list[str] | None = None):
        if not path or not self._model:
            return
        if path not in self._model.swc_types:
            return
        if self._model.swc_types[path].kind != "COMPOSITION":
            return
        if push and self._current_comp and self._current_comp != path:
            self._nav_stack.append(self._current_comp)
        self._view_mode = "composition"
        self._current_swc = ""
        self._current_comp = path
        self._return_view = ("composition", path)
        self._pending_focus = list(focus_ids or [])
        self.tables.set_composition(path)
        self._reload_graph()
        self._show_composition_props(path)
        self._update_breadcrumb()
        self._sync_view_buttons()
        self.status.showMessage(f"Composition: {self._model.resolve_name(path)}")

    def _select_swc_type(self, path: str, focus_ids: list[str] | None = None):
        if not path or not self._model:
            return
        swc = self._model.swc_types.get(path)
        if not swc:
            return
        # Composition type from Application list shouldn't happen; still allow type view
        self._view_mode = "swc"
        self._current_swc = path
        self._return_view = ("swc", path)
        self._pending_focus = list(focus_ids or [])
        self.tables.set_composition("")  # clear connector tables
        self._reload_graph()
        self._show_swc_props(path)
        self._update_breadcrumb()
        self._sync_view_buttons()
        self.status.showMessage(f"SWC: {swc.name}  ({swc.kind})")

    def _drill_into(self, type_path: str):
        if not self._model or not type_path:
            return
        swc = self._model.swc_types.get(type_path)
        if not swc or swc.kind != "COMPOSITION":
            self.status.showMessage(f"无法进入: {type_path}")
            return
        self._select_composition(type_path, push=True)
        self.status.showMessage(f"进入 Composition: {swc.name}")

    def _nav_back(self):
        if self._view_mode in ("chain", "peers"):
            self._set_view_kind("struct")
            return
        if not self._nav_stack:
            return
        parent = self._nav_stack.pop()
        self._current_comp = ""
        self._select_composition(parent, push=False)
        self.status.showMessage(f"返回: {self._model.resolve_name(parent)}")

    def _set_view_kind(self, kind: str):
        """kind: struct | chain | peers"""
        if kind == "peers":
            seed = self._peer_star_port or self._trace_port or (
                self._last_sel_path if self._last_sel_kind == "port" else ""
            )
            if not seed or not self._model or seed not in self._model.ports:
                QMessageBox.information(
                    self,
                    "对端图",
                    "请先选择一个 Port，再点「对端图」。\n\n"
                    "Application 口会自动抬到最外层 Composition Port；\n"
                    "本侧与各对端嵌套链路并排（折叠占位可点展开）。",
                )
                self._sync_view_buttons()
                return
            if self._view_mode not in ("peers",):
                if self._view_mode == "swc":
                    self._return_view = ("swc", self._current_swc)
                elif self._view_mode == "chain":
                    pass  # keep prior return_view
                else:
                    self._return_view = ("composition", self._current_comp)
                self._peer_star_expand = {0}  # default expand first peer chain
            lifted = self._model.lift_port_for_peer_view(seed)
            self._peer_star_port = seed
            self._view_mode = "peers"
            self._reload_graph()
            self._update_breadcrumb()
            self._sync_view_buttons()
            n = sum(
                1
                for p in self._model.find_port_peers(
                    lifted,
                    chain=self._current_chain(),
                    peer_model=self._peer_model,
                )
                if p.relation in ("assembly", "direction_pair", "cross_file")
            )
            lift_note = ""
            if lifted != seed:
                lift_note = (
                    f"  ·  已抬升 {self._model.resolve_name(seed)} → "
                    f"{self._model.resolve_name(lifted)}"
                )
            self.status.showMessage(
                f"1:N 对端链路: {self._model.resolve_name(lifted)}  ·  "
                f"{n} 个对端（默认展开 1 条，点占位展开更多）{lift_note}"
            )
            return
        if kind == "chain":
            # If chains empty, try last selected / traced port
            if not self._chains or not any(c.hops for c in self._chains):
                seed = self._trace_port or (
                    self._last_sel_path if self._last_sel_kind == "port" else ""
                )
                if seed and self._model and seed in self._model.ports:
                    self._trace_port_chains(seed, auto_open_chain=False)
            if not self._chains or not any(c.hops for c in self._chains):
                QMessageBox.information(
                    self,
                    "链路图",
                    "请先在左树或图上选择一个有 Assembly/Delegation 连接的 Port，\n"
                    "再点「链路图」。\n\n"
                    "提示：选 Application SWC 的 Port（如 BrkLampSwc/SideBrkLampSts）"
                    "通常会自动打开全链路。",
                )
                self._sync_view_buttons()
                return
            if self._view_mode != "chain":
                if self._view_mode == "swc":
                    self._return_view = ("swc", self._current_swc)
                elif self._view_mode != "peers":
                    self._return_view = ("composition", self._current_comp)
            self._view_mode = "chain"
            # leave split: chain is primary pane
            if self.chk_split.isChecked():
                # still show nested chain on the right; primary stays structure
                pass
            self._reload_graph()
            self._update_breadcrumb()
            self._sync_view_buttons()
            self.status.showMessage(
                "链路图（嵌套 Composition）：橙框=子Composition · 蓝框=SWC · "
                "紫虚线=Delegation · 蓝实线=Assembly · 右键端口可跳对端"
            )
            return
        # struct: restore previous composition/swc view
        mode, path = self._return_view
        if self._view_mode in ("chain", "peers"):
            if mode == "swc" and path:
                self._select_swc_type(path)
            elif path:
                self._select_composition(path, push=False)
            elif self._current_comp:
                self._view_mode = "composition"
                self._reload_graph()
            elif self._current_swc:
                self._view_mode = "swc"
                self._reload_graph()
            else:
                self._view_mode = "composition"
                self._reload_graph()
            self._sync_view_buttons()
            return
        self._sync_view_buttons()

    def _port_kinds(self) -> set[str]:
        kinds: set[str] = set()
        if self.chk_sr_ports.isChecked():
            kinds.add("SR")
        if self.chk_cs_ports.isChecked():
            kinds.add("CS")
        return kinds or {"SR", "CS"}

    def _on_split_toggled(self):
        if hasattr(self, "act_split"):
            self.act_split.blockSignals(True)
            self.act_split.setChecked(self.chk_split.isChecked())
            self.act_split.blockSignals(False)
        split = self.chk_split.isChecked()
        self.graph_chain_view.setVisible(split)
        if split and not self._chains:
            self.status.showMessage("分屏已开：请选择 Port 生成链路后右侧显示链路图")
        self._reload_graph()

    def _build_structure_graph(self):
        """Composition or SWC type graph for left/primary pane."""
        show_ports = self.chk_sr_ports.isChecked() or self.chk_cs_ports.isChecked()
        kinds = self._port_kinds()
        if self._view_mode == "swc" or (
            self.chk_split.isChecked() and self._current_swc and not self._current_comp
        ):
            path = self._current_swc
            if not path:
                return None
            return build_swc_type_graph(
                self._model,
                path,
                show_ports=show_ports,
                limit_ports=self.chk_limit_ports.isChecked(),
                port_kinds=kinds,
                show_rte_access=self.chk_rte_access.isChecked(),
            )
        path = self._current_comp
        if not path:
            # when in chain-only mode without split, still need something
            mode, p = self._return_view
            if mode == "composition" and p:
                path = p
            elif mode == "swc" and p:
                return build_swc_type_graph(
                    self._model,
                    p,
                    show_ports=show_ports,
                    limit_ports=self.chk_limit_ports.isChecked(),
                    port_kinds=kinds,
                    show_rte_access=self.chk_rte_access.isChecked(),
                )
            else:
                return None
        return build_composition_graph(
            self._model,
            path,
            show_delegation=self.chk_delegation.isChecked(),
            show_sr_ports=show_ports,
            limit_ports=self.chk_limit_ports.isChecked(),
            nest_preview=self.chk_nest_preview.isChecked(),
            port_kinds=kinds,
        )

    def _reload_graph(self):
        if not self._model:
            return
        focus = list(self._pending_focus)
        split = self.chk_split.isChecked()

        if split:
            # Left: structure; Right: chain (if any)
            g_struct = self._build_structure_graph()
            if g_struct is not None:
                self.graph.set_graph(g_struct)
            chain = self._current_chain()
            cm = self._active_chain_model() or self._model
            if chain and cm:
                self.graph_chain_view.set_graph(build_sr_chain_graph(cm, chain))
                self.graph_chain_view.show()
            else:
                self.graph_chain_view.hide()
            self._sync_view_buttons()
            self._pending_focus = []
            if focus and g_struct is not None:
                resolved = []
                for ref in focus:
                    nid = self.graph.resolve_node_id(ref)
                    if nid:
                        resolved.append(nid)
                if resolved:
                    self.graph.highlight_connection(None, resolved, focus=True)
            if g_struct is not None:
                self._mirror_sync_graph_window(g_struct, focus)
            return

        if self._view_mode == "chain":
            chain = self._current_chain()
            if not chain:
                return
            cm = self._active_chain_model() or self._model
            g = build_sr_chain_graph(cm, chain)
            self.graph.set_graph(g)
            self._sync_view_buttons()
            self._mirror_sync_graph_window(g, focus)
            return

        if self._view_mode == "peers":
            seed = self._peer_star_port or self._trace_port
            if not seed or seed not in self._model.ports:
                return
            g = build_peer_star_graph(
                self._model,
                seed,
                peer_model=self._peer_model,
                max_full_peers=1,
                expand_peer_indices=self._peer_star_expand or {0},
            )
            self.graph.set_graph(g)
            self._sync_view_buttons()
            self._pending_focus = []
            lifted = self._model.lift_port_for_peer_view(seed)
            nid = self.graph.resolve_node_id(lifted) or self.graph.resolve_node_id(
                seed
            )
            if nid:
                self.graph.highlight_connection(None, [nid], focus=True)
            self._mirror_sync_graph_window(g, [nid] if nid else focus)
            return

        g = self._build_structure_graph()
        if g is None:
            return
        self.graph.set_graph(g)
        self._sync_view_buttons()
        self._pending_focus = []
        if focus:
            resolved = []
            for ref in focus:
                nid = self.graph.resolve_node_id(ref)
                if nid:
                    resolved.append(nid)
            if resolved:
                self.graph.highlight_connection(None, resolved, focus=True)
        self._mirror_sync_graph_window(g, focus)

    def _mirror_sync_graph_window(self, graph, focus_ids: list[str] | None = None):
        win = self._sync_graph_window
        if win is None:
            return
        try:
            win.sync_options_from(
                show_sr=self.chk_sr_ports.isChecked(),
                show_cs=self.chk_cs_ports.isChecked(),
                limit_ports=self.chk_limit_ports.isChecked(),
                show_delegation=self.chk_delegation.isChecked(),
                nest_preview=self.chk_nest_preview.isChecked(),
            )
            win.mirror_graph(
                graph,
                crumb_parts=self._breadcrumb_parts(),
                can_back=(
                    self._view_mode == "chain" or bool(self._nav_stack)
                ),
                focus_ids=focus_ids,
            )
        except RuntimeError:
            self._sync_graph_window = None

    def popout_graph_window(self):
        """Open / focus a graph window synced with the main view."""
        if not self._model:
            QMessageBox.information(self, "弹出图", "请先打开 ARXML。")
            return
        if self._sync_graph_window is not None:
            try:
                self._sync_graph_window.raise_()
                self._sync_graph_window.activateWindow()
                self._reload_graph()
                return
            except RuntimeError:
                self._sync_graph_window = None
        title = "Graph (同步主窗)"
        if self._current_comp:
            title = f"Graph · {self._model.resolve_name(self._current_comp)} (同步)"
        win = GraphWindow(
            self._model,
            title=title,
            sync_with_main=True,
            show_sr=self.chk_sr_ports.isChecked(),
            show_cs=self.chk_cs_ports.isChecked(),
            limit_ports=self.chk_limit_ports.isChecked(),
            show_delegation=self.chk_delegation.isChecked(),
            nest_preview=self.chk_nest_preview.isChecked(),
            parent=None,
        )
        win.node_clicked.connect(self._on_graph_node)
        win.edge_clicked.connect(self._on_graph_edge)
        win.drill_into.connect(self._drill_into)
        win.nav_back.connect(self._nav_back)
        win.crumb_activated.connect(self._on_crumb_activated)
        win.open_child_window.connect(self.open_composition_in_new_window)
        win.closed.connect(self._on_graph_window_closed)
        self._sync_graph_window = win
        self._graph_windows.append(win)
        win.show()
        self._reload_graph()
        self.status.showMessage("已弹出图形窗口（与主窗同步）")

    def open_composition_in_new_window(self, composition_path: str):
        """Independent graph window starting at a composition type (feature 3)."""
        if not self._model or not composition_path:
            return
        swc = self._model.swc_types.get(composition_path)
        if not swc or swc.kind != "COMPOSITION":
            QMessageBox.information(
                self, "新窗口", f"不是 Composition 类型:\n{composition_path}"
            )
            return
        win = GraphWindow(
            self._model,
            title=f"Graph · {swc.name}",
            sync_with_main=False,
            composition_path=composition_path,
            nav_stack=[],
            view_mode="composition",
            show_sr=self.chk_sr_ports.isChecked(),
            show_cs=self.chk_cs_ports.isChecked(),
            limit_ports=self.chk_limit_ports.isChecked(),
            show_delegation=self.chk_delegation.isChecked(),
            nest_preview=self.chk_nest_preview.isChecked(),
            parent=None,
        )
        win.node_clicked.connect(self._on_graph_node)
        win.edge_clicked.connect(self._on_graph_edge)
        # Independent window drills locally; still allow spawning more children
        win.open_child_window.connect(self.open_composition_in_new_window)
        win.closed.connect(self._on_graph_window_closed)
        self._graph_windows.append(win)
        win.show()
        self.status.showMessage(f"新窗口: {swc.name}")

    def _open_selected_composition_window(self):
        drill = getattr(self.graph, "_last_selected_drill", "") or ""
        if not drill:
            QMessageBox.information(
                self,
                "新窗口",
                "请先在图上选中一个子 Composition（橙色框），\n"
                "或对其右键 / Ctrl+双击。",
            )
            return
        self.open_composition_in_new_window(drill)

    def _on_graph_window_closed(self, win):
        if win is self._sync_graph_window:
            self._sync_graph_window = None
        try:
            self._graph_windows.remove(win)
        except ValueError:
            pass

    def _current_chain(self) -> Optional[SrChain]:
        if not self._chains:
            return None
        if self._chain_index < 0 or self._chain_index >= len(self._chains):
            return self._chains[0]
        return self._chains[self._chain_index]

    def _trace_port_chains(self, port_path: str, auto_open_chain: bool = True):
        if not self._model or not port_path:
            return
        self._trace_port = port_path
        self._chains = self._model.trace_sr_port(port_path)
        self._chain_index = 0
        self._populate_chain_combo()
        self._fill_sr_chain_table(self._current_chain())
        hops = len(self._current_chain().hops) if self._current_chain() else 0
        has_hops = bool(self._chains and any(c.hops for c in self._chains))
        msg = (
            f"SR 全链路: {self._model.resolve_name(port_path)}  "
            f"→ {len(self._chains)} 条路径, 当前 {hops} 跳"
        )
        if has_hops and not auto_open_chain and self._view_mode != "chain":
            msg += "  · 点工具栏「链路图」查看嵌套全链路"
        self.status.showMessage(msg)
        if has_hops and auto_open_chain:
            if self.chk_split.isChecked():
                self._reload_graph()
            else:
                self._set_view_kind("chain")
        elif has_hops and (
            self._view_mode == "chain" or self.chk_split.isChecked()
        ):
            # Already on chain / split: refresh nested diagram after re-trace
            self._reload_graph()

    def _populate_chain_combo(self):
        self.cmb_chain.blockSignals(True)
        self.cmb_chain.clear()
        if not self._model:
            self.cmb_chain.blockSignals(False)
            return
        for i, ch in enumerate(self._chains):
            proto = self._model.resolve_name(ch.start_proto) if ch.start_proto else "(no instance)"
            end = ""
            if ch.endpoints:
                end = " → " + self._model.resolve_name(ch.endpoints[0])
            self.cmb_chain.addItem(f"{i + 1}. {proto}{end}  ({len(ch.hops)} hops)", i)
        self.cmb_chain.setCurrentIndex(self._chain_index)
        self.cmb_chain.blockSignals(False)

    def _on_chain_combo(self, idx: int):
        if idx < 0 or idx >= len(self._chains):
            return
        self._chain_index = idx
        self._fill_sr_chain_table(self._current_chain())
        if self._view_mode == "chain":
            self._reload_graph()
        self._update_breadcrumb()

    def _fill_sr_chain_table(self, chain: Optional[SrChain]):
        self.sr_table.setRowCount(0)
        cm = self._active_chain_model() or self._model
        if not chain or not cm:
            return
        self.sr_table.setRowCount(len(chain.hops))
        for i, hop in enumerate(chain.hops):
            vals = [
                str(i + 1),
                hop.kind,
                hop_dir_label(cm, hop),
                hop.connector_name,
                hop.from_label(cm),
                hop.to_label(cm),
                cm.resolve_name(hop.composition_path),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, i)
                item.setData(Qt.ItemDataRole.UserRole + 1, hop.connector_path)
                item.setData(Qt.ItemDataRole.UserRole + 2, hop.composition_path)
                item.setData(Qt.ItemDataRole.UserRole + 3, hop.kind)
                item.setData(Qt.ItemDataRole.UserRole + 4, hop.from_port)
                item.setData(Qt.ItemDataRole.UserRole + 5, hop.to_port)
                self.sr_table.setItem(i, c, item)
        self.sr_table.resizeColumnsToContents()

    def _on_sr_hop_select(self):
        rows = self.sr_table.selectionModel().selectedRows() if self.sr_table.selectionModel() else []
        if not rows:
            return
        item = self.sr_table.item(rows[0].row(), 0)
        if not item:
            return
        hop_i = item.data(Qt.ItemDataRole.UserRole)
        chain = self._current_chain()
        if chain is None or hop_i is None or hop_i >= len(chain.hops):
            return
        hop = chain.hops[int(hop_i)]
        cm = self._active_chain_model() or self._model
        self._set_detail(
            [
                f"Hop #{int(hop_i) + 1}",
                f"Kind: {hop.kind}",
                f"Connector: {hop.connector_name}",
                f"Path: {hop.connector_path}",
                f"Composition: {hop.composition_path}",
                f"From: {hop.from_label(cm)}",
                f"To: {hop.to_label(cm)}",
                f"Interface: {hop.interface}",
                "",
                "选中 hop 会高亮整条链路上的端口；双击 → Composition 定位",
            ]
        )
        if self._view_mode == "chain" or self.chk_split.isChecked():
            # highlight this hop + full chain path ports
            edge_id = hop.connector_path or f"chainhop::{hop_i}::{hop.connector_name}"
            node_ids: list[str] = []
            for h in chain.hops:
                for pp in (h.from_port, h.to_port):
                    if not pp:
                        continue
                    for view in (self.graph, self.graph_chain_view):
                        g = getattr(view, "_graph", None)
                        if not g:
                            continue
                        for n in g.nodes:
                            if (n.meta or {}).get("port_path") == pp:
                                node_ids.append(n.id)
            views = [self.graph]
            if self.chk_split.isChecked():
                views.append(self.graph_chain_view)
            for view in views:
                if not view.isVisible():
                    continue
                view.highlight_connection(edge_id, node_ids or None, focus=True)

    def _on_sr_hop_locate(self, row: int, _col: int):
        item = self.sr_table.item(row, 0)
        if not item or not self._model:
            return
        comp = item.data(Qt.ItemDataRole.UserRole + 2) or ""
        kind = item.data(Qt.ItemDataRole.UserRole + 3) or ""
        conn = item.data(Qt.ItemDataRole.UserRole + 1) or ""
        from_port = item.data(Qt.ItemDataRole.UserRole + 4) or ""
        to_port = item.data(Qt.ItemDataRole.UserRole + 5) or ""
        if not comp:
            return
        focus = []
        for ref in (from_port, to_port):
            if ref:
                focus.append(ref)
                focus.append(f"outer::{ref}")
        self._select_composition(comp, push=False, focus_ids=focus)
        # also try highlight edge after graph loads
        self._pending_focus = focus
        self._reload_graph()
        if conn:
            node_ids = []
            for ref in (from_port, to_port):
                nid = self.graph.resolve_node_id(ref)
                if nid:
                    node_ids.append(nid)
            edge_id = conn
            if edge_id not in self.graph._edge_items:
                for eid in self.graph._edge_items:
                    if eid == conn or eid.endswith("/" + str(conn).split("/")[-1]):
                        edge_id = eid
                        break
            self.graph.highlight_connection(edge_id, node_ids, focus=True)
        self.status.showMessage(f"定位 {kind}: {self._model.resolve_name(conn)} @ {self._model.resolve_name(comp)}")

    def _on_tree_select(self, path: str, kind: str):
        if not self._model or not path:
            return
        self._last_sel_path = path
        self._last_sel_kind = kind
        self.tables.set_selection_filter(path)
        if kind == "behavior":
            self._show_behavior_props(path)
            return
        if kind == "runnable":
            self._show_runnable_props(path)
            return
        if kind == "os_task":
            self._show_os_task_props(path)
            return
        if kind == "rte_event":
            self._show_rte_event_props(path)
            return
        if kind == "adt":
            self._show_adt_props(path)
            return
        if kind == "adt_element":
            self._show_adt_element_props(path)
            return
        if kind == "idt":
            self._show_idt_props(path)
            return
        if kind == "base_type":
            self._show_base_type_props(path)
            return
        if kind == "data_type_map":
            # path is ADT ref; show ADT with mapping emphasis
            self._show_adt_props(path)
            return
        if kind == "sr_interface":
            self._show_sr_interface_props(path)
            return
        if kind == "sr_data_element":
            self._show_sr_data_element_props(path)
            return
        if kind == "assembly":
            self._show_connector_props(path, "assembly")
            return
        if kind == "delegation":
            self._show_connector_props(path, "delegation")
            return
        if kind == "data_mapping":
            self._show_data_mapping_props(path)
            return
        if kind == "cs_interface":
            cs = self._model.cs_interfaces.get(path)
            if not cs:
                return
            lines = [
                "Kind: CLIENT-SERVER-INTERFACE",
                f"Name: {cs.name}",
                f"Path: {path}",
                f"Operations: {len(cs.operations)}",
            ]
            for op in cs.operations[:50]:
                args = f"({', '.join(op.arguments)})" if op.arguments else ""
                lines.append(f"  - {op.name}{args}")
            if len(cs.operations) > 50:
                lines.append(f"  … +{len(cs.operations) - 50} more")
            # list SWCs that use this interface
            users = [
                p for p in self._model.ports.values()
                if p.interface_ref == path
            ]
            lines.append(f"Ports using this IF: {len(users)}")
            for p in users[:20]:
                lines.append(f"  - {p.direction} {self._model.resolve_name(p.owner_path)}.{p.name}")
            self._set_detail(lines)
            return
        if kind == "cs_operation":
            # find parent CS IF
            for cs in self._model.cs_interfaces.values():
                for op in cs.operations:
                    if op.path == path:
                        args = ", ".join(op.arguments) if op.arguments else "(no args)"
                        self._set_detail(
                            [
                                "Kind: CLIENT-SERVER-OPERATION",
                                f"Name: {op.name}",
                                f"Path: {op.path}",
                                f"Interface: {cs.name}",
                                f"Arguments: {args}",
                            ]
                        )
                        return
            return
        if kind == "composition":
            self._nav_stack = []
            self._select_composition(path, push=False)
        elif kind == "prototype":
            proto = self._model.prototypes.get(path)
            if not proto:
                return
            self._nav_stack = []
            # Show parent composition and locate this prototype (and its type if nested)
            focus = [path]
            t = self._model.swc_types.get(proto.type_ref)
            self._select_composition(proto.composition_path, push=False, focus_ids=focus)
            self._show_prototype_props(path)
            if t and t.kind == "COMPOSITION":
                self.status.showMessage(
                    f"Prototype → {proto.name}  (Composition 类型，可双击图上橙框进入)"
                )
        elif kind == "port":
            port = self._model.ports.get(path)
            if not port:
                return
            owner = self._model.swc_types.get(port.owner_path)
            # Composition outer ports with hops also open nested chain (not only App)
            peek = self._model.trace_sr_port(path)
            will_chain = bool(peek and any(c.hops for c in peek))
            if owner and owner.kind == "COMPOSITION":
                self._nav_stack = []
                self._select_composition(
                    port.owner_path, push=False, focus_ids=[f"outer::{path}", path]
                )
                self._show_port_props(path, auto_open_chain=will_chain)
            elif owner:
                # Application / other SWC type → type view + full SR chain
                self._select_swc_type(port.owner_path, focus_ids=[path])
                self._show_port_props(path, auto_open_chain=True)
            else:
                self._show_port_props(path, auto_open_chain=will_chain)
            self.rte_panel.show_port(path)
        elif kind == "swc":
            swc = self._model.swc_types.get(path)
            if not swc:
                return
            if swc.kind == "COMPOSITION":
                self._nav_stack = []
                self._select_composition(path, push=False)
            else:
                self._select_swc_type(path)
                self.rte_panel.show_swc(path)

    def _graph_node_meta_port(self, node_id: str) -> str:
        for view in (self.graph, self.graph_chain_view):
            g = getattr(view, "_graph", None)
            if not g:
                continue
            for n in g.nodes:
                if n.id == node_id:
                    return (n.meta or {}).get("port_path") or ""
        return ""

    def _active_chain_model(self) -> Optional[ArxmlModel]:
        if self._chain_model_source == "peer_file" and self._peer_model:
            return self._peer_model
        return self._model

    def _peer_lookup_for_menu(self, port_path: str):
        if not self._model or not port_path:
            return []
        peers = self._model.find_port_peers(
            port_path,
            chain=self._current_chain(),
            peer_model=self._peer_model,
        )
        return [(p.port_path, p.label, p.source) for p in peers]

    def open_peer_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open peer ARXML (对照)", "", "ARXML (*.arxml);;All (*.*)"
        )
        if path:
            self._load_peer_path(path, quiet=False)

    def _load_peer_path(self, path: str, *, quiet: bool = False):
        self.status.showMessage(f"解析对照文件 {path}…")
        self.progress.show()
        QApplication.processEvents()
        try:
            peer = ArxmlParser(progress=lambda m: self.status.showMessage(m)).parse(
                path
            )
        except Exception as e:
            self.progress.hide()
            QMessageBox.warning(self, "对照文件", str(e))
            return
        self.progress.hide()
        self._peer_model = peer
        self._peer_undo.clear()
        self._settings.setValue("last_peer", path)
        self.status.showMessage(
            f"对照文件已加载: {os.path.basename(path)}  "
            f"(Ports={len(peer.ports)} Assemblies={len(peer.assemblies)})  "
            f"|  {format_model_scale(peer)}"
        )
        if not quiet:
            QMessageBox.information(
                self,
                "对照文件",
                f"已加载对照 ARXML:\n{path}\n\n"
                "右键端口 /「对端列表」可匹配跨文件 P↔R。",
            )

    def clear_peer_file(self):
        self._peer_model = None
        self._peer_undo.clear()
        if self._chain_model_source == "peer_file":
            self._chain_model_source = "primary"
        self._settings.setValue("last_peer", "")
        self.status.showMessage("已清除对照文件")

    def save_peer_arxml_file(self):
        if not self._peer_model:
            QMessageBox.information(self, "Save peer", "未加载对照文件。")
            return
        if not self._peer_model.is_dirty():
            QMessageBox.information(self, "Save peer", "对照文件没有待保存的修改。")
            return
        warn = ""
        if self._model and self._model.is_dirty():
            warn = (
                "\n\n⚠ 主文件也有未保存修改；两侧 pending 可能冲突，"
                "建议先分清改动再分别 Save / Save peer。"
            )
        ans = QMessageBox.question(
            self,
            "Save peer ARXML",
            f"覆盖写入对照文件？\n{self._peer_model.filepath}\n会生成 .bak 备份。{warn}",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        ok, msg = save_arxml(self._peer_model, make_backup=True)
        if ok:
            QMessageBox.information(self, "Save peer", msg)
            self.status.showMessage(msg.split("\n")[0])
        else:
            QMessageBox.warning(self, "Save peer", msg)

    def swap_peer_as_primary(self):
        """P2: edit symmetry — open peer as the editable primary file."""
        if not self._peer_model or not self._peer_model.filepath:
            QMessageBox.information(self, "Swap peer", "请先加载对照文件。")
            return
        peer_fp = self._peer_model.filepath
        old_primary = self._model.filepath if self._model else ""
        if self._model and self._model.is_dirty():
            ans = QMessageBox.question(
                self,
                "Swap peer",
                "当前主文件有未保存修改，切换后内存修改会丢失（除非先 Save）。\n继续？",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.load_file(peer_fp)
        # After load completes async — remember to re-attach old primary as peer
        self._pending_peer_after_load = old_primary

    def _maybe_attach_pending_peer(self):
        fp = getattr(self, "_pending_peer_after_load", "") or ""
        self._pending_peer_after_load = ""
        if fp and os.path.isfile(fp):
            self._load_peer_path(fp, quiet=True)

    def show_peer_list(self):
        if not self._model:
            return
        port_path = self._trace_port or (
            self._last_sel_path if self._last_sel_kind == "port" else ""
        )
        if not port_path or port_path not in self._model.ports:
            QMessageBox.information(self, "对端", "请先选择一个 Port。")
            return
        peers = self._model.find_port_peers(
            port_path,
            chain=self._current_chain(),
            peer_model=self._peer_model,
        )
        dlg = PeerListDialog(
            self._model,
            port_path,
            peers,
            chain=self._current_chain(),
            peer_model=self._peer_model,
            parent=self,
        )
        dlg.jump_to.connect(self._navigate_to_port)
        dlg.open_star_view.connect(self._open_peer_star_for)
        dlg.exec()

    def _open_peer_star_for(self, port_path: str):
        if not port_path or not self._model or port_path not in self._model.ports:
            return
        self._peer_star_port = port_path
        self._trace_port = port_path
        self._last_sel_path = port_path
        self._last_sel_kind = "port"
        self._set_view_kind("peers")

    def jump_chain_peer(self):
        """One-click: prefer true P↔R; else chain other end; else same-dir Delegation."""
        if not self._model:
            return
        port_path = self._trace_port or (
            self._last_sel_path if self._last_sel_kind == "port" else ""
        )
        if not port_path:
            QMessageBox.information(self, "对端", "请先选择 Port 或打开链路。")
            return
        peers = self._model.find_port_peers(
            port_path,
            chain=self._current_chain(),
            peer_model=self._peer_model,
        )
        if not peers:
            QMessageBox.information(
                self,
                "对端",
                "未找到 P↔R 对端。\n"
                "可 File→Open peer ARXML 加载对照文件，或在「对端列表」里选委托同向端/链路另一端。",
            )
            return
        # Prefer true opposite-direction peers
        order = {
            "assembly": 0,
            "direction_pair": 1,
            "cross_file": 2,
            "chain_end": 3,
            "delegation": 4,
        }
        peers = sorted(peers, key=lambda p: order.get(p.relation, 9))
        top = peers[0]
        if top.relation in ("delegation", "chain_end"):
            self.status.showMessage(
                f"无 Assembly/_P↔_R 对端，改为跳转「{top.relation}」：{top.label}"
            )
        self._navigate_to_port(top.port_path, top.source)

    def _port_ids_on_graphs(self, port_path: str) -> list[str]:
        ids: list[str] = []
        for view in (self.graph_chain_view, self.graph):
            g = getattr(view, "_graph", None)
            if not g or not view.isVisible():
                continue
            for n in g.nodes:
                if (
                    (n.meta or {}).get("port_path") == port_path
                    or n.id == port_path
                    or n.id == f"outer::{port_path}"
                ):
                    ids.append(n.id)
        return ids

    def _highlight_port_on_graphs(self, port_path: str) -> bool:
        ids = self._port_ids_on_graphs(port_path)
        if not ids:
            return False
        for view in (self.graph_chain_view, self.graph):
            if not view.isVisible():
                continue
            view_ids = [
                i
                for i in ids
                if i in getattr(view, "_node_items", {})
            ]
            if view_ids:
                view.highlight_node(view_ids[0])
                view.focus_on(view_ids)
                return True
        return False

    def _port_on_current_chain(self, port_path: str) -> bool:
        chain = self._current_chain()
        if not chain:
            return False
        if port_path == chain.start_port or port_path in (chain.endpoints or []):
            return True
        return any(
            port_path in (h.from_port, h.to_port) for h in chain.hops
        )

    def _navigate_to_port(self, port_path: str, source: str = "primary"):
        """Jump to a peer port (primary or peer_file)."""
        if not port_path:
            return
        source = source or "primary"
        if source == "peer_file":
            if not self._peer_model:
                QMessageBox.information(
                    self, "对端", "对照文件未加载。请 File → Open peer ARXML。"
                )
                return
            port = self._peer_model.ports.get(port_path)
            if not port:
                QMessageBox.information(self, "对端", f"对照文件中无此端口:\n{port_path}")
                return
            self._chain_model_source = "peer_file"
            self._trace_port = port_path
            self._chains = self._peer_model.trace_sr_port(port_path)
            self._chain_index = 0
            self._populate_chain_combo()
            self._fill_sr_chain_table(self._current_chain())
            self._set_view_kind("chain")
            chain = self._current_chain()
            if chain:
                g = build_sr_chain_graph(self._peer_model, chain)
                self.graph.set_graph(g)
            self._set_detail(
                [
                    "Kind: 对照文件 Port（P↔R 对端）",
                    f"File: {self._peer_model.filepath}",
                    f"Direction: {port.direction}",
                    f"Name: {port.name}",
                    f"Path: {port_path}",
                    f"Owner: {port.owner_path}",
                    f"Interface: {port.interface_ref}",
                    f"Chains: {len(self._chains)}",
                    "",
                    "当前链路图来自对照文件（只读浏览）。编辑仍针对主文件。",
                ]
            )
            self.status.showMessage(
                f"对照 P↔R 对端：{port.direction}-{port.name} @ "
                f"{self._peer_model.resolve_name(port.owner_path)}"
            )
            return

        if not self._model:
            return
        self._chain_model_source = "primary"
        port = self._model.ports.get(port_path)
        if not port:
            QMessageBox.information(self, "对端", f"端口不存在:\n{port_path}")
            return
        self._last_sel_path = port_path
        self._last_sel_kind = "port"

        # Already on current chain diagram → only highlight, do NOT re-trace/rebuild
        # (re-trace was destroying the nested chain view — main bug)
        if self._port_on_current_chain(port_path) or self._port_ids_on_graphs(port_path):
            self._highlight_port_on_graphs(port_path)
            self._show_port_props(
                port_path, auto_open_chain=False, update_chain=False
            )
            self.status.showMessage(
                f"已定位：{port.direction}-{port.name} @ "
                f"{self._model.resolve_name(port.owner_path)}"
            )
            return

        # Not on current graph — open its own chain
        self._show_port_props(port_path, auto_open_chain=True, update_chain=True)
        self._highlight_port_on_graphs(port_path)
        self.status.showMessage(
            f"已打开链路：{port.direction}-{port.name} @ "
            f"{self._model.resolve_name(port.owner_path)}"
        )

    def _on_graph_node(self, node_id: str, kind: str):
        filt = node_id
        meta_port = self._graph_node_meta_port(node_id)
        if node_id.startswith("outer::"):
            filt = node_id.replace("outer::", "", 1)
        elif node_id.startswith("swctype::"):
            filt = node_id.replace("swctype::", "", 1)
        elif node_id.startswith("nested::"):
            parts = node_id.split("::", 2)
            filt = parts[1] if len(parts) >= 2 else node_id
        elif node_id.startswith("moreport::") or node_id.startswith("outer-more::"):
            filt = ""
        elif meta_port:
            filt = meta_port
        self.tables.set_selection_filter(filt)
        if kind in ("proto_swc", "proto_comp"):
            if node_id.startswith("swctype::"):
                self._show_swc_props(node_id.replace("swctype::", "", 1))
            else:
                self._show_prototype_props(node_id)
        elif kind == "chain_port":
            # 对端图折叠占位：点击展开该对端全链
            if self._view_mode == "peers" and self.graph._graph:
                for n in self.graph._graph.nodes:
                    if n.id != node_id:
                        continue
                    meta = n.meta or {}
                    if meta.get("peer_star_expandable"):
                        idx = meta.get("peer_star_index")
                        if idx is not None:
                            self._peer_star_expand.add(int(idx))
                            self._reload_graph()
                            self.status.showMessage(
                                f"已展开对端 #{int(idx) + 1} 嵌套链路"
                            )
                            return
                    break
            if meta_port:
                self._show_port_props(meta_port, auto_open_chain=False)
        elif kind == "sr_port":
            if node_id.startswith("moreport::"):
                self._set_detail(["还有更多端口未全部画出；可在左侧树中展开查看全部。"])
            elif meta_port:
                # In chain view: refresh only; in structure/swc: open nested chain if hops
                auto = self._view_mode != "chain"
                self._show_port_props(meta_port, auto_open_chain=auto)
            else:
                auto = self._view_mode != "chain"
                self._show_port_props(node_id, auto_open_chain=auto)
        elif kind == "nested_child":
            node = None
            if self.graph._graph:
                for n in self.graph._graph.nodes:
                    if n.id == node_id:
                        node = n
                        break
            if node and node.type_ref:
                if node.type_kind == "COMPOSITION":
                    self._set_detail(
                        [
                            "Kind: nested COMPOSITION preview",
                            f"Name: {node.label}",
                            f"Type: {node.type_ref}",
                            "双击进入该 Composition 内部",
                        ]
                    )
                else:
                    self._show_swc_props(node.type_ref)
        elif kind == "outer_port":
            if node_id.startswith("outer-more::"):
                self._set_detail(["外框还有更多端口；取消勾选无关过滤或在左树 Outer Ports 中查看。"])
            elif meta_port:
                auto = self._view_mode != "chain"
                self._show_port_props(meta_port, auto_open_chain=auto)
            else:
                auto = self._view_mode != "chain"
                self._show_port_props(
                    node_id.replace("outer::", "", 1), auto_open_chain=auto
                )
        elif kind == "runnable":
            if node_id.startswith("runnable-more::"):
                self._set_detail(
                    [
                        "更多 Runnable / Access 未全部画出。",
                        "可取消 Limit ports 或在左树 Internal Behavior 下查看。",
                    ]
                )
            elif node_id.startswith("runnable::"):
                rpath = node_id.replace("runnable::", "", 1)
                self._show_runnable_props(rpath)
            else:
                # type_ref may hold runnable path
                node = None
                if self.graph._graph:
                    for n in self.graph._graph.nodes:
                        if n.id == node_id:
                            node = n
                            break
                rpath = (node.meta or {}).get("runnable_path") if node else ""
                if rpath:
                    self._show_runnable_props(rpath)
        elif kind == "frame":
            if self._view_mode in ("chain", "peers"):
                return
            if self._view_mode == "swc" and self._current_swc:
                self._show_swc_props(self._current_swc)
            elif self._current_comp:
                self._show_composition_props(self._current_comp)

    def _on_graph_edge(self, edge_id: str, kind: str):
        self.graph.highlight_edge(edge_id)
        if kind in ("access_send", "access_recv", "access_other"):
            meta = {}
            if self.graph._graph:
                for e in self.graph._graph.edges:
                    if e.id == edge_id:
                        meta = e.meta or {}
                        break
            rpath = meta.get("runnable_path") or ""
            ppath = meta.get("port_ref") or ""
            lines = [
                f"Kind: RTE Port Access ({kind})",
                f"Label: {meta.get('access_kind') or kind}",
                f"Runnable: {self._model.resolve_name(rpath) if rpath and self._model else rpath}",
                f"Port: {self._model.resolve_name(ppath) if ppath and self._model else ppath}",
            ]
            if meta.get("data_element"):
                lines.append(f"DataElement/Op: {meta['data_element']}")
            html_parts = []
            if rpath:
                html_parts.append(
                    self._link_html(
                        "runnable",
                        rpath,
                        f"→ Runnable {self._model.resolve_name(rpath) if self._model else rpath}",
                    )
                )
            if ppath:
                html_parts.append(
                    self._link_html(
                        "port",
                        ppath,
                        f"→ Port {self._model.resolve_name(ppath) if self._model else ppath}",
                    )
                )
            self._set_detail(
                lines,
                html_extra="<br/>".join(html_parts) if html_parts else "",
            )
            nodes = []
            for ref in (rpath, ppath):
                nid = self.graph.resolve_node_id(ref)
                if nid:
                    nodes.append(nid)
            self.graph.highlight_connection(edge_id, nodes, focus=True)
            return
        # Chain-view edges may use synthetic ids; prefer meta
        if self._view_mode == "chain" and self.graph._graph:
            for e in self.graph._graph.edges:
                if e.id == edge_id:
                    real = e.meta.get("connector_path") or edge_id
                    self._show_connector_props(real, e.kind)
                    # select matching hop in table
                    for r in range(self.sr_table.rowCount()):
                        it = self.sr_table.item(r, 0)
                        if it and (it.data(Qt.ItemDataRole.UserRole + 1) or "") == real:
                            self.sr_table.selectRow(r)
                            break
                    return
        self._show_connector_props(edge_id, kind)

    def _on_table_row(self, conn_id: str, kind: str, focus_ref: str = ""):
        node_ids: list[str] = []
        if self._model and kind == "assembly":
            for a in self._model.assemblies:
                if (a.path or a.name) != conn_id:
                    continue
                for ref in (
                    a.provider_port_ref,
                    a.requester_port_ref,
                    a.provider_proto_ref,
                    a.requester_proto_ref,
                ):
                    nid = self.graph.resolve_node_id(ref)
                    if nid:
                        node_ids.append(nid)
                break
        elif self._model and kind == "delegation":
            for d in self._model.delegations:
                if (d.path or d.name) != conn_id:
                    continue
                for ref in (d.outer_port_ref, d.inner_port_ref, d.inner_proto_ref):
                    nid = self.graph.resolve_node_id(ref)
                    if nid:
                        node_ids.append(nid)
                break

        if focus_ref:
            nid = self.graph.resolve_node_id(focus_ref)
            if nid:
                # Put clicked port/proto first so it stays in focus set
                node_ids = [nid] + [x for x in node_ids if x != nid]

        # Prefer matching edge id; also try by name if path mismatch
        edge_id = conn_id
        if edge_id not in getattr(self.graph, "_edge_items", {}):
            for eid in self.graph._edge_items:
                if eid == conn_id or eid.endswith("/" + conn_id.split("/")[-1]):
                    edge_id = eid
                    break

        self.graph.highlight_connection(edge_id, node_ids, focus=True)
        self._show_connector_props(conn_id, kind)
        if focus_ref:
            port = self._model.ports.get(focus_ref) if self._model else None
            if port:
                self.status.showMessage(
                    f"定位: {port.direction}-PORT {port.name}  ({kind} {conn_id.split('/')[-1]})"
                )
            else:
                self.status.showMessage(f"定位连接: {conn_id.split('/')[-1]}")
        else:
            self.status.showMessage(f"高亮 {kind}: {conn_id.split('/')[-1]}")

    def _jump_href(self, kind: str, path: str) -> str:
        return f"arxmljump://x?kind={quote(kind, safe='')}&path={quote(path or '', safe='')}"

    def _link_html(self, kind: str, path: str, label: str) -> str:
        return (
            f'<a href="{self._jump_href(kind, path)}">'
            f"{_html_esc(label)}</a>"
        )

    def _set_detail(self, lines: list[str], *, html_extra: str = ""):
        body = _html_esc("\n".join(lines)).replace("\n", "<br/>")
        extra = f"<div style='margin-top:8px'>{html_extra}</div>" if html_extra else ""
        self.detail.setHtml(
            "<div style='font-family:Consolas,monospace;font-size:12px;line-height:1.35'>"
            f"{body}{extra}</div>"
        )

    def _on_detail_link(self, url: QUrl):
        if url.scheme() != "arxmljump":
            return
        q = parse_qs(url.query())
        kind = (q.get("kind") or [""])[0]
        path = unquote((q.get("path") or [""])[0])
        if not path or not self._model:
            return
        if kind == "port" and path in self._model.ports:
            self._pending_focus = [path]
            owner = self._model.ports[path].owner_path
            if owner and owner in self._model.swc_types:
                self._select_swc_type(owner)
            self._show_port_props(path, auto_open_chain=False, update_chain=False)
            nid = self.graph.resolve_node_id(path)
            if nid:
                self.graph.highlight_connection(None, [nid], focus=True)
            self.status.showMessage(f"跳转 Port: {self._model.resolve_name(path)}")
        elif kind == "runnable" and path in self._model.runnables:
            self._show_runnable_props(path)
            nid = self.graph.resolve_node_id(path)
            if nid:
                self.graph.highlight_connection(None, [nid], focus=True)
            self.status.showMessage(
                f"跳转 Runnable: {self._model.resolve_name(path)}"
            )
        elif kind == "adt" and path in self._model.adts:
            self._show_adt_props(path)
            self.status.showMessage(f"跳转 ADT: {self._model.resolve_name(path)}")
        elif kind == "idt" and path in self._model.idts:
            self._show_idt_props(path)
            self.status.showMessage(f"跳转 IDT: {self._model.resolve_name(path)}")

    def _connected_ports_without_access(self, swc_path: str) -> list:
        """Application SWC ports that have connectors but no Runnable PortAccess."""
        if not self._model:
            return []
        out = []
        swc = self._model.swc_types.get(swc_path)
        if not swc or swc.kind != "APPLICATION":
            return out
        behs = self._model.behaviors_of_swc(swc_path)
        if not behs or all(b.is_empty for b in behs):
            return out
        for port in swc.ports:
            if not (
                self._model.assemblies_by_port.get(port.path)
                or self._model.delegations_by_port.get(port.path)
            ):
                continue
            if self._model.accesses_by_port.get(port.path):
                continue
            out.append(port)
        return out

    def _access_summary_lines(self, swc_path: str) -> list[str]:
        if not self._model or not swc_path:
            return []
        n_acc = 0
        for beh in self._model.behaviors_of_swc(swc_path):
            for r in beh.runnables:
                n_acc += len(r.accesses)
        missing = self._connected_ports_without_access(swc_path)
        lines = [
            f"Access 摘要: Access 条数={n_acc} / "
            f"已连接但未 Access 的 Port={len(missing)}"
        ]
        for p in missing[:12]:
            lines.append(f"  · 未 Access: {p.direction}-{p.name}")
        if len(missing) > 12:
            lines.append(f"  … +{len(missing) - 12} more")
        return lines

    def _show_composition_props(self, path: str):
        swc = self._model.swc_types.get(path)
        if not swc:
            return
        self._set_detail(
            [
                f"Kind: COMPOSITION",
                f"Name: {swc.name}",
                f"Path: {path}",
                f"Prototypes: {len(swc.prototypes)}",
                f"Outer ports: {len(swc.ports)}",
                f"Assembly connectors: {len(swc.assemblies)}",
                f"Delegation connectors: {len(swc.delegations)}",
            ]
        )
        self._chains = []
        self._trace_port = ""
        self.cmb_chain.clear()
        self.sr_table.setRowCount(0)

    def _show_prototype_props(self, path: str):
        proto = self._model.prototypes.get(path)
        if not proto:
            return
        t = self._model.swc_types.get(proto.type_ref)
        lines = [
            "Kind: PROTOTYPE",
            f"Name: {proto.name}",
            f"Path: {path}",
            f"Composition: {proto.composition_path}",
            f"TYPE-TREF: {proto.type_ref}",
            f"DEST: {proto.type_dest}",
        ]
        if t:
            lines += [f"Type kind: {t.kind}", f"Type ports: {len(t.ports)}"]
        asm = self._model.assemblies_touching(path)
        lines.append(f"Assemblies touching: {len(asm)}")
        self._set_detail(lines)
        self._fill_sr_from_assemblies(asm)

    def _show_port_props(
        self,
        path: str,
        auto_open_chain: bool = False,
        *,
        update_chain: bool = True,
    ):
        port = self._model.ports.get(path)
        if not port:
            # Peer-file port clicked on 对端图
            if self._peer_model and path in self._peer_model.ports:
                pp = self._peer_model.ports[path]
                self._set_detail(
                    [
                        f"Kind: {pp.direction}-PORT ({pp.iface_kind})  [对照文件]",
                        f"Name: {pp.name}",
                        f"Path: {path}",
                        f"Owner: {pp.owner_path}",
                        f"Interface: {pp.interface_ref}",
                        f"File: {self._peer_model.filepath or ''}",
                        "",
                        "此 Port 在对照文件中；可用「跳转 P↔R 对端」或 Open peer 后定位。",
                    ]
                )
            return
        self._peer_star_port = path
        iface = self._model.interface_of_port(path)
        cs_iface = self._model.cs_interface_of_port(path)
        # Keep existing chain when only highlighting a peer already on the diagram
        if update_chain:
            chains = self._model.trace_sr_port(path)
        else:
            chains = list(self._chains) if self._chains else self._model.trace_sr_port(path)
        total_hops = sum(len(c.hops) for c in chains)
        lines = [
            f"Kind: {port.direction}-PORT ({port.iface_kind})",
            f"Name: {port.name}",
            f"Path: {path}",
            f"Owner: {port.owner_path}",
            f"Interface: {port.interface_ref}",
            f"Interface DEST: {port.interface_dest}",
            f"Chains: {len(chains)}  (total hops: {total_hops})",
        ]
        if port.iface_kind == "CS" and cs_iface:
            lines.append(f"CS Operations ({len(cs_iface.operations)}):")
            for op in cs_iface.operations[:40]:
                args = f"({', '.join(op.arguments)})" if op.arguments else ""
                lines.append(f"  - {op.name}{args}")
            if len(cs_iface.operations) > 40:
                lines.append(f"  … +{len(cs_iface.operations) - 40} more")
        type_html_parts: list[str] = []
        if iface:
            lines.append(f"Data elements ({len(iface.data_elements)}):")
            type_summary_bits = []
            for de in iface.data_elements[:40]:
                type_n = self._model.resolve_name(de.type_ref) if de.type_ref else "?"
                adt = self._model.adts.get(de.type_ref) if de.type_ref else None
                extra = f" [{adt.kind}]" if adt else ""
                jump_kind = ""
                if adt:
                    jump_kind = "adt"
                elif de.type_ref and de.type_ref in self._model.idts:
                    extra = " [IDT]"
                    jump_kind = "idt"
                lines.append(f"  - {de.name} : {type_n}{extra}")
                type_summary_bits.append(f"{de.name}:{type_n}")
                if jump_kind and de.type_ref:
                    type_html_parts.append(
                        self._link_html(
                            jump_kind,
                            de.type_ref,
                            f"{de.name} → {type_n}{extra}",
                        )
                    )
            if len(iface.data_elements) > 40:
                lines.append(f"  … +{len(iface.data_elements) - 40} more")
            if type_summary_bits:
                lines.append("Types: " + ", ".join(type_summary_bits[:12]))
                if len(type_summary_bits) > 12:
                    lines.append(f"  … +{len(type_summary_bits) - 12} more types")
        accesses = self._model.accesses_by_port.get(path, [])
        runnables = self._model.runnables_accessing_port(path)
        lines.append(f"RTE Accesses: {len(accesses)}  (Runnables: {len(runnables)})")
        if not accesses:
            lines.append("  (0 — 空壳 IB 或无 VARIABLE-ACCESS 指向此 Port)")
        access_html_parts = []
        for acc in accesses[:30]:
            r = self._model.runnables.get(acc.runnable_path)
            r_n = r.name if r else self._model.resolve_name(acc.runnable_path)
            kind_u = (acc.access_kind or "?").upper()
            if kind_u in ("RECEIVE", "RECV"):
                tag, arrow = "RECV", "←"
            elif kind_u in ("SEND", "SERVER-CALL"):
                tag = "SEND" if kind_u == "SEND" else "CALL"
                arrow = "→"
            else:
                tag, arrow = kind_u[:8], "·"
            tgt = acc.data_element_ref or acc.operation_ref
            de_n = self._model.resolve_name(tgt) if tgt else ""
            de_part = f" {arrow} {de_n}" if de_n else ""
            lines.append(f"  - {tag} by {r_n}{de_part}")
            if acc.runnable_path:
                access_html_parts.append(
                    self._link_html(
                        "runnable",
                        acc.runnable_path,
                        f"{tag} by {r_n}{de_part}",
                    )
                )
        if len(accesses) > 30:
            lines.append(f"  … +{len(accesses) - 30} more")
        if port.owner_path:
            lines.extend(self._access_summary_lines(port.owner_path))
        maps = self._model.mappings_by_port.get(path, [])
        lines.append(f"System Data Mappings: {len(maps)}")
        for dm in maps[:20]:
            lines.append(
                f"  - {dm.name} → {self._model.resolve_name(dm.signal_ref) or dm.signal_ref}"
            )
        if not maps:
            lines.append("  (当前文件无 Port↔Signal 映射，或未解析到)")
        peers = self._model.find_port_peers(
            path, chain=self._current_chain(), peer_model=self._peer_model
        )
        pr = [p for p in peers if p.relation in ("assembly", "direction_pair", "cross_file")]
        dels = [p for p in peers if p.relation == "delegation"]
        ends = [p for p in peers if p.relation == "chain_end"]
        lines.append("")
        lines.append(f"① 本侧方向: {port.direction}-PORT ({port.iface_kind})")
        lines.append(f"② 真正 P↔R 对端 ({len(pr)}):")
        if pr:
            for peer in pr[:8]:
                lines.append(f"  - [{peer.relation}] {peer.label}")
        else:
            lines.append("  (无；可 Open peer ARXML / 查 Assembly / 同名 _P↔_R)")
        lines.append(f"③ 委托同向端 ({len(dels)}) ※非收发:")
        for peer in dels[:6]:
            lines.append(f"  - {peer.label}")
        if not dels:
            lines.append("  (无)")
        lines.append(f"④ 链路另一端 ({len(ends)}) ※同向连通:")
        for peer in ends[:4]:
            lines.append(f"  - {peer.label}")
        if not ends:
            lines.append("  (无 / 未打开链路)")
        # Cross-file half-chain (primary hops + peer P↔R)
        xhops = build_cross_file_chain(self._model, path, self._peer_model)
        lines.extend(format_cross_chain(xhops))
        # Chain direction summary
        if chains and any(c.hops for c in chains):
            ch = chains[0]
            dirs = [hop_dir_label(self._model, h) for h in ch.hops]
            has_flip = any("→" in d and d[0] != d[-1] for d in dirs)
            lines.append(
                "链路方向: "
                + " · ".join(dirs[:12])
                + ((" …" if len(dirs) > 12 else ""))
                + (
                    "  ✓含 P↔R 翻转"
                    if has_flip
                    else "  ⚠仅同向透传，无 Assembly 收发翻转"
                )
            )
        lines.append("")
        lines.append(
            "下方跳数表含「方向」列；双击定位。Ctrl+Shift+P 对端列表。"
        )
        html_chunks = []
        if type_html_parts:
            html_chunks.append(
                "<b>点击跳转 DataType:</b><br/>" + "<br/>".join(type_html_parts)
            )
        if access_html_parts:
            html_chunks.append(
                "<b>点击跳转 Runnable:</b><br/>" + "<br/>".join(access_html_parts)
            )
        self._set_detail(lines, html_extra="<br/><br/>".join(html_chunks))
        if update_chain:
            self._trace_port_chains(path, auto_open_chain=auto_open_chain)
        self.rte_panel.show_port(path)

    def _show_swc_props(self, path: str):
        swc = self._model.swc_types.get(path)
        if not swc:
            return
        behaviors = self._model.behaviors_of_swc(path)
        lines = [
            f"Kind: {swc.kind}",
            f"Name: {swc.name}",
            f"Path: {path}",
            f"Ports: {len(swc.ports)} "
            f"(SR={sum(1 for p in swc.ports if p.iface_kind=='SR')} "
            f"CS={sum(1 for p in swc.ports if p.iface_kind=='CS')})",
        ]
        if behaviors:
            empty_n = sum(1 for b in behaviors if b.is_empty)
            n_r = sum(len(b.runnables) for b in behaviors)
            n_e = sum(len(b.events) for b in behaviors)
            lines.append(f"Internal Behaviors: {len(behaviors)} (empty stubs: {empty_n})")
            lines.append(f"Runnables: {n_r}  Events: {n_e}")
            if empty_n == len(behaviors):
                lines.append("提示: 导出中 IB 无有效 SHORT-NAME/REF，RTE 映射不可用。")
            if swc.kind == "APPLICATION":
                lines.extend(self._access_summary_lines(path))
        else:
            lines.append("Internal Behaviors: 0")
        lines += [
            "",
            "点击图上 Port 可追踪 Assembly/Delegation 全链路（SR/CS 通用）。",
            "右侧 RTE 表展示 Event→Runnable→Port Access。",
            "SWC 类型图勾选 Show RTE Access 可看 Runnable→Port 边。",
        ]
        self._set_detail(lines)
        self.rte_panel.show_swc(path)
        # keep existing chain if same owner; otherwise clear
        if self._trace_port:
            p = self._model.ports.get(self._trace_port)
            if not p or p.owner_path != path:
                self._chains = []
                self._trace_port = ""
                self.cmb_chain.clear()
                self.sr_table.setRowCount(0)
        else:
            self.sr_table.setRowCount(0)

    def _show_behavior_props(self, path: str):
        beh = None
        for blist in self._model.behaviors_by_swc.values():
            for b in blist:
                if b.path == path:
                    beh = b
                    break
            if beh:
                break
        if not beh:
            return
        lines = [
            "Kind: SWC-INTERNAL-BEHAVIOR",
            f"Name: {beh.name}",
            f"Path: {path}",
            f"Owner SWC: {beh.owner_swc}",
            f"Runnables: {len(beh.runnables)}",
            f"Events: {len(beh.events)}",
            f"Empty stub: {beh.is_empty}",
        ]
        if beh.is_empty:
            lines.append("提示: 导出中 IB 无有效 SHORT-NAME/REF。")
        self._set_detail(lines)
        owner = beh.owner_swc
        if owner and owner in self._model.swc_types:
            self._select_swc_type(owner)
        self.rte_panel.show_behavior(path)

    def _show_runnable_props(self, path: str):
        r = self._model.runnables.get(path)
        if not r:
            return
        lines = [
            "Kind: RUNNABLE-ENTITY",
            f"Name: {r.name}",
            f"Path: {path}",
            f"Symbol: {r.symbol or '(none)'}",
            f"Owner SWC: {r.owner_swc}",
            f"Triggered by events: {len(r.triggered_by)}",
        ]
        for ep in r.triggered_by:
            ev = self._model.rte_events.get(ep)
            if ev:
                lines.append(f"  - [{ev.kind}] {ev.name}" + (f" period={ev.period}" if ev.period else ""))
            else:
                lines.append(f"  - {ep}")
        lines.append(f"Port accesses: {len(r.accesses)}")
        access_html_parts = []
        for a in r.accesses[:40]:
            port_n = self._model.resolve_name(a.port_ref) if a.port_ref else "?"
            tgt = a.data_element_ref or a.operation_ref
            tgt_n = self._model.resolve_name(tgt) if tgt else ""
            kind_u = (a.access_kind or "?").upper()
            if kind_u in ("RECEIVE", "RECV"):
                tag = "RECV"
            elif kind_u == "SERVER-CALL":
                tag = "CALL"
            elif kind_u == "SEND":
                tag = "SEND"
            else:
                tag = kind_u[:8]
            de = f".{tgt_n}" if tgt_n else ""
            lines.append(f"  - {tag} {port_n}{de}")
            if a.port_ref:
                access_html_parts.append(
                    self._link_html("port", a.port_ref, f"{tag} {port_n}{de}")
                )
        if len(r.accesses) > 40:
            lines.append(f"  … +{len(r.accesses) - 40} more")
        if r.owner_swc:
            lines.extend(self._access_summary_lines(r.owner_swc))
        html_extra = ""
        if access_html_parts:
            html_extra = (
                "<b>点击跳转 Port:</b><br/>" + "<br/>".join(access_html_parts)
            )
        self._set_detail(lines, html_extra=html_extra)
        if r.owner_swc and r.owner_swc in self._model.swc_types:
            self._select_swc_type(r.owner_swc)
            nid = self.graph.resolve_node_id(path)
            if nid:
                self.graph.highlight_connection(None, [nid], focus=True)
        self.rte_panel.show_runnable(path)

    def _show_rte_event_props(self, path: str):
        ev = self._model.rte_events.get(path)
        if not ev:
            return
        run_n = (
            self._model.resolve_name(ev.start_on_runnable_ref)
            if ev.start_on_runnable_ref
            else "(none)"
        )
        lines = [
            f"Kind: RTE-EVENT ({ev.kind})",
            f"Name: {ev.name}",
            f"Path: {path}",
            f"Period: {ev.period or '-'}",
            f"Offset: {ev.offset or '-'}",
            f"START-ON-EVENT → {run_n}",
            f"Owner SWC: {ev.owner_swc}",
        ]
        self._set_detail(lines)
        if ev.owner_swc and ev.owner_swc in self._model.swc_types:
            self._select_swc_type(ev.owner_swc)
        if ev.start_on_runnable_ref and ev.start_on_runnable_ref in self._model.runnables:
            self.rte_panel.show_runnable(ev.start_on_runnable_ref)
        elif ev.behavior_path:
            self.rte_panel.show_behavior(ev.behavior_path)

    def _show_data_mapping_props(self, path: str):
        dm = next((x for x in self._model.data_mappings if x.path == path), None)
        if not dm:
            return
        lines = [
            f"Kind: {dm.kind}",
            f"Name: {dm.name}",
            f"Path: {path}",
            f"SYSTEM-MAPPING: {dm.mapping_set_path or '-'}",
            f"Component: {dm.component_ref or '-'}",
            f"Port: {dm.port_ref or '-'}",
            f"DataElement: {dm.data_element_ref or '-'}",
            f"Signal: {dm.signal_ref or '-'}",
        ]
        self._set_detail(lines)

    def _show_adt_props(self, path: str):
        adt = self._model.adts.get(path)
        if not adt:
            return
        lines = [
            f"Kind: APPLICATION-{adt.kind}-DATA-TYPE",
            f"Name: {adt.name}",
            f"Path: {path}",
            f"Category: {adt.category or '-'}",
        ]
        if adt.compu_method_ref:
            lines.append(f"CompuMethod: {adt.compu_method_ref}")
        if adt.data_constr_ref:
            lines.append(f"DataConstr: {adt.data_constr_ref}")
        idt = self._model.mapped_idt_of_adt(path)
        if idt:
            lines.append(f"Mapped IDT: {idt.name}  ({idt.path})")
            if idt.base_type_ref:
                lines.append(f"  BaseType: {idt.base_type_ref}")
        else:
            lines.append("Mapped IDT: (none)")
        if adt.kind == "RECORD":
            lines.append(f"Elements ({len(adt.elements)}):")
            for el in adt.elements[:80]:
                tn = self._model.resolve_name(el.type_ref) if el.type_ref else "?"
                lines.append(f"  - {el.name} : {tn}")
            if len(adt.elements) > 80:
                lines.append(f"  … +{len(adt.elements) - 80} more")
        elif adt.kind == "ARRAY":
            tn = (
                self._model.resolve_name(adt.element_type_ref)
                if adt.element_type_ref
                else "?"
            )
            lines.append(f"Element type: {tn}")
            lines.append(f"Array size: {adt.array_size or '-'} ({adt.array_size_semantics or ''})")
        self._set_detail(lines)

    def _show_adt_element_props(self, path: str):
        for adt in self._model.adts.values():
            for el in adt.elements:
                if el.path == path or (not el.path and False):
                    lines = [
                        "Kind: APPLICATION-RECORD-ELEMENT",
                        f"Name: {el.name}",
                        f"Path: {el.path}",
                        f"Owner ADT: {adt.name} ({adt.path})",
                        f"TYPE-TREF: {el.type_ref}",
                        f"DEST: {el.type_dest}",
                    ]
                    child = self._model.adts.get(el.type_ref)
                    if child:
                        lines.append(f"Resolved ADT kind: {child.kind}")
                    self._set_detail(lines)
                    return
        # fallback: path may be owner ADT
        self._show_adt_props(path)

    def _show_idt_props(self, path: str):
        idt = self._model.idts.get(path)
        if not idt:
            return
        lines = [
            "Kind: IMPLEMENTATION-DATA-TYPE",
            f"Name: {idt.name}",
            f"Path: {path}",
            f"Category: {idt.category or '-'}",
            f"BaseType: {idt.base_type_ref or '-'}",
        ]
        if idt.base_type_ref and idt.base_type_ref in self._model.base_types:
            bt = self._model.base_types[idt.base_type_ref]
            lines.append(
                f"  native={bt.native_declaration or '-'}  "
                f"size={bt.size or '-'}  encoding={bt.encoding or '-'}"
            )
        adt = self._model.mapped_adt_of_idt(path)
        if adt:
            lines.append(f"Mapped ADT: {adt.name} ({adt.kind})  {adt.path}")
        else:
            lines.append("Mapped ADT: (none)")
        self._set_detail(lines)

    def _show_base_type_props(self, path: str):
        bt = self._model.base_types.get(path)
        if not bt:
            return
        users = [i for i in self._model.idts.values() if i.base_type_ref == path]
        lines = [
            "Kind: SW-BASE-TYPE",
            f"Name: {bt.name}",
            f"Path: {path}",
            f"Category: {bt.category or '-'}",
            f"Size: {bt.size or '-'}",
            f"Encoding: {bt.encoding or '-'}",
            f"Native: {bt.native_declaration or '-'}",
            f"Used by IDTs: {len(users)}",
        ]
        for i in users[:30]:
            lines.append(f"  - {i.name}")
        if len(users) > 30:
            lines.append(f"  … +{len(users) - 30} more")
        self._set_detail(lines)

    def _show_connector_props(self, conn_id: str, kind: str):
        if not self._model:
            return
        if kind == "assembly":
            for a in self._model.assemblies:
                if (a.path or a.name) == conn_id:
                    iface = ""
                    p = self._model.ports.get(a.provider_port_ref)
                    if p and p.interface_ref in self._model.interfaces:
                        iface = self._model.interfaces[p.interface_ref].name
                        des = [
                            de.name
                            for de in self._model.interfaces[p.interface_ref].data_elements
                        ]
                    else:
                        des = []
                    self._set_detail(
                        [
                            "Kind: ASSEMBLY-SW-CONNECTOR",
                            f"Name: {a.name}",
                            f"Path: {a.path}",
                            f"Composition: {a.composition_path}",
                            f"Provider proto: {a.provider_proto_ref}",
                            f"Provider port: {a.provider_port_ref}",
                            f"Requester proto: {a.requester_proto_ref}",
                            f"Requester port: {a.requester_port_ref}",
                            f"Interface: {iface}",
                            f"DataElements: {', '.join(des[:20])}",
                        ]
                    )
                    self._fill_sr_from_assemblies([a])
                    return
        else:
            for d in self._model.delegations:
                if (d.path or d.name) == conn_id:
                    self._set_detail(
                        [
                            "Kind: DELEGATION-SW-CONNECTOR",
                            f"Name: {d.name}",
                            f"Path: {d.path}",
                            f"Composition: {d.composition_path}",
                            f"Outer port: {d.outer_port_ref}",
                            f"Inner proto: {d.inner_proto_ref}",
                            f"Inner port: {d.inner_port_ref}",
                            f"Direction: {d.inner_direction}",
                        ]
                    )
                    self.sr_table.setRowCount(0)
                    return

    def _fill_sr_from_assemblies(self, assemblies):
        """Show assemblies as single-hop rows in the chain table (legacy helper)."""
        if not self._model:
            return
        hops = []
        for a in assemblies:
            iface = ""
            p = self._model.ports.get(a.provider_port_ref)
            if p and p.interface_ref in self._model.interfaces:
                iface = self._model.interfaces[p.interface_ref].name
            hops.append(
                SrHop(
                    kind="assembly",
                    connector_name=a.name,
                    connector_path=a.path,
                    composition_path=a.composition_path,
                    from_port=a.provider_port_ref,
                    from_proto=a.provider_proto_ref,
                    to_port=a.requester_port_ref,
                    to_proto=a.requester_proto_ref,
                    interface=iface,
                )
            )
        chain = SrChain(start_port="", hops=hops)
        self._chains = [chain] if hops else []
        self._chain_index = 0
        self._populate_chain_combo()
        self._fill_sr_chain_table(chain if hops else None)

    def find_path(self):
        if not self._model:
            return
        dlg = FindDialog(self._model, self)
        dlg.jump_to.connect(self._jump_to)
        dlg.exec()

    def run_consistency_check(self):
        if not self._model:
            QMessageBox.information(self, "检查", "请先打开 ARXML。")
            return
        dlg = CheckDialog(
            self._model,
            self,
            peer_model=self._peer_model,
            os_rte=self._os_rte,
        )
        dlg.jump_to.connect(self._jump_to)
        dlg.about_to_fix.connect(self._on_about_to_consistency_fix)
        dlg.fixes_applied.connect(self._on_fixes_applied)
        dlg.exec()

    def _load_os_rte_for_model(self, model: ArxmlModel):
        path = default_os_rte_path(model.filepath or "")
        ov, err = load_os_rte(path)
        if err:
            self.status.showMessage(f"OS/RTE Mapping: {err}")
            ov = empty_overlay(path)
        self._os_rte = ov or empty_overlay(path)
        if path and not self._os_rte.source_path:
            self._os_rte.source_path = path
        self.tree.set_os_rte(self._os_rte)
        if self._os_rte_dlg is not None:
            try:
                panel = self._os_rte_dlg.findChild(OsRtePanel)
                if panel:
                    panel.set_context(self._model, self._os_rte)
            except RuntimeError:
                self._os_rte_dlg = None
        n_t = len(self._os_rte.tasks)
        n_m = len(self._os_rte.mappings)
        if n_t or n_m:
            self.status.showMessage(
                self.status.currentMessage()
                + f"  |  OsRTE Tasks={n_t} Maps={n_m}"
            )

    def _on_os_rte_changed(self):
        self.tree.set_os_rte(self._os_rte)
        dirty = " *" if self._os_rte.dirty else ""
        self.status.showMessage(
            f"OS/RTE Mapping 已修改{dirty} — File → Save OS/RTE Mapping"
        )

    def show_os_rte_mapping(self):
        if not self._model:
            QMessageBox.information(self, "OS/RTE", "请先打开 ARXML。")
            return
        from PySide6.QtWidgets import QDialog as _QDialog

        if self._os_rte_dlg is not None:
            try:
                self._os_rte_dlg.raise_()
                self._os_rte_dlg.activateWindow()
                return
            except RuntimeError:
                self._os_rte_dlg = None
        dlg = _QDialog(self)
        dlg.setWindowTitle("OS/RTE Mapping（侧车）")
        dlg.resize(900, 520)
        lay = QVBoxLayout(dlg)
        panel = OsRtePanel(dlg)
        panel.set_context(self._model, self._os_rte)
        panel.changed.connect(self._on_os_rte_changed)
        panel.save_requested.connect(self.save_os_rte_mapping)
        panel.jump_to.connect(self._jump_to)
        lay.addWidget(panel)
        self._os_rte_dlg = dlg
        dlg.show()

    def open_os_rte_mapping(self):
        if not self._model:
            QMessageBox.information(self, "OS/RTE", "请先打开 ARXML。")
            return
        start = self._os_rte.source_path or default_os_rte_path(
            self._model.filepath or ""
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open OS/RTE Mapping",
            start or "",
            "OS/RTE JSON (*.os_rte.json *.json);;All (*.*)",
        )
        if not path:
            return
        ov, err = load_os_rte(path)
        if err or ov is None:
            QMessageBox.warning(self, "OS/RTE", err or "加载失败")
            return
        self._os_rte = ov
        self.tree.set_os_rte(self._os_rte)
        if self._os_rte_dlg is not None:
            try:
                panel = self._os_rte_dlg.findChild(OsRtePanel)
                if panel:
                    panel.set_context(self._model, self._os_rte)
            except RuntimeError:
                pass
        self.status.showMessage(
            f"已加载 OS/RTE Mapping: {path}  "
            f"Tasks={len(ov.tasks)} Maps={len(ov.mappings)}"
        )
        self.show_os_rte_mapping()

    def save_os_rte_mapping(self):
        if not self._model:
            QMessageBox.information(self, "OS/RTE", "请先打开 ARXML。")
            return
        path = self._os_rte.source_path or default_os_rte_path(
            self._model.filepath or ""
        )
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save OS/RTE Mapping",
                "",
                "OS/RTE JSON (*.os_rte.json);;JSON (*.json)",
            )
            if not path:
                return
            if not path.endswith(".json"):
                path += ".os_rte.json"
        err = save_os_rte(path, self._os_rte)
        if err:
            QMessageBox.warning(self, "OS/RTE", err)
            return
        self.tree.set_os_rte(self._os_rte)
        if self._os_rte_dlg is not None:
            try:
                panel = self._os_rte_dlg.findChild(OsRtePanel)
                if panel:
                    panel.refresh()
            except RuntimeError:
                pass
        self.status.showMessage(f"已保存 OS/RTE Mapping: {path}")

    def import_os_rte_csv_file(self):
        if not self._model:
            QMessageBox.information(self, "OS/RTE", "请先打开 ARXML。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import OS/RTE CSV",
            "",
            "CSV (*.csv);;All (*.*)",
        )
        if not path:
            return
        ov, msg = import_os_rte_csv(path, self._os_rte)
        self._os_rte = ov
        self.tree.set_os_rte(self._os_rte)
        if self._os_rte_dlg is not None:
            try:
                panel = self._os_rte_dlg.findChild(OsRtePanel)
                if panel:
                    panel.set_context(self._model, self._os_rte)
            except RuntimeError:
                pass
        QMessageBox.information(self, "Import CSV", msg)
        self.status.showMessage(msg)

    def export_os_rte_csv_file(self):
        if not self._model:
            QMessageBox.information(self, "OS/RTE", "请先打开 ARXML。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export OS/RTE CSV",
            "os_rte_mapping.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        err = export_os_rte_csv(path, self._os_rte)
        if err:
            QMessageBox.warning(self, "Export CSV", err)
        else:
            QMessageBox.information(self, "Export CSV", f"已导出:\n{path}")

    def generate_rte_skeleton_files(self):
        if not self._model:
            QMessageBox.information(self, "RTE", "请先打开 ARXML。")
            return
        if not self._os_rte.tasks:
            QMessageBox.information(
                self,
                "RTE",
                "侧车尚无 OS Task。请先 Tools → OS/RTE Mapping 配置，或导入 CSV。",
            )
            return
        start = ""
        if self._model.filepath:
            start = os.path.join(
                os.path.dirname(self._model.filepath), "rte_skeleton"
            )
        out_dir = QFileDialog.getExistingDirectory(
            self, "选择 RTE 骨架输出目录", start or ""
        )
        if not out_dir:
            return
        written, err = generate_rte_skeleton(
            self._model, self._os_rte, out_dir
        )
        if err:
            QMessageBox.warning(self, "RTE skeleton", err)
            return
        QMessageBox.information(
            self,
            "RTE skeleton",
            "已生成最小骨架（非完整 DaVinci RTE）:\n"
            + "\n".join(written[:12])
            + (f"\n… 共 {len(written)} 个文件" if len(written) > 12 else ""),
        )
        self.status.showMessage(f"RTE skeleton → {out_dir} ({len(written)} files)")

    def _show_os_task_props(self, task_name: str):
        task = self._os_rte.get_task(task_name) if self._os_rte else None
        if not task:
            self._set_detail([f"未知 OS Task: {task_name}"])
            return
        maps = self._os_rte.mappings_by_task(task_name)
        lines = [
            "Kind: OS-TASK (overlay)",
            f"Name: {task.name}",
            f"Priority: {task.priority}",
            f"Schedule: {task.schedule}",
            f"Type: {task.type}",
            f"Mappings: {len(maps)}",
            f"Sidecar: {self._os_rte.source_path or '(unsaved)'}",
        ]
        html_parts = []
        for m in maps[:40]:
            proto_n = (
                self._model.resolve_name(m.swc_prototype) if self._model else m.swc_prototype
            )
            run_n = (
                self._model.resolve_name(m.runnable) if self._model else m.runnable
            )
            lines.append(f"  [{m.position}] {proto_n}.{run_n}")
            if m.runnable:
                html_parts.append(
                    self._link_html(
                        "runnable",
                        m.runnable,
                        f"[{m.position}] {proto_n}.{run_n}",
                    )
                )
        if len(maps) > 40:
            lines.append(f"  … +{len(maps) - 40} more")
        html_extra = ""
        if html_parts:
            html_extra = (
                "<b>点击跳转 Runnable:</b><br/>" + "<br/>".join(html_parts)
            )
        self._set_detail(lines, html_extra=html_extra)

    def _on_validate_on_open_toggled(self, checked: bool):
        self._validate_on_open = bool(checked)
        self._settings.setValue("validate_on_open", self._validate_on_open)
        if not checked:
            self._validate_defer_timer.stop()

    def cancel_spec_validate(self):
        self._validate_defer_timer.stop()
        if self._validate_worker and self._validate_worker.isRunning():
            self._validate_worker.cancel()
            self.status.showMessage("已请求取消规范校验…")
        else:
            self.status.showMessage("当前无进行中的规范校验")

    def run_spec_validate_scoped(self):
        scope = ""
        if self._view_mode == "swc" and self._current_swc:
            scope = self._current_swc
        elif self._current_comp:
            scope = self._current_comp
        elif self._last_sel_path:
            scope = self._last_sel_path
        if not scope:
            QMessageBox.information(
                self, "规范校验", "请先打开 Composition 或选中 SWC。"
            )
            return
        self.run_spec_validate(
            force_dialog=True, include_pending=False, scope_prefix=scope
        )

    def run_spec_validate(
        self,
        *,
        force_dialog: bool = True,
        include_pending: bool = False,
        scope_prefix: str = "",
    ):
        if not self._model or not self._model.filepath:
            QMessageBox.information(self, "规范校验", "请先打开 ARXML。")
            return
        if include_pending and not self._model.is_dirty():
            QMessageBox.information(
                self,
                "规范校验",
                "当前没有未保存修改，将按磁盘文件校验。",
            )
            include_pending = False
        if self._validate_worker and self._validate_worker.isRunning():
            self.status.showMessage("规范校验进行中…（可 File→Cancel validation）")
            return
        mode = "含 pending" if include_pending else "磁盘文件"
        if scope_prefix:
            mode += f" · scope={self._model.resolve_name(scope_prefix)}"
        self.status.showMessage(f"AUTOSAR 规范校验中（XSD + 语义 + N:M · {mode}）…")
        pend = self._model if include_pending else None
        self._validate_worker = SpecValidateWorker(
            self._model.filepath,
            include_pending_model=pend,
            scope_prefix=scope_prefix,
        )
        self._validate_worker.progress.connect(
            lambda m: self.status.showMessage(m.replace("\n", " ").strip()[:160])
        )
        self._validate_worker.finished_ok.connect(
            lambda r: self._on_spec_validated(r, force_dialog=force_dialog)
        )
        self._validate_worker.failed.connect(
            lambda e: QMessageBox.warning(self, "规范校验", e)
        )
        self._validate_worker.start()

    def _on_spec_validated(self, result: SpecValidateResult, *, force_dialog: bool):
        self._last_spec_result = result
        msg = f"规范校验 {result.summary}"
        self.status.showMessage(msg)
        show = force_dialog or (
            self._auto_show_spec_dialog and (not result.ok or result.warnings)
        )
        # Always pop if errors; for open-time warnings ask once lightly
        if not force_dialog and result.ok and not result.warnings:
            return
        if not force_dialog and result.ok and result.warnings:
            ans = QMessageBox.question(
                self,
                "规范校验",
                f"{msg}\n\n有 {len(result.warnings)} 条警告，是否查看详情？",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            show = True
        if show or not result.ok:
            dlg = SpecValidateDialog(result, self, model=self._model)
            dlg.jump_to.connect(self._jump_to)
            dlg.jump_source.connect(self._jump_to_source_line)
            dlg.exec()

    def undo_last_edit(self):
        if not self._model:
            return
        label = self._undo.undo(self._model)
        if not label:
            QMessageBox.information(self, "Undo", "没有可撤销的编辑。")
            return
        if self._current_comp:
            self.tables.set_composition(self._current_comp)
            self.tables.refresh()
        self.tree.set_model(self._model)
        self._reload_graph()
        self._update_title()
        self.status.showMessage(f"已撤销: {label}")

    def redo_last_edit(self):
        if not self._model:
            return
        label = self._undo.redo(self._model)
        if not label:
            QMessageBox.information(self, "Redo", "没有可重做的编辑。")
            return
        if self._current_comp:
            self.tables.set_composition(self._current_comp)
            self.tables.refresh()
        self.tree.set_model(self._model)
        self._reload_graph()
        self._update_title()
        self.status.showMessage(f"已重做: {label}")

    def undo_peer_edit(self):
        if not self._peer_model:
            QMessageBox.information(self, "Undo peer", "未加载对照文件。")
            return
        label = self._peer_undo.undo(self._peer_model)
        if not label:
            QMessageBox.information(self, "Undo peer", "对照文件没有可撤销的编辑。")
            return
        self._update_title()
        self.status.showMessage(f"已撤销对照: {label}（需 Save peer 写回）")

    def redo_peer_edit(self):
        if not self._peer_model:
            QMessageBox.information(self, "Redo peer", "未加载对照文件。")
            return
        label = self._peer_undo.redo(self._peer_model)
        if not label:
            QMessageBox.information(self, "Redo peer", "对照文件没有可重做的编辑。")
            return
        self._update_title()
        self.status.showMessage(f"已重做对照: {label}（需 Save peer 写回）")

    def _checkpoint(self, label: str):
        if self._model:
            self._undo.push(self._model, label)

    def _checkpoint_peer(self, label: str):
        if self._peer_model:
            self._peer_undo.push(self._peer_model, label)

    def _on_about_to_consistency_fix(self, n: int, target: str):
        if n <= 0:
            return
        if target in ("peer",):
            self._checkpoint_peer(f"consistency fix ×{n}")
        elif target == "mixed":
            self._checkpoint(f"consistency fix ×{n}")
            self._checkpoint_peer(f"consistency fix ×{n}")
        else:
            self._checkpoint(f"consistency fix ×{n}")

    def _on_fixes_applied(self, n: int):
        if n <= 0:
            return
        if self._current_comp:
            self.tables.set_composition(self._current_comp)
            self.tables.refresh()
        self._reload_graph()
        self._update_title()
        self.status.showMessage(f"已应用 {n} 处修复（需 Save / Save peer 写回）")

    def _jump_to(self, path: str, kind: str):
        if not path or not self._model:
            return
        # Prefer selecting known model objects (respect explicit kind when unique)
        if kind == "runnable" and path in self._model.runnables:
            pass
        elif kind == "os_task" and self._os_rte and self._os_rte.get_task(path):
            pass
        elif path in self._model.ports:
            kind = "port"
        elif path in self._model.runnables:
            kind = "runnable"
        elif path in self._model.prototypes:
            kind = "prototype"
        elif path in self._model.swc_types:
            swc = self._model.swc_types[path]
            kind = "composition" if swc.kind == "COMPOSITION" else "swc"
        self._on_tree_select(path, kind)
        self.status.showMessage(f"定位: {kind} {self._model.resolve_name(path)}")

    def _jump_to_source_line(self, filepath: str, line: int):
        """Show source context around an XSD line and offer to open the file."""
        if not filepath or not os.path.isfile(filepath) or line <= 0:
            return
        try:
            with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            QMessageBox.warning(self, "定位源行", str(e))
            return
        i0 = max(0, line - 4)
        i1 = min(len(lines), line + 3)
        snippet = []
        for i in range(i0, i1):
            mark = ">>" if i + 1 == line else "  "
            snippet.append(f"{mark}{i + 1:6d}| {lines[i].rstrip()}")
        text = "\n".join(snippet) if snippet else f"(行 {line} 超出文件范围)"
        self.status.showMessage(f"源文件 L{line}: {(lines[line - 1].strip() if line <= len(lines) else '')[:120]}")
        ans = QMessageBox.question(
            self,
            f"源文件 L{line}",
            f"{filepath}\n\n{text}\n\n是否用系统默认程序打开该文件？",
        )
        if ans == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(filepath))

    def _on_connect_mode(self):
        on = self.chk_connect.isChecked()
        self.graph.connect_mode = on
        # Keep structure view: chain auto-open would interrupt drag-connect
        if on and self._view_mode == "chain" and not self.chk_split.isChecked():
            self._set_view_kind("struct")
        self.graph.setCursor(
            Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor
        )
        self.status.showMessage(
            "连线模式开：按住 Port 拖到另一 Port（不会跳转链路图；仍可用 Shift+拖）"
            if on
            else "连线模式关（仍可用 Shift+拖）"
        )

    def _on_connect_ports(self, from_id: str, to_id: str):
        if not self._model or not self.graph._graph:
            return
        comp = self._current_comp
        if not comp or self._view_mode == "swc":
            QMessageBox.information(
                self,
                "拖线建连",
                "请在 Composition 结构图中操作（打开含 Prototype 的 Composition）。",
            )
            return
        # Cross-file connect is not supported (primary graph only)
        if self._chain_model_source == "peer_file":
            QMessageBox.information(
                self,
                "拖线建连",
                "当前为对照链路视图，无法跨文件创建连接。\n"
                "请回到主文件 Composition 结构图连线。",
            )
            return
        plan, err = plan_connection(
            self._model, self.graph._graph, comp, from_id, to_id
        )
        if err or not plan:
            QMessageBox.warning(self, "拖线建连", err or "无法创建连接")
            return
        msg = f"创建 {plan.kind}: {plan.suggested_name}？"
        if plan.warning:
            msg += f"\n警告: {plan.warning}"
        ans = QMessageBox.question(self, "拖线建连", msg)
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._checkpoint(f"connect {plan.kind} {plan.suggested_name}")
        if plan.kind == "assembly":
            e = self._model.queue_add_assembly(
                comp,
                plan.suggested_name,
                plan.provider_proto,
                plan.provider_port,
                plan.requester_proto,
                plan.requester_port,
            )
        else:
            e = self._model.queue_add_delegation(
                comp,
                plan.suggested_name,
                plan.outer_port,
                plan.inner_proto,
                plan.inner_port,
            )
        if e:
            QMessageBox.warning(self, "拖线建连", e)
            return
        self.tables.set_composition(comp)
        self.tables.refresh()
        self._reload_graph()
        self._update_title()
        path = f"{comp}/Connectors/{plan.suggested_name}"
        self.graph.highlight_connection(path, None, focus=True)
        keep = " · 连线模式仍开，可继续拖" if self.chk_connect.isChecked() else ""
        self.status.showMessage(
            f"已新增 {plan.kind}「{plan.suggested_name}」（需 Save）{keep}"
        )
        # Keep connect mode armed (do not clear checkbox)
        if self.chk_connect.isChecked():
            self.graph.connect_mode = True
            self.graph.setCursor(Qt.CursorShape.CrossCursor)

    def rename_selected_object(self):
        """Rename Port / ADT / IDT / SR-IF / Runnable / Event."""
        if not self._model:
            return
        # Prefer last tree selection stored
        kind = getattr(self, "_last_sel_kind", "") or ""
        path = getattr(self, "_last_sel_path", "") or ""
        kind_map = {
            "port": "port",
            "adt": "adt",
            "idt": "idt",
            "sr_interface": "sr_interface",
            "runnable": "runnable",
            "rte_event": "rte_event",
        }
        ek = kind_map.get(kind)
        if not ek or not path:
            QMessageBox.information(
                self,
                "重命名",
                "请先在左树选中 Port / ADT / IDT / SR Interface / Runnable / Event。",
            )
            return
        cur = self._model.resolve_name(path)
        new_name, ok = QInputDialog.getText(
            self, "重命名", f"新 SHORT-NAME（当前: {cur}）:", text=cur
        )
        if not ok or not new_name.strip() or new_name.strip() == cur:
            return
        self._checkpoint(f"rename {ek} {cur}")
        err = self._model.queue_rename_element(ek, path, new_name.strip())
        if err:
            QMessageBox.warning(self, "重命名", err)
            return
        self.tree.set_model(self._model)
        self._reload_graph()
        self._update_title()
        self.status.showMessage(
            f"已重命名 {ek}: {cur} → {new_name.strip()}（需 Save；REF 将同步改写）"
        )

    def _refresh_after_edit(self, msg: str):
        self.tree.set_model(self._model)
        self.rte_panel.set_model(self._model)
        self.tables.refresh()
        self._reload_graph()
        self._update_title()
        self.status.showMessage(msg)

    def batch_add_delegated_outer_ports(self):
        """Batch-create outer _DG ports + Delegation for unconnected inner ports."""
        if not self._model:
            return
        comp = self._current_comp
        if not comp:
            QMessageBox.information(
                self, "批量委托", "请先打开一个 Composition 结构图。"
            )
            return
        swc = self._model.swc_types.get(comp)
        if not swc or swc.kind != "COMPOSITION":
            QMessageBox.information(self, "批量委托", "当前不是 Composition。")
            return
        candidates = []
        for proto in swc.prototypes:
            t = self._model.swc_types.get(proto.type_ref)
            if not t:
                continue
            for p in t.ports:
                if p.iface_kind not in ("SR", "CS", ""):
                    continue
                # already has delegation from this composition?
                has = False
                for d in self._model.delegations_by_comp.get(comp, []):
                    if d.inner_port_ref == p.path and d.inner_proto_ref == proto.path:
                        has = True
                        break
                if not has:
                    candidates.append((proto, p))
        if not candidates:
            QMessageBox.information(
                self, "批量委托", "没有需要补委托的内口（均已有 Delegation）。"
            )
            return
        preview = BatchDelegatePreviewDialog(self._model, comp, candidates, self)
        if preview.exec() != preview.DialogCode.Accepted:
            return
        selected = preview.selected_candidates(candidates)
        if not selected:
            return
        self._checkpoint(f"batch delegated outer ×{len(selected)}")
        ok_n = 0
        errs = []
        for proto, port in selected:
            err = self._model.queue_add_delegated_outer_port(
                comp, proto.path, port.path, ""
            )
            if err:
                errs.append(f"{proto.name}.{port.name}: {err}")
            else:
                ok_n += 1
        self.tables.set_composition(comp)
        self._refresh_after_edit(
            f"批量委托完成: 成功 {ok_n}/{len(selected)}（需 Save）"
        )
        if errs:
            QMessageBox.warning(
                self,
                "批量委托",
                f"成功 {ok_n}，失败 {len(errs)}：\n" + "\n".join(errs[:15]),
            )

    def create_system_mapping_stub(self):
        if not self._model:
            return
        if self._model.system_mapping_sets:
            QMessageBox.information(
                self,
                "SYSTEM stub",
                "已有 SYSTEM-MAPPING：\n"
                + "\n".join(self._model.system_mapping_sets[:8]),
            )
            return
        sys_name, ok = QInputDialog.getText(
            self, "SYSTEM stub", "SYSTEM SHORT-NAME:", text="System"
        )
        if not ok or not sys_name.strip():
            return
        map_name, ok = QInputDialog.getText(
            self, "SYSTEM stub", "SYSTEM-MAPPING SHORT-NAME:", text="SystemMapping"
        )
        if not ok or not map_name.strip():
            return
        pkg, ok = QInputDialog.getText(
            self, "SYSTEM stub", "AR-PACKAGE 路径:", text="/System"
        )
        if not ok:
            return
        self._checkpoint("create SYSTEM/Mapping stub")
        err = self._model.queue_add_system_mapping_set(
            sys_name.strip(), map_name.strip(), (pkg or "/System").strip()
        )
        if err:
            QMessageBox.warning(self, "SYSTEM stub", err)
            return
        self._refresh_after_edit(
            f"已创建 SYSTEM/{sys_name} + Mapping/{map_name}（需 Save）"
        )
        QMessageBox.information(
            self,
            "SYSTEM stub",
            "已排队创建 SYSTEM + SYSTEM-MAPPING。\n"
            "Save 后可用 Edit→Add Data Mapping 添加映射。",
        )

    def add_data_mapping(self):
        if not self._model:
            return
        if not self._model.system_mapping_sets:
            QMessageBox.information(
                self,
                "Data Mapping",
                "当前 ARXML 无 SYSTEM-MAPPING（SWC 导出常见）。"
                "可用 testdata/mini_sysmap.arxml 试写回。",
            )
            return
        if not self._model.system_signals and not self._model.i_signals:
            QMessageBox.information(
                self, "Data Mapping", "当前文件没有 SYSTEM-SIGNAL / I-SIGNAL。"
            )
            return
        dlg = AddDataMappingDialog(self._model, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        vals = dlg.result_values()
        if not vals:
            return
        set_path, name, kind, proto, port, de, sig = vals
        self._checkpoint(f"add mapping {name}")
        err = self._model.queue_add_data_mapping(
            set_path,
            name,
            component_ref=proto,
            port_ref=port,
            data_element_ref=de,
            signal_ref=sig,
            mapping_kind=kind,
        )
        if err:
            QMessageBox.warning(self, "Data Mapping", err)
            return
        self._refresh_after_edit(f"已新增 Mapping「{name}」（需 Save 写回）")

    def edit_selected_data_mapping(self):
        if not self._model:
            return
        path = ""
        if self._last_sel_kind == "data_mapping":
            path = self._last_sel_path
        if not path:
            QMessageBox.information(
                self, "Data Mapping", "请先在左树选中一条 Data Mapping。"
            )
            return
        dm = next((x for x in self._model.data_mappings if x.path == path), None)
        if not dm:
            QMessageBox.warning(self, "Data Mapping", "映射不存在。")
            return
        dlg = EditDataMappingDialog(self._model, dm, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        new_name, sig = dlg.result_values()
        self._checkpoint(f"update mapping {dm.name}")
        err = self._model.queue_update_data_mapping(
            path, signal_ref=sig, new_name=new_name
        )
        if err:
            QMessageBox.warning(self, "Data Mapping", err)
            return
        self._refresh_after_edit(f"已更新 Mapping「{dm.name}」（需 Save 写回）")

    def delete_selected_data_mapping(self):
        if not self._model:
            return
        if self._last_sel_kind != "data_mapping" or not self._last_sel_path:
            QMessageBox.information(
                self, "Data Mapping", "请先在左树选中一条 Data Mapping。"
            )
            return
        path = self._last_sel_path
        name = self._model.resolve_name(path)
        ans = QMessageBox.question(
            self, "删除 Mapping", f"删除 Data Mapping「{name}」？"
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._checkpoint(f"delete mapping {name}")
        err = self._model.queue_delete_data_mapping(path)
        if err:
            QMessageBox.warning(self, "Data Mapping", err)
            return
        self._refresh_after_edit(f"已删除 Mapping「{name}」（需 Save 写回）")

    def _preferred_behavior_path(self) -> str:
        kind = self._last_sel_kind
        path = self._last_sel_path
        if kind == "behavior":
            return path
        if kind == "runnable":
            r = self._model.runnables.get(path) if self._model else None
            return r.behavior_path if r else ""
        if kind == "rte_event":
            ev = self._model.rte_events.get(path) if self._model else None
            return ev.behavior_path if ev else ""
        if kind == "swc" and self._model:
            behs = self._model.behaviors_of_swc(path)
            return behs[0].path if behs else ""
        return ""

    def add_runnable(self):
        if not self._model:
            return
        if not self._model.behaviors_by_swc:
            QMessageBox.information(self, "Runnable", "当前文件无 Internal Behavior。")
            return
        dlg = AddRunnableDialog(self._model, self._preferred_behavior_path(), self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        vals = dlg.result_values()
        if not vals:
            return
        beh, name, symbol = vals
        self._checkpoint(f"add runnable {name}")
        err = self._model.queue_add_runnable(beh, name, symbol)
        if err:
            QMessageBox.warning(self, "Runnable", err)
            return
        self._refresh_after_edit(f"已新增 Runnable「{name}」（需 Save 写回）")

    def set_runnable_symbol(self):
        if not self._model:
            return
        path = self._last_sel_path if self._last_sel_kind == "runnable" else ""
        if not path or path not in self._model.runnables:
            QMessageBox.information(self, "Symbol", "请先在左树选中 Runnable。")
            return
        r = self._model.runnables[path]
        new_sym, ok = QInputDialog.getText(
            self, "Runnable Symbol", f"SYMBOL（当前: {r.symbol}）:", text=r.symbol
        )
        if not ok:
            return
        self._checkpoint(f"set symbol {r.name}")
        err = self._model.queue_set_runnable_symbol(path, new_sym.strip())
        if err:
            QMessageBox.warning(self, "Symbol", err)
            return
        self._refresh_after_edit(
            f"已设置 Symbol「{r.name}」→ {new_sym.strip()}（需 Save）"
        )

    def add_timing_event(self):
        if not self._model:
            return
        if not self._model.runnables:
            QMessageBox.information(
                self, "Event", "当前文件无 Runnable（请先新增 Runnable）。"
            )
            return
        dlg = AddTimingEventDialog(self._model, self._preferred_behavior_path(), self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        vals = dlg.result_values()
        if not vals:
            return
        beh, name, run, period, offset = vals
        self._checkpoint(f"add timing event {name}")
        err = self._model.queue_add_timing_event(
            beh, name, run, period=period, offset=offset
        )
        if err:
            QMessageBox.warning(self, "Event", err)
            return
        self._refresh_after_edit(f"已新增 Timing Event「{name}」（需 Save 写回）")

    def add_init_event(self):
        if not self._model or not self._model.runnables:
            QMessageBox.information(self, "Init Event", "请先有 Runnable。")
            return
        dlg = AddTimingEventDialog(self._model, self._preferred_behavior_path(), self)
        dlg.setWindowTitle("新增 Init Event")
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        vals = dlg.result_values()
        if not vals:
            return
        beh, name, run, _period, _offset = vals
        err = self._model.queue_add_init_event(beh, name, run)
        if err:
            QMessageBox.warning(self, "Init Event", err)
            return
        self._refresh_after_edit(f"已新增 Init Event「{name}」（需 Save）")

    def add_data_received_event(self):
        if not self._model or not self._model.runnables:
            QMessageBox.information(self, "DataReceived", "请先有 Runnable。")
            return
        dlg = AddPortAccessDialog(self._model, "", self)
        dlg.setWindowTitle("新增 DataReceived Event（先选 Port/DE，再填 Event 名）")
        # reuse access dialog for port/de; then ask name/runnable
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        vals = dlg.result_values()
        if not vals:
            return
        run, _kind, port, de, _aname = vals
        r = self._model.runnables.get(run)
        if not r:
            return
        name, ok = QInputDialog.getText(
            self,
            "DataReceived Event",
            "Event SHORT-NAME:",
            text=f"Ev_{self._model.resolve_name(port)}_Rx",
        )
        if not ok or not name.strip():
            return
        err = self._model.queue_add_data_received_event(
            r.behavior_path, name.strip(), run, port, de
        )
        if err:
            QMessageBox.warning(self, "DataReceived", err)
            return
        self._refresh_after_edit(f"已新增 DataReceived Event「{name.strip()}」（需 Save）")

    def add_system_signal(self):
        if not self._model:
            return
        name, ok = QInputDialog.getText(self, "SYSTEM-SIGNAL", "SHORT-NAME:")
        if not ok or not name.strip():
            return
        pkg = ""
        if self._model.system_signals:
            sample = next(iter(self._model.system_signals.keys()))
            pkg = sample.rsplit("/", 1)[0]
        err = self._model.queue_add_system_signal(name.strip(), pkg)
        if err:
            QMessageBox.warning(self, "Signal", err)
            return
        self._refresh_after_edit(f"已新增 SYSTEM-SIGNAL「{name.strip()}」（需 Save）")

    def add_port(self):
        if not self._model:
            return
        # pick owner SWC
        owners = list(self._model.application_paths()) + list(
            self._model.composition_paths()
        )
        if not owners:
            QMessageBox.information(self, "Port", "无可用 SWC。")
            return
        labels = [self._model.resolve_name(p) for p in owners]
        default = 0
        if self._last_sel_kind == "swc" and self._last_sel_path in owners:
            default = owners.index(self._last_sel_path)
        elif self._last_sel_kind == "composition" and self._last_sel_path in owners:
            default = owners.index(self._last_sel_path)
        label, ok = QInputDialog.getItem(
            self, "Add Port", "Owner SWC / Composition:", labels, default, False
        )
        if not ok:
            return
        owner = owners[labels.index(label)]
        name, ok = QInputDialog.getText(self, "Add Port", "Port SHORT-NAME:")
        if not ok or not name.strip():
            return
        direction, ok = QInputDialog.getItem(
            self, "Add Port", "Direction:", ["P", "R"], 0, False
        )
        if not ok:
            return
        ifaces = list(self._model.interfaces.keys()) + list(
            self._model.cs_interfaces.keys()
        )
        if not ifaces:
            QMessageBox.information(self, "Port", "无可用 Interface。")
            return
        ilabels = [self._model.resolve_name(p) for p in ifaces]
        ilabel, ok = QInputDialog.getItem(
            self, "Add Port", "Interface:", ilabels, 0, False
        )
        if not ok:
            return
        iface = ifaces[ilabels.index(ilabel)]
        self._checkpoint(f"add port {name.strip()}")
        err = self._model.queue_add_port(owner, name.strip(), direction, iface)
        if err:
            QMessageBox.warning(self, "Port", err)
            return
        self._refresh_after_edit(
            f"已新增 {direction}-Port「{name.strip()}」（需 Save）"
        )

    def add_delegated_outer_port(self):
        if not self._model:
            return
        comps = self._model.composition_paths()
        if not comps:
            QMessageBox.information(self, "Delegated Outer", "无 Composition。")
            return
        clabels = [self._model.resolve_name(p) for p in comps]
        default = 0
        if self._current_comp in comps:
            default = comps.index(self._current_comp)
        clabel, ok = QInputDialog.getItem(
            self, "Delegated Outer", "Composition:", clabels, default, False
        )
        if not ok:
            return
        comp = comps[clabels.index(clabel)]
        swc = self._model.swc_types.get(comp)
        if not swc or not swc.prototypes:
            QMessageBox.information(self, "Delegated Outer", "该 Composition 无 Prototype。")
            return
        plabels = [p.name for p in swc.prototypes]
        plabel, ok = QInputDialog.getItem(
            self, "Delegated Outer", "Inner Prototype:", plabels, 0, False
        )
        if not ok:
            return
        proto = swc.prototypes[plabels.index(plabel)]
        t = self._model.swc_types.get(proto.type_ref)
        if not t or not t.ports:
            QMessageBox.information(self, "Delegated Outer", "内部类型无 Port。")
            return
        port_labels = [f"{p.direction}-{p.name}" for p in t.ports]
        port_label, ok = QInputDialog.getItem(
            self, "Delegated Outer", "Inner Port:", port_labels, 0, False
        )
        if not ok:
            return
        inner = t.ports[port_labels.index(port_label)]
        outer_name, ok = QInputDialog.getText(
            self,
            "Delegated Outer",
            "Outer Port 名（空则自动 …_DG_P/_R）:",
            text=f"{inner.name}_DG_{inner.direction}",
        )
        if not ok:
            return
        err = self._model.queue_add_delegated_outer_port(
            comp, proto.path, inner.path, outer_name.strip()
        )
        if err:
            QMessageBox.warning(self, "Delegated Outer", err)
            return
        self._refresh_after_edit(
            f"已创建委托外端口 + Delegation（需 Save）"
        )

    def set_event_period(self):
        if not self._model:
            return
        path = self._last_sel_path if self._last_sel_kind == "rte_event" else ""
        ev = self._model.rte_events.get(path) if path else None
        if not ev:
            QMessageBox.information(self, "Period", "请先在左树选中 Event。")
            return
        period, ok = QInputDialog.getText(
            self,
            "Event Period",
            f"PERIOD（秒，当前: {ev.period or '-'}）:",
            text=ev.period or "0.01",
        )
        if not ok or not period.strip():
            return
        err = self._model.queue_set_event_period(path, period.strip())
        if err:
            QMessageBox.warning(self, "Period", err)
            return
        self._refresh_after_edit(
            f"已设置 Period「{ev.name}」→ {period.strip()}（需 Save）"
        )

    def rebind_event_runnable(self):
        if not self._model:
            return
        path = self._last_sel_path if self._last_sel_kind == "rte_event" else ""
        if not path or path not in self._model.rte_events:
            QMessageBox.information(
                self, "Rebind", "请先在左树选中 Event。"
            )
            return
        dlg = RebindEventRunnableDialog(self._model, path, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        run = dlg.result_runnable()
        err = self._model.queue_set_event_runnable(path, run)
        if err:
            QMessageBox.warning(self, "Rebind", err)
            return
        self._refresh_after_edit(
            f"已重绑定 Event → {self._model.resolve_name(run)}（需 Save）"
        )

    def add_port_access(self):
        if not self._model:
            return
        run_path = self._last_sel_path if self._last_sel_kind == "runnable" else ""
        if not self._model.runnables:
            QMessageBox.information(self, "Port Access", "当前文件无 Runnable。")
            return
        dlg = AddPortAccessDialog(self._model, run_path, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        vals = dlg.result_values()
        if not vals:
            return
        run, kind, port, de, name = vals
        err = self._model.queue_add_port_access(
            run, kind, port, de, name=name
        )
        if err:
            QMessageBox.warning(self, "Port Access", err)
            return
        self._refresh_after_edit(
            f"已新增 Port Access「{name or kind}」（需 Save 写回）"
        )

    def delete_selected_ib_object(self):
        if not self._model:
            return
        kind = self._last_sel_kind
        path = self._last_sel_path

        if kind == "rte_event":
            name = self._model.resolve_name(path)
            ans = QMessageBox.question(
                self, "删除 Event", f"删除 Event「{name}」？"
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            err = self._model.queue_delete_rte_event(path)
            if err:
                QMessageBox.warning(self, "删除 IB", err)
                return
            self._refresh_after_edit(f"已删除 Event「{name}」（需 Save 写回）")
            return

        if kind == "runnable":
            r = self._model.runnables.get(path)
            if not r:
                return
            options = [f"Runnable「{r.name}」"]
            access_opts = list(r.accesses)
            for a in access_opts:
                options.append(f"Port Access「{a.name}」({a.access_kind})")
            choice, ok = QInputDialog.getItem(
                self, "删除 IB", "选择要删除的对象:", options, 0, False
            )
            if not ok:
                return
            if choice.startswith("Runnable"):
                ans = QMessageBox.question(
                    self, "删除 Runnable", f"确认删除 Runnable「{r.name}」？"
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return
                err = self._model.queue_delete_runnable(path)
            else:
                idx = options.index(choice) - 1
                acc = access_opts[idx]
                err = self._model.queue_delete_port_access(path, acc.path)
            if err:
                QMessageBox.warning(self, "删除 IB", err)
                return
            self._refresh_after_edit(f"已删除（需 Save 写回）")
            return

        # No tree selection: pick any Port Access globally
        items = []
        for r in self._model.runnables.values():
            for a in r.accesses:
                items.append(
                    (f"{r.name}/{a.name} ({a.access_kind})", r.path, a.path)
                )
        if not items:
            QMessageBox.information(
                self,
                "删除 IB",
                "请先在左树选中 Runnable 或 Event。",
            )
            return
        labels = [x[0] for x in items]
        choice, ok = QInputDialog.getItem(
            self, "删除 Port Access", "选择要删除的 Access:", labels, 0, False
        )
        if not ok:
            return
        _, rpath, apath = items[labels.index(choice)]
        err = self._model.queue_delete_port_access(rpath, apath)
        if err:
            QMessageBox.warning(self, "删除 IB", err)
            return
        self._refresh_after_edit("已删除 Port Access（需 Save 写回）")

    def _show_sr_interface_props(self, path: str):
        iface = self._model.interfaces.get(path)
        if not iface:
            return
        lines = [
            "Kind: SENDER-RECEIVER-INTERFACE",
            f"Name: {iface.name}",
            f"Path: {path}",
            f"Data elements: {len(iface.data_elements)}",
        ]
        for de in iface.data_elements[:60]:
            tn = self._model.resolve_name(de.type_ref) if de.type_ref else "?"
            adt = self._model.adts.get(de.type_ref) if de.type_ref else None
            extra = f" [{adt.kind}]" if adt else ""
            lines.append(f"  - {de.name} : {tn}{extra}")
        if len(iface.data_elements) > 60:
            lines.append(f"  … +{len(iface.data_elements) - 60} more")
        users = [p for p in self._model.ports.values() if p.interface_ref == path]
        lines.append(f"Ports using this IF: {len(users)}")
        for p in users[:20]:
            lines.append(
                f"  - {p.direction} {self._model.resolve_name(p.owner_path)}.{p.name}"
            )
        self._set_detail(lines)

    def _show_sr_data_element_props(self, path: str):
        for iface in self._model.interfaces.values():
            for de in iface.data_elements:
                if de.path == path or (
                    not de.path and False
                ):
                    lines = [
                        "Kind: VARIABLE-DATA-PROTOTYPE",
                        f"Name: {de.name}",
                        f"Path: {de.path}",
                        f"Interface: {iface.name}",
                        f"TYPE-TREF: {de.type_ref}",
                        f"DEST: {de.type_dest}",
                    ]
                    adt = self._model.adts.get(de.type_ref) if de.type_ref else None
                    if adt:
                        lines.append(f"Resolved ADT: {adt.name} ({adt.kind})")
                        idt = self._model.mapped_idt_of_adt(adt.path)
                        if idt:
                            lines.append(f"Mapped IDT: {idt.name}")
                    self._set_detail(lines)
                    return
        # path may be interface
        self._show_sr_interface_props(path)

    def export_csv(self):
        if not self._model or not self._current_comp:
            QMessageBox.information(self, "Export", "Select a composition first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "connectors.csv", "CSV (*.csv)"
        )
        if path:
            self.tables.export_csv(path)
            self.status.showMessage(f"Exported {path}")

    def _resolve_export_swc_path(self) -> str:
        """Best-effort current Application SWC path for export."""
        if not self._model:
            return ""
        if self._current_swc and self._current_swc in self._model.swc_types:
            swc = self._model.swc_types[self._current_swc]
            if swc.kind == "APPLICATION":
                return self._current_swc
        if self._last_sel_kind == "swc" and self._last_sel_path in self._model.swc_types:
            swc = self._model.swc_types[self._last_sel_path]
            if swc.kind == "APPLICATION":
                return self._last_sel_path
        if self._last_sel_kind == "port" and self._last_sel_path in self._model.ports:
            owner = self._model.ports[self._last_sel_path].owner_path
            swc = self._model.swc_types.get(owner)
            if swc and swc.kind == "APPLICATION":
                return owner
        if self._last_sel_kind == "prototype" and self._last_sel_path in self._model.prototypes:
            tref = self._model.prototypes[self._last_sel_path].type_ref
            swc = self._model.swc_types.get(tref)
            if swc and swc.kind == "APPLICATION":
                return tref
        return ""

    def export_swc_arxml(self):
        if not self._model or not self._model.filepath:
            QMessageBox.information(self, "导出 SWC", "请先打开 ARXML。")
            return
        pre = self._resolve_export_swc_path()
        dlg = ExportSwcDialog(self._model, self, preselect_path=pre)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        paths = dlg.selected_swc_paths()
        out_dir = dlg.output_directory()
        if not paths:
            QMessageBox.information(self, "导出 SWC", "请至少选择一个 SWC。")
            return
        if not out_dir:
            QMessageBox.information(self, "导出 SWC", "请指定输出目录。")
            return
        self.status.showMessage(f"导出 {len(paths)} 个 SWC…")
        QApplication.processEvents()
        extras = []
        if dlg.use_peer_closure() and self._peer_model and self._peer_model.filepath:
            extras.append(self._peer_model.filepath)
        results, err = extract_all_swcs(
            self._model.filepath,
            out_dir,
            swc_paths=paths,
            validate_export=dlg.validate_after_export(),
            extra_sources=extras or None,
        )
        if err:
            QMessageBox.warning(self, "导出 SWC", err)
            return
        ok_n = sum(1 for r in results if r.ok)
        lines = [f"成功 {ok_n}/{len(results)} → {out_dir}", ""]
        for r in results:
            if r.ok:
                lines.append(
                    f"✓ {r.swc_name}: {r.element_count} 元素 "
                    f"(依赖 {r.dep_count}) → {os.path.basename(r.output_path)}"
                )
                if r.missing_refs:
                    sample = ", ".join(r.missing_refs[:3])
                    if len(sample) > 80:
                        sample = sample[:80] + "…"
                    lines.append(
                        f"  ⚠ 未解析引用 {len(r.missing_refs)} 个（可能跨文件）: {sample}"
                    )
            else:
                lines.append(f"✗ {r.swc_path}: {r.message}")
        QMessageBox.information(self, "导出 SWC", "\n".join(lines[:40]))
        self.status.showMessage(f"SWC 导出完成: {ok_n}/{len(results)} → {out_dir}")

    def export_current_swc_arxml(self):
        """Export currently selected SWC (or open multi-picker if unclear)."""
        swc_path = self._resolve_export_swc_path()
        if not swc_path:
            self.export_swc_arxml()
            return
        self.export_swc_arxml_one(swc_path)

    def export_current_composition_slice(self):
        if not self._model or not self._model.filepath:
            QMessageBox.information(self, "导出 Composition", "请先打开 ARXML。")
            return
        comp = self._current_comp
        if not comp:
            QMessageBox.information(self, "导出 Composition", "请先打开一个 Composition。")
            return
        swc = self._model.swc_types.get(comp)
        if not swc or swc.kind != "COMPOSITION":
            QMessageBox.information(self, "导出 Composition", "当前不是 Composition。")
            return
        name = self._model.resolve_name(comp)
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"导出 Composition「{name}」",
            f"{name}_composition.arxml",
            "ARXML (*.arxml);;All (*.*)",
        )
        if not path:
            return
        extras = []
        if self._peer_model and self._peer_model.filepath:
            extras.append(self._peer_model.filepath)
        self.status.showMessage(f"导出 Composition {name}…")
        QApplication.processEvents()
        r = extract_composition_to_file(
            self._model.filepath,
            comp,
            path,
            extra_sources=extras or None,
        )
        if r.ok:
            QMessageBox.information(self, "导出 Composition", f"{r.message}\n→ {r.output_path}")
        else:
            QMessageBox.warning(self, "导出 Composition", r.message)
        self.status.showMessage(r.message)

    def export_system_slice(self):
        if not self._model or not self._model.filepath:
            QMessageBox.information(self, "导出 SYSTEM", "请先打开 ARXML。")
            return
        import xml.etree.ElementTree as ET

        try:
            tree = ET.parse(self._model.filepath)
            idx, _ = build_index(tree.getroot())
        except Exception as e:
            QMessageBox.warning(self, "导出 SYSTEM", f"索引失败: {e}")
            return
        rows = list_system_slice_paths(idx)
        # Also include known mapping sets from model
        for p in self._model.system_mapping_sets or []:
            if not any(r[0] == p for r in rows):
                rows.append((p, self._model.resolve_name(p), "SYSTEM-MAPPING"))
        if not rows:
            QMessageBox.information(
                self, "导出 SYSTEM", "文件中未找到 SYSTEM / SYSTEM-MAPPING。"
            )
            return
        labels = [f"{tag}: {name}  ({path})" for path, name, tag in rows]
        label, ok = QInputDialog.getItem(
            self, "导出 SYSTEM 切片", "选择目标:", labels, 0, False
        )
        if not ok:
            return
        path_sel, name, tag = rows[labels.index(label)]
        out, _ = QFileDialog.getSaveFileName(
            self,
            f"导出 {tag}「{name}」",
            f"{name}_{tag.lower()}.arxml",
            "ARXML (*.arxml);;All (*.*)",
        )
        if not out:
            return
        extras = []
        if self._peer_model and self._peer_model.filepath:
            extras.append(self._peer_model.filepath)
        self.status.showMessage(f"导出 {tag} {name}…")
        QApplication.processEvents()
        r = extract_system_slice_to_file(
            self._model.filepath,
            path_sel,
            out,
            extra_sources=extras or None,
        )
        if r.ok:
            QMessageBox.information(self, "导出 SYSTEM", f"{r.message}\n→ {r.output_path}")
        else:
            QMessageBox.warning(self, "导出 SYSTEM", r.message)
        self.status.showMessage(r.message)

    def export_swc_arxml_one(self, swc_path: str):
        """Export a single Application SWC (right-click / shortcut)."""
        if not self._model or not self._model.filepath:
            QMessageBox.information(self, "导出 SWC", "请先打开 ARXML。")
            return
        if not swc_path:
            return
        swc = self._model.swc_types.get(swc_path)
        if swc and swc.kind != "APPLICATION":
            QMessageBox.information(
                self,
                "导出 SWC",
                f"仅支持导出 Application SWC，当前为 {swc.kind}。",
            )
            return
        name = self._model.resolve_name(swc_path)
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"导出 SWC「{name}」ARXML",
            f"{name}.arxml",
            "ARXML (*.arxml);;All (*.*)",
        )
        if not path:
            return
        ans_val = QMessageBox.question(
            self,
            "导出 SWC",
            "导出后是否运行规范校验？\n（大文件较慢；可跳过）",
        )
        do_validate = ans_val == QMessageBox.StandardButton.Yes
        extras = []
        if self._peer_model and self._peer_model.filepath:
            extras.append(self._peer_model.filepath)
        self.status.showMessage(f"导出 {name}…")
        QApplication.processEvents()
        r = extract_swc_to_file(
            self._model.filepath,
            swc_path,
            path,
            write_missing_report=True,
            validate_export=do_validate,
            extra_sources=extras or None,
        )
        if not r.ok:
            QMessageBox.warning(self, "导出 SWC", r.message)
            return
        extra = ""
        if r.missing_refs:
            extra = (
                f"\n\n未解析引用 {len(r.missing_refs)} 个"
                f"（可能跨文件）:\n  " + "\n  ".join(r.missing_refs[:8])
            )
            if r.missing_report_path:
                extra += f"\n清单: {r.missing_report_path}"
        QMessageBox.information(
            self,
            "导出 SWC",
            f"{r.message}\n→ {r.output_path}{extra}",
        )
        self.status.showMessage(r.message)

    def _on_limit_ports_toggled(self):
        on = self.chk_limit_ports.isChecked()
        self._settings.setValue("limit_ports", on)
        # Persist into project config when a file is open
        if self._model and self._model.filepath:
            cfg = load_project_config(self._model.filepath) or ProjectConfig(
                primary=self._model.filepath
            )
            cfg.limit_ports = on
            cfg.primary = self._model.filepath
            if self._peer_model and self._peer_model.filepath:
                cfg.peer = self._peer_model.filepath
            save_project_config(self._model.filepath, cfg)
        self._reload_graph()

    def show_help(self):
        HelpDialog(self).exec()

    def export_pr_orphan_csv(self):
        if not self._model:
            QMessageBox.information(self, "P↔R 报告", "请先打开 ARXML。")
            return
        rows = collect_pr_orphan_rows(self._model, self._peer_model)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export P↔R orphan CSV", "pr_orphans.csv", "CSV (*.csv)"
        )
        if not path:
            return
        import csv

        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["severity", "message", "path"])
            w.writeheader()
            w.writerows(rows)
        QMessageBox.information(
            self, "P↔R 报告", f"已导出 {len(rows)} 行 →\n{path}"
        )
        self.status.showMessage(f"P↔R 报告: {len(rows)} 行")

    def save_project_config_file(self):
        if not self._model or not self._model.filepath:
            QMessageBox.information(self, "工程配置", "请先打开 ARXML。")
            return
        cfg = ProjectConfig(
            primary=self._model.filepath,
            peer=(self._peer_model.filepath if self._peer_model else "") or "",
            validate_on_open=self._validate_on_open,
            limit_ports=self.chk_limit_ports.isChecked(),
            export_dir="",
        )
        path = save_project_config(self._model.filepath, cfg)
        if path.startswith("写入失败"):
            QMessageBox.warning(self, "工程配置", path)
            return
        QMessageBox.information(self, "工程配置", f"已保存:\n{path}")
        self.status.showMessage(f"工程配置已保存: {path}")

    def save_graph_image(self):
        if not self._model or not self.graph._graph:
            QMessageBox.information(self, "Save image", "请先打开 ARXML 并在中图显示内容。")
            return
        if self._view_mode == "chain" and self._trace_port:
            default_name = "sr_chain_" + (self._model.resolve_name(self._trace_port) or "port")
        elif self._view_mode == "swc" and self._current_swc:
            default_name = self._model.resolve_name(self._current_swc) or "swc"
        else:
            default_name = self._model.resolve_name(self._current_comp) or "composition"
        # sanitize filename
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in default_name)[:80]
        path, selected = QFileDialog.getSaveFileName(
            self,
            "Save graph as image",
            f"{safe}.png",
            "PNG (*.png);;JPEG (*.jpg *.jpeg)",
        )
        if not path:
            return
        if selected.startswith("JPEG") and not path.lower().endswith((".jpg", ".jpeg")):
            path += ".jpg"
        elif selected.startswith("PNG") and not path.lower().endswith(".png"):
            path += ".png"
        ok = self.graph.export_image(path, scale=2.0)
        if ok:
            self.status.showMessage(f"已保存图: {path}")
        else:
            QMessageBox.warning(self, "Save image", "保存失败，请检查路径与磁盘空间。")

    def _update_title(self):
        base = "ARXML Composition / Port Viewer"
        if not self._model:
            self.setWindowTitle(base)
            return
        name = os.path.basename(self._model.filepath) if self._model.filepath else ""
        dirty = " *" if self._model.is_dirty() else ""
        self.setWindowTitle(f"{base} — {name}{dirty}" if name else base)

    def _resolve_edit_composition(self, title: str) -> str:
        comp = self._current_comp
        if self._view_mode == "chain":
            mode, path = self._return_view
            if mode == "composition" and path:
                comp = path
        if not comp:
            QMessageBox.information(
                self,
                title,
                "请先在左树打开一个 Composition（中图为该 Composition 结构图）。",
            )
            return ""
        swc = self._model.swc_types.get(comp) if self._model else None
        if not swc or swc.kind != "COMPOSITION":
            QMessageBox.information(self, title, "当前不是有效的 Composition。")
            return ""
        return comp

    def add_assembly_connector(self, prefer_kind: str = "All"):
        if not self._model:
            return
        comp = self._resolve_edit_composition("新增 Assembly")
        if not comp:
            return
        swc = self._model.swc_types[comp]
        if len(swc.prototypes) < 1:
            QMessageBox.information(self, "新增 Assembly", "该 Composition 没有 Prototype。")
            return

        dlg = AddAssemblyDialog(self._model, comp, self, prefer_kind=prefer_kind)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        vals = dlg.result_values()
        if not vals:
            return
        name, p_proto, p_port, r_proto, r_port = vals
        self._checkpoint(f"add assembly {name}")
        err = self._model.queue_add_assembly(comp, name, p_proto, p_port, r_proto, r_port)
        if err:
            QMessageBox.warning(self, "新增 Assembly", err)
            return
        if self._view_mode != "composition" or self._current_comp != comp:
            self._select_composition(comp, push=False)
        else:
            self.tables.set_composition(comp)
            self._reload_graph()
        self.tables.refresh()
        self._update_title()
        self.status.showMessage(f"已新增 Assembly「{name}」（需 File→Save 写回 ARXML）")
        path = f"{comp}/Connectors/{name}"
        self.graph.highlight_connection(path, None, focus=True)

    def add_delegation_connector(self):
        if not self._model:
            return
        comp = self._resolve_edit_composition("新增 Delegation")
        if not comp:
            return
        swc = self._model.swc_types[comp]
        if not swc.ports:
            QMessageBox.information(self, "新增 Delegation", "该 Composition 没有外端口。")
            return
        if not swc.prototypes:
            QMessageBox.information(self, "新增 Delegation", "该 Composition 没有 Prototype。")
            return
        dlg = AddDelegationDialog(self._model, comp, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        vals = dlg.result_values()
        if not vals:
            return
        name, outer, proto, inner = vals
        self._checkpoint(f"add delegation {name}")
        err = self._model.queue_add_delegation(comp, name, outer, proto, inner)
        if err:
            QMessageBox.warning(self, "新增 Delegation", err)
            return
        if self._view_mode != "composition" or self._current_comp != comp:
            self._select_composition(comp, push=False)
        else:
            self.tables.set_composition(comp)
            self._reload_graph()
        self.tables.refresh()
        self.tables.tabs.setCurrentIndex(1)
        self._update_title()
        self.status.showMessage(f"已新增 Delegation「{name}」（需 File→Save 写回 ARXML）")
        path = f"{comp}/Connectors/{name}"
        self.graph.highlight_connection(path, None, focus=True)

    def rename_selected_connector(self):
        if not self._model:
            return
        sel = self.tables.selected_connector()
        if not sel:
            QMessageBox.information(self, "Rename", "请先在底表选中一条 Assembly / Delegation。")
            return
        conn_id, kind, name, comp = sel
        new_name, ok = QInputDialog.getText(
            self, "Rename connector", f"新 SHORT-NAME（当前: {name}）:", text=name
        )
        if not ok or not new_name.strip() or new_name.strip() == name:
            return
        new_name = new_name.strip()
        self._checkpoint(f"rename connector {name}")
        self._model.queue_rename_connector(conn_id, name, comp, kind, new_name)
        self.tables.refresh()
        self._reload_graph()
        self._update_title()
        self.status.showMessage(f"已排队重命名: {name} → {new_name}（需 Save 写回）")

    def delete_selected_connector(self):
        if not self._model:
            return
        sel = self.tables.selected_connector()
        if not sel:
            QMessageBox.information(self, "Delete", "请先在底表选中一条 Assembly / Delegation。")
            return
        conn_id, kind, name, comp = sel
        ans = QMessageBox.question(
            self,
            "Delete connector",
            f"删除 {kind}「{name}」？\n（内存立即生效，需 File→Save 写回 ARXML）",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._checkpoint(f"delete {kind} {name}")
        self._model.queue_delete_connector(conn_id, name, comp, kind)
        self.tables.refresh()
        self._reload_graph()
        self._update_title()
        self.status.showMessage(f"已排队删除: {name}（需 Save 写回）")

    def save_arxml_file(self):
        if not self._model:
            return
        if not self._model.is_dirty():
            QMessageBox.information(self, "Save", "没有待保存的修改。")
            return
        warn = ""
        if self._peer_model and self._peer_model.is_dirty():
            warn = (
                "\n\n⚠ 对照文件也有未保存修改；跨文件 Assembly/Mapping 可能不一致，"
                "请确认后再 Save peer。"
            )
        if self._os_rte and self._os_rte.dirty:
            warn += "\n\n（OsRTE 侧车有未保存修改 → File → Save OS/RTE Mapping）"
        ans = QMessageBox.question(
            self,
            "Save ARXML",
            f"覆盖写入？\n{self._model.filepath}\n会生成 .bak 备份。{warn}",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        ok, msg = save_arxml(self._model, make_backup=True)
        if ok:
            self._update_title()
            QMessageBox.information(self, "Save", msg)
            self.status.showMessage(msg.split("\n")[0])
        else:
            QMessageBox.warning(self, "Save", msg)

    def save_arxml_as(self):
        if not self._model:
            return
        if not self._model.is_dirty():
            QMessageBox.information(self, "Save As", "没有待保存的修改。可先重命名/删除连接器。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save ARXML As",
            self._model.filepath or "export.arxml",
            "ARXML (*.arxml);;All (*.*)",
        )
        if not path:
            return
        ok, msg = save_arxml(self._model, dest_path=path, make_backup=False)
        if ok:
            self.lbl_file.setText(os.path.basename(path))
            self._update_title()
            QMessageBox.information(self, "Save As", msg)
            self.status.showMessage(msg.split("\n")[0])
        else:
            QMessageBox.warning(self, "Save As", msg)
