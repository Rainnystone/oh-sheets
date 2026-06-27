# tests/core/test_rule_evolution.py
from scripts.core.rule_evolution import update_rule_confidence

def test_update_rule_confidence():
    rule = {"id": "R001", "confidence": 0.8, "support": 5}
    success_rule = update_rule_confidence(rule, outcome=0.9)
    assert success_rule["confidence"] == 0.82
    assert success_rule["support"] == 6

    fail_rule = update_rule_confidence(rule, outcome=0.2)
    assert fail_rule["confidence"] == 0.75
    assert fail_rule["support"] == 5

    # Test archiving logic (returns None if confidence drops below 0.3)
    archive_rule = {"id": "R003", "confidence": 0.32, "support": 1}
    archived = update_rule_confidence(archive_rule, outcome=0.1)
    assert archived is None
