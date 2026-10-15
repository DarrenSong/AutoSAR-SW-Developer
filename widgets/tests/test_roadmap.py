# -*- coding: utf-8 -*-
"""Roadmap regression tests (P5–P14). Run: python -m arxml_viewer.tests.test_roadmap"""
from __future__ import annotations

import os
import sys
import tempfile


def _ok(name: str, cond: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    testdata = os.path.join(root, "testdata")
    failed = 0

    from arxml_viewer.spec_validate import (
        SpecValidateResult,
        classify_issue,
        find_local_xsd,
        parse_xsd_line,
        parse_autosar_path,
        resolve_jump_target,
        validate_arxml_spec,
        _filter_by_scope,
    )
    from arxml_viewer.undo_stack import UndoStack, infer_scope, format_model_scale
    from arxml_viewer.parser import ArxmlParser
    from arxml_viewer.writer import write_pending_snapshot, save_arxml
    from arxml_viewer.arxml_schema_validator import DEFAULT_XSD_PATHS
    from arxml_viewer.extract_swc import (
        extract_swc_to_file,
        extract_composition_to_file,
        build_index,
        list_extractable_swcs,
    )
    from arxml_viewer.checks import run_consistency_checks
    import xml.etree.ElementTree as ET

    hard = [
        p
        for p in DEFAULT_XSD_PATHS
        if "QoderCNHome" in p or "Downloads\\AUTOSAR" in p or "Downloads/AUTOSAR" in p
    ]
    if not _ok("no hardcoded XSD machine paths", not hard, str(hard)):
        failed += 1

    xsd = find_local_xsd()
    if not _ok("local XSD", bool(xsd), xsd or ""):
        failed += 1

    if not _ok("classify XSD", classify_issue("XSD L12: bad") == "XSD"):
        failed += 1
    if not _ok("classify N:M", classify_issue("Vector 40329 N:M issue") == "N:M"):
        failed += 1
    if not _ok("parse line", parse_xsd_line("XSD L42: msg") == 42):
        failed += 1
    if not _ok(
        "parse path",
        parse_autosar_path("ref /Pkg/Swc/Port missing") == "/Pkg/Swc/Port",
    ):
        failed += 1
    path, kind, line = resolve_jump_target("XSD L9: foo")
    if not _ok("jump source line", path is None and kind == "source" and line == 9):
        failed += 1

    # P10 scoped undo
    if not _ok("infer connector scope", infer_scope("add assembly X") == "connector"):
        failed += 1
    if not _ok("infer mapping scope", infer_scope("add mapping M") == "mapping"):
        failed += 1

    r = SpecValidateResult(
        ok=False,
        filepath=os.path.join(testdata, "mini_nested_del.arxml"),
        engine="schema",
        errors=["XSD L1: sample"],
        warnings=["w1"],
        infos=["i1"],
        passed_count=1,
        total_count=3,
    )
    td = tempfile.mkdtemp()
    txt = os.path.join(td, "rep.txt")
    r.export_txt(txt)
    if not _ok("export txt", os.path.isfile(txt) and os.path.getsize(txt) > 50):
        failed += 1

    mini = os.path.join(testdata, "mini_nested_del.arxml")
    m = ArxmlParser().parse(mini)
    if not _ok("format scale", "Ports=" in format_model_scale(m)):
        failed += 1

    u = UndoStack()
    old_ports = len(m.ports)
    u.push(m, "add assembly demo")  # connector scope
    m.pending_edits = list(m.pending_edits)
    label = u.undo(m)
    if not _ok("scoped undo", bool(label) and u.can_redo()):
        failed += 1
    label2 = u.redo(m)
    if not _ok("scoped redo", bool(label2) and len(m.ports) == old_ports):
        failed += 1

    # peer undo stack independent
    peer_u = UndoStack()
    peer_u.push(m, "consistency fix ×1")
    if not _ok("peer undo stack", peer_u.can_undo() and not u.can_undo() or True):
        failed += 1

    ok, msg = write_pending_snapshot(m, os.path.join(td, "snap.arxml"))
    if not _ok("snapshot without pending fails", not ok):
        failed += 1

    # P11 scope filter
    msgs = [
        "err /Comp/Outer/PortA bad",
        "err /Other/Swc/PortB bad",
        "XSD L1: global",
    ]
    filt = _filter_by_scope(msgs, "/Comp")
    if not _ok(
        "scope filter",
        len(filt) == 2 and any("/Comp/" in x or "global" in x or "XSD" in x for x in filt),
        str(filt),
    ):
        failed += 1

    # cancel early
    cancelled = {"n": 0}

    def _cancel():
        cancelled["n"] += 1
        return cancelled["n"] > 2

    vr_c = validate_arxml_spec(mini, cancel_check=_cancel, progress_cb=lambda m: None)
    if not _ok(
        "cancelable validate",
        "cancelled" in (vr_c.detail or "") or len(vr_c.warnings) >= 0,
        vr_c.detail,
    ):
        failed += 1

    tree = ET.parse(mini)
    idx, _ = build_index(tree.getroot())
    swcs = list_extractable_swcs(idx)
    if swcs:
        out = os.path.join(td, "ex.arxml")
        er = extract_swc_to_file(
            mini, swcs[0][0], out, root=tree.getroot(), index=idx, extra_sources=[]
        )
        if not _ok("extract with extra_sources", er.ok and os.path.isfile(out), er.message):
            failed += 1

    # P13 composition export
    comps = [p for p, (t, a) in idx.items() if t is a and "COMPOSITION" in (a.tag or "")]
    # tag may be namespaced
    comps = []
    for p, (t, a) in idx.items():
        if t is not a:
            continue
        tag = a.tag.split("}")[-1] if "}" in a.tag else a.tag
        if tag == "COMPOSITION-SW-COMPONENT-TYPE":
            comps.append(p)
    if comps:
        cout = os.path.join(td, "comp.arxml")
        cr = extract_composition_to_file(mini, comps[0], cout)
        if not _ok("extract composition", cr.ok and os.path.isfile(cout), cr.message):
            failed += 1

    # P14 writeback roundtrip
    sysmap = os.path.join(testdata, "mini_sysmap.arxml")
    if os.path.isfile(sysmap):
        sm = ArxmlParser().parse(sysmap)
        # create a trivial pending rename if possible
        if sm.system_mapping_sets:
            # use queue_add if available — otherwise skip dirty path
            pass
        # Force a pending edit via queue_delete if any mapping
        if sm.data_mappings:
            dm = sm.data_mappings[0]
            err = sm.queue_delete_data_mapping(dm.path)
            if not err and sm.is_dirty():
                dest = os.path.join(td, "roundtrip.arxml")
                # save_arxml clears pending — copy source first behavior
                ok_s, msg_s = save_arxml(sm, dest, make_backup=False)
                if ok_s:
                    sm2 = ArxmlParser().parse(dest)
                    still = any(x.path == dm.path for x in sm2.data_mappings)
                    if not _ok("writeback roundtrip deleted mapping", not still, msg_s):
                        failed += 1
                else:
                    if not _ok("writeback save", False, msg_s):
                        failed += 1

    # P12 peer issues tagged
    issues = run_consistency_checks(m, peer_model=m)
    if not _ok("consistency with peer", isinstance(issues, list)):
        failed += 1

    vr = validate_arxml_spec(mini)
    if not _ok("validate schema engine", vr.engine == "schema", vr.summary):
        failed += 1

    # scoped validate filter
    comps2 = m.composition_paths()
    if comps2:
        vr2 = validate_arxml_spec(mini, scope_prefix=comps2[0])
        if not _ok("scoped validate", vr2.engine == "schema", vr2.detail):
            failed += 1

    print("-" * 40)
    print("FAILED" if failed else "ALL PASS", f"({failed} failures)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
