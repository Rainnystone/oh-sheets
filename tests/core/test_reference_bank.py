import os
import json
from scripts.core.reference_bank import ReferenceBank


# ---------------------------------------------------------------------------
# retrieve_rules (slice 1)
# ---------------------------------------------------------------------------

def _rule(rule_id, input_type="auto", confidence=0.5, trigger="field_extraction"):
    """Helper: build a minimal valid rule dict."""
    return {
        "id": rule_id,
        "when": {"input_type": input_type, "trigger": trigger},
        "condition": {"field": "x"},
        "then": {"action": "semantic_extract"},
        "confidence": confidence,
        "support": 0,
    }


def test_retrieve_rules_filters_by_input_type(tmp_path):
    """retrieve_rules("pdf") returns only pdf rules (auto not yet covered here)."""
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        _rule("R001", input_type="pdf", confidence=0.7),
        _rule("R002", input_type="excel", confidence=0.7),
    ])
    result = bank.retrieve_rules("pdf")
    ids = [r["id"] for r in result]
    assert ids == ["R001"]


def test_retrieve_rules_auto_wildcard_matches_all(tmp_path):
    """Legacy "auto" rules match every input_type query (forward compat)."""
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        _rule("R001", input_type="auto", confidence=0.7),
        _rule("R002", input_type="pdf", confidence=0.7),
    ])
    pdf_ids = [r["id"] for r in bank.retrieve_rules("pdf")]
    excel_ids = [r["id"] for r in bank.retrieve_rules("excel")]
    assert pdf_ids == ["R001", "R002"]
    assert excel_ids == ["R001"]


def test_retrieve_rules_drops_low_confidence(tmp_path):
    """Rules with confidence < 0.3 (archive threshold) are filtered out."""
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        _rule("R001", input_type="pdf", confidence=0.8),
        _rule("R002", input_type="pdf", confidence=0.3),   # boundary — kept
        _rule("R003", input_type="pdf", confidence=0.29),  # below — dropped
        _rule("R004", input_type="pdf", confidence=0.0),   # below — dropped
    ])
    ids = [r["id"] for r in bank.retrieve_rules("pdf")]
    assert ids == ["R001", "R002"]


def test_retrieve_rules_sorts_by_confidence_desc(tmp_path):
    """Highest-confidence rules first — better few-shot ordering for the LLM."""
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        _rule("R001", input_type="pdf", confidence=0.4),
        _rule("R002", input_type="pdf", confidence=0.9),
        _rule("R003", input_type="pdf", confidence=0.6),
    ])
    ids = [r["id"] for r in bank.retrieve_rules("pdf")]
    assert ids == ["R002", "R003", "R001"]


def test_retrieve_rules_dedupes_by_id(tmp_path):
    """Duplicate IDs collapse to a single entry (keep highest confidence)."""
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        _rule("R001", input_type="pdf", confidence=0.4),
        _rule("R001", input_type="auto", confidence=0.8),  # same ID, higher conf
        _rule("R002", input_type="pdf", confidence=0.5),
    ])
    result = bank.retrieve_rules("pdf")
    ids = [r["id"] for r in result]
    assert ids == ["R001", "R002"]
    # The kept R001 should be the higher-confidence one
    r001 = next(r for r in result if r["id"] == "R001")
    assert r001["confidence"] == 0.8


def test_retrieve_rules_tags_source_direct(tmp_path):
    """Every returned rule carries _source='direct' (slice 1 only sets direct).

    _source is in-memory only — it must NOT be persisted to rules.jsonl.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([_rule("R001", input_type="pdf", confidence=0.7)])
    result = bank.retrieve_rules("pdf")
    assert result[0]["_source"] == "direct"
    # Persistence check: re-load and confirm _source is not on disk
    on_disk = bank.load_rules()
    assert "_source" not in on_disk[0]


# ---------------------------------------------------------------------------
# add_rule (slice 1)
# ---------------------------------------------------------------------------

def test_add_rule_generates_unique_ids(tmp_path):
    """IDs are max(existing)+1, not len(existing)+1.

    The old code used len(new_rules)+1, which caused collisions when
    phase2_draft and phase5_reflect both created rules (both got R001).
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    # Pre-existing rules R001..R005 (with a gap so len != max)
    bank.save_rules([
        _rule(f"R00{i}", input_type="pdf", confidence=0.5)
        for i in range(1, 6)
    ])
    # First new rule should be R006, not R001
    r1 = bank.add_rule(input_type="pdf", trigger="field_extraction",
                       field="vendor", action="semantic_extract")
    assert r1["id"] == "R006"
    # After saving and adding another, it should be R007
    bank.save_rules(bank.load_rules() + [r1])
    r2 = bank.add_rule(input_type="pdf", trigger="field_extraction",
                       field="amount", action="semantic_extract")
    assert r2["id"] == "R007"

    # Empty bank → first ID is R001
    empty_bank = ReferenceBank(str(tmp_path / "empty"))
    r3 = empty_bank.add_rule(input_type="pdf", trigger="field_extraction",
                             field="x", action="semantic_extract")
    assert r3["id"] == "R001"


def test_add_rule_does_not_persist_until_saved(tmp_path):
    """add_rule returns a dict but does not write to disk.
    Caller must call save_rules() to persist a batch.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([_rule("R001", input_type="pdf", confidence=0.5)])

    new_rule = bank.add_rule(input_type="pdf", trigger="field_extraction",
                             field="vendor", action="semantic_extract")
    # Immediately after add_rule, the disk state is unchanged
    on_disk = bank.load_rules()
    assert [r["id"] for r in on_disk] == ["R001"]

    # Only after save_rules does the new rule appear
    bank.save_rules(on_disk + [new_rule])
    on_disk_after = bank.load_rules()
    assert [r["id"] for r in on_disk_after] == ["R001", "R002"]


def test_add_rule_unique_ids_within_unsaved_batch(tmp_path):
    """Successive unsaved add_rule() calls produce unique IDs.

    Regression: phase2_draft calls add_rule() in a loop without saving
    between calls. Without pending-ID tracking, every call saw an empty
    disk and returned R001 — reintroducing the collision add_rule was
    meant to fix.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    rules = [
        bank.add_rule(input_type="pdf", trigger="field_extraction",
                      field=f"field_{i}", action="semantic_extract")
        for i in range(3)
    ]
    ids = [r["id"] for r in rules]
    assert ids == ["R001", "R002", "R003"]

    # After save, pending is cleared — next add_rule reads from disk only.
    bank.save_rules(rules)
    next_rule = bank.add_rule(input_type="pdf", trigger="field_extraction",
                              field="next", action="semantic_extract")
    assert next_rule["id"] == "R004"


def test_reference_bank_crud(tmp_path):
    bank_dir = tmp_path / "reference_bank"
    bank = ReferenceBank(str(bank_dir))
    
    # Test Anchors
    bank.save_anchors({"schema_version": "1.0", "anchors": {"test": {"type": "match"}}})
    assert bank.load_anchors()["anchors"]["test"]["type"] == "match"
    
    # Test Rules
    bank.save_rules([{"id": "R001", "confidence": 0.9}])
    assert bank.load_rules()[0]["id"] == "R001"
    
    # Test Success Patterns
    bank.save_success_patterns([{"pattern_id": "P001", "accuracy": 1.0}])
    assert bank.load_success_patterns()[0]["pattern_id"] == "P001"
    
    # Test Knowledge Graph
    bank.save_knowledge_graph({"edges": [{"from": "R001", "to": "R002"}]})
    assert bank.load_knowledge_graph()["edges"][0]["from"] == "R001"
