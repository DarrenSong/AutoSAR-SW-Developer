# -*- coding: utf-8 -*-
"""
Extract one Application SWC (and transitive dependencies) into a standalone ARXML.

Based on D:\\QoderCNHome\\arxml_tool_gui\\extract_swc.py:
  SWC + PortInterface / ADT / IDT / CompuMethod / DataConstr / BaseType /
  Unit / Constant / DataTypeMappingSet, etc. via REF closure.
"""
from __future__ import annotations

import copy
import os
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

NS = "http://autosar.org/schema/r4.0"

ET.register_namespace("", NS)
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

SWC_TAGS = {
    "APPLICATION-SW-COMPONENT-TYPE",
    "SENSOR-ACTUATOR-SW-COMPONENT-TYPE",
    "SERVICE-SW-COMPONENT-TYPE",
    "ECU-ABSTRACTION-SW-COMPONENT-TYPE",
    "COMPLEX-DEVICE-DRIVER-SW-COMPONENT-TYPE",
    "PARAMETER-SW-COMPONENT-TYPE",
}


def _sn(elem) -> Optional[str]:
    e = elem.find(f"{{{NS}}}SHORT-NAME")
    return e.text if e is not None else None


def _local(elem) -> str:
    t = elem.tag
    return t.split("}", 1)[-1] if "}" in t else t


def _iter_refs(elem) -> List[str]:
    refs = []
    for e in elem.iter():
        tag = _local(e)
        if (tag.endswith("-REF") or tag.endswith("-TREF")) and e.text and e.text.startswith("/"):
            refs.append(e.text.strip())
    return refs


def _index_child_named(index: dict, pkg_map: dict, parent_path: str, pkg_name: str, parent_elem, child):
    cname = _sn(child)
    if not cname:
        return
    cpath = f"{parent_path}/{cname}"
    index[cpath] = (child, parent_elem)
    pkg_map[cpath] = pkg_name


def build_index(root) -> Tuple[dict, dict]:
    """
    Build AUTOSAR absolute path → (target_elem, top_level_elem_to_copy).
    Walks nested AR-PACKAGES.
    """
    index: dict = {}
    pkg_map: dict = {}

    def walk_packages(packages_el, path_prefix: str):
        if packages_el is None:
            return
        for pkg in packages_el:
            if _local(pkg) != "AR-PACKAGE":
                continue
            pkg_name = _sn(pkg)
            if not pkg_name:
                continue
            pkg_path = f"{path_prefix}/{pkg_name}" if path_prefix else f"/{pkg_name}"
            # top segment used when rebuilding flat packages in output
            top_pkg = pkg_path.strip("/").split("/", 1)[0]

            elems_container = pkg.find(f"{{{NS}}}ELEMENTS")
            if elems_container is not None:
                for elem in elems_container:
                    name = _sn(elem)
                    if not name:
                        continue
                    path = f"{pkg_path}/{name}"
                    index[path] = (elem, elem)
                    pkg_map[path] = top_pkg

                    for container_tag in (
                        "ELEMENTS",
                        "DATA-ELEMENTS",
                        "PORTS",
                        "OPERATIONS",
                        "ARGUMENTS",
                        "POSSIBLE-ERRORS",
                        "MODE-DECLARATION-GROUPS",
                        "MODE-DECLARATIONS",
                        "TRIGGERS",
                        "NV-DATAS",
                        "PARAMETERS",
                    ):
                        sub = elem.find(f"{{{NS}}}{container_tag}")
                        if sub is None:
                            continue
                        for child in sub:
                            _index_child_named(index, pkg_map, path, top_pkg, elem, child)

                    if _local(elem) == "APPLICATION-ARRAY-DATA-TYPE":
                        array_elem = elem.find(f"{{{NS}}}ELEMENT")
                        if array_elem is not None:
                            _index_child_named(index, pkg_map, path, top_pkg, elem, array_elem)

                    # CLIENT-SERVER-OPERATION / ARGUMENTS nested under OPERATIONS
                    ops = elem.find(f"{{{NS}}}OPERATIONS")
                    if ops is not None:
                        for op in ops:
                            op_name = _sn(op)
                            if not op_name:
                                continue
                            op_path = f"{path}/{op_name}"
                            args = op.find(f"{{{NS}}}ARGUMENTS")
                            if args is None:
                                continue
                            for arg in args:
                                _index_child_named(
                                    index, pkg_map, op_path, top_pkg, elem, arg
                                )

            # nested packages
            nested = pkg.find(f"{{{NS}}}AR-PACKAGES")
            if nested is not None:
                walk_packages(nested, pkg_path)

    # root may be AUTOSAR
    top = root.find(f"{{{NS}}}AR-PACKAGES")
    if top is None:
        # sometimes already AR-PACKAGES
        if _local(root) == "AR-PACKAGES":
            top = root
        else:
            for c in root:
                if _local(c) == "AR-PACKAGES":
                    top = c
                    break
    walk_packages(top, "")
    return index, pkg_map


