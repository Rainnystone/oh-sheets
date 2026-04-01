# oh-sheets! Semantic Reference Engine Design

## 0. 目标

把当前扩展从“记坐标”升级为“可迁移的结构语义系统”。

- 保留现有学习循环，但在 `reference` 中引入可复用的语义规则层。
- 目标是让新版本模板不再依赖固定单元格清单，而是依赖结构关系、公式关系、自然语言语义约束。
- 失败时不盲填；优先给出可执行修正建议并触发 mini skill 生成。
- 明确目标是“本地 few-shot RLHF”：把每次失败或修正都压成可复用经验，下一次新输入优先用这个经验自我修正并减少干预。

## 1. 现状问题

当前输出链条虽然能跑通常规场景，但在模板变更时容易退化为“死记硬背”。

- 新增列/字段或表头变动时，写入逻辑容易偏离。
- 不同报表类型之间缺少统一规则承接，不能复用通用理解。
- 规则缺少对公式和文本语义的记录，无法约束“这行不该是谁的”类问题。

## 2. 设计目标（本次实现）

- 在 reference 中新增两类知识：
  - `layout_relation`：字段间的行列关系（相对定位）与迁移约束。
  - `logic_constraints`：公式关系、计算关系、字段一致性关系。
  - `language_constraints`：自然语言语义约束（例如字段唯一性、缺失处理口径）。
- 新增模板布局签名能力，支持结构级版本对比。
- 执行阶段按三层机制运行：理解、写入、校验。
- 目标执行标准：当输入模板签名不一致时，系统必须优先回到学习分支，不允许进入“硬猜坐标写入”。

## 3. 术语

- `reference`：目标模板级知识库，不再只含字段映射，还含规则与约束。
- `semantic field`：对字段含义有统一名称和描述的字段（比如 Identifier_Field, Period_Field）。
- `layout relation`：字段与字段之间的相对行列约束（上、下、左、右偏移）。
- `rule note`：每次修正失败后沉淀的“通用纠错规则”。

## 4. 新增文件与数据结构

### 4.1 schema.json 扩展

新增 top-level 结构：

- `meta.signature`：模板签名。
- `meta.version`：模板版本号。
- `meta.family`：模板族（如 ProjectReport）。
- `fields`：每个 semantic field 的字段定义。
  - `cell`：可选绝对定位。
  - `relative_to` + `row_offset` + `col_offset`：可选的结构关系。
- `logic_constraints`：与公式/数学关系相关的约束项。
- `language_constraints`：自然语言级校验（同一性、排他性、默认口径）。
- `migration_hints`：历史版本可复用映射建议。

### 4.2 rules.md 扩展

新增用于运行期解释的结构化段落：

- `# Field Identity`：字段语义定义与别名。
- `# Layout Rules`：结构迁移规则。
- `# Computation Rules`：公式关系与容错口径。
- `# Language Rules`：语义约束（比如“字段 A 不可覆盖字段 B 的说明”）。
- `# Learning Notes`：自动总结的可复用经验。

### 4.3 模板签名（结构级）

新增脚本 `scripts/template_layout_signature.py` 保留模板结构签名，用于判断变体是否属于同一结构族，作为版本迁移依据。

### 4.4 本地 few-shot 记忆库（本质是 RLHF 记忆）

在每个模板目录新增 `memory/`，用于本地少样本学习，不依赖远端或云端存储：

- `memory/execution_log.jsonl`
  - 每次执行记录：`signature`, `input_type`, `error_type`, `missing_fields`, `repair_action`, `human_confirmed`, `confidence`, `rule_ids`。
- `memory/failure_clusters.json`
  - 聚合过往同类失败模式，例如“主锚点列漂移”“小数位口径变化”。
- `memory/summary_rules.json`
  - 维护可复用规则摘要（非死规则），支持按签名和语义标签检索。

这三类文件是 local few-shot 的知识源，不直接依赖单笔样例中的死坐标。

## 5. 执行流程（改造后）

### 5.1 学习阶段

