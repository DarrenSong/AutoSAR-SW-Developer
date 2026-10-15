# -*- coding: utf-8 -*-
"""
Generate PDF user manual from 用户使用说明书.md

Usage:
  python -m arxml_viewer.docs.build_manual_pdf
  python arxml_viewer/docs/build_manual_pdf.py [-o out.pdf] [manual.md]

Requires: reportlab  (pip install reportlab)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import List, Optional, Tuple


def _find_cn_font() -> Tuple[str, Optional[str]]:
    """Return (fontName, ttfPath or None). Prefer Windows Chinese fonts."""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        ("SimHei", os.path.join(windir, "Fonts", "simhei.ttf")),
        ("SimSun", os.path.join(windir, "Fonts", "simsun.ttc")),
        ("MicrosoftYaHei", os.path.join(windir, "Fonts", "msyh.ttc")),
        ("MicrosoftYaHei", os.path.join(windir, "Fonts", "msyh.ttf")),
    ]
    for name, path in candidates:
        if os.path.isfile(path):
            return name, path
    return "Helvetica", None


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _inline_md(text: str) -> str:
    """Very small markdown inline: **bold**, `code`."""
    s = _esc(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8">\1</font>', s)
    return s


def _parse_table_row(line: str) -> List[str]:
    parts = [c.strip() for c in line.strip().strip("|").split("|")]
    return parts


def build_pdf(md_path: str, out_path: str) -> None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor, black, white
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
            Preformatted,
            PageBreak,
            KeepTogether,
        )
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as e:
        raise SystemExit(
            "未安装 reportlab。请执行:\n"
            "  pip install reportlab\n"
            "或:\n"
            "  pip install -r arxml_viewer/requirements-pdf.txt"
        ) from e

    if not os.path.isfile(md_path):
        raise SystemExit(f"找不到说明书源文件: {md_path}")

    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    font_name, font_path = _find_cn_font()
    if font_path:
        # TTC may need subfontIndex; try register, fallback Helvetica
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_path))
        except Exception:
            try:
                pdfmetrics.registerFont(TTFont(font_name, font_path, subfontIndex=0))
            except Exception:
                font_name = "Helvetica"

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ManualTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=20,
        leading=26,
        spaceAfter=12,
        textColor=HexColor("#1a237e"),
    )
    h1 = ParagraphStyle(
        "ManualH1",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=14,
        leading=20,
        spaceBefore=14,
        spaceAfter=8,
        textColor=HexColor("#0d47a1"),
        borderPadding=3,
    )
    h2 = ParagraphStyle(
        "ManualH2",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=12,
        leading=16,
        spaceBefore=10,
        spaceAfter=6,
        textColor=HexColor("#1565c0"),
    )
    h3 = ParagraphStyle(
        "ManualH3",
        parent=styles["Heading3"],
        fontName=font_name,
        fontSize=11,
        leading=14,
        spaceBefore=8,
        spaceAfter=4,
        textColor=HexColor("#37474f"),
    )
    body = ParagraphStyle(
        "ManualBody",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9.5,
        leading=14,
        spaceAfter=4,
    )
    bullet = ParagraphStyle(
        "ManualBullet",
        parent=body,
        leftIndent=14,
        bulletIndent=4,
        spaceAfter=2,
    )
    code_style = ParagraphStyle(
        "ManualCode",
        parent=styles["Code"],
        fontName="Courier",
        fontSize=8,
        leading=11,
        backColor=HexColor("#f5f5f5"),
        leftIndent=6,
        rightIndent=6,
        spaceBefore=4,
        spaceAfter=8,
    )
    footer_style = ParagraphStyle(
        "ManualFooter",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=8,
        textColor=HexColor("#9e9e9e"),
        alignment=1,
    )

    story: List = []
    i = 0
    in_code = False
    code_buf: List[str] = []
    first_title_done = False

    def flush_code():
        nonlocal code_buf
        if not code_buf:
            return
        text = "\n".join(code_buf)
        story.append(Preformatted(text, code_style))
        code_buf = []

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()

        if line.startswith("```"):
            if in_code:
                in_code = False
                flush_code()
            else:
                in_code = True
            i += 1
            continue

        if in_code:
            code_buf.append(raw)
            i += 1
            continue

        if not line.strip():
            story.append(Spacer(1, 3))
            i += 1
            continue

        if line.strip() == "---":
            story.append(Spacer(1, 6))
            i += 1
            continue

        # Table: header | sep | rows
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*[-:| ]+\|", lines[i + 1]):
            rows = [_parse_table_row(line)]
            i += 2  # skip separator
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_parse_table_row(lines[i]))
                i += 1
            # Paragraph cells for wrapping
            data = []
            for ri, row in enumerate(rows):
                data.append(
                    [
                        Paragraph(_inline_md(c), body if ri else h3)
                        for c in row
                    ]
                )
            col_n = max(len(r) for r in data) if data else 1
            page_w = A4[0] - 40 * mm
            col_w = page_w / col_n
            tbl = Table(data, colWidths=[col_w] * col_n, repeatRows=1)
            tbl.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), font_name),
                        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#e3f2fd")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#0d47a1")),
                        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#b0bec5")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [white, HexColor("#fafafa")],
                        ),
                    ]
                )
            )
            story.append(tbl)
            story.append(Spacer(1, 8))
            continue

        if line.startswith("# "):
            text = line[2:].strip()
            if not first_title_done:
                story.append(Paragraph(_inline_md(text), title))
                first_title_done = True
            else:
                story.append(Paragraph(_inline_md(text), h1))
            i += 1
            continue
        if line.startswith("## "):
            story.append(Paragraph(_inline_md(line[3:].strip()), h1))
            i += 1
            continue
        if line.startswith("### "):
            story.append(Paragraph(_inline_md(line[4:].strip()), h2))
            i += 1
            continue

        m_ul = re.match(r"^[-*]\s+(.+)$", line)
        if m_ul:
            story.append(
                Paragraph(f"• {_inline_md(m_ul.group(1))}", bullet)
            )
            i += 1
            continue

        m_ol = re.match(r"^(\d+)\.\s+(.+)$", line)
        if m_ol:
            story.append(
                Paragraph(
                    f"{m_ol.group(1)}. {_inline_md(m_ol.group(2))}", bullet
                )
            )
            i += 1
            continue

        story.append(Paragraph(_inline_md(line), body))
        i += 1

    flush_code()

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)

    def _on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(font_name if font_path else "Helvetica", 8)
        canvas.setFillColor(HexColor("#9e9e9e"))
        canvas.drawCentredString(
            A4[0] / 2, 12 * mm, f"— {canvas.getPageNumber()} —"
        )
        canvas.drawString(20 * mm, 12 * mm, "ARXML Viewer 使用说明书")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="ARXML Viewer 用户使用说明书",
        author="arxml_viewer",
    )
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    print(f"已生成 PDF:\n  {os.path.abspath(out_path)}")


def main(argv: Optional[List[str]] = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    default_md = os.path.join(here, "用户使用说明书.md")
    default_out = os.path.join(here, "ARXML_Viewer_用户使用说明书.pdf")

    ap = argparse.ArgumentParser(description="将使用说明书 Markdown 生成 PDF")
    ap.add_argument(
        "markdown",
        nargs="?",
        default=default_md,
        help="说明书 Markdown 路径",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=default_out,
        help="输出 PDF 路径",
    )
    args = ap.parse_args(argv)
    build_pdf(args.markdown, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