def _top_path_of(index: dict, add_elem) -> Optional[str]:
    for p, (t, a) in index.items():
        if a is add_elem and t is add_elem:
            return p
    return None


def collect_deps(swc_elem, index: dict, swc_full_path: str) -> Set[str]:
    """REF closure; track scanned top elements by id to avoid cycles."""
    added: Set[str] = set()
    scanned_ids: Set[int] = set()
    to_scan: List = []

    if swc_full_path:
        added.add(swc_full_path)
    to_scan.append(swc_elem)
    scanned_ids.add(id(swc_elem))

    while to_scan:
        elem = to_scan.pop(0)
        for ref_path in _iter_refs(elem):
            if ref_path in added:
                continue
            if ref_path in index:
                _target, add_elem = index[ref_path]
                top_path = _top_path_of(index, add_elem)
                if top_path:
                    added.add(top_path)
                added.add(ref_path)
                if id(add_elem) not in scanned_ids:
                    scanned_ids.add(id(add_elem))
                    to_scan.append(add_elem)
            elif swc_full_path and ref_path.startswith(swc_full_path + "/"):
                added.add(ref_path)

    return added


def _pkg_for_path(path: str) -> Optional[str]:
    parts = path.strip("/").split("/")
    return parts[0] if parts else None


def build_output(root, paths: Iterable[str], index: dict):
    new_root = ET.Element(root.tag)
    for k, v in root.attrib.items():
        new_root.set(k, v)

    ar_packages = ET.SubElement(new_root, f"{{{NS}}}AR-PACKAGES")
    by_pkg: Dict[str, set] = defaultdict(set)
    for path in paths:
        pkg_name = _pkg_for_path(path)
        if pkg_name:
            by_pkg[pkg_name].add(path)

    for pkg_name in sorted(by_pkg.keys()):
        pkg = ET.SubElement(ar_packages, f"{{{NS}}}AR-PACKAGE")
        pkg_sn = ET.SubElement(pkg, f"{{{NS}}}SHORT-NAME")
        pkg_sn.text = pkg_name
        elems_container = ET.SubElement(pkg, f"{{{NS}}}ELEMENTS")
        added_top: Set[int] = set()
        for path in sorted(by_pkg[pkg_name]):
            if path not in index:
                continue
            _target, add_elem = index[path]
            tid = id(add_elem)
            if tid in added_top:
                continue
            # only emit top-level ELEMENTS members (target == add_elem)
            if _target is not add_elem:
                # child path — ensure parent top elem is included via its top path
                continue
            added_top.add(tid)
            elems_container.append(copy.deepcopy(add_elem))

    return new_root


@dataclass
class ExtractResult:
    ok: bool
    swc_path: str = ""
    swc_name: str = ""
    output_path: str = ""
    dep_count: int = 0
    element_count: int = 0
    message: str = ""
    missing_refs: List[str] = field(default_factory=list)
    missing_report_path: str = ""
    validate_summary: str = ""


