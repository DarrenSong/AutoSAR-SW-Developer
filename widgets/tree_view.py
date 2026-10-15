# -*- coding: utf-8 -*-
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model import ArxmlModel
from ..os_rte import OsRteOverlay


ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_KIND = Qt.ItemDataRole.UserRole + 1
ROLE_LAZY = Qt.ItemDataRole.UserRole + 10  # lazy payload key


class ModelTree(QWidget):
    """Tree + filter box. Emits selection_path(path, kind)."""

    selection_path = Signal(str, str)
    export_swc_requested = Signal(str)  # Application SWC type path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: ArxmlModel | None = None
        self._os_rte: OsRteOverlay | None = None
        self._filter = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("过滤:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "模糊过滤：子串 / 空格分词 / 缩写(bld) / 忽略_ （Enter）…"
        )
        self.filter_edit.setToolTip(
            "匹配规则（任一命中即可）:\n"
            "· 子串：backli 匹配 BackLiDrvrReq\n"
            "· 忽略下划线：backlidrvr 匹配 BackLi_Drvr_Req\n"
            "· 空格分词（AND）：back li req\n"
            "· 子序列/缩写：bld 或 BLDR 匹配 BackLiDrvrReq\n"
            "Enter 应用；清空恢复全部"
        )
        self.filter_edit.returnPressed.connect(self._apply_filter)
        self.filter_edit.textChanged.connect(self._on_filter_typed)
        self._filter_debounce = QTimer(self)
        self._filter_debounce.setSingleShot(True)
        self._filter_debounce.setInterval(350)
        self._filter_debounce.timeout.connect(self._apply_filter)
        bar.addWidget(self.filter_edit, 1)
        lay.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Kind"])
        self.tree.setColumnWidth(0, 280)
        self.tree.itemSelectionChanged.connect(self._on_sel)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        lay.addWidget(self.tree, 1)

    def set_model(self, model: ArxmlModel | None):
        self._model = model
        self._filter = (self.filter_edit.text() or "").strip().lower()
        self._rebuild()

    def set_os_rte(self, overlay: OsRteOverlay | None):
        self._os_rte = overlay
        self._rebuild()

    def _on_filter_typed(self, text: str):
        # clear → immediate; otherwise debounce rebuild (also Enter)
        if not (text or "").strip():
            self._filter_debounce.stop()
            self._filter = ""
            self._rebuild()
            return
        self._filter_debounce.start()

    def _apply_filter(self):
        self._filter_debounce.stop()
        self._filter = (self.filter_edit.text() or "").strip().lower()
        self._rebuild()

    def _rebuild(self):
        self.tree.clear()
        model = self._model
        if not model:
            return

        root = QTreeWidgetItem(["Compositions", "ROOT"])
        root.setData(0, ROLE_PATH, "")
        root.setData(0, ROLE_KIND, "group")
        self.tree.addTopLevelItem(root)

        roots_item = QTreeWidgetItem(["Top-level", "GROUP"])
        roots_item.setData(0, ROLE_KIND, "group")
        root.addChild(roots_item)

        shown = set()
        for cpath in model.root_compositions:
            self._add_composition_item(roots_item, cpath, model, shown, depth=0)

        all_item = QTreeWidgetItem(["All Compositions", "GROUP"])
        all_item.setData(0, ROLE_KIND, "group")
        root.addChild(all_item)
        for cpath in model.composition_paths():
            if cpath in shown:
                continue
            self._add_composition_item(all_item, cpath, model, shown, depth=0, recurse=False)

        # Application SWCs: Ports 与 Internal Behavior（*swc_IB）同级挂在 SWC 下
        apps = QTreeWidgetItem(["Application SWCs", "GROUP"])
        apps.setData(0, ROLE_KIND, "group")
        root.addChild(apps)
        for apath in model.application_paths():
            swc = model.swc_types[apath]
            behaviors = getattr(swc, "behaviors", None) or model.behaviors_of_swc(apath)
            if self._filter and not self._match(swc.name, apath):
                port_hit = any(self._match(p.name, p.path) for p in swc.ports)
                beh_hit = any(
                    self._match(b.name, b.path) for b in (behaviors or [])
                )
                if not port_hit and not beh_hit:
                    continue
            it = QTreeWidgetItem([swc.name, "APPLICATION"])
            it.setData(0, ROLE_PATH, apath)
            it.setData(0, ROLE_KIND, "swc")
            it.setForeground(0, QBrush(QColor("#1a5f7a")))
            tip = apath
            if not behaviors:
                tip += "  [缺 Internal Behavior]"
                it.setForeground(0, QBrush(QColor("#c62828")))
            it.setToolTip(0, tip)
            apps.addChild(it)
            self._add_ports(it, swc, model)
            self._add_internal_behaviors(it, swc, model)

        self._add_data_types(root, model)
        self._add_sr_interfaces(root, model)
        self._add_data_mappings(root, model)

        if model.cs_interfaces:
            cs_root = QTreeWidgetItem(
                [f"CS Interfaces ({len(model.cs_interfaces)})", "GROUP"]
            )
            cs_root.setData(0, ROLE_KIND, "group")
            cs_root.setForeground(0, QBrush(QColor("#6a1b9a")))
            root.addChild(cs_root)
            for path in sorted(model.cs_interfaces.keys()):
                cs = model.cs_interfaces[path]
                if self._filter and not self._match(cs.name, path):
                    continue
                it = QTreeWidgetItem([cs.name, "CS-IF"])
                it.setData(0, ROLE_PATH, path)
                it.setData(0, ROLE_KIND, "cs_interface")
                it.setForeground(0, QBrush(QColor("#6a1b9a")))
                it.setToolTip(0, path)
                cs_root.addChild(it)
                for op in cs.operations:
                    if self._filter and not self._match(op.name, op.path):
                        continue
                    oit = QTreeWidgetItem([op.name, "OPERATION"])
                    oit.setData(0, ROLE_PATH, op.path)
                    oit.setData(0, ROLE_KIND, "cs_operation")
                    tip = ", ".join(op.arguments) if op.arguments else ""
                    oit.setToolTip(0, tip or op.path)
                    it.addChild(oit)

        self._add_os_tasks(root, model)

        root.setExpanded(True)
        roots_item.setExpanded(True)
        if self._filter:
            self.tree.expandToDepth(2)

    def _add_os_tasks(self, parent: QTreeWidgetItem, model: ArxmlModel):
        ov = self._os_rte
        n_t = len(ov.tasks) if ov else 0
        n_m = len(ov.mappings) if ov else 0
        folder = QTreeWidgetItem(
            [f"OS Tasks (overlay) ({n_t}/{n_m})", "GROUP"]
        )
        folder.setData(0, ROLE_KIND, "group")
        folder.setForeground(0, QBrush(QColor("#455a64")))
        tip = "侧车 JSON：OsTask + Runnable→Task（非 ECUC）"
        if ov and ov.source_path:
            tip += f"\n{ov.source_path}"
        folder.setToolTip(0, tip)
        parent.addChild(folder)
        if not ov or not ov.tasks:
            empty = QTreeWidgetItem(["(无 Task — Tools → OS/RTE Mapping)", "INFO"])
            empty.setData(0, ROLE_KIND, "group")
            folder.addChild(empty)
            return
        for task in ov.tasks:
            if self._filter and not self._match(task.name):
                maps = ov.mappings_by_task(task.name)
                if not any(
                    self._match(m.swc_prototype, m.runnable, task.name) for m in maps
                ):
                    continue
            label = (
                f"{task.name}  prio={task.priority}  "
                f"{task.schedule}/{task.type}"
            )
            tit = QTreeWidgetItem([label, "OS-TASK"])
            tit.setData(0, ROLE_PATH, task.name)
            tit.setData(0, ROLE_KIND, "os_task")
            tit.setForeground(0, QBrush(QColor("#37474f")))
            tit.setToolTip(0, f"{task.name}\npriority={task.priority}")
            folder.addChild(tit)
            for m in ov.mappings_by_task(task.name):
                proto_n = model.resolve_name(m.swc_prototype)
                run_n = model.resolve_name(m.runnable)
                mlabel = f"[{m.position}] {proto_n}.{run_n}"
                if self._filter and not self._match(
                    mlabel, m.swc_prototype, m.runnable, task.name
                ):
                    continue
                mit = QTreeWidgetItem([mlabel, "OS-MAP"])
                # Selecting jumps to Runnable (existing handler)
                mit.setData(0, ROLE_PATH, m.runnable)
                mit.setData(0, ROLE_KIND, "runnable")
                mit.setToolTip(
                    0,
                    f"Task={task.name}\nProto={m.swc_prototype}\n"
                    f"Runnable={m.runnable}",
                )
                mit.setForeground(0, QBrush(QColor("#546e7a")))
                tit.addChild(mit)

    @staticmethod
    def _norm_text(s: str) -> str:
        """Lowercase and strip separators for fuzzy compare."""
        return re.sub(r"[_\-/\s]+", "", (s or "").lower())

    @staticmethod
    def _camel_initials(s: str) -> str:
        """BackLiDrvrReq / back_li_drvr → bldr (approx)."""
        if not s:
            return ""
        # split on _ - / and CamelCase boundaries
        parts = re.findall(
            r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+",
            s.replace("_", " ").replace("-", " ").replace("/", " "),
        )
        if not parts:
            return ModelTree._norm_text(s)[:8]
        return "".join(p[0] for p in parts if p).lower()

    @staticmethod
    def _is_subsequence(query: str, text: str) -> bool:
        """True if all chars of query appear in order in text."""
        if not query:
            return True
        it = iter(text)
        return all(ch in it for ch in query)

    def _match(self, *parts: str) -> bool:
        """Fuzzy match filter against name/path fragments."""
        if not self._filter:
            return True
        q = self._filter
        blob = " ".join(p for p in parts if p).lower()
        if not blob:
            return False
        # 1) plain substring
        if q in blob:
            return True
        # 2) space/comma separated tokens (AND)
        tokens = [t for t in re.split(r"[\s,;]+", q) if t]
        if len(tokens) > 1 and all(t in blob for t in tokens):
            return True
        # 3) ignore underscores / path separators
        nq = self._norm_text(q)
        nblob = self._norm_text(blob)
        if nq and nq in nblob:
            return True
        if len(tokens) > 1 and all(self._norm_text(t) in nblob for t in tokens):
            return True
        # 4) camelCase / segment initials (e.g. BLDR, bldr)
        initials = " ".join(self._camel_initials(p) for p in parts if p)
        if nq and (nq == self._norm_text(initials) or nq in initials.replace(" ", "")):
            return True
        # 5) subsequence fuzzy (short queries only, avoid noise)
        if 2 <= len(nq) <= 12 and self._is_subsequence(nq, nblob):
            return True
        return False

    def _add_lazy_folder(
        self, parent: QTreeWidgetItem, title: str, lazy_key: str, color: QColor
    ):
        folder = QTreeWidgetItem([title, "GROUP"])
        folder.setData(0, ROLE_KIND, "group")
        folder.setData(0, ROLE_LAZY, lazy_key)
        folder.setForeground(0, QBrush(color))
        parent.addChild(folder)
        # placeholder so expand arrow shows
        ph = QTreeWidgetItem(["…", ""])
        ph.setData(0, ROLE_KIND, "group")
        folder.addChild(ph)
        return folder

    def _on_expanded(self, item: QTreeWidgetItem):
        lazy = item.data(0, ROLE_LAZY)
        if not lazy or not self._model:
            return
        item.setData(0, ROLE_LAZY, None)
        while item.childCount():
            item.removeChild(item.child(0))
        self._populate_lazy(item, lazy)

    def _populate_lazy(self, folder: QTreeWidgetItem, lazy_key: str):
        model = self._model
        assert model is not None
        if lazy_key.startswith("adt:"):
            kind = lazy_key.split(":", 1)[1]
            color = QColor("#00695c")
            items = sorted(
                (a for a in model.adts.values() if a.kind == kind),
                key=lambda a: a.name.lower(),
            )
            for adt in items:
                if self._filter and not self._match(adt.name, adt.path):
                    continue
                self._add_adt_item(folder, adt, model, color)
        elif lazy_key == "idt":
            color = QColor("#00838f")
            for path in sorted(model.idts.keys(), key=lambda p: model.idts[p].name.lower()):
                idt = model.idts[path]
                if self._filter and not self._match(idt.name, path):
                    continue
                it = QTreeWidgetItem([idt.name, "IDT"])
                it.setData(0, ROLE_PATH, path)
                it.setData(0, ROLE_KIND, "idt")
                it.setForeground(0, QBrush(color))
                tip = path
                if idt.base_type_ref:
                    tip += f"\nBase: {idt.base_type_ref}"
                adt_p = model.adt_by_idt.get(path)
                if adt_p:
                    tip += f"\n← ADT: {model.resolve_name(adt_p)}"
                it.setToolTip(0, tip)
                folder.addChild(it)
        elif lazy_key == "dt_map":
            for m in sorted(
                model.data_type_maps,
                key=lambda x: model.resolve_name(x.adt_ref).lower(),
            ):
                an = model.resolve_name(m.adt_ref) or m.adt_ref
                inn = model.resolve_name(m.idt_ref) or m.idt_ref
                if self._filter and not self._match(an, inn, m.adt_ref, m.idt_ref):
                    continue
                it = QTreeWidgetItem([f"{an} → {inn}", "DT-MAP"])
                it.setData(0, ROLE_PATH, m.adt_ref or m.idt_ref)
                it.setData(0, ROLE_KIND, "data_type_map")
                it.setToolTip(0, f"{m.adt_ref}\n→ {m.idt_ref}")
                folder.addChild(it)
        elif lazy_key == "sr_if":
            color = QColor("#2e7d32")
            for path in sorted(model.interfaces.keys()):
                iface = model.interfaces[path]
                if self._filter and not self._match(iface.name, path):
                    if not any(
                        self._match(de.name, de.path) for de in iface.data_elements
                    ):
                        continue
                it = QTreeWidgetItem([iface.name, "SR-IF"])
                it.setData(0, ROLE_PATH, path)
                it.setData(0, ROLE_KIND, "sr_interface")
                it.setForeground(0, QBrush(color))
                it.setToolTip(0, path)
                folder.addChild(it)
                for de in iface.data_elements:
                    if self._filter and not self._match(de.name, de.path, de.type_ref):
                        continue
                    tn = model.resolve_name(de.type_ref) if de.type_ref else ""
                    dit = QTreeWidgetItem(
                        [f"{de.name}" + (f" : {tn}" if tn else ""), "DATA-ELEM"]
                    )
                    dit.setData(0, ROLE_PATH, de.path or path)
                    dit.setData(0, ROLE_KIND, "sr_data_element")
                    dit.setData(0, Qt.ItemDataRole.UserRole + 2, de.type_ref)
                    dit.setData(0, Qt.ItemDataRole.UserRole + 3, path)
                    dit.setToolTip(0, de.type_ref or de.path)
                    it.addChild(dit)
        if folder.childCount() == 0:
            empty = QTreeWidgetItem(["(无匹配)", ""])
            empty.setData(0, ROLE_KIND, "group")
            folder.addChild(empty)

    def _add_adt_item(self, parent, adt, model: ArxmlModel, color: QColor):
        kind_col = f"ADT-{adt.kind[:3]}"
        it = QTreeWidgetItem([adt.name, kind_col])
        it.setData(0, ROLE_PATH, adt.path)
        it.setData(0, ROLE_KIND, "adt")
        it.setForeground(0, QBrush(color))
        tip = adt.path
        mapped = model.idt_by_adt.get(adt.path)
        if mapped:
            tip += f"\n→ IDT: {model.resolve_name(mapped)}"
        it.setToolTip(0, tip)
        parent.addChild(it)
        if adt.kind == "RECORD":
            for el in adt.elements:
                if self._filter and not self._match(el.name, el.path, el.type_ref):
                    continue
                eit = QTreeWidgetItem([el.name, "ADT-ELEM"])
                eit.setData(0, ROLE_PATH, el.path or adt.path)
                eit.setData(0, ROLE_KIND, "adt_element")
                eit.setToolTip(0, el.type_ref or el.path)
                it.addChild(eit)

    def _add_data_types(self, root: QTreeWidgetItem, model: ArxmlModel):
        if not (model.adts or model.idts or model.base_types):
            return
        prim, rec, arr, n_idt, n_base = model.adt_summary()
        n_adt = prim + rec + arr
        dt_root = QTreeWidgetItem([f"Data Types / ADT ({n_adt})", "GROUP"])
        dt_root.setData(0, ROLE_KIND, "group")
        dt_root.setForeground(0, QBrush(QColor("#00695c")))
        dt_root.setToolTip(
            0,
            f"ADT Primitive={prim} Record={rec} Array={arr} · "
            f"IDT={n_idt} · BaseType={n_base} · Maps={len(model.data_type_maps)}",
        )
        root.addChild(dt_root)

        if model.adts:
            adt_folder = QTreeWidgetItem(
                [f"Application Data Types ({n_adt})", "GROUP"]
            )
            adt_folder.setData(0, ROLE_KIND, "group")
            adt_folder.setForeground(0, QBrush(QColor("#00695c")))
            dt_root.addChild(adt_folder)
            for kind, label, cnt in (
                ("PRIMITIVE", "Primitive", prim),
                ("RECORD", "Record", rec),
                ("ARRAY", "Array", arr),
            ):
                if cnt == 0:
                    continue
                # filter mode: populate eagerly so matches appear
                if self._filter:
                    folder = QTreeWidgetItem([f"{label} ({cnt})", "GROUP"])
                    folder.setData(0, ROLE_KIND, "group")
                    folder.setForeground(0, QBrush(QColor("#00695c")))
                    adt_folder.addChild(folder)
                    self._populate_lazy(folder, f"adt:{kind}")
                else:
                    self._add_lazy_folder(
                        adt_folder, f"{label} ({cnt})", f"adt:{kind}", QColor("#00695c")
                    )

        if model.idts:
            if self._filter:
                folder = QTreeWidgetItem(
                    [f"Implementation Data Types ({n_idt})", "GROUP"]
                )
                folder.setData(0, ROLE_KIND, "group")
                folder.setForeground(0, QBrush(QColor("#00838f")))
                dt_root.addChild(folder)
                self._populate_lazy(folder, "idt")
            else:
                self._add_lazy_folder(
                    dt_root,
                    f"Implementation Data Types ({n_idt})",
                    "idt",
                    QColor("#00838f"),
                )

        if model.base_types:
            base_folder = QTreeWidgetItem([f"Base Types ({n_base})", "GROUP"])
            base_folder.setData(0, ROLE_KIND, "group")
            base_folder.setForeground(0, QBrush(QColor("#455a64")))
            dt_root.addChild(base_folder)
            for path in sorted(
                model.base_types.keys(),
                key=lambda p: model.base_types[p].name.lower(),
            ):
                bt = model.base_types[path]
                if self._filter and not self._match(bt.name, path):
                    continue
                it = QTreeWidgetItem([bt.name, "BASE-TYPE"])
                it.setData(0, ROLE_PATH, path)
                it.setData(0, ROLE_KIND, "base_type")
                it.setForeground(0, QBrush(QColor("#455a64")))
                it.setToolTip(0, path)
                base_folder.addChild(it)

        if model.data_type_maps:
            if self._filter:
                folder = QTreeWidgetItem(
                    [f"ADT ↔ IDT Maps ({len(model.data_type_maps)})", "GROUP"]
                )
                folder.setData(0, ROLE_KIND, "group")
                dt_root.addChild(folder)
                self._populate_lazy(folder, "dt_map")
            else:
                self._add_lazy_folder(
                    dt_root,
                    f"ADT ↔ IDT Maps ({len(model.data_type_maps)})",
                    "dt_map",
                    QColor("#5d4037"),
                )

    def _add_sr_interfaces(self, root: QTreeWidgetItem, model: ArxmlModel):
        if not model.interfaces:
            return
        n = len(model.interfaces)
        if self._filter:
            folder = QTreeWidgetItem([f"SR Interfaces ({n})", "GROUP"])
            folder.setData(0, ROLE_KIND, "group")
            folder.setForeground(0, QBrush(QColor("#2e7d32")))
            root.addChild(folder)
            self._populate_lazy(folder, "sr_if")
        else:
            self._add_lazy_folder(
                root, f"SR Interfaces ({n})", "sr_if", QColor("#2e7d32")
            )

    def _add_data_mappings(self, root: QTreeWidgetItem, model: ArxmlModel):
        n = len(model.data_mappings)
        folder = QTreeWidgetItem(
            [f"System Data Mappings ({n})", "GROUP"]
        )
        folder.setData(0, ROLE_KIND, "group")
        folder.setForeground(0, QBrush(QColor("#bf360c")))
        if n == 0:
            folder.setToolTip(
                0,
                "当前 ARXML 无 SYSTEM/I-Signal Data Mapping（SWC 导出常见）。"
                "可用 testdata/mini_sysmap.arxml 验证。",
            )
            empty = QTreeWidgetItem(["(无映射数据)", "INFO"])
            empty.setData(0, ROLE_KIND, "group")
            folder.addChild(empty)
        else:
            for dm in model.data_mappings:
                if self._filter and not self._match(
                    dm.name, dm.path, dm.port_ref, dm.signal_ref
                ):
                    continue
                label = dm.name or model.resolve_name(dm.signal_ref) or "mapping"
                it = QTreeWidgetItem([label, dm.kind])
                it.setData(0, ROLE_PATH, dm.path)
                it.setData(0, ROLE_KIND, "data_mapping")
                it.setForeground(0, QBrush(QColor("#bf360c")))
                tip = f"{dm.port_ref}\n→ {dm.signal_ref}"
                it.setToolTip(0, tip)
                folder.addChild(it)
        root.addChild(folder)

    def _add_composition_item(
        self,
        parent: QTreeWidgetItem,
        cpath: str,
        model: ArxmlModel,
        shown: set,
        depth: int,
        recurse: bool = True,
    ):
        if depth > 8 or cpath in shown and recurse:
            if recurse:
                return
        swc = model.swc_types.get(cpath)
        if not swc:
            return
        if self._filter and not self._match(swc.name, cpath):
            if recurse:
                # still recurse into children that might match
                pass
            elif not any(self._match(p.name, p.path) for p in swc.ports):
                return
        if recurse:
            shown.add(cpath)
        it = QTreeWidgetItem([swc.name, "COMPOSITION"])
        it.setData(0, ROLE_PATH, cpath)
        it.setData(0, ROLE_KIND, "composition")
        it.setForeground(0, QBrush(QColor("#8B4513")))
        parent.addChild(it)

        protos_folder = QTreeWidgetItem(["Prototypes", "GROUP"])
        protos_folder.setData(0, ROLE_KIND, "group")
        it.addChild(protos_folder)
        for proto in swc.prototypes:
            if self._filter and not self._match(proto.name, proto.path, proto.type_ref):
                continue
            pit = QTreeWidgetItem([proto.name, "PROTOTYPE"])
            pit.setData(0, ROLE_PATH, proto.path)
            pit.setData(0, ROLE_KIND, "prototype")
            pit.setToolTip(0, proto.type_ref)
            protos_folder.addChild(pit)
            if recurse and proto.type_ref in model.swc_types:
                child_type = model.swc_types[proto.type_ref]
                if child_type.kind == "COMPOSITION":
                    self._add_composition_item(
                        pit, proto.type_ref, model, shown, depth + 1, recurse=True
                    )
                elif child_type.kind == "APPLICATION":
                    # Ports 与 IB 同级（与 Application SWCs 列表一致）
                    self._add_ports(pit, child_type, model)
                    self._add_internal_behaviors(pit, child_type, model)

        ports_folder = QTreeWidgetItem(["Outer Ports", "GROUP"])
        ports_folder.setData(0, ROLE_KIND, "group")
        it.addChild(ports_folder)
        self._add_ports(ports_folder, swc, model)

        conn = QTreeWidgetItem(
            [
                f"Connectors (A={len(swc.assemblies)} D={len(swc.delegations)})",
                "INFO",
            ]
        )
        conn.setData(0, ROLE_PATH, cpath)
        conn.setData(0, ROLE_KIND, "composition")
        it.addChild(conn)

    def _add_ports(self, parent: QTreeWidgetItem, swc, model: ArxmlModel | None = None):
        model = model or self._model
        for port in swc.ports:
            if self._filter and not self._match(port.name, port.path, port.interface_ref):
                continue
            ik = getattr(port, "iface_kind", "SR") or "SR"
            kind = f"{port.direction}-{ik}"
            label = port.name
            type_lines: list[str] = []
            if model and ik == "SR":
                type_lines = model.port_sr_type_lines(port.path)
                summary = model.port_sr_type_summary(port.path)
                if summary:
                    label = f"{port.name}  · {summary}"
            if self._filter and type_lines and not self._match(
                label, port.name, port.path, *type_lines
            ):
                # already matched name/path above; keep port if name matched
                pass
            pit = QTreeWidgetItem([label, kind])
            pit.setData(0, ROLE_PATH, port.path)
            pit.setData(0, ROLE_KIND, "port")
            if ik == "CS":
                color = QColor("#6a1b9a") if port.direction == "P" else QColor("#ad1457")
            else:
                color = QColor("#0b6e4f") if port.direction == "P" else QColor("#9b2226")
            pit.setForeground(0, QBrush(color))
            tip = f"{ik}: {port.interface_ref}" if port.interface_ref else ik
            if type_lines:
                tip += "\n" + "\n".join(type_lines)
            pit.setToolTip(0, tip)
            parent.addChild(pit)

    def _add_internal_behaviors(self, parent: QTreeWidgetItem, swc, model: ArxmlModel):
        """Hang SWC-INTERNAL-BEHAVIOR under SWC, sibling of Ports (not a separate RTE root)."""
        behaviors = getattr(swc, "behaviors", None) or model.behaviors_of_swc(swc.path)
        if not behaviors:
            # Placeholder so缺失 IB 在树上可见（校验器也会报错）
            miss = QTreeWidgetItem(["(缺 Internal Behavior)", "IB-MISSING"])
            miss.setData(0, ROLE_PATH, swc.path)
            miss.setData(0, ROLE_KIND, "swc")
            miss.setForeground(0, QBrush(QColor("#c62828")))
            miss.setToolTip(0, f"{swc.path} 无 SWC-INTERNAL-BEHAVIOR")
            parent.addChild(miss)
            return
        for beh in behaviors:
            if self._filter and not self._match(beh.name, beh.path):
                continue
            empty_mark = " (empty)" if beh.is_empty else ""
            # Display like XxxSwc_IB when name already encodes it; keep SHORT-NAME as-is
            label = beh.name or f"{swc.name}_IB"
            bit = QTreeWidgetItem(
                [f"{label}{empty_mark}", "INTERNAL-BEHAVIOR"]
            )
            bit.setData(0, ROLE_PATH, beh.path)
            bit.setData(0, ROLE_KIND, "behavior")
            bit.setForeground(0, QBrush(QColor("#1565c0")))
            bit.setToolTip(
                0,
                "导出中 IB 无有效 SHORT-NAME/REF" if beh.is_empty else beh.path,
            )
            parent.addChild(bit)

            run_folder = QTreeWidgetItem(
                [f"Runnables ({len(beh.runnables)})", "GROUP"]
            )
            run_folder.setData(0, ROLE_KIND, "group")
            bit.addChild(run_folder)
            for r in beh.runnables:
                if self._filter and not self._match(r.name, r.path, r.symbol):
                    continue
                rit = QTreeWidgetItem([r.name or "(unnamed)", "RUNNABLE"])
                rit.setData(0, ROLE_PATH, r.path)
                rit.setData(0, ROLE_KIND, "runnable")
                rit.setToolTip(0, r.symbol or r.path)
                run_folder.addChild(rit)
                # Port Access children: click/select jumps to Port
                for acc in r.accesses:
                    port_n = (
                        model.resolve_name(acc.port_ref) if acc.port_ref else "?"
                    )
                    tgt = acc.data_element_ref or acc.operation_ref
                    tgt_n = model.resolve_name(tgt) if tgt else ""
                    kind = (acc.access_kind or "OTHER").upper()
                    if kind in ("SEND", "SERVER-CALL"):
                        arrow, tag = "→", "SEND" if kind == "SEND" else "CALL"
                    elif kind in ("RECEIVE", "RECV"):
                        arrow, tag = "←", "RECV"
                    else:
                        arrow, tag = "·", kind[:8] or "ACCESS"
                    de = f".{tgt_n}" if tgt_n else ""
                    label = f"{tag} {arrow} {port_n}{de}"
                    if self._filter and not self._match(
                        label, acc.port_ref or "", port_n, tgt_n
                    ):
                        continue
                    ait = QTreeWidgetItem([label, tag])
                    # Navigate to Port on select (same as Port node)
                    ait.setData(0, ROLE_PATH, acc.port_ref or "")
                    ait.setData(0, ROLE_KIND, "port")
                    tip = f"{kind} access → {acc.port_ref or ''}"
                    if tgt:
                        tip += f"\n{tgt}"
                    ait.setToolTip(0, tip)
                    ait.setForeground(0, QBrush(QColor("#00695c")))
                    rit.addChild(ait)

            ev_folder = QTreeWidgetItem([f"Events ({len(beh.events)})", "GROUP"])
            ev_folder.setData(0, ROLE_KIND, "group")
            bit.addChild(ev_folder)
            for ev in beh.events:
                if self._filter and not self._match(ev.name, ev.path):
                    continue
                eit = QTreeWidgetItem([ev.name or "(unnamed)", ev.kind or "EVENT"])
                eit.setData(0, ROLE_PATH, ev.path)
                eit.setData(0, ROLE_KIND, "rte_event")
                tip = ev.start_on_runnable_ref or ev.path
                if ev.period:
                    tip = f"period={ev.period} → {tip}"
                eit.setToolTip(0, tip)
                ev_folder.addChild(eit)

    def _on_sel(self):
        items = self.tree.selectedItems()
        if not items:
            return
        it = items[0]
        path = it.data(0, ROLE_PATH) or ""
        kind = it.data(0, ROLE_KIND) or ""
        if kind in ("group", "root"):
            return
        self.selection_path.emit(path, kind)

    def _swc_path_for_item(self, it: QTreeWidgetItem) -> str:
        """Resolve Application SWC type path from a tree item (swc / prototype / port)."""
        if not self._model or not it:
            return ""
        path = it.data(0, ROLE_PATH) or ""
        kind = it.data(0, ROLE_KIND) or ""
        if kind == "swc":
            swc = self._model.swc_types.get(path)
            if swc and swc.kind == "APPLICATION":
                return path
            return ""
        if kind == "prototype":
            proto = self._model.prototypes.get(path)
            if not proto:
                return ""
            swc = self._model.swc_types.get(proto.type_ref)
            if swc and swc.kind == "APPLICATION":
                return proto.type_ref
            return ""
        if kind == "port":
            port = self._model.ports.get(path)
            if not port:
                return ""
            swc = self._model.swc_types.get(port.owner_path)
            if swc and swc.kind == "APPLICATION":
                return port.owner_path
        return ""

    def _on_context_menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it:
            return
        swc_path = self._swc_path_for_item(it)
        if not swc_path:
            return
        # also select the item for consistency
        self.tree.setCurrentItem(it)
        name = self._model.resolve_name(swc_path) if self._model else swc_path
        menu = QMenu(self)
        act = menu.addAction(f"导出 SWC ARXML（含依赖）: {name}")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen == act:
            self.export_swc_requested.emit(swc_path)
