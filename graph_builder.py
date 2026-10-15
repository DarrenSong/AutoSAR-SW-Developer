# -*- coding: utf-8 -*-
"""Build nested Composition block diagrams with SR ports (Vector-style)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Set, Tuple

from .model import ArxmlModel, Port, PortPeer, SrChain, SwcType

# Layout constants
PORT_ROW_H = 16.0
PORT_PIN = 10.0
PORT_LABEL_W = 140.0  # space reserved outside pin for text
BODY_MIN_W = 150.0
BODY_PAD_Y = 36.0  # title area
# Soft defaults only used when limit_ports=True
MAX_PORTS_SIDE = 12
MAX_OUTER_SIDE = 32
NEST_CHILD_W = 88.0
NEST_CHILD_H = 30.0


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str  # frame | proto_swc | proto_comp | nested_child | outer_port | sr_port | chain_port | runnable
    x: float = 0.0
    y: float = 0.0
    w: float = 120.0
    h: float = 48.0
    type_ref: str = ""
    type_kind: str = ""
    port_direction: str = ""  # P | R
    drill_path: str = ""
    parent_id: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    kind: str  # assembly | delegation | access_send | access_recv | access_other
    label: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class CompositionGraph:
    composition_path: str
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    frame_id: str = ""


def _grid_size(n: int) -> Tuple[int, int]:
    if n <= 0:
        return 1, 1
    cols = max(1, min(3, math.ceil(math.sqrt(n))))
    rows = math.ceil(n / cols)
    return rows, cols


def _shorten(name: str, max_len: int = 22) -> str:
    if len(name) <= max_len:
        return name
    return name[: max_len - 1] + "…"


def _split_ports(ports: List[Port]) -> Tuple[List[Port], List[Port]]:
    r_ports = [p for p in ports if p.direction == "R"]
    p_ports = [p for p in ports if p.direction == "P"]
    return r_ports, p_ports


def _prioritize_ports(
    ports: List[Port], hot: Set[str], limit: int
) -> Tuple[List[Port], int]:
    """Hot (connected) ports first; return (visible, hidden_count)."""
    if not ports:
        return [], 0
    hot_list = [p for p in ports if p.path in hot]
    cold = [p for p in ports if p.path not in hot]
    ordered = hot_list + cold
    if len(ordered) <= limit:
        return ordered, 0
    return ordered[:limit], len(ordered) - limit


def _body_size(
    title: str,
    r_vis: int,
    p_vis: int,
    extra_h: float = 0.0,
    min_w: float = BODY_MIN_W,
) -> Tuple[float, float]:
    rows = max(r_vis, p_vis, 1)
    h = BODY_PAD_Y + rows * PORT_ROW_H + 12.0 + extra_h
    # body width enough for title
    tw = max(len(title) * 7.5, min_w)
    w = max(min_w, min(tw, 280.0))
    return w, h


def _box_footprint(body_w: float, body_h: float, has_ports: bool) -> Tuple[float, float]:
    """Total space including port label wings."""
    if not has_ports:
        return body_w + 24.0, body_h + 16.0
    return body_w + 2 * (PORT_LABEL_W + PORT_PIN + 8), body_h + 20.0


def _filter_ports_by_kind(ports: List[Port], kinds: Optional[Set[str]]) -> List[Port]:
    if not kinds:
        return list(ports)
    return [p for p in ports if (p.iface_kind or "SR") in kinds]


def build_swc_type_graph(
    model: ArxmlModel,
    swc_path: str,
    show_ports: bool = True,
    limit_ports: bool = False,
    port_kinds: Optional[Set[str]] = None,
    show_rte_access: bool = True,
    # backward-compat alias
    show_sr_ports: bool | None = None,
) -> CompositionGraph:
    """Single Application/Atomic SWC type view (box + ports + optional RTE Access)."""
    if show_sr_ports is not None:
        show_ports = show_sr_ports
    g = CompositionGraph(composition_path=swc_path)
    swc = model.swc_types.get(swc_path)
    if not swc:
        return g

    side_limit = MAX_PORTS_SIDE if limit_ports else 10_000
    kinds = port_kinds if port_kinds is not None else {"SR", "CS"}
    ports = _filter_ports_by_kind(swc.ports, kinds) if show_ports else []
    r_all, p_all = _split_ports(ports)
    r_vis, r_more = _prioritize_ports(r_all, set(), side_limit)
    p_vis, p_more = _prioritize_ports(p_all, set(), side_limit)
    bw, bh = _body_size(
        swc.name,
        len(r_vis) + (1 if r_more else 0),
        len(p_vis) + (1 if p_more else 0),
    )
    fw, fh = _box_footprint(bw, bh, bool(ports))

    want_access = bool(show_rte_access and swc.kind == "APPLICATION")
    pad_l = PORT_LABEL_W + 48.0
    pad_r = PORT_LABEL_W + 48.0
    pad_t = 48.0
    pad_b = 100.0 if want_access else 40.0
    frame_w = fw + pad_l + pad_r
    frame_h = max(fh, bh + 40) + pad_t + pad_b
    frame_x, frame_y = frame_w / 2.0, frame_h / 2.0

    frame_id = f"frame::{swc_path}"
    g.frame_id = frame_id
    g.nodes.append(
        GraphNode(
            id=frame_id,
            label=swc.name,
            kind="frame",
            x=frame_x,
            y=frame_y,
            w=frame_w,
            h=frame_h,
            type_ref=swc_path,
            type_kind=swc.kind,
            meta={"title": swc.name, "path": swc_path, "swc_type_view": True},
        )
    )

    box_id = f"swctype::{swc_path}"
    # Shift SWC box up a bit when runnables sit below
    cy_off = -18.0 if want_access else 8.0
    cx, cy = frame_x, frame_y + cy_off
    kind = "proto_comp" if swc.kind == "COMPOSITION" else "proto_swc"
    g.nodes.append(
        GraphNode(
            id=box_id,
            label=swc.name,
            kind=kind,
            x=cx,
            y=cy,
            w=bw,
            h=bh,
            type_ref=swc_path,
            type_kind=swc.kind,
            parent_id=frame_id,
            meta={
                "prototype": swc.name,
                "type": swc.name,
                "swc_type_view": True,
                "full_label": swc.name,
            },
        )
    )
    if show_ports:
        _add_box_sr_ports(
            g, box_id, cx, cy, bw, bh, r_vis, p_vis, r_more, p_more, model=model
        )
    if want_access:
        _add_swc_rte_access(g, model, swc_path, cx, cy, bh, limit_ports)
    return g


def _add_swc_rte_access(
    g: CompositionGraph,
    model: ArxmlModel,
    swc_path: str,
    cx: float,
    cy: float,
    body_h: float,
    limit_ports: bool,
) -> None:
    """Runnable nodes below SWC box + Access edges to port pins (SWC type view only)."""
    runnables = []
    for beh in model.behaviors_of_swc(swc_path):
        runnables.extend(beh.runnables)
    if not runnables:
        return

    max_run = 16 if limit_ports else 48
    visible = runnables[:max_run]
    hidden = len(runnables) - len(visible)

    run_w, run_h = 88.0, 28.0
    gap = 12.0
    row_y = cy + body_h / 2 + 44.0
    n = len(visible)
    cols = min(n, 6)
    rows = max(1, math.ceil(n / cols)) if n else 1
    total_w = cols * run_w + max(cols - 1, 0) * gap
    start_x = cx - total_w / 2 + run_w / 2

    port_ids = {n.id for n in g.nodes if n.kind == "sr_port"}
    edge_budget = 60 if limit_ports else 200
    n_edges = 0

    for i, r in enumerate(visible):
        col, row = i % cols, i // cols
        rid = f"runnable::{r.path}"
        g.nodes.append(
            GraphNode(
                id=rid,
                label=_shorten(r.name or "(runnable)", 14),
                kind="runnable",
                x=start_x + col * (run_w + gap),
                y=row_y + row * (run_h + gap),
                w=run_w,
                h=run_h,
                type_ref=r.path,
                meta={
                    "full_label": r.name,
                    "symbol": r.symbol or "",
                    "runnable_path": r.path,
                    "access_count": len(r.accesses),
                },
            )
        )
        for acc in r.accesses:
            if n_edges >= edge_budget:
                break
            port_ref = acc.port_ref or ""
            if not port_ref or port_ref not in port_ids:
                continue
            kind_u = (acc.access_kind or "OTHER").upper()
            if kind_u in ("SEND", "SERVER-CALL"):
                ekind = "access_send"
                elabel = "SEND" if kind_u == "SEND" else "CALL"
            elif kind_u in ("RECEIVE", "RECV"):
                ekind, elabel = "access_recv", "RECV"
            else:
                ekind, elabel = "access_other", (kind_u[:6] or "ACC")
            tgt = acc.data_element_ref or acc.operation_ref
            de_n = tgt.rsplit("/", 1)[-1] if tgt else ""
            eid = f"access::{r.path}::{port_ref}::{elabel}::{de_n or n_edges}"
            g.edges.append(
                GraphEdge(
                    id=eid,
                    source=rid,
                    target=port_ref,
                    kind=ekind,
                    label=elabel + (f".{de_n}" if de_n else ""),
                    meta={
                        "access_kind": kind_u,
                        "port_ref": port_ref,
                        "runnable_path": r.path,
                        "data_element": de_n,
                    },
                )
            )
            n_edges += 1

    if hidden or n_edges >= edge_budget:
        tip_bits = []
        if hidden:
            tip_bits.append(f"+{hidden} runnables")
        if n_edges >= edge_budget:
            tip_bits.append("access capped")
        tip = "; ".join(tip_bits)
        g.nodes.append(
            GraphNode(
                id=f"runnable-more::{swc_path}",
                label=_shorten(tip or "…", 22),
                kind="runnable",
                x=cx,
                y=row_y + rows * (run_h + gap) + 4,
                w=140.0,
                h=22.0,
                meta={"placeholder": True, "full_label": tip},
            )
        )


def build_composition_graph(
    model: ArxmlModel,
    composition_path: str,
    show_delegation: bool = True,
    show_sr_ports: bool = True,
    limit_ports: bool = False,
    max_delegation_edges: int = 80,
    nest_preview: bool = False,
    port_kinds: Optional[Set[str]] = None,
) -> CompositionGraph:
    g = CompositionGraph(composition_path=composition_path)
    swc = model.swc_types.get(composition_path)
    if not swc or swc.kind != "COMPOSITION":
        return g

    hot_ports = _collect_hot_ports(model, composition_path)
    protos = list(swc.prototypes)
    side_limit = MAX_PORTS_SIDE if limit_ports else 10_000
    outer_limit = MAX_OUTER_SIDE if limit_ports else 10_000
    allowed_kinds = port_kinds if port_kinds is not None else {"SR", "CS"}

    # Precompute each proto body size + footprint
    sizes: List[Tuple[float, float]] = []  # footprint w,h for layout cells
    body_sizes: List[Tuple[float, float]] = []
    kinds: List[str] = []
    port_plans: List[dict] = []

    for proto in protos:
        t = model.swc_types.get(proto.type_ref)
        tkind = t.kind if t else ""
        kinds.append(tkind)
        ports = (
            _filter_ports_by_kind(t.ports, allowed_kinds)
            if t and show_sr_ports
            else []
        )
        # For nested composition preview, prefer that type's outer ports
        r_all, p_all = _split_ports(ports)
        r_vis, r_more = _prioritize_ports(r_all, hot_ports, side_limit)
        p_vis, p_more = _prioritize_ports(p_all, hot_ports, side_limit)
        extra = 0.0
        if tkind == "COMPOSITION" and nest_preview and t is not None:
            nc = min(len(t.prototypes), 8)
            nr, nc2 = _grid_size(max(nc, 1))
            extra = 10 + nr * (NEST_CHILD_H + 6)
        bw, bh = _body_size(proto.name, len(r_vis) + (1 if r_more else 0), len(p_vis) + (1 if p_more else 0), extra)
        body_sizes.append((bw, bh))
        fw, fh = _box_footprint(bw, bh, bool(ports))
        sizes.append((fw, fh))
        port_plans.append(
            {"r_vis": r_vis, "p_vis": p_vis, "r_more": r_more, "p_more": p_more}
        )

    n = max(len(protos), 1)
    rows, cols = _grid_size(n)
    gap_x, gap_y = 48.0, 56.0
    col_w = [0.0] * cols
    row_h = [0.0] * rows
    for i, (w, h) in enumerate(sizes):
        r, c = i // cols, i % cols
        col_w[c] = max(col_w[c], w)
        row_h[r] = max(row_h[r], h)

    content_w = sum(col_w) + gap_x * max(cols - 1, 0)
    content_h = sum(row_h) + gap_y * max(rows - 1, 0)
    grid_h = content_h

    # Margins leave room for outer port labels outside the frame
    outer_label_band = PORT_LABEL_W + 28.0
    pad_l = outer_label_band + 40.0
    pad_r = outer_label_band + 40.0
    pad_t, pad_b = 56.0, 48.0
    # Ensure enough height so outer-port labels don't stack on top of each other
    if show_sr_ports and swc.ports:
        r_all, p_all = _split_ports(swc.ports)
        r_n = min(len(r_all), outer_limit) + (1 if len(r_all) > outer_limit else 0)
        p_n = min(len(p_all), outer_limit) + (1 if len(p_all) > outer_limit else 0)
        outer_side = max(r_n, p_n, 1)
        min_h_for_outers = (outer_side + 1) * (PORT_ROW_H + 2) + pad_t + pad_b
        content_h = max(content_h, min_h_for_outers - pad_t - pad_b)
    frame_w = content_w + pad_l + pad_r
    frame_h = content_h + pad_t + pad_b
    frame_x, frame_y = frame_w / 2.0, frame_h / 2.0

    frame_id = f"frame::{composition_path}"
    g.frame_id = frame_id
    g.nodes.append(
        GraphNode(
            id=frame_id,
            label=swc.name,
            kind="frame",
            x=frame_x,
            y=frame_y,
            w=frame_w,
            h=frame_h,
            type_ref=composition_path,
            type_kind="COMPOSITION",
            meta={"title": swc.name, "path": composition_path},
        )
    )

    # Place outer SR ports of THIS composition on the frame edge
    if show_sr_ports:
        _add_frame_sr_ports(
            g,
            model,
            swc,
            frame_id,
            frame_w,
            frame_h,
            hot_ports,
            outer_limit,
            allowed_kinds,
        )

    # Center prototype grid inside the content area (extra height is for outer ports)
    origin_x = pad_l
    origin_y = pad_t + max(0.0, (content_h - grid_h) / 2.0)
    x_offs, acc = [], 0.0
    for c in range(cols):
        x_offs.append(acc)
        acc += col_w[c] + gap_x
    y_offs, acc = [], 0.0
    for r in range(rows):
        y_offs.append(acc)
        acc += row_h[r] + gap_y

    for i, proto in enumerate(protos):
        r, c = i // cols, i % cols
        fw, fh = sizes[i]
        bw, bh = body_sizes[i]
        cx = origin_x + x_offs[c] + col_w[c] / 2
        cy = origin_y + y_offs[r] + row_h[r] / 2
        t = model.swc_types.get(proto.type_ref)
        tkind = kinds[i]
        plan = port_plans[i]

        if tkind == "COMPOSITION":
            kind = "proto_comp"
            drill = proto.type_ref
        else:
            kind = "proto_swc"
            drill = ""

        g.nodes.append(
            GraphNode(
                id=proto.path,
                label=proto.name,
                kind=kind,
                x=cx,
                y=cy,
                w=bw,
                h=bh,
                type_ref=proto.type_ref,
                type_kind=tkind or "APPLICATION",
                drill_path=drill,
                parent_id=frame_id,
                meta={
                    "prototype": proto.name,
                    "type": model.resolve_name(proto.type_ref),
                    "hint": "双击进入内部" if kind == "proto_comp" else "",
                },
            )
        )

        if show_sr_ports and t is not None:
            _add_box_sr_ports(
                g,
                proto.path,
                cx,
                cy,
                bw,
                bh,
                plan["r_vis"],
                plan["p_vis"],
                plan["r_more"],
                plan["p_more"],
                model=model,
            )

        if kind == "proto_comp" and nest_preview and t is not None:
            _add_nested_children(g, model, t, proto.path, cx, cy, bw, bh)

    # Assembly: prefer port-to-port if both ends exist as nodes
    node_ids = {n.id for n in g.nodes}
    for a in model.assemblies_by_comp.get(composition_path, []):
        if not a.provider_proto_ref or not a.requester_proto_ref:
            continue
        src = a.provider_port_ref if a.provider_port_ref in node_ids else a.provider_proto_ref
        tgt = a.requester_port_ref if a.requester_port_ref in node_ids else a.requester_proto_ref
        iface_name = ""
        pport = model.ports.get(a.provider_port_ref)
        if pport and pport.interface_ref in model.interfaces:
            iface_name = model.interfaces[pport.interface_ref].name
        g.edges.append(
            GraphEdge(
                id=a.path or a.name,
                source=src,
                target=tgt,
                kind="assembly",
                label=a.name,
                meta={
                    "connector": a.name,
                    "provider_port": model.resolve_name(a.provider_port_ref),
                    "requester_port": model.resolve_name(a.requester_port_ref),
                    "interface": iface_name,
                    "provider_port_path": a.provider_port_ref,
                    "requester_port_path": a.requester_port_ref,
                },
            )
        )

    if show_delegation:
        _add_delegation_edges(g, model, composition_path, max_delegation_edges, node_ids)

    return g


def _collect_hot_ports(model: ArxmlModel, composition_path: str) -> Set[str]:
    hot: Set[str] = set()
    for a in model.assemblies_by_comp.get(composition_path, []):
        if a.provider_port_ref:
            hot.add(a.provider_port_ref)
        if a.requester_port_ref:
            hot.add(a.requester_port_ref)
    for d in model.delegations_by_comp.get(composition_path, []):
        if d.outer_port_ref:
            hot.add(d.outer_port_ref)
        if d.inner_port_ref:
            hot.add(d.inner_port_ref)
    return hot


def _add_box_sr_ports(
    g: CompositionGraph,
    owner_id: str,
    cx: float,
    cy: float,
    bw: float,
    bh: float,
    r_vis: List[Port],
    p_vis: List[Port],
    r_more: int,
    p_more: int,
    model: Optional[ArxmlModel] = None,
):
    left = cx - bw / 2
    right = cx + bw / 2
    top = cy - bh / 2 + BODY_PAD_Y

    def place(ports: List[Port], more: int, is_p: bool):
        total = len(ports) + (1 if more else 0)
        for idx, port in enumerate(ports):
            y = top + idx * PORT_ROW_H + PORT_ROW_H / 2
            if is_p:
                x = right + PORT_PIN / 2
            else:
                x = left - PORT_PIN / 2
            type_lines = (
                model.port_sr_type_lines(port.path) if model else []
            )
            g.nodes.append(
                GraphNode(
                    id=port.path,
                    label=port.name,
                    kind="sr_port",
                    x=x,
                    y=y,
                    w=PORT_PIN,
                    h=PORT_PIN,
                    port_direction=port.direction,
                    parent_id=owner_id,
                    meta={
                        "port_path": port.path,
                        "interface": port.interface_ref,
                        "owner": owner_id,
                        "full_label": port.name,
                        "iface_kind": port.iface_kind or "SR",
                        "type_lines": type_lines,
                    },
                )
            )
        if more:
            y = top + len(ports) * PORT_ROW_H + PORT_ROW_H / 2
            x = right + PORT_PIN / 2 if is_p else left - PORT_PIN / 2
            g.nodes.append(
                GraphNode(
                    id=f"moreport::{owner_id}::{'P' if is_p else 'R'}",
                    label=f"+{more}",
                    kind="sr_port",
                    x=x,
                    y=y,
                    w=PORT_PIN,
                    h=PORT_PIN,
                    port_direction="P" if is_p else "R",
                    parent_id=owner_id,
                    meta={"more": more, "owner": owner_id},
                )
            )

    place(r_vis, r_more, False)
    place(p_vis, p_more, True)


def _add_frame_sr_ports(
    g: CompositionGraph,
    model: ArxmlModel,
    swc: SwcType,
    frame_id: str,
    frame_w: float,
    frame_h: float,
    hot: Set[str],
    outer_limit: int,
    port_kinds: Optional[Set[str]] = None,
):
    """Outer ports on composition frame — labels sit outside so they are not clipped."""
    filtered = _filter_ports_by_kind(swc.ports, port_kinds or {"SR", "CS"})
    r_all, p_all = _split_ports(filtered)
    r_vis, r_more = _prioritize_ports(r_all, hot, outer_limit)
    p_vis, p_more = _prioritize_ports(p_all, hot, outer_limit)

    def place(ports: List[Port], more: int, is_p: bool):
        n = len(ports) + (1 if more else 0)
        if n == 0:
            return
        for idx, port in enumerate(ports):
            frac = (idx + 1) / (n + 1)
            y = frac * frame_h
            # pin on frame edge; label drawn outside in the scene
            x = frame_w if is_p else 0.0
            g.nodes.append(
                GraphNode(
                    id=f"outer::{port.path}",
                    label=port.name,
                    kind="outer_port",
                    x=x,
                    y=y,
                    w=12.0,
                    h=12.0,
                    port_direction=port.direction,
                    parent_id=frame_id,
                    meta={
                        "port_path": port.path,
                        "interface": port.interface_ref,
                        "full_label": port.name,
                        "label_outside": True,
                        "iface_kind": port.iface_kind or "SR",
                        "type_lines": model.port_sr_type_lines(port.path),
                    },
                )
            )
        if more:
            frac = (len(ports) + 1) / (n + 1)
            y = frac * frame_h
            x = frame_w if is_p else 0.0
            g.nodes.append(
                GraphNode(
                    id=f"outer-more::{frame_id}::{'P' if is_p else 'R'}",
                    label=f"+{more} ports",
                    kind="outer_port",
                    x=x,
                    y=y,
                    w=12.0,
                    h=12.0,
                    port_direction="P" if is_p else "R",
                    parent_id=frame_id,
                    meta={"more": more, "full_label": f"+{more} more ports", "label_outside": True},
                )
            )

    place(r_vis, r_more, False)
    place(p_vis, p_more, True)


def _add_nested_children(
    g: CompositionGraph,
    model: ArxmlModel,
    nested: SwcType,
    parent_proto_id: str,
    cx: float,
    cy: float,
    bw: float,
    bh: float,
):
    children = nested.prototypes[:8]
    if not children:
        return
    n = len(children)
    rows, cols = _grid_size(n)
    gap = 6.0
    grid_w = cols * NEST_CHILD_W + (cols - 1) * gap
    left = cx - grid_w / 2
    # place near bottom of body below title/ports area
    top = cy + bh / 2 - 12 - rows * (NEST_CHILD_H + gap)

    for i, ch in enumerate(children):
        r, c = i // cols, i % cols
        nx = left + c * (NEST_CHILD_W + gap) + NEST_CHILD_W / 2
        ny = top + r * (NEST_CHILD_H + gap) + NEST_CHILD_H / 2
        t = model.swc_types.get(ch.type_ref)
        tkind = t.kind if t else "APPLICATION"
        g.nodes.append(
            GraphNode(
                id=f"nested::{parent_proto_id}::{ch.path}",
                label=ch.name,
                kind="nested_child",
                x=nx,
                y=ny,
                w=NEST_CHILD_W,
                h=NEST_CHILD_H,
                type_ref=ch.type_ref,
                type_kind=tkind,
                drill_path=ch.type_ref if tkind == "COMPOSITION" else "",
                parent_id=parent_proto_id,
                meta={"prototype": ch.name, "full_label": ch.name},
            )
        )
    if len(nested.prototypes) > 8:
        g.nodes.append(
            GraphNode(
                id=f"nested::{parent_proto_id}::more",
                label=f"+{len(nested.prototypes) - 8} more",
                kind="nested_child",
                x=cx,
                y=cy + bh / 2 - 10,
                w=90,
                h=16,
                parent_id=parent_proto_id,
                meta={"more": True, "full_label": f"+{len(nested.prototypes) - 8} more"},
            )
        )


def _add_delegation_edges(
    g: CompositionGraph,
    model: ArxmlModel,
    composition_path: str,
    max_edges: int,
    node_ids: Set[str],
):
    drawn = 0
    for d in model.delegations_by_comp.get(composition_path, []):
        if drawn >= max_edges:
            break
        if not d.outer_port_ref:
            continue
        outer_id = f"outer::{d.outer_port_ref}"
        if outer_id not in node_ids:
            continue
        # prefer inner port node, else proto
        if d.inner_port_ref and d.inner_port_ref in node_ids:
            inner = d.inner_port_ref
        elif d.inner_proto_ref and d.inner_proto_ref in node_ids:
            inner = d.inner_proto_ref
        else:
            continue
        if d.inner_direction == "P":
            src, tgt = inner, outer_id
        else:
            src, tgt = outer_id, inner
        g.edges.append(
            GraphEdge(
                id=d.path or d.name,
                source=src,
                target=tgt,
                kind="delegation",
                label=d.name,
                meta={
                    "connector": d.name,
                    "outer_port": model.resolve_name(d.outer_port_ref),
                    "inner_port": model.resolve_name(d.inner_port_ref),
                    "inner_proto": model.resolve_name(d.inner_proto_ref),
                    "direction": d.inner_direction,
                },
            )
        )
        drawn += 1


@dataclass
class _NestBox:
    """Internal nest tree for Vector-style chain diagram."""
    box_id: str
    label: str
    kind: str  # frame | proto_comp | proto_swc
    type_ref: str = ""
    proto_path: str = ""
    ports: List[str] = field(default_factory=list)
    children: List["_NestBox"] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


def _ensure_child_box(
    model: ArxmlModel, parent: _NestBox, proto_path: str
) -> Optional[_NestBox]:
    if not proto_path:
        return None
    for ch in parent.children:
        if ch.proto_path == proto_path:
            return ch
    proto = model.prototypes.get(proto_path)
    if not proto:
        return None
    t = model.swc_types.get(proto.type_ref)
    tkind = t.kind if t else "APPLICATION"
    if tkind == "COMPOSITION":
        kind = "proto_comp"
    else:
        kind = "proto_swc"
    box = _NestBox(
        box_id=f"chainbox::{proto_path}",
        label=proto.name,
        kind=kind,
        type_ref=proto.type_ref,
        proto_path=proto_path,
    )
    parent.children.append(box)
    return box


def _add_port_unique(box: _NestBox, port_path: str):
    if port_path and port_path not in box.ports:
        box.ports.append(port_path)


def _climb_to_root_composition(model: ArxmlModel, comp: str) -> str:
    """Walk parent prototypes until a composition that is not nested further."""
    cur = comp or ""
    seen: Set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        parents = model.parent_protos_of_comp.get(cur, [])
        if not parents:
            return cur
        nxt = parents[0].composition_path
        if not nxt:
            return cur
        cur = nxt
    return comp or ""


def _collect_chain_compositions(model: ArxmlModel, chain: SrChain) -> Set[str]:
    comps: Set[str] = set()
    if chain.start_composition:
        comps.add(chain.start_composition)
    if chain.start_port:
        p = model.ports.get(chain.start_port)
        if p:
            owner = model.swc_types.get(p.owner_path)
            if owner and owner.kind == "COMPOSITION":
                comps.add(p.owner_path)
    for hop in chain.hops:
        if hop.composition_path:
            comps.add(hop.composition_path)
        for pref in (hop.from_proto, hop.to_proto, chain.start_proto):
            if not pref:
                continue
            pr = model.prototypes.get(pref)
            if not pr:
                continue
            if pr.composition_path:
                comps.add(pr.composition_path)
            t = model.swc_types.get(pr.type_ref)
            if t and t.kind == "COMPOSITION":
                comps.add(pr.type_ref)
    return comps


def _pick_chain_root_composition(model: ArxmlModel, chain: SrChain) -> str:
    comps = _collect_chain_compositions(model, chain)
    if not comps:
        return ""
    # Climb every involved composition; prefer a true product root
    climbed = {_climb_to_root_composition(model, c) for c in comps}
    seed = chain.start_composition or next(iter(comps))
    root = _climb_to_root_composition(model, seed)
    if root in climbed:
        return root
    return next(iter(climbed))


def _instance_proto_of_comp(
    model: ArxmlModel, comp_type: str, hint_proto: str = ""
) -> str:
    """Pick a SWC-PROTOTYPE path whose type is comp_type (nested instance)."""
    if hint_proto:
        pr = model.prototypes.get(hint_proto)
        if pr and pr.type_ref == comp_type:
            return hint_proto
    parents = model.parent_protos_of_comp.get(comp_type, [])
    if len(parents) == 1:
        return parents[0].path
    if hint_proto:
        # hint may be a child proto living inside comp_type
        hp = model.prototypes.get(hint_proto)
        if hp and hp.composition_path == comp_type:
            for p in parents:
                if p.composition_path == hp.composition_path:
                    continue
                # parent instance of comp_type in grandparent
                return p.path
            if parents:
                return parents[0].path
    return parents[0].path if parents else ""


def _ensure_comp_box(
    model: ArxmlModel,
    root: _NestBox,
    root_comp: str,
    comp_type: str,
    hint_proto: str = "",
) -> _NestBox:
    """
    Ensure a nest box for composition type `comp_type` exists under root,
    creating intermediate nested Composition prototypes as needed.
    """
    if not comp_type or comp_type == root_comp or comp_type == root.type_ref:
        return root
    # Already present?
    def find(box: _NestBox) -> Optional[_NestBox]:
        if box.type_ref == comp_type:
            return box
        for ch in box.children:
            hit = find(ch)
            if hit:
                return hit
        return None

    existing = find(root)
    if existing:
        return existing

    proto_path = _instance_proto_of_comp(model, comp_type, hint_proto)
    if not proto_path:
        return root
    pr = model.prototypes.get(proto_path)
    if not pr:
        return root
    parent_comp = pr.composition_path or root_comp
    parent_box = _ensure_comp_box(model, root, root_comp, parent_comp, "")
    return _ensure_child_box(model, parent_box, proto_path) or parent_box


def _ensure_proto_under_comp(
    model: ArxmlModel,
    root: _NestBox,
    root_comp: str,
    proto_path: str,
) -> Optional[_NestBox]:
    if not proto_path:
        return None
    pr = model.prototypes.get(proto_path)
    if not pr:
        return None
    parent = _ensure_comp_box(
        model, root, root_comp, pr.composition_path or root_comp, proto_path
    )
    return _ensure_child_box(model, parent, proto_path)


def _build_chain_nest_tree(model: ArxmlModel, chain: SrChain) -> Optional[_NestBox]:
    """
    Build multi-level nest: Top → Mid → App for full Delegation chains.
    Root frame is the outermost composition that covers all hops.
    """
    root_comp = _pick_chain_root_composition(model, chain)
    if not root_comp and chain.start_port:
        p = model.ports.get(chain.start_port)
        if p:
            owner = model.swc_types.get(p.owner_path)
            if owner and owner.kind == "COMPOSITION":
                root_comp = p.owner_path
            else:
                # application type view — single box
                root = _NestBox(
                    box_id=f"chainbox::swc::{p.owner_path}",
                    label=model.resolve_name(p.owner_path),
                    kind="proto_swc",
                    type_ref=p.owner_path,
                )
                _add_port_unique(root, chain.start_port)
                for hop in chain.hops:
                    _add_port_unique(root, hop.from_port)
                    _add_port_unique(root, hop.to_port)
                return root
    if not root_comp:
        return None

    swc = model.swc_types.get(root_comp)
    root = _NestBox(
        box_id=f"chainbox::root::{root_comp}",
        label=swc.name if swc else model.resolve_name(root_comp),
        kind="frame",
        type_ref=root_comp,
    )

    # Place start port on the correct nest box
    sp = model.ports.get(chain.start_port)
    if sp:
        owner_swc = model.swc_types.get(sp.owner_path)
        if owner_swc and owner_swc.kind == "COMPOSITION":
            box = _ensure_comp_box(model, root, root_comp, sp.owner_path, "")
            _add_port_unique(box, chain.start_port)
        elif chain.start_proto:
            box = _ensure_proto_under_comp(model, root, root_comp, chain.start_proto)
            if box:
                _add_port_unique(box, chain.start_port)
            else:
                _add_port_unique(root, chain.start_port)
        else:
            _add_port_unique(root, chain.start_port)

    for hop in chain.hops:
        comp = hop.composition_path or root_comp
        hint = hop.from_proto or hop.to_proto or chain.start_proto
        parent = _ensure_comp_box(model, root, root_comp, comp, hint)
        if hop.kind == "delegation":
            from_port = model.ports.get(hop.from_port)
            # Outer port of this composition ↔ inner proto port
            from_is_outer = bool(
                from_port and from_port.owner_path == comp
            )
            if from_is_outer:
                _add_port_unique(parent, hop.from_port)
                child = _ensure_proto_under_comp(
                    model, root, root_comp, hop.to_proto
                ) or _ensure_child_box(model, parent, hop.to_proto)
                if child:
                    _add_port_unique(child, hop.to_port)
                else:
                    _add_port_unique(parent, hop.to_port)
            else:
                child = _ensure_proto_under_comp(
                    model, root, root_comp, hop.from_proto
                ) or _ensure_child_box(model, parent, hop.from_proto)
                if child:
                    _add_port_unique(child, hop.from_port)
                else:
                    _add_port_unique(parent, hop.from_port)
                _add_port_unique(parent, hop.to_port)
        else:
            # assembly: ports live on sibling prototypes, not on the frame
            ca = _ensure_proto_under_comp(
                model, root, root_comp, hop.from_proto
            ) or _ensure_child_box(model, parent, hop.from_proto)
            cb = _ensure_proto_under_comp(
                model, root, root_comp, hop.to_proto
            ) or _ensure_child_box(model, parent, hop.to_proto)
            if ca:
                _add_port_unique(ca, hop.from_port)
            if cb:
                _add_port_unique(cb, hop.to_port)
    return root


def _layout_nest_box(box: _NestBox, model: ArxmlModel) -> None:
    """Bottom-up size, then caller assigns positions."""
    pad_l, pad_r, pad_t, pad_b = 56.0, 56.0, 48.0, 28.0
    gap = 28.0
    port_band = max(len(box.ports), 1) * (PORT_ROW_H + 2)

    if not box.children:
        # leaf SWC / empty composition
        n_ports = max(len(box.ports), 1)
        box.w = max(BODY_MIN_W, 120.0 + PORT_LABEL_W * 0.3)
        box.h = max(64.0, BODY_PAD_Y + n_ports * PORT_ROW_H + 16.0)
        return

    for ch in box.children:
        _layout_nest_box(ch, model)

    # children in a row
    kids_w = sum(ch.w for ch in box.children) + gap * (len(box.children) - 1)
    kids_h = max(ch.h for ch in box.children)
    box.w = max(kids_w + pad_l + pad_r, BODY_MIN_W + 80)
    box.h = max(kids_h + pad_t + pad_b, port_band + pad_t + pad_b)


def _place_nest_box(box: _NestBox, cx: float, cy: float) -> None:
    box.x, box.y = cx, cy
    if not box.children:
        return
    pad_l, pad_t = 56.0, 48.0
    gap = 28.0
    kids_w = sum(ch.w for ch in box.children) + gap * (len(box.children) - 1)
    kids_h = max(ch.h for ch in box.children)
    left = cx - kids_w / 2
    # vertically center children in content area below title
    content_top = cy - box.h / 2 + pad_t
    content_h = box.h - pad_t - 28.0
    mid_y = content_top + content_h / 2
    x = left
    for ch in box.children:
        _place_nest_box(ch, x + ch.w / 2, mid_y)
        x += ch.w + gap


def _emit_nest_nodes(
    g: CompositionGraph,
    model: ArxmlModel,
    box: _NestBox,
    port_node_ids: Dict[str, str],
) -> None:
    """Emit box + its ports; fill port_node_ids[port_path]=node_id (last wins)."""
    drill = box.type_ref if box.kind == "proto_comp" else ""
    g.nodes.append(
        GraphNode(
            id=box.box_id,
            label=box.label,
            kind=box.kind,
            x=box.x,
            y=box.y,
            w=box.w,
            h=box.h,
            type_ref=box.type_ref,
            type_kind=(
                model.swc_types[box.type_ref].kind
                if box.type_ref in model.swc_types
                else ""
            ),
            drill_path=drill,
            meta={
                "title": box.label,
                "path": box.type_ref,
                "proto_path": box.proto_path,
                "sr_chain_view": box.kind == "frame",
                "nested_chain": True,
                "hint": "链路嵌套 Composition" if box.kind == "proto_comp" else "",
            },
        )
    )
    # ports on left (R) / right (P)
    r_ports = []
    p_ports = []
    for pp in box.ports:
        port = model.ports.get(pp)
        if port and port.direction == "P":
            p_ports.append(pp)
        else:
            r_ports.append(pp)

    def place_side(paths: List[str], is_p: bool):
        n = max(len(paths), 1)
        for idx, pp in enumerate(paths):
            port = model.ports.get(pp)
            frac = (idx + 1) / (n + 1)
            y = box.y - box.h / 2 + frac * box.h
            x = box.x + box.w / 2 if is_p else box.x - box.w / 2
            is_outer = box.kind == "frame" or (
                port is not None and port.owner_path == box.type_ref
            )
            kind = "outer_port" if is_outer and box.kind in ("frame", "proto_comp") else "sr_port"
            nid = f"chainport::{box.box_id}::{pp}"
            port_node_ids[pp] = nid
            g.nodes.append(
                GraphNode(
                    id=nid,
                    label=model.resolve_name(pp),
                    kind=kind,
                    x=x,
                    y=y,
                    w=PORT_PIN if kind == "sr_port" else 12.0,
                    h=PORT_PIN if kind == "sr_port" else 12.0,
                    port_direction=port.direction if port else ("P" if is_p else "R"),
                    parent_id=box.box_id,
                    meta={
                        "port_path": pp,
                        "full_label": model.resolve_name(pp),
                        "label_outside": True,
                        "iface_kind": (port.iface_kind if port else "SR") or "SR",
                        "owner": box.box_id,
                        "chain_view": True,
                        "nested_chain": True,
                    },
                )
            )

    place_side(r_ports, False)
    place_side(p_ports, True)

    for ch in box.children:
        _emit_nest_nodes(g, model, ch, port_node_ids)


def build_sr_chain_graph(model: ArxmlModel, chain: SrChain) -> CompositionGraph:
    """
    Vector-style nested Composition diagram for one SR/CS chain.

    Outer frame = root composition; child orange boxes = nested compositions;
    blue boxes = application SWCs; purple dashed = Delegation, blue = Assembly.
    """
    g = CompositionGraph(composition_path=chain.start_composition or chain.start_port)
    if not chain.start_port and not chain.hops:
        return g

    root = _build_chain_nest_tree(model, chain)
    if root is None:
        return g

    _layout_nest_box(root, model)
    # place root centered
    _place_nest_box(root, root.w / 2 + 40.0, root.h / 2 + 40.0)

    port_node_ids: Dict[str, str] = {}
    _emit_nest_nodes(g, model, root, port_node_ids)
    g.frame_id = root.box_id

    # Update root frame title
    for n in g.nodes:
        if n.id == root.box_id and n.kind == "frame":
            start_name = model.resolve_name(chain.start_port)
            n.label = f"{root.label}  ·  Chain: {start_name}"
            n.meta["title"] = n.label
            n.meta["sr_chain_view"] = True
            n.meta["nested_chain"] = True
            break

    # Edges: map hop endpoints to port nodes (label includes P→R / 同向)
    for i, hop in enumerate(chain.hops):
        sid = port_node_ids.get(hop.from_port)
        tid = port_node_ids.get(hop.to_port)
        if not sid or not tid:
            continue
        fp = model.ports.get(hop.from_port)
        tp = model.ports.get(hop.to_port)
        fd = (fp.direction if fp else "?") or "?"
        td = (tp.direction if tp else "?") or "?"
        if hop.kind == "assembly":
            dir_lbl = f"{fd}→{td}"
        elif fd == td:
            dir_lbl = f"同向{fd}"
        else:
            dir_lbl = f"{fd}/{td}"
        edge_label = f"{hop.connector_name} [{dir_lbl}]" if hop.connector_name else dir_lbl
        g.edges.append(
            GraphEdge(
                id=hop.connector_path or f"chainhop::{i}::{hop.connector_name}",
                source=sid,
                target=tid,
                kind=hop.kind,
                label=edge_label,
                meta={
                    "connector": hop.connector_name,
                    "connector_path": hop.connector_path,
                    "composition": hop.composition_path,
                    "interface": hop.interface,
                    "from_port": hop.from_port,
                    "to_port": hop.to_port,
                    "from_proto": hop.from_proto,
                    "to_proto": hop.to_proto,
                    "hop_index": i,
                    "dir_label": dir_lbl,
                    "chain_view": True,
                    "nested_chain": True,
                },
            )
        )
    return g


def _pick_best_chain(model: ArxmlModel, port_path: str) -> Optional[SrChain]:
    chains = [c for c in model.trace_sr_port(port_path) if c.hops or c.start_port]
    if not chains:
        return None
    return max(chains, key=lambda c: (len(c.hops), len(c.endpoints)))


def _graph_bbox(g: CompositionGraph) -> Tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y) of node centers ± half size."""
    if not g.nodes:
        return 0.0, 0.0, 0.0, 0.0
    xs0, ys0, xs1, ys1 = [], [], [], []
    for n in g.nodes:
        xs0.append(n.x - n.w / 2)
        ys0.append(n.y - n.h / 2)
        xs1.append(n.x + n.w / 2)
        ys1.append(n.y + n.h / 2)
    return min(xs0), min(ys0), max(xs1), max(ys1)


