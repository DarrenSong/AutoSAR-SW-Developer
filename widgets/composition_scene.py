# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPen,
    QPainter,
    QFont,
    QPainterPath,
    QFontMetrics,
    QImage,
)
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsPathItem,
    QGraphicsLineItem,
    QGraphicsSimpleTextItem,
    QGraphicsItem,
    QMenu,
    QStyle,
)

from ..graph_builder import CompositionGraph, GraphEdge, GraphNode, PORT_LABEL_W, PORT_PIN


def _elide(text: str, font: QFont, max_w: float) -> str:
    fm = QFontMetrics(font)
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, int(max_w))


class NodeItem(QGraphicsRectItem):
    def __init__(self, node: GraphNode):
        self.node = node
        self._default_border = QColor("#333")
        self._label_item: QGraphicsSimpleTextItem | None = None

        if node.kind in ("sr_port", "outer_port"):
            self._init_port(node)
            return

        w, h = node.w, node.h
        super().__init__(-w / 2, -h / 2, w, h)
        self.setPos(node.x, node.y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

        if node.kind == "chain_port":
            self.setZValue(3)
            is_p = node.port_direction == "P"
            ik = node.meta.get("iface_kind") or "SR"
            if ik == "CS":
                fill = QColor("#f3e5f5") if is_p else QColor("#fce4ec")
                border = QColor("#6a1b9a") if is_p else QColor("#ad1457")
            else:
                fill = QColor("#e8f5e9") if is_p else QColor("#ffebee")
                border = QColor("#2e7d32") if is_p else QColor("#c62828")
            if not node.port_direction:
                fill, border = QColor("#eceff1"), QColor("#546e7a")
            self.setBrush(QBrush(fill))
            self.setPen(QPen(border, 2))
            self._default_border = border
            dir_tag = (
                f"{node.port_direction}-{ik}" if node.port_direction else "PORT"
            )
            font = QFont("Segoe UI", 8, QFont.Weight.Bold)
            title = QGraphicsSimpleTextItem(_elide(node.label, font, w - 12), self)
            title.setFont(font)
            title.setBrush(QBrush(QColor("#222")))
            br = title.boundingRect()
            title.setPos(-br.width() / 2, -h / 2 + 8)
            sf = QFont("Segoe UI", 7)
            sub = QGraphicsSimpleTextItem(dir_tag, self)
            sub.setFont(sf)
            sub.setBrush(QBrush(border))
            sbr = sub.boundingRect()
            sub.setPos(-sbr.width() / 2, -h / 2 + 28)
            tip = node.meta.get("full_label") or node.label
            tip += f"\n{dir_tag}"
            if node.meta.get("composition"):
                tip += f"\nSWC: {node.meta['composition']}"
            if node.meta.get("peer_relation"):
                tip += f"\n对端关系: {node.meta['peer_relation']}"
            if node.meta.get("peer_source") == "peer_file":
                tip += "\n来源: 对照文件"
            if node.meta.get("peer_star_focus"):
                tip += "\n(本侧焦点)"
            if node.meta.get("dir_tag_extra"):
                sub2 = QGraphicsSimpleTextItem(str(node.meta["dir_tag_extra"]), self)
                sub2.setFont(sf)
                sub2.setBrush(QBrush(QColor("#546e7a")))
                s2 = sub2.boundingRect()
                sub2.setPos(-s2.width() / 2, -h / 2 + 40)
            self.setToolTip(tip)
            return

        if node.kind == "frame":
            self.setZValue(-10)
            self.setBrush(QBrush(QColor("#fafafa")))
            self.setPen(QPen(QColor("#5d4037"), 2.5))
            self._default_border = QColor("#5d4037")
            title = QGraphicsSimpleTextItem(node.label, self)
            title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            title.setBrush(QBrush(QColor("#3e2723")))
            title.setPos(-w / 2 + 12, -h / 2 + 8)
            if node.meta.get("peer_star_view"):
                hint = QGraphicsSimpleTextItem(
                    "1:N 对端链路  ·  左=本侧嵌套Composition链  ·  "
                    "右=各对端嵌套链  ·  中间连线=P↔R  ·  紫虚线=Delegation",
                    self,
                )
            elif node.meta.get("nested_chain") or node.meta.get("sr_chain_view"):
                hint = QGraphicsSimpleTextItem(
                    "嵌套链路  ·  外框=Composition  ·  橙=子Composition  ·  "
                    "蓝=SWC  ·  紫虚线=Delegation  ·  蓝实线=Assembly",
                    self,
                )
            else:
                hint = QGraphicsSimpleTextItem(
                    "当前层  ·  双击进入子 Composition  ·  绿/红=SR  ·  紫=CS", self
                )
            hint.setFont(QFont("Segoe UI", 7))
            hint.setBrush(QBrush(QColor("#8d6e63")))
            hint.setPos(-w / 2 + 12, -h / 2 + 26)
            self.setToolTip(f"{node.label}\n{node.type_ref}")
            return

        if node.kind == "proto_comp":
            self.setZValue(0)
            self.setBrush(QBrush(QColor("#fff8e1")))
            self.setPen(QPen(QColor("#ef6c00"), 2))
            self._default_border = QColor("#ef6c00")
            font = QFont("Segoe UI", 9, QFont.Weight.Bold)
            title = QGraphicsSimpleTextItem(_elide(node.label, font, w - 16), self)
            title.setFont(font)
            title.setBrush(QBrush(QColor("#e65100")))
            title.setPos(-w / 2 + 8, -h / 2 + 6)
            if node.meta.get("nested_chain"):
                sub = QGraphicsSimpleTextItem("嵌套 Composition（链路）", self)
            else:
                sub = QGraphicsSimpleTextItem("Composition · 双击进入", self)
            sub.setFont(QFont("Segoe UI", 7))
            sub.setBrush(QBrush(QColor("#f57c00")))
            sub.setPos(-w / 2 + 8, -h / 2 + 22)
            tip = f"{node.label}\n{node.type_ref}"
            if not node.meta.get("nested_chain"):
                tip += "\n双击进入 · Ctrl+双击/右键 → 新窗口"
            self.setToolTip(tip)
            return

        if node.kind == "nested_child":
            is_comp = node.type_kind == "COMPOSITION"
            self.setZValue(2)
            self.setBrush(QBrush(QColor("#ffe0b2") if is_comp else QColor("#e3f2fd")))
            self.setPen(QPen(QColor("#ef6c00") if is_comp else QColor("#1976d2"), 1))
            self._default_border = QColor("#ef6c00") if is_comp else QColor("#1976d2")
            font = QFont("Segoe UI", 7)
            label = QGraphicsSimpleTextItem(_elide(node.label, font, w - 6), self)
            label.setFont(font)
            br = label.boundingRect()
            label.setPos(-br.width() / 2, -br.height() / 2)
            tip = node.meta.get("full_label") or node.label
            if node.drill_path:
                tip += "\n双击进入"
            self.setToolTip(tip)
            return

        if node.kind == "runnable":
            self.setZValue(3)
            is_ph = bool(node.meta.get("placeholder"))
            fill = QColor("#eceff1") if is_ph else QColor("#e0f2f1")
            border = QColor("#78909c") if is_ph else QColor("#00695c")
            self.setBrush(QBrush(fill))
            self.setPen(QPen(border, 1.5))
            self._default_border = border
            font = QFont("Segoe UI", 7, QFont.Weight.Bold)
            label = QGraphicsSimpleTextItem(_elide(node.label, font, w - 8), self)
            label.setFont(font)
            label.setBrush(QBrush(QColor("#004d40")))
            br = label.boundingRect()
            label.setPos(-br.width() / 2, -br.height() / 2)
            tip = node.meta.get("full_label") or node.label
            if node.meta.get("symbol"):
                tip += f"\nsymbol: {node.meta['symbol']}"
            if node.meta.get("access_count") is not None:
                tip += f"\naccesses: {node.meta['access_count']}"
            self.setToolTip(tip)
            return

        # proto_swc
        self.setZValue(1)
        self.setBrush(QBrush(QColor("#e3f2fd")))
        self.setPen(QPen(QColor("#1565c0"), 2))
        self._default_border = QColor("#1565c0")
        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        label = QGraphicsSimpleTextItem(_elide(node.label, font, w - 12), self)
        label.setFont(font)
        br = label.boundingRect()
        label.setPos(-br.width() / 2, -h / 2 + 8)
        if node.type_ref:
            sf = QFont("Segoe UI", 6)
            tname = node.type_ref.rsplit("/", 1)[-1]
            sub = QGraphicsSimpleTextItem(_elide(tname, sf, w - 12), self)
            sub.setFont(sf)
            sub.setBrush(QBrush(QColor("#5472d3")))
            sbr = sub.boundingRect()
            sub.setPos(-sbr.width() / 2, -h / 2 + 24)
        self.setToolTip(f"{node.label}\n{node.type_ref}")

    def _init_port(self, node: GraphNode):
        """Port pin + label outside (not clipped by the pin rect)."""
        is_p = node.port_direction == "P"
        label_w = PORT_LABEL_W
        pin = PORT_PIN
        # Item spans pin + label so sceneRect includes text
        if is_p:
            # pin at left of item, label to the right
            total_w = pin + 4 + label_w
            super().__init__(0, -pin / 2, total_w, pin + 4)
            # position: node.x is pin center
            self.setPos(node.x - pin / 2, node.y)
            pin_x = 0.0
            text_x = pin + 4
        else:
            total_w = pin + 4 + label_w
            super().__init__(-total_w, -pin / 2, total_w, pin + 4)
            self.setPos(node.x + pin / 2, node.y)
            pin_x = -pin
            text_x = -total_w

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(6)
        # transparent hit area; draw pin ourselves via child rect
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setPen(QPen(Qt.PenStyle.NoPen))

        ik = node.meta.get("iface_kind") or "SR"
        if node.meta.get("more"):
            fill = QColor("#757575")
        elif ik == "CS":
            # purple family for Client-Server
            fill = QColor("#6a1b9a") if is_p else QColor("#ad1457")
        else:
            fill = QColor("#2e7d32") if is_p else QColor("#c62828")
        self._default_border = fill
        pin_item = QGraphicsRectItem(pin_x, -pin / 2, pin, pin, self)
        pin_item.setBrush(QBrush(fill))
        pin_item.setPen(QPen(fill.darker(120), 1))
        self._pin_item = pin_item

        font = QFont("Segoe UI", 7)
        full = node.meta.get("full_label") or node.label
        text = _elide(full, font, label_w - 2)
        lab = QGraphicsSimpleTextItem(text, self)
        lab.setFont(font)
        lab.setBrush(QBrush(QColor("#222")))
        br = lab.boundingRect()
        if is_p:
            lab.setPos(text_x, -br.height() / 2)
        else:
            lab.setPos(text_x + (label_w - br.width()), -br.height() / 2)
        self._label_item = lab

        iface = node.meta.get("interface") or ""
        tip = f"{node.port_direction}-{ik}  {full}"
        if iface:
            tip += f"\nIF: {iface}"
        type_lines = node.meta.get("type_lines") or []
        if type_lines:
            tip += "\n" + "\n".join(type_lines)
        if node.meta.get("more"):
            tip = full
        self.setToolTip(tip)

    def paint(self, painter, option, widget=None):
        # Avoid Qt dashed selection rect covering the outside label
        if self.node.kind in ("sr_port", "outer_port"):
            option.state &= ~QStyle.StateFlag.State_Selected
            option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, widget)

    def set_highlight(self, on: bool):
        if self.node.kind in ("sr_port", "outer_port"):
            if hasattr(self, "_pin_item"):
                if on:
                    self._pin_item.setPen(QPen(QColor("#ff6f00"), 2))
                else:
                    self._pin_item.setPen(QPen(self._default_border.darker(120), 1))
            return
        if on:
            self.setPen(QPen(QColor("#ff6f00"), 3))
        else:
            w = 2 if self.node.kind not in ("nested_child",) else 1
            if self.node.kind == "frame":
                w = 2.5
            self.setPen(QPen(self._default_border, w))


