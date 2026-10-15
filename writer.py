# -*- coding: utf-8 -*-
"""Apply pending edits and write ARXML back to disk."""
from __future__ import annotations

import os
import shutil
from typing import List, Optional, Tuple

from lxml import etree

from .model import PendingEdit
from .parser import _local, _path_of, _sn

NS = "http://autosar.org/schema/r4.0"

EVENT_TAGS = (
    "TIMING-EVENT",
    "INIT-EVENT",
    "DATA-RECEIVED-EVENT",
    "DATA-RECEIVE-ERROR-EVENT",
    "OPERATION-INVOKED-EVENT",
    "MODE-SWITCH-EVENT",
    "BACKGROUND-EVENT",
    "SWC-MODE-SWITCH-EVENT",
    "EXTERNAL-TRIGGER-OCCURRED-EVENT",
    "INTERNAL-TRIGGER-OCCURRED-EVENT",
    "DATA-SEND-COMPLETED-EVENT",
    "ASYNCHRONOUS-SERVER-CALL-RETURNS-EVENT",
)


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _sub(parent, tag: str, text: str | None = None, **attrs):
    el = etree.SubElement(parent, _q(tag), attrs)
    if text is not None:
        el.text = text
    return el


def _find_or_create_child(parent, tag: str):
    for c in parent:
        if _local(c.tag) == tag:
            return c
    return _sub(parent, tag)


def _set_or_create_text(parent, tag: str, text: str):
    for c in parent:
        if _local(c.tag) == tag:
            c.text = text
            return c
    return _sub(parent, tag, text)


def _find_composition_elem(root, composition_path: str):
    """Find COMPOSITION-SW-COMPONENT-TYPE by absolute path (preferred) or short name."""
    if not composition_path:
        return None
    for el in root.iter():
        if _local(el.tag) != "COMPOSITION-SW-COMPONENT-TYPE":
            continue
        if _path_of(el) == composition_path:
            return el
    # fallback short name
    tail = composition_path.rsplit("/", 1)[-1]
    for el in root.iter():
        if _local(el.tag) == "COMPOSITION-SW-COMPONENT-TYPE" and _sn(el) == tail:
            return el
    return None


def _find_connectors_container(root, composition_path: str):
    comp = _find_composition_elem(root, composition_path)
    if comp is None:
        return None
    for c in comp:
        if _local(c.tag) == "CONNECTORS":
            return c
    # create empty CONNECTORS if missing
    return _sub(comp, "CONNECTORS")


def _find_connector_elem(root, edit: PendingEdit):
    """Locate ASSEMBLY/DELEGATION element matching composition + name/path."""
    want_tags = (
        ("ASSEMBLY-SW-CONNECTOR",)
        if edit.connector_kind == "assembly"
        else ("DELEGATION-SW-CONNECTOR",)
    )
    name_candidates = {edit.connector_name}
    if edit.connector_path:
        name_candidates.add(edit.connector_path.rsplit("/", 1)[-1])
    name_candidates = {n for n in name_candidates if n}

    for el in root.iter():
        if _local(el.tag) not in want_tags:
            continue
        sn = _sn(el)
        if sn not in name_candidates:
            continue
        # ensure under the right composition
        cur = el.getparent()
        while cur is not None and _local(cur.tag) != "COMPOSITION-SW-COMPONENT-TYPE":
            cur = cur.getparent()
        if cur is None:
            continue
        if edit.composition_path and _path_of(cur) != edit.composition_path:
            if _sn(cur) != edit.composition_path.rsplit("/", 1)[-1]:
                continue
        return el
    return None


