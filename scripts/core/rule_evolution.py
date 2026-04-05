# scripts/core/rule_evolution.py
from datetime import datetime

def update_rule_confidence(rule: dict, outcome: float) -> dict:
    """Updates confidence. Returns None if rule should be archived (confidence < 0.3)."""
    updated = rule.copy()
    confidence = updated.get("confidence", 0.5)
    support = updated.get("support", 0)

    if outcome >= 0.8:
        updated["confidence"] = min(1.0, round(confidence + 0.02, 2))
        updated["support"] = support + 1
    elif outcome <= 0.3:
        updated["confidence"] = max(0.0, round(confidence - 0.05, 2))
        
    if updated["confidence"] < 0.3:
        return None
        
    return updated

def decay_rules(rules: list, days_inactive: int = 30) -> list:
    decayed_rules = []
    now = datetime.now()
    
    for rule in rules:
        decayed = rule.copy()
        last_used_str = decayed.get("last_used")
        if last_used_str:
            try:
                last_used = datetime.fromisoformat(last_used_str)
                days_since_use = (now - last_used).days
                if days_since_use > days_inactive:
                    decay_factor = 0.99 ** (days_since_use - days_inactive)
                    decayed["confidence"] = round(decayed.get("confidence", 0.5) * decay_factor, 4)
            except ValueError:
                pass
        # Only keep rules that haven't dropped below archiving threshold
        if decayed.get("confidence", 0.5) >= 0.3:
            decayed_rules.append(decayed)
        
    return decayed_rules