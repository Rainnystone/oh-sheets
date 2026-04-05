# oh-sheets! Reference Bank v2 设计规范

## 0. 目标

将 oh-sheets! 从"坐标映射"升级为"语义记忆系统"，核心改进：

1. **Reference Bank** — 结构化的场景参考库（锚点 + 规则 + 成功模式）
2. **LLM 优先执行** — 规则作为 few-shot 注入 prompt，充分利用 LLM 自然语义和多模态能力
3. **规则进化机制** — confidence 更新、衰减、归档，知识持续进化
4. **公式理解** — 识别 Excel 公式关系，不覆盖公式单元格，利用公式验证
5. **结构化组织** — scripts 按职责分层，数据文件按模板隔离

## 1. 问题诊断

### 1.1 当前问题

| 问题 | 表现 |
|------|------|
| 规则质量差 | 基于坐标映射而非语义理解，无法利用 LLM 能力 |
| 变体识别弱 | 新 PDF/Excel 格式无法正确路由 |
| 成功经验丢失 | 没有机制沉淀和复用成功案例 |
| 记忆只记失败 | execution_log 只记录错误，成功经验无法复用 |
| 缺乏反馈闭环 | 没有信号机制告诉系统"这条规则有用" |

### 1.2 业界参考

| 项目 | 核心洞察 |
|------|----------|
| **elfmem** | 知识必须"活"——会强化、会衰减、会关联 |
| **Sensible.so** | 字段定位 = 锚点 + 方法，锚点是"死记硬背"的标识符 |
| **Meta-Policy Reflexion** | 规则应该是 predicate 风格的结构化断言，带 confidence 和 support |

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          oh-sheets! v2 架构                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────────────────────────────────────┐    │
│  │   Input     │    │              Reference Bank                 │    │
│  │ PDF/Excel/  │    │  ┌──────────┐ ┌──────────┐ ┌─────────────┐ │    │
│  │ Word/MD     │    │  │ anchors  │ │  rules   │ │  success_   │ │    │
│  └──────┬──────┘    │  │  .json   │ │  .jsonl  │ │ patterns.jsonl│    │
│         │           │  └──────────┘ └──────────┘ └─────────────┘ │    │
│         ▼           │                    │                       │    │
│  ┌─────────────┐    │                    ▼                       │    │
│  │  Signature  │    │           ┌──────────────┐                │    │
│  │   Guard     │    │           │ knowledge_   │                │    │
│  └──────┬──────┘    │           │ graph.json   │                │    │
│         │           │           └──────────────┘                │    │
│         ▼           │                                           │    │
│  ┌─────────────────────────────────────────────────────────────┐ │    │
│  │                     Orchestrator                             │ │    │
│  │  ┌───────────┐   ┌───────────┐   ┌───────────┐              │ │    │
│  │  │  Retrieve │ → │   Build   │ → │   LLM     │              │ │    │
│  │  │  Context  │   │   Prompt  │   │  Execute  │              │ │    │
│  │  └───────────┘   └───────────┘   └─────┬─────┘              │ │    │
│  │                                         │                    │ │    │
│  │                                         ▼                    │ │    │
│  │                                  ┌───────────┐              │ │    │
│  │                                  │  Validate │              │ │    │
│  │                                  └─────┬─────┘              │ │    │
│  └────────────────────────────────────────┼────────────────────┘ │    │
│                                           │                      │    │
│         ┌─────────────────────────────────┼──────────────────────┘    │
│         │                                 │                            │
│         ▼                                 ▼                            │
│  ┌─────────────┐                   ┌─────────────┐                     │
│  │   Output    │                   │  Feedback   │                     │
│  │  (Excel)    │                   │  & Evolve   │                     │
│  └─────────────┘                   └──────┬──────┘                     │
│                                           │                            │
│                                           ▼                            │
│                                    ┌─────────────┐                     │
│                                    │ Update Bank │                     │
│                                    └─────────────┘                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心流程

