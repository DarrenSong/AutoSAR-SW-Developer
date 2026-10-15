# -*- coding: utf-8 -*-
"""In-memory model for AUTOSAR SWC / Composition / connectors."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class DataElement:
    name: str
    path: str
    type_ref: str = ""
    type_dest: str = ""


@dataclass
class SrInterface:
    name: str
    path: str
    data_elements: List[DataElement] = field(default_factory=list)


@dataclass
class CsOperation:
    name: str
    path: str
    # ARGUMENT-DATA-PROTOTYPE short names (IN/INOUT/OUT lumped for display)
    arguments: List[str] = field(default_factory=list)


@dataclass
class CsInterface:
    name: str
    path: str
    operations: List[CsOperation] = field(default_factory=list)


@dataclass
class AdtRecordElement:
    name: str
    path: str
    type_ref: str = ""
    type_dest: str = ""


@dataclass
class ApplicationDataType:
    """AUTOSAR Application Data Type (ADT)."""
    name: str
    path: str
    kind: str  # PRIMITIVE | RECORD | ARRAY
    category: str = ""
    compu_method_ref: str = ""
    data_constr_ref: str = ""
    # RECORD
    elements: List[AdtRecordElement] = field(default_factory=list)
    # ARRAY
    element_type_ref: str = ""
    element_type_dest: str = ""
    array_size: str = ""
    array_size_semantics: str = ""


@dataclass
class ImplementationDataType:
    """AUTOSAR Implementation Data Type (IDT)."""
    name: str
    path: str
    category: str = ""
    base_type_ref: str = ""


@dataclass
class SwBaseType:
    name: str
    path: str
    category: str = ""
    size: str = ""
    encoding: str = ""
    native_declaration: str = ""


@dataclass
class DataTypeMap:
    """ADT ↔ IDT mapping entry."""
    adt_ref: str
    idt_ref: str
    adt_dest: str = ""
    idt_dest: str = ""


@dataclass
class Port:
    name: str
    path: str
    direction: str  # "P" | "R"
    owner_path: str  # SWC or Composition type path
    interface_ref: str = ""
    interface_dest: str = ""
    iface_kind: str = "SR"  # SR | CS | OTHER


@dataclass
class PendingEdit:
    """Queued mutation applied on Save / Save As."""
    kind: str
    # rename_connector | delete_connector | add_assembly | add_delegation |
    # rename_element | add_data_mapping | delete_data_mapping | update_data_mapping |
    # add_runnable | delete_runnable | set_runnable_symbol |
    # add_timing_event | add_init_event | add_data_received_event |
    # delete_rte_event | set_event_period | set_event_runnable |
    # add_port_access | delete_port_access |
    # add_system_signal | add_port | add_delegated_outer_port | add_system_mapping_set
    connector_path: str = ""
    connector_name: str = ""
    composition_path: str = ""
    connector_kind: str = ""  # assembly | delegation
    new_name: str = ""
    system_name: str = ""
    # add_assembly fields
    provider_proto_ref: str = ""
    provider_port_ref: str = ""
    requester_proto_ref: str = ""
    requester_port_ref: str = ""
    # add_delegation fields
    outer_port_ref: str = ""
    inner_proto_ref: str = ""
    inner_port_ref: str = ""
    inner_direction: str = ""  # P | R
    # rename_element: port | adt | idt | sr_interface | runnable | rte_event
    element_kind: str = ""
    element_path: str = ""
    # data mapping
    mapping_set_path: str = ""
    mapping_kind: str = ""  # SR-TO-SIGNAL | SR-TO-I-SIGNAL
    component_ref: str = ""
    data_element_ref: str = ""
    signal_ref: str = ""
    # IB
    behavior_path: str = ""
    runnable_path: str = ""
    event_path: str = ""
    period: str = ""
    offset: str = ""
    symbol: str = ""
    access_kind: str = ""  # SEND | RECEIVE
    access_name: str = ""
    # add_port / signal
    package_path: str = ""
    owner_swc_path: str = ""
    port_direction: str = ""  # P | R
    interface_ref: str = ""


@dataclass
class DataMapping:
    """System-level sender-receiver / signal data mapping (if present in ARXML)."""
    name: str
    path: str
    kind: str  # SR-TO-SIGNAL | SR-TO-I-SIGNAL | OTHER
    component_ref: str = ""
    port_ref: str = ""
    data_element_ref: str = ""
    signal_ref: str = ""
    system_signal_ref: str = ""
    mapping_set_path: str = ""  # parent SYSTEM-MAPPING path


@dataclass
class SwcType:
    name: str
    path: str
    kind: str  # APPLICATION | COMPOSITION | OTHER
    ports: List[Port] = field(default_factory=list)
    # composition only
    prototypes: List["Prototype"] = field(default_factory=list)
    assemblies: List["AssemblyConnector"] = field(default_factory=list)
    delegations: List["DelegationConnector"] = field(default_factory=list)
    # application SWC internal behaviors (RTE)
    behaviors: List["SwcInternalBehavior"] = field(default_factory=list)


@dataclass
class Prototype:
    name: str
    path: str
    composition_path: str
    type_ref: str = ""
    type_dest: str = ""


@dataclass
class AssemblyConnector:
    name: str
    path: str
    composition_path: str
    provider_proto_ref: str = ""
    provider_port_ref: str = ""
    requester_proto_ref: str = ""
    requester_port_ref: str = ""


@dataclass
class DelegationConnector:
    name: str
    path: str
    composition_path: str
    outer_port_ref: str = ""
    inner_proto_ref: str = ""
    inner_port_ref: str = ""
    inner_direction: str = ""  # P | R


@dataclass
class PortAccess:
    """Runnable port data/operation access (RTE mapping at SWC IB level)."""
    access_kind: str  # SEND | RECEIVE | SERVER-CALL | OTHER
    name: str = ""
    path: str = ""
    runnable_path: str = ""
    port_ref: str = ""
    data_element_ref: str = ""
    operation_ref: str = ""


@dataclass
class RteEvent:
    name: str
    path: str
    kind: str  # TIMING | INIT | DATA-RECEIVED | OPERATION-INVOKED | OTHER
    behavior_path: str = ""
    owner_swc: str = ""
    start_on_runnable_ref: str = ""
    period: str = ""
    offset: str = ""


@dataclass
class RunnableEntity:
    name: str
    path: str
    behavior_path: str = ""
    owner_swc: str = ""
    symbol: str = ""
    accesses: List[PortAccess] = field(default_factory=list)
    triggered_by: List[str] = field(default_factory=list)  # event paths


@dataclass
class SwcInternalBehavior:
    name: str
    path: str
    owner_swc: str = ""
    runnables: List[RunnableEntity] = field(default_factory=list)
    events: List[RteEvent] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True if export has IB tags but no usable names/refs."""
        named_r = any(r.name for r in self.runnables)
        named_e = any(e.name for e in self.events)
        any_access = any(a.port_ref for r in self.runnables for a in r.accesses)
        return not (named_r or named_e or any_access)


@dataclass
class SrHop:
    """One hop on an SR connectivity chain."""
    kind: str  # assembly | delegation
    connector_name: str = ""
    connector_path: str = ""
    composition_path: str = ""
    from_port: str = ""
    from_proto: str = ""
    to_port: str = ""
    to_proto: str = ""
    interface: str = ""

    def from_label(self, model: "ArxmlModel") -> str:
        return _endpoint_label(model, self.from_proto, self.from_port)

    def to_label(self, model: "ArxmlModel") -> str:
        return _endpoint_label(model, self.to_proto, self.to_port)


@dataclass
class PortPeer:
    """Counterpart port for navigation (Delegation / Assembly / chain / name)."""
    port_path: str
    relation: str  # delegation | assembly | chain_end | direction_pair | cross_file
    label: str = ""
    source: str = "primary"  # primary | peer_file
    peer_filepath: str = ""


@dataclass
class SrChain:
    """Full chain starting from one prototype instance of a type-level port."""
    start_port: str
    start_proto: str = ""  # empty when tracing composition outer without instance
    start_composition: str = ""
    hops: List[SrHop] = field(default_factory=list)
    # leaf endpoints discovered (application ports / outer ports with no further hop)
    endpoints: List[str] = field(default_factory=list)

    @property
    def instance_key(self) -> str:
        return self.start_proto or self.start_port


