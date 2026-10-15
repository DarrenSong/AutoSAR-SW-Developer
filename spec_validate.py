# -*- coding: utf-8 -*-
"""
AUTOSAR spec validation for arxml_viewer.

Single engine: arxml_schema_validator.py + AUTOSAR_MMOD_XMLSchema/AUTOSAR_00046.xsd
(includes XSD + semantic checks + Vector 40329 N:M communication).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple


_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_XSD = os.path.join(_PKG_DIR, "AUTOSAR_MMOD_XMLSchema", "AUTOSAR_00046.xsd")

_XSD_LINE_RE = re.compile(r"XSD L(\d+)\s*:", re.I)
_PATH_RE = re.compile(r"(/(?:[A-Za-z][A-Za-z0-9_]*)(?:/(?:[A-Za-z][A-Za-z0-9_]*))+)")


ISSUE_CATEGORIES = ("全部", "XSD", "N:M", "REF", "NAME", "TIMING", "OTHER")


def classify_issue(msg: str) -> str:
    """Bucket a validation message for UI filtering."""
    m = msg or ""
    u = m.upper()
    if m.startswith("XSD ") or "XSD L" in m or "SCHEMA" in u and "校验" in m:
        return "XSD"
    if "40329" in m or "N:M" in u or "N/M" in u or "一对多" in m or "多对多" in m:
        return "N:M"
    if "REF" in u or "引用" in m or "DEST" in m or "TREF" in u:
        return "REF"
    if "IDENTIFIER" in m or "SHORT-NAME" in m or "命名" in m or "UUID" in u:
        return "NAME"
    if "TIMING" in u or "OFFSET" in m or "PERIOD" in m:
        return "TIMING"
    return "OTHER"


def parse_xsd_line(msg: str) -> Optional[int]:
    m = _XSD_LINE_RE.search(msg or "")
    return int(m.group(1)) if m else None


def parse_autosar_path(msg: str) -> Optional[str]:
    m = _PATH_RE.search(msg or "")
    return m.group(1) if m else None


def resolve_jump_target(
    msg: str, model=None
) -> Tuple[Optional[str], str, Optional[int]]:
    """
    Return (path, kind, line) for navigation from a validation message.
    kind is a tree/model kind hint, or 'source' when only a line is known.
    """
    line = parse_xsd_line(msg)
    path = parse_autosar_path(msg)
    if path and model is not None:
        if path in getattr(model, "ports", {}):
            return path, "port", line
        if path in getattr(model, "swc_types", {}):
            swc = model.swc_types[path]
            kind = "composition" if getattr(swc, "kind", "") == "COMPOSITION" else "swc"
            return path, kind, line
        if path in getattr(model, "assemblies", {}) or path in getattr(
            model, "delegations", {}
        ):
            return path, "connector", line
        if path in getattr(model, "runnables", {}):
            return path, "runnable", line
        if path in getattr(model, "adts", {}):
            return path, "adt", line
        if path in getattr(model, "idts", {}):
            return path, "idt", line
        if path in getattr(model, "interfaces", {}) or path in getattr(
            model, "cs_interfaces", {}
        ):
            return path, "sr_interface", line
        return path, "path", line
    if path:
        return path, "path", line
    if line is not None:
        return None, "source", line
    return None, "", None


@dataclass
class SpecIssue:
    severity: str
    message: str


@dataclass
class SpecValidateResult:
    ok: bool
    filepath: str
    engine: str  # schema | none
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    infos: List[str] = field(default_factory=list)
    passed_count: int = 0
    total_count: int = 0
    detail: str = ""

    @property
    def summary(self) -> str:
        return (
            f"[{self.engine}] E={len(self.errors)} W={len(self.warnings)} "
            f"pass={self.passed_count}/{self.total_count}"
        )

    def _fix_hint(self, msg: str) -> Optional[str]:
        try:
            from .arxml_schema_validator import ValidationResult

            return ValidationResult().get_fix_hint(msg)
        except Exception:
            return None

    def export_txt(self, out_path: str) -> None:
        """Write full validation report as UTF-8 text."""
        xsd = find_local_xsd() or "(未找到)"
        conclusion = "通过" if self.ok else f"存在 {len(self.errors)} 个错误"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"{'=' * 72}\n")
            f.write("  AUTOSAR ARXML 规范校验报告\n")
            f.write("  基于 AUTOSAR_00046.xsd (CP 4.4.0 / AP 18-10)\n")
            f.write(f"{'=' * 72}\n")
            f.write(f"  文件: {self.filepath}\n")
            f.write(f"  XSD:  {xsd}\n")
            f.write(f"  引擎: {self.engine}\n")
            f.write(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"  详情: {self.detail}\n")
            f.write(f"{'=' * 72}\n\n")
            f.write(
                f"检查项: {self.total_count}  通过: {self.passed_count}  "
                f"错误: {len(self.errors)}  警告: {len(self.warnings)}\n\n"
            )
            if self.errors:
                f.write(f"--- 错误 ({len(self.errors)}) ---\n")
                for i, e in enumerate(self.errors, 1):
                    f.write(f"  [{i}] {e}\n")
                    hint = self._fix_hint(e)
                    if hint:
                        f.write(f"      -> {hint}\n")
                f.write("\n")
            if self.warnings:
                f.write(f"--- 警告 ({len(self.warnings)}) ---\n")
                for i, w in enumerate(self.warnings, 1):
                    f.write(f"  [{i}] {w}\n")
                    hint = self._fix_hint(w)
                    if hint:
                        f.write(f"      -> {hint}\n")
                f.write("\n")
            if self.infos:
                f.write(f"--- 信息 ({len(self.infos)}) ---\n")
                for i, x in enumerate(self.infos, 1):
                    f.write(f"  [{i}] {x}\n")
            f.write(f"\n{'=' * 72}\n")
            f.write(f"  结论: {conclusion}\n")
            f.write(f"{'=' * 72}\n")

    def export_pdf(self, out_path: str) -> None:
        """Write PDF report. Raises RuntimeError if reportlab is unavailable."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.lib.colors import HexColor
            from reportlab.platypus import (
                SimpleDocTemplate,
                Paragraph,
                Spacer,
                Table,
                TableStyle,
            )
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError as e:
            raise RuntimeError(
                "未安装 reportlab，无法导出 PDF。请运行: pip install reportlab"
            ) from e

        xsd = find_local_xsd() or "(未找到)"
        font_path = os.path.join(
            os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "simhei.ttf"
        )
        if os.path.isfile(font_path):
            pdfmetrics.registerFont(TTFont("SimHei", font_path))
            cn_font = "SimHei"
        else:
            cn_font = "Helvetica"

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "CNTitle", parent=styles["Title"], fontName=cn_font, fontSize=18, spaceAfter=12
        )
        h2_style = ParagraphStyle(
            "CNH2",
            parent=styles["Heading2"],
            fontName=cn_font,
            fontSize=13,
            spaceAfter=8,
            textColor=HexColor("#333333"),
        )
        body_style = ParagraphStyle(
            "CNBody",
            parent=styles["Normal"],
            fontName=cn_font,
            fontSize=9,
            leading=13,
            spaceAfter=4,
        )
        error_style = ParagraphStyle(
            "CNError", parent=body_style, textColor=HexColor("#CC0000")
        )
        warn_style = ParagraphStyle(
            "CNWarn", parent=body_style, textColor=HexColor("#CC7700")
        )
        info_style = ParagraphStyle(
            "CNInfo", parent=body_style, textColor=HexColor("#336699")
        )
        hint_style = ParagraphStyle(
            "CNHint",
            parent=body_style,
            fontSize=8,
            leading=11,
            textColor=HexColor("#666666"),
            leftIndent=12,
        )

        def _esc(s: str) -> str:
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>")
            )

        doc = SimpleDocTemplate(
            out_path,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        story = []
        story.append(Paragraph("AUTOSAR ARXML 规范校验报告", title_style))
        story.append(
            Paragraph("基于 AUTOSAR_00046.xsd (CP 4.4.0 / AP 18-10)", body_style)
        )
        story.append(Spacer(1, 8))

        info_data = [
            ["文件", os.path.basename(self.filepath) or self.filepath],
            ["路径", self.filepath],
            ["XSD", os.path.basename(xsd) if xsd != "(未找到)" else xsd],
            ["引擎", self.engine],
            ["时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ]
        info_table = Table(info_data, colWidths=[30 * mm, 140 * mm])
        info_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), cn_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TEXTCOLOR", (0, 0), (0, -1), HexColor("#666666")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(info_table)
        story.append(Spacer(1, 12))

        status_text = "通过" if self.ok else f"存在 {len(self.errors)} 个错误"
        status_color = "#009900" if self.ok else "#CC0000"
        summary_data = [
            ["检查项", "通过", "错误", "警告", "结论"],
            [
                str(self.total_count),
                str(self.passed_count),
                str(len(self.errors)),
                str(len(self.warnings)),
                Paragraph(
                    f'<font color="{status_color}">{status_text}</font>', body_style
                ),
            ],
        ]
        summary_table = Table(
            summary_data, colWidths=[30 * mm, 30 * mm, 30 * mm, 30 * mm, 50 * mm]
        )
        summary_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), cn_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#EEEEEE")),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(summary_table)
        story.append(Spacer(1, 16))

        if self.errors:
            story.append(Paragraph(f"错误 ({len(self.errors)})", h2_style))
            for i, e in enumerate(self.errors, 1):
                story.append(Paragraph(f"[{i}] {_esc(e)}", error_style))
                hint = self._fix_hint(e)
                if hint:
                    story.append(Paragraph(_esc(hint), hint_style))
            story.append(Spacer(1, 8))

        if self.warnings:
            story.append(Paragraph(f"警告 ({len(self.warnings)})", h2_style))
            for i, w in enumerate(self.warnings, 1):
                story.append(Paragraph(f"[{i}] {_esc(w)}", warn_style))
                hint = self._fix_hint(w)
                if hint:
                    story.append(Paragraph(_esc(hint), hint_style))
            story.append(Spacer(1, 8))

        if self.infos:
            story.append(Paragraph(f"信息 ({len(self.infos)})", h2_style))
            for i, x in enumerate(self.infos, 1):
                story.append(Paragraph(f"[{i}] {_esc(x)}", info_style))

        def _draw_page_number(canvas, _doc):
            canvas.saveState()
            canvas.setFont(cn_font, 8)
            canvas.setFillColor(HexColor("#999999"))
            canvas.drawCentredString(A4[0] / 2, 12 * mm, f"- {canvas.getPageNumber()} -")
            canvas.restoreState()

        doc.build(story, onFirstPage=_draw_page_number, onLaterPages=_draw_page_number)


def find_local_xsd() -> Optional[str]:
    if os.path.isfile(_LOCAL_XSD):
        return _LOCAL_XSD
    return None


def _filter_by_scope(messages: List[str], scope_prefix: str) -> List[str]:
    """Keep messages that mention scope_prefix or have no path (global)."""
    if not scope_prefix:
        return list(messages)
    pref = scope_prefix.rstrip("/")
    out = []
    for m in messages:
        p = parse_autosar_path(m)
        if p is None or p == pref or p.startswith(pref + "/"):
            out.append(m)
        elif pref in m:
            out.append(m)
    return out


def _run_schema_validator(
    filepath: str,
    *,
    cancel_check=None,
    progress_cb=None,
    scope_prefix: str = "",
) -> SpecValidateResult:
    from .arxml_schema_validator import AutosarSchemaValidator

    xsd = find_local_xsd()
    v = AutosarSchemaValidator(
        filepath,
        xsd_path=xsd,
        cancel_check=cancel_check,
        progress_cb=progress_cb,
    )
    if not v.xsd_path or not os.path.isfile(v.xsd_path):
        return SpecValidateResult(
            ok=False,
            filepath=filepath,
            engine="schema",
            errors=[
                "未找到 AUTOSAR_00046.xsd。"
                f"请确认存在: {_LOCAL_XSD}"
            ],
            detail="XSD missing",
        )
    r = v.validate()
    errors = list(getattr(r, "errors", []) or [])
    warnings = list(getattr(r, "warnings", []) or [])
    infos = [
        x
        for x in (getattr(r, "infos", []) or [])
        if not str(x).startswith("[PASS]")
    ][:80]
    if scope_prefix:
        errors = _filter_by_scope(errors, scope_prefix)
        warnings = _filter_by_scope(warnings, scope_prefix)
        infos = _filter_by_scope(infos, scope_prefix)
    detail = f"xsd={v.xsd_path}"
    if scope_prefix:
        detail += f" scope={scope_prefix}"
    if getattr(v, "cancelled", False):
        detail += " cancelled"
    return SpecValidateResult(
        ok=len(errors) == 0 and not getattr(v, "cancelled", False),
        filepath=filepath,
        engine="schema",
        errors=errors,
        warnings=warnings,
        infos=infos,
        passed_count=int(getattr(r, "passed_count", 0) or 0),
        total_count=int(getattr(r, "total_count", 0) or 0),
        detail=detail,
    )


def validate_arxml_spec(
    filepath: str,
    *,
    cancel_check=None,
    progress_cb=None,
    scope_prefix: str = "",
    **_ignored,
) -> SpecValidateResult:
    """
    Run full AUTOSAR validation (arxml_schema_validator + AUTOSAR_00046.xsd).

    scope_prefix: if set, filter reported issues to that Composition/SWC path.
    cancel_check: callable returning True to abort between phases.
    progress_cb: callable(str) for UI status.
    """
    if not filepath or not os.path.isfile(filepath):
        return SpecValidateResult(
            ok=False,
            filepath=filepath or "",
            engine="none",
            errors=[f"文件不存在: {filepath}"],
            detail="文件不存在",
        )

    import contextlib
    import io

    buf = io.StringIO()
    try:
        # When progress_cb is provided, do not swallow stdout progress
        if progress_cb:
            return _run_schema_validator(
                filepath,
                cancel_check=cancel_check,
                progress_cb=progress_cb,
                scope_prefix=scope_prefix,
            )
        with contextlib.redirect_stdout(buf):
            return _run_schema_validator(
                filepath,
                cancel_check=cancel_check,
                progress_cb=None,
                scope_prefix=scope_prefix,
            )
    except Exception as e:
        return SpecValidateResult(
            ok=False,
            filepath=filepath,
            engine="none",
            errors=[f"规范校验异常: {e}"],
            detail=str(e),
        )


def hop_dir_label(model, hop) -> str:
    """Human label for one chain hop: P→R / 同向P / 同向R / ?."""
    fp = model.ports.get(hop.from_port) if model else None
    tp = model.ports.get(hop.to_port) if model else None
    fd = (fp.direction if fp else "") or "?"
    td = (tp.direction if tp else "") or "?"
    if hop.kind == "assembly":
        return f"{fd}→{td}"
    if fd == td:
        return f"同向{fd}"
    return f"{fd}/{td}"