def _add_assembly_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    container = _find_connectors_container(root, edit.composition_path)
    if container is None:
        return False, f"未找到 Composition: {edit.composition_path}"
    # refuse duplicate short-name in same CONNECTORS
    for c in container:
        if _local(c.tag) == "ASSEMBLY-SW-CONNECTOR" and _sn(c) == edit.connector_name:
            return False, f"XML 中已存在同名 Assembly: {edit.connector_name}"

    asm = _sub(container, "ASSEMBLY-SW-CONNECTOR")
    _sub(asm, "SHORT-NAME", edit.connector_name)
    prov = _sub(asm, "PROVIDER-IREF")
    _sub(
        prov,
        "CONTEXT-COMPONENT-REF",
        edit.provider_proto_ref,
        DEST="SW-COMPONENT-PROTOTYPE",
    )
    _sub(
        prov,
        "TARGET-P-PORT-REF",
        edit.provider_port_ref,
        DEST="P-PORT-PROTOTYPE",
    )
    req = _sub(asm, "REQUESTER-IREF")
    _sub(
        req,
        "CONTEXT-COMPONENT-REF",
        edit.requester_proto_ref,
        DEST="SW-COMPONENT-PROTOTYPE",
    )
    _sub(
        req,
        "TARGET-R-PORT-REF",
        edit.requester_port_ref,
        DEST="R-PORT-PROTOTYPE",
    )
    return True, ""


def _add_delegation_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    container = _find_connectors_container(root, edit.composition_path)
    if container is None:
        return False, f"未找到 Composition: {edit.composition_path}"
    for c in container:
        if _local(c.tag) == "DELEGATION-SW-CONNECTOR" and _sn(c) == edit.connector_name:
            return False, f"XML 中已存在同名 Delegation: {edit.connector_name}"

    direction = (edit.inner_direction or "R").upper()
    if direction not in ("P", "R"):
        direction = "R"
    dest_port = "P-PORT-PROTOTYPE" if direction == "P" else "R-PORT-PROTOTYPE"
    iref_tag = (
        "P-PORT-IN-COMPOSITION-INSTANCE-REF"
        if direction == "P"
        else "R-PORT-IN-COMPOSITION-INSTANCE-REF"
    )
    target_tag = "TARGET-P-PORT-REF" if direction == "P" else "TARGET-R-PORT-REF"

    dlg = _sub(container, "DELEGATION-SW-CONNECTOR")
    _sub(dlg, "SHORT-NAME", edit.connector_name)
    inner = _sub(dlg, "INNER-PORT-IREF")
    iref = _sub(inner, iref_tag)
    _sub(
        iref,
        "CONTEXT-COMPONENT-REF",
        edit.inner_proto_ref,
        DEST="SW-COMPONENT-PROTOTYPE",
    )
    _sub(iref, target_tag, edit.inner_port_ref, DEST=dest_port)
    _sub(dlg, "OUTER-PORT-REF", edit.outer_port_ref, DEST=dest_port)
    return True, ""


def _find_named_elem_by_path(root, abs_path: str, tag_candidates: tuple):
    if not abs_path:
        return None
    for el in root.iter():
        if _local(el.tag) not in tag_candidates:
            continue
        if _path_of(el) == abs_path:
            return el
    # fallback by short name
    tail = abs_path.rsplit("/", 1)[-1]
    for el in root.iter():
        if _local(el.tag) in tag_candidates and _sn(el) == tail:
            return el
    return None


def _port_ref_tags(root, port_ref: str) -> Tuple[str, str]:
    """Return (DEST, TARGET-*-PORT-REF tag) for a port path."""
    el = _find_named_elem_by_path(
        root, port_ref, ("P-PORT-PROTOTYPE", "R-PORT-PROTOTYPE")
    )
    if el is not None and _local(el.tag) == "R-PORT-PROTOTYPE":
        return "R-PORT-PROTOTYPE", "TARGET-R-PORT-REF"
    return "P-PORT-PROTOTYPE", "TARGET-P-PORT-REF"


def _signal_dest(root, signal_ref: str, mapping_kind: str) -> str:
    if mapping_kind == "SR-TO-I-SIGNAL" or (
        signal_ref
        and _find_named_elem_by_path(root, signal_ref, ("I-SIGNAL",)) is not None
    ):
        return "I-SIGNAL"
    return "SYSTEM-SIGNAL"


