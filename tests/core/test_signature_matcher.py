# tests/core/test_signature_matcher.py
from scripts.core.signature_matcher import calculate_signature, match_patterns

def test_calculate_signature():
    assert calculate_signature("test content") == "9473fdd0d880a43c21b7778d34872157"

def test_match_patterns():
    patterns = [
        {"input_signature": "9473fdd0d880a43c21b7778d34872157", "accuracy": 1.0},
        {"input_signature": "other", "accuracy": 0.8}
    ]
    matches = match_patterns("9473fdd0d880a43c21b7778d34872157", patterns)
    assert len(matches) == 1
    assert matches[0]["accuracy"] == 1.0
