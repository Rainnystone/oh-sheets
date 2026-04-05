import hashlib

def calculate_signature(content: str) -> str:
    """Calculate an MD5 signature for input content."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()

def match_patterns(signature: str, patterns: list, top_k: int = 3) -> list:
    """Find success patterns matching the input signature."""
    matches = [p for p in patterns if p.get("input_signature") == signature]
    return sorted(matches, key=lambda x: x.get("accuracy", 0.0), reverse=True)[:top_k]
