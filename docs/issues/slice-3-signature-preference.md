# Issue: Slice 3 — Signature preference + success-pattern unification

**PRD:** [`docs/prd/deepen-reference-bank.md`](deepen-reference-bank.md)
**Domain glossary:** [`CONTEXT.md`](../../CONTEXT.md)
**ADR:** [`0001-reference-bank-owns-persistence.md`](../adr/0001-reference-bank-owns-persistence.md)
**Slice:** 3 of 4 (depends on slice 2's `_source` tagging)
**Estimate:** Medium

## Context

Two problems this slice fixes:

1. **Signature preference is unwired.** `match_patterns` exists but the
   orchestrator doesn't use its output to prefer rules that succeeded on
   similar inputs. Spec §4.2 step 2 implies this preference.
2. **Success patterns are a mess.** Two writers
   (`execution_orchestrator` and `learning_orchestrator.phase4_commit`)
   write different schemas; neither populates the full spec §3.4 fields
   (`pattern_id`, `input_type`, `fields_extracted`, `rules_used`,
   `anchors_matched`). A third dead writer exists in
   `local_few_shot_memory.record_success_pattern`.

This slice unifies success-pattern writing into one Bank method and wires
signature-based rule preference into `retrieve_rules()`.

Read the PRD's "Confirmed design decisions" table (rows 8, 9, 10) and the
"Slice 3" section before starting.

## Tasks

### 1. Add `record_success_pattern()` to `ReferenceBank`

File: `scripts/core/reference_bank.py`

```python
def record_success_pattern(
    self,
    input_signature: str,
    input_type: str,
    extracted: dict,
    rules_used: list[str],
    anchors_matched: list[str],
    accuracy: float = 1.0,
) -> None:
    """
    Single writer for success patterns. Populates the full spec §3.4 schema:
    pattern_id (P001, P002, ...), input_signature, input_type,
    fields_extracted (keys of `extracted`), accuracy, rules_used,
    anchors_matched, created_at.
    Persists immediately to success_patterns.jsonl (append).
    """
```

`pattern_id` generation: `max(existing pattern numbers) + 1`, format
`P{N:03d}`. Same pattern as `add_rule`'s ID generation in slice 1.

### 2. Wire signature preference into `retrieve_rules()`

Same file. Add as step 5 (after KG expansion, before final sort):

```python
# Slice 3: signature preference
if input_signature is not None:
    matched_patterns = match_patterns(input_signature, self.load_success_patterns(), top_k=3)
    preferred_rule_ids = set()
    for p in matched_patterns:
        preferred_rule_ids.update(p.get("rules_used", []))
    # Boost: rules in preferred_rule_ids get _source="via_signature"
    # (in addition to or instead of their existing _source).
    # If a rule is already in the result set, upgrade its _source to
    # "via_signature" if it was "via_kg" (signature preference > KG).
    # If a rule is NOT in the result set but is in preferred_rule_ids,
    # add it with _source="via_signature".
```

`_source` precedence (highest to lowest): `via_signature` > `direct` >
`via_kg`. When deduping, keep the highest-precedence `_source`.

Wait — re-examine. `direct` means "matched the input_type+trigger filter
directly." `via_signature` means "succeeded on a signature-matched input
before." A rule can be both. Which wins? **Decision: `via_signature`
wins** — a rule that has historically succeeded on similar input is a
stronger signal than a rule that merely matches the input type. Update
the dedupe logic from slice 2 accordingly.

### 3. Replace the two existing success-pattern writers

File: `scripts/orchestration/execution_orchestrator.py`

Lines ~234-238 (the inline `patterns.append({...}); bank.save_success_patterns(patterns)`):
replace with:

```python
bank.record_success_pattern(
    input_signature=input_sig,
    input_type=input_type,  # the same one used for retrieve_rules
    extracted=extracted,
    rules_used=[r["id"] for r in rules_used_in_extraction],  # see note below
    anchors_matched=[a for a in anchors_used_in_extraction],  # see note below
    accuracy=1.0,
)
```

**Note on `rules_used` / `anchors_used`:** the orchestrator currently
doesn't track which rules/anchors were actually used in the extraction.
For slice 3, pass the full retrieved rule set (`retrieve_rules` return
value) as `rules_used` and the loaded anchors as `anchors_matched`. This
is an over-approximation (not all retrieved rules were actually used by
the LLM), but it's what spec §3.4 asks for and it's the best signal
available without LLM instrumentation. Document this in a code comment.

File: `scripts/orchestration/learning_orchestrator.py`

Lines ~208-213 (`phase4_commit`'s inline success-pattern append): same
replacement. `input_type` comes from the RALPH loop's sample input.

### 4. Delete the dead third writer

File: `scripts/memory/local_few_shot_memory.py`

Delete `record_success_pattern` (lines ~203-209, the function defined
after the `if __name__ == "__main__":` guard that reaches into
`core.reference_bank`). It has zero callers. The canonical writer now
lives on the Bank itself.

### 5. Rename misleading `match_patterns` branch

File: `scripts/core/signature_matcher.py`

The "similar" branch (line 30) does NOT compare signatures — it filters by
`accuracy >= threshold`. This is misleading. Rename and document:

```python
def match_patterns(signature: str, patterns: list, top_k: int = 3, threshold: float = 0.8) -> list:
    """
    Find success patterns for the input signature.

    1. Exact signature match: return matching patterns sorted by accuracy.
    2. No exact match: FALLBACK by accuracy — return patterns with
       accuracy >= threshold, sorted by accuracy. This is NOT a signature
       similarity computation; it returns historically-accurate patterns
       regardless of their signature. Renamed from "similar" to avoid
       implying signature comparison.

    True signature similarity would require vector embeddings and is out
    of scope (see PRD non-goals).
    """
    exact_matches = [p for p in patterns if p.get("input_signature") == signature]
    if exact_matches:
        return sorted(exact_matches, key=lambda x: x.get("accuracy", 0.0), reverse=True)[:top_k]

    # Accuracy-based fallback (not signature similarity)
    by_accuracy = [p for p in patterns if p.get("accuracy", 0.0) >= threshold]
    return sorted(by_accuracy, key=lambda x: x.get("accuracy", 0.0), reverse=True)[:top_k]
```

No behavior change — just renaming and honest docstring.

### 6. Tests

File: `tests/core/test_reference_bank.py`

Add:
- `test_retrieve_rules_signature_preference_exact` — given success pattern
  P1 (sig=S1, rules_used=[R001]), `retrieve_rules("pdf",
  input_signature=S1)` returns R001 with `_source="via_signature"`.
- `test_retrieve_rules_via_signature_overrides_via_kg` — if a rule is both
  `via_kg` and `via_signature`, the returned rule has
  `_source="via_signature"`.
- `test_record_success_pattern_populates_full_schema` — after
  `record_success_pattern(...)`, the saved pattern has `pattern_id`,
  `input_signature`, `input_type`, `fields_extracted`, `accuracy`,
  `rules_used`, `anchors_matched`, `created_at`.
- `test_record_success_pattern_generates_sequential_ids` — two calls
  produce P001, P002.
- `test_record_success_pattern_appends_not_overwrites` — existing patterns
  are preserved.

File: `tests/core/test_signature_matcher.py`

Update:
- Rename test `test_match_patterns_no_exact_match_returns_similar` →
  `test_match_patterns_no_exact_match_returns_by_accuracy_fallback`.
- Add assertion in docstring or comment that no signature comparison
  occurs in the fallback path.

File: `tests/orchestration/test_execution_orchestrator.py`,
`tests/orchestration/test_learning_orchestrator.py`

Update tests that asserted on `save_success_patterns` being called — they
should now assert on `record_success_pattern` being called with the right
fields.

## Acceptance criteria

- [ ] Given success patterns P1 (sig=S1, rules_used=[R001]) and input with
      sig S1, `retrieve_rules("pdf", input_signature=S1)` returns R001 with
      `_source` including `"via_signature"`.
- [ ] `record_success_pattern()` populates all spec §3.4 fields:
      `pattern_id`, `input_signature`, `input_type`, `fields_extracted`,
      `accuracy`, `rules_used`, `anchors_matched`, `created_at`.
- [ ] Only ONE success-pattern writer remains in the codebase
      (`bank.record_success_pattern`). The dead
      `local_few_shot_memory.record_success_pattern` is deleted. The two
      inline appenders in the orchestrators are gone.
- [ ] `match_patterns`'s fallback branch is renamed; docstring is honest
      about no signature comparison.
- [ ] `_source` precedence: `via_signature` > `direct` > `via_kg`.
- [ ] All existing tests pass.

## Out of scope

- Vector-embedding-based signature similarity (PRD non-goal).
- `apply_outcome` / lifecycle fold (slice 4).
- Tracking which rules the LLM *actually* used (would require LLM
  instrumentation; out of scope).

## How to verify

```bash
cd /workspace
python -m pytest tests/core/test_reference_bank.py -v
python -m pytest tests/core/test_signature_matcher.py -v
python -m pytest tests/orchestration/ -v
python -m pytest tests/ -v
```