1. **签名守卫** — 模板签名比对，决定路由（执行/学习/迁移）
2. **上下文检索** — 从 Reference Bank 检索相关 anchors + rules + success_patterns
3. **Prompt 构建** — 将规则作为 few-shot 注入 LLM prompt
4. **LLM 执行** — 调用 LLM（带视觉能力）执行提取
5. **验证** — 结果校验，缺失/错误字段检测
6. **反馈进化** — 记录 outcome，更新规则置信度

## 3. 数据结构设计

### 3.1 目录结构

```
~/.oh-sheets/templates/<template-name>/
├── template.xlsx                    # 空白目标模板
├── schema.json                      # 字段映射契约
├── reference_bank/                  # 场景参考库
│   ├── anchors.json                 # 锚点字典
│   ├── rules.jsonl                  # 规则库
│   ├── success_patterns.jsonl       # 成功模式
│   └── knowledge_graph.json         # 知识图谱
├── extractors/                      # 确定性脚本（备选）
│   └── *.py
└── memory/                          # 执行记忆
    ├── execution_log.jsonl
    ├── failure_clusters.json
    └── summary_rules.json
```

### 3.2 anchors.json — 锚点字典

```json
{
  "schema_version": "1.0",
  "template_signature": "abc123...",
  "anchors": {
    "field_label": {
      "type": "text_match",
      "patterns": [],
      "case_sensitive": false,
      "role": "label",
      "description": ""
    },
    "value_pattern": {
      "type": "regex",
      "pattern": "",
      "role": "value_matcher",
      "description": ""
    },
    "section_start_marker": {
      "type": "spatial",
      "relative_to": null,
      "offset": {"row": 0, "col": 0},
      "role": "section_start",
      "description": ""
    },
    "visual_anchor": {
      "type": "visual",
      "features": [],
      "role": "visual_locator",
      "description": ""
    }
  }
}
```

**锚点类型：**

| type | 用途 |
|------|------|
| `text_match` | 文本标签匹配（字段名、表头、区块标题） |
| `regex` | 值模式匹配（日期、金额、编号格式） |
| `spatial` | 空间相对定位（"某锚点下方第N行"） |
| `visual` | 视觉特征定位（加粗、边框、背景色） |

**角色枚举：**

| role | 含义 |
|------|------|
| `label` | 字段标签/表头 |
| `value_matcher` | 值模式识别器 |
| `section_start` | 区块起始边界 |
| `section_end` | 区块结束边界 |
| `table_start` | 表格起始位置 |
| `visual_locator` | 视觉定位参考点 |

### 3.3 rules.jsonl — 规则库

```jsonl
{"id":"R001","when":{"input_type":"pdf","trigger":"field_extraction"},"condition":{"field":"{field_name}","context":"..."},"then":{"action":"extract_after_anchor","anchor":"...","method":"semantic_extract","prompt":"..."},"confidence":0.92,"support":5}
{"id":"R002","when":{"input_type":"excel","trigger":"field_extraction"},"condition":{"field":"{field_name}","context":"..."},"then":{"action":"extract_by_header","method":"find_column_by_header","headers":[],"fallback":"..."},"confidence":0.88,"support":3}
{"id":"R003","when":{"error_type":"missing_fields"},"condition":{"missing":["{field_name}"]},"then":{"action":"try_patterns","patterns":["..."]},"confidence":0.85,"support":4}
```

**规则结构：** `WHEN + CONDITION → THEN`，带 `confidence` 和 `support`

### 3.4 success_patterns.jsonl — 成功模式

```jsonl
{"pattern_id":"P001","input_signature":"...","input_type":"pdf","fields_extracted":[],"accuracy":1.0,"rules_used":[],"anchors_matched":[],"created_at":"..."}
```

### 3.5 knowledge_graph.json — 知识图谱

