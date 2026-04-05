import json
import tempfile
from pathlib import Path

from scripts.memory.local_few_shot_memory import record_execution, rebuild_failure_summary, suggest_repairs


def _tmp_mem_dir():
    return Path(tempfile.mkdtemp(prefix="oh-sheets-memory-"))


def test_record_and_rebuild_summary_rules():
    memory_dir = _tmp_mem_dir()
    event_a = {
        "template_signature": "sig-template-v1",
        "error_type": "row_misalignment",
        "missing_fields": ["Field_A", "Field_B"],
        "repair_action": "repair_anchor_chain",
        "human_confirmed": True,
        "confidence": 0.83,
        "rule_ids": [],
    }
    event_b = dict(event_a)
    event_b["human_confirmed"] = False
    event_c = dict(event_a)
    event_c["repair_action"] = "manual_repair_check"

    record_execution(memory_dir, event_a)
    record_execution(memory_dir, event_b)
    record_execution(memory_dir, event_c)

    report = rebuild_failure_summary(memory_dir, min_support=2)
    rules = report["rules"]["rules"]

    assert len(rules) == 1
    assert rules[0]["template_signature"] == "sig-template-v1"
    assert rules[0]["error_type"] == "row_misalignment"
    assert rules[0]["repair_action"] == "repair_anchor_chain"
    assert rules[0]["support"] == 3


def test_query_repairs_by_signature_and_fields():
    memory_dir = _tmp_mem_dir()
    base = {
        "template_signature": "sig-test-v1",
        "error_type": "semantic_mismatch",
        "missing_fields": ["Field_C", "Field_D"],
        "repair_action": "repair_by_reference_chain",
        "human_confirmed": True,
        "confidence": 0.95,
    }
    record_execution(memory_dir, base)
    record_execution(memory_dir, base)
    rebuild_failure_summary(memory_dir, min_support=2)

    rules = suggest_repairs(memory_dir, "sig-test-v1", "semantic_mismatch", ["Field_C", "Field_D"])
    assert len(rules) == 1
    assert rules[0]["repair_action"] == "repair_by_reference_chain"

    no_match = suggest_repairs(memory_dir, "sig-other", "semantic_mismatch", ["Field_C", "Field_D"])
    assert no_match == []
