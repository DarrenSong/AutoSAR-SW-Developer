# -*- coding: utf-8 -*-
"""Load/save .arxml_viewer.json next to a primary ARXML (project pair + prefs)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


CONFIG_NAME = ".arxml_viewer.json"


@dataclass
class ProjectConfig:
    primary: str = ""
    peer: str = ""
    validate_on_open: bool = True
    limit_ports: bool = False
    export_dir: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def config_path_for(arxml_path: str) -> str:
    d = os.path.dirname(os.path.abspath(arxml_path)) if arxml_path else ""
    return os.path.join(d, CONFIG_NAME) if d else CONFIG_NAME


def load_project_config(arxml_path: str) -> Optional[ProjectConfig]:
    path = config_path_for(arxml_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return ProjectConfig(
        primary=data.get("primary") or arxml_path,
        peer=data.get("peer") or "",
        validate_on_open=bool(data.get("validate_on_open", True)),
        limit_ports=bool(data.get("limit_ports", False)),
        export_dir=data.get("export_dir") or "",
        extra=data.get("extra") or {},
    )


def save_project_config(arxml_path: str, cfg: ProjectConfig) -> str:
    path = config_path_for(arxml_path)
    cfg.primary = arxml_path
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)
    except OSError as e:
        return f"写入失败: {e}"
    return path