def _add_data_mapping_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    sm = _find_named_elem_by_path(root, edit.mapping_set_path, ("SYSTEM-MAPPING",))
    if sm is None:
        return False, f"未找到 SYSTEM-MAPPING: {edit.mapping_set_path}"
    container = _find_or_create_child(sm, "DATA-MAPPINGS")
    for c in container:
        if _local(c.tag) in (
            "SENDER-RECEIVER-TO-SIGNAL-MAPPING",
            "SENDER-RECEIVER-TO-I-SIGNAL-MAPPING",
        ) and _sn(c) == edit.connector_name:
            return False, f"XML 中已存在同名 Mapping: {edit.connector_name}"

    kind = edit.mapping_kind or "SR-TO-SIGNAL"
    tag = (
        "SENDER-RECEIVER-TO-I-SIGNAL-MAPPING"
        if kind == "SR-TO-I-SIGNAL"
        else "SENDER-RECEIVER-TO-SIGNAL-MAPPING"
    )
    mapping = _sub(container, tag)
    _sub(mapping, "SHORT-NAME", edit.connector_name)
    iref = _sub(mapping, "DATA-ELEMENT-IREF")
    _sub(
        iref,
        "CONTEXT-COMPONENT-REF",
        edit.component_ref,
        DEST="SW-COMPONENT-PROTOTYPE",
    )
    port_dest, port_tag = _port_ref_tags(root, edit.provider_port_ref)
    _sub(iref, port_tag, edit.provider_port_ref, DEST=port_dest)
    _sub(
        iref,
        "TARGET-DATA-PROTOTYPE-REF",
        edit.data_element_ref,
        DEST="VARIABLE-DATA-PROTOTYPE",
    )
    sig_dest = _signal_dest(root, edit.signal_ref, kind)
    sig_tag = "I-SIGNAL-REF" if sig_dest == "I-SIGNAL" else "SYSTEM-SIGNAL-REF"
    _sub(mapping, sig_tag, edit.signal_ref, DEST=sig_dest)
    return True, ""


def _delete_data_mapping_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    tags = (
        "SENDER-RECEIVER-TO-SIGNAL-MAPPING",
        "SENDER-RECEIVER-TO-I-SIGNAL-MAPPING",
    )
    el = _find_named_elem_by_path(root, edit.connector_path, tags)
    if el is None:
        return False, f"未找到 Mapping: {edit.connector_path}"
    parent = el.getparent()
    if parent is None:
        return False, "Mapping 无父节点"
    parent.remove(el)
    return True, ""


def _update_data_mapping_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    tags = (
        "SENDER-RECEIVER-TO-SIGNAL-MAPPING",
        "SENDER-RECEIVER-TO-I-SIGNAL-MAPPING",
    )
    el = _find_named_elem_by_path(root, edit.connector_path, tags)
    if el is None:
        return False, f"未找到 Mapping: {edit.connector_path}"
    if edit.new_name:
        _set_or_create_text(el, "SHORT-NAME", edit.new_name)
    if edit.signal_ref:
        # replace existing signal / i-signal ref
        for c in list(el):
            if _local(c.tag) in ("SYSTEM-SIGNAL-REF", "I-SIGNAL-REF"):
                el.remove(c)
        kind = edit.mapping_kind or "SR-TO-SIGNAL"
        sig_dest = _signal_dest(root, edit.signal_ref, kind)
        sig_tag = "I-SIGNAL-REF" if sig_dest == "I-SIGNAL" else "SYSTEM-SIGNAL-REF"
        _sub(el, sig_tag, edit.signal_ref, DEST=sig_dest)
    return True, ""


def _find_behavior_elem(root, behavior_path: str):
    return _find_named_elem_by_path(root, behavior_path, ("SWC-INTERNAL-BEHAVIOR",))


def _add_runnable_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    beh = _find_behavior_elem(root, edit.behavior_path)
    if beh is None:
        return False, f"未找到 Internal Behavior: {edit.behavior_path}"
    container = _find_or_create_child(beh, "RUNNABLES")
    for c in container:
        if _local(c.tag) == "RUNNABLE-ENTITY" and _sn(c) == edit.connector_name:
            return False, f"XML 中已存在 Runnable: {edit.connector_name}"
    re = _sub(container, "RUNNABLE-ENTITY")
    _sub(re, "SHORT-NAME", edit.connector_name)
    if edit.symbol:
        _sub(re, "SYMBOL", edit.symbol)
    return True, ""


