# -*- coding: utf-8 -*-
"""Minimal RTE C skeleton from OsRte overlay + IB (not full COM/DaVinci)."""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

from .model import ArxmlModel
from .os_rte import OsRteOverlay


def generate_rte_skeleton(
    model: ArxmlModel,
    overlay: OsRteOverlay,
    out_dir: str,
    *,
    module_prefix: str = "Rte",
) -> Tuple[List[str], str]:
    """
    Write Rte_<Task>.c / Rte_Tasks.h stubs that call runnable symbols in mapping order.

    Returns (written_paths, error). Empty error means success.
    """
    if not model:
        return [], "无模型"
    if not overlay or not overlay.tasks:
        return [], "侧车无 OS Task，请先配置 Tools → OS/RTE Mapping"
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as e:
        return [], f"无法创建目录: {e}"

    written: List[str] = []
    task_decls: List[str] = []
    for task in overlay.tasks:
        maps = overlay.mappings_by_task(task.name)
        maps = sorted(maps, key=lambda m: (m.position, m.runnable))
        c_name = f"{module_prefix}_{_safe_ident(task.name)}.c"
        c_path = os.path.join(out_dir, c_name)
        lines = [
            f"/* Generated skeleton — NOT a full Vector/DaVinci RTE */",
            f"/* ECU={overlay.ecu}  Task={task.name}  prio={task.priority} */",
            f'#include "{module_prefix}_Tasks.h"',
            "",
        ]
        # extern decls for symbols
        seen_sym = set()
        calls: List[str] = []
        for m in maps:
            r = model.runnables.get(m.runnable)
            sym = (r.symbol if r and r.symbol else "") or (
                r.name if r else m.runnable.rsplit("/", 1)[-1]
            )
            sym = _safe_ident(sym)
            proto_n = model.resolve_name(m.swc_prototype)
            run_n = model.resolve_name(m.runnable)
            if sym not in seen_sym:
                lines.append(f"extern void {sym}(void);  /* {proto_n}.{run_n} */")
                seen_sym.add(sym)
            calls.append(f"    {sym}();  /* pos={m.position} {proto_n}.{run_n} */")
        if not maps:
            lines.append("/* (no runnable mappings for this task) */")
        lines.append("")
        fn = f"{module_prefix}_Task_{_safe_ident(task.name)}"
        task_decls.append(f"void {fn}(void);")
        lines.append(f"void {fn}(void)")
        lines.append("{")
        if calls:
            lines.extend(calls)
        else:
            lines.append("    /* empty */")
        lines.append("}")
        lines.append("")
        try:
            with open(c_path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines))
            written.append(c_path)
        except OSError as e:
            return written, f"写 {c_name} 失败: {e}"

    h_path = os.path.join(out_dir, f"{module_prefix}_Tasks.h")
    h_lines = [
        f"#ifndef {_safe_ident(module_prefix).upper()}_TASKS_H",
        f"#define {_safe_ident(module_prefix).upper()}_TASKS_H",
        "",
        "/* Generated skeleton — map these into OsTask bodies / ScheduleTables */",
        f"/* source overlay: {overlay.source_path or '(unsaved)'} */",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        *task_decls,
        "",
        "#ifdef __cplusplus",
        "}",
        "#endif",
        "",
        f"#endif /* {_safe_ident(module_prefix).upper()}_TASKS_H */",
        "",
    ]
    try:
        with open(h_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(h_lines))
        written.append(h_path)
    except OSError as e:
        return written, f"写头文件失败: {e}"

    readme = os.path.join(out_dir, "README_RTE_SKELETON.txt")
    try:
        with open(readme, "w", encoding="utf-8", newline="\n") as f:
            f.write(
                "Minimal RTE skeleton from arxml_viewer OsRTE overlay.\n"
                "NOT a substitute for DaVinci/Vector RTE or COM stack.\n"
                "Wire each Rte_Task_* into the corresponding OsTask entry function.\n"
            )
        written.append(readme)
    except OSError:
        pass
    return written, ""


def _safe_ident(name: str) -> str:
    out = []
    for ch in name or "X":
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out)
    if s and s[0].isdigit():
        s = "T_" + s
    return s or "X"
