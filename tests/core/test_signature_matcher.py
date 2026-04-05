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

def test_match_patterns_no_exact_match_returns_similar():
    """When no exact signature match, return similar patterns by metadata."""
    patterns = [
        {"input_signature": "abc123", "accuracy": 0.95, "input_type": "pdf"},
        {"input_signature": "def456", "accuracy": 0.85, "input_type": "pdf"},
        {"input_signature": "ghi789", "accuracy": 0.70, "input_type": "excel"}
    ]

    # No exact match for this signature
    matches = match_patterns("nonexistent_sig", patterns, threshold=0.8)

    # Should return patterns with accuracy >= threshold, sorted by accuracy
    assert len(matches) == 2
    assert matches[0]["accuracy"] == 0.95
    assert matches[1]["accuracy"] == 0.85

def test_match_patterns_respects_top_k():
    """Test that top_k limits number of results."""
    patterns = [
        {"input_signature": "sig1", "accuracy": 0.9},
        {"input_signature": "sig2", "accuracy": 0.85},
        {"input_signature": "sig3", "accuracy": 0.8}
    ]

    matches = match_patterns("nonexistent", patterns, threshold=0.75, top_k=2)
    assert len(matches) == 2

def test_match_patterns_empty_when_no_similar():
    """Returns empty list when no patterns meet threshold."""
    patterns = [
        {"input_signature": "sig1", "accuracy": 0.5},
        {"input_signature": "sig2", "accuracy": 0.4}
    ]

    matches = match_patterns("nonexistent", patterns, threshold=0.8)
    assert len(matches) == 0
