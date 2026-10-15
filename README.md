# AutoSAR-SW-Developer
# ARXML Composition / Port Viewer

浏览与有限编辑 AUTOSAR ARXML：Composition 结构图、SR/CS 链路、Delegation 嵌套全链路、RTE IB、System Data Mapping、一致性检查、AUTOSAR 规范校验、按 SWC 导出与写回。

## 快速开始

```bash
python -m arxml_viewer
# 或
python arxml_viewer/run.py

# 冒烟回归
python -m arxml_viewer.smoke_test
```

夹具：`testdata/mini_rte.arxml`、`mini_sysmap.arxml`、`mini_nested_del.arxml`、`mini_cs.arxml`。

## 规范校验（唯一完整引擎）

- `arxml_viewer/arxml_schema_validator.py` + `AUTOSAR_MMOD_XMLSchema/AUTOSAR_00046.xsd`
- 含 XSD / 语义 / Vector 40329 N:M；**File → Validate AUTOSAR…**
- **Validate with pending edits…** / **Validate current Composition/SWC…**（结果按路径过滤）
- 打开后延后校验；引擎阶段可取消；状态栏显示校验进度与文件规模
- 对话框：过滤 / 双击跳转 / TXT·PDF；PDF：`pip install -e ".[pdf]"` 或 `requirements-pdf.txt`
- XSD 可用 `ARXML_XSD`；大文件建议 **Limit ports**

## 链路 / 对端

- 跳数表「方向」列：`P→R` / `同向P`
- 属性栏：本侧 · P↔R · 委托 · 链路端 + **跨文件半链**
- 右键 / 对端列表 / 跳转 P↔R；对照文件 Open peer
- **Help → Export P↔R orphan report CSV…**

## 按 SWC 导出

| 入口 | 用途 |
|------|------|
| 左树 / 图 **右键 SWC** | 导出这一个（含依赖；未解析 REF 写 `.missing_refs.txt`） |
| File → Export current（Ctrl+Shift+E） | 同上 |
| File → Export SWC(s) 多选到目录 | 批量 |

## 连线模式

- 拖 Port→Port；合法目标绿虚线；**成功后保持连线模式**
- 仅结构图；Shift+拖亦可

## 编辑 / 写回

- Assembly / Delegation / Mapping / IB / Port / Signal…
- **Edit → Undo / Redo**（轻量分 scope 快照）；**Undo/Redo peer** 与主文件分栈
- 一致性修复可落到对照文件（Target=peer，需 Save peer）
- 批量委托：**预览表勾选**后再创建
- **Save peer** / **Swap: open peer as primary**
- 导出：SWC / **Composition slice** / **SYSTEM·Mapping slice**；可合并 peer 闭包
- **Help → Save project config** → `.arxml_viewer.json`

## 测试

```bash
python -m arxml_viewer.smoke_test
python -m arxml_viewer.tests.test_roadmap
```

## 帮助

**Help → Quick help / 速查…**（F1）

完整说明书（Markdown）与 PDF：

```bash
# 源文
arxml_viewer/docs/用户使用说明书.md

# 生成 PDF（需 reportlab）
python -m arxml_viewer.docs.build_manual_pdf
# 输出: arxml_viewer/docs/ARXML_Viewer_用户使用说明书.pdf
```

## OS/RTE Mapping（轻量侧车）

与主 ARXML 同目录的 `<stem>.os_rte.json` 可配置 OsTask 与 Runnable→Task（**非 ECUC**）。  
菜单：`Tools → OS/RTE Mapping…`、CSV 导入/导出、`Generate RTE skeleton (C)…`（最小骨架）。左树有 `OS Tasks (overlay)`。

## 对端图

Application 口自动抬升到顶层 P/R；1:N 嵌套链路并排；默认展开 1 条对端，点占位展开更多。Find 关键字 `1n` 可列一对多 P-Port。

## 明确不做

ECUC / DaVinci 工程级配置、**完整** RTE/COM 代码生成、与 Vector 工程双向同步。
