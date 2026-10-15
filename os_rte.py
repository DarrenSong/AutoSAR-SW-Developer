# -*- coding: utf-8 -*-
"""Lightweight OS-Task / Runnable→Task overlay (sidecar JSON, not ECUC)."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class OsTask:
    name: str
    priority: int = 0
    schedule: str = "FULL"  # FULL | NON
    type: str = "EXTENDED"  # BASIC | EXTENDED


@dataclass
class RunnableToTaskMapping:
    task: str
    swc_prototype: str
    runnable: str
    position: int = 0


@dataclass
class OsRteOverlay:
    version: int = 1
    ecu: str = "EcuStub"
    tasks: List[OsTask] = field(default_factory=list)
    mappings: List[RunnableToTaskMapping] = field(default_factory=list)
    source_path: str = ""
    dirty: bool = False

    def rebuild_indexes(self) -> None:
        self._by_task: Dict[str, List[RunnableToTaskMapping]] = defaultdict(list)
        self._by_runnable: Dict[str, List[RunnableToTaskMapping]] = defaultdict(list)
        self._task_by_name: Dict[str, OsTask] = {}
        for t in self.tasks:
            self._task_by_name[t.name] = t
        for m in sorted(self.mappings, key=lambda x: (x.task, x.position, x.runnable)):
            self._by_task[m.task].append(m)
            self._by_runnable[m.runnable].append(m)

    def __post_init__(self) -> None:
        self.rebuild_indexes()

    def task_names(self) -> List[str]:
        return [t.name for t in self.tasks]

    def get_task(self, name: str) -> Optional[OsTask]:
        return getattr(self, "_task_by_name", {}).get(name)

    def mappings_by_task(self, task_name: str) -> List[RunnableToTaskMapping]:
        return list(getattr(self, "_by_task", {}).get(task_name, []))

    def mappings_by_runnable(self, runnable_path: str) -> List[RunnableToTaskMapping]:
        return list(getattr(self, "_by_runnable", {}).get(runnable_path, []))

    def task_of(self, proto: str, runnable: str) -> Optional[str]:
        for m in self.mappings:
            if m.swc_prototype == proto and m.runnable == runnable:
                return m.task
        return None

    def add_task(self, task: OsTask) -> str:
        if not task.name:
            return "Task 名称不能为空"
        if any(t.name == task.name for t in self.tasks):
            return f"Task 已存在: {task.name}"
        self.tasks.append(task)
        self.dirty = True
        self.rebuild_indexes()
        return ""

    def remove_task(self, name: str) -> str:
        self.tasks = [t for t in self.tasks if t.name != name]
        self.mappings = [m for m in self.mappings if m.task != name]
        self.dirty = True
        self.rebuild_indexes()
        return ""

    def add_mapping(self, mapping: RunnableToTaskMapping) -> str:
        if not mapping.task or not mapping.swc_prototype or not mapping.runnable:
            return "Task / Prototype / Runnable 均不能为空"
        if not self.get_task(mapping.task):
            return f"未知 Task: {mapping.task}"
        for m in self.mappings:
            if (
                m.swc_prototype == mapping.swc_prototype
                and m.runnable == mapping.runnable
                and m.task == mapping.task
            ):
                return "相同 Mapping 已存在"
        self.mappings.append(mapping)
        self.dirty = True
        self.rebuild_indexes()
        return ""

    def remove_mapping(
        self, task: str, swc_prototype: str, runnable: str
    ) -> str:
        before = len(self.mappings)
        self.mappings = [
            m
            for m in self.mappings
            if not (
                m.task == task
                and m.swc_prototype == swc_prototype
                and m.runnable == runnable
            )
        ]
        if len(self.mappings) == before:
            return "未找到 Mapping"
        self.dirty = True
        self.rebuild_indexes()
        return ""

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "ecu": self.ecu,
            "tasks": [asdict(t) for t in self.tasks],
            "mappings": [asdict(m) for m in self.mappings],
        }


def default_os_rte_path(arxml_path: str) -> str:
    if not arxml_path:
        return ""
    stem, _ = os.path.splitext(os.path.abspath(arxml_path))
    return stem + ".os_rte.json"


def empty_overlay(source_path: str = "") -> OsRteOverlay:
    return OsRteOverlay(source_path=source_path, dirty=False)


def load_os_rte(path: str) -> Tuple[Optional[OsRteOverlay], str]:
    """Return (overlay, error). Missing file → empty overlay, no error."""
    if not path:
        return empty_overlay(), ""
    if not os.path.isfile(path):
        return empty_overlay(path), ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return None, f"读取失败: {e}"
    tasks = []
    for t in data.get("tasks") or []:
        if not isinstance(t, dict):
            continue
        name = (t.get("name") or "").strip()
        if not name:
            continue
        tasks.append(
            OsTask(
                name=name,
                priority=int(t.get("priority") or 0),
                schedule=str(t.get("schedule") or "FULL"),
                type=str(t.get("type") or "EXTENDED"),
            )
        )
    mappings = []
    for m in data.get("mappings") or []:
        if not isinstance(m, dict):
            continue
        task = (m.get("task") or "").strip()
        proto = (m.get("swc_prototype") or "").strip()
        run = (m.get("runnable") or "").strip()
        if not task or not proto or not run:
            continue
        mappings.append(
            RunnableToTaskMapping(
                task=task,
                swc_prototype=proto,
                runnable=run,
                position=int(m.get("position") or 0),
            )
        )
    ov = OsRteOverlay(
        version=int(data.get("version") or 1),
        ecu=str(data.get("ecu") or "EcuStub"),
        tasks=tasks,
        mappings=mappings,
        source_path=path,
        dirty=False,
    )
    return ov, ""


def save_os_rte(path: str, overlay: OsRteOverlay) -> str:
    """Save overlay; return error string or empty on success."""
    if not path:
        return "未指定保存路径"
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(overlay.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as e:
        return f"写入失败: {e}"
    overlay.source_path = path
    overlay.dirty = False
    return ""


def import_os_rte_csv(path: str, overlay: Optional[OsRteOverlay] = None) -> Tuple[OsRteOverlay, str]:
    """
    Import tasks/mappings from CSV into overlay (merge).

    Columns (header required):
      kind,task,priority,schedule,type,swc_prototype,runnable,position
    kind=task → name in task, optional priority/schedule/type
    kind=mapping → task,swc_prototype,runnable,position
    """
    import csv

    ov = overlay or empty_overlay()
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return ov, "CSV 无表头"
            n_t = n_m = 0
            for row in reader:
                kind = (row.get("kind") or row.get("Kind") or "").strip().lower()
                if kind == "task":
                    name = (row.get("task") or row.get("name") or "").strip()
                    if not name:
                        continue
                    if not ov.get_task(name):
                        err = ov.add_task(
                            OsTask(
                                name=name,
                                priority=int(row.get("priority") or 0),
                                schedule=(row.get("schedule") or "FULL").strip()
                                or "FULL",
                                type=(row.get("type") or "EXTENDED").strip()
                                or "EXTENDED",
                            )
                        )
                        if not err:
                            n_t += 1
                elif kind in ("mapping", "map", ""):
                    # bare mapping rows without kind also accepted if runnable set
                    task = (row.get("task") or "").strip()
                    proto = (row.get("swc_prototype") or row.get("prototype") or "").strip()
                    run = (row.get("runnable") or "").strip()
                    if not (task and proto and run):
                        if kind == "mapping":
                            continue
                        continue
                    if not ov.get_task(task):
                        ov.add_task(OsTask(name=task))
                    err = ov.add_mapping(
                        RunnableToTaskMapping(
                            task=task,
                            swc_prototype=proto,
                            runnable=run,
                            position=int(row.get("position") or 0),
                        )
                    )
                    if not err:
                        n_m += 1
    except (OSError, csv.Error, ValueError) as e:
        return ov, f"CSV 导入失败: {e}"
    ov.dirty = True
    return ov, f"已导入 Task+{n_t} Mapping+{n_m}"


def export_os_rte_csv(path: str, overlay: OsRteOverlay) -> str:
    """Export overlay to CSV; return error or empty."""
    import csv

    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "kind",
                    "task",
                    "priority",
                    "schedule",
                    "type",
                    "swc_prototype",
                    "runnable",
                    "position",
                ]
            )
            for t in overlay.tasks:
                w.writerow(
                    ["task", t.name, t.priority, t.schedule, t.type, "", "", ""]
                )
            for m in overlay.mappings:
                w.writerow(
                    [
                        "mapping",
                        m.task,
                        "",
                        "",
                        "",
                        m.swc_prototype,
                        m.runnable,
                        m.position,
                    ]
                )
    except OSError as e:
        return f"导出失败: {e}"
    return ""
