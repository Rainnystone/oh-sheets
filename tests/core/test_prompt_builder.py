# tests/core/test_prompt_builder.py
from scripts.core.prompt_builder import build_context_prompt

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