def _shift_remap_graph(
    src: CompositionGraph,
    *,
    id_prefix: str,
    dx: float,
    dy: float,
    side_tag: str,
) -> Tuple[CompositionGraph, Dict[str, str], Dict[str, str]]:
    """
    Copy graph with id prefix + translation.
    Returns (graph, old_id→new_id, port_path→new_node_id).
    """
    out = CompositionGraph(composition_path=src.composition_path)
    id_map: Dict[str, str] = {n.id: f"{id_prefix}{n.id}" for n in src.nodes}
    port_nodes: Dict[str, str] = {}
    for n in src.nodes:
        nid = id_map[n.id]
        meta = dict(n.meta or {})
        meta["peer_star_side"] = side_tag
        parent = id_map.get(n.parent_id, "") if n.parent_id else ""
        nn = replace(
            n,
            id=nid,
            x=n.x + dx,
            y=n.y + dy,
            parent_id=parent,
            meta=meta,
        )
        out.nodes.append(nn)
        pp = meta.get("port_path") or ""
        if pp and n.kind in ("sr_port", "outer_port", "chain_port"):
            port_nodes[pp] = nid
    for e in src.edges:
        sid = id_map.get(e.source, f"{id_prefix}{e.source}")
        tid = id_map.get(e.target, f"{id_prefix}{e.target}")
        meta = dict(e.meta or {})
        meta["peer_star_side"] = side_tag
        out.edges.append(
            replace(
                e,
                id=f"{id_prefix}{e.id}",
                source=sid,
                target=tid,
                meta=meta,
            )
        )
    if src.frame_id:
        out.frame_id = id_map.get(src.frame_id, f"{id_prefix}{src.frame_id}")
    return out, id_map, port_nodes


