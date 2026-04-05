# scripts/core/prompt_builder.py
import json

def format_rules_as_few_shot(rules: list) -> str:
    """
    Format rules as few-shot examples with confidence/support header.

    Spec §5.3 format:
    规则 {rule_id} [置信度: {confidence}, 成功次数: {support}]:
    - 触发条件: 提取 {field_name} 字段时
    - 操作: {action_description}
    - 示例: "{input_example}" → "{output_example}"
    """
    if not rules:
        return "暂无规则"

    # Sort by confidence (highest first)
    sorted_rules = sorted(rules, key=lambda x: x.get("confidence", 0), reverse=True)

    lines = ["## 提取规则（按置信度排序）"]
    for rule in sorted_rules:
        rule_id = rule.get("id", "未知")
        confidence = rule.get("confidence", 0)
        support = rule.get("support", 0)

        lines.append(f"\n规则 {rule_id} [置信度: {confidence}, 成功次数: {support}]:")

        # Trigger condition
        condition = rule.get("condition", {})
        field_name = condition.get("field", "未知字段")
        lines.append(f"- 触发条件: 提取 {field_name} 字段时")

        # Action description
        then_clause = rule.get("then", {})
        action = then_clause.get("action", "未定义操作")
        anchor = then_clause.get("anchor", "")
        pattern = then_clause.get("pattern", "")
        action_desc = f"{action}"
        if anchor:
            action_desc += f" (锚点: {anchor})"
        if pattern:
            action_desc += f" (模式: {pattern})"
        lines.append(f"- 操作: {action_desc}")

        # Example if provided
        example = rule.get("example")
        if example:
            input_ex = example.get("input", "")
            output_ex = example.get("output", "")
            lines.append(f"- 示例: \"{input_ex}\" → \"{output_ex}\"")

    return "\n".join(lines)

def build_context_prompt(
    template_signature: str,
    schema_fields: dict,
    formula_constraints: list,
    anchors: dict,
    rules: list,
    success_patterns: list,
    input_content: str
) -> str:
    rules_section = format_rules_as_few_shot(rules)

    prompt = f"""## 目标模板签名
{template_signature}

## 字段定义
{json.dumps(schema_fields, ensure_ascii=False, indent=2)}

## 公式约束
{json.dumps(formula_constraints, ensure_ascii=False, indent=2)}
说明：以上单元格包含公式，请勿填充，但可用于验证。

## 锚点参考
{json.dumps(anchors, ensure_ascii=False, indent=2)}

{rules_section}

## 成功案例参考
{json.dumps(success_patterns, ensure_ascii=False, indent=2)}

## 输入文档
{input_content}
"""
    return prompt
