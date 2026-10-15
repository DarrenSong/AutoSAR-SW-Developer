# -*- coding: utf-8 -*-
"""
File-level scans for export-platform defects (duplicates / UUID / empty CS / N:M).

Detection is streaming / package-local — does not use nested whole-file regex.
Repair is delegated to arxml_tool_gui scripts via external_fix.py.
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from .checks import CheckIssue
from .external_fix import resolve_scripts_dir

UUID_ATTR_RE = re.compile(r'(?<![\w-])UUID="([^"]+)"')
SN_RE = re.compile(r"<SHORT-NAME>([^<]+)</SHORT-NAME>")

TARGET_PACKAGES = {
    "PortInterfaces": ["SENDER-RECEIVER-INTERFACE"],
    "ImplementationDataTypes": ["IMPLEMENTATION-DATA-TYPE"],
    "ApplicationDataTypes": [
        "APPLICATION-DATA-TYPE",
        "APPLICATION-RECORD-DATA-TYPE",
        "APPLICATION-PRIMITIVE-DATA-TYPE",
        "APPLICATION-ARRAY-DATA-TYPE",
        "APPLICATION-MAP-DATA-TYPE",
    ],
    "DataConstrs": ["DATA-CONSTR"],
    "CompuMethods": ["COMPU-METHOD"],
    "ConstantSpecifications": ["CONSTANT-SPECIFICATION"],
}

# Friendly labels for UI
PKG_LABEL = {
    "ApplicationDataTypes": "ADT",
    "ImplementationDataTypes": "IDT",
    "PortInterfaces": "PortInterface",
    "DataConstrs": "DataConstr",
    "CompuMethods": "CompuMethod",
    "ConstantSpecifications": "Constant",
    "DataTypeMappingSets": "DataTypeMap",
}


def _find_package_range(lines: List[str], package_name: str) -> Optional[Tuple[int, int]]:
    for i, line in enumerate(lines):
        if "<AR-PACKAGE>" not in line and not re.search(r"<AR-PACKAGE[\s>]", line):
            continue
        for j in range(i, min(i + 5, len(lines))):
            if f"<SHORT-NAME>{package_name}</SHORT-NAME>" in lines[j]:
                depth = 0
                for k in range(i, len(lines)):
                    depth += lines[k].count("<AR-PACKAGE>") + len(
                        re.findall(r"<AR-PACKAGE[\s>]", lines[k])
                    )
                    depth -= lines[k].count("</AR-PACKAGE>")
                    if depth <= 0:
                        return i, k
    return None


def _short_name(lines: List[str], start: int, end: int) -> Optional[str]:
    for j in range(start, min(start + 8, end + 1)):
        m = SN_RE.search(lines[j])
        if m:
            return m.group(1)
    return None


def _find_child_elements(
    lines: List[str], pkg_start: int, pkg_end: int, tag_list: List[str]
) -> List[Tuple[str, int, int]]:
    """[(short_name, start, end), ...]"""
    elements: List[Tuple[str, int, int]] = []
    for tag in tag_list:
        open_re = re.compile(r"<%s(?:[\s>/])" % re.escape(tag))
        close = f"</{tag}>"
        i = pkg_start
        while i <= pkg_end:
            if open_re.search(lines[i]):
                depth = 0
                end = i
                for k in range(i, pkg_end + 1):
                    depth += len(open_re.findall(lines[k]))
                    depth -= lines[k].count(close)
                    if depth <= 0:
                        end = k
                        break
                name = _short_name(lines, i, end) or "?"
                elements.append((name, i, end))
                i = end + 1
            else:
                i += 1
    return elements


def _scan_datatype_map_dups(lines: List[str]) -> List[str]:
    """Return APPLICATION-DATA-TYPE-REF values that appear >1 in DataTypeMappingSets."""
    rng = _find_package_range(lines, "DataTypeMappingSets")
    if not rng:
        return []
    p0, p1 = rng
    refs: List[str] = []
    i = p0
    open_re = re.compile(r"<DATA-TYPE-MAP(?:[\s>/])")
    while i <= p1:
        if open_re.search(lines[i]):
            depth = 0
            end = i
            app_ref = ""
            for k in range(i, p1 + 1):
                depth += len(open_re.findall(lines[k]))
                depth -= lines[k].count("</DATA-TYPE-MAP>")
                if not app_ref:
                    m = re.search(
                        r"<APPLICATION-DATA-TYPE-REF[^>]*>([^<]+)", lines[k]
                    )
                    if m:
                        app_ref = m.group(1).strip()
                if depth <= 0:
                    end = k
                    break
            if app_ref:
                refs.append(app_ref)
            i = end + 1
        else:
            i += 1
    c = Counter(refs)
    return sorted([r for r, n in c.items() if n > 1])


def scan_package_duplicates(filepath: str) -> List[CheckIssue]:
    issues: List[CheckIssue] = []
    if not filepath or not os.path.isfile(filepath):
        return issues
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()

    total_groups = 0
    samples: List[str] = []
    for pkg, tags in TARGET_PACKAGES.items():
        rng = _find_package_range(lines, pkg)
        if not rng:
            continue
        elems = _find_child_elements(lines, rng[0], rng[1], tags)
        c = Counter(n for n, _s, _e in elems)
        dups = sorted([n for n, v in c.items() if v > 1 and n != "?"])
        if not dups:
            continue
        total_groups += len(dups)
        label = PKG_LABEL.get(pkg, pkg)
        for name in dups[:8]:
            samples.append(f"{label}:{name}×{c[name]}")
            issues.append(
                CheckIssue(
                    "error",
                    label,
                    f"{pkg} 内 SHORT-NAME 重复: {name}（{c[name]} 份）"
                    f" — 可用去重脚本修复",
                    f"/{pkg}/{name}",
                    "adt" if label == "ADT" else ("idt" if label == "IDT" else ""),
                    fix_action="script_dedup",
                    fix_label="运行 dedup_arxml.py（写出 beta，不覆盖原文件）",
                )
            )
        if len(dups) > 8:
            issues.append(
                CheckIssue(
                    "error",
                    label,
                    f"{pkg} 另有 {len(dups) - 8} 组 SHORT-NAME 重复",
                    f"/{pkg}",
                    "",
                    fix_action="script_dedup",
                    fix_label="运行 dedup_arxml.py（写出 beta，不覆盖原文件）",
                )
            )

    map_dups = _scan_datatype_map_dups(lines)
    if map_dups:
        total_groups += len(map_dups)
        for ref in map_dups[:10]:
            issues.append(
                CheckIssue(
                    "error",
                    "DataTypeMap",
                    f"DATA-TYPE-MAP 重复 APPLICATION-DATA-TYPE-REF: {ref}",
                    ref,
                    "adt",
                    fix_action="script_dedup",
                    fix_label="运行 dedup_arxml.py（写出 beta，不覆盖原文件）",
                )
            )
        if len(map_dups) > 10:
            issues.append(
                CheckIssue(
                    "error",
                    "DataTypeMap",
                    f"另有 {len(map_dups) - 10} 组 DataTypeMap 重复",
                    "/DataTypeMappingSets",
                    "",
                    fix_action="script_dedup",
                    fix_label="运行 dedup_arxml.py（写出 beta，不覆盖原文件）",
                )
            )

    if total_groups and not any(i.fix_action == "script_dedup" for i in issues):
        pass
    elif total_groups:
        # summary already covered by per-item issues
        _ = samples
    return issues


def scan_duplicate_uuids(filepath: str) -> List[CheckIssue]:
    issues: List[CheckIssue] = []
    if not filepath or not os.path.isfile(filepath):
        return issues
    counts: Counter = Counter()
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            for m in UUID_ATTR_RE.finditer(line):
                counts[m.group(1)] += 1
    dups = sorted([u for u, n in counts.items() if n > 1])
    if not dups:
        return issues
    issues.append(
        CheckIssue(
            "error",
            "UUID",
            f"发现 {len(dups)} 组重复 UUID（示例 {dups[0]} ×{counts[dups[0]]}）"
            f" — 可用 UUID 修复脚本",
            filepath,
            "",
            fix_action="script_fix_uuid",
            fix_label="运行 fix_duplicate_uuids.py --fix（写出 beta；数据类型类或需 custom-fix）",
        )
    )
    for u in dups[:12]:
        issues.append(
            CheckIssue(
                "error",
                "UUID",
                f"重复 UUID: {u}（出现 {counts[u]} 次）",
                "",
                "",
                fix_action="script_fix_uuid",
                fix_label="运行 fix_duplicate_uuids.py --fix（写出 beta）",
            )
        )
    if len(dups) > 12:
        issues.append(
            CheckIssue(
                "error",
                "UUID",
                f"另有 {len(dups) - 12} 组重复 UUID",
                "",
                "",
                fix_action="script_fix_uuid",
                fix_label="运行 fix_duplicate_uuids.py --fix（写出 beta）",
            )
        )
    return issues


def scan_empty_constants(filepath: str) -> List[CheckIssue]:
    """Empty CS shells — platform export issue; backdoor fix only."""
    issues: List[CheckIssue] = []
    if not filepath or not os.path.isfile(filepath):
        return issues
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    open_re = re.compile(r"<CONSTANT-SPECIFICATION(?:[\s>/])")
    close = "</CONSTANT-SPECIFICATION>"
    empties: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if not open_re.search(lines[i]):
            i += 1
            continue
        depth = 0
        end = i
        for k in range(i, n):
            depth += len(open_re.findall(lines[k]))
            depth -= lines[k].count(close)
            if depth <= 0:
                end = k
                break
        sn = _short_name(lines, i, end) or "?"
        block = "\n".join(lines[i : end + 1])
        has_vs = "<VALUE-SPEC>" in block or "<VALUE-REF>" in block
        if not has_vs:
            empties.append(sn)
        i = end + 1

    if not empties:
        return issues
    tool_ok = bool(resolve_scripts_dir())
    note = "（宜由导出平台修复；viewer 仅提供后门脚本）"
    if not tool_ok:
        note += " — 未找到 tools/ 脚本，后门不可用"
    issues.append(
        CheckIssue(
            "warning",
            "Constant",
            f"空壳 ConstantSpecification {len(empties)} 个缺 VALUE-SPEC {note}",
            "/ConstantSpecifications",
            "",
            fix_action="backdoor_empty_cs" if tool_ok else "",
            fix_label="后门: fix_empty_constants.py（写出 beta，非推荐默认路径）"
            if tool_ok
            else "",
        )
    )
    for sn in empties[:15]:
        issues.append(
            CheckIssue(
                "warning",
                "Constant",
                f"空壳 CS: {sn} 缺 VALUE-SPEC",
                f"/ConstantSpecifications/{sn}",
                "",
                fix_action="backdoor_empty_cs" if tool_ok else "",
                fix_label="后门: fix_empty_constants.py"
                if tool_ok
                else "",
            )
        )
    if len(empties) > 15:
        issues.append(
            CheckIssue(
                "warning",
                "Constant",
                f"另有 {len(empties) - 15} 个空壳 Constant",
                "",
                "",
                fix_action="backdoor_empty_cs" if tool_ok else "",
                fix_label="后门: fix_empty_constants.py"
                if tool_ok
                else "",
            )
        )
    return issues


def scan_nm_dgr(filepath: str) -> List[CheckIssue]:
    """N:M / redundant DG_R — platform export issue; backdoor fix only."""
    issues: List[CheckIssue] = []
    if not filepath or not os.path.isfile(filepath):
        return issues
    tools = resolve_scripts_dir()
    if not tools:
        issues.append(
            CheckIssue(
                "info",
                "N:M",
                "未找到 arxml_viewer/tools，跳过 N:M / DG_R 扫描",
                "",
                "",
            )
        )
        return issues
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        from fix_nm_dgr_cascade import detect_nm_bases  # type: ignore
    except Exception as e:
        issues.append(
            CheckIssue(
                "info",
                "N:M",
                f"无法加载 detect_nm_bases: {e}",
                "",
                "",
            )
        )
        return issues
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    nm_map: Dict[str, Set[str]] = detect_nm_bases(lines)
    if not nm_map:
        return issues
    total = sum(len(v) for v in nm_map.values())
    issues.append(
        CheckIssue(
            "warning",
            "N:M",
            f"疑似 Vector 40329 N:M / 冗余 DG_R：{len(nm_map)} 个 Composition、"
            f"{total} 个数据元素（宜由导出平台修复；viewer 仅提供后门）",
            "",
            "composition",
            fix_action="backdoor_nm_dgr",
            fix_label="后门: fix_nm_dgr_cascade.py（写出 beta，非推荐默认路径）",
        )
    )
    for comp, bases in sorted(nm_map.items())[:10]:
        shown = ", ".join(sorted(bases)[:6])
        extra = f" …+{len(bases) - 6}" if len(bases) > 6 else ""
        issues.append(
            CheckIssue(
                "warning",
                "N:M",
                f"[{comp}] 冗余 DG_R: {shown}{extra}",
                "",
                "composition",
                fix_action="backdoor_nm_dgr",
                fix_label="后门: fix_nm_dgr_cascade.py",
            )
        )
    if len(nm_map) > 10:
        issues.append(
            CheckIssue(
                "warning",
                "N:M",
                f"另有 {len(nm_map) - 10} 个 Composition 含冗余 DG_R",
                "",
                "composition",
                fix_action="backdoor_nm_dgr",
                fix_label="后门: fix_nm_dgr_cascade.py",
            )
        )
    return issues


def run_export_defect_checks(filepath: str) -> List[CheckIssue]:
    """All file-level export defect checks for a saved ARXML path."""
    if not filepath or not os.path.isfile(filepath):
        return [
            CheckIssue(
                "info",
                "Export",
                "无磁盘路径，跳过 ADT/IDT/UUID/空壳CS/N:M 文件级扫描",
                "",
                "",
            )
        ]
    out: List[CheckIssue] = []
    out.extend(scan_package_duplicates(filepath))
    out.extend(scan_duplicate_uuids(filepath))
    out.extend(scan_empty_constants(filepath))
    out.extend(scan_nm_dgr(filepath))
    return out