def _delete_runnable_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    el = _find_named_elem_by_path(root, edit.runnable_path, ("RUNNABLE-ENTITY",))
    if el is None:
        return False, f"未找到 Runnable: {edit.runnable_path}"
    parent = el.getparent()
    if parent is None:
        return False, "Runnable 无父节点"
    parent.remove(el)
    return True, ""


def _set_runnable_symbol_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    el = _find_named_elem_by_path(root, edit.runnable_path, ("RUNNABLE-ENTITY",))
    if el is None:
        return False, f"未找到 Runnable: {edit.runnable_path}"
    _set_or_create_text(el, "SYMBOL", edit.symbol or "")
    return True, ""


def _add_timing_event_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    beh = _find_behavior_elem(root, edit.behavior_path)
    if beh is None:
        return False, f"未找到 Internal Behavior: {edit.behavior_path}"
    container = _find_or_create_child(beh, "EVENTS")
    for c in container:
        if _local(c.tag) in EVENT_TAGS and _sn(c) == edit.connector_name:
            return False, f"XML 中已存在 Event: {edit.connector_name}"
    ev = _sub(container, "TIMING-EVENT")
    _sub(ev, "SHORT-NAME", edit.connector_name)
    _sub(
        ev,
        "START-ON-EVENT-REF",
        edit.runnable_path,
        DEST="RUNNABLE-ENTITY",
    )
    _sub(ev, "PERIOD", edit.period or "0.01")
    if edit.offset:
        _sub(ev, "OFFSET", edit.offset)
    return True, ""


def _add_init_event_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    beh = _find_behavior_elem(root, edit.behavior_path)
    if beh is None:
        return False, f"未找到 Internal Behavior: {edit.behavior_path}"
    container = _find_or_create_child(beh, "EVENTS")
    for c in container:
        if _local(c.tag) in EVENT_TAGS and _sn(c) == edit.connector_name:
            return False, f"XML 中已存在 Event: {edit.connector_name}"
    ev = _sub(container, "INIT-EVENT")
    _sub(ev, "SHORT-NAME", edit.connector_name)
    _sub(
        ev,
        "START-ON-EVENT-REF",
        edit.runnable_path,
        DEST="RUNNABLE-ENTITY",
    )
    return True, ""


def _add_data_received_event_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    beh = _find_behavior_elem(root, edit.behavior_path)
    if beh is None:
        return False, f"未找到 Internal Behavior: {edit.behavior_path}"
    container = _find_or_create_child(beh, "EVENTS")
    for c in container:
        if _local(c.tag) in EVENT_TAGS and _sn(c) == edit.connector_name:
            return False, f"XML 中已存在 Event: {edit.connector_name}"
    ev = _sub(container, "DATA-RECEIVED-EVENT")
    _sub(ev, "SHORT-NAME", edit.connector_name)
    _sub(
        ev,
        "START-ON-EVENT-REF",
        edit.runnable_path,
        DEST="RUNNABLE-ENTITY",
    )
    # DATA-IREF
    data = _sub(ev, "DATA-IREF")
    port_dest, _ = _port_ref_tags(root, edit.provider_port_ref)
    _sub(
        data,
        "CONTEXT-R-PORT-REF",
        edit.provider_port_ref,
        DEST=port_dest,
    )
    _sub(
        data,
        "TARGET-DATA-ELEMENT-REF",
        edit.data_element_ref,
        DEST="VARIABLE-DATA-PROTOTYPE",
    )
    return True, ""


