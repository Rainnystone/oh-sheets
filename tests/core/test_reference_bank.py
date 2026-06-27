import os
import re
import json
from datetime import datetime, timedelta
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
# query_anchors (slice 2)
# ---------------------------------------------------------------------------

def test_query_anchors_by_field(tmp_path):
    """query_anchors("vendor_name") returns the anchor for that field."""
    bank = ReferenceBank(str(tmp_path / "bank"))
    anchors = {
        "vendor_name": {"type": "text_match", "role": "label", "pattern": "Vendor"},
        "amount": {"type": "spatial", "role": "value_matcher"},
    }
    bank.save_anchors(anchors)
    result = bank.query_anchors("vendor_name")
    assert result["type"] == "text_match"
    assert result["role"] == "label"


def test_query_anchors_all(tmp_path):
    """query_anchors(None) returns the full anchor dict."""
    bank = ReferenceBank(str(tmp_path / "bank"))
    anchors = {
        "vendor_name": {"type": "text_match", "role": "label", "pattern": "Vendor"},
        "amount": {"type": "spatial", "role": "value_matcher"},
    }
    bank.save_anchors(anchors)
    result = bank.query_anchors()
    assert result == anchors
    # Missing field returns None
    assert bank.query_anchors("nonexistent") is None


# ---------------------------------------------------------------------------
# retrieve_rules KG expansion (slice 2)
# ---------------------------------------------------------------------------

def _edge(src, dst, relation, weight=1.0):
    return {"from": src, "to": dst, "relation": relation, "weight": weight}


def test_retrieve_rules_expands_via_uses_anchor(tmp_path):
    """retrieve_rules expands 1 hop via uses_anchor edges (symmetric).

    Given R001 (pdf) uses anchor A1, and R002 (excel — wouldn't match the
    pdf filter directly) also uses A1, retrieving pdf inputs that match
    R001 also returns R002 with _source="via_kg".
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        _rule("R001", input_type="pdf", confidence=0.9),    # direct match
        _rule("R002", input_type="excel", confidence=0.7),  # only via KG
        _rule("R003", input_type="pdf", confidence=0.5),    # direct, no shared anchor
    ])
    # R001 and R002 both use anchor A1; R003 uses A2 (no other rule)
    bank.save_knowledge_graph({"schema_version": "1.0", "edges": [
        _edge("R001", "A1", "uses_anchor"),
        _edge("R002", "A1", "uses_anchor"),
        _edge("R003", "A2", "uses_anchor"),
    ]})
    result = bank.retrieve_rules("pdf")
    sources = {r["id"]: r["_source"] for r in result}
    # R001 and R003 matched the filter directly
    assert sources["R001"] == "direct"
    assert sources["R003"] == "direct"
    # R002 (excel) reached the result via KG expansion through shared A1
    assert sources["R002"] == "via_kg"


def test_retrieve_rules_expands_via_often_follows(tmp_path):
    """retrieve_rules expands via often_follows edges (directional).

    Edge {from: R001, to: R002, relation: often_follows} means: when R001
    is in the direct set, R002 is a neighbor. The reverse is NOT true —
    if R002 is direct, R001 is NOT expanded.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        _rule("R001", input_type="pdf", confidence=0.9),     # direct match
        _rule("R002", input_type="excel", confidence=0.7),   # neighbor via often_follows
        _rule("R003", input_type="excel", confidence=0.6),   # NOT a neighbor (reverse direction)
    ])
    # R001 →often_follows→ R002 (directional). R003 →often_follows→ R001
    # means R001 is a neighbor of R003, NOT the reverse.
    bank.save_knowledge_graph({"schema_version": "1.0", "edges": [
        _edge("R001", "R002", "often_follows"),
        _edge("R003", "R001", "often_follows"),
    ]})
    result = bank.retrieve_rules("pdf")
    sources = {r["id"]: r["_source"] for r in result}
    # R002 expanded via R001→R002 edge (directional, correct direction)
    assert sources["R002"] == "via_kg"
    # R003 is NOT expanded — R003→R001 edge points the wrong way
    assert "R003" not in sources