def build_peer_star_graph(
    model: ArxmlModel,
    port_path: str,
    peer_model: Optional[ArxmlModel] = None,
    *,
    max_peers: int = 12,
    max_full_peers: int = 1,
    expand_peer_indices: Optional[Set[int]] = None,
    lift_application: bool = True,
) -> CompositionGraph:
    """
    1:N 对端视图：本侧嵌套链路 + 各对端嵌套链路并排。

    - Application 口默认沿 Delegation 抬到最外层 Composition Port 再找对端。
    - 默认只展开 max_full_peers 条对端全链；其余显示可点「展开」占位（性能）。
    """
    g = CompositionGraph(composition_path=port_path or "peer_star")
    seed = port_path
    if lift_application and seed:
        seed = model.lift_port_for_peer_view(seed)
    port = model.ports.get(seed)
    if not port:
        return g
    port_path = seed  # use lifted focus for peers / chains

    peers: List[PortPeer] = [
        p
        for p in model.find_port_peers(port_path, peer_model=peer_model)
        if p.relation in ("assembly", "direction_pair", "cross_file")
    ][:max_peers]
    if expand_peer_indices is None:
        expand = set(range(min(max_full_peers, len(peers))))
    else:
        expand = set(expand_peer_indices)
        # keep at least the first max_full_peers expanded
        expand |= set(range(min(max_full_peers, len(peers))))

    focus_name = model.resolve_name(port_path)
    pad = 48.0
    gap_x = 100.0
    gap_y = 56.0

    # --- left: focus nested chain ---
    focus_chain = _pick_best_chain(model, port_path)
    focus_port_nodes: Dict[str, str] = {}
    left_g: Optional[CompositionGraph] = None
    if focus_chain:
        raw = build_sr_chain_graph(model, focus_chain)
        x0, y0, x1, y1 = _graph_bbox(raw)
        left_g, _, focus_port_nodes = _shift_remap_graph(
            raw,
            id_prefix="L::",
            dx=pad - x0,
            dy=pad + 36.0 - y0,
            side_tag="focus",
        )
        for n in left_g.nodes:
            if n.kind == "frame":
                n.meta["peer_star_view"] = True
                n.meta["peer_star_focus"] = True
                n.label = f"本侧 {port.direction}  ·  {focus_name}"
                n.meta["title"] = n.label

    # Fallback: no hops — still show a single port box
    if left_g is None or not left_g.nodes:
        left_g = CompositionGraph(composition_path=port_path)
        fid = f"L::focus::{port_path}"
        left_g.nodes.append(
            GraphNode(
                id=fid,
                label=_shorten(focus_name, 20),
                kind="chain_port",
                x=pad + 100,
                y=pad + 80,
                w=160,
                h=48,
                port_direction=port.direction,
                meta={
                    "port_path": port_path,
                    "full_label": focus_name,
                    "iface_kind": port.iface_kind or "SR",
                    "peer_star_focus": True,
                    "composition": model.resolve_name(port.owner_path),
                },
            )
        )
        focus_port_nodes[port_path] = fid

    lx0, ly0, lx1, ly1 = _graph_bbox(left_g)
    left_w = max(lx1 - lx0, 200.0)
    left_h = max(ly1 - ly0, 120.0)

    # --- right: each peer nested chain stacked (lazy: collapsed = stub) ---
    peer_graphs: List[Tuple[PortPeer, CompositionGraph, Dict[str, str]]] = []
    right_top = pad + 36.0
    for i, peer in enumerate(peers):
        src = (
            peer_model
            if peer.source == "peer_file" and peer_model
            else model
        )
        if not src or peer.port_path not in src.ports:
            continue
        # lift peer application ports too (same-file)
        peer_focus = peer.port_path
        if lift_application and peer.source != "peer_file":
            peer_focus = src.lift_port_for_peer_view(peer.port_path)
        pport = src.ports.get(peer_focus) or src.ports[peer.port_path]
        pname = src.resolve_name(peer_focus)
        src_tag = "对照" if peer.source == "peer_file" else "本文件"
        full = i in expand
        if full:
            chain = _pick_best_chain(src, peer_focus)
            if chain:
                raw = build_sr_chain_graph(src, chain)
                rx0, ry0, rx1, ry1 = _graph_bbox(raw)
                dx = lx1 + gap_x - rx0
                dy = right_top - ry0
                pg, _, pnodes = _shift_remap_graph(
                    raw,
                    id_prefix=f"R{i}::",
                    dx=dx,
                    dy=dy,
                    side_tag=f"peer{i}",
                )
                for n in pg.nodes:
                    if n.kind == "frame":
                        n.label = (
                            f"对端{i + 1} {pport.direction}  ·  {pname}  "
                            f"[{peer.relation}/{src_tag}]"
                        )
                        n.meta["title"] = n.label
                        n.meta["peer_star_view"] = True
                # ensure link target uses lifted path key
                if peer_focus not in pnodes and peer.port_path in pnodes:
                    pnodes[peer_focus] = pnodes[peer.port_path]
                pnodes["_link_port"] = peer_focus
                peer_graphs.append((peer, pg, pnodes))
                _, _, _, pry1 = _graph_bbox(pg)
                right_top = pry1 + gap_y
                continue
        # collapsed stub or empty chain
        nid = f"R{i}::stub::{peer_focus}"
        stub = CompositionGraph(composition_path=peer_focus)
        stub_label = (
            f"对端{i + 1} {pport.direction}-{_shorten(pname, 14)}  "
            f"[点击展开全链]"
            if not full
            else _shorten(pname, 20)
        )
        stub.nodes.append(
            GraphNode(
                id=nid,
                label=stub_label,
                kind="chain_port",
                x=lx1 + gap_x + 120,
                y=right_top + 30,
                w=200,
                h=52,
                port_direction=pport.direction,
                meta={
                    "port_path": peer_focus,
                    "full_label": (
                        f"{pname}\n{peer.relation}/{src_tag}\n"
                        + ("双击/点击展开嵌套链路" if not full else "")
                    ),
                    "iface_kind": pport.iface_kind or "SR",
                    "peer_relation": peer.relation,
                    "peer_source": peer.source,
                    "composition": src.resolve_name(pport.owner_path),
                    "peer_star_stub": not full,
                    "peer_star_index": i,
                    "peer_star_expandable": not full,
                },
            )
        )
        peer_graphs.append(
            (peer, stub, {peer_focus: nid, "_link_port": peer_focus})
        )
        right_top += 52 + gap_y

    # merge
    for n in left_g.nodes:
        g.nodes.append(n)
    for e in left_g.edges:
        g.edges.append(e)
    for peer, pg, pnodes in peer_graphs:
        for n in pg.nodes:
            g.nodes.append(n)
        for e in pg.edges:
            g.edges.append(e)

    # link focus port ↔ each peer port (prefer exact path node)
    focus_nid = focus_port_nodes.get(port_path)
    if not focus_nid:
        # any node carrying focus path
        for n in g.nodes:
            if (n.meta or {}).get("port_path") == port_path and n.id.startswith("L::"):
                focus_nid = n.id
                break

    for i, (peer, _pg, pnodes) in enumerate(peer_graphs):
        link_port = pnodes.get("_link_port") or peer.port_path
        peer_nid = pnodes.get(link_port) or pnodes.get(peer.port_path)
        if not peer_nid:
            for n in g.nodes:
                if (n.meta or {}).get("port_path") == link_port and n.id.startswith(
                    f"R{i}::"
                ):
                    peer_nid = n.id
                    break
        if not focus_nid or not peer_nid:
            continue
        if peer.relation == "assembly":
            ekind = "assembly"
        elif peer.relation == "cross_file":
            ekind = "access_other"
        else:
            ekind = "delegation"
        g.edges.append(
            GraphEdge(
                id=f"peerlink::{port_path}::{link_port}::{i}",
                source=focus_nid,
                target=peer_nid,
                kind=ekind,
                label=f"P↔R {peer.relation}",
                meta={
                    "dir_label": "P↔R",
                    "peer_relation": peer.relation,
                    "peer_source": peer.source,
                    "peer_star_link": True,
                },
            )
        )

    if not peers:
        g.nodes.append(
            GraphNode(
                id="peerstar-empty",
                label="(无 P↔R 对端)",
                kind="chain_port",
                x=lx1 + gap_x + 80,
                y=pad + 80,
                w=160,
                h=40,
                meta={"full_label": "无 assembly / 同名_P↔_R / 对照文件对端"},
            )
        )

    # outer title frame
    bx0, by0, bx1, by1 = _graph_bbox(g)
    fw = (bx1 - bx0) + pad * 2
    fh = (by1 - by0) + pad * 2 + 28
    # shift everything into frame with top band for title
    title_band = 40.0
    shift_x = pad - bx0
    shift_y = pad + title_band - by0
    for n in g.nodes:
        n.x += shift_x
        n.y += shift_y

    n_peer = len(peer_graphs)
    n_full = sum(1 for i, _ in enumerate(peers) if i in expand)
    n_stub = max(0, n_peer - n_full)
    stub_note = f"  ·  已展开{n_full}/折叠{n_stub}（点占位展开）" if n_stub else ""
    title = (
        f"1:N 对端链路  ·  本侧 {port.direction}-{focus_name}  ·  "
        f"{n_peer} 个对端{stub_note}"
    )
    frame_id = f"peerstar-frame::{port_path}"
    g.frame_id = frame_id
    g.nodes.insert(
        0,
        GraphNode(
            id=frame_id,
            label=title,
            kind="frame",
            x=fw / 2,
            y=(fh + title_band) / 2,
            w=fw,
            h=fh + title_band,
            type_ref=port.owner_path,
            meta={
                "peer_star_view": True,
                "title": title,
                "path": port_path,
                "sr_chain_view": True,
                "nested_chain": True,
            },
        ),
    )
    return g