def _find_ar_package_for_path(root, package_path: str):
    """Find AR-PACKAGE whose absolute path equals package_path."""
    if not package_path:
        return None
    for el in root.iter():
        if _local(el.tag) != "AR-PACKAGE":
            continue
        if _path_of(el) == package_path:
            return el
    # create nested packages under AUTOSAR/AR-PACKAGES
    parts = [p for p in package_path.split("/") if p]
    if not parts:
        return None
    autosar = root
    packages = None
    for c in autosar:
        if _local(c.tag) == "AR-PACKAGES":
            packages = c
            break
    if packages is None:
        packages = _sub(autosar, "AR-PACKAGES")
    cur_pkg_parent = packages
    cur_path = ""
    target = None
    for part in parts:
        cur_path = f"{cur_path}/{part}"
        found = None
        # AR-PACKAGE children are under AR-PACKAGES or nested AR-PACKAGES
        search_in = cur_pkg_parent
        for c in search_in:
            if _local(c.tag) == "AR-PACKAGE" and _sn(c) == part:
                found = c
                break
            if _local(c.tag) == "AR-PACKAGES":
                for cc in c:
                    if _local(cc.tag) == "AR-PACKAGE" and _sn(cc) == part:
                        found = cc
                        break
        if found is None:
            # ensure AR-PACKAGES container
            if _local(cur_pkg_parent.tag) != "AR-PACKAGES":
                nested = None
                for c in cur_pkg_parent:
                    if _local(c.tag) == "AR-PACKAGES":
                        nested = c
                        break
                if nested is None:
                    nested = _sub(cur_pkg_parent, "AR-PACKAGES")
                cur_pkg_parent = nested
            found = _sub(cur_pkg_parent, "AR-PACKAGE")
            _sub(found, "SHORT-NAME", part)
        target = found
        cur_pkg_parent = found
    return target


def _add_system_signal_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    pkg = _find_ar_package_for_path(root, edit.package_path)
    if pkg is None:
        return False, f"无法创建/找到 AR-PACKAGE: {edit.package_path}"
    elements = _find_or_create_child(pkg, "ELEMENTS")
    for c in elements:
        if _local(c.tag) == "SYSTEM-SIGNAL" and _sn(c) == edit.connector_name:
            return False, f"XML 中已存在 SYSTEM-SIGNAL: {edit.connector_name}"
    sig = _sub(elements, "SYSTEM-SIGNAL")
    _sub(sig, "SHORT-NAME", edit.connector_name)
    return True, ""


def _add_system_mapping_set_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    """Create SYSTEM / MAPPINGS / SYSTEM-MAPPING stub."""
    pkg = _find_ar_package_for_path(root, edit.package_path)
    if pkg is None:
        return False, f"无法创建/找到 AR-PACKAGE: {edit.package_path}"
    elements = _find_or_create_child(pkg, "ELEMENTS")
    sys_name = edit.system_name or "System"
    system_el = None
    for c in elements:
        if _local(c.tag) == "SYSTEM" and _sn(c) == sys_name:
            system_el = c
            break
    if system_el is None:
        system_el = _sub(elements, "SYSTEM")
        _sub(system_el, "SHORT-NAME", sys_name)
    mappings = _find_or_create_child(system_el, "MAPPINGS")
    map_name = edit.connector_name or "SystemMapping"
    for c in mappings:
        if _local(c.tag) == "SYSTEM-MAPPING" and _sn(c) == map_name:
            return False, f"XML 中已存在 SYSTEM-MAPPING: {map_name}"
    sm = _sub(mappings, "SYSTEM-MAPPING")
    _sub(sm, "SHORT-NAME", map_name)
    return True, ""


def _find_swc_type_elem(root, swc_path: str):
    tags = (
        "APPLICATION-SW-COMPONENT-TYPE",
        "COMPOSITION-SW-COMPONENT-TYPE",
        "SENSOR-ACTUATOR-SW-COMPONENT-TYPE",
        "SERVICE-SW-COMPONENT-TYPE",
        "ECU-ABSTRACTION-SW-COMPONENT-TYPE",
        "COMPLEX-DEVICE-DRIVER-SW-COMPONENT-TYPE",
    )
    return _find_named_elem_by_path(root, swc_path, tags)


