# oh-sheets! 📄✨

[English](README.md) | [中文](README_zh.md)

**oh-sheets!** 是一个开源的元技能扩展（Meta-skill Extension），专为代码智能体（如 Gemini CLI, Claude Code）设计。它旨在解决一个令人头疼的痛点：将非结构化或半结构化数据（如 PDF、图片、Word 文档或排版混乱的 Excel）提取并填入严格且固定格式的 Excel 模板中。

与硬编码脆弱的正则表达式或脚本不同，`oh-sheets! v2` 引入了动态的**语义参考库 (Semantic Reference Bank)**。它通过自适应的 **RALPH（反思与修正）** 循环从用户提供的样本中学习，自主构建包含锚点、规则和成功模式的结构化知识图谱，从而引导“大模型优先 (LLM-first)”的数据提取。

## 🚀 核心价值与功能

将数据提取到 Excel 时，经常会因为上游文件版式变化而导致整个系统崩溃。`oh-sheets!` 作为智能协调器（Orchestrator）应运而生：
- **零配置学习：** 只需提供一个样本输入和您期望填好的 Excel 模板，它能学习语义结构并自主生成提取规则。
- **大模型优先执行：** 使用携带丰富上下文负载（few-shot 规则、空间锚点、公式约束）的大模型进行语义提取，对排版变化具有极高的适应性。
- **非破坏性写入：** 采用 `openpyxl` 注入数据，100% 保留您原始模板的样式、公式和宏。
- **规则进化：** 系统会持续学习。成功的提取会提升规则置信度，失败则会惩罚，长期不用的规则会随时间自然衰减。

## 🛠 前置条件与环境

运行 `oh-sheets!` 前，请确保环境具备以下工具。内置的“环境守卫 (Environment Sentinel)”会在每次调用时自动帮您检查。

- **Python 3.x**
- **Python 依赖包：** `docling`, `pdf2image`, `pandas`, `openpyxl`, `Pillow`, `google-genai` (或其他等效 SDK)
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
4. **测试集：** 用于验证所学规则的第二组文件（输入 + 填好的标答）。

随后，智能体将启动内部的 **RALPH Loop**，识别空间锚点，起草提取规则，进行测试，并不断完善其知识图谱，直到在测试集上达到 100% 的数据精确匹配。

`schema.json` 作为严格的契约，定义字段类型并自动提取公式约束（例如保护 `=SUM(A1:A5)` 单元格），从而确保大模型绝对不会覆盖您的计算公式。

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

## 🧠 深度解析：语义参考库 v2 (Semantic Reference Bank)

同一个 Excel 模板，可能对应着五种不同版式的上游 PDF？以下是 `oh-sheets! v2` 应对混乱的策略：

1. **结构化记忆：** 知识不再简单地存放在 `rules.md` 中，而是被拆分为明确的组件，存放在 `~/.oh-sheets/templates/<name>/reference_bank/` 下：
   - `anchors.json`：空间和视觉定位器（例如：“供应商名称总是在 'Vendor:' 字符串的下方”）。
   - `rules.jsonl`：将条件映射到提取策略的结构化断言规则。
   - `success_patterns.jsonl`：已知成功的文档版式 MD5 签名，用于实现毫秒级快速匹配。
   - `knowledge_graph.json`：追踪不同规则和锚点之间的关系与依赖。
2. **动态进化：** 当 `oh-sheets!` 成功提取一份文档时，`learning_orchestrator` 会提升所用规则的 `confidence`（置信度）得分。如果校验失败（如缺少必填字段），规则将受到惩罚。得分低于置信度阈值 (0.3) 的规则将被自动归档，以防过时逻辑导致系统臃肿。
3. **校验与反馈闭环：** 编排器在向 Excel 写入数据前，会严格根据 `schema.json` 契约校验 LLM 的输出。如果数据缺失或格式错误，失败将被记录到 `execution_log.jsonl` 中，并重新输入到 RALPH 循环中，触发即时的反思和自我修复。