def test_retrieve_rules_direct_wins_over_via_kg(tmp_path):
    """A rule that is BOTH direct (matches filter) AND a KG neighbor is
    returned once with _source="direct" — never "via_kg", never twice.

    R001 and R002 both match the pdf filter directly AND share anchor A1.
    Without dedupe-prefer-direct, R002 might appear as via_kg (because
    _expand_via_kg would otherwise include it). The implementation
    excludes direct IDs from via_kg, AND dedupe prefers direct on
    collision — both paths are covered by this test.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        _rule("R001", input_type="pdf", confidence=0.9),
        _rule("R002", input_type="pdf", confidence=0.7),
    ])
    bank.save_knowledge_graph({"schema_version": "1.0", "edges": [
        _edge("R001", "A1", "uses_anchor"),
        _edge("R002", "A1", "uses_anchor"),
    ]})
    result = bank.retrieve_rules("pdf")
    ids = [r["id"] for r in result]
    # R002 appears exactly once
    assert ids.count("R002") == 1
    # And its source is direct (matched the filter), not via_kg
    r002 = next(r for r in result if r["id"] == "R002")
    assert r002["_source"] == "direct"


def test_retrieve_rules_kg_1_hop_only(tmp_path):
    """KG expansion is 1 hop only — no transitive closure.

    Chain: R001 →often_follows→ R002 →often_follows→ R003.
    Matching R001 (direct) returns R002 (1-hop neighbor) but NOT R003
    (2-hop neighbor). All non-direct rules use input_type="excel" so
    they cannot match the pdf filter directly — they only enter the
    result set via KG.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        _rule("R001", input_type="pdf", confidence=0.9),    # direct
        _rule("R002", input_type="excel", confidence=0.7),  # 1-hop
        _rule("R003", input_type="excel", confidence=0.6),  # 2-hop — must NOT appear
    ])
    bank.save_knowledge_graph({"schema_version": "1.0", "edges": [
        _edge("R001", "R002", "often_follows"),
        _edge("R002", "R003", "often_follows"),
    ]})
    result = bank.retrieve_rules("pdf")
    ids = {r["id"] for r in result}
    assert "R001" in ids           # direct
    assert "R002" in ids           # 1-hop neighbor
    assert "R003" not in ids       # 2-hop — would require transitive expansion


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


# ---------------------------------------------------------------------------
# record_success_pattern (slice 3)
# ---------------------------------------------------------------------------

def test_record_success_pattern_populates_full_schema(tmp_path):
    """record_success_pattern is the single writer for success patterns.

    It must populate the full spec §3.4 schema: pattern_id, input_signature,
    input_type, fields_extracted, accuracy, rules_used, anchors_matched,
    created_at. Before this slice, two inline writers wrote different
    partial schemas and a third dead writer existed.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.record_success_pattern(
        input_signature="sig_abc",
        input_type="pdf",
        extracted={"vendor_name": "ABC Corp", "amount": "1000"},
        rules_used=["R001", "R002"],
        anchors_matched=["A1"],
        accuracy=1.0,
    )
    patterns = bank.load_success_patterns()
    assert len(patterns) == 1
    p = patterns[0]
    # Full §3.4 schema — all eight fields present.
    assert set(p.keys()) >= {
        "pattern_id", "input_signature", "input_type", "fields_extracted",
        "accuracy", "rules_used", "anchors_matched", "created_at",
    }
    assert p["input_signature"] == "sig_abc"
    assert p["input_type"] == "pdf"
    assert p["fields_extracted"] == ["vendor_name", "amount"]
    assert p["accuracy"] == 1.0
    assert p["rules_used"] == ["R001", "R002"]
    assert p["anchors_matched"] == ["A1"]
    assert p["pattern_id"].startswith("P")
    # created_at is an ISO timestamp (parseable).
    datetime.fromisoformat(p["created_at"])


def test_record_success_pattern_generates_sequential_ids(tmp_path):
    """pattern_id is max(existing)+1, not len(existing)+1.

    Same convention as add_rule's R00x IDs. Two successive calls produce
    P001 then P002; if a P005 already exists on disk, the next is P006
    (not P002).
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.record_success_pattern(
        input_signature="s1", input_type="pdf", extracted={"a": "1"},
        rules_used=[], anchors_matched=[],
    )
    bank.record_success_pattern(
        input_signature="s2", input_type="pdf", extracted={"b": "2"},
        rules_used=[], anchors_matched=[],
    )
    ids = [p["pattern_id"] for p in bank.load_success_patterns()]
    assert ids == ["P001", "P002"]

    # Pre-existing P005 on disk → next is P006 (max+1, not len+1=3).
    bank2 = ReferenceBank(str(tmp_path / "bank2"))
    bank2.save_success_patterns([{"pattern_id": "P005", "accuracy": 1.0}])
    bank2.record_success_pattern(
        input_signature="s3", input_type="pdf", extracted={"c": "3"},
        rules_used=[], anchors_matched=[],
    )
    assert bank2.load_success_patterns()[-1]["pattern_id"] == "P006"


