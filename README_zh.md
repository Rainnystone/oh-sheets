# oh-sheets! 📄✨

[English](README.md) | [中文](README_zh.md)

**oh-sheets!** 是一个开源的元技能扩展（Meta-skill Extension），专为代码智能体（如 Gemini CLI, Claude Code）设计。它旨在解决一个令人头疼的痛点：将非结构化或半结构化数据（如 PDF、图片、Word 文档或排版混乱的 Excel）提取并填入严格且固定格式的 Excel 模板中。

与硬编码脆弱的正则表达式不同，`oh-sheets!` 通过自适应的 **RALPH（反思与修正）** 循环从用户提供的样本中学习。它能自主为您每一个特定的目标模板生成专用的、确定性的 Python 提取脚本和知识规则库。

## 🚀 核心价值与功能

将数据提取到 Excel 时，经常会因为上游文件版式变化而导致整个系统崩溃。`oh-sheets!` 作为智能协调器（Orchestrator）应运而生：
- **零配置学习：** 只需提供一个样本输入和您期望填好的 Excel 模板，它会自己编写提取代码。
- **非破坏性写入：** 采用 `openpyxl` 注入数据，100% 保留您原始模板的样式、公式和宏。
- **视觉兜底与常识校验：** 如果因未预料的排版变化导致代码执行失败，它会优雅地降级到大模型的原生视觉（Vision）能力，并结合语义推理来保障数据完整性。

## 🛠 前置条件与环境

运行 `oh-sheets!` 前，请确保环境具备以下工具。内置的“环境守卫 (Environment Sentinel)”会在每次调用时自动帮您检查。

- **Python 3.x**
- **Python 依赖包：** `docling`, `pdf2image`, `pandas`, `openpyxl`, `Pillow`
- **系统级依赖：** `poppler` (用于 PDF 转图片)
  - macOS: `brew install poppler`
  - Ubuntu/Debian: `sudo apt-get install poppler-utils`

## 📖 如何使用

工作流分为两个阶段：**学习阶段** 和 **日常执行阶段**。

### 1. 交互式学习流程
要教会 `oh-sheets!` 处理一个新模板，只需运行：
```bash
oh-sheets learn
```
智能体将交互式地向您询问：
1. **模板命名：** (例如 `ProjectTemplate`)
2. **空白基础模板：** 目标 Excel 文件的空表。
3. **样本输入与目标输出：** 对应的原始 PDF/图片，以及根据该原始文件完美填好的 Excel 模板。
4. **测试集：** 用于验证所生成代码的第二组文件（输入 + 填好的标答）。

随后，智能体将启动内部的 **RALPH Loop**，不断编写、测试、修改 Python 提取脚本，直到在测试集上达到 100% 的数据精确匹配。

`schema.json` 现在支持通过 `relative_to`、`row_offset`、`col_offset` 记录字段之间的行列关系，这样模板新版本可优先按结构迁移，而不是只靠固定单元格坐标。

### 2. 日常执行
训练完成后，使用统一命令进行日常数据提取：
```bash
oh-sheets extract --template 'ProjectTemplate' --input source_file.pdf --output out.xlsx
```

### 3. 模板管理
列出所有已学习的模板：
```bash
oh-sheets list
```
删除指定模板：
```bash
oh-sheets delete 'ProjectTemplate'
```

## 🧠 深度解析：如何应对五花八门的 Excel 需求

同一个 Excel 模板，可能对应着五种不同版式的上游 PDF？以下是 `oh-sheets!` 应对混乱的策略：

1. **变体隔离 (Variant Isolation)：** 生成的 Python 脚本是与“输入类型和排版变体”强绑定的。如果您传入了 3 种不同格式的 PDF，系统会分别生成 `pdf_variant_1.py`, `pdf_variant_2.py` 等独立脚本，并干净地隔离在 `~/.oh-sheets/templates/<name>/extractors/` 目录中。
2. **约束契约与全局规则：** 对于每一个目标模板，都会生成一个严格的 `schema.json` 作为映射契约。同时，`rules.md` 会记录全局业务逻辑（例如：“数值字段必须按统一精度格式化”）。
3. **多模态降级 (Multi-modal Fallback)：** 如果上游排版突然改变导致脚本报错退出（`Exit 1`），智能体会捕获该错误并顺序尝试其他已知变体脚本。如果全军覆没，它会无缝将文档转为图片，基于 `rules.md` 调用大模型的视觉能力强行提取数据。
4. **持续学习 (Continuous Learning)：** 如果系统被迫使用了视觉兜底，它会在任务完成后主动询问：*“我刚才使用了视觉降级。需要我在后台把这个新版式也学习一下，生成一个新代码吗？”*
