# -*- coding: utf-8 -*-
"""Consistency check report dialog with batch fix + tool_gui script repairs."""
from __future__ import annotations

import os
from typing import List, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..checks import CheckIssue, run_consistency_checks, summarize_issues
from ..external_fix import (
    is_backdoor_action,
    is_script_action,
    resolve_tool_gui_dir,
    run_script_fix,
)
from ..model import ArxmlModel
from ..os_rte import OsRteOverlay


class CheckDialog(QDialog):
    jump_to = Signal(str, str)  # path, kind
    about_to_fix = Signal(int, str)  # count, target primary|peer|mixed
    fixes_applied = Signal(int)  # count
    open_fixed_file = Signal(str)  # path written by external script

    def __init__(
        self,
        model: ArxmlModel,
        parent=None,
        peer_model: ArxmlModel | None = None,
        os_rte: OsRteOverlay | None = None,
    ):
        super().__init__(parent)
        self._model = model
        self._peer_model = peer_model
        self._os_rte = os_rte
        self._all: List[CheckIssue] = []
        self.setWindowTitle("一致性检查")
        self.resize(1040, 560)
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.cmb_sev = QComboBox()
        self.cmb_sev.addItem("全部", "all")
        self.cmb_sev.addItem("仅 Error", "error")
        self.cmb_sev.addItem("Error+Warning", "warning")
        self.cmb_sev.addItem("仅 Info", "info")
        self.cmb_sev.addItem("可修复", "fixable")
        self.cmb_sev.addItem("推荐修复", "recommended")
        self.cmb_sev.addItem("后门修复", "backdoor")
        self.cmb_sev.currentIndexChanged.connect(self._fill)
        btn = QPushButton("重新检查")
        btn.clicked.connect(self._run)
        btn_fix = QPushButton("应用勾选的修复")
        btn_fix.setToolTip(
            "模型内修复立即生效（需 Save）；"
            "脚本修复写出 beta 新文件（不覆盖原件）。"
            "后门项（空壳CS / N:M）需额外确认。"
        )
        btn_fix.clicked.connect(self._apply_fixes)
        btn_all = QPushButton("全选推荐修复")
        btn_all.setToolTip("只勾选非后门的可修复项（去重 / UUID / 坏连接等）")
        btn_all.clicked.connect(self._select_all_recommended)
        bar.addWidget(QLabel("级别:"))
        bar.addWidget(self.cmb_sev)
        bar.addWidget(btn)
        bar.addWidget(btn_all)
        bar.addWidget(btn_fix)
        bar.addStretch(1)
        self.lbl = QLabel("")
        bar.addWidget(self.lbl)
        lay.addLayout(bar)

        tool = resolve_tool_gui_dir()
        self.lbl_tool = QLabel(
            f"scripts: {tool}" if tool else "scripts: 未找到 arxml_viewer/tools"
        )
        self.lbl_tool.setStyleSheet("color:#666;")
        lay.addWidget(self.lbl_tool)

        # Always-visible script actions (not only when table rows are flagged)
        fix_bar = QHBoxLayout()
        fix_bar.addWidget(QLabel("脚本修复:"))
        self.btn_dedup = QPushButton("去重 ADT/IDT/DataMap…")
        self.btn_dedup.setToolTip("推荐：dedup_arxml.py → 写出 beta，不覆盖原文件")
        self.btn_dedup.clicked.connect(lambda: self._run_script_button("script_dedup"))
        self.btn_uuid = QPushButton("修复重复 UUID…")
        self.btn_uuid.setToolTip("推荐：fix_duplicate_uuids.py --fix → 写出 beta")
        self.btn_uuid.clicked.connect(lambda: self._run_script_button("script_fix_uuid"))
        self.btn_empty_cs = QPushButton("后门: 空壳 Constant…")
        self.btn_empty_cs.setToolTip(
            "导出平台问题；后门调用 fix_empty_constants.py 写出 beta"
        )
        self.btn_empty_cs.clicked.connect(
            lambda: self._run_script_button("backdoor_empty_cs", backdoor=True)
        )
        self.btn_nm = QPushButton("后门: N:M / DG_R…")
        self.btn_nm.setToolTip(
            "导出平台问题；后门调用 fix_nm_dgr_cascade.py 写出 beta"
        )
        self.btn_nm.clicked.connect(
            lambda: self._run_script_button("backdoor_nm_dgr", backdoor=True)
        )
        for b in (self.btn_dedup, self.btn_uuid, self.btn_empty_cs, self.btn_nm):
            fix_bar.addWidget(b)
        fix_bar.addStretch(1)
        lay.addLayout(fix_bar)
        self._sync_script_buttons_enabled()

        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(
            ["修复", "Severity", "Category", "Target", "Message", "Path"]
        )
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.cellDoubleClicked.connect(self._on_dbl)
        lay.addWidget(self.tbl, 1)

        tip = QLabel(
            "双击跳转 · 推荐可修复：坏连接 / ADT·IDT·DataMap 去重 / UUID 重复（脚本写出 beta）。"
            "空壳 Constant、N:M/DG_R 属导出平台问题，仅「后门」可用脚本补救，勿当默认流程。"
        )
        tip.setStyleSheet("color:#666;")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self._run()

    def _run(self):
        self._all = run_consistency_checks(
            self._model, peer_model=self._peer_model, os_rte=self._os_rte
        )
        n_fix = sum(1 for i in self._all if i.fix_action)
        n_rec = sum(
            1
            for i in self._all
            if i.fix_action and not is_backdoor_action(i.fix_action)
        )
        n_bd = sum(1 for i in self._all if is_backdoor_action(i.fix_action))
        peer_note = " +对照" if self._peer_model else ""
        os_note = (
            " +OsRTE"
            if self._os_rte and (self._os_rte.tasks or self._os_rte.mappings)
            else ""
        )
        self.lbl.setText(
            summarize_issues(self._all)
            + f"  Fixable={n_fix}(推荐{n_rec}/后门{n_bd}){peer_note}{os_note}"
        )
        self._fill()

    def _visible_rows(self) -> List[CheckIssue]:
        mode = self.cmb_sev.currentData()
        rows = self._all
        if mode == "error":
            rows = [i for i in self._all if i.severity == "error"]
        elif mode == "warning":
            rows = [i for i in self._all if i.severity in ("error", "warning")]
        elif mode == "info":
            rows = [i for i in self._all if i.severity == "info"]
        elif mode == "fixable":
            rows = [i for i in self._all if i.fix_action]
        elif mode == "recommended":
            rows = [
                i
                for i in self._all
                if i.fix_action and not is_backdoor_action(i.fix_action)
            ]
        elif mode == "backdoor":
            rows = [i for i in self._all if is_backdoor_action(i.fix_action)]
        return rows

    def _fill(self):
        rows = self._visible_rows()
        self.tbl.setRowCount(0)
        colors = {
            "error": QColor("#c62828"),
            "warning": QColor("#ef6c00"),
            "info": QColor("#546e7a"),
        }
        for issue in rows:
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            if issue.fix_action:
                chk.setCheckState(Qt.CheckState.Unchecked)
                tip = issue.fix_label or issue.fix_action
                if is_backdoor_action(issue.fix_action):
                    tip = "[后门] " + tip
                chk.setToolTip(tip)
            else:
                chk.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                chk.setText("—")
            chk.setData(Qt.ItemDataRole.UserRole, issue)
            self.tbl.setItem(row, 0, chk)
            target = issue.fix_target or "primary"
            if is_backdoor_action(issue.fix_action):
                target = "后门"
            elif is_script_action(issue.fix_action):
                target = "脚本→beta"
            vals = [
                issue.severity,
                issue.category,
                target,
                issue.message,
                issue.path,
            ]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, issue.path)
                item.setData(Qt.ItemDataRole.UserRole + 1, issue.kind)
                if col == 0:
                    item.setForeground(colors.get(issue.severity, QColor("#333")))
                self.tbl.setItem(row, col + 1, item)
        self.tbl.resizeColumnsToContents()

    def _select_all_recommended(self):
        for row in range(self.tbl.rowCount()):
            item = self.tbl.item(row, 0)
            if not item:
                continue
            issue = item.data(Qt.ItemDataRole.UserRole)
            if (
                isinstance(issue, CheckIssue)
                and issue.fix_action
                and not is_backdoor_action(issue.fix_action)
            ):
                item.setCheckState(Qt.CheckState.Checked)

    def _sync_script_buttons_enabled(self):
        tool_ok = bool(resolve_tool_gui_dir())
        has_file = bool(self._model and self._model.filepath)
        for b in (self.btn_dedup, self.btn_uuid, self.btn_empty_cs, self.btn_nm):
            b.setEnabled(tool_ok and has_file)
        if not tool_ok:
            tip = "未找到 arxml_viewer/tools 下的修复脚本"
            for b in (self.btn_dedup, self.btn_uuid, self.btn_empty_cs, self.btn_nm):
                b.setToolTip(tip)

    def _run_script_button(self, action: str, *, backdoor: bool = False):
        """Always-visible button path for bundled tools/ scripts."""
        self._sync_script_buttons_enabled()
        if not resolve_tool_gui_dir():
            QMessageBox.warning(
                self,
                "脚本修复",
                "未找到 arxml_viewer/tools 下的修复脚本。",
            )
            return
        inp = (self._model.filepath or "") if self._model else ""
        if not inp or not os.path.isfile(inp):
            QMessageBox.warning(self, "脚本修复", "当前没有已保存的磁盘 ARXML 路径。")
            return
        if backdoor:
            ans = QMessageBox.warning(
                self,
                "后门修复确认",
                "此项属于导出平台问题（空壳 Constant / N:M·DG_R）。\n"
                "viewer 仅提供脚本后门：写出 beta 新文件，不覆盖原件。\n\n继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        else:
            ans = QMessageBox.question(
                self,
                "脚本修复",
                f"将对磁盘文件运行脚本（写出 beta，不覆盖原件）：\n{inp}\n\n继续？",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        if self._model.is_dirty():
            warn = QMessageBox.question(
                self,
                "未保存修改",
                "有未保存 pending；脚本基于磁盘原文件，不含 pending。\n仍要继续？",
            )
            if warn != QMessageBox.StandardButton.Yes:
                return
        donors = []
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
            self._sync_script_buttons_enabled()
        if res.ok and res.output_path:
            self.fixes_applied.emit(1)
            ask = QMessageBox.question(
                self,
                "修复完成",
                f"已写出:\n{res.output_path}\n\n是否打开该文件？",
            )
            if ask == QMessageBox.StandardButton.Yes:
                self.open_fixed_file.emit(res.output_path)
            self._run()
            return
        QMessageBox.warning(
            self,
            "脚本修复",
            f"{action} 失败或未产出文件 (rc={res.returncode})。\n\n"
            + ((res.log or "")[-2000:]),
        )

    def _target_model(self, issue: CheckIssue) -> ArxmlModel | None:
        if (issue.fix_target or "primary") == "peer":
            return self._peer_model
        return self._model

    def _selected_issues(self) -> List[CheckIssue]:
        selected: List[CheckIssue] = []
        for row in range(self.tbl.rowCount()):
            item = self.tbl.item(row, 0)
            if not item or item.checkState() != Qt.CheckState.Checked:
                continue
            issue = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(issue, CheckIssue) and issue.fix_action:
                selected.append(issue)
        return selected

    def _apply_fixes(self):
        selected = self._selected_issues()
        if not selected:
            QMessageBox.information(self, "修复", "未勾选任何可修复项。")
            return

        model_fixes = [
            i
            for i in selected
            if i.fix_action in ("delete_connector", "delete_data_mapping")
        ]
        script_actions: Set[str] = {
            i.fix_action
            for i in selected
            if is_script_action(i.fix_action)
        }
        backdoors = {a for a in script_actions if is_backdoor_action(a)}
        recommended_scripts = script_actions - backdoors

        if backdoors:
            ans = QMessageBox.warning(
                self,
                "后门修复确认",
                "勾选了「后门」项（空壳 Constant / N:M·DG_R）。\n\n"
                "这类问题应由导出平台修复，viewer 仅留脚本后门写出 beta 新文件，"
                "不会覆盖原 ARXML，也不应作为默认流程。\n\n继续执行后门脚本？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                script_actions -= backdoors

        if not model_fixes and not script_actions:
            return

        msg_parts = []
        if model_fixes:
            msg_parts.append(f"模型内修复 {len(model_fixes)} 项（需 Save）")
        if recommended_scripts:
            msg_parts.append(
                f"脚本修复 {len(recommended_scripts)} 类（去重/UUID→写出 beta）"
            )
        if script_actions & backdoors:
            msg_parts.append(f"后门脚本 {len(script_actions & backdoors)} 类")
        targets = {(i.fix_target or "primary") for i in model_fixes} or {"primary"}
        target_label = "mixed" if len(targets) > 1 else next(iter(targets))
        ans = QMessageBox.question(
            self,
            "应用修复",
            "将执行：\n- " + "\n- ".join(msg_parts) + f"\n模型目标: {target_label}\n继续？",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        if model_fixes:
            self.about_to_fix.emit(len(model_fixes), target_label)
        applied = 0
        for issue in model_fixes:
            m = self._target_model(issue)
            if not m:
                continue
            if issue.fix_action == "delete_connector":
                m.queue_delete_connector(
                    issue.path,
                    issue.fix_connector_name or issue.path.rsplit("/", 1)[-1],
                    issue.fix_composition,
                    issue.fix_connector_kind or "assembly",
                )
                applied += 1
            elif issue.fix_action == "delete_data_mapping":
                err = m.queue_delete_data_mapping(
                    issue.fix_connector_name or issue.path
                )
                if not err:
                    applied += 1

        written: List[str] = []
        logs: List[str] = []
        if script_actions:
            if self._model.is_dirty():
                warn = QMessageBox.question(
                    self,
                    "未保存修改",
                    "当前文件有未保存的 pending 编辑。\n"
                    "外部脚本基于磁盘上的原文件运行，不会包含这些 pending。\n"
                    "建议先 Save 再修。仍要对磁盘文件跑脚本吗？",
                )
                if warn != QMessageBox.StandardButton.Yes:
                    script_actions = set()
            inp = self._model.filepath or ""
            donors: List[str] = []
            if "backdoor_empty_cs" in script_actions:
                d, _ = QFileDialog.getOpenFileName(
                    self,
                    "可选：选择 Donor ARXML（可取消跳过）",
                    inp,
                    "ARXML (*.arxml);;All (*.*)",
                )
                if d:
                    donors = [d]
            for action in sorted(script_actions):
                res = run_script_fix(
                    action, inp, donor_paths=donors if action == "backdoor_empty_cs" else None
                )
                logs.append(
                    f"=== {action} (rc={res.returncode}) ===\n{res.log[-4000:]}"
                )
                if res.ok and res.output_path:
                    written.append(res.output_path)
                    applied += 1
                elif not res.ok:
                    QMessageBox.warning(
                        self,
                        "脚本修复",
                        f"{action} 失败/未产出文件。\n\n"
                        + (res.log[-1500:] if res.log else res.log),
                    )

        self.fixes_applied.emit(applied)
        if written:
            paths = "\n".join(written)
            ask = QMessageBox.question(
                self,
                "修复完成",
                f"已排队模型修复 / 脚本写出：\n{paths}\n\n是否打开最新写出的文件？",
            )
            if ask == QMessageBox.StandardButton.Yes:
                self.open_fixed_file.emit(written[-1])
        else:
            QMessageBox.information(
                self,
                "修复",
                f"已处理 {applied} 处。"
                + ("（脚本未写出新文件时请查看日志）" if script_actions else ""),
            )
        self._run()

    def _on_dbl(self, row: int, col: int):
        if col == 0:
            return
        item = self.tbl.item(row, 1)
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole) or ""
        kind = item.data(Qt.ItemDataRole.UserRole + 1) or ""
        if path and kind:
            self.jump_to.emit(path, kind)
