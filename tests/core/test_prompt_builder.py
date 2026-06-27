# tests/core/test_prompt_builder.py
from scripts.core.prompt_builder import build_context_prompt, format_rules_as_few_shot

def test_build_context_prompt():
    prompt = build_context_prompt(
        template_signature="abc12345",
        schema_fields={"Field_A": {"type": "string"}},
        formula_constraints=[{"cell": "D5", "description": "Sum"}],
        anchors={"vendor": {"type": "text_match"}},
        rules=[{"id": "R001", "confidence": 0.9}],
        success_patterns=[],
        input_content="Sample Content"
    )

    assert "abc12345" in prompt
    assert "Field_A" in prompt
    assert "D5" in prompt
    assert "R001" in prompt
    assert "Sample Content" in prompt

def test_format_rules_as_few_shot():
    """Test that rules are formatted as few-shot examples with confidence/support."""
    rules = [
        {
            "id": "R001",
            "confidence": 0.92,
            "support": 5,
            "condition": {"field": "vendor_name"},
            "then": {"action": "extract_after_anchor", "anchor": "Vendor:"},
            "example": {"input": "Vendor: ABC Corp", "output": "ABC Corp"}
        },
        {
            "id": "R002",
            "confidence": 0.75,
            "support": 3,
            "condition": {"field": "total_amount"},
            "then": {"action": "find_by_regex", "pattern": "\\$[\\d,.]+"}
        }
    ]

    formatted = format_rules_as_few_shot(rules)

    # Should have header with confidence and support
    assert "规则 R001" in formatted
    assert "置信度: 0.92" in formatted
    assert "成功次数: 5" in formatted

    # Should have trigger condition
    assert "触发条件" in formatted
    assert "vendor_name" in formatted

    # Should have action description
    assert "操作:" in formatted
    assert "extract_after_anchor" in formatted

    # Should have example if provided
    assert "示例:" in formatted
    assert "Vendor: ABC Corp" in formatted
    assert "ABC Corp" in formatted

    # Rules should be sorted by confidence (R001 first, then R002)
    r001_pos = formatted.find("R001")
    r002_pos = formatted.find("R002")
    assert r001_pos < r002_pos, "Rules should be sorted by confidence (highest first)"


def test_format_rules_renders_via_kg_provenance(tmp_path=None):
    """Rules expanded via the knowledge graph are tagged in the prompt.

    A rule with `_source="via_kg"` is rendered with a 来源: 知识图谱关联
    note in the header line, so the LLM knows the rule was inferred
    rather than directly matched. Direct rules (and rules without an
    explicit _source) get no provenance note — backward compatible.
    """
    rules = [
        {
            "id": "R001",
            "confidence": 0.9,
            "support": 5,
            "condition": {"field": "vendor_name"},
            "then": {"action": "semantic_extract"},
            "_source": "direct",
        },
        {
            "id": "R002",
            "confidence": 0.78,
            "support": 2,
            "condition": {"field": "amount"},
            "then": {"action": "semantic_extract"},
            "_source": "via_kg",
        },
        {
            # No _source at all — treated as direct, no provenance note.
            "id": "R003",
            "confidence": 0.6,
            "support": 1,
            "condition": {"field": "date"},
            "then": {"action": "semantic_extract"},
        },
    ]

    formatted = format_rules_as_few_shot(rules)

    # R001 (direct): no provenance note in its header line.
    r001_line = next(
        line for line in formatted.splitlines() if line.startswith("\n规则 R001") or "规则 R001" in line
    )
    assert "来源" not in r001_line

    # R002 (via_kg): provenance note present.
    r002_line = next(line for line in formatted.splitlines() if "规则 R002" in line)
    assert "来源: 知识图谱关联" in r002_line

    # R003 (no _source): backward compatible — no provenance note.
    r003_line = next(line for line in formatted.splitlines() if "规则 R003" in line)
    assert "来源" not in r003_line
