import hashlib

def calculate_signature(content: str) -> str:
    """Calculate an MD5 signature for input content."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()

def match_patterns(signature: str, patterns: list, top_k: int = 3, threshold: float = 0.8) -> list:
    """
    Find success patterns for the input signature.

    1. Exact signature match: return matching patterns sorted by accuracy.
    2. No exact match: FALLBACK by accuracy — return patterns with
       accuracy >= threshold, sorted by accuracy. This is NOT a signature
       similarity computation; it returns historically-accurate patterns
       regardless of their signature. Renamed internally from "similar"
       to avoid implying signature comparison.

    True signature similarity would require vector embeddings and is out
    of scope (see PRD non-goals).

    Args:
        signature: The input signature to match.
        patterns: List of success patterns with input_signature and accuracy.
        top_k: Maximum number of results to return.
        threshold: Minimum accuracy for the fallback (used when no exact match).

    Returns:
        List of matching patterns, sorted by accuracy.
    """
    # First, try exact signature match
    exact_matches = [p for p in patterns if p.get("input_signature") == signature]
    if exact_matches:
        return sorted(exact_matches, key=lambda x: x.get("accuracy", 0.0), reverse=True)[:top_k]

    # No exact match — accuracy-based fallback (NOT signature similarity).
    by_accuracy = [p for p in patterns if p.get("accuracy", 0.0) >= threshold]
    return sorted(by_accuracy, key=lambda x: x.get("accuracy", 0.0), reverse=True)[:top_k]