def list_extractable_swcs(index: dict) -> List[Tuple[str, str, object]]:
    """Return [(path, name, elem), ...] for atomic SWC types."""
    out = []
    for path, (target, add_elem) in index.items():
        if target is not add_elem:
            continue
        if _local(add_elem) in SWC_TAGS:
            out.append((path, _sn(add_elem) or path.rsplit("/", 1)[-1], add_elem))
    out.sort(key=lambda x: x[1].lower())
    return out


def _merge_extra_indexes(index: dict, extra_sources: Optional[List[str]]) -> int:
    """Merge peer/extra ARXML indexes so REF closure can pull cross-file deps."""
    added = 0
    for ep in extra_sources or []:
        if not ep or not os.path.isfile(ep):
            continue
        try:
            eroot = ET.parse(ep).getroot()
            eindex, _ = build_index(eroot)
        except Exception:
            continue
        for k, v in eindex.items():
            if k not in index:
                index[k] = v
                added += 1
    return added


def extract_swc_to_file(
    source_arxml: str,
    swc_path: str,
    dest_path: str,
    *,
    root=None,
    index: Optional[dict] = None,
    write_missing_report: bool = True,
    validate_export: bool = False,
    extra_sources: Optional[List[str]] = None,
) -> ExtractResult:
    """
    Extract one SWC by absolute path (e.g. /SwComponentType/FooSwc) to dest_path.

    extra_sources: optional peer ARXML paths whose elements may satisfy REFs.
    """
    if not source_arxml or not os.path.isfile(source_arxml):
        return ExtractResult(False, message=f"源文件不存在: {source_arxml}")
    if root is None or index is None:
        try:
            tree = ET.parse(source_arxml)
            root = tree.getroot()
            index, _ = build_index(root)
        except Exception as e:
            return ExtractResult(False, message=f"解析失败: {e}")
    else:
        # Caller-provided index: copy so peer merge does not mutate shared state
        index = dict(index)

    _merge_extra_indexes(index, extra_sources)

    entry = index.get(swc_path)
    if not entry:
        # try by short name among SWCs
        matches = [p for p, n, _ in list_extractable_swcs(index) if n == swc_path or p.endswith("/" + swc_path)]
        if len(matches) == 1:
            swc_path = matches[0]
            entry = index.get(swc_path)
        else:
            return ExtractResult(
                False,
                swc_path=swc_path,
                message=f"未找到 SWC 路径: {swc_path}",
            )

    target, add_elem = entry
    swc_elem = add_elem if _local(add_elem) in SWC_TAGS else target
    if _local(swc_elem) not in SWC_TAGS:
        return ExtractResult(
            False,
            swc_path=swc_path,
            message=f"不是可导出的 SWC 类型: {_local(swc_elem)}",
        )

    # Prefer top-level path
    top_path = swc_path
    for p, (t, a) in index.items():
        if a is swc_elem and t is swc_elem:
            top_path = p
            break

    paths = collect_deps(swc_elem, index, top_path)
    missing = []
    for ref in _iter_refs(swc_elem):
        if ref not in index and not ref.startswith(top_path + "/"):
            # only report if never resolved via any dep (cheap check)
            pass

    # recount unresolved across closure
    seen_elems = set()
    for p in list(paths):
        if p not in index:
            continue
        _t, ae = index[p]
        if id(ae) in seen_elems:
            continue
        seen_elems.add(id(ae))
        for ref in _iter_refs(ae):
            if ref in index:
                continue
            if ref.startswith(top_path + "/"):
                continue
            if ref not in missing:
                missing.append(ref)

    out_root = build_output(root, paths, index)
    # count top elements
    n_el = 0
    for pkg in out_root.findall(f"{{{NS}}}AR-PACKAGES/{{{NS}}}AR-PACKAGE"):
        el = pkg.find(f"{{{NS}}}ELEMENTS")
        if el is not None:
            n_el += len(list(el))

    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
        ET.indent(out_root, space="  ")
        ET.ElementTree(out_root).write(
            dest_path, xml_declaration=True, encoding="UTF-8"
        )
    except Exception as e:
        return ExtractResult(False, swc_path=top_path, message=f"写入失败: {e}")

    name = _sn(swc_elem) or top_path.rsplit("/", 1)[-1]
    missing_report = ""
    if write_missing_report and missing:
        missing_report = dest_path + ".missing_refs.txt"
        try:
            with open(missing_report, "w", encoding="utf-8") as f:
                f.write(f"# Unresolved REFs for {name} ({top_path})\n")
                f.write(f"# source={source_arxml}\n")
                for ref in missing:
                    f.write(ref + "\n")
        except OSError:
            missing_report = ""

    validate_summary = ""
    if validate_export:
        try:
            from .spec_validate import validate_arxml_spec

            vr = validate_arxml_spec(dest_path)
            validate_summary = vr.summary
        except Exception as e:
            validate_summary = f"validate failed: {e}"

    msg = f"已导出 {name}: {n_el} 个顶层元素（含 {max(0, n_el - 1)} 个依赖）"
    if missing:
        msg += f"；未解析引用 {len(missing)} 个"
    if validate_summary:
        msg += f"；{validate_summary}"

    return ExtractResult(
        ok=True,
        swc_path=top_path,
        swc_name=name,
        output_path=dest_path,
        dep_count=max(0, n_el - 1),
        element_count=n_el,
        message=msg,
        missing_refs=missing[:80],
        missing_report_path=missing_report,
        validate_summary=validate_summary,
    )


