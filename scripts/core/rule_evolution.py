# scripts/core/rule_evolution.py
from enum import Enum


class Outcome(Enum):
    """Lifecycle outcome for a rule set (slice 4).

    The enum's .value is the float update_rule_confidence expects, so
    `update_rule_confidence(rule, Outcome.SUCCESS.value)` works unchanged.
    Kept here (not on the Bank) because it parameterizes the math.
    """
    SUCCESS = 1.0    # reward all rules (+0.02 confidence, +1 support)
    FAILURE = 0.2    # penalize all rules (-0.05 confidence)
    PARTIAL = 0.5    # reserved for future partial-success semantics
                     # (treated as no-op by update_rule_confidence today)


def update_rule_confidence(rule: dict, outcome: float) -> dict | None:
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