def _endpoint_label(model: "ArxmlModel", proto: str, port: str) -> str:
    pn = model.resolve_name(port)
    if proto:
        return f"{model.resolve_name(proto)}.{pn}"
    owner = ""
    p = model.ports.get(port)
    if p:
        owner = model.resolve_name(p.owner_path)
    if owner:
        return f"{owner}.{pn}"
    return pn


@dataclass
class ArxmlModel:
    filepath: str = ""
    swc_types: Dict[str, SwcType] = field(default_factory=dict)  # path -> type
    interfaces: Dict[str, SrInterface] = field(default_factory=dict)
    cs_interfaces: Dict[str, CsInterface] = field(default_factory=dict)
    ports: Dict[str, Port] = field(default_factory=dict)
    prototypes: Dict[str, Prototype] = field(default_factory=dict)
    assemblies: List[AssemblyConnector] = field(default_factory=list)
    delegations: List[DelegationConnector] = field(default_factory=list)
    # composition path -> connectors owned by that composition
    assemblies_by_comp: Dict[str, List[AssemblyConnector]] = field(default_factory=dict)
    delegations_by_comp: Dict[str, List[DelegationConnector]] = field(default_factory=dict)
    # which compositions are top-level (not used as type of any prototype)
    root_compositions: List[str] = field(default_factory=list)
    # pending write-back edits (not yet flushed to disk)
    pending_edits: List[PendingEdit] = field(default_factory=list)

    # Indexes built in finalize
    assemblies_by_port: Dict[str, List[AssemblyConnector]] = field(default_factory=dict)
    delegations_by_port: Dict[str, List[DelegationConnector]] = field(default_factory=dict)
    prototypes_by_type: Dict[str, List[Prototype]] = field(default_factory=dict)
    # composition type path -> prototypes that use this composition as type (parent instances)
    parent_protos_of_comp: Dict[str, List[Prototype]] = field(default_factory=dict)

    # RTE / Internal Behavior
    behaviors_by_swc: Dict[str, List[SwcInternalBehavior]] = field(default_factory=dict)
    runnables: Dict[str, RunnableEntity] = field(default_factory=dict)
    rte_events: Dict[str, RteEvent] = field(default_factory=dict)
    accesses_by_port: Dict[str, List[PortAccess]] = field(default_factory=dict)

    # Application / Implementation data types
    adts: Dict[str, ApplicationDataType] = field(default_factory=dict)
    idts: Dict[str, ImplementationDataType] = field(default_factory=dict)
    base_types: Dict[str, SwBaseType] = field(default_factory=dict)
    data_type_maps: List[DataTypeMap] = field(default_factory=list)
    idt_by_adt: Dict[str, str] = field(default_factory=dict)  # adt path → idt path
    adt_by_idt: Dict[str, str] = field(default_factory=dict)

    # System-level data mappings (often empty in SWC-only exports)
    data_mappings: List[DataMapping] = field(default_factory=list)
    mappings_by_port: Dict[str, List[DataMapping]] = field(default_factory=dict)
    system_signals: Dict[str, str] = field(default_factory=dict)  # path -> name
    i_signals: Dict[str, str] = field(default_factory=dict)
    system_mapping_sets: List[str] = field(default_factory=list)  # SYSTEM-MAPPING paths

    def is_dirty(self) -> bool:
        return bool(self.pending_edits)

    def behaviors_of_swc(self, swc_path: str) -> List[SwcInternalBehavior]:
        return self.behaviors_by_swc.get(swc_path, [])

    def runnables_accessing_port(self, port_path: str) -> List[RunnableEntity]:
        seen = set()
        out: List[RunnableEntity] = []
        for acc in self.accesses_by_port.get(port_path, []):
            if acc.runnable_path in seen:
                continue
            seen.add(acc.runnable_path)
            r = self.runnables.get(acc.runnable_path)
            if r:
                out.append(r)
        return out

    def rte_summary(self) -> Tuple[int, int, int, int]:
        """behaviors, runnables, events, non-empty behaviors."""
        n_beh = sum(len(v) for v in self.behaviors_by_swc.values())
        n_run = len(self.runnables)
        n_ev = len(self.rte_events)
        n_nonempty = sum(
            1
            for blist in self.behaviors_by_swc.values()
            for b in blist
            if not b.is_empty
        )
        return n_beh, n_run, n_ev, n_nonempty

    def adt_summary(self) -> Tuple[int, int, int, int, int]:
        """primitive, record, array, idt, base_type counts."""
        prim = sum(1 for a in self.adts.values() if a.kind == "PRIMITIVE")
        rec = sum(1 for a in self.adts.values() if a.kind == "RECORD")
        arr = sum(1 for a in self.adts.values() if a.kind == "ARRAY")
        return prim, rec, arr, len(self.idts), len(self.base_types)

    def mapped_idt_of_adt(self, adt_path: str) -> Optional[ImplementationDataType]:
        idt_path = self.idt_by_adt.get(adt_path)
        if not idt_path:
            return None
        return self.idts.get(idt_path)

    def mapped_adt_of_idt(self, idt_path: str) -> Optional[ApplicationDataType]:
        adt_path = self.adt_by_idt.get(idt_path)
        if not adt_path:
            return None
        return self.adts.get(adt_path)

    def interface_kind_of_port(self, port_path: str) -> str:
        port = self.ports.get(port_path)
        return port.iface_kind if port else "OTHER"

    def cs_interface_of_port(self, port_path: str) -> Optional[CsInterface]:
        port = self.ports.get(port_path)
        if not port or not port.interface_ref:
            return None
        return self.cs_interfaces.get(port.interface_ref)

    def assembly_iface_kind(self, a: "AssemblyConnector") -> str:
        """SR / CS / MIXED / OTHER based on endpoint ports."""
        pk = self.ports.get(a.provider_port_ref)
        rk = self.ports.get(a.requester_port_ref)
        kinds = set()
        if pk:
            kinds.add(pk.iface_kind)
        if rk:
            kinds.add(rk.iface_kind)
        if kinds == {"CS"}:
            return "CS"
        if kinds == {"SR"}:
            return "SR"
        if "CS" in kinds and "SR" in kinds:
            return "MIXED"
        if kinds:
            return next(iter(kinds))
        return "OTHER"

    def queue_rename_connector(
        self, connector_path: str, connector_name: str, composition_path: str,
        connector_kind: str, new_name: str,
    ):
        self.pending_edits.append(
            PendingEdit(
                kind="rename_connector",
                connector_path=connector_path,
                connector_name=connector_name,
                composition_path=composition_path,
                connector_kind=connector_kind,
                new_name=new_name,
            )
        )
        # update in-memory model immediately
        if connector_kind == "assembly":
            for a in self.assemblies:
                if (a.path or a.name) == connector_path or a.name == connector_name:
                    a.name = new_name
                    if a.path:
                        a.path = a.path.rsplit("/", 1)[0] + "/" + new_name
                    break
        else:
            for d in self.delegations:
                if (d.path or d.name) == connector_path or d.name == connector_name:
                    d.name = new_name
                    if d.path:
                        d.path = d.path.rsplit("/", 1)[0] + "/" + new_name
                    break

    def queue_delete_connector(
        self, connector_path: str, connector_name: str, composition_path: str,
        connector_kind: str,
    ):
        self.pending_edits.append(
            PendingEdit(
                kind="delete_connector",
                connector_path=connector_path,
                connector_name=connector_name,
                composition_path=composition_path,
                connector_kind=connector_kind,
            )
        )
        if connector_kind == "assembly":
            self.assemblies = [
                a for a in self.assemblies
                if not ((a.path or a.name) == connector_path or a.name == connector_name)
            ]
            if composition_path in self.assemblies_by_comp:
                self.assemblies_by_comp[composition_path] = [
                    a for a in self.assemblies_by_comp[composition_path]
                    if not ((a.path or a.name) == connector_path or a.name == connector_name)
                ]
            swc = self.swc_types.get(composition_path)
            if swc:
                swc.assemblies = [
                    a for a in swc.assemblies
                    if not ((a.path or a.name) == connector_path or a.name == connector_name)
                ]
        else:
            self.delegations = [
                d for d in self.delegations
                if not ((d.path or d.name) == connector_path or d.name == connector_name)
            ]
            if composition_path in self.delegations_by_comp:
                self.delegations_by_comp[composition_path] = [
                    d for d in self.delegations_by_comp[composition_path]
                    if not ((d.path or d.name) == connector_path or d.name == connector_name)
                ]
            swc = self.swc_types.get(composition_path)
            if swc:
                swc.delegations = [
                    d for d in swc.delegations
                    if not ((d.path or d.name) == connector_path or d.name == connector_name)
                ]
        self.build_indexes()

    def queue_add_assembly(
        self,
        composition_path: str,
        name: str,
        provider_proto_ref: str,
        provider_port_ref: str,
        requester_proto_ref: str,
        requester_port_ref: str,
    ) -> str:
        """
        Queue creation of ASSEMBLY-SW-CONNECTOR. Returns error message or "".
        Updates in-memory model immediately on success.
        """
        if not composition_path or composition_path not in self.swc_types:
            return "无效的 Composition"
        swc = self.swc_types[composition_path]
        if swc.kind != "COMPOSITION":
            return "目标不是 Composition"
        name = (name or "").strip()
        if not name:
            return "连接器名称不能为空"
        if not all([provider_proto_ref, provider_port_ref, requester_proto_ref, requester_port_ref]):
            return "请选择完整的 Provider / Requester 端口"
        if provider_proto_ref == requester_proto_ref and provider_port_ref == requester_port_ref:
            return "不能连接到同一端口"
        p_port = self.ports.get(provider_port_ref)
        r_port = self.ports.get(requester_port_ref)
        if not p_port or p_port.direction != "P":
            return "Provider 必须是 P-Port"
        if not r_port or r_port.direction != "R":
            return "Requester 必须是 R-Port"
        # duplicate name?
        for a in self.assemblies_by_comp.get(composition_path, []):
            if a.name == name:
                return f"名称已存在: {name}"
            if (
                a.provider_port_ref == provider_port_ref
                and a.requester_port_ref == requester_port_ref
                and a.provider_proto_ref == provider_proto_ref
                and a.requester_proto_ref == requester_proto_ref
            ):
                return f"相同连接已存在: {a.name}"

        path = f"{composition_path}/Connectors/{name}"
        a = AssemblyConnector(
            name=name,
            path=path,
            composition_path=composition_path,
            provider_proto_ref=provider_proto_ref,
            provider_port_ref=provider_port_ref,
            requester_proto_ref=requester_proto_ref,
            requester_port_ref=requester_port_ref,
        )
        self.pending_edits.append(
            PendingEdit(
                kind="add_assembly",
                connector_path=path,
                connector_name=name,
                composition_path=composition_path,
                connector_kind="assembly",
                provider_proto_ref=provider_proto_ref,
                provider_port_ref=provider_port_ref,
                requester_proto_ref=requester_proto_ref,
                requester_port_ref=requester_port_ref,
            )
        )
        self.assemblies.append(a)
        self.assemblies_by_comp.setdefault(composition_path, []).append(a)
        swc.assemblies.append(a)
        self.build_indexes()
        return ""

    def queue_add_delegation(
        self,
        composition_path: str,
        name: str,
        outer_port_ref: str,
        inner_proto_ref: str,
        inner_port_ref: str,
    ) -> str:
        """Queue DELEGATION-SW-CONNECTOR. Returns error message or empty string."""
        if not composition_path or composition_path not in self.swc_types:
            return "无效的 Composition"
        swc = self.swc_types[composition_path]
        if swc.kind != "COMPOSITION":
            return "目标不是 Composition"
        name = (name or "").strip()
        if not name:
            return "连接器名称不能为空"
        if not all([outer_port_ref, inner_proto_ref, inner_port_ref]):
            return "请选择完整的 Outer / Inner 端口"
        outer = self.ports.get(outer_port_ref)
        inner = self.ports.get(inner_port_ref)
        if not outer or outer.owner_path != composition_path:
            return "Outer 必须是本 Composition 的外端口"
        if not inner:
            return "Inner Port 无效"
        proto = self.prototypes.get(inner_proto_ref)
        if not proto or proto.composition_path != composition_path:
            return "Inner Prototype 不属于当前 Composition"
        if outer.direction != inner.direction:
            return (
                f"内外方向须一致 (Outer={outer.direction}, Inner={inner.direction})"
            )
        for d in self.delegations_by_comp.get(composition_path, []):
            if d.name == name:
                return f"名称已存在: {name}"
            if (
                d.outer_port_ref == outer_port_ref
                and d.inner_port_ref == inner_port_ref
                and d.inner_proto_ref == inner_proto_ref
            ):
                return f"相同 Delegation 已存在: {d.name}"

        path = f"{composition_path}/Connectors/{name}"
        d = DelegationConnector(
            name=name,
            path=path,
            composition_path=composition_path,
            outer_port_ref=outer_port_ref,
            inner_proto_ref=inner_proto_ref,
            inner_port_ref=inner_port_ref,
            inner_direction=inner.direction,
        )
        self.pending_edits.append(
            PendingEdit(
                kind="add_delegation",
                connector_path=path,
                connector_name=name,
                composition_path=composition_path,
                connector_kind="delegation",
                outer_port_ref=outer_port_ref,
                inner_proto_ref=inner_proto_ref,
                inner_port_ref=inner_port_ref,
                inner_direction=inner.direction,
            )
        )
        self.delegations.append(d)
        self.delegations_by_comp.setdefault(composition_path, []).append(d)
        swc.delegations.append(d)
        self.build_indexes()
        return ""

    def queue_rename_element(
        self, element_kind: str, element_path: str, new_name: str
    ) -> str:
        """
        Rename Port / ADT / IDT / SR-IF.
        Updates in-memory name + path keys; writer also rewrites REF texts.
        """
        new_name = (new_name or "").strip()
        if not new_name:
            return "名称不能为空"
        if "/" in new_name or "\\" in new_name:
            return "名称不能包含路径分隔符"

        old_path = element_path
        parent = old_path.rsplit("/", 1)[0] if "/" in old_path else ""
        new_path = f"{parent}/{new_name}" if parent else new_name

        if element_kind == "port":
            obj = self.ports.get(old_path)
            if not obj:
                return "Port 不存在"
            if obj.name == new_name:
                return ""
            old_name = obj.name
            obj.name = new_name
            obj.path = new_path
            self.ports.pop(old_path, None)
            self.ports[new_path] = obj
            self._rewrite_port_refs(old_path, new_path)
        elif element_kind == "adt":
            obj = self.adts.get(old_path)
            if not obj:
                return "ADT 不存在"
            if obj.name == new_name:
                return ""
            old_name = obj.name
            obj.name = new_name
            obj.path = new_path
            self.adts.pop(old_path, None)
            self.adts[new_path] = obj
            if old_path in self.idt_by_adt:
                idt_p = self.idt_by_adt.pop(old_path)
                self.idt_by_adt[new_path] = idt_p
                self.adt_by_idt[idt_p] = new_path
            for iface in self.interfaces.values():
                for de in iface.data_elements:
                    if de.type_ref == old_path:
                        de.type_ref = new_path
        elif element_kind == "idt":
            obj = self.idts.get(old_path)
            if not obj:
                return "IDT 不存在"
            if obj.name == new_name:
                return ""
            old_name = obj.name
            obj.name = new_name
            obj.path = new_path
            self.idts.pop(old_path, None)
            self.idts[new_path] = obj
            if old_path in self.adt_by_idt:
                adt_p = self.adt_by_idt.pop(old_path)
                self.adt_by_idt[new_path] = adt_p
                self.idt_by_adt[adt_p] = new_path
        elif element_kind == "sr_interface":
            obj = self.interfaces.get(old_path)
            if not obj:
                return "SR Interface 不存在"
            if obj.name == new_name:
                return ""
            old_name = obj.name
            obj.name = new_name
            obj.path = new_path
            self.interfaces.pop(old_path, None)
            self.interfaces[new_path] = obj
            for p in self.ports.values():
                if p.interface_ref == old_path:
                    p.interface_ref = new_path
        elif element_kind == "runnable":
            obj = self.runnables.get(old_path)
            if not obj:
                return "Runnable 不存在"
            if obj.name == new_name:
                return ""
            old_name = obj.name
            obj.name = new_name
            obj.path = new_path
            self.runnables.pop(old_path, None)
            self.runnables[new_path] = obj
            for ev in self.rte_events.values():
                if ev.start_on_runnable_ref == old_path:
                    ev.start_on_runnable_ref = new_path
            for beh in self.behaviors_by_swc.get(obj.owner_swc, []):
                for r in beh.runnables:
                    if r.path == new_path or r is obj:
                        r.path = new_path
                        r.name = new_name
            for acc in obj.accesses:
                acc.runnable_path = new_path
        elif element_kind == "rte_event":
            obj = self.rte_events.get(old_path)
            if not obj:
                return "Event 不存在"
            if obj.name == new_name:
                return ""
            old_name = obj.name
            obj.name = new_name
            obj.path = new_path
            self.rte_events.pop(old_path, None)
            self.rte_events[new_path] = obj
            for r in self.runnables.values():
                r.triggered_by = [
                    new_path if t == old_path else t for t in r.triggered_by
                ]
            for beh in self.behaviors_by_swc.get(obj.owner_swc, []):
                for e in beh.events:
                    if e is obj or e.path == new_path:
                        e.path = new_path
                        e.name = new_name
        else:
            return f"不支持重命名: {element_kind}"

        self.pending_edits.append(
            PendingEdit(
                kind="rename_element",
                element_kind=element_kind,
                element_path=old_path,
                connector_path=old_path,
                connector_name=old_name,
                new_name=new_name,
            )
        )
        self.build_indexes()
        return ""

    def queue_add_data_mapping(
        self,
        mapping_set_path: str,
        name: str,
        *,
        component_ref: str,
        port_ref: str,
        data_element_ref: str,
        signal_ref: str,
        mapping_kind: str = "SR-TO-SIGNAL",
    ) -> str:
        name = (name or "").strip()
        if not name:
            return "映射名称不能为空"
        if not mapping_set_path:
            return "没有可用的 SYSTEM-MAPPING（请先有 System/Mappings）"
        if not all([component_ref, port_ref, data_element_ref, signal_ref]):
            return "请选择完整的 Prototype / Port / DataElement / Signal"
        for dm in self.data_mappings:
            if dm.name == name and dm.mapping_set_path == mapping_set_path:
                return f"同名映射已存在: {name}"
        path = f"{mapping_set_path}/{name}"
        dm = DataMapping(
            name=name,
            path=path,
            kind=mapping_kind,
            component_ref=component_ref,
            port_ref=port_ref,
            data_element_ref=data_element_ref,
            signal_ref=signal_ref,
            system_signal_ref=signal_ref,
            mapping_set_path=mapping_set_path,
        )
        self.data_mappings.append(dm)
        self.pending_edits.append(
            PendingEdit(
                kind="add_data_mapping",
                connector_name=name,
                connector_path=path,
                mapping_set_path=mapping_set_path,
                mapping_kind=mapping_kind,
                component_ref=component_ref,
                provider_port_ref=port_ref,
                data_element_ref=data_element_ref,
                signal_ref=signal_ref,
            )
        )
        self.build_indexes()
        return ""

    def queue_delete_data_mapping(self, mapping_path: str) -> str:
        dm = next((x for x in self.data_mappings if x.path == mapping_path), None)
        if not dm:
            return "映射不存在"
        self.data_mappings = [x for x in self.data_mappings if x.path != mapping_path]
        self.pending_edits.append(
            PendingEdit(
                kind="delete_data_mapping",
                connector_path=mapping_path,
                connector_name=dm.name,
                mapping_set_path=dm.mapping_set_path,
                mapping_kind=dm.kind,
            )
        )
        self.build_indexes()
        return ""

    def queue_update_data_mapping(
        self,
        mapping_path: str,
        *,
        signal_ref: str = "",
        new_name: str = "",
    ) -> str:
        dm = next((x for x in self.data_mappings if x.path == mapping_path), None)
        if not dm:
            return "映射不存在"
        old_path = mapping_path
        if new_name.strip() and new_name.strip() != dm.name:
            dm.name = new_name.strip()
            parent = old_path.rsplit("/", 1)[0] if "/" in old_path else ""
            dm.path = f"{parent}/{dm.name}" if parent else dm.name
        if signal_ref and signal_ref != dm.signal_ref:
            dm.signal_ref = signal_ref
            dm.system_signal_ref = signal_ref
        self.pending_edits.append(
            PendingEdit(
                kind="update_data_mapping",
                connector_path=old_path,
                connector_name=dm.name,
                mapping_set_path=dm.mapping_set_path,
                mapping_kind=dm.kind,
                signal_ref=dm.signal_ref,
                new_name=dm.name,
            )
        )
        self.build_indexes()
        return ""

    def queue_add_runnable(
        self, behavior_path: str, name: str, symbol: str = ""
    ) -> str:
        beh = self._behavior_by_path(behavior_path)
        if not beh:
            return "Internal Behavior 不存在"
        name = (name or "").strip()
        if not name:
            return "Runnable 名称不能为空"
        if any(r.name == name for r in beh.runnables):
            return f"Runnable 已存在: {name}"
        path = f"{behavior_path}/{name}"
        r = RunnableEntity(
            name=name,
            path=path,
            behavior_path=behavior_path,
            owner_swc=beh.owner_swc,
            symbol=symbol or name,
        )
        beh.runnables.append(r)
        self.runnables[path] = r
        self.pending_edits.append(
            PendingEdit(
                kind="add_runnable",
                behavior_path=behavior_path,
                runnable_path=path,
                connector_name=name,
                symbol=r.symbol,
            )
        )
        return ""

    def queue_delete_runnable(self, runnable_path: str) -> str:
        r = self.runnables.get(runnable_path)
        if not r:
            return "Runnable 不存在"
        beh = self._behavior_by_path(r.behavior_path)
        if beh:
            beh.runnables = [x for x in beh.runnables if x.path != runnable_path]
        self.runnables.pop(runnable_path, None)
        for ev in self.rte_events.values():
            if ev.start_on_runnable_ref == runnable_path:
                ev.start_on_runnable_ref = ""
        self.pending_edits.append(
            PendingEdit(
                kind="delete_runnable",
                runnable_path=runnable_path,
                behavior_path=r.behavior_path,
                connector_name=r.name,
            )
        )
        self.build_indexes()
        return ""

    def queue_set_runnable_symbol(self, runnable_path: str, symbol: str) -> str:
        r = self.runnables.get(runnable_path)
        if not r:
            return "Runnable 不存在"
        r.symbol = symbol
        self.pending_edits.append(
            PendingEdit(
                kind="set_runnable_symbol",
                runnable_path=runnable_path,
                behavior_path=r.behavior_path,
                symbol=symbol,
                connector_name=r.name,
            )
        )
        return ""

    def queue_add_timing_event(
        self,
        behavior_path: str,
        name: str,
        runnable_path: str,
        period: str = "0.01",
        offset: str = "0",
    ) -> str:
        beh = self._behavior_by_path(behavior_path)
        if not beh:
            return "Internal Behavior 不存在"
        name = (name or "").strip()
        if not name:
            return "Event 名称不能为空"
        if runnable_path not in self.runnables:
            return "目标 Runnable 不存在"
        if any(e.name == name for e in beh.events):
            return f"Event 已存在: {name}"
        path = f"{behavior_path}/{name}"
        ev = RteEvent(
            name=name,
            path=path,
            kind="TIMING",
            behavior_path=behavior_path,
            owner_swc=beh.owner_swc,
            start_on_runnable_ref=runnable_path,
            period=period,
            offset=offset,
        )
        beh.events.append(ev)
        self.rte_events[path] = ev
        self.pending_edits.append(
            PendingEdit(
                kind="add_timing_event",
                behavior_path=behavior_path,
                event_path=path,
                runnable_path=runnable_path,
                connector_name=name,
                period=period,
                offset=offset,
            )
        )
        self.build_indexes()
        return ""

    def queue_add_init_event(
        self, behavior_path: str, name: str, runnable_path: str
    ) -> str:
        beh = self._behavior_by_path(behavior_path)
        if not beh:
            return "Internal Behavior 不存在"
        name = (name or "").strip()
        if not name:
            return "Event 名称不能为空"
        if runnable_path not in self.runnables:
            return "目标 Runnable 不存在"
        if any(e.name == name for e in beh.events):
            return f"Event 已存在: {name}"
        path = f"{behavior_path}/{name}"
        ev = RteEvent(
            name=name,
            path=path,
            kind="INIT",
            behavior_path=behavior_path,
            owner_swc=beh.owner_swc,
            start_on_runnable_ref=runnable_path,
        )
        beh.events.append(ev)
        self.rte_events[path] = ev
        self.pending_edits.append(
            PendingEdit(
                kind="add_init_event",
                behavior_path=behavior_path,
                event_path=path,
                runnable_path=runnable_path,
                connector_name=name,
            )
        )
        self.build_indexes()
        return ""

    def queue_add_data_received_event(
        self,
        behavior_path: str,
        name: str,
        runnable_path: str,
        port_ref: str,
        data_element_ref: str,
    ) -> str:
        beh = self._behavior_by_path(behavior_path)
        if not beh:
            return "Internal Behavior 不存在"
        name = (name or "").strip()
        if not name:
            return "Event 名称不能为空"
        if runnable_path not in self.runnables:
            return "目标 Runnable 不存在"
        if not port_ref or not data_element_ref:
            return "请选择 Port 与 DataElement"
        if any(e.name == name for e in beh.events):
            return f"Event 已存在: {name}"
        path = f"{behavior_path}/{name}"
        ev = RteEvent(
            name=name,
            path=path,
            kind="DATA-RECEIVED",
            behavior_path=behavior_path,
            owner_swc=beh.owner_swc,
            start_on_runnable_ref=runnable_path,
        )
        beh.events.append(ev)
        self.rte_events[path] = ev
        self.pending_edits.append(
            PendingEdit(
                kind="add_data_received_event",
                behavior_path=behavior_path,
                event_path=path,
                runnable_path=runnable_path,
                connector_name=name,
                provider_port_ref=port_ref,
                data_element_ref=data_element_ref,
            )
        )
        self.build_indexes()
        return ""

    def queue_delete_rte_event(self, event_path: str) -> str:
        ev = self.rte_events.get(event_path)
        if not ev:
            return "Event 不存在"
        beh = self._behavior_by_path(ev.behavior_path)
        if beh:
            beh.events = [x for x in beh.events if x.path != event_path]
        self.rte_events.pop(event_path, None)
        self.pending_edits.append(
            PendingEdit(
                kind="delete_rte_event",
                event_path=event_path,
                behavior_path=ev.behavior_path,
                connector_name=ev.name,
            )
        )
        self.build_indexes()
        return ""

    def queue_set_event_period(self, event_path: str, period: str) -> str:
        ev = self.rte_events.get(event_path)
        if not ev:
            return "Event 不存在"
        ev.period = period
        self.pending_edits.append(
            PendingEdit(
                kind="set_event_period",
                event_path=event_path,
                behavior_path=ev.behavior_path,
                period=period,
                connector_name=ev.name,
            )
        )
        return ""

    def queue_set_event_runnable(self, event_path: str, runnable_path: str) -> str:
        ev = self.rte_events.get(event_path)
        if not ev:
            return "Event 不存在"
        if runnable_path and runnable_path not in self.runnables:
            return "Runnable 不存在"
        ev.start_on_runnable_ref = runnable_path
        self.pending_edits.append(
            PendingEdit(
                kind="set_event_runnable",
                event_path=event_path,
                behavior_path=ev.behavior_path,
                runnable_path=runnable_path,
                connector_name=ev.name,
            )
        )
        self.build_indexes()
        return ""

    def queue_add_port_access(
        self,
        runnable_path: str,
        access_kind: str,
        port_ref: str,
        data_element_ref: str,
        name: str = "",
    ) -> str:
        r = self.runnables.get(runnable_path)
        if not r:
            return "Runnable 不存在"
        access_kind = (access_kind or "").upper()
        if access_kind not in ("SEND", "RECEIVE"):
            return "access_kind 须为 SEND 或 RECEIVE"
        if not port_ref or not data_element_ref:
            return "请选择 Port 与 DataElement"
        port = self.ports.get(port_ref)
        if not port:
            return "Port 不存在"
        if access_kind == "SEND" and port.direction != "P":
            return "SEND 需要 P-Port"
        if access_kind == "RECEIVE" and port.direction != "R":
            return "RECEIVE 需要 R-Port"
        aname = (name or "").strip() or (
            f"{'DSP' if access_kind == 'SEND' else 'DRP'}_"
            f"{self.resolve_name(port_ref)}_{self.resolve_name(data_element_ref)}"
        )
        apath = f"{runnable_path}/{aname}"
        acc = PortAccess(
            access_kind=access_kind,
            name=aname,
            path=apath,
            runnable_path=runnable_path,
            port_ref=port_ref,
            data_element_ref=data_element_ref,
        )
        r.accesses.append(acc)
        self.pending_edits.append(
            PendingEdit(
                kind="add_port_access",
                runnable_path=runnable_path,
                behavior_path=r.behavior_path,
                access_kind=access_kind,
                access_name=aname,
                provider_port_ref=port_ref,
                data_element_ref=data_element_ref,
                connector_path=apath,
            )
        )
        self.build_indexes()
        return ""

    def queue_delete_port_access(self, runnable_path: str, access_path: str) -> str:
        r = self.runnables.get(runnable_path)
        if not r:
            return "Runnable 不存在"
        before = len(r.accesses)
        r.accesses = [a for a in r.accesses if a.path != access_path]
        if len(r.accesses) == before:
            return "Port Access 不存在"
        self.pending_edits.append(
            PendingEdit(
                kind="delete_port_access",
                runnable_path=runnable_path,
                behavior_path=r.behavior_path,
                connector_path=access_path,
                access_name=access_path.rsplit("/", 1)[-1],
            )
        )
        self.build_indexes()
        return ""

    def queue_add_system_signal(self, name: str, package_path: str = "") -> str:
        name = (name or "").strip()
        if not name:
            return "Signal 名称不能为空"
        if any(n == name for n in self.system_signals.values()):
            return f"SYSTEM-SIGNAL 已存在: {name}"
        pkg = (package_path or "").strip()
        if not pkg:
            # reuse package of an existing signal, else /Signals
            if self.system_signals:
                sample = next(iter(self.system_signals.keys()))
                pkg = sample.rsplit("/", 1)[0] if "/" in sample else "/Signals"
            else:
                pkg = "/Signals"
        path = f"{pkg}/{name}"
        if path in self.system_signals:
            return f"路径已存在: {path}"
        self.system_signals[path] = name
        self.pending_edits.append(
            PendingEdit(
                kind="add_system_signal",
                connector_name=name,
                connector_path=path,
                package_path=pkg,
                signal_ref=path,
            )
        )
        return ""

    def queue_add_system_mapping_set(
        self,
        system_name: str = "System",
        mapping_name: str = "SystemMapping",
        package_path: str = "/System",
    ) -> str:
        """
        Create a minimal SYSTEM + SYSTEM-MAPPING stub so Data Mapping can be added.
        """
        system_name = (system_name or "System").strip()
        mapping_name = (mapping_name or "SystemMapping").strip()
        pkg = (package_path or "/System").strip() or "/System"
        if not pkg.startswith("/"):
            pkg = "/" + pkg
        system_path = f"{pkg}/{system_name}"
        mapping_path = f"{system_path}/Mappings/{mapping_name}"
        if mapping_path in self.system_mapping_sets:
            return f"SYSTEM-MAPPING 已存在: {mapping_path}"
        self.system_mapping_sets.append(mapping_path)
        self.pending_edits.append(
            PendingEdit(
                kind="add_system_mapping_set",
                package_path=pkg,
                system_name=system_name,
                connector_name=mapping_name,
                connector_path=mapping_path,
                mapping_set_path=mapping_path,
            )
        )
        return ""

    def queue_add_port(
        self,
        owner_swc_path: str,
        name: str,
        direction: str,
        interface_ref: str,
    ) -> str:
        swc = self.swc_types.get(owner_swc_path)
        if not swc:
            return "SWC / Composition 不存在"
        name = (name or "").strip()
        direction = (direction or "").upper()
        if direction not in ("P", "R"):
            return "direction 须为 P 或 R"
        if not name:
            return "Port 名称不能为空"
        if any(p.name == name for p in swc.ports):
            return f"Port 已存在: {name}"
        if not interface_ref:
            return "请选择 Interface"
        iface_kind = "SR"
        if interface_ref in self.cs_interfaces:
            iface_kind = "CS"
        elif interface_ref not in self.interfaces:
            iface_kind = "OTHER"
        path = f"{owner_swc_path}/{name}"
        port = Port(
            name=name,
            path=path,
            direction=direction,
            owner_path=owner_swc_path,
            interface_ref=interface_ref,
            interface_dest=(
                "CLIENT-SERVER-INTERFACE"
                if iface_kind == "CS"
                else "SENDER-RECEIVER-INTERFACE"
            ),
            iface_kind=iface_kind,
        )
        swc.ports.append(port)
        self.ports[path] = port
        self.pending_edits.append(
            PendingEdit(
                kind="add_port",
                owner_swc_path=owner_swc_path,
                connector_name=name,
                connector_path=path,
                port_direction=direction,
                interface_ref=interface_ref,
            )
        )
        self.build_indexes()
        return ""

    def queue_add_delegated_outer_port(
        self,
        composition_path: str,
        inner_proto_ref: str,
        inner_port_ref: str,
        outer_name: str = "",
    ) -> str:
        """
        Create Composition outer port (…_DG_P/_DG_R) + Delegation to inner port.
        """
        comp = self.swc_types.get(composition_path)
        if not comp or comp.kind != "COMPOSITION":
            return "请选择 Composition"
        inner = self.ports.get(inner_port_ref)
        proto = self.prototypes.get(inner_proto_ref)
        if not inner or not proto:
            return "请选择内部 Prototype 与 Port"
        if proto.composition_path != composition_path:
            return "Prototype 不属于该 Composition"
        direction = inner.direction or "R"
        suffix = "_DG_P" if direction == "P" else "_DG_R"
        base = outer_name.strip() or f"{inner.name}{suffix}"
        if not base.endswith(("_DG_P", "_DG_R", "_P", "_R")):
            base = base + suffix
        err = self.queue_add_port(
            composition_path,
            base,
            direction,
            inner.interface_ref,
        )
        if err:
            return err
        outer_path = f"{composition_path}/{base}"
        conn_name = f"{proto.name}_{inner.name}_to_{base}_DG"
        err = self.queue_add_delegation(
            composition_path,
            conn_name,
            outer_path,
            inner_proto_ref,
            inner_port_ref,
        )
        if err:
            return f"Outer Port 已创建，但 Delegation 失败: {err}"
        return ""

    def _behavior_by_path(self, behavior_path: str) -> Optional[SwcInternalBehavior]:
        for blist in self.behaviors_by_swc.values():
            for b in blist:
                if b.path == behavior_path:
                    return b
        return None

    def _rewrite_port_refs(self, old_path: str, new_path: str):
        for a in self.assemblies:
            if a.provider_port_ref == old_path:
                a.provider_port_ref = new_path
            if a.requester_port_ref == old_path:
                a.requester_port_ref = new_path
        for d in self.delegations:
            if d.outer_port_ref == old_path:
                d.outer_port_ref = new_path
            if d.inner_port_ref == old_path:
                d.inner_port_ref = new_path
        for r in self.runnables.values():
            for acc in r.accesses:
                if acc.port_ref == old_path:
                    acc.port_ref = new_path

    def build_indexes(self):
        """Call after parse finalize to speed up SR tracing."""
        self.assemblies_by_port = defaultdict(list)
        self.delegations_by_port = defaultdict(list)
        self.prototypes_by_type = defaultdict(list)
        self.parent_protos_of_comp = defaultdict(list)

        for a in self.assemblies:
            if a.provider_port_ref:
                self.assemblies_by_port[a.provider_port_ref].append(a)
            if a.requester_port_ref:
                self.assemblies_by_port[a.requester_port_ref].append(a)

        for d in self.delegations:
            if d.outer_port_ref:
                self.delegations_by_port[d.outer_port_ref].append(d)
            if d.inner_port_ref:
                self.delegations_by_port[d.inner_port_ref].append(d)

        for proto in self.prototypes.values():
            if proto.type_ref:
                self.prototypes_by_type[proto.type_ref].append(proto)
                t = self.swc_types.get(proto.type_ref)
                if t and t.kind == "COMPOSITION":
                    self.parent_protos_of_comp[proto.type_ref].append(proto)

        # plain dicts for easier serialization / typing
        self.assemblies_by_port = dict(self.assemblies_by_port)
        self.delegations_by_port = dict(self.delegations_by_port)
        self.prototypes_by_type = dict(self.prototypes_by_type)
        self.parent_protos_of_comp = dict(self.parent_protos_of_comp)

        # RTE: port → accesses; event → runnable.triggered_by
        self.accesses_by_port = defaultdict(list)
        for r in self.runnables.values():
            r.triggered_by = []
            for acc in r.accesses:
                if acc.port_ref:
                    self.accesses_by_port[acc.port_ref].append(acc)
        for ev in self.rte_events.values():
            if ev.start_on_runnable_ref and ev.start_on_runnable_ref in self.runnables:
                self.runnables[ev.start_on_runnable_ref].triggered_by.append(ev.path)
        self.accesses_by_port = dict(self.accesses_by_port)

        # ADT ↔ IDT maps
        self.idt_by_adt = {}
        self.adt_by_idt = {}
        for m in self.data_type_maps:
            if m.adt_ref and m.idt_ref:
                self.idt_by_adt[m.adt_ref] = m.idt_ref
                self.adt_by_idt[m.idt_ref] = m.adt_ref

        self.mappings_by_port = defaultdict(list)
        for dm in self.data_mappings:
            if dm.port_ref:
                self.mappings_by_port[dm.port_ref].append(dm)
        self.mappings_by_port = dict(self.mappings_by_port)

    def composition_paths(self) -> List[str]:
        return sorted(
            p for p, t in self.swc_types.items() if t.kind == "COMPOSITION"
        )

    def application_paths(self) -> List[str]:
        return sorted(
            p for p, t in self.swc_types.items() if t.kind == "APPLICATION"
        )

    def resolve_name(self, path: str) -> str:
        if not path:
            return ""
        return path.rsplit("/", 1)[-1]

    def interface_of_port(self, port_path: str) -> Optional[SrInterface]:
        port = self.ports.get(port_path)
        if not port or not port.interface_ref:
            return None
        return self.interfaces.get(port.interface_ref)

    def port_sr_type_lines(self, port_path: str) -> List[str]:
        """SR Port → Interface DataElement → type short names (one line per DE)."""
        port = self.ports.get(port_path) if port_path else None
        if not port or (port.iface_kind or "SR") not in ("SR", ""):
            return []
        iface = self.interface_of_port(port_path)
        if not iface:
            return []
        lines: List[str] = []
        for de in iface.data_elements:
            type_n = self.resolve_name(de.type_ref) if de.type_ref else "?"
            adt = self.adts.get(de.type_ref) if de.type_ref else None
            kind = f" [{adt.kind}]" if adt else ""
            if not adt and de.type_ref and de.type_ref in self.idts:
                kind = " [IDT]"
            lines.append(f"{de.name}: {type_n}{kind}")
        return lines

    def port_sr_type_summary(self, port_path: str) -> str:
        """Compact label suffix: single type name, or 'N DE' when multiple."""
        lines = self.port_sr_type_lines(port_path)
        if not lines:
            return ""
        if len(lines) == 1:
            # "Status: FooAdt [PRIMITIVE]" → use type name after ": "
            part = lines[0].split(": ", 1)
            type_part = part[1] if len(part) == 2 else lines[0]
            # strip trailing kind tag for short label
            if " [" in type_part:
                type_part = type_part.split(" [", 1)[0]
            return type_part
        return f"{len(lines)} DE"

    def assemblies_touching(self, path: str) -> List[AssemblyConnector]:
        """Connectors that reference path as proto or port."""
        out = []
        for a in self.assemblies:
            if path in (
                a.provider_proto_ref,
                a.requester_proto_ref,
                a.provider_port_ref,
                a.requester_port_ref,
                a.composition_path,
            ):
                out.append(a)
        return out

    def delegations_touching(self, path: str) -> List[DelegationConnector]:
        out = []
        for d in self.delegations:
            if path in (
                d.outer_port_ref,
                d.inner_proto_ref,
                d.inner_port_ref,
                d.composition_path,
            ):
                out.append(d)
        return out

    def sr_links_for_port(self, port_path: str) -> List[dict]:
        """Provider→Requester links involving this port (via assembly)."""
        links = []
        for a in self.assemblies_by_port.get(port_path, self.assemblies):
            if port_path not in (a.provider_port_ref, a.requester_port_ref):
                continue
            iface = None
            pport = self.ports.get(a.provider_port_ref)
            if pport:
                iface = self.interfaces.get(pport.interface_ref)
            links.append(
                {
                    "connector": a.name,
                    "connector_path": a.path,
                    "provider_proto": self.resolve_name(a.provider_proto_ref),
                    "provider_port": self.resolve_name(a.provider_port_ref),
                    "requester_proto": self.resolve_name(a.requester_proto_ref),
                    "requester_port": self.resolve_name(a.requester_port_ref),
                    "interface": iface.name if iface else "",
                    "data_elements": [de.name for de in iface.data_elements] if iface else [],
                }
            )
        return links

    @staticmethod
    def opposite_port_names(name: str) -> List[str]:
        """Foo_P ↔ Foo_R naming variants."""
        alts: List[str] = []
        if name.endswith("_P"):
            alts.append(name[:-2] + "_R")
        elif name.endswith("_R"):
            alts.append(name[:-2] + "_P")
        return alts

    def lift_port_for_peer_view(self, port_path: str) -> str:
        """
        Walk outward along Delegation (inner→outer) to the outermost same-direction
        Port. Application SWC ports lift to top-level Composition outer (_DG…_P/_R)
        so 对端图 can match direction_pair / cross-file peers.
        """
        if not port_path or port_path not in self.ports:
            return port_path
        seen: Set[str] = set()
        cur = port_path
        while cur not in seen:
            seen.add(cur)
            nxt = ""
            for d in self.delegations_by_port.get(cur, []):
                if d.inner_port_ref == cur and d.outer_port_ref:
                    out_p = self.ports.get(d.outer_port_ref)
                    in_p = self.ports.get(cur)
                    # keep same direction when possible
                    if out_p and in_p and out_p.direction and in_p.direction:
                        if out_p.direction != in_p.direction:
                            continue
                    nxt = d.outer_port_ref
                    break
            if not nxt or nxt not in self.ports:
                break
            cur = nxt
        return cur

    def find_port_peers(
        self,
        port_path: str,
        *,
        chain: Optional["SrChain"] = None,
        peer_model: Optional["ArxmlModel"] = None,
    ) -> List[PortPeer]:
        """
        Find counterpart ports for navigation.

        Priority relations:
        - delegation: same connector outer ↔ inner
        - assembly: provider(P) ↔ requester(R)
        - chain_end: other end of the current SR chain
        - direction_pair: same SHORT-NAME with _P↔_R (heuristic)
        - cross_file: match in peer_model (ZCUD↔ZCUP) by _P/_R name + interface
        """
        if not port_path or port_path not in self.ports:
            return []
        seen: Set[str] = set()
        out: List[PortPeer] = []

        def add(
            path: str,
            relation: str,
            label: str,
            *,
            source: str = "primary",
            peer_filepath: str = "",
            in_model: Optional["ArxmlModel"] = None,
        ):
            key = f"{source}:{path}"
            if not path or path == port_path or key in seen:
                return
            m = in_model or self
            if path not in m.ports:
                return
            seen.add(key)
            out.append(
                PortPeer(
                    port_path=path,
                    relation=relation,
                    label=label,
                    source=source,
                    peer_filepath=peer_filepath,
                )
            )

        port = self.ports[port_path]
        # True P↔R peers first in listing order (assembly / name / cross_file).
        # Delegation outer↔inner is SAME direction — label as 委托同向端, not 对端.
        for a in self.assemblies_by_port.get(port_path, []):
            if a.provider_port_ref == port_path and a.requester_port_ref:
                add(
                    a.requester_port_ref,
                    "assembly",
                    f"P↔R 对端 (Assembly→R) → {self.resolve_name(a.requester_proto_ref)}."
                    f"{self.resolve_name(a.requester_port_ref)}",
                )
            elif a.requester_port_ref == port_path and a.provider_port_ref:
                add(
                    a.provider_port_ref,
                    "assembly",
                    f"P↔R 对端 (Assembly→P) → {self.resolve_name(a.provider_proto_ref)}."
                    f"{self.resolve_name(a.provider_port_ref)}",
                )

        for d in self.delegations_by_port.get(port_path, []):
            if d.outer_port_ref == port_path and d.inner_port_ref:
                inn = self.ports.get(d.inner_port_ref)
                dir_s = inn.direction if inn else "?"
                add(
                    d.inner_port_ref,
                    "delegation",
                    f"委托同向端 (内 {dir_s}) → {self.resolve_name(d.inner_port_ref)}"
                    f" @ {self.resolve_name(d.inner_proto_ref) or self.resolve_name(d.composition_path)}"
                    f"  ※非P↔R",
                )
            if d.inner_port_ref == port_path and d.outer_port_ref:
                outp = self.ports.get(d.outer_port_ref)
                dir_s = outp.direction if outp else "?"
                add(
                    d.outer_port_ref,
                    "delegation",
                    f"委托同向端 (外 {dir_s}) → {self.resolve_name(d.outer_port_ref)}"
                    f" @ {self.resolve_name(d.composition_path)}"
                    f"  ※非P↔R",
                )

        if chain is not None:
            ends: List[str] = []
            if chain.start_port:
                ends.append(chain.start_port)
            for e in chain.endpoints:
                if e:
                    ends.append(e)
            if not chain.endpoints and chain.hops:
                last = chain.hops[-1]
                far = (
                    last.to_port
                    if last.to_port and last.to_port != chain.start_port
                    else last.from_port
                )
                if far:
                    ends.append(far)
            uniq_ends: List[str] = []
            for e in ends:
                if e and e not in uniq_ends:
                    uniq_ends.append(e)
            on_chain = (
                port_path == chain.start_port
                or port_path in uniq_ends
                or any(port_path in (h.from_port, h.to_port) for h in chain.hops)
            )
            if on_chain:
                for e in uniq_ends:
                    if e == port_path:
                        continue
                    po = self.ports.get(e)
                    owner = self.swc_types.get(po.owner_path) if po else None
                    kind_hint = (
                        "App"
                        if owner and owner.kind == "APPLICATION"
                        else "Outer"
                        if owner and owner.kind == "COMPOSITION"
                        else ""
                    )
                    dir_s = po.direction if po else "?"
                    add(
                        e,
                        "chain_end",
                        f"链路另一端 ({dir_s}{('/' + kind_hint) if kind_hint else ''}) → "
                        f"{self.resolve_name(e)} @ {self.resolve_name(po.owner_path) if po else ''}"
                        f"  ※同向连通端，非P↔R",
                    )

        # Name heuristic: Foo_P ↔ Foo_R (including *_DG_P / *_DG_R)
        name = port.name
        alts = self.opposite_port_names(name)
        for alt in alts:
            matches = [p for p in self.ports.values() if p.name == alt]
            matches.sort(
                key=lambda p: (
                    0 if p.owner_path == port.owner_path else 1,
                    0
                    if (p.owner_path.split("/")[:3] == port.owner_path.split("/")[:3])
                    else 1,
                    p.path,
                )
            )
            for p in matches[:8]:
                add(
                    p.path,
                    "direction_pair",
                    f"P↔R 对端 (同名反向 {p.direction}) → {p.name} @ "
                    f"{self.resolve_name(p.owner_path)}",
                )

        # Cross-file (e.g. ZCUD P outer ↔ ZCUP R outer / App)
        if peer_model is not None and peer_model is not self:
            peer_fp = peer_model.filepath or "(对照文件)"
            short_fp = peer_fp.replace("\\", "/").rsplit("/", 1)[-1]
            want_dir = "R" if port.direction == "P" else "P" if port.direction == "R" else ""
            iface_name = ""
            if port.interface_ref:
                iface_name = self.resolve_name(port.interface_ref)
            name_cands = set(alts) | {name}
            # also try strip trailing _DG repeated for fuzzy? keep exact opposite names
            stem = name[:-2] if name.endswith(("_P", "_R")) else name
            scored: List[Tuple[int, str, str]] = []  # score, path, label
            for p in peer_model.ports.values():
                if want_dir and p.direction != want_dir:
                    continue
                pstem = p.name[:-2] if p.name.endswith(("_P", "_R")) else p.name
                score = 0
                if p.name in name_cands:
                    score += 100
                elif pstem == stem:
                    score += 90
                else:
                    continue
                if iface_name and p.interface_ref:
                    if peer_model.resolve_name(p.interface_ref) == iface_name:
                        score += 20
                owner_n = peer_model.resolve_name(p.owner_path)
                scored.append(
                    (
                        -score,
                        p.path,
                        f"P↔R 对端 [对照:{short_fp}] {p.direction}-{p.name} @ {owner_n}",
                    )
                )
            scored.sort()
            for _, path, label in scored[:12]:
                add(
                    path,
                    "cross_file",
                    label,
                    source="peer_file",
                    peer_filepath=peer_fp,
                    in_model=peer_model,
                )
            # Also: assemblies in peer file whose provider/requester name matches
            for a in peer_model.assemblies:
                for pref, role in (
                    (a.provider_port_ref, "P"),
                    (a.requester_port_ref, "R"),
                ):
                    pp = peer_model.ports.get(pref)
                    if not pp:
                        continue
                    stem = name[:-2] if name.endswith(("_P", "_R")) else name
                    pstem = pp.name[:-2] if pp.name.endswith(("_P", "_R")) else pp.name
                    if pstem != stem and pp.name not in name_cands:
                        continue
                    other = (
                        a.requester_port_ref
                        if role == "P"
                        else a.provider_port_ref
                    )
                    other_p = peer_model.ports.get(other)
                    if not other_p:
                        continue
                    add(
                        other,
                        "cross_file",
                        f"[对照:{short_fp}] Assembly对端 ({other_p.direction}) → "
                        f"{other_p.name} @ {peer_model.resolve_name(other_p.owner_path)}",
                        source="peer_file",
                        peer_filepath=peer_fp,
                        in_model=peer_model,
                    )

        # True opposite-direction first
        order = {
            "assembly": 0,
            "direction_pair": 1,
            "cross_file": 2,
            "chain_end": 3,
            "delegation": 4,
        }
        out.sort(key=lambda x: (order.get(x.relation, 9), x.label))
        return out

    def trace_sr_port(self, port_path: str, max_hops: int = 32) -> List[SrChain]:
        """
        Trace full Assembly/Delegation chains for a type-level SR port.

        Returns one SrChain per (prototype instance × path-to-endpoint).
        If the type is not instantiated, traces once with empty proto context.
        """
        port = self.ports.get(port_path)
        if not port:
            return []

        owner = self.swc_types.get(port.owner_path)
        starts: List[Tuple[str, str, str]] = []  # port, proto, composition

        if owner and owner.kind == "APPLICATION":
            protos = self.prototypes_by_type.get(port.owner_path, [])
            if not protos:
                starts.append((port_path, "", ""))
            else:
                for proto in protos:
                    starts.append((port_path, proto.path, proto.composition_path))
        else:
            starts.append((port_path, "", port.owner_path))

        chains: List[SrChain] = []
        for sp, sproto, scomp in starts:
            chains.extend(self._paths_from(sp, sproto, scomp, max_hops))
        return chains

    def _paths_from(
        self,
        start_port: str,
        start_proto: str,
        start_composition: str,
        max_hops: int,
    ) -> List[SrChain]:
        """BFS with parent pointers; emit one chain per leaf endpoint path."""
        start = (start_port, start_proto)
        parent: Dict[Tuple[str, str], Tuple[Tuple[str, str], SrHop]] = {}
        visited: Set[Tuple[str, str]] = {start}
        q: deque[Tuple[str, str, int]] = deque([(start_port, start_proto, 0)])
        leaves: List[Tuple[str, str]] = []

        while q:
            port_path, proto_path, depth = q.popleft()
            # Stop expanding once we reach another Application port (end of SR chain)
            po = self.ports.get(port_path)
            own = self.swc_types.get(po.owner_path) if po else None
            at_app = bool(own and own.kind == "APPLICATION")
            if at_app and (port_path, proto_path) != start:
                leaves.append((port_path, proto_path))
                continue
            neighbors = self._neighbors(port_path, proto_path) if depth < max_hops else []
            expanded = False
            for hop, next_port, next_proto in neighbors:
                if hop.from_port != port_path:
                    hop = SrHop(
                        kind=hop.kind,
                        connector_name=hop.connector_name,
                        connector_path=hop.connector_path,
                        composition_path=hop.composition_path,
                        from_port=hop.to_port,
                        from_proto=hop.to_proto,
                        to_port=hop.from_port,
                        to_proto=hop.from_proto,
                        interface=hop.interface,
                    )
                node = (next_port, next_proto or "")
                if node in visited:
                    continue
                visited.add(node)
                parent[node] = ((port_path, proto_path), hop)
                q.append((next_port, next_proto or "", depth + 1))
                expanded = True
            if not expanded and (port_path, proto_path) != start:
                leaves.append((port_path, proto_path))

        # Prefer APPLICATION ports as endpoints; else all leaves
        app_leaves = []
        for ppath, pr in leaves:
            po = self.ports.get(ppath)
            own = self.swc_types.get(po.owner_path) if po else None
            if own and own.kind == "APPLICATION":
                app_leaves.append((ppath, pr))
        targets = app_leaves or leaves

        if not targets and len(visited) == 1:
            # isolated port
            return [
                SrChain(
                    start_port=start_port,
                    start_proto=start_proto,
                    start_composition=start_composition,
                    hops=[],
                    endpoints=[],
                )
            ]

        if not targets:
            # reached nodes but no clear leaf — take farthest APPLICATION or any
            farthest = None
            for node in visited:
                if node == start:
                    continue
                po = self.ports.get(node[0])
                own = self.swc_types.get(po.owner_path) if po else None
                if own and own.kind == "APPLICATION":
                    farthest = node
                    break
            if farthest is None:
                for node in visited:
                    if node != start:
                        farthest = node
                        break
            targets = [farthest] if farthest else []

        chains: List[SrChain] = []
        for target in targets:
            hops: List[SrHop] = []
            cur = target
            while cur in parent:
                prev, hop = parent[cur]
                hops.append(hop)
                cur = prev
            hops.reverse()
            chain = SrChain(
                start_port=start_port,
                start_proto=start_proto,
                start_composition=start_composition,
                hops=hops,
                endpoints=[target[0]],
            )
            chains.append(chain)
        return chains

    def _neighbors(
        self, port_path: str, proto_path: str
    ) -> List[Tuple[SrHop, str, str]]:
        """Return list of (hop, next_port, next_proto) from this endpoint."""
        out: List[Tuple[SrHop, str, str]] = []
        iface = ""
        p = self.ports.get(port_path)
        if p and p.interface_ref in self.interfaces:
            iface = self.interfaces[p.interface_ref].name

        for a in self.assemblies_by_port.get(port_path, []):
            if port_path == a.provider_port_ref:
                if proto_path and a.provider_proto_ref and a.provider_proto_ref != proto_path:
                    continue
                hop = SrHop(
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
                out.append((hop, a.requester_port_ref, a.requester_proto_ref))
            elif port_path == a.requester_port_ref:
                if proto_path and a.requester_proto_ref and a.requester_proto_ref != proto_path:
                    continue
                hop = SrHop(
                    kind="assembly",
                    connector_name=a.name,
                    connector_path=a.path,
                    composition_path=a.composition_path,
                    from_port=a.requester_port_ref,
                    from_proto=a.requester_proto_ref,
                    to_port=a.provider_port_ref,
                    to_proto=a.provider_proto_ref,
                    interface=iface,
                )
                out.append((hop, a.provider_port_ref, a.provider_proto_ref))

        for d in self.delegations_by_port.get(port_path, []):
            if port_path == d.inner_port_ref:
                if proto_path and d.inner_proto_ref and d.inner_proto_ref != proto_path:
                    continue
                # When leaving to outer: keep parent Composition *instance* so
                # upper-level Assembly/Delegation can continue (multi-layer nest).
                outer_proto = ""
                parents = self.parent_protos_of_comp.get(d.composition_path, [])
                if len(parents) == 1:
                    outer_proto = parents[0].path
                elif parents and proto_path:
                    # multiple instances — prefer any; filter later by assembly proto
                    outer_proto = parents[0].path
                hop = SrHop(
                    kind="delegation",
                    connector_name=d.name,
                    connector_path=d.path,
                    composition_path=d.composition_path,
                    from_port=d.inner_port_ref,
                    from_proto=d.inner_proto_ref,
                    to_port=d.outer_port_ref,
                    to_proto=outer_proto,
                    interface=iface,
                )
                out.append((hop, d.outer_port_ref, outer_proto))
            elif port_path == d.outer_port_ref:
                # proto_path may be the nested Composition prototype (from parent)
                # or empty when this composition is the tracing root.
                if proto_path:
                    pr = self.prototypes.get(proto_path)
                    if pr and pr.type_ref != d.composition_path:
                        # wrong instance context — skip
                        continue
                hop = SrHop(
                    kind="delegation",
                    connector_name=d.name,
                    connector_path=d.path,
                    composition_path=d.composition_path,
                    from_port=d.outer_port_ref,
                    from_proto=proto_path,
                    to_port=d.inner_port_ref,
                    to_proto=d.inner_proto_ref,
                    interface=iface,
                )
                out.append((hop, d.inner_port_ref, d.inner_proto_ref))

        return out