```json
{
  "schema_version": "1.0",
  "edges": [
    {"from": "R001", "to": "R003", "relation": "often_follows", "weight": 0.8},
    {"from": "R001", "to": "anchor_id", "relation": "uses_anchor", "weight": 1.0}
  ]
}
```

### 3.6 schema.json 扩展

```json
{
  "meta": {
    "signature": "abc123...",
    "version": "2.0"
  },
  "fields": {
    "Field_A": {"cell": "B2", "type": "string", "required": true},
    "Field_B": {"cell": "B3", "type": "number"}
  },
  "formula_constraints": [
    {"cell": "D5", "formula": "=SUM(D2:D4)", "depends_on": ["D2", "D3", "D4"], "description": "金额合计"}
  ]
}
```

## 4. 核心流程详解

### 4.1 学习流程（RALPH Loop v2）

```
输入：Sample Input (PDF/Excel/Word/MD) + Target Excel

Phase 1: ANALYZE
• LLM 分析样本输入，提取字段区域、格式特征、视觉特征
• 生成 anchors.json（锚点字典）
• 生成 schema.json（字段映射）
• 识别 Excel 公式关系，生成 formula_constraints

Phase 2: DRAFT
• 基于锚点和样本，生成初始规则 rules.jsonl
• 构建知识图谱 knowledge_graph.json

Phase 3: TEST
• 检索相关规则 + 锚点
• 构建 LLM prompt（规则作为 few-shot）
• 执行提取 → 生成 JSON
• 写入 Excel → data_diff 验证

        ┌─────────┴─────────┐
        │   验证通过？       │
        └─────────┬─────────┘
         是 ↓           │ 否

Phase 4: COMMIT      Phase 5: REFLECT
• 记录 success_      • 分析失败原因
  patterns.jsonl     • 生成/修正规则
• 规则 confidence ↑  • 更新锚点
• 输出完成           • 返回 Phase 3 重试
                     • 最多 5 轮
```

### 4.2 执行流程（Extract Flow）

```
输入：Input File + Template Name

Step 1: SIGNATURE CHECK
• 计算输入文件签名
• 比对 success_patterns 中的 input_signature
• 决策：直接执行 / 检索相似模式 / 触发学习

Step 2: RETRIEVE CONTEXT
• 检索匹配的 success_patterns (top_k=3)
• 检索相关规则（按 input_type + trigger 过滤）
• 检索相关锚点
• 知识图谱扩展：激活关联规则

Step 3: BUILD PROMPT
• 系统提示：角色 + 任务定义
• 锚点提示：关键定位参考
• 规则 few-shot：相关规则作为示例
• 成功案例：匹配的 success_patterns
• 目标 schema：需要提取的字段列表
• 公式约束：需要保护的公式单元格

Step 4: LLM EXECUTE
• 调用 LLM（支持视觉输入）
• 输出结构化 JSON
• 多模态：图片/PDF 页面作为视觉输入

Step 5: VALIDATE
• 检查必填字段是否完整
• 检查字段类型/格式
• 检查约束条件（如 schema 中定义）
• 检查公式单元格未被覆盖

Step 6: WRITE & FEEDBACK
• 写入 Excel（非破坏性）
• 记录执行结果到 memory/execution_log.jsonl
• 更新规则 confidence（成功 +0.02，失败 -0.05）
• 若成功：记录 success_pattern
```

### 4.3 规则进化机制

```python
def update_rule_confidence(rule_id: str, outcome: float):
    """
    outcome: 0.0 (失败) → 1.0 (完美)
    """
    if outcome >= 0.8:
        # 成功：confidence 上升，support +1
        rule.confidence = min(1.0, rule.confidence + 0.02)
        rule.support += 1
    elif outcome <= 0.3:
        # 失败：confidence 下降
        rule.confidence = max(0.0, rule.confidence - 0.05)
        if rule.confidence < 0.3:
            # 归档低质量规则
            archive_rule(rule_id)

def decay_rules(template_dir: str, days: int = 30):
    """
    长期不用的规则自然衰减
    """
    for rule in load_rules(template_dir):
        days_since_use = (now - rule.last_used).days
        if days_since_use > days:
            decay_factor = 0.99 ** (days_since_use - days)
            rule.confidence *= decay_factor
```

