# scripts/core/prompt_builder.py
import json

def build_context_prompt(
    template_signature: str,
    schema_fields: dict,
    formula_constraints: list,
    anchors: dict,
    rules: list,
    success_patterns: list,
    input_content: str
) -> str:
    prompt = f"""## 目标模板签名\n{template_signature}\n
## 字段定义\n{json.dumps(schema_fields, ensure_ascii=False, indent=2)}\n
## 公式约束\n{json.dumps(formula_constraints, ensure_ascii=False, indent=2)}\n说明：以上单元格包含公式，请勿填充，但可用于验证。\n
## 锚点参考\n{json.dumps(anchors, ensure_ascii=False, indent=2)}\n
## 相关规则\n{json.dumps(rules, ensure_ascii=False, indent=2)}\n
## 成功案例参考\n{json.dumps(success_patterns, ensure_ascii=False, indent=2)}\n
## 输入文档\n{input_content}\n"""
    return prompt
