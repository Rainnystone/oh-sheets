import hashlib

def calculate_signature(content: str) -> str:
    """Calculate an MD5 signature for input content."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()

def match_patterns(signature: str, patterns: list, top_k: int = 3, threshold: float = 0.8) -> list:
    """
    Find success patterns matching the input signature.

    1. First tries exact signature match.
    2. If no exact match, returns patterns with accuracy >= threshold.
    3. Results are sorted by accuracy (highest first).

    Args:
        signature: The input signature to match.
        patterns: List of success patterns with input_signature and accuracy.
        top_k: Maximum number of results to return.
        threshold: Minimum accuracy for similarity match (used when no exact match).

    Returns:
        List of matching patterns, sorted by accuracy.
    """
    # First, try exact signature match
    exact_matches = [p for p in patterns if p.get("input_signature") == signature]
    if exact_matches:
        return sorted(exact_matches, key=lambda x: x.get("accuracy", 0.0), reverse=True)[:top_k]

    # No exact match - return similar patterns by accuracy threshold
    similar = [p for p in patterns if p.get("accuracy", 0.0) >= threshold]
    return sorted(similar, key=lambda x: x.get("accuracy", 0.0), reverse=True)[:top_k]