def extract_all_swcs(
    source_arxml: str,
    output_dir: str,
    *,
    swc_paths: Optional[List[str]] = None,
    validate_export: bool = False,
    extra_sources: Optional[List[str]] = None,
) -> Tuple[List[ExtractResult], str]:
    """Extract many SWCs into output_dir/<Name>.arxml."""
    if not os.path.isfile(source_arxml):
        return [], f"源文件不存在: {source_arxml}"
    try:
        tree = ET.parse(source_arxml)
        root = tree.getroot()
        index, _ = build_index(root)
    except Exception as e:
        return [], f"解析失败: {e}"

    _merge_extra_indexes(index, extra_sources)

    os.makedirs(output_dir, exist_ok=True)
    if swc_paths:
        targets = []
        for p in swc_paths:
            if p in index:
                targets.append((p, _sn(index[p][1]) or p.rsplit("/", 1)[-1], index[p][1]))
            else:
                targets.append((p, p, None))
    else:
        targets = list_extractable_swcs(index)

    results: List[ExtractResult] = []
    for path, name, elem in targets:
        if elem is None:
            results.append(ExtractResult(False, swc_path=path, message=f"未找到: {path}"))
            continue
        dest = os.path.join(output_dir, f"{name}.arxml")
        results.append(
            extract_swc_to_file(
                source_arxml,
                path,
                dest,
                root=root,
                index=index,
                validate_export=validate_export,
                extra_sources=extra_sources,
            )
        )
    return results, ""