def _add_port_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    swc = _find_swc_type_elem(root, edit.owner_swc_path)
    if swc is None:
        return False, f"未找到 SWC: {edit.owner_swc_path}"
    ports = _find_or_create_child(swc, "PORTS")
    direction = (edit.port_direction or "R").upper()
    tag = "P-PORT-PROTOTYPE" if direction == "P" else "R-PORT-PROTOTYPE"
    for c in ports:
        if _local(c.tag) in ("P-PORT-PROTOTYPE", "R-PORT-PROTOTYPE") and _sn(c) == edit.connector_name:
            return False, f"XML 中已存在 Port: {edit.connector_name}"
    port_el = _sub(ports, tag)
    _sub(port_el, "SHORT-NAME", edit.connector_name)
    # interface tref
    iface = edit.interface_ref or ""
    dest = "SENDER-RECEIVER-INTERFACE"
    # detect CS by looking up element
    if _find_named_elem_by_path(root, iface, ("CLIENT-SERVER-INTERFACE",)) is not None:
        dest = "CLIENT-SERVER-INTERFACE"
    tref_tag = (
        "PROVIDED-INTERFACE-TREF" if direction == "P" else "REQUIRED-INTERFACE-TREF"
    )
    _sub(port_el, tref_tag, iface, DEST=dest)
    return True, ""


def _delete_rte_event_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    el = _find_named_elem_by_path(root, edit.event_path, EVENT_TAGS)
    if el is None:
        return False, f"未找到 Event: {edit.event_path}"
    parent = el.getparent()
    if parent is None:
        return False, "Event 无父节点"
    parent.remove(el)
    return True, ""


def _set_event_period_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    el = _find_named_elem_by_path(root, edit.event_path, EVENT_TAGS)
    if el is None:
        return False, f"未找到 Event: {edit.event_path}"
    _set_or_create_text(el, "PERIOD", edit.period or "0.01")
    return True, ""


def _set_event_runnable_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    el = _find_named_elem_by_path(root, edit.event_path, EVENT_TAGS)
    if el is None:
        return False, f"未找到 Event: {edit.event_path}"
    found = False
    for c in el:
        if _local(c.tag) == "START-ON-EVENT-REF":
            c.text = edit.runnable_path
            c.set("DEST", "RUNNABLE-ENTITY")
            found = True
            break
    if not found:
        _sub(
            el,
            "START-ON-EVENT-REF",
            edit.runnable_path,
            DEST="RUNNABLE-ENTITY",
        )
    return True, ""


def _add_port_access_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    re = _find_named_elem_by_path(root, edit.runnable_path, ("RUNNABLE-ENTITY",))
    if re is None:
        return False, f"未找到 Runnable: {edit.runnable_path}"
    kind = (edit.access_kind or "SEND").upper()
    container_tag = (
        "DATA-SEND-POINTS" if kind == "SEND" else "DATA-RECEIVE-POINT-BY-ARGUMENTS"
    )
    container = _find_or_create_child(re, container_tag)
    for c in container:
        if _local(c.tag) == "VARIABLE-ACCESS" and _sn(c) == edit.access_name:
            return False, f"XML 中已存在 Port Access: {edit.access_name}"
    va = _sub(container, "VARIABLE-ACCESS")
    _sub(va, "SHORT-NAME", edit.access_name)
    accessed = _sub(va, "ACCESSED-VARIABLE")
    iref = _sub(accessed, "AUTOSAR-VARIABLE-IREF")
    port_dest, _ = _port_ref_tags(root, edit.provider_port_ref)
    _sub(
        iref,
        "PORT-PROTOTYPE-REF",
        edit.provider_port_ref,
        DEST=port_dest,
    )
    _sub(
        iref,
        "TARGET-DATA-PROTOTYPE-REF",
        edit.data_element_ref,
        DEST="VARIABLE-DATA-PROTOTYPE",
    )
    return True, ""


