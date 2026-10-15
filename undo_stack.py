# -*- coding: utf-8 -*-
"""Scoped undo/redo for pending model edits (memory only)."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class UndoFrame:
    label: str
    scope: str
    snapshot: Dict[str, Any] = field(default_factory=dict)


_ALL_ATTRS: Tuple[str, ...] = (
    "pending_edits",
    "assemblies",
    "delegations",
    "ports",
    "swc_types",
    "prototypes",
    "data_mappings",
    "system_signals",
    "i_signals",
    "system_mapping_sets",
    "runnables",
    "rte_events",
    "behaviors_by_swc",
    "interfaces",
    "cs_interfaces",
    "adts",
    "idts",
    "accesses_by_port",
)

_SCOPE_ATTRS: Dict[str, Tuple[str, ...]] = {
    "connector": (
        "pending_edits",
        "assemblies",
        "delegations",
        "ports",
        "swc_types",
        "prototypes",
    ),
    "mapping": (
        "pending_edits",
        "data_mappings",
        "system_signals",
        "i_signals",
        "system_mapping_sets",
    ),
    "ib": (
        "pending_edits",
        "runnables",
        "rte_events",
        "behaviors_by_swc",
        "accesses_by_port",
    ),
    "port": ("pending_edits", "ports", "swc_types"),
    "full": _ALL_ATTRS,
}


def infer_scope(label: str) -> str:
    """Map edit labels to a lightweight snapshot scope."""
    l = (label or "").lower()
    if any(
        k in l
        for k in (
            "assembly",
            "delegation",
            "connect",
            "connector",
            "batch delegated",
            "consistency fix",
        )
    ):
        return "connector"
    if any(k in l for k in ("mapping", "system stub", "system/mapping", "signal")):
        return "mapping"
    if any(
        k in l
        for k in ("runnable", "timing", "event", "symbol", "access", "ib ", "init event")
    ):
        return "ib"
    if "port" in l:
        return "port"
    return "full"


def _snapshot_model(model, attrs: Sequence[str]) -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    for attr in attrs:
        if hasattr(model, attr):
            snap[attr] = deepcopy(getattr(model, attr))
    return snap


def _restore_model(model, snap: Dict[str, Any]) -> None:
    for attr, val in snap.items():
        if hasattr(model, attr):
            setattr(model, attr, val)
    model.build_indexes()


class UndoStack:
    def __init__(self, max_depth: int = 40):
        self._undo: List[UndoFrame] = []
        self._redo: List[UndoFrame] = []
        self._max = max_depth

    def clear(self):
        self._undo.clear()
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, model, label: str, *, scope: str = ""):
        if not model:
            return
        sc = scope or infer_scope(label)
        attrs = _SCOPE_ATTRS.get(sc, _ALL_ATTRS)
        self._undo.append(
            UndoFrame(label=label, scope=sc, snapshot=_snapshot_model(model, attrs))
        )
        self._redo.clear()
        if len(self._undo) > self._max:
            self._undo.pop(0)

    def undo(self, model) -> Optional[str]:
        if not self._undo or not model:
            return None
        frame = self._undo.pop()
        attrs = _SCOPE_ATTRS.get(frame.scope, _ALL_ATTRS)
        self._redo.append(
            UndoFrame(
                label=frame.label,
                scope=frame.scope,
                snapshot=_snapshot_model(model, attrs),
            )
        )
        if len(self._redo) > self._max:
            self._redo.pop(0)
        _restore_model(model, frame.snapshot)
        return frame.label

    def redo(self, model) -> Optional[str]:
        if not self._redo or not model:
            return None
        frame = self._redo.pop()
        attrs = _SCOPE_ATTRS.get(frame.scope, _ALL_ATTRS)
        self._undo.append(
            UndoFrame(
                label=frame.label,
                scope=frame.scope,
                snapshot=_snapshot_model(model, attrs),
            )
        )
        if len(self._undo) > self._max:
            self._undo.pop(0)
        _restore_model(model, frame.snapshot)
        return frame.label


def format_model_scale(model) -> str:
    """Compact scale string for status bar (no heavy RSS dependency)."""
    if not model:
        return ""
    n_ports = len(getattr(model, "ports", {}) or {})
    n_asm = len(getattr(model, "assemblies", []) or [])
    n_del = len(getattr(model, "delegations", []) or [])
    n_comp = len(model.composition_paths()) if hasattr(model, "composition_paths") else 0
    n_app = len(model.application_paths()) if hasattr(model, "application_paths") else 0
    size_mb = 0.0
    fp = getattr(model, "filepath", "") or ""
    if fp:
        try:
            import os

            size_mb = os.path.getsize(fp) / (1024 * 1024)
        except OSError:
            pass
    tip = ""
    if n_ports >= 800 or size_mb >= 20:
        tip = " · 建议 Limit ports"
    return (
        f"规模: {size_mb:.1f}MB Comp={n_comp} App={n_app} "
        f"Asm={n_asm} Del={n_del} Ports={n_ports}{tip}"
    )