def extract_by_path_closure(
    source_arxml: str,
    top_path: str,
    dest_path: str,
    *,
    allowed_tags: Optional[Set[str]] = None,
    extra_sources: Optional[List[str]] = None,
    validate_export: bool = False,
) -> ExtractResult:
    """
    Generic REF-closure extract for Composition / SYSTEM / Mapping sets.
    allowed_tags: if set, top element local-name must be in this set.
    """
    if not source_arxml or not os.path.isfile(source_arxml):
        return ExtractResult(False, message=f"源文件不存在: {source_arxml}")
    try:
        tree = ET.parse(source_arxml)
        root = tree.getroot()
        index, _ = build_index(root)
    except Exception as e:
        return ExtractResult(False, message=f"解析失败: {e}")

    _merge_extra_indexes(index, extra_sources)
    entry = index.get(top_path)
    if not entry:
        return ExtractResult(False, swc_path=top_path, message=f"未找到路径: {top_path}")
    named, add_elem = entry
    # For top-level ELEMENTS members, named is add_elem; for children named differs
    scan_elem = add_elem if named is add_elem else named
    tag = _local(named)
    if allowed_tags and tag not in allowed_tags:
        return ExtractResult(
            False,
            swc_path=top_path,
            message=f"类型不符: {tag}（期望 {sorted(allowed_tags)}）",
        )

    # Prefer top-level path for package emission
    for p, (t, a) in index.items():
        if a is add_elem and t is add_elem:
            top_path = p
            named = t
            scan_elem = a
            break

    paths = collect_deps(scan_elem, index, top_path)
    missing = []
    seen_elems = set()
    for p in list(paths):
        if p not in index:
            continue
        _t, ae = index[p]
        if id(ae) in seen_elems:
            continue
        seen_elems.add(id(ae))
        for ref in _iter_refs(ae):
            if ref in index or ref.startswith(top_path + "/"):
                continue
            if ref not in missing:
                missing.append(ref)

    out_root = build_output(root, paths, index)
    n_el = 0
    for pkg in out_root.findall(f"{{{NS}}}AR-PACKAGES/{{{NS}}}AR-PACKAGE"):
        el = pkg.find(f"{{{NS}}}ELEMENTS")
        if el is not None:
            n_el += len(list(el))

    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
        ET.indent(out_root, space="  ")
        ET.ElementTree(out_root).write(
            dest_path, xml_declaration=True, encoding="UTF-8"
        )
    except Exception as e:
        return ExtractResult(False, swc_path=top_path, message=f"写入失败: {e}")

    name = _sn(named) or top_path.rsplit("/", 1)[-1]
    validate_summary = ""
    if validate_export:
        try:
            from .spec_validate import validate_arxml_spec

            vr = validate_arxml_spec(dest_path)
            validate_summary = vr.summary
        except Exception as e:
            validate_summary = f"validate failed: {e}"

    msg = f"已导出 {name} ({tag}): {n_el} 个顶层元素"
    if missing:
        msg += f"；未解析引用 {len(missing)} 个"
    if validate_summary:
        msg += f"；{validate_summary}"
    return ExtractResult(
        ok=True,
        swc_path=top_path,
        swc_name=name,
        output_path=dest_path,
        dep_count=max(0, n_el - 1),
        element_count=n_el,
        message=msg,
        missing_refs=missing[:80],
        validate_summary=validate_summary,
    )


def extract_composition_to_file(
    source_arxml: str,
    composition_path: str,
    dest_path: str,
    *,
    extra_sources: Optional[List[str]] = None,
    validate_export: bool = False,
) -> ExtractResult:
    """Export a COMPOSITION-SW-COMPONENT-TYPE with REF closure (incl. nested SWCs)."""
    return extract_by_path_closure(
        source_arxml,
        composition_path,
        dest_path,
        allowed_tags={"COMPOSITION-SW-COMPONENT-TYPE"},
        extra_sources=extra_sources,
        validate_export=validate_export,
    )


def extract_system_slice_to_file(
    source_arxml: str,
    system_or_mapping_path: str,
    dest_path: str,
    *,
    extra_sources: Optional[List[str]] = None,
    validate_export: bool = False,
) -> ExtractResult:
    """Export SYSTEM or SYSTEM-MAPPING (+ closure) as a slice ARXML."""
    return extract_by_path_closure(
        source_arxml,
        system_or_mapping_path,
        dest_path,
        allowed_tags={"SYSTEM", "SYSTEM-MAPPING"},
        extra_sources=extra_sources,
        validate_export=validate_export,
    )


def list_system_slice_paths(index: dict) -> List[Tuple[str, str, str]]:
    """Return [(path, name, tag), ...] for SYSTEM / SYSTEM-MAPPING tops."""
    out = []
    for path, (target, add_elem) in index.items():
        if target is not add_elem:
            continue
        tag = _local(add_elem)
        if tag in ("SYSTEM", "SYSTEM-MAPPING"):
            out.append((path, _sn(add_elem) or path.rsplit("/", 1)[-1], tag))
    out.sort(key=lambda x: (x[2], x[1].lower()))
    return out