def _delete_port_access_elem(root, edit: PendingEdit) -> Tuple[bool, str]:
    re = _find_named_elem_by_path(root, edit.runnable_path, ("RUNNABLE-ENTITY",))
    if re is None:
        return False, f"未找到 Runnable: {edit.runnable_path}"
    want = edit.access_name or (
        edit.connector_path.rsplit("/", 1)[-1] if edit.connector_path else ""
    )
    if not want:
        return False, "缺少 Port Access 名称"
    for container_tag in (
        "DATA-SEND-POINTS",
        "DATA-RECEIVE-POINT-BY-ARGUMENTS",
        "DATA-RECEIVE-POINT-BY-VALUES",
        "DATA-WRITE-ACCESSS",
        "DATA-READ-ACCESSS",
        "DATA-WRITE-ACCESS",
        "DATA-READ-ACCESS",
    ):
        for cont in re:
            if _local(cont.tag) != container_tag:
                continue
            for va in list(cont):
                if _local(va.tag) == "VARIABLE-ACCESS" and _sn(va) == want:
                    cont.remove(va)
                    return True, ""
    # also match by absolute path if SHORT-NAME differs
    if edit.connector_path:
        for va in re.iter():
            if _local(va.tag) != "VARIABLE-ACCESS":
                continue
            if _path_of(va) == edit.connector_path:
                parent = va.getparent()
                if parent is not None:
                    parent.remove(va)
                    return True, ""
    return False, f"未找到 Port Access: {want}"


def apply_edits_to_tree(root, edits: List[PendingEdit]) -> Tuple[int, List[str]]:
    """Mutate XML tree. Returns (applied_count, warnings)."""
    applied = 0
    warnings: List[str] = []
    handlers = {
        "add_assembly": _add_assembly_elem,
        "add_delegation": _add_delegation_elem,
        "rename_element": _rename_element,
        "add_data_mapping": _add_data_mapping_elem,
        "delete_data_mapping": _delete_data_mapping_elem,
        "update_data_mapping": _update_data_mapping_elem,
        "add_runnable": _add_runnable_elem,
        "delete_runnable": _delete_runnable_elem,
        "set_runnable_symbol": _set_runnable_symbol_elem,
        "add_timing_event": _add_timing_event_elem,
        "add_init_event": _add_init_event_elem,
        "add_data_received_event": _add_data_received_event_elem,
        "delete_rte_event": _delete_rte_event_elem,
        "set_event_period": _set_event_period_elem,
        "set_event_runnable": _set_event_runnable_elem,
        "add_port_access": _add_port_access_elem,
        "delete_port_access": _delete_port_access_elem,
        "add_system_signal": _add_system_signal_elem,
        "add_system_mapping_set": _add_system_mapping_set_elem,
        "add_port": _add_port_elem,
    }
    for edit in edits:
        handler = handlers.get(edit.kind)
        if handler is not None:
            ok, err = handler(root, edit)
            if ok:
                applied += 1
            else:
                warnings.append(err or f"{edit.kind} 失败")
            continue

        el = _find_connector_elem(root, edit)
        if el is None:
            warnings.append(
                f"未找到连接器: {edit.connector_kind} {edit.connector_name} "
                f"@ {edit.composition_path}"
            )
            continue
        if edit.kind == "delete_connector":
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
                applied += 1
        elif edit.kind == "rename_connector":
            if not edit.new_name:
                warnings.append(f"重命名缺少新名: {edit.connector_name}")
                continue
            sn_el = None
            for c in el:
                if _local(c.tag) == "SHORT-NAME":
                    sn_el = c
                    break
            if sn_el is None:
                warnings.append(f"无 SHORT-NAME: {edit.connector_name}")
                continue
            sn_el.text = edit.new_name
            applied += 1
        else:
            warnings.append(f"未知编辑类型: {edit.kind}")
    return applied, warnings


