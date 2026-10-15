# -*- coding: utf-8 -*-
"""Regression smoke for arxml_viewer (run: python -m arxml_viewer.smoke_test)."""
from __future__ import annotations

import os
import sys
import tempfile


def _ok(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    testdata = os.path.join(root, "testdata")
    failed = 0

    from arxml_viewer.parser import ArxmlParser
    from arxml_viewer.extract_swc import extract_swc_to_file, build_index, list_extractable_swcs
    from arxml_viewer.checks import run_consistency_checks
    from arxml_viewer.spec_validate import find_local_xsd, validate_arxml_spec
    from arxml_viewer.graph_builder import build_sr_chain_graph
    from arxml_viewer.peer_chain import build_cross_file_chain
    from arxml_viewer.project_config import ProjectConfig, save_project_config, load_project_config
    from arxml_viewer.undo_stack import UndoStack

    # XSD pack present
    xsd = find_local_xsd()
    if not _ok("local XSD", bool(xsd and os.path.isfile(xsd)), xsd or ""):
        failed += 1

    mini = os.path.join(testdata, "mini_nested_del.arxml")
    m = ArxmlParser().parse(mini)
    if not _ok("parse mini_nested_del", bool(m.ports), f"ports={len(m.ports)}"):
        failed += 1

    apps = [p for p in m.ports.values() if m.swc_types.get(p.owner_path, type("x", (), {"kind": ""})()).kind == "APPLICATION"]
    if apps:
        chains = m.trace_sr_port(apps[0].path)
        g = build_sr_chain_graph(m, chains[0]) if chains else None
        if not _ok("chain graph", bool(g and g.edges), f"edges={len(g.edges) if g else 0}"):
            failed += 1

    issues = run_consistency_checks(m)
    if not _ok("consistency checks", isinstance(issues, list), f"n={len(issues)}"):
        failed += 1

    # extract
    td = tempfile.mkdtemp()
    import xml.etree.ElementTree as ET

    tree = ET.parse(mini)
    idx, _ = build_index(tree.getroot())
    swcs = list_extractable_swcs(idx)
    if swcs:
        out = os.path.join(td, swcs[0][1] + ".arxml")
        r = extract_swc_to_file(mini, swcs[0][0], out, root=tree.getroot(), index=idx)
        if not _ok("extract SWC", r.ok and os.path.isfile(out), r.message):
            failed += 1

    # validate (default schema includes N:M check)
    vr = validate_arxml_spec(mini)
    if not _ok("spec validate schema", vr.engine == "schema", vr.summary):
        failed += 1

    # project config
    cfg_path = save_project_config(mini, ProjectConfig(peer="", limit_ports=True))
    loaded = load_project_config(mini)
    if not _ok("project config", bool(loaded and loaded.limit_ports), str(cfg_path)):
        failed += 1
    try:
        os.remove(cfg_path)
    except OSError:
        pass

    # undo
    u = UndoStack()
    u.push(m, "t")
    if not _ok("undo stack", u.can_undo()):
        failed += 1

    # cross chain helper
    if apps:
        hops = build_cross_file_chain(m, apps[0].path, None)
        if not _ok("peer_chain helper", len(hops) >= 1, f"hops={len(hops)}"):
            failed += 1

    # CS fixture
    cs = os.path.join(testdata, "mini_cs.arxml")
    if os.path.isfile(cs):
        cm = ArxmlParser().parse(cs)
        if not _ok("parse mini_cs", bool(cm.cs_interfaces or cm.ports)):
            failed += 1

    # P0: lift + peer star lazy stubs
    from arxml_viewer.graph_builder import build_peer_star_graph

    if apps:
        lifted = m.lift_port_for_peer_view(apps[0].path)
        if not _ok("lift_port_for_peer_view", bool(lifted), lifted):
            failed += 1
        star = build_peer_star_graph(m, apps[0].path, max_full_peers=1)
        stubs = [
            n
            for n in star.nodes
            if (n.meta or {}).get("peer_star_expandable")
        ]
        if not _ok(
            "peer_star graph",
            bool(star.nodes),
            f"nodes={len(star.nodes)} stubs={len(stubs)}",
        ):
            failed += 1

    # P1: OsRTE CSV + RTE skeleton
    from arxml_viewer.os_rte import (
        OsRteOverlay,
        OsTask,
        RunnableToTaskMapping,
        export_os_rte_csv,
        import_os_rte_csv,
    )
    from arxml_viewer.rte_codegen import generate_rte_skeleton

    ov = OsRteOverlay(
        tasks=[OsTask(name="OsTask_10ms", priority=10)],
        mappings=[
            RunnableToTaskMapping(
                task="OsTask_10ms",
                swc_prototype="/Pkg/Proto",
                runnable="/Pkg/RE",
                position=0,
            )
        ],
    )
    ov.rebuild_indexes()
    csv_path = os.path.join(td, "os_rte.csv")
    err = export_os_rte_csv(csv_path, ov)
    ov2, msg = import_os_rte_csv(csv_path)
    if not _ok(
        "os_rte csv roundtrip",
        not err and ov2 is not None and len(ov2.tasks) == 1,
        msg or err or "",
    ):
        failed += 1
    rte_dir = os.path.join(td, "rte_out")
    written, gerr = generate_rte_skeleton(m, ov, rte_dir)
    if not _ok(
        "rte skeleton",
        not gerr and bool(written),
        gerr or f"files={len(written or [])}",
    ):
        failed += 1

    # P3: Find fuzzy + 1n helper
    from arxml_viewer.widgets.find_dialog import fuzzy_match, search_model

    if not _ok("fuzzy_match", fuzzy_match("bldr", "BackLiDrvrReq_P")):
        failed += 1
    hits_1n = search_model(m, "1n", limit=50)
    if not _ok("find 1n keyword", isinstance(hits_1n, list)):
        failed += 1

    # Empty CS / VALUE-SPEC streaming indexer (fix_empty_constants.py)
    empty_cs = os.path.join(testdata, "mini_empty_cs.arxml")
    if os.path.isfile(empty_cs):
        sys.path.insert(0, os.path.dirname(root))  # repo root for fix_empty_constants
        from fix_empty_constants import process as fix_cs_process, stream_index_input

        elines = open(empty_cs, encoding="utf-8").read().splitlines()
        eindex = stream_index_input(elines)
        if not _ok(
            "stream empty CS index",
            len(eindex.empties) == 2 and "Uint16" in eindex.adts,
            f"empties={len(eindex.empties)} adts={list(eindex.adts)}",
        ):
            failed += 1
        out_cs = os.path.join(td, "fixed_cs.arxml")
        donor_cs = os.path.join(testdata, "mini_empty_cs_donor.arxml")
        nfix = fix_cs_process(empty_cs, out_cs, [donor_cs] if os.path.isfile(donor_cs) else [])
        fixed_idx = stream_index_input(open(out_cs, encoding="utf-8").read().splitlines())
        if not _ok(
            "fix_empty_constants",
            nfix >= 2 and len(fixed_idx.empties) == 0,
            f"fixed={nfix} remain={len(fixed_idx.empties)}",
        ):
            failed += 1

    print("-" * 40)
    print("FAILED" if failed else "ALL PASS", f"({failed} failures)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
