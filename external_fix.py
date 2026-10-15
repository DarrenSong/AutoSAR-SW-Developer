# -*- coding: utf-8 -*-
"""Invoke bundled repair scripts under arxml_viewer/tools (no external dir)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence


def resolve_scripts_dir() -> Optional[str]:
    """Local tools/ next to this package (scripts copied into the repo)."""
    here = os.path.dirname(os.path.abspath(__file__))
    tools = os.path.join(here, "tools")
    if os.path.isfile(os.path.join(tools, "dedup_arxml.py")):
        return tools
    return None


# Backward-compatible alias used by dialogs
def resolve_tool_gui_dir() -> Optional[str]:
    return resolve_scripts_dir()


def suggest_beta_output(path: str) -> str:
    root, ext = os.path.splitext(path)
    m = re.search(r"_beta(\d+)\.(\d+)$", root)
    if m:
        major, minor = int(m.group(1)), int(m.group(2))
        return f"{root[: m.start()]}_beta{major}.{minor + 1}{ext}"
    return f"{root}_beta0.1{ext}"


@dataclass
class ScriptFixResult:
    ok: bool
    output_path: str = ""
    log: str = ""
    returncode: int = -1


# fix_action -> (script filename, extra args, uses -o)
SCRIPT_FIXES = {
    "script_dedup": ("dedup_arxml.py", [], False),
    "script_fix_uuid": ("fix_duplicate_uuids.py", ["--fix"], True),
    "backdoor_empty_cs": ("fix_empty_constants.py", [], True),
    "backdoor_nm_dgr": ("fix_nm_dgr_cascade.py", [], True),
}


def is_backdoor_action(action: str) -> bool:
    return (action or "").startswith("backdoor_")


def is_script_action(action: str) -> bool:
    return action in SCRIPT_FIXES


def run_script_fix(
    action: str,
    input_path: str,
    *,
    output_path: Optional[str] = None,
    donor_paths: Optional[Sequence[str]] = None,
) -> ScriptFixResult:
    """Run bundled script; returns log + output path (best-effort)."""
    meta = SCRIPT_FIXES.get(action)
    if not meta:
        return ScriptFixResult(False, log=f"未知修复动作: {action}")
    tools = resolve_scripts_dir()
    if not tools:
        return ScriptFixResult(
            False,
            log="未找到 arxml_viewer/tools 下的修复脚本。",
        )
    script, extra, use_o = meta
    script_path = os.path.join(tools, script)
    if not os.path.isfile(script_path):
        return ScriptFixResult(False, log=f"脚本不存在: {script_path}")
    if not input_path or not os.path.isfile(input_path):
        return ScriptFixResult(False, log=f"输入文件不存在: {input_path}")

    out = (output_path or "").strip() or suggest_beta_output(input_path)
    if os.path.exists(out) and out != input_path:
        base, ext = os.path.splitext(out)
        n = 1
        while os.path.exists(f"{base}_r{n}{ext}"):
            n += 1
        out = f"{base}_r{n}{ext}"

    cmd: List[str] = [sys.executable, script_path, input_path]
    cmd.extend(extra)
    if use_o:
        cmd.extend(["-o", out])
    if action == "backdoor_empty_cs" and donor_paths:
        for d in donor_paths:
            if d and os.path.isfile(d):
                cmd.extend(["--donor", d])

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            cmd,
            cwd=tools,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=3600,
        )
    except subprocess.TimeoutExpired:
        return ScriptFixResult(False, log="脚本超时（>1h）")
    except OSError as e:
        return ScriptFixResult(False, log=f"无法启动脚本: {e}")

    log = (proc.stdout or "") + (proc.stderr or "")
    if not use_o:
        m = re.search(r"输出文件:\s*(.+)", log)
        if m:
            out = m.group(1).strip()
    ok = False
    if use_o and os.path.isfile(out):
        ok = True
    elif not use_o and os.path.isfile(out):
        ok = True
    elif proc.returncode == 0 and os.path.isfile(out):
        ok = True
    return ScriptFixResult(
        ok=ok,
        output_path=out if os.path.isfile(out) else "",
        log=log,
        returncode=proc.returncode,
    )


def parse_script_output_path(log: str, fallback: str = "") -> str:
    m = re.search(r"输出文件:\s*(.+)", log or "")
    if m:
        p = m.group(1).strip()
        if os.path.isfile(p):
            return p
    return fallback if fallback and os.path.isfile(fallback) else ""