1. 分析空白模板，先生成布局签名。
2. 生成 schema v2：优先识别 semantic field 与关系，不只识别坐标。
3. 自动提炼 `logic_constraints` 与 `language_constraints`，放入 reference。
4. 生成 extractor。
5. 用 RALPH 对照 test set 验证。
6. 对失败进行二次学习：优先修复关系与约束，再调整字段。
7. 结果落库到 `memory/execution_log.jsonl`，并触发 `memory/summary_rules.json` 的聚合更新。

### 5.2 执行阶段

1. 读取 `signature` 比对，若不匹配则尝试结构迁移。
2. 若签名差异级别超过阈值，进入 learn 兜底，不允许直接执行；若差异小于阈值则触发轻量迁移。
3. 写入前先做关系解析：字段定位按 `relative_to`/`row_offset`/`col_offset`，并结合当前版本的 `failure_clusters` 做优先修复。
4. 结合 `memory/summary_rules.json` 做语义预筛选，提前剔除明显漂移输入（如字段归属冲突）。
5. 写入后做约束检查：
   - 数值一致性（公式类约束）。
   - 唯一性/归属性等语义约束。
6. 不确定字段进入人类确认队列；确认后沉淀到 `rules.md` 与 `memory/summary_rules.json`。
7. 每次执行结果都写入 `memory/execution_log.jsonl`，并给 `summary_rules` 更新一个增量摘要。

## 6. 误差闭环（mini RLHF 思路）

执行闭环分成四步：
1. 归因：把偏差分成“布局关系漂移”和“语义口径偏差”。
2. 萃取：从偏差中抽取可复用信号，形成“症状→修复动作”对：
   - 症状：同名标识被写入错行。
   - 修复动作：优先以标识列为锚点重建行关系。
3. 总结：对同类型症状做去重和泛化，更新 `memory/summary_rules.json`，并写回 `logic_constraints` 或 `language_constraints`。
4. 学习触发：若同一签名族内出现高频重复偏差且未被规则消解，自动触发 learn 分支做新版本 schema/relation 重建。

该闭环不是只加一条死规则，而是输出“在当前语境下生效、可迁移到同类场景”的规则摘要。

## 7. 边界与回退

- 未匹配的字段不做猜测写入。
- 只在高置信关系链条中自动修复；否则阻断并返回待确认清单。
- 任何布局变更都记录到新版本，避免旧规则被覆盖。

## 7.1 不一致处理优先级

1. 硬错误（布局签名不兼容）：立即停止执行，进入学习回路，要求用户确认或补充样本。
2. 软错误（关系定位偏移、边界值缺失）：可尝试迁移推断；不确定时进入确认队列。
3. 规则冲突（语义冲突但可判别）：先执行回退到安全值，再请求人类确认，避免污染主数据。

## 8. 验收标准

- 模板新增字段时，旧字段仍按关系映射成功。
- 同一语义字段在不同布局下可定位。
- 约束检查能阻止明显语义错误（例如“同一标识在重复行出现”）。
- 无需新增死规则即可支持结构微调。
- 本地 few-shot 记忆在下一次同签名/近似签名任务上自动触发修正规则命中率明显提升（例如同一失败症状二次出现时自动修复命中率 > 70%，至少有可追溯记录）。
- 签名不一致时不会进入普通写入路径，必须进入 learn 或确认分支。

## 9. 直接交付清单

- 已支持
  - `scripts/template_layout_signature.py`
  - `excel_writer` 的相对关系读取
  - prompt 与文档对 `schema v2` 与规则约束的说明
- 待实施（与本 spec 对齐）
  - 在 learn/extract 的 orchestrator 中接入规则检查与迁移分支
  - 在 `rules.md` 中落地结构化约束段
  - 把成功提取结果反馈回 `logic_constraints`/`language_constraints`
  - 建立 `memory/` 结构并联动 `execution_log`、`failure_clusters`、`summary_rules`
  - 在签名不一致时触发 learn 回路，而不是 fallback 到写入
