# -*- coding: utf-8 -*-
"""Parse AUTOSAR CP ARXML into ArxmlModel."""
from __future__ import annotations

from typing import Callable, Optional

from lxml import etree

from .model import (
    AdtRecordElement,
    ApplicationDataType,
    ArxmlModel,
    DataMapping,
    DataTypeMap,
    ImplementationDataType,
    SwBaseType,
    AssemblyConnector,
    CsInterface,
    CsOperation,
    DataElement,
    DelegationConnector,
    Port,
    PortAccess,
    Prototype,
    RteEvent,
    RunnableEntity,
    SrInterface,
    SwcInternalBehavior,
    SwcType,
)

NS_AUTOSAR = "http://autosar.org/schema/r4.0"


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag


def _sn(elem) -> str:
    for c in elem:
        if _local(c.tag) == "SHORT-NAME" and c.text:
            return c.text.strip()
    return ""


def _text(elem) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _child(elem, name: str):
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _children(elem, name: str):
    return [c for c in elem if _local(c.tag) == name]


def _find_deep(elem, name: str):
    for e in elem.iter():
        if _local(e.tag) == name:
            return e
    return None


def _findall_deep(elem, name: str):
    return [e for e in elem.iter() if _local(e.tag) == name]


def _path_of(elem) -> str:
    """Build AUTOSAR absolute path from SHORT-NAME ancestors."""
    parts = []
    cur = elem
    while cur is not None:
        tag = _local(cur.tag)
        if tag in (
            "AR-PACKAGE",
            "APPLICATION-SW-COMPONENT-TYPE",
            "COMPOSITION-SW-COMPONENT-TYPE",
            "SW-COMPONENT-PROTOTYPE",
            "P-PORT-PROTOTYPE",
            "R-PORT-PROTOTYPE",
            "SENDER-RECEIVER-INTERFACE",
            "CLIENT-SERVER-INTERFACE",
            "VARIABLE-DATA-PROTOTYPE",
            "CLIENT-SERVER-OPERATION",
            "ASSEMBLY-SW-CONNECTOR",
            "DELEGATION-SW-CONNECTOR",
            "SWC-INTERNAL-BEHAVIOR",
            "RUNNABLE-ENTITY",
            "TIMING-EVENT",
            "INIT-EVENT",
            "DATA-RECEIVED-EVENT",
            "OPERATION-INVOKED-EVENT",
            "BACKGROUND-EVENT",
            "MODE-SWITCH-EVENT",
            "VARIABLE-ACCESS",
            "SERVER-CALL-POINT",
            "SYNCHRONOUS-SERVER-CALL-POINT",
            "ASYNCHRONOUS-SERVER-CALL-POINT",
            "APPLICATION-PRIMITIVE-DATA-TYPE",
            "APPLICATION-RECORD-DATA-TYPE",
            "APPLICATION-ARRAY-DATA-TYPE",
            "APPLICATION-RECORD-ELEMENT",
            "IMPLEMENTATION-DATA-TYPE",
            "SW-BASE-TYPE",
            "COMPU-METHOD",
            "DATA-CONSTR",
            "SENDER-RECEIVER-TO-SIGNAL-MAPPING",
            "SENDER-RECEIVER-TO-I-SIGNAL-MAPPING",
            "I-SIGNAL",
            "SYSTEM-SIGNAL",
            "SYSTEM",
            "SYSTEM-MAPPING",
        ):
            name = _sn(cur)
            if name:
                parts.append(name)
        parent = cur.getparent()
        cur = parent
    parts.reverse()
    return "/" + "/".join(parts) if parts else ""