def _rename_element(root, edit: PendingEdit) -> Tuple[bool, str]:
    old_path = edit.element_path or edit.connector_path
    new_name = edit.new_name
    if not old_path or not new_name:
        return False, "重命名缺少路径或新名"
    kind = edit.element_kind
    tag_map = {
        "port": ("P-PORT-PROTOTYPE", "R-PORT-PROTOTYPE"),
        "adt": (
            "APPLICATION-PRIMITIVE-DATA-TYPE",
            "APPLICATION-RECORD-DATA-TYPE",
            "APPLICATION-ARRAY-DATA-TYPE",
        ),
        "idt": ("IMPLEMENTATION-DATA-TYPE",),
        "sr_interface": ("SENDER-RECEIVER-INTERFACE",),
        "runnable": ("RUNNABLE-ENTITY",),
        "rte_event": EVENT_TAGS,
    }
    tags = tag_map.get(kind)
    if not tags:
        return False, f"未知元素类型: {kind}"
    el = _find_named_elem_by_path(root, old_path, tags)
    if el is None:
        return False, f"未找到元素: {old_path}"
    sn_el = None
    for c in el:
        if _local(c.tag) == "SHORT-NAME":
            sn_el = c
            break
    if sn_el is None:
        return False, f"无 SHORT-NAME: {old_path}"
    sn_el.text = new_name
    parent = old_path.rsplit("/", 1)[0] if "/" in old_path else ""
    new_path = f"{parent}/{new_name}" if parent else new_name
    # Rewrite absolute path references across the document
    if old_path != new_path:
        for node in root.iter():
            if node.text and node.text.strip() == old_path:
                node.text = new_path
    return True, ""


def write_pending_snapshot(model, dest_path: str) -> Tuple[bool, str]:
    """
    Apply pending_edits onto a copy of the source ARXML and write to dest_path.
    Does not mutate model.filepath or clear pending_edits (for validate-with-pending).
    """
    src = model.filepath
    if not src or not os.path.isfile(src):
        return False, "没有有效的源 ARXML 路径"
    if not model.pending_edits:
        return False, "没有待保存的修改"
    if not dest_path:
        return False, "未指定输出路径"

    parser = etree.XMLParser(remove_comments=False, huge_tree=True, recover=True)
    try:
        tree = etree.parse(src, parser)
    except Exception as e:
        return False, f"读取失败: {e}"

    root = tree.getroot()
    applied, warnings = apply_edits_to_tree(root, list(model.pending_edits))
    if applied == 0:
        return False, "没有成功应用任何修改\n" + "\n".join(warnings)

    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
        tree.write(
            dest_path,
            xml_declaration=True,
            encoding="UTF-8",
            pretty_print=False,
        )
    except Exception as e:
        return False, f"写入失败: {e}"

    msg = f"已写出快照 {dest_path}（应用 {applied} 处修改，未清空 pending）"
    if warnings:
        msg += "\n警告:\n" + "\n".join(warnings)
    return True, msg


def save_arxml(
    model,
    dest_path: Optional[str] = None,
    *,
    make_backup: bool = True,
) -> Tuple[bool, str]:
    """
    Reload source ARXML, apply pending_edits, write to dest_path (or overwrite source).
    Returns (ok, message).
    """
    src = model.filepath
    if not src or not os.path.isfile(src):
        return False, "没有有效的源 ARXML 路径"
    if not model.pending_edits:
        return False, "没有待保存的修改"

    dest = dest_path or src
    parser = etree.XMLParser(remove_comments=False, huge_tree=True, recover=True)
    try:
        tree = etree.parse(src, parser)
    except Exception as e:
        return False, f"读取失败: {e}"

    root = tree.getroot()
    applied, warnings = apply_edits_to_tree(root, model.pending_edits)
    if applied == 0:
        return False, "没有成功应用任何修改\n" + "\n".join(warnings)

    if make_backup and os.path.abspath(dest) == os.path.abspath(src):
        bak = src + ".bak"
        try:
            shutil.copy2(src, bak)
        except Exception as e:
            return False, f"备份失败: {e}"

    try:
        tree.write(
            dest,
            xml_declaration=True,
            encoding="UTF-8",
            pretty_print=False,
        )
    except Exception as e:
        return False, f"写入失败: {e}"

    model.filepath = dest
    model.pending_edits.clear()
    msg = f"已写入 {dest}（应用 {applied} 处修改）"
    if warnings:
        msg += "\n警告:\n" + "\n".join(warnings)
    if make_backup and os.path.abspath(dest) == os.path.abspath(src):
        msg += f"\n备份: {src}.bak"
    return True, msg