class EdgeItem(QGraphicsPathItem):
    def __init__(self, edge: GraphEdge, src: QPointF, tgt: QPointF):
        super().__init__()
        self.edge = edge
        path = QPainterPath(src)
        mid = QPointF((src.x() + tgt.x()) / 2, (src.y() + tgt.y()) / 2 - 12)
        path.quadTo(mid, tgt)
        self.setPath(path)
        if edge.kind == "assembly":
            self.setPen(QPen(QColor("#1565c0"), 1.8, Qt.PenStyle.SolidLine))
        elif edge.kind == "access_send":
            self.setPen(QPen(QColor("#2e7d32"), 1.5, Qt.PenStyle.SolidLine))
        elif edge.kind == "access_recv":
            self.setPen(QPen(QColor("#00838f"), 1.5, Qt.PenStyle.SolidLine))
        elif edge.kind == "access_other":
            self.setPen(QPen(QColor("#546e7a"), 1.2, Qt.PenStyle.DotLine))
        else:
            self.setPen(QPen(QColor("#7b1fa2"), 1.3, Qt.PenStyle.DashLine))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        # Above proto boxes (0/1) so nested Delegation/Assembly stay visible;
        # below port pins (6). Was -1 and got covered by orange/blue fills.
        self.setZValue(5)
        meta = edge.meta or {}
        tip = f"{edge.kind}: {edge.label}"
        if meta.get("dir_label"):
            tip += f"\n方向: {meta['dir_label']}"
        if meta.get("interface"):
            tip += f"\nIF: {meta['interface']}"
        if meta.get("provider_port"):
            tip += f"\n{meta.get('provider_port')} → {meta.get('requester_port')}"
        if meta.get("outer_port"):
            tip += f"\nouter {meta.get('outer_port')} ↔ {meta.get('inner_port')}"
        if meta.get("runnable_path"):
            tip += f"\nRunnable → Port Access"
            if meta.get("data_element"):
                tip += f"\nDE: {meta['data_element']}"
        self.setToolTip(tip)
        self._default_pen = QPen(self.pen())

    def set_highlight(self, on: bool):
        if on:
            self.setPen(QPen(QColor("#ff6f00"), 3, self._default_pen.style()))
        else:
            self.setPen(self._default_pen)