def test_record_success_pattern_appends_not_overwrites(tmp_path):
    """record_success_pattern appends; existing patterns survive.

    Critical for the success-history invariant: the bank accumulates
    patterns over time. The old inline writers called save_success_patterns
    with a freshly-built list, which was correct only because they loaded
    first — but the contract must be explicit: never overwrite.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_success_patterns([
        {"pattern_id": "P001", "input_signature": "old_sig",
         "input_type": "pdf", "accuracy": 1.0, "rules_used": ["R001"]},
    ])
    bank.record_success_pattern(
        input_signature="new_sig", input_type="excel",
        extracted={"x": "1"}, rules_used=["R002"], anchors_matched=[],
    )
    patterns = bank.load_success_patterns()
    assert len(patterns) == 2
    # Old pattern preserved unchanged.
    assert patterns[0]["pattern_id"] == "P001"
    assert patterns[0]["input_signature"] == "old_sig"
    # New pattern appended with next ID.
    assert patterns[1]["pattern_id"] == "P002"
    assert patterns[1]["input_signature"] == "new_sig"


# ---------------------------------------------------------------------------
# retrieve_rules signature preference (slice 3)
# ---------------------------------------------------------------------------

def test_retrieve_rules_signature_preference_exact(tmp_path):
    """retrieve_rules(input_signature=S) prefers rules that succeeded on
    a signature-matched input before, tagging them _source="via_signature".

    Scenario: rule R001 is a direct pdf match, AND success pattern P1
    (sig=S1, rules_used=[R001]) records that R001 succeeded on input
    with signature S1. Retrieving with input_signature=S1 upgrades R001's
    _source from "direct" to "via_signature" — a rule that historically
    succeeded on similar input is a stronger signal than a mere type match.

    Precedence (locked here and in S3-5): via_signature > direct > via_kg.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([_rule("R001", input_type="pdf", confidence=0.7)])
    bank.save_success_patterns([
        {"pattern_id": "P001", "input_signature": "S1",
         "input_type": "pdf", "accuracy": 1.0, "rules_used": ["R001"]},
    ])
    result = bank.retrieve_rules("pdf", input_signature="S1")
    sources = {r["id"]: r["_source"] for r in result}
    assert sources["R001"] == "via_signature"


def test_retrieve_rules_no_signature_no_preference(tmp_path):
    """Without input_signature, signature preference is inactive — rules
    keep their direct/via_kg sources (slice 1-2 behavior unchanged).
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([_rule("R001", input_type="pdf", confidence=0.7)])
    bank.save_success_patterns([
        {"pattern_id": "P001", "input_signature": "S1",
         "input_type": "pdf", "accuracy": 1.0, "rules_used": ["R001"]},
    ])
    # No input_signature → R001 stays "direct".
    result = bank.retrieve_rules("pdf")
    assert result[0]["_source"] == "direct"
