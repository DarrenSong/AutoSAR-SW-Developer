# -*- coding: utf-8 -*-
"""Dialog showing AUTOSAR spec validation results."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from PySide6.QtCore import QUrl

from ..external_fix import resolve_tool_gui_dir, run_script_fix
from ..spec_validate import (
    ISSUE_CATEGORIES,
    SpecValidateResult,
    classify_issue,
    resolve_jump_target,
)


class SpecValidateDialog(QDialog):
    """Validation result browser with filter, jump, script fixes, and TXT/PDF export."""

    jump_to = Signal(str, str)  # path, kind
    jump_source = Signal(str, int)  # filepath, line
    open_fixed_file = Signal(str)  # beta file from tool_gui script

    def __init__(self, result: SpecValidateResult, parent=None, model=None):
        super().__init__(parent)
        self._result = result
        self._model = model
        self._rows: List[Tuple[str, str, str]] = []  # sev, category, msg
        self.setWindowTitle("AUTOSAR 规范校验")
        self.resize(1000, 600)
        lay = QVBoxLayout(self)

        status = "通过" if result.ok else "存在错误"
        color = "#2e7d32" if result.ok else "#c62828"
        head = QLabel(
            f"<b style='color:{color}'>{status}</b>  ·  {result.summary}<br>"
            f"<span style='color:#666'>{result.filepath}</span>"
        )
        head.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(head)

        tip = QLabel(
            "完整校验（XSD / 语义 / N:M）。双击行可跳转路径或源文件行。"
            "下方「脚本修复」使用本仓库 tools/（写出 beta，不覆盖原文件）；"
            "空壳 Constant / N:M 为后门。"
        )
        tip.setStyleSheet("color:#666;")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        tool = resolve_tool_gui_dir()
        self.lbl_tool = QLabel(
            f"scripts: {tool}" if tool else "scripts: 未找到 arxml_viewer/tools"
        )
        self.lbl_tool.setStyleSheet("color:#666;")
        lay.addWidget(self.lbl_tool)

        fix_bar = QHBoxLayout()
        fix_bar.addWidget(QLabel("脚本修复:"))
        self.btn_dedup = QPushButton("去重 ADT/IDT/DataMap…")
        self.btn_dedup.setToolTip("推荐：dedup_arxml.py → beta")
        self.btn_dedup.clicked.connect(lambda: self._run_script("script_dedup"))
        self.btn_uuid = QPushButton("修复重复 UUID…")
        self.btn_uuid.setToolTip("推荐：fix_duplicate_uuids.py --fix → beta")
        self.btn_uuid.clicked.connect(lambda: self._run_script("script_fix_uuid"))
        self.btn_empty_cs = QPushButton("后门: 空壳 Constant…")
        self.btn_empty_cs.setToolTip(
            "导出平台问题；fix_empty_constants.py → beta（非默认流程）"
        )
        self.btn_empty_cs.clicked.connect(
            lambda: self._run_script("backdoor_empty_cs", backdoor=True)
        )
        self.btn_nm = QPushButton("后门: N:M / DG_R…")
        self.btn_nm.setToolTip(
            "导出平台问题；fix_nm_dgr_cascade.py → beta（非默认流程）"
        )
        self.btn_nm.clicked.connect(
            lambda: self._run_script("backdoor_nm_dgr", backdoor=True)
        )
        for b in (self.btn_dedup, self.btn_uuid, self.btn_empty_cs, self.btn_nm):
            fix_bar.addWidget(b)
        fix_bar.addStretch(1)
        lay.addLayout(fix_bar)
        self._sync_fix_buttons()

        filt = QHBoxLayout()
        filt.addWidget(QLabel("级别:"))
        self.cmb_sev = QComboBox()
        self.cmb_sev.addItem("全部", "all")
        self.cmb_sev.addItem("仅 Error", "error")
        self.cmb_sev.addItem("Error+Warning", "warning")
        self.cmb_sev.addItem("仅 Info", "info")
        self.cmb_sev.currentIndexChanged.connect(self._fill)
        filt.addWidget(self.cmb_sev)
        filt.addWidget(QLabel("类别:"))
        self.cmb_cat = QComboBox()
        for c in ISSUE_CATEGORIES:
            self.cmb_cat.addItem(c, c)
        self.cmb_cat.currentIndexChanged.connect(self._fill)
        filt.addWidget(self.cmb_cat)
        filt.addWidget(QLabel("关键字:"))
        self.ed_kw = QLineEdit()
        self.ed_kw.setPlaceholderText("过滤消息…")
        self.ed_kw.textChanged.connect(self._fill)
        filt.addWidget(self.ed_kw, 1)
        self.lbl_count = QLabel("")
        filt.addWidget(self.lbl_count)
        lay.addLayout(filt)

        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["级别", "类别", "消息"])
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.setWordWrap(True)
        self.tbl.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.tbl.cellDoubleClicked.connect(self._on_dbl)
        lay.addWidget(self.tbl, 1)

        # Build full row list (errors never truncated)
        for m in result.errors:
            self._rows.append(("error", classify_issue(m), m))
        for m in result.warnings:
            self._rows.append(("warning", classify_issue(m), m))
        for m in result.infos:
            self._rows.append(("info", classify_issue(m), m))
        self._fill()

        bar = QHBoxLayout()
        btn_save = QPushButton("保存结果…")
        btn_save.setToolTip("导出校验报告为 TXT 或 PDF")
        btn_save.clicked.connect(self._save_report)
        bar.addWidget(btn_save)
        btn_jump = QPushButton("跳转到选中项")
        btn_jump.clicked.connect(self._jump_selected)
        bar.addWidget(btn_jump)
        bar.addStretch(1)
        btn = QPushButton("关闭")
        btn.clicked.connect(self.accept)
        bar.addWidget(btn)
        lay.addLayout(bar)

    def _visible(self) -> List[Tuple[str, str, str]]:
        sev = self.cmb_sev.currentData()
        cat = self.cmb_cat.currentData()
        kw = (self.ed_kw.text() or "").strip().lower()
        rows = self._rows
        if sev == "error":
            rows = [r for r in rows if r[0] == "error"]
        elif sev == "warning":
            rows = [r for r in rows if r[0] in ("error", "warning")]
        elif sev == "info":
            rows = [r for r in rows if r[0] == "info"]
        if cat and cat != "全部":
            rows = [r for r in rows if r[1] == cat]
        if kw:
            rows = [r for r in rows if kw in r[2].lower()]
        return rows

    def _fill(self):
        rows = self._visible()
        self.lbl_count.setText(f"{len(rows)} / {len(self._rows)}")
        self.tbl.setRowCount(len(rows))
        colors = {
            "error": QColor("#ffebee"),
            "warning": QColor("#fff8e1"),
            "info": QColor("#e3f2fd"),
        }
        for i, (sev, cat, msg) in enumerate(rows):
            a = QTableWidgetItem(sev)
            b = QTableWidgetItem(cat)
            c = QTableWidgetItem(msg)
            for it in (a, b, c):
                it.setTextAlignment(
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
                )
                it.setData(Qt.ItemDataRole.UserRole, msg)
                bg = colors.get(sev)
                if bg:
                    it.setBackground(bg)
            self.tbl.setItem(i, 0, a)
            self.tbl.setItem(i, 1, b)
            self.tbl.setItem(i, 2, c)
        self.tbl.resizeColumnsToContents()
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.resizeRowsToContents()

    def _msg_at_row(self, row: int) -> str:
        item = self.tbl.item(row, 2) or self.tbl.item(row, 0)
        if not item:
            return ""
        return item.data(Qt.ItemDataRole.UserRole) or item.text() or ""

    def _jump_message(self, msg: str):
        if not msg:
            return
        path, kind, line = resolve_jump_target(msg, self._model)
        if path:
            self.jump_to.emit(path, kind or "path")
        if line is not None and self._result.filepath:
            self.jump_source.emit(self._result.filepath, line)
        if not path and line is None:
            QMessageBox.information(
                self, "跳转", "该消息无可解析路径或行号。可复制消息后手工查找。"
            )

    def _on_dbl(self, row: int, _col: int):
        self._jump_message(self._msg_at_row(row))

    def _jump_selected(self):
        rows = self.tbl.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "跳转", "请先选中一行。")
            return
        self._jump_message(self._msg_at_row(rows[0].row()))

    def _input_path(self) -> str:
        if self._result and self._result.filepath:
            return self._result.filepath
        if self._model and getattr(self._model, "filepath", ""):
            return self._model.filepath or ""
        return ""

    def _sync_fix_buttons(self):
        ok = bool(resolve_tool_gui_dir()) and bool(self._input_path())
        for b in (self.btn_dedup, self.btn_uuid, self.btn_empty_cs, self.btn_nm):
            b.setEnabled(ok)

    def _run_script(self, action: str, *, backdoor: bool = False):
        self._sync_fix_buttons()
        if not resolve_tool_gui_dir():
            QMessageBox.warning(
                self,
                "脚本修复",
                "未找到 arxml_viewer/tools 下的修复脚本。",
            )
            return
        inp = self._input_path()
        if not inp or not os.path.isfile(inp):
            QMessageBox.warning(self, "脚本修复", "无有效磁盘 ARXML 路径。")
            return
        if backdoor:
            ans = QMessageBox.warning(
                self,
                "后门修复确认",
                "空壳 Constant / N:M·DG_R 宜由导出平台修复。\n"
                "此处仅后门脚本写出 beta，不覆盖原文件。\n\n继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        else:
            ans = QMessageBox.question(
                self,
                "脚本修复",
                f"对磁盘文件运行脚本（写出 beta）：\n{inp}\n\n继续？",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        donors: List[str] = []
        if action == "backdoor_empty_cs":
            d, _ = QFileDialog.getOpenFileName(
                self,
                "可选：Donor ARXML（可取消跳过）",
                inp,
                "ARXML (*.arxml);;All (*.*)",
            )
            if d:
                donors = [d]
        for b in (self.btn_dedup, self.btn_uuid, self.btn_empty_cs, self.btn_nm):
            b.setEnabled(False)
        try:
            res = run_script_fix(action, inp, donor_paths=donors or None)
        finally:
            self._sync_fix_buttons()
        if res.ok and res.output_path:
            ask = QMessageBox.question(
                self,
                "修复完成",
                f"已写出:\n{res.output_path}\n\n是否打开该文件？",
            )
            if ask == QMessageBox.StandardButton.Yes:
                self.open_fixed_file.emit(res.output_path)
            return
        QMessageBox.warning(
            self,
            "脚本修复",
            f"{action} 失败或未产出文件 (rc={res.returncode})。\n\n"
            + ((res.log or "")[-2000:]),
        )

    def _default_report_path(self, ext: str) -> str:
        base = os.path.splitext(os.path.basename(self._result.filepath or "arxml"))[0]
        safe = (
            "".join(c if c.isalnum() or c in "-_" else "_" for c in base)
            or "validation"
        )
        folder = os.path.dirname(self._result.filepath) if self._result.filepath else ""
        return os.path.join(folder, f"{safe}_validation_report.{ext}")

    def _open_containing_folder(self, path: str):
        folder = os.path.dirname(os.path.abspath(path))
        if not folder or not os.path.isdir(folder):
            return
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _save_report(self):
        path, selected = QFileDialog.getSaveFileName(
            self,
            "保存校验结果",
            self._default_report_path("txt"),
            "文本报告 (*.txt);;PDF 报告 (*.pdf)",
        )
        if not path:
            return
        want_pdf = "PDF" in selected or path.lower().endswith(".pdf")
        if want_pdf:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
        else:
            if not path.lower().endswith(".txt"):
                path += ".txt"
        try:
            if want_pdf:
                self._result.export_pdf(path)
            else:
                self._result.export_txt(path)
        except RuntimeError as e:
            QMessageBox.warning(self, "保存校验结果", str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, "保存校验结果", f"保存失败: {e}")
            return
        ans = QMessageBox.question(
            self,
            "保存校验结果",
            f"已保存:\n{path}\n\n是否打开所在文件夹？",
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._open_containing_folder(path)