class CompositionView(QGraphicsView):
    node_clicked = Signal(str, str)
    edge_clicked = Signal(str, str)
    drill_into = Signal(str)
    open_in_new_window = Signal(str)  # composition type path
    connect_ports = Signal(str, str)  # from_node_id, to_node_id (Shift+drag)
    navigate_to_port = Signal(str, str)  # port_path, source (primary|peer_file)
    export_swc_requested = Signal(str)  # Application SWC type path
    # Optional: (port_path) -> list[(peer_path, menu_label)]
    peer_lookup = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        # Arrow cursor for easy click-select; pan via middle-drag or empty-area left-drag
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self._node_items: dict[str, NodeItem] = {}
        self._edge_items: dict[str, EdgeItem] = {}
        self._graph: CompositionGraph | None = None
        self.peer_lookup = None
        self._panning = False
        self._pan_last = QPointF()
        self._press_pos = QPointF()
        self._press_hit: NodeItem | EdgeItem | None = None
        self._pan_armed = False  # left press on empty/frame — may become pan
        self._last_selected_drill = ""
        self._connect_armed = False
        self._connect_from: NodeItem | None = None
        self._rubber: QGraphicsLineItem | None = None
        self.connect_mode = False  # if True, drag from port always connects (no Shift)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def set_graph(self, graph: CompositionGraph):
        self._graph = graph
        self._rubber = None
        self._connect_armed = False
        self._connect_from = None
        self._scene.clear()
        self._node_items.clear()
        self._edge_items.clear()

        order = {
            "frame": 0,
            "proto_comp": 1,
            "proto_swc": 2,
            "nested_child": 3,
            "chain_port": 3,
            "runnable": 3,
            "sr_port": 4,
            "outer_port": 5,
        }
        for node in sorted(graph.nodes, key=lambda n: order.get(n.kind, 9)):
            item = NodeItem(node)
            self._scene.addItem(item)
            self._node_items[node.id] = item

        for edge in graph.edges:
            s = self._node_items.get(edge.source)
            t = self._node_items.get(edge.target)
            if not s or not t:
                continue
            # connect to pin centers
            ei = EdgeItem(edge, self._anchor(s), self._anchor(t))
            self._scene.addItem(ei)
            self._edge_items[edge.id] = ei

        br = self._scene.itemsBoundingRect().adjusted(-60, -40, 60, 40)
        self._scene.setSceneRect(br)
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _anchor(self, item: NodeItem) -> QPointF:
        """Connection point: pin center for ports, box center otherwise."""
        n = item.node
        if n.kind in ("sr_port", "outer_port"):
            return QPointF(n.x, n.y)
        return item.pos()

    def highlight_edge(self, edge_id: str | None):
        for eid, item in self._edge_items.items():
            item.set_highlight(eid == edge_id)

    def highlight_node(self, node_id: str | None):
        for nid, item in self._node_items.items():
            item.set_highlight(nid == node_id)

    def highlight_connection(
        self,
        edge_id: str | None = None,
        node_ids: list[str] | None = None,
        focus: bool = True,
    ):
        """Highlight an edge and related nodes; optionally zoom to them."""
        ids = set(node_ids or [])
        # Also highlight endpoints of the edge if present
        edge_item = self._edge_items.get(edge_id) if edge_id else None
        if edge_item is not None:
            ids.add(edge_item.edge.source)
            ids.add(edge_item.edge.target)

        for eid, item in self._edge_items.items():
            item.set_highlight(edge_id is not None and eid == edge_id)
        for nid, item in self._node_items.items():
            item.set_highlight(nid in ids)

        if focus:
            self.focus_on(list(ids), edge_id)

    def resolve_node_id(self, ref: str) -> str | None:
        """Map a model path to a graph node id (handles outer:: / runnable:: / peer / L::)."""
        if not ref:
            return None
        if ref in self._node_items:
            return ref
        for prefix in (
            "outer::",
            "runnable::",
            "peer::",
            "peerstar-focus::",
            "peerstar-peer::",
            "L::focus::",
        ):
            cand = f"{prefix}{ref}"
            if cand in self._node_items:
                return cand
        # Peer-star / remapped chain nodes use L:: / R0:: ids; match meta.port_path
        g = self._graph
        if g:
            prefer_l = None
            any_hit = None
            for n in g.nodes:
                meta = n.meta or {}
                if meta.get("port_path") != ref:
                    continue
                if n.id not in self._node_items:
                    continue
                if n.id.startswith("L::"):
                    prefer_l = n.id
                    break
                if any_hit is None:
                    any_hit = n.id
            if prefer_l:
                return prefer_l
            if any_hit:
                return any_hit
        return None

    def focus_on(self, node_ids: list[str] | None = None, edge_id: str | None = None):
        """Center / fit view on given nodes and optional edge."""
        rect: QRectF | None = None
        for nid in node_ids or []:
            item = self._node_items.get(nid)
            if item is None:
                continue
            br = item.sceneBoundingRect()
            rect = br if rect is None else rect.united(br)
        if edge_id and edge_id in self._edge_items:
            br = self._edge_items[edge_id].sceneBoundingRect()
            rect = br if rect is None else rect.united(br)
        if rect is None or rect.isNull():
            return
        # Pad so labels remain visible
        pad = max(80.0, min(rect.width(), rect.height()) * 0.35 + 40.0)
        target = rect.adjusted(-pad, -pad, pad, pad)
        self.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)
        # Avoid over-zooming tiny connections
        m = self.transform().m11()
        if m > 2.5:
            self.scale(2.5 / m, 2.5 / m)
            self.centerOn(target.center())

    def export_image(self, path: str, scale: float = 2.0) -> bool:
        """Render the whole scene to PNG/JPG. Returns True on success."""
        if self._scene is None:
            return False
        br = self._scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if br.isEmpty():
            return False
        w = max(1, int(br.width() * scale))
        h = max(1, int(br.height() * scale))
        # Cap extreme sizes (e.g. 520 outer ports)
        max_side = 16000
        if w > max_side or h > max_side:
            s = max_side / max(w, h)
            w = max(1, int(w * s))
            h = max(1, int(h * s))
            scale = scale * s
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor("#f5f5f5"))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._scene.render(painter, QRectF(0, 0, w, h), br)
        painter.end()
        return img.save(path)

    def _item_at(self, pos):
        item = self.itemAt(pos)
        cur = item
        while cur is not None:
            if isinstance(cur, (NodeItem, EdgeItem)):
                return cur
            cur = cur.parentItem()
        return None

    def _is_pan_background(self, hit) -> bool:
        """Empty space or composition frame — left-drag pans here."""
        if hit is None:
            return True
        return isinstance(hit, NodeItem) and hit.node.kind == "frame"

    def _is_connectable_port(self, hit) -> bool:
        return (
            isinstance(hit, NodeItem)
            and hit.node.kind in ("sr_port", "outer_port")
            and not hit.node.meta.get("more")
        )

    def _clear_rubber(self):
        if self._rubber is not None:
            self._scene.removeItem(self._rubber)
            self._rubber = None
        self._connect_armed = False
        self._connect_from = None

    def mousePressEvent(self, event):
        hit = self._item_at(event.pos())
        self._press_pos = event.position()
        self._press_hit = hit
        self._pan_armed = False

        # Middle button → pan immediately
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            want_connect = self.connect_mode or bool(
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            )
            if want_connect and self._is_connectable_port(hit):
                # Arm rubber-band only — do NOT emit node_clicked here.
                # Emitting would open/jump to the SR chain view and destroy
                # the structure diagram mid-drag.
                self._connect_armed = True
                self._connect_from = hit
                self.highlight_node(hit.node.id)
                sp = self.mapToScene(event.position().toPoint())
                self._rubber = QGraphicsLineItem(sp.x(), sp.y(), sp.x(), sp.y())
                self._rubber.setPen(QPen(QColor("#ff6f00"), 2, Qt.PenStyle.DashLine))
                self._rubber.setZValue(100)
                self._scene.addItem(self._rubber)
                self.setCursor(Qt.CursorShape.CrossCursor)
                event.accept()
                return
            if self._is_pan_background(hit):
                # defer click vs pan until move/release
                self._pan_armed = True
                self._pan_last = event.position()
                event.accept()
                return
            if isinstance(hit, NodeItem):
                self._remember_drill(hit.node)
                self.node_clicked.emit(hit.node.id, hit.node.kind)
                self.highlight_node(hit.node.id)
            elif isinstance(hit, EdgeItem):
                self.edge_clicked.emit(hit.edge.id, hit.edge.kind)
                self.highlight_edge(hit.edge.id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._connect_armed and self._rubber is not None and self._connect_from:
            sp0 = self._anchor(self._connect_from)
            hit = self._item_at(event.pos())
            # Snap rubber end to valid target port center
            if (
                self._is_connectable_port(hit)
                and hit is not self._connect_from
                and hit.node.id != self._connect_from.node.id
            ):
                sp1 = self._anchor(hit)
                self.highlight_node(hit.node.id)
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                sp1 = self.mapToScene(event.position().toPoint())
                self.highlight_node(self._connect_from.node.id)
            self._rubber.setLine(sp0.x(), sp0.y(), sp1.x(), sp1.y())
            # Valid target → green dash; otherwise orange
            if (
                self._is_connectable_port(hit)
                and hit.node.id != self._connect_from.node.id
            ):
                self._rubber.setPen(QPen(QColor("#2e7d32"), 2.5, Qt.PenStyle.DashLine))
            else:
                self._rubber.setPen(QPen(QColor("#ff6f00"), 2, Qt.PenStyle.DashLine))
            event.accept()
            return
        if self._pan_armed and not self._panning:
            delta = event.position() - self._press_pos
            if abs(delta.x()) + abs(delta.y()) > 4:
                self._panning = True
                self._pan_armed = False
                self._pan_last = event.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._panning:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(int(hbar.value() - delta.x()))
            vbar.setValue(int(vbar.value() - delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self._connect_armed and self._connect_from:
                hit = self._item_at(event.pos())
                src = self._connect_from.node.id
                self._clear_rubber()
                self.setCursor(Qt.CursorShape.ArrowCursor)
                if self._is_connectable_port(hit) and hit.node.id != src:
                    self.connect_ports.emit(src, hit.node.id)
                event.accept()
                return
            if self._panning:
                self._panning = False
                self._pan_armed = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
                event.accept()
                return
            if self._pan_armed:
                # click without drag on empty/frame
                self._pan_armed = False
                hit = self._press_hit
                if isinstance(hit, NodeItem):
                    self.node_clicked.emit(hit.node.id, hit.node.kind)
                    self.highlight_node(hit.node.id)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        hit = self._item_at(event.pos())
        if isinstance(hit, NodeItem):
            n = hit.node
            drill = n.drill_path or (
                n.type_ref if n.kind in ("proto_comp", "nested_child") else ""
            )
            if drill and n.kind in ("proto_comp", "nested_child") and n.type_kind == "COMPOSITION":
                # Ctrl+双击 → 新窗口；普通双击 → 本视图下钻
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self.open_in_new_window.emit(drill)
                else:
                    self.drill_into.emit(drill)
                return
            if drill:
                self.drill_into.emit(drill)
                return
        super().mouseDoubleClickEvent(event)

    def _remember_drill(self, node: GraphNode):
        drill = node.drill_path or (
            node.type_ref if node.kind in ("proto_comp", "nested_child") else ""
        )
        if node.kind in ("proto_comp", "nested_child") and node.type_kind == "COMPOSITION":
            self._last_selected_drill = drill
        else:
            self._last_selected_drill = ""

    def _port_path_of_hit(self, hit) -> str:
        if not isinstance(hit, NodeItem):
            return ""
        n = hit.node
        if n.kind not in ("sr_port", "outer_port", "chain_port"):
            return ""
        pp = (n.meta or {}).get("port_path") or ""
        if pp:
            return pp
        if n.id.startswith("outer::"):
            return n.id.replace("outer::", "", 1)
        if n.id.startswith("chainport::"):
            return ""
        # structure-view SR pin uses port path as node id
        return n.id

    def _on_context_menu(self, pos):
        hit = self._item_at(pos)
        menu = QMenu(self)
        peer_actions: list[tuple] = []
        port_path = self._port_path_of_hit(hit)
        if port_path and callable(self.peer_lookup):
            peers = self.peer_lookup(port_path) or []
            if peers:
                if len(peers) == 1:
                    entry = peers[0]
                    pp, label = entry[0], entry[1]
                    src = entry[2] if len(entry) > 2 else "primary"
                    act = menu.addAction(f"跳转到对端：{label}")
                    peer_actions.append((act, pp, src))
                else:
                    sub = menu.addMenu("跳转到对端")
                    for entry in peers:
                        pp, label = entry[0], entry[1]
                        src = entry[2] if len(entry) > 2 else "primary"
                        act = sub.addAction(label)
                        peer_actions.append((act, pp, src))
                menu.addSeparator()

        drill = ""
        export_swc_path = ""
        export_swc_name = ""
        if isinstance(hit, NodeItem):
            n = hit.node
            drill = n.drill_path or (
                n.type_ref if n.kind in ("proto_comp", "nested_child") else ""
            )
            if not (
                n.kind in ("proto_comp", "nested_child") and n.type_kind == "COMPOSITION"
            ):
                drill = ""
            # Application SWC box / type view
            if n.kind in ("proto_swc",) and (n.type_kind or "") == "APPLICATION" and n.type_ref:
                export_swc_path = n.type_ref
                export_swc_name = n.label or n.type_ref.rsplit("/", 1)[-1]
            elif n.id.startswith("swctype::"):
                export_swc_path = n.id.replace("swctype::", "", 1)
                export_swc_name = n.label or export_swc_path.rsplit("/", 1)[-1]
        if not drill:
            drill = self._last_selected_drill
        act_export = None
        if export_swc_path:
            act_export = menu.addAction(
                f"导出 SWC ARXML（含依赖）: {export_swc_name}"
            )
            menu.addSeparator()
        act_enter = menu.addAction("进入 Composition")
        act_enter.setEnabled(bool(drill))
        act_new = menu.addAction("在新窗口打开")
        act_new.setEnabled(bool(drill))
        if not peer_actions and not drill and not act_export:
            act_enter.setEnabled(False)
            act_new.setEnabled(False)
            if port_path:
                menu.addAction("（无对端可跳转）").setEnabled(False)
            else:
                return
        chosen = menu.exec(self.mapToGlobal(pos))
        for act, pp, src in peer_actions:
            if chosen == act:
                self.navigate_to_port.emit(pp, src)
                return
        if act_export is not None and chosen == act_export:
            self.export_swc_requested.emit(export_swc_path)
            return
        if not drill:
            return
        if chosen == act_enter:
            self.drill_into.emit(drill)
        elif chosen == act_new:
            self.open_in_new_window.emit(drill)