## 5. Prompt 模板设计

### 5.1 系统提示

```
你是 oh-sheets! 数据提取专家。你的任务是从输入文档中提取结构化数据，
并填入目标 Excel 模板。

## 你的能力
1. 理解 PDF/Excel/Word/Markdown 等多种输入格式
2. 利用视觉能力定位关键字段区域
3. 根据锚点和规则快速定位数据
4. 理解 Excel 公式关系，避免覆盖公式单元格

## 输出要求
- 输出 JSON 格式，严格匹配 schema 定义的字段
- 必填字段不可缺失
- 数值字段保持原始精度
- 日期字段统一格式：YYYY-MM-DD
```

### 5.2 上下文提示模板

```
## 目标模板签名
{template_signature}

## 字段定义
{schema_fields}

## 公式约束
{formula_constraints}
说明：以下单元格包含公式，请勿填充，但可用于验证：
- {cell}: {formula_description}

## 锚点参考
{anchors}

## 相关规则
{rules}

## 成功案例参考
{success_patterns}

## 输入文档
{input_content}
```

### 5.3 规则 Few-Shot 格式

```
## 提取规则（按置信度排序）

规则 {rule_id} [置信度: {confidence}, 成功次数: {support}]:
- 触发条件: 提取 {field_name} 字段时
- 操作: {action_description}
- 示例: "{input_example}" → "{output_example}"
```

## 6. 错误处理与边界情况

### 6.1 错误分类

| 错误类型 | 触发条件 | 处理策略 |
|----------|----------|----------|
| `signature_mismatch` | 输入签名与所有 success_patterns 不匹配 | 进入学习流程 |
| `missing_required_field` | 必填字段提取失败 | 检索 repair 规则，重试最多 3 次 |
| `validation_failed` | 字段格式/类型校验失败 | 返回错误详情，请求用户确认 |
| `formula_conflict` | 尝试写入公式单元格 | 跳过该字段，记录警告 |
| `llm_error` | LLM 调用失败/超时 | 重试 2 次，降级到确定性提取器 |
| `rule_conflict` | 多条规则给出矛盾建议 | 选择 confidence 最高的规则 |

### 6.2 降级策略

```
优先级 1: LLM + Reference Bank（完整语义提取）
           ↓ 失败
优先级 2: LLM + 仅锚点（减少规则依赖）
           ↓ 失败
优先级 3: 确定性提取器（extractors/*.py，如有）
           ↓ 失败
优先级 4: 请求用户介入，提供修正或样本
```

## 7. 文件组织规范

### 7.1 仓库目录结构

```
oh-sheets!/
├── SKILL.md
├── README.md
├── README_zh.md
│
├── scripts/
│   ├── core/                     # 核心模块
│   │   ├── reference_bank.py
│   │   ├── rule_evolution.py
│   │   ├── prompt_builder.py
│   │   └── signature_matcher.py
│   │
│   ├── extraction/               # 提取相关
│   │   ├── llm_extractor.py
│   │   └── formula_analyzer.py
│   │
│   ├── io/                       # 输入输出
│   │   ├── excel_writer.py
│   │   └── data_diff.py
│   │
│   ├── memory/                   # 记忆系统
│   │   └── local_few_shot_memory.py
│   │
│   ├── orchestration/            # 编排层
│   │   ├── execution_orchestrator.py
│   │   └── learning_orchestrator.py
│   │
│   └── utils/                    # 工具函数
│       ├── template_layout_signature.py
│       └── env_check.py
│
├── references/
│   ├── prompt_templates.md
│   └── config_schema.md
│
├── docs/
│   └── superpowers/specs/
│
├── tests/                        # 镜像 scripts 结构
│   ├── core/
│   ├── extraction/
│   ├── io/
│   ├── memory/
│   ├── orchestration/
│   └── e2e/
│
└── examples/
```

