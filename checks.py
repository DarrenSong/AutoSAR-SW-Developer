# -*- coding: utf-8 -*-
"""Consistency checks for ARXML model (beyond pure viewing)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

from .model import ArxmlModel

if TYPE_CHECKING:
    from .os_rte import OsRteOverlay


@dataclass
class CheckIssue:
    severity: str  # error | warning | info
    category: str
    message: str
    path: str = ""
    kind: str = ""  # tree selection kind hint
    # batch-fixable actions
    fix_action: str = ""  # delete_connector | ""
    fix_label: str = ""
    fix_composition: str = ""
    fix_connector_kind: str = ""  # assembly | delegation
    fix_connector_name: str = ""
    fix_target: str = "primary"  # primary | peer


def _check_assemblies(model: ArxmlModel, *, target: str = "primary") -> List[CheckIssue]:
    issues: List[CheckIssue] = []
    tag = "[对照] " if target == "peer" else ""
    for a in model.assemblies:
        p = model.ports.get(a.provider_port_ref)
        r = model.ports.get(a.requester_port_ref)
        if not p or not r:
            issues.append(
                CheckIssue(
                    "error",
                    "Assembly",
                    f"{tag}连接端点 Port 缺失: {a.name}",
                    a.path or a.name,
                    "assembly",
                    fix_action="delete_connector",
                    fix_label="删除该 Assembly",
                    fix_composition=a.composition_path,
                    fix_connector_kind="assembly",
                    fix_connector_name=a.name,
                    fix_target=target,
                )
            )
            continue
        if p.direction != "P" or r.direction != "R":
            issues.append(
                CheckIssue(
                    "error",
                    "Assembly",
                    f"{tag}方向错误 (需 P→R): {a.name}",
                    a.path or a.name,
                    "assembly",
                    fix_action="delete_connector",
                    fix_label="删除该 Assembly",
                    fix_composition=a.composition_path,
                    fix_connector_kind="assembly",
                    fix_connector_name=a.name,
                    fix_target=target,
                )
            )
        if p.interface_ref and r.interface_ref and p.interface_ref != r.interface_ref:
            issues.append(
                CheckIssue(
                    "warning",
                    "Assembly",
                    f"{tag}接口不一致: {a.name}  "
                    f"P={model.resolve_name(p.interface_ref)} "
                    f"R={model.resolve_name(r.interface_ref)}",
                    a.path or a.name,
                    "assembly",
                    fix_target=target,
                )
            )
        elif p.iface_kind and r.iface_kind and p.iface_kind != r.iface_kind:
            issues.append(
                CheckIssue(
                    "warning",
                    "Assembly",
                    f"{tag}接口类型不一致 ({p.iface_kind}/{r.iface_kind}): {a.name}",
                    a.path or a.name,
                    "assembly",
                    fix_target=target,
                )
            )
    return issues


def _check_delegations(model: ArxmlModel, *, target: str = "primary") -> List[CheckIssue]:
    issues: List[CheckIssue] = []
    tag = "[对照] " if target == "peer" else ""
    for d in model.delegations:
        outer = model.ports.get(d.outer_port_ref)
        inner = model.ports.get(d.inner_port_ref)
        if not outer or not inner:
            issues.append(
                CheckIssue(
                    "error",
                    "Delegation",
                    f"{tag}外/内 Port 缺失: {d.name}",
                    d.path or d.name,
                    "delegation",
                    fix_action="delete_connector",
                    fix_label="删除该 Delegation",
                    fix_composition=d.composition_path,
                    fix_connector_kind="delegation",
                    fix_connector_name=d.name,
                    fix_target=target,
                )
            )
            continue
        if outer.direction and inner.direction and outer.direction != inner.direction:
            issues.append(
                CheckIssue(
                    "warning",
                    "Delegation",
                    f"{tag}内外 Port 方向不一致: {d.name} "
                    f"({outer.direction}/{inner.direction})",
                    d.path or d.name,
                    "delegation",
                    fix_target=target,
                )
            )
        if (
            outer.interface_ref
            and inner.interface_ref
            and outer.interface_ref != inner.interface_ref
        ):
            issues.append(
                CheckIssue(
                    "warning",
                    "Delegation",
                    f"{tag}内外接口不一致: {d.name}",
                    d.path or d.name,
                    "delegation",
                    fix_target=target,
                )
            )
    return issues


def run_consistency_checks(
    model: ArxmlModel,
    peer_model: ArxmlModel | None = None,
    os_rte: Optional["OsRteOverlay"] = None,
) -> List[CheckIssue]:
    issues: List[CheckIssue] = []
    if not model:
        return issues

    issues.extend(_check_assemblies(model, target="primary"))
    issues.extend(_check_delegations(model, target="primary"))
    if peer_model:
        issues.extend(_check_assemblies(peer_model, target="peer"))
        issues.extend(_check_delegations(peer_model, target="peer"))
    if os_rte is not None:
        issues.extend(_check_os_rte(model, os_rte))

    unconn: List[CheckIssue] = []
    for port in model.ports.values():
        owner = model.swc_types.get(port.owner_path)
        if not owner or owner.kind != "APPLICATION":
            continue
        if model.assemblies_by_port.get(port.path) or model.delegations_by_port.get(
            port.path
        ):
            continue
        unconn.append(
            CheckIssue(
                "info",
                "Port",
                f"Application Port 无 Assembly/Delegation: "
                f"{owner.name}.{port.name} ({port.direction}-{port.iface_kind})",
                port.path,
                "port",
            )
        )
    if len(unconn) > 50:
        issues.extend(unconn[:50])
        issues.append(
            CheckIssue(
                "info",
                "Port",
                f"另有 {len(unconn) - 50} 个未连接 Application Port（已截断）",
                "",
                "port",
            )
        )
    else:
        issues.extend(unconn)

    for adt in model.adts.values():
        if adt.path not in model.idt_by_adt:
            issues.append(
                CheckIssue(
                    "warning",
                    "ADT",
                    f"ADT 无 IDT 映射: {adt.name} ({adt.kind})",
                    adt.path,
                    "adt",
                )
            )

    for idt in model.idts.values():
        if (idt.category or "").upper() == "VALUE" and not idt.base_type_ref:
            issues.append(
                CheckIssue(
                    "warning",
                    "IDT",
                    f"VALUE IDT 无 BaseType: {idt.name}",
                    idt.path,
                    "idt",
                )
            )

    for ev in model.rte_events.values():
        if not ev.name and not ev.start_on_runnable_ref:
            continue
        if ev.start_on_runnable_ref and ev.start_on_runnable_ref not in model.runnables:
            issues.append(
                CheckIssue(
                    "error",
                    "RTE",
                    f"Event 指向不存在的 Runnable: {ev.name or ev.path}",
                    ev.path,
                    "rte_event",
                )
            )
        elif ev.name and not ev.start_on_runnable_ref:
            issues.append(
                CheckIssue(
                    "warning",
                    "RTE",
                    f"Event 无 START-ON-EVENT-REF: {ev.name}",
                    ev.path,
                    "rte_event",
                )
            )

    for r in model.runnables.values():
        if not r.name:
            continue
        if not r.triggered_by:
            issues.append(
                CheckIssue(
                    "info",
                    "RTE",
                    f"Runnable 无触发 Event: {r.name}",
                    r.path,
                    "runnable",
                )
            )

    for iface in model.interfaces.values():
        for de in iface.data_elements:
            if de.type_ref and de.type_ref not in model.adts and de.type_ref not in model.idts:
                issues.append(
                    CheckIssue(
                        "warning",
                        "SR-IF",
                        f"DataElement 类型未解析: {iface.name}.{de.name} → {de.type_ref}",
                        de.path or iface.path,
                        "sr_interface",
                    )
                )

    # Empty Internal Behavior stubs
    for swc_path, blist in model.behaviors_by_swc.items():
        for b in blist:
            if b.is_empty:
                issues.append(
                    CheckIssue(
                        "warning",
                        "RTE",
                        f"空壳 Internal Behavior: {b.name or '(unnamed)'} @ "
                        f"{model.resolve_name(swc_path)}",
                        b.path,
                        "behavior",
                    )
                )

    # Application ports with connectors but no Runnable PortAccess
    n_no_rte = 0
    for port in model.ports.values():
        owner = model.swc_types.get(port.owner_path)
        if not owner or owner.kind != "APPLICATION":
            continue
        if not (
            model.assemblies_by_port.get(port.path)
            or model.delegations_by_port.get(port.path)
        ):
            continue
        if model.accesses_by_port.get(port.path):
            continue
        # only flag if SWC has non-empty IB
        behs = model.behaviors_of_swc(port.owner_path)
        if not behs or all(b.is_empty for b in behs):
            continue
        n_no_rte += 1
        if n_no_rte <= 40:
            issues.append(
                CheckIssue(
                    "info",
                    "RTE",
                    f"Port 已连线但无 Runnable Access: "
                    f"{owner.name}.{port.name}",
                    port.path,
                    "port",
                )
            )
    if n_no_rte > 40:
        issues.append(
            CheckIssue(
                "info",
                "RTE",
                f"另有 {n_no_rte - 40} 个已连线但无 Access 的 Port（已截断）",
                "",
                "port",
            )
        )

    # Data mapping dangling refs
    for dm in model.data_mappings:
        if dm.port_ref and dm.port_ref not in model.ports:
            issues.append(
                CheckIssue(
                    "error",
                    "Mapping",
                    f"Mapping Port REF 悬空: {dm.name} → {dm.port_ref}",
                    dm.path,
                    "data_mapping",
                    fix_action="delete_data_mapping",
                    fix_label="删除该 Data Mapping",
                    fix_connector_name=dm.path,
                )
            )
        if dm.signal_ref and (
            dm.signal_ref not in model.system_signals
            and dm.signal_ref not in model.i_signals
        ):
            issues.append(
                CheckIssue(
                    "warning",
                    "Mapping",
                    f"Mapping Signal REF 未解析: {dm.name} → {dm.signal_ref}",
                    dm.path,
                    "data_mapping",
                )
            )
        if dm.component_ref and dm.component_ref not in model.prototypes:
            issues.append(
                CheckIssue(
                    "warning",
                    "Mapping",
                    f"Mapping Component REF 悬空: {dm.name}",
                    dm.path,
                    "data_mapping",
                )
            )

    # Composition outer ports not used by any Delegation (info, capped)
    n_orphan_outer = 0
    for port in model.ports.values():
        owner = model.swc_types.get(port.owner_path)
        if not owner or owner.kind != "COMPOSITION":
            continue
        if model.delegations_by_port.get(port.path):
            continue
        n_orphan_outer += 1
        if n_orphan_outer <= 30:
            issues.append(
                CheckIssue(
                    "info",
                    "Delegation",
                    f"Composition 外端口无 Delegation: "
                    f"{owner.name}.{port.name} ({port.direction})",
                    port.path,
                    "port",
                )
            )
    if n_orphan_outer > 30:
        issues.append(
            CheckIssue(
                "info",
                "Delegation",
                f"另有 {n_orphan_outer - 30} 个无 Delegation 的外端口（已截断）",
                "",
                "port",
            )
        )

    # P without R / R without P (name heuristic + optional peer file)
    issues.extend(_check_direction_orphans(model, peer_model))

    # File-level export defects (ADT/IDT/UUID fixable via tool_gui scripts;
    # empty CS / N:M reported with backdoor only)
    from .export_defect_checks import run_export_defect_checks

    issues.extend(run_export_defect_checks(model.filepath or ""))

    return issues


def _check_os_rte(model: ArxmlModel, os_rte: "OsRteOverlay") -> List[CheckIssue]:
    """Validate sidecar OsTask / Runnable→Task mappings against the ARXML model."""
    issues: List[CheckIssue] = []
    if not os_rte.tasks and not os_rte.mappings:
        return issues

    task_names = {t.name for t in os_rte.tasks}
    for m in os_rte.mappings:
        if m.task not in task_names:
            issues.append(
                CheckIssue(
                    "error",
                    "OsRTE",
                    f"Mapping 指向未知 Task: {m.task} "
                    f"({model.resolve_name(m.swc_prototype)}."
                    f"{model.resolve_name(m.runnable)})",
                    m.runnable,
                    "runnable",
                )
            )
        if m.swc_prototype and m.swc_prototype not in model.prototypes:
            issues.append(
                CheckIssue(
                    "error",
                    "OsRTE",
                    f"Mapping Prototype 悬空: {m.swc_prototype}",
                    m.swc_prototype,
                    "prototype",
                )
            )
        if m.runnable and m.runnable not in model.runnables:
            issues.append(
                CheckIssue(
                    "error",
                    "OsRTE",
                    f"Mapping Runnable 悬空: {m.runnable}",
                    m.runnable,
                    "runnable",
                )
            )

    # Same (proto, runnable) mapped to multiple tasks
    seen: dict = {}
    for m in os_rte.mappings:
        key = (m.swc_prototype, m.runnable)
        if key in seen and seen[key] != m.task:
            issues.append(
                CheckIssue(
                    "warning",
                    "OsRTE",
                    f"同一 Runnable 映射到多个 Task: "
                    f"{model.resolve_name(m.swc_prototype)}."
                    f"{model.resolve_name(m.runnable)} → "
                    f"{seen[key]} 与 {m.task}",
                    m.runnable,
                    "runnable",
                )
            )
        else:
            seen[key] = m.task

    # Empty tasks
    for t in os_rte.tasks:
        if not os_rte.mappings_by_task(t.name):
            issues.append(
                CheckIssue(
                    "info",
                    "OsRTE",
                    f"OS Task 无 Runnable Mapping: {t.name}",
                    "",
                    "os_task",
                )
            )

    # Application prototypes with non-empty IB runnables but no mapping
    mapped = {(m.swc_prototype, m.runnable) for m in os_rte.mappings}
    mapped_runnables = {m.runnable for m in os_rte.mappings}
    n_unmapped = 0
    n_access_no_task = 0
    n_map_no_access = 0
    for proto in model.prototypes.values():
        swc = model.swc_types.get(proto.type_ref)
        if not swc or swc.kind != "APPLICATION":
            continue
        behs = model.behaviors_of_swc(proto.type_ref)
        if not behs or all(b.is_empty for b in behs):
            continue
        for beh in behs:
            for r in beh.runnables:
                has_map = (proto.path, r.path) in mapped
                has_acc = bool(r.accesses)
                if not has_map:
                    n_unmapped += 1
                    if n_unmapped <= 40:
                        issues.append(
                            CheckIssue(
                                "info",
                                "OsRTE",
                                f"Runnable 未映射到 OS Task: "
                                f"{proto.name}.{r.name}",
                                r.path,
                                "runnable",
                            )
                        )
                    if has_acc:
                        n_access_no_task += 1
                        if n_access_no_task <= 30:
                            issues.append(
                                CheckIssue(
                                    "warning",
                                    "OsRTE",
                                    f"有 Port Access 但未映射 Task: "
                                    f"{proto.name}.{r.name} "
                                    f"(accesses={len(r.accesses)})",
                                    r.path,
                                    "runnable",
                                )
                            )
                elif not has_acc:
                    n_map_no_access += 1
                    if n_map_no_access <= 20:
                        issues.append(
                            CheckIssue(
                                "info",
                                "OsRTE",
                                f"已映射 Task 但无 Port Access: "
                                f"{proto.name}.{r.name}",
                                r.path,
                                "runnable",
                            )
                        )
    if n_unmapped > 40:
        issues.append(
            CheckIssue(
                "info",
                "OsRTE",
                f"另有 {n_unmapped - 40} 个未映射 Runnable（已截断）",
                "",
                "runnable",
            )
        )
    # Orphan mappings already covered; flag runnables mapped but not in any proto type IB — skip
    _ = mapped_runnables
    return issues


def _port_stem(name: str) -> str:
    if name.endswith(("_DG_P", "_DG_R")):
        return name[:-5]
    if name.endswith(("_P", "_R")):
        return name[:-2]
    return name


def _index_ports_by_stem(model: ArxmlModel) -> dict:
    by: dict = {}
    for p in model.ports.values():
        if p.iface_kind and p.iface_kind not in ("SR", "CS", ""):
            continue
        stem = _port_stem(p.name)
        by.setdefault(stem, {"P": [], "R": []})
        if p.direction in ("P", "R"):
            by[stem][p.direction].append(p)
    return by


def _check_direction_orphans(
    model: ArxmlModel, peer_model: ArxmlModel | None
) -> List[CheckIssue]:
    """Flag stems that have only P or only R across primary (+ peer) files."""
    issues: List[CheckIssue] = []
    primary = _index_ports_by_stem(model)
    peer = _index_ports_by_stem(peer_model) if peer_model else {}
    stems = set(primary) | set(peer)
    n_p_only = n_r_only = 0
    for stem in sorted(stems):
        ps = list(primary.get(stem, {}).get("P", []))
        rs = list(primary.get(stem, {}).get("R", []))
        if peer_model:
            ps.extend(peer.get(stem, {}).get("P", []))
            rs.extend(peer.get(stem, {}).get("R", []))
        # Skip stems with neither side meaningful
        if not ps and not rs:
            continue
        if ps and not rs:
            n_p_only += 1
            if n_p_only <= 40:
                sample = ps[0]
                src = (
                    "对照"
                    if peer_model and sample.path not in model.ports
                    else "本文件"
                )
                issues.append(
                    CheckIssue(
                        "warning",
                        "P↔R",
                        f"有 P 无 R（stem={stem}）@ {src}: "
                        f"{model.resolve_name(sample.owner_path) if sample.path in model.ports else (peer_model.resolve_name(sample.owner_path) if peer_model else '')}"
                        f".{sample.name}",
                        sample.path if sample.path in model.ports else "",
                        "port",
                    )
                )
        elif rs and not ps:
            n_r_only += 1
            if n_r_only <= 40:
                sample = rs[0]
                src = (
                    "对照"
                    if peer_model and sample.path not in model.ports
                    else "本文件"
                )
                owner_m = model if sample.path in model.ports else peer_model
                issues.append(
                    CheckIssue(
                        "warning",
                        "P↔R",
                        f"有 R 无 P（stem={stem}）@ {src}: "
                        f"{owner_m.resolve_name(sample.owner_path) if owner_m else ''}."
                        f"{sample.name}",
                        sample.path if sample.path in model.ports else "",
                        "port",
                    )
                )
    if n_p_only > 40:
        issues.append(
            CheckIssue(
                "warning",
                "P↔R",
                f"另有 {n_p_only - 40} 个「有P无R」stem（已截断）",
                "",
                "port",
            )
        )
    if n_r_only > 40:
        issues.append(
            CheckIssue(
                "warning",
                "P↔R",
                f"另有 {n_r_only - 40} 个「有R无P」stem（已截断）",
                "",
                "port",
            )
        )
    return issues


def summarize_issues(issues: List[CheckIssue]) -> str:
    n_e = sum(1 for i in issues if i.severity == "error")
    n_w = sum(1 for i in issues if i.severity == "warning")
    n_i = sum(1 for i in issues if i.severity == "info")
    return f"Errors={n_e}  Warnings={n_w}  Info={n_i}  Total={len(issues)}"