class ArxmlParser:
    def __init__(self, progress: Optional[Callable[[str], None]] = None):
        self.progress = progress or (lambda _m: None)

    def parse(self, filepath: str) -> ArxmlModel:
        self.progress("Loading XML…")
        # huge_tree for large files
        parser = etree.XMLParser(remove_comments=True, huge_tree=True, recover=True)
        tree = etree.parse(filepath, parser)
        root = tree.getroot()
        model = ArxmlModel(filepath=filepath)

        self.progress("Scanning element counts…")
        counts = self._count_interest(root)
        self.progress(
            f"Scan: SR-IF={counts.get('SENDER-RECEIVER-INTERFACE', 0)} "
            f"CS-IF={counts.get('CLIENT-SERVER-INTERFACE', 0)} "
            f"ADT={counts.get('APPLICATION-PRIMITIVE-DATA-TYPE', 0) + counts.get('APPLICATION-RECORD-DATA-TYPE', 0) + counts.get('APPLICATION-ARRAY-DATA-TYPE', 0)} "
            f"IDT={counts.get('IMPLEMENTATION-DATA-TYPE', 0)} "
            f"SWC={counts.get('APPLICATION-SW-COMPONENT-TYPE', 0)} "
            f"Comp={counts.get('COMPOSITION-SW-COMPONENT-TYPE', 0)} "
            f"Asm={counts.get('ASSEMBLY-SW-CONNECTOR', 0)} "
            f"Del={counts.get('DELEGATION-SW-CONNECTOR', 0)}"
        )

        self.progress("Parsing SR / CS interfaces…")
        self._parse_interfaces(root, model)
        self.progress(
            f"Interfaces done: SR={len(model.interfaces)} CS={len(model.cs_interfaces)}"
        )

        self.progress("Parsing ADT / IDT / BaseTypes…")
        self._parse_data_types(root, model, counts=counts)
        prim, rec, arr, n_idt, n_base = model.adt_summary()
        self.progress(
            f"DataTypes done: ADT={prim}+{rec}+{arr} IDT={n_idt} Base={n_base} "
            f"Maps={len(model.data_type_maps)}"
        )

        self.progress("Parsing SWC / Composition types…")
        self._parse_swc_types(root, model)
        self.progress(
            f"SWC done: types={len(model.swc_types)} ports={len(model.ports)} "
            f"prototypes={len(model.prototypes)}"
        )

        self.progress("Parsing connectors…")
        self._parse_connectors(root, model, counts=counts)
        self.progress(
            f"Connectors done: Assembly={len(model.assemblies)} "
            f"Delegation={len(model.delegations)}"
        )

        self.progress("Parsing SWC Internal Behaviors (RTE)…")
        self._parse_internal_behaviors(root, model, counts=counts)
        n_beh, n_run, n_ev, n_ok = model.rte_summary()
        self.progress(f"RTE done: IB={n_beh} Runnables={n_run} Events={n_ev}")

        self.progress("Parsing system data mappings…")
        self._parse_data_mappings(root, model)
        self.progress(f"DataMappings done: {len(model.data_mappings)}")

        self.progress("Building indexes…")
        self._finalize(model)
        self.progress("Done.")
        return model

    def _count_interest(self, root) -> dict:
        tags = {
            "SENDER-RECEIVER-INTERFACE",
            "CLIENT-SERVER-INTERFACE",
            "APPLICATION-PRIMITIVE-DATA-TYPE",
            "APPLICATION-RECORD-DATA-TYPE",
            "APPLICATION-ARRAY-DATA-TYPE",
            "IMPLEMENTATION-DATA-TYPE",
            "SW-BASE-TYPE",
            "DATA-TYPE-MAP",
            "APPLICATION-SW-COMPONENT-TYPE",
            "COMPOSITION-SW-COMPONENT-TYPE",
            "ASSEMBLY-SW-CONNECTOR",
            "DELEGATION-SW-CONNECTOR",
            "SWC-INTERNAL-BEHAVIOR",
            "RUNNABLE-ENTITY",
            "TIMING-EVENT",
        }
        counts: dict = {}
        n = 0
        for el in root.iter():
            tag = _local(el.tag)
            if tag in tags:
                counts[tag] = counts.get(tag, 0) + 1
            n += 1
            if n % 200_000 == 0:
                self.progress(f"Scanning… {n // 1000}k elements")
        return counts

    def _parse_interfaces(self, root, model: ArxmlModel):
        for iface_el in root.iter():
            tag = _local(iface_el.tag)
            if tag == "SENDER-RECEIVER-INTERFACE":
                name = _sn(iface_el)
                path = _path_of(iface_el)
                if not path:
                    continue
                iface = SrInterface(name=name, path=path)
                de_container = _child(iface_el, "DATA-ELEMENTS")
                if de_container is not None:
                    for vdp in _children(de_container, "VARIABLE-DATA-PROTOTYPE"):
                        den = _sn(vdp)
                        de_path = f"{path}/{den}" if den else _path_of(vdp)
                        tref = _child(vdp, "TYPE-TREF")
                        iface.data_elements.append(
                            DataElement(
                                name=den,
                                path=de_path,
                                type_ref=_text(tref),
                                type_dest=tref.get("DEST", "") if tref is not None else "",
                            )
                        )
                model.interfaces[path] = iface
            elif tag == "CLIENT-SERVER-INTERFACE":
                name = _sn(iface_el)
                path = _path_of(iface_el)
                if not path:
                    continue
                cs = CsInterface(name=name, path=path)
                ops_el = _child(iface_el, "OPERATIONS")
                if ops_el is not None:
                    for op_el in _children(ops_el, "CLIENT-SERVER-OPERATION"):
                        on = _sn(op_el)
                        op_path = f"{path}/{on}" if on else _path_of(op_el)
                        args: list[str] = []
                        args_el = _child(op_el, "ARGUMENTS")
                        if args_el is not None:
                            for arg in args_el:
                                if _local(arg.tag) == "ARGUMENT-DATA-PROTOTYPE":
                                    an = _sn(arg)
                                    if an:
                                        args.append(an)
                        cs.operations.append(
                            CsOperation(name=on, path=op_path, arguments=args)
                        )
                model.cs_interfaces[path] = cs

    def _parse_ports(self, owner_el, owner_path: str, model: ArxmlModel) -> list:
        ports = []
        ports_el = _child(owner_el, "PORTS")
        if ports_el is None:
            return ports
        for pel in ports_el:
            tag = _local(pel.tag)
            if tag == "P-PORT-PROTOTYPE":
                direction = "P"
                iref = _child(pel, "PROVIDED-INTERFACE-TREF")
            elif tag == "R-PORT-PROTOTYPE":
                direction = "R"
                iref = _child(pel, "REQUIRED-INTERFACE-TREF")
            else:
                continue
            pname = _sn(pel)
            ppath = f"{owner_path}/{pname}" if pname else _path_of(pel)
            dest = iref.get("DEST", "") if iref is not None else ""
            iref_path = _text(iref)
            if dest == "CLIENT-SERVER-INTERFACE" or iref_path in model.cs_interfaces:
                iface_kind = "CS"
            elif dest == "SENDER-RECEIVER-INTERFACE" or iref_path in model.interfaces:
                iface_kind = "SR"
            else:
                iface_kind = "OTHER"
            port = Port(
                name=pname,
                path=ppath,
                direction=direction,
                owner_path=owner_path,
                interface_ref=iref_path,
                interface_dest=dest,
                iface_kind=iface_kind,
            )
            ports.append(port)
            model.ports[ppath] = port
        return ports

    def _parse_swc_types(self, root, model: ArxmlModel):
        for el in root.iter():
            tag = _local(el.tag)
            if tag == "APPLICATION-SW-COMPONENT-TYPE":
                kind = "APPLICATION"
            elif tag == "COMPOSITION-SW-COMPONENT-TYPE":
                kind = "COMPOSITION"
            else:
                continue
            name = _sn(el)
            path = _path_of(el)
            if not path:
                continue
            swc = SwcType(name=name, path=path, kind=kind)
            swc.ports = self._parse_ports(el, path, model)

            if kind == "COMPOSITION":
                comps = _child(el, "COMPONENTS")
                if comps is not None:
                    for proto_el in _children(comps, "SW-COMPONENT-PROTOTYPE"):
                        pn = _sn(proto_el)
                        ppath = f"{path}/{pn}" if pn else _path_of(proto_el)
                        tref = _child(proto_el, "TYPE-TREF")
                        proto = Prototype(
                            name=pn,
                            path=ppath,
                            composition_path=path,
                            type_ref=_text(tref),
                            type_dest=tref.get("DEST", "") if tref is not None else "",
                        )
                        swc.prototypes.append(proto)
                        model.prototypes[ppath] = proto

            model.swc_types[path] = swc

    def _parse_data_types(self, root, model: ArxmlModel, counts: Optional[dict] = None):
        total = 0
        if counts:
            total = (
                counts.get("APPLICATION-PRIMITIVE-DATA-TYPE", 0)
                + counts.get("APPLICATION-RECORD-DATA-TYPE", 0)
                + counts.get("APPLICATION-ARRAY-DATA-TYPE", 0)
                + counts.get("IMPLEMENTATION-DATA-TYPE", 0)
                + counts.get("SW-BASE-TYPE", 0)
                + counts.get("DATA-TYPE-MAP", 0)
            )
        done = 0
        report_every = max(50, total // 20) if total else 200
        for el in root.iter():
            tag = _local(el.tag)
            hit = False
            if tag == "APPLICATION-PRIMITIVE-DATA-TYPE":
                self._parse_adt_primitive(el, model)
                hit = True
            elif tag == "APPLICATION-RECORD-DATA-TYPE":
                self._parse_adt_record(el, model)
                hit = True
            elif tag == "APPLICATION-ARRAY-DATA-TYPE":
                self._parse_adt_array(el, model)
                hit = True
            elif tag == "IMPLEMENTATION-DATA-TYPE":
                self._parse_idt(el, model)
                hit = True
            elif tag == "SW-BASE-TYPE":
                self._parse_base_type(el, model)
                hit = True
            elif tag == "DATA-TYPE-MAP":
                self._parse_data_type_map(el, model)
                hit = True
            if hit:
                done += 1
                if total and done % report_every == 0:
                    self.progress(f"DataTypes… {done}/{total}")
                elif not total and done % report_every == 0:
                    self.progress(f"DataTypes… {done}")

    def _sw_def_prop_ref(self, el, ref_tag: str) -> str:
        props = _find_deep(el, "SW-DATA-DEF-PROPS-CONDITIONAL")
        if props is None:
            props = _find_deep(el, "SW-DATA-DEF-PROPS")
        if props is None:
            return ""
        return _text(_child(props, ref_tag)) or _text(_find_deep(props, ref_tag))

    def _parse_adt_primitive(self, el, model: ArxmlModel):
        name = _sn(el)
        path = _path_of(el)
        if not path:
            return
        cat = _text(_child(el, "CATEGORY"))
        model.adts[path] = ApplicationDataType(
            name=name,
            path=path,
            kind="PRIMITIVE",
            category=cat,
            compu_method_ref=self._sw_def_prop_ref(el, "COMPU-METHOD-REF"),
            data_constr_ref=self._sw_def_prop_ref(el, "DATA-CONSTR-REF"),
        )

    def _parse_adt_record(self, el, model: ArxmlModel):
        name = _sn(el)
        path = _path_of(el)
        if not path:
            return
        cat = _text(_child(el, "CATEGORY")) or "STRUCTURE"
        adt = ApplicationDataType(
            name=name,
            path=path,
            kind="RECORD",
            category=cat,
            compu_method_ref=self._sw_def_prop_ref(el, "COMPU-METHOD-REF"),
            data_constr_ref=self._sw_def_prop_ref(el, "DATA-CONSTR-REF"),
        )
        elems = _child(el, "ELEMENTS")
        if elems is not None:
            for re_el in _children(elems, "APPLICATION-RECORD-ELEMENT"):
                en = _sn(re_el)
                epath = _path_of(re_el) or (f"{path}/{en}" if en else "")
                tref = _child(re_el, "TYPE-TREF")
                adt.elements.append(
                    AdtRecordElement(
                        name=en,
                        path=epath,
                        type_ref=_text(tref),
                        type_dest=tref.get("DEST", "") if tref is not None else "",
                    )
                )
        model.adts[path] = adt

    def _parse_adt_array(self, el, model: ArxmlModel):
        name = _sn(el)
        path = _path_of(el)
        if not path:
            return
        cat = _text(_child(el, "CATEGORY")) or "ARRAY"
        elem = _child(el, "ELEMENT")
        type_ref = ""
        type_dest = ""
        size = ""
        sem = ""
        if elem is not None:
            tref = _child(elem, "TYPE-TREF")
            type_ref = _text(tref)
            type_dest = tref.get("DEST", "") if tref is not None else ""
            size = _text(_child(elem, "MAX-NUMBER-OF-ELEMENTS"))
            sem = _text(_child(elem, "ARRAY-SIZE-SEMANTICS"))
        model.adts[path] = ApplicationDataType(
            name=name,
            path=path,
            kind="ARRAY",
            category=cat,
            element_type_ref=type_ref,
            element_type_dest=type_dest,
            array_size=size,
            array_size_semantics=sem,
            compu_method_ref=self._sw_def_prop_ref(el, "COMPU-METHOD-REF"),
            data_constr_ref=self._sw_def_prop_ref(el, "DATA-CONSTR-REF"),
        )

    def _parse_idt(self, el, model: ArxmlModel):
        name = _sn(el)
        path = _path_of(el)
        if not path:
            return
        cat = _text(_child(el, "CATEGORY"))
        base = self._sw_def_prop_ref(el, "BASE-TYPE-REF")
        model.idts[path] = ImplementationDataType(
            name=name,
            path=path,
            category=cat,
            base_type_ref=base,
        )

    def _parse_base_type(self, el, model: ArxmlModel):
        name = _sn(el)
        path = _path_of(el)
        if not path:
            return
        model.base_types[path] = SwBaseType(
            name=name,
            path=path,
            category=_text(_child(el, "CATEGORY")),
            size=_text(_child(el, "BASE-TYPE-SIZE")),
            encoding=_text(_child(el, "BASE-TYPE-ENCODING")),
            native_declaration=_text(_child(el, "NATIVE-DECLARATION")),
        )

    def _parse_data_type_map(self, el, model: ArxmlModel):
        aref = _child(el, "APPLICATION-DATA-TYPE-REF")
        iref = _child(el, "IMPLEMENTATION-DATA-TYPE-REF")
        adt = _text(aref)
        idt = _text(iref)
        if not adt and not idt:
            return
        model.data_type_maps.append(
            DataTypeMap(
                adt_ref=adt,
                idt_ref=idt,
                adt_dest=aref.get("DEST", "") if aref is not None else "",
                idt_dest=iref.get("DEST", "") if iref is not None else "",
            )
        )

    def _parse_data_mappings(self, root, model: ArxmlModel):
        """Parse system-level SR↔Signal mappings when present."""
        for el in root.iter():
            tag = _local(el.tag)
            if tag == "SYSTEM-SIGNAL":
                p = _path_of(el)
                if p:
                    model.system_signals[p] = _sn(el) or p.rsplit("/", 1)[-1]
                continue
            if tag == "I-SIGNAL":
                p = _path_of(el)
                if p:
                    model.i_signals[p] = _sn(el) or p.rsplit("/", 1)[-1]
                continue
            if tag == "SYSTEM-MAPPING":
                p = _path_of(el)
                if p and p not in model.system_mapping_sets:
                    model.system_mapping_sets.append(p)
                continue
            if tag not in (
                "SENDER-RECEIVER-TO-SIGNAL-MAPPING",
                "SENDER-RECEIVER-TO-I-SIGNAL-MAPPING",
            ):
                continue
            name = _sn(el) or tag
            path = _path_of(el) or name
            kind = "SR-TO-I-SIGNAL" if "I-SIGNAL" in tag else "SR-TO-SIGNAL"
            # owner SYSTEM-MAPPING
            set_path = ""
            cur = el.getparent()
            while cur is not None:
                if _local(cur.tag) == "SYSTEM-MAPPING":
                    set_path = _path_of(cur)
                    break
                cur = cur.getparent()
            if set_path and set_path not in model.system_mapping_sets:
                model.system_mapping_sets.append(set_path)
            comp = (
                _text(_find_deep(el, "CONTEXT-COMPONENT-REF"))
                or _text(_find_deep(el, "SW-COMPONENT-PROTOTYPE-REF"))
            )
            port = (
                _text(_find_deep(el, "TARGET-P-PORT-REF"))
                or _text(_find_deep(el, "TARGET-R-PORT-REF"))
                or _text(_find_deep(el, "PORT-PROTOTYPE-REF"))
            )
            de = (
                _text(_find_deep(el, "TARGET-DATA-PROTOTYPE-REF"))
                or _text(_find_deep(el, "DATA-ELEMENT-PROTOTYPE-REF"))
            )
            sig = (
                _text(_find_deep(el, "SYSTEM-SIGNAL-REF"))
                or _text(_find_deep(el, "I-SIGNAL-REF"))
                or _text(_find_deep(el, "TARGET-I-SIGNAL-REF"))
            )
            model.data_mappings.append(
                DataMapping(
                    name=name,
                    path=path,
                    kind=kind,
                    component_ref=comp,
                    port_ref=port,
                    data_element_ref=de,
                    signal_ref=sig,
                    system_signal_ref=sig,
                    mapping_set_path=set_path,
                )
            )

    def _parse_internal_behaviors(
        self, root, model: ArxmlModel, counts: Optional[dict] = None
    ):
        total = counts.get("SWC-INTERNAL-BEHAVIOR", 0) if counts else 0
        done = 0
        report_every = max(5, total // 10) if total else 20
        for el in root.iter():
            if _local(el.tag) != "SWC-INTERNAL-BEHAVIOR":
                continue
            done += 1
            if total and done % report_every == 0:
                self.progress(f"Internal Behavior… {done}/{total}")
            # owner APPLICATION-SW-COMPONENT-TYPE
            owner = ""
            cur = el.getparent()
            while cur is not None:
                if _local(cur.tag) == "APPLICATION-SW-COMPONENT-TYPE":
                    owner = _path_of(cur)
                    break
                cur = cur.getparent()
            if not owner:
                continue
            bname = _sn(el) or "IB"
            bpath = _path_of(el) or f"{owner}/{bname}"
            beh = SwcInternalBehavior(name=bname, path=bpath, owner_swc=owner)

            runnables_el = _child(el, "RUNNABLES")
            if runnables_el is not None:
                for re_el in _children(runnables_el, "RUNNABLE-ENTITY"):
                    r = self._parse_runnable(re_el, bpath, owner)
                    beh.runnables.append(r)
                    model.runnables[r.path] = r

            events_el = _child(el, "EVENTS")
            if events_el is not None:
                for ev_el in events_el:
                    tag = _local(ev_el.tag)
                    if not tag.endswith("-EVENT") and tag not in (
                        "TIMING-EVENT",
                        "INIT-EVENT",
                        "DATA-RECEIVED-EVENT",
                        "OPERATION-INVOKED-EVENT",
                        "BACKGROUND-EVENT",
                        "MODE-SWITCH-EVENT",
                    ):
                        continue
                    ev = self._parse_rte_event(ev_el, tag, bpath, owner)
                    beh.events.append(ev)
                    model.rte_events[ev.path] = ev

            model.behaviors_by_swc.setdefault(owner, []).append(beh)
            swc = model.swc_types.get(owner)
            if swc:
                swc.behaviors.append(beh)

    def _parse_runnable(self, el, behavior_path: str, owner_swc: str) -> RunnableEntity:
        name = _sn(el)
        path = _path_of(el) or (f"{behavior_path}/{name}" if name else f"{behavior_path}/Runnable")
        symbol = _text(_child(el, "SYMBOL"))
        r = RunnableEntity(
            name=name,
            path=path,
            behavior_path=behavior_path,
            owner_swc=owner_swc,
            symbol=symbol,
        )
        # Data send / receive → VARIABLE-ACCESS
        for tag, kind in (
            ("DATA-SEND-POINTS", "SEND"),
            ("DATA-RECEIVE-POINT-BY-ARGUMENTS", "RECEIVE"),
            ("DATA-RECEIVE-POINT-BY-VALUES", "RECEIVE"),
            ("DATA-WRITE-ACCESSES", "SEND"),
            ("DATA-READ-ACCESSES", "RECEIVE"),
        ):
            container = _child(el, tag)
            if container is None:
                continue
            for va in _children(container, "VARIABLE-ACCESS"):
                acc = self._parse_variable_access(va, kind, path)
                if acc:
                    r.accesses.append(acc)
        # Server call points
        for tag in (
            "SERVER-CALL-POINTS",
            "SYNCHRONOUS-SERVER-CALL-POINTS",
            "ASYNCHRONOUS-SERVER-CALL-POINTS",
        ):
            container = _child(el, tag)
            if container is None:
                continue
            for scp in container:
                ct = _local(scp.tag)
                if "SERVER-CALL-POINT" not in ct:
                    continue
                acc = self._parse_server_call(scp, path)
                if acc:
                    r.accesses.append(acc)
        return r

    def _parse_variable_access(self, el, kind: str, runnable_path: str) -> Optional[PortAccess]:
        name = _sn(el)
        path = _path_of(el) or ""
        port_ref = ""
        de_ref = ""
        # AUTOSAR-VARIABLE-IREF / AUTOSAR-VARIABLE-IN-IMPL-DATATYPE
        for iref_tag in (
            "AUTOSAR-VARIABLE-IREF",
            "AUTOSAR-VARIABLE-IN-IMPL-DATATYPE",
            "VARIABLE-DATA-PROTOTYPE-REF",
        ):
            iref = _find_deep(el, iref_tag)
            if iref is None:
                continue
            if _local(iref.tag) == "VARIABLE-DATA-PROTOTYPE-REF":
                de_ref = _text(iref)
                break
            pref = _child(iref, "PORT-PROTOTYPE-REF")
            tref = _child(iref, "TARGET-DATA-PROTOTYPE-REF")
            if pref is None:
                pref = _find_deep(iref, "PORT-PROTOTYPE-REF")
            if tref is None:
                tref = _find_deep(iref, "TARGET-DATA-PROTOTYPE-REF")
            port_ref = _text(pref)
            de_ref = _text(tref)
            break
        if not port_ref and not de_ref and not name:
            # empty stub
            return PortAccess(access_kind=kind, name=name, path=path, runnable_path=runnable_path)
        return PortAccess(
            access_kind=kind,
            name=name,
            path=path,
            runnable_path=runnable_path,
            port_ref=port_ref,
            data_element_ref=de_ref,
        )

    def _parse_server_call(self, el, runnable_path: str) -> Optional[PortAccess]:
        name = _sn(el)
        path = _path_of(el) or ""
        port_ref = ""
        op_ref = ""
        # OPERATION-IREF under CONTEXT-R-PORT-REF / TARGET-REQUIRED-OPERATION-REF
        oref = _find_deep(el, "OPERATION-IREF")
        if oref is not None:
            pref = _child(oref, "CONTEXT-R-PORT-REF")
            if pref is None:
                pref = _find_deep(oref, "CONTEXT-R-PORT-REF")
            top = _child(oref, "TARGET-REQUIRED-OPERATION-REF")
            if top is None:
                top = _find_deep(oref, "TARGET-REQUIRED-OPERATION-REF")
            port_ref = _text(pref)
            op_ref = _text(top)
        return PortAccess(
            access_kind="SERVER-CALL",
            name=name,
            path=path,
            runnable_path=runnable_path,
            port_ref=port_ref,
            operation_ref=op_ref,
        )

    def _parse_rte_event(self, el, tag: str, behavior_path: str, owner_swc: str) -> RteEvent:
        name = _sn(el)
        path = _path_of(el) or (f"{behavior_path}/{name}" if name else f"{behavior_path}/{tag}")
        kind_map = {
            "TIMING-EVENT": "TIMING",
            "INIT-EVENT": "INIT",
            "DATA-RECEIVED-EVENT": "DATA-RECEIVED",
            "OPERATION-INVOKED-EVENT": "OPERATION-INVOKED",
            "BACKGROUND-EVENT": "BACKGROUND",
            "MODE-SWITCH-EVENT": "MODE-SWITCH",
        }
        kind = kind_map.get(tag, tag.replace("-EVENT", "") or "OTHER")
        start = _text(_child(el, "START-ON-EVENT-REF"))
        period = _text(_child(el, "PERIOD"))
        offset = _text(_child(el, "OFFSET"))
        return RteEvent(
            name=name,
            path=path,
            kind=kind,
            behavior_path=behavior_path,
            owner_swc=owner_swc,
            start_on_runnable_ref=start,
            period=period,
            offset=offset,
        )

    def _parse_connectors(self, root, model: ArxmlModel, counts: Optional[dict] = None):
        total = 0
        if counts:
            total = counts.get("ASSEMBLY-SW-CONNECTOR", 0) + counts.get(
                "DELEGATION-SW-CONNECTOR", 0
            )
        done = 0
        report_every = max(100, total // 20) if total else 500
        for el in root.iter():
            tag = _local(el.tag)
            if tag == "ASSEMBLY-SW-CONNECTOR":
                self._parse_assembly(el, model)
                done += 1
            elif tag == "DELEGATION-SW-CONNECTOR":
                self._parse_delegation(el, model)
                done += 1
            else:
                continue
            if total and done % report_every == 0:
                self.progress(f"Connectors… {done}/{total}")
            elif not total and done % report_every == 0:
                self.progress(f"Connectors… {done}")

    def _owner_composition_path(self, connector_el) -> str:
        """Walk up to COMPOSITION-SW-COMPONENT-TYPE path."""
        cur = connector_el.getparent()
        while cur is not None:
            if _local(cur.tag) == "COMPOSITION-SW-COMPONENT-TYPE":
                return _path_of(cur)
            cur = cur.getparent()
        return ""

    def _parse_assembly(self, el, model: ArxmlModel):
        name = _sn(el)
        comp_path = self._owner_composition_path(el)
        path = f"{comp_path}/Connectors/{name}" if comp_path and name else _path_of(el)

        prov = _child(el, "PROVIDER-IREF")
        req = _child(el, "REQUESTER-IREF")
        a = AssemblyConnector(
            name=name,
            path=path,
            composition_path=comp_path,
            provider_proto_ref=_text(_child(prov, "CONTEXT-COMPONENT-REF")) if prov is not None else "",
            provider_port_ref=_text(_child(prov, "TARGET-P-PORT-REF")) if prov is not None else "",
            requester_proto_ref=_text(_child(req, "CONTEXT-COMPONENT-REF")) if req is not None else "",
            requester_port_ref=_text(_child(req, "TARGET-R-PORT-REF")) if req is not None else "",
        )
        model.assemblies.append(a)
        if comp_path and comp_path in model.swc_types:
            model.swc_types[comp_path].assemblies.append(a)

    def _parse_delegation(self, el, model: ArxmlModel):
        name = _sn(el)
        comp_path = self._owner_composition_path(el)
        path = f"{comp_path}/Connectors/{name}" if comp_path and name else _path_of(el)

        outer = _child(el, "OUTER-PORT-REF")
        inner = _child(el, "INNER-PORT-IREF")
        inner_proto = ""
        inner_port = ""
        inner_dir = ""
        if inner is not None:
            p_ref = _find_deep(inner, "P-PORT-IN-COMPOSITION-INSTANCE-REF")
            r_ref = _find_deep(inner, "R-PORT-IN-COMPOSITION-INSTANCE-REF")
            iref = p_ref if p_ref is not None else r_ref
            if iref is not None:
                inner_dir = "P" if p_ref is not None else "R"
                inner_proto = _text(_child(iref, "CONTEXT-COMPONENT-REF"))
                port_tag = "TARGET-P-PORT-REF" if inner_dir == "P" else "TARGET-R-PORT-REF"
                inner_port = _text(_child(iref, port_tag))

        d = DelegationConnector(
            name=name,
            path=path,
            composition_path=comp_path,
            outer_port_ref=_text(outer),
            inner_proto_ref=inner_proto,
            inner_port_ref=inner_port,
            inner_direction=inner_dir,
        )
        model.delegations.append(d)
        if comp_path and comp_path in model.swc_types:
            model.swc_types[comp_path].delegations.append(d)

    def _finalize(self, model: ArxmlModel):
        for a in model.assemblies:
            model.assemblies_by_comp.setdefault(a.composition_path, []).append(a)
        for d in model.delegations:
            model.delegations_by_comp.setdefault(d.composition_path, []).append(d)

        used_as_type: set = set()
        for proto in model.prototypes.values():
            if proto.type_ref:
                used_as_type.add(proto.type_ref)

        roots = []
        for path, swc in model.swc_types.items():
            if swc.kind == "COMPOSITION" and path not in used_as_type:
                roots.append(path)
        # also include compositions that look like TopLevel even if referenced oddly
        if not roots:
            roots = [p for p, t in model.swc_types.items() if t.kind == "COMPOSITION"]
        model.root_compositions = sorted(roots)
        model.build_indexes()
