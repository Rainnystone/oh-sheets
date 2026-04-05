# tests/core/test_rule_evolution.py
from datetime import datetime, timedelta
from scripts.core.rule_evolution import update_rule_confidence, decay_rules

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

def test_decay_rules():
    now = datetime.now()
    old_date = (now - timedelta(days=32)).isoformat()
    recent_date = (now - timedelta(days=5)).isoformat()
    
    rules = [
        {"id": "R001", "confidence": 0.8, "last_used": old_date},
        {"id": "R002", "confidence": 0.9, "last_used": recent_date}
    ]
    
    decayed = decay_rules(rules, days_inactive=30)
    assert decayed[0]["confidence"] < 0.8
    assert decayed[1]["confidence"] == 0.9
