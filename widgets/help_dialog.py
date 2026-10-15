# -*- coding: utf-8 -*-
"""Built-in quick help for ARXML Viewer."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QTextBrowser, QVBoxLayout


HELP_HTML = """
<h2>ARXML Viewer 速查</h2>
<h3>连接关系</h3>
<ul>
<li><b>Assembly（蓝实线）</b>：P↔R，真正的收发对端</li>
<li><b>Delegation（紫虚线）</b>：同向透传（外↔内），不是收发翻转</li>
<li><b>链路另一端</b>：全链路 App↔Outer 连通端，常与对端同向</li>
</ul>
<h3>对端怎么看</h3>
<ol>
<li>选中 Port → 属性栏「①本侧 ②P↔R ③委托 ④链路端」</li>
<li>右键 Port /「对端列表」/「跳转 P↔R 对端」</li>
<li>对照文件：File → Open peer ARXML（ZCUD↔ZCUP）</li>
</ol>
<h3>树结构 · Application SWC</h3>
<ul>
<li>Application SWCs 下：Port 与 <b>*_IB（Internal Behavior）</b> 同级挂在对应 SWC 下</li>
<li>无 IB 的 Application SWC 树上标红，规范校验报 error</li>
</ul>
<h3>导出 SWC</h3>
<ul>
<li>左树/图 <b>右键 Application SWC</b> → 导出含依赖的独立 ARXML</li>
<li>File → 多选到目录 / 单个文件（Ctrl+Shift+E）</li>
</ul>
<h3>校验</h3>
<ul>
<li>Validate AUTOSAR / pending / current Composition·SWC；Cancel 可中断阶段；进度在状态栏</li>
<li>对话框：过滤 / 双击跳转 / TXT·PDF。Consistency check 与规范校验互补</li>
</ul>
<h3>Undo / 对照</h3>
<ul>
<li>主文件 Undo/Redo（分 scope）；对照 Undo peer / Redo peer 分栈</li>
<li>一致性修复 Target=peer 写对照；跨文件连线不支持（仅主 Composition）</li>
</ul>
<h3>导出切片</h3>
<ul>
<li>SWC / Composition slice / SYSTEM·Mapping slice；可合并对照 REF</li>
</ul>
<h3>连线模式</h3>
<ul>
<li>勾选后拖 Port→Port；合法目标绿虚线吸附；成功后保持连线模式</li>
<li>也可 Shift+拖；结构图中操作</li>
</ul>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("帮助 / 速查")
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setHtml(HELP_HTML)
        lay.addWidget(browser, 1)
        btn = QPushButton("关闭")
        btn.clicked.connect(self.accept)
        lay.addWidget(btn)
