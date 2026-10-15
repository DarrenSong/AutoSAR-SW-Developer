# -*- coding: utf-8 -*-
"""Cross-file (primary ↔ peer) half-chain / P↔R pairing helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .model import ArxmlModel, PortPeer


@dataclass
class CrossChainHop:
    side: str  # primary | peer
    direction: str
    port_path: str
    label: str
    relation: str = ""


def build_cross_file_chain(
    model: ArxmlModel,
    port_path: str,
    peer_model: Optional[ArxmlModel],
) -> List[CrossChainHop]:
    """
    Build a readable primary→peer half-chain:
      local SR hops (as port sequence) + matched peer P↔R ports.
    """
    hops: List[CrossChainHop] = []
    if not model or port_path not in model.ports:
        return hops
    port = model.ports[port_path]
    hops.append(
        CrossChainHop(
            "primary",
            port.direction,
            port_path,
            f"{model.resolve_name(port.owner_path)}.{port.name}",
            "start",
        )
    )
    # Walk local chain endpoints
    chains = model.trace_sr_port(port_path)
    if chains:
        ch = max(chains, key=lambda c: len(c.hops))
        for h in ch.hops:
            tp = model.ports.get(h.to_port)
            hops.append(
                CrossChainHop(
                    "primary",
                    (tp.direction if tp else "?") or "?",
                    h.to_port,
                    h.to_label(model),
                    h.kind,
                )
            )

    if not peer_model:
        return hops

    peers = model.find_port_peers(port_path, peer_model=peer_model)
    cross = [p for p in peers if p.source == "peer_file"]
    for p in cross[:6]:
        pp = peer_model.ports.get(p.port_path)
        hops.append(
            CrossChainHop(
                "peer",
                (pp.direction if pp else "?") or "?",
                p.port_path,
                p.label,
                p.relation,
            )
        )
        # Also append peer-side chain end if any
        if pp:
            pchains = peer_model.trace_sr_port(p.port_path)
            if pchains:
                pch = max(pchains, key=lambda c: len(c.hops))
                if pch.endpoints:
                    ep = pch.endpoints[0]
                    epo = peer_model.ports.get(ep)
                    hops.append(
                        CrossChainHop(
                            "peer",
                            (epo.direction if epo else "?") or "?",
                            ep,
                            f"{peer_model.resolve_name(epo.owner_path) if epo else ''}."
                            f"{peer_model.resolve_name(ep)}",
                            "chain_end",
                        )
                    )
    return hops


def format_cross_chain(hops: List[CrossChainHop]) -> List[str]:
    lines = ["跨文件半链 / 对端路径:"]
    if not hops:
        lines.append("  (无)")
        return lines
    for i, h in enumerate(hops):
        lines.append(
            f"  {i + 1}. [{h.side}] {h.direction}  {h.label}  ({h.relation})"
        )
    return lines


def collect_pr_orphan_rows(
    model: ArxmlModel, peer_model: Optional[ArxmlModel] = None
) -> List[dict]:
    """Rows for P↔R CSV export."""
    from .checks import _check_direction_orphans

    issues = _check_direction_orphans(model, peer_model)
    rows = []
    for iss in issues:
        if iss.category != "P↔R":
            continue
        rows.append(
            {
                "severity": iss.severity,
                "message": iss.message,
                "path": iss.path,
            }
        )
    return rows
