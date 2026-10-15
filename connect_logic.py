# -*- coding: utf-8 -*-
"""Resolve graph port-to-port drag into Assembly or Delegation create args."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .graph_builder import CompositionGraph, GraphNode
from .model import ArxmlModel


@dataclass
class ConnectPlan:
    kind: str  # assembly | delegation
    composition_path: str
    # assembly
    provider_proto: str = ""
    provider_port: str = ""
    requester_proto: str = ""
    requester_port: str = ""
    # delegation
    outer_port: str = ""
    inner_proto: str = ""
    inner_port: str = ""
    suggested_name: str = ""
    warning: str = ""


def _node(graph: CompositionGraph, nid: str) -> Optional[GraphNode]:
    for n in graph.nodes:
        if n.id == nid:
            return n
    return None


def _port_path(n: GraphNode) -> str:
    return n.meta.get("port_path") or (
        n.id.replace("outer::", "", 1) if n.id.startswith("outer::") else n.id
    )


def plan_connection(
    model: ArxmlModel,
    graph: CompositionGraph,
    composition_path: str,
    from_id: str,
    to_id: str,
) -> tuple[Optional[ConnectPlan], str]:
    """
    Returns (plan, error). error non-empty means cannot connect.
    """
    a = _node(graph, from_id)
    b = _node(graph, to_id)
    if not a or not b:
        return None, "未找到端口节点"
    if a.kind not in ("sr_port", "outer_port") or b.kind not in ("sr_port", "outer_port"):
        return None, "只能连接 Port 针脚"

    pa = model.ports.get(_port_path(a))
    pb = model.ports.get(_port_path(b))
    if not pa or not pb:
        return None, "Port 不在模型中"

    # Normalize: outer + inner → delegation; two inners → assembly
    outer_n = inner_n = None
    if a.kind == "outer_port" and b.kind == "sr_port":
        outer_n, inner_n = a, b
    elif b.kind == "outer_port" and a.kind == "sr_port":
        outer_n, inner_n = b, a

    if outer_n and inner_n:
        outer = model.ports.get(_port_path(outer_n))
        inner = model.ports.get(_port_path(inner_n))
        proto = inner_n.parent_id or ""
        if not outer or not inner:
            return None, "Delegation 端点无效"
        if outer.direction != inner.direction:
            return None, f"Delegation 要求同向 (Outer={outer.direction}, Inner={inner.direction})"
        if not proto or proto.startswith("frame::"):
            return None, "无法解析 Inner Prototype"
        warn = ""
        if (
            outer.interface_ref
            and inner.interface_ref
            and outer.interface_ref != inner.interface_ref
        ):
            warn = "内外接口不一致"
        pname = model.resolve_name(proto)
        plan = ConnectPlan(
            kind="delegation",
            composition_path=composition_path,
            outer_port=outer.path,
            inner_proto=proto,
            inner_port=inner.path,
            suggested_name=f"{pname}_{inner.name}_to_{outer.name}_DG",
            warning=warn,
        )
        return plan, ""

    if a.kind == "sr_port" and b.kind == "sr_port":
        # Assembly: need one P and one R on different prototypes
        if pa.direction == pb.direction:
            return None, f"Assembly 需要 P→R，当前均为 {pa.direction}"
        if a.parent_id == b.parent_id:
            return None, "不能连接同一 Prototype 上的端口"
        if pa.direction == "P":
            p_proto, p_port, r_proto, r_port = a.parent_id, pa.path, b.parent_id, pb.path
        else:
            p_proto, p_port, r_proto, r_port = b.parent_id, pb.path, a.parent_id, pa.path
        warn = ""
        if (
            pa.interface_ref
            and pb.interface_ref
            and pa.interface_ref != pb.interface_ref
        ):
            warn = "接口不一致"
        pp = model.resolve_name(p_proto)
        rp = model.resolve_name(r_proto)
        plan = ConnectPlan(
            kind="assembly",
            composition_path=composition_path,
            provider_proto=p_proto,
            provider_port=p_port,
            requester_proto=r_proto,
            requester_port=r_port,
            suggested_name=f"{pp}_{model.resolve_name(p_port)}_to_{rp}_{model.resolve_name(r_port)}",
            warning=warn,
        )
        return plan, ""

    return None, "不支持的连接组合（外端口之间请用 Delegation 对到内部 Port）"