### 7.2 文件命名约定

| 类型 | 命名规则 | 示例 |
|------|----------|------|
| 脚本文件 | snake_case.py | `reference_bank.py` |
| 测试文件 | test_<module>.py | `test_reference_bank.py` |
| JSON 数据文件 | snake_case.json / .jsonl | `anchors.json`, `rules.jsonl` |
| 配置文件 | snake_case.yaml | `config.yaml` |
| 文档文件 | kebab-case.md | `prompt-templates.md` |

### 7.3 模块职责边界

| 目录 | 职责 | 禁止 |
|------|------|------|
| `orchestration/` | 流程编排，不处理具体逻辑 | 直接调用 LLM |
| `core/` | 核心业务逻辑，不直接调用 LLM | 跨层调用 |
| `extraction/` | LLM 调用，多模态处理 | 文件读写 |
| `io/` | 文件读写，格式转换 | 业务逻辑 |
| `memory/` | 持久化存储，历史记录 | 直接调用 LLM |
| `utils/` | 无状态工具函数 | 有状态操作 |

## 8. 测试策略

### 8.1 测试层次

| 层次 | 测试内容 |
|------|----------|
| 单元测试 | 每个模块的核心函数 |
| 集成测试 | Reference Bank + LLM 流程 |
| E2E 测试 | 端到端场景覆盖 |

### 8.2 E2E 测试场景

| 编号 | 场景 | 输入 | 预期结果 |
|------|------|------|----------|
| E2E-01 | PDF 提取 | PDF 文档 | 正确提取所有字段，写入 Excel |
| E2E-02 | Excel 转换 | Excel 源文件 | 正确提取并填入目标模板 |
| E2E-03 | 新变体处理 | 未见过的格式 | 触发学习或正确路由到相似模式 |
| E2E-04 | 多轮修正 | 故意制造的缺失字段 | 成功修复，规则 confidence 更新 |
| E2E-05 | 公式模板 | 含公式的目标模板 | 公式单元格不被覆盖 |

## 9. 实现清单

### 9.1 新增文件

| 文件 | 功能 |
|------|------|
| `scripts/core/reference_bank.py` | Reference Bank 管理器 |
| `scripts/core/rule_evolution.py` | 规则进化引擎 |
| `scripts/core/prompt_builder.py` | Prompt 构建器 |
| `scripts/core/signature_matcher.py` | 签名匹配器 |
| `scripts/extraction/llm_extractor.py` | LLM 提取器 |
| `scripts/extraction/formula_analyzer.py` | 公式分析器 |
| `scripts/orchestration/learning_orchestrator.py` | 学习编排器 |

### 9.2 修改文件

| 文件 | 改动 |
|------|------|
| `scripts/orchestration/execution_orchestrator.py` | 重构为 Reference Bank 检索 + LLM 执行流程 |
| `scripts/memory/local_few_shot_memory.py` | 扩展：支持成功模式记录 + 规则置信度更新 |
| `scripts/utils/template_layout_signature.py` | 扩展：支持输入文件签名计算 |
| `references/prompt_templates.md` | 新增 v2 prompt 模板 |
| `SKILL.md` | 更新 skill 说明 |

## 10. 验收标准

- [ ] Reference Bank 数据结构完整实现
- [ ] LLM 提取流程跑通（支持 PDF/Excel/Word/MD）
- [ ] 规则进化机制生效（confidence 更新、衰减）
- [ ] 公式分析正确，公式单元格不被覆盖
- [ ] 新变体能触发学习或正确路由
- [ ] 成功模式能被记录和检索复用
- [ ] 单元测试覆盖率 > 80%
- [ ] E2E 测试场景全部通过