# Issue: Slice 1 — `retrieve_rules()` + input-type tagging

**PRD:** [`docs/prd/deepen-reference-bank.md`](deepen-reference-bank.md)
**Domain glossary:** [`CONTEXT.md`](../../CONTEXT.md)
**ADR:** [`0001-reference-bank-owns-persistence.md`](../adr/0001-reference-bank-owns-persistence.md)
**Slice:** 1 of 4 (must ship first; slices 2-4 depend on this)
**Estimate:** Small-medium

## Context

The Reference Bank is currently a shallow JSON store. This slice adds the
first real domain behavior — `retrieve_rules()` — and migrates rules from
the meaningless `"auto"` input-type tag to real types
(`pdf`/`excel`/`word`/`md`).

This slice is the foundation: slices 2 (KG expansion), 3 (signature
preference), and 4 (lifecycle fold) all build on `retrieve_rules()`.

Read the PRD's "Confirmed design decisions" table (rows 3, 4, 5, 17, 19)
and the "Slice 1" section before starting.

## Tasks

### 1. Add `retrieve_rules()` to `ReferenceBank`

File: `scripts/core/reference_bank.py`

```python
def retrieve_rules(
    self,
    input_type: str,
    trigger: str = "field_extraction",
    input_signature: str | None = None,   # reserved for slice 3; ignored in slice 1
    top_k: int = 10,
) -> list[dict]:
    """
    Filter rules by input_type ("auto" matches all) and trigger.
    Drop rules with confidence < 0.3.
    Sort by confidence descending.
    Dedupe by rule ID (keep highest-confidence copy).
    Tag each rule with _source="direct" (slice 1 only sets "direct";
    slices 2 and 3 add "via_kg" and "via_signature").
    Return top_k.
    """
```

Implementation notes:
- `_source` is an in-memory field only — do NOT persist it to `rules.jsonl`.
  Strip it before any `save_rules` call, or set it only on the returned
  copies.
- The `input_signature` parameter is accepted but unused in slice 1. This
  is intentional — it reserves the signature for slice 3 without changing
  the call sites again.
- `top_k=10` default; callers may override.

### 2. Add `add_rule()` typed constructor to `ReferenceBank`

Same file. Replaces the inline dict literals in `phase2_draft` and
`phase5_reflect`.

```python
def add_rule(
    self,
    input_type: str,
    trigger: str,
    field: str,
    action: str,
    confidence: float = 0.5,
    **extra,
) -> dict:
    """
    Construct a rule with a unique ID (max(existing IDs) + 1, NOT len + 1 —
    fixes the R001 collision bug), required fields, and created_at.
    Does NOT auto-save; caller calls save_rules() to persist a batch.
    Returns the constructed rule dict.
    """
```

ID generation: load existing rules, find max numeric ID, +1, format as
`R{N:03d}`. This fixes the collision where `phase2_draft` and
`phase5_reflect` both generate `R001`.

### 3. Add `_determine_input_type()` helper in `execution_orchestrator`

File: `scripts/orchestration/execution_orchestrator.py`

```python
def _determine_input_type(file_path: str) -> str:
    """Return 'pdf' | 'excel' | 'word' | 'md' based on file extension.
    Unknown extensions default to 'md' (text)."""
```

Map: `.pdf` → `pdf`; `.xlsx`/`.xls`/`.xlsm`/`.xlsb`/`.xltx`/`.xltm` →
`excel`; `.doc`/`.docx` → `word`; `.md`/`.txt` and everything else → `md`.

### 4. Migrate call sites

- `execution_orchestrator.py` line 107: `bank.load_rules()` →
  `bank.retrieve_rules(input_type=_determine_input_type(args.input))`
- `learning_orchestrator.py` `phase2_draft` line 145:
  `"input_type": "auto"` → real input type. The phase method has access to
  the sample file path — derive input_type from it. If the phase method
  signature doesn't currently carry the file path, add it as a parameter
  (preferred) or read from `self.sample_path` if the RALPHLoop already
  holds it.
- `learning_orchestrator.py` `phase5_reflect` line 241: add `input_type`
  to the `when` dict. Use the same input_type the failing extraction was
  attempting (pass it through `failure_info` if not already there).
- `learning_orchestrator.py` `phase3_test` line 176: `load_rules()` →
  `retrieve_rules(input_type=...)`. The phase method needs the input_type;
  thread it through from `run_full_cycle`.

### 5. Tests

File: `tests/core/test_reference_bank.py`

Add:
- `test_retrieve_rules_filters_by_input_type` — given pdf + excel rules,
  `retrieve_rules("pdf")` returns only pdf + auto rules.
- `test_retrieve_rules_auto_wildcard_matches_all` — `auto` rules appear in
  every input_type query.
- `test_retrieve_rules_drops_low_confidence` — rules with confidence < 0.3
  are excluded.
- `test_retrieve_rules_sorts_by_confidence_desc` — highest confidence first.
- `test_retrieve_rules_dedupes_by_id` — duplicate IDs collapse to the
  highest-confidence copy.
- `test_retrieve_rules_tags_source_direct` — every returned rule has
  `_source == "direct"`.
- `test_add_rule_generates_unique_ids` — two `add_rule` calls produce
  R001, R002; calling after existing R005 produces R006 (not R001).
- `test_add_rule_does_not_persist_until_saved` — `add_rule` doesn't write
  to disk; `save_rules([rule])` does.

File: `tests/orchestration/test_execution_orchestrator.py`

Add:
- `test_determine_input_type` — parametrized over extensions.

Update existing tests if they asserted on `load_rules` being called — they
should now assert on `retrieve_rules`.

## Acceptance criteria

- [ ] `retrieve_rules("pdf")` returns only `pdf` + `auto` rules, sorted by
      confidence desc, no rules with confidence < 0.3, no duplicate IDs.
- [ ] Every returned rule has `_source == "direct"`.
- [ ] New rules created via `add_rule()` carry real input types
      (`pdf`/`excel`/`word`/`md`), never `"auto"`.
- [ ] Existing `"auto"` rules still match all input types (wildcard).
- [ ] `add_rule()` generates IDs as `max(existing) + 1`, not `len + 1`.
- [ ] `_source` is never persisted to `rules.jsonl`.
- [ ] All existing tests pass.
- [ ] No layer violations introduced (orchestration does not call LLMs or
      do file I/O beyond what it already does — this slice should reduce
      file I/O in orchestrators, not add it).

## Out of scope

- KG expansion (slice 2)
- Signature preference (slice 3)
- `apply_outcome` / lifecycle fold (slice 4)
- Success-pattern unification (slice 3)
- Moving persistence to `io/` (rejected, ADR-0001)
- Fixing the `phase5_reflect` penalize-fresh-repair-rules bug (slice 4)

## How to verify

```bash
cd /workspace
python -m pytest tests/core/test_reference_bank.py -v
python -m pytest tests/orchestration/ -v
python -m pytest tests/ -v  # full suite, ensure no regressions
```
