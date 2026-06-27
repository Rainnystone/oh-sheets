# Issue: Slice 4 — Lifecycle fold (absorbs candidate 06)

**PRD:** [`docs/prd/deepen-reference-bank.md`](deepen-reference-bank.md)
**Domain glossary:** [`CONTEXT.md`](../../CONTEXT.md)
**ADR:** [`0001-reference-bank-owns-persistence.md`](../adr/0001-reference-bank-owns-persistence.md)
**Slice:** 4 of 4 (depends on slices 1-3; final slice)
**Estimate:** Medium

## Context

This slice absorbs architecture candidate 06 (duplicated confidence-update
policy). The "reward all rules on success, penalize all rules on failure"
policy is currently copy-pasted across three call sites with no test
asserting the actual policy. It lands in the Bank as `apply_outcome()`.

It also fixes two bugs:
- `decay_rules` is dead code (never called; `last_used` never written).
- `phase5_reflect` creates repair rules at confidence 0.6, then immediately
  penalizes them to 0.55 before they ever fire.

And introduces lazy decay at retrieval time, so stale rules are always
pruned before they reach the prompt.

Read the PRD's "Confirmed design decisions" table (rows 11-17) and the
"Slice 4" section before starting.

## Tasks

### 1. Add `Outcome` enum

File: `scripts/core/rule_evolution.py` (keep the math here; the enum lives
with the math it parameterizes)

```python
from enum import Enum

class Outcome(Enum):
    SUCCESS = 1.0    # reward all rules (+0.02 confidence, +1 support)
    FAILURE = 0.2    # penalize all rules (-0.05 confidence)
    PARTIAL = 0.5    # reserved for future partial-success semantics
                     # (treated as no-op by update_rule_confidence today)
```

`update_rule_confidence(rule, outcome.value)` continues to work unchanged —
the enum's `.value` is the float the math expects.

### 2. Add `apply_outcome()` to `ReferenceBank`

File: `scripts/core/reference_bank.py`

```python
def apply_outcome(self, outcome: "Outcome") -> int:
    """
    Reward/penalize all rules per outcome. Archives rules that drop
    below 0.3. Persists the updated rule set. Returns count archived.

    Replaces the three duplicated loops in:
    - execution_orchestrator.py:227-232
    - learning_orchestrator.phase4_commit:217-223
    - learning_orchestrator.phase5_reflect:250-254
    """
    rules = self.load_rules()
    kept = []
    archived_count = 0
    for r in rules:
        ur = update_rule_confidence(r, outcome.value)
        if ur is None:
            archived_count += 1
        else:
            kept.append(ur)
    self.save_rules(kept)
    return archived_count
```

Import `Outcome` and `update_rule_confidence` from `rule_evolution` at the
top of `reference_bank.py`.

### 3. Add `decay_inactive_rules()` to `ReferenceBank`

Same file. Absorbs the dead `decay_rules` function from `rule_evolution.py`.

```python
def decay_inactive_rules(self, days: int = 30) -> int:
    """
    Prune long-unused rules. A rule unused for > `days` has confidence
    multiplied by 0.99^(days_since_use - days). Rules that drop below 0.3
    are archived. Persists the updated rule set. Returns count archived.

    Called lazily by retrieve_rules() so stale rules are always pruned
    before reaching the prompt.
    """
```

Implementation: same math as the existing `decay_rules` in
`rule_evolution.py`, but reads from / writes to the Bank's own files.

### 4. Wire lazy decay + `last_used` updates into `retrieve_rules()`

Same file. At the top of `retrieve_rules()`:

```python
def retrieve_rules(self, input_type, trigger="field_extraction",
                   input_signature=None, top_k=10):
    # Slice 4: lazy decay
    self.decay_inactive_rules()

    # ... existing slice 1-3 logic ...

    # Slice 4: update last_used for retrieved rules
    retrieved_ids = {r["id"] for r in result}
    now = datetime.now().isoformat()
    all_rules = self.load_rules()
    for r in all_rules:
        if r["id"] in retrieved_ids:
            r["last_used"] = now
    self.save_rules(all_rules)

    return result
```

**Caveat:** this writes to disk on every retrieve. If performance becomes
a concern, batch the `last_used` updates (e.g. only write if the most
recent `last_used` is > 1 hour old). For now, simple is correct.

**Important:** strip `_source` from `all_rules` before `save_rules` —
`_source` is in-memory only (slice 1 contract).

### 5. Delete dead `decay_rules` from `rule_evolution.py`

File: `scripts/core/rule_evolution.py`

Delete the `decay_rules` function (lines 21-40). It's absorbed into the
Bank as `decay_inactive_rules`. Keep `update_rule_confidence` and the new
`Outcome` enum — both are used by the Bank.

### 6. Replace the three duplicated confidence-update loops

File: `scripts/orchestration/execution_orchestrator.py`

Lines 227-232 (the `for r in rules: ur = update_rule_confidence(r, 1.0)`
loop) → single call:

```python
bank.apply_outcome(Outcome.SUCCESS)
```

Remove the `from scripts.core.rule_evolution import update_rule_confidence`
import if no longer used.

File: `scripts/orchestration/learning_orchestrator.py`

`phase4_commit` lines 217-223 → `self.bank.apply_outcome(Outcome.SUCCESS)`

`phase5_reflect` lines 250-254 — **restructure to fix the bug**:

```python
def phase5_reflect(self, failure_info, existing_rules):
    # ... existing rule-generation logic (creates new_rules via add_rule) ...

    # Slice 4 bug fix: new repair rules skip the failure penalty.
    # Only EXISTING rules get penalized.
    new_rule_ids = {r["id"] for r in new_rules if r not in existing_rules}
    # Apply failure outcome to existing rules only
    existing_rules = self.bank.apply_outcome(Outcome.FAILURE)  # returns nothing useful here
    # Re-load after apply_outcome mutated the bank
    surviving_existing = self.bank.load_rules()
    surviving_existing = [r for r in surviving_existing if r["id"] not in new_rule_ids]

    return surviving_existing + new_rules
```

**The bug being fixed:** today, `phase5_reflect` creates new rules at
confidence 0.6, then calls `update_rule_confidence(rule, 0.2)` on ALL
rules including the new ones, dropping them to 0.55 before they ever fire.
After the fix, new rules keep their 0.6 confidence and get a fair chance.

The exact structure may need adjustment based on how `phase5_reflect`
currently threads state — the key invariant is: **new repair rules do not
receive the failure penalty; only pre-existing rules do.**

### 7. Tests

File: `tests/core/test_reference_bank.py`

Add:
- `test_apply_outcome_success_rewards_all` — 5-rule bank, all confidence
  0.80. `apply_outcome(Outcome.SUCCESS)` → all 5 at 0.82, support +1.
- `test_apply_outcome_failure_penalizes_all` — 5-rule bank, all 0.80.
  `apply_outcome(Outcome.FAILURE)` → all 5 at 0.75.
- `test_apply_outcome_failure_archives_below_threshold` — a rule at 0.32
  gets `apply_outcome(Outcome.FAILURE)` → drops to 0.27 → archived
  (returns count=1, rule gone from bank).
- `test_apply_outcome_returns_archived_count` — returns the number
  archived.
- `test_decay_inactive_rules_prunes_stale` — a rule with `last_used` 60
  days ago has confidence × 0.99^30.
- `test_decay_inactive_rules_archives_below_threshold` — if decay drops a
  rule below 0.3, it's archived.
- `test_retrieve_rules_triggers_lazy_decay` — calling `retrieve_rules`
  runs decay (verify by checking a stale rule's confidence was reduced
  after retrieve).
- `test_retrieve_rules_updates_last_used` — after `retrieve_rules`, the
  returned rules have `last_used` ≈ now (within test tolerance).
- `test_retrieve_rules_does_not_persist_source` — after `retrieve_rules`
  + lazy `save_rules`, `rules.jsonl` does not contain `_source` fields.

File: `tests/orchestration/test_learning_orchestrator.py`

Add:
- `test_phase5_reflect_new_rules_keep_creation_confidence` — after
  `phase5_reflect` creates repair rules at 0.6, those rules' confidence
  is still 0.6 (not 0.55).
- `test_phase5_reflect_existing_rules_penalized` — existing rules in the
  bank DO get the failure penalty.

File: `tests/orchestration/test_execution_orchestrator.py`

Update:
- Replace assertions on `update_rule_confidence` being called with
  assertions on `bank.apply_outcome(Outcome.SUCCESS)` being called.

## Acceptance criteria

- [ ] `bank.apply_outcome(Outcome.SUCCESS)` on a 5-rule bank increments
      all 5 confidences by 0.02 and supports by 1.
- [ ] `bank.apply_outcome(Outcome.FAILURE)` decrements all by 0.05 and
      archives any that drop below 0.3; returns the archived count.
- [ ] `retrieve_rules()` triggers lazy decay: a rule unused 60 days has
      confidence × 0.99^30.
- [ ] `retrieve_rules()` updates `last_used` on retrieved rules.
- [ ] After `phase5_reflect`, new repair rules' confidence equals their
      creation value (0.6), not 0.55.
- [ ] After `phase5_reflect`, existing rules DID receive the failure
      penalty.
- [ ] `decay_rules` is deleted from `rule_evolution.py` (absorbed into
      Bank).
- [ ] No duplicated confidence-update loop remains: `grep -r
      "update_rule_confidence" scripts/orchestration/` returns nothing.
- [ ] `_source` is never persisted to `rules.jsonl`.
- [ ] All existing tests pass.

## Out of scope

- `Outcome.PARTIAL` semantics (reserved, no-op today).
- Scheduled/cron decay (lazy is sufficient per PRD decision 13).
- Batching `last_used` writes for performance (correctness first; optimize
  later if needed).

## How to verify

```bash
cd /workspace
python -m pytest tests/core/test_reference_bank.py -v
python -m pytest tests/core/test_rule_evolution.py -v
python -m pytest tests/orchestration/ -v
python -m pytest tests/ -v

# Verify the duplication is gone:
grep -r "update_rule_confidence" scripts/orchestration/ || echo "OK: no orchestrator calls the math directly"
grep -r "decay_rules" scripts/ || echo "OK: dead function deleted"
```

## After this slice ships

Candidate 01 (Reference Bank deepening) is complete. Candidates 05 (Rule
schema) and 06 (confidence policy) are absorbed. The remaining
architecture-review candidates (02 Execution Orchestrator, 03 RALPH Loop,
04 sys.exit in io/) are now smaller — re-run
`/improve-codebase-architecture` to reassess.
