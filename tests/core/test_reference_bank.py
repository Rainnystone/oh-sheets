import os
import json
from scripts.core.reference_bank import ReferenceBank

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
