# PRD: Deepen the Reference Bank (candidate 01)

**Source:** Architecture review 2026-06-27, candidate 01
**Status:** Approved for implementation
**Design thread:** This session's grilling (5 user-confirmed decisions + maintainer-decided technical details)
**Domain glossary:** [`CONTEXT.md`](../../CONTEXT.md)
**Architectural decision:** [ADR-0001](0001-reference-bank-owns-persistence.md)

## Problem

The Reference Bank is the load-bearing domain concept (spec §4.2 step 2:
"RETRIEVE CONTEXT … 知识图谱扩展: 激活关联规则"), but the implementation is a
shallow JSON store. Retrieval is inlined in the orchestrators; the knowledge
graph is write-only; rule lifecycle (confidence, decay, archival) is
duplicated across three callers with no test asserting the actual policy.

Symptoms (from the architecture review):

- `load_knowledge_graph` has zero callers — the knowledge graph is write-only.
- All rules are tagged `input_type: "auto"` — retrieval by input type is a
  no-op today.
- Confidence < 0.3 rules still reach the LLM prompt (filtered only after
  extraction, not before).
- `decay_rules` is dead code (never called; `last_used` is never written).
- `phase5_reflect` creates repair rules at confidence 0.6, then immediately
  penalizes them to 0.55 before they ever fire (likely bug).
- `phase2_draft` and `phase5_reflect` both generate rule ID `R001` — ID
  collisions.
- Three copies of the "reward all / penalize all" confidence-update loop
  across `execution_orchestrator`, `learning_orchestrator.phase4_commit`,
  `learning_orchestrator.phase5_reflect`.

## Goal

Deepen the Reference Bank so it owns its actual domain behavior: retrieval,
knowledge-graph expansion, and rule lifecycle. The orchestrators stop
reaching into JSON files and start asking the Bank questions. The Bank's
interface becomes the test surface.

This candidate absorbs:
- **Candidate 05** (Rule schema fragmentation) — the Bank owns Rule
  construction via a typed schema.
- **Candidate 06** (confidence-update policy duplication) — the policy lands
  inside the Bank as `apply_outcome`.

## Non-goals

- Fixing the orchestrator god modules (candidates 02, 03) — those shrink as
  a side effect but are not the target of this PRD.
- Fixing `sys.exit` in `io/` modules (candidate 04) — independent, can be
  done in parallel.
- Moving persistence to `io/` — explicitly rejected, see ADR-0001.
- Vector-embedding-based signature similarity — out of scope; we reuse the
  existing `match_patterns` accuracy-threshold fallback.
- Auto-constructing `often_follows` knowledge-graph edges — reserved for a
  future PR; the edge type is supported but not auto-populated.

## Confirmed design decisions

These were resolved during grilling. Each is locked unless reopened.

| # | Decision | Value | Source |
|---|----------|-------|--------|
| 1 | Retrieval target behavior | Full chain: filter + KG expansion + signature preference | User-confirmed |
| 2 | Build approach | Sliced into 4 sequential slices, each independently shippable | Maintainer-decided (best practice) |
| 3 | Slice 1 scope | `retrieve_rules()` + input-type tagging + `auto` wildcard | User-confirmed |
| 4 | Input-type tagging | Real types (`pdf`/`excel`/`word`/`md`), not `auto` | User-confirmed |
| 5 | Legacy `auto` rules | Treated as wildcard matching any input type | User-confirmed |
| 6 | KG expansion hops | 1 hop (subset of multi-hop; extensible) | Maintainer-decided |
| 7 | KG edge types | `uses_anchor`, `often_follows` (per spec §3.5) | Maintainer-decided |
| 8 | Rule provenance | Internal `_source` field (`direct`/`via_kg`/`via_signature`), not persisted | Maintainer-decided |
| 9 | Signature similarity | Reuse `match_patterns`; rename misleading "similar" branch; no embeddings | Maintainer-decided |
| 10 | `top_k` for signature preference | 3 (existing default) | Maintainer-decided |
| 11 | Lifecycle interface | `bank.apply_outcome(outcome: Outcome) -> int` (returns archived count) | Maintainer-decided |
| 12 | `Outcome` enum | `SUCCESS` (1.0), `FAILURE` (0.2), `PARTIAL` (0.5, reserved) | Maintainer-decided |
| 13 | Decay trigger | Lazy — at retrieval time, not on a schedule | Maintainer-decided |
| 14 | Decay threshold | 30 days inactive → confidence × `0.99^(days-30)` (existing constants) | Maintainer-decided |
| 15 | `last_used` updates | Updated for rules hit by `retrieve_rules` | Maintainer-decided |
| 16 | `phase5_reflect` bug fix | New repair rules skip the failure-penalty pass; only existing rules penalized | Maintainer-decided |
| 17 | Rule ID generation | `max(existing IDs) + 1`, not `len + 1` — fixes collision | Maintainer-decided |
| 18 | Persistence layer | Stays in Bank as private methods (ADR-0001) | Maintainer-decided |
| 19 | Quality filter threshold | 0.3 (matches spec §4.3 archive threshold; safe minimum) | Maintainer-decided |

## Target interface (the deepened Reference Bank)

```python
class ReferenceBank:
    # --- retrieval (slice 1 + 2 + 3) ---
    def retrieve_rules(
        self,
        input_type: str,
        trigger: str = "field_extraction",
        input_signature: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """
        Full-chain retrieval:
        1. Lazy decay (slice 4) — prune stale rules, update last_used.
        2. Filter by input_type ("auto" matches all) and trigger.
        3. Quality filter: drop confidence < 0.3.
        4. KG expansion (slice 2): 1-hop via uses_anchor / often_follows.
        5. Signature preference (slice 3): boost rules from matching
           success_patterns' rules_used.
        6. Sort by confidence desc; dedupe by rule ID (keep highest).
        7. Tag each rule with _source: direct / via_kg / via_signature.
        8. Return top_k.
        """

    def query_anchors(self, field: str | None = None) -> dict | list:
        """Slice 2: query anchors by field, or all if field is None."""

    # --- lifecycle (slice 4) ---
    def apply_outcome(self, outcome: "Outcome") -> int:
        """
        Reward/penalize all rules per outcome. Archives rules that drop
        below 0.3. Returns count archived. Replaces the 3 duplicated loops.
        """

    def decay_inactive_rules(self, days: int = 30) -> int:
        """Prune long-unused rules. Called lazily by retrieve_rules.
        Returns count pruned."""

    # --- construction (slice 1) ---
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
        Typed rule construction. Generates ID as max(existing)+1.
        Validates required fields. Replaces inline dict literals in
        phase2_draft and phase5_reflect.
        """

    # --- success patterns (slice 3) ---
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
        Single writer for success patterns. Populates the full spec §3.4
        schema (pattern_id, input_type, fields_extracted, rules_used,
        anchors_matched). Replaces the two existing writers.
        """
```

## Slices

Four sequential slices. Each is independently shippable, independently
testable, and leaves the codebase in a working state.

### Slice 1: `retrieve_rules()` + input-type tagging

**Behavior:** Filter + quality-filter + sort + dedupe. No KG, no signature
preference yet. Input-type tagging migrated from `"auto"` to real types.

**Files touched:**
- `scripts/core/reference_bank.py` — add `retrieve_rules()`, `add_rule()`
- `scripts/orchestration/execution_orchestrator.py` — add
  `_determine_input_type(file_path)`; replace `load_rules()` with
  `retrieve_rules(input_type)` at line 107
- `scripts/orchestration/learning_orchestrator.py` — `phase2_draft` line 145
  (`"auto"` → real type from sample file), `phase5_reflect` line 241 (add
  `input_type` to `when`), `phase3_test` line 176 (`load_rules()` →
  `retrieve_rules()`)
- `tests/core/test_reference_bank.py` — add `retrieve_rules` tests
  (filter / sort / dedupe / quality-filter / `auto` wildcard)
- `tests/orchestration/` — update for input-type judgment

**Out of scope for slice 1:** KG expansion, signature preference, lifecycle
fold, success-pattern unification.

**Acceptance:**
- `retrieve_rules("pdf")` returns only `pdf` + `auto` rules, sorted by
  confidence desc, no rules with confidence < 0.3, no duplicate IDs.
- New rules created via `add_rule()` carry real input types.
- Existing `"auto"` rules still match all input types.
- All existing tests pass.

### Slice 2: Knowledge-graph expansion (1 hop)

**Behavior:** `retrieve_rules()` activates 1-hop-related rules via
`uses_anchor` and `often_follows` edges. `query_anchors()` added.

**Files touched:**
- `scripts/core/reference_bank.py` — add `_expand_via_kg(rule_ids)`,
  `query_anchors()`; integrate into `retrieve_rules()` step 4
- `scripts/orchestration/learning_orchestrator.py` — `phase2_draft` auto-creates
  `uses_anchor` edges when a rule references an anchor
- `scripts/core/prompt_builder.py` — optionally render `_source` provenance
  in few-shot formatting
- `tests/core/test_reference_bank.py` — KG expansion tests
- `tests/orchestration/test_learning_orchestrator.py` — `uses_anchor` edge
  creation test

**Out of scope:** `often_follows` auto-construction (edge type supported but
not auto-populated), signature preference.

**Acceptance:**
- Given a rule R001 with a `uses_anchor` edge to anchor A1, and a rule R002
  also using A1, `retrieve_rules()` for an input matching R001 also returns
  R002 with `_source="via_kg"`.
- `query_anchors("vendor_name")` returns the anchor for that field.

### Slice 3: Signature preference + success-pattern unification

**Behavior:** `retrieve_rules()` boosts rules that succeeded on
signature-matched inputs. Single `record_success_pattern()` writer replaces
the two existing writers; full spec §3.4 schema populated.

**Files touched:**
- `scripts/core/reference_bank.py` — add `record_success_pattern()`;
  integrate signature preference into `retrieve_rules()` step 5; deprecate
  direct `save_success_patterns()` callers
- `scripts/core/signature_matcher.py` — rename misleading "similar" branch
  to `by_accuracy_fallback`; docstring clarifies no signature comparison
- `scripts/orchestration/execution_orchestrator.py` — replace inline
  success-pattern append (lines 234-238) with `record_success_pattern()`
- `scripts/orchestration/learning_orchestrator.py` — replace inline
  success-pattern append (lines 208-213) with `record_success_pattern()`
- `scripts/memory/local_few_shot_memory.py` — delete dead
  `record_success_pattern` wrapper (lines 203-209)
- `tests/core/test_reference_bank.py` — signature preference tests
- `tests/core/test_signature_matcher.py` — updated for rename

**Out of scope:** `apply_outcome` lifecycle fold (slice 4).

**Acceptance:**
- Given success patterns P1 (sig=S1, rules_used=[R001]) and input with sig
  S1, `retrieve_rules("pdf", input_signature=S1)` returns R001 with
  `_source` including `"via_signature"`.
- `record_success_pattern()` populates `pattern_id`, `input_type`,
  `fields_extracted`, `rules_used`, `anchors_matched` (spec §3.4).
- Only one success-pattern writer remains in the codebase.

### Slice 4: Lifecycle fold (absorbs candidate 06)

**Behavior:** `apply_outcome(Outcome)` and `decay_inactive_rules()` land in
the Bank. Three duplicated confidence-update loops deleted. Lazy decay at
retrieval time. `phase5_reflect` penalize-fresh-repair-rules bug fixed.

**Files touched:**
- `scripts/core/reference_bank.py` — add `apply_outcome()`,
  `decay_inactive_rules()`; call decay lazily inside `retrieve_rules()`;
  update `last_used` on retrieved rules
- `scripts/core/rule_evolution.py` — keep `update_rule_confidence()` (pure
  math, used internally by Bank); delete `decay_rules()` (absorbed into Bank
  as `decay_inactive_rules`)
- `scripts/orchestration/execution_orchestrator.py` — replace inline loop
  (lines 227-232) with `bank.apply_outcome(Outcome.SUCCESS)`
- `scripts/orchestration/learning_orchestrator.py` — replace
  `phase4_commit` loop (217-223) with `apply_outcome(SUCCESS)`;
  restructure `phase5_reflect` (236-254) so new rules skip penalty, only
  existing rules get `apply_outcome(FAILURE)`
- `tests/core/test_reference_bank.py` — `apply_outcome` tests (SUCCESS
  rewards all, FAILURE penalizes all + archives < 0.3, PARTIAL reserved),
  lazy decay test
- `tests/orchestration/test_learning_orchestrator.py` — assert new repair
  rules keep their creation confidence after reflect

**Acceptance:**
- `bank.apply_outcome(Outcome.SUCCESS)` on a 5-rule bank increments all 5
  confidences by 0.02; `apply_outcome(Outcome.FAILURE)` decrements all by
  0.05 and archives any that drop below 0.3.
- `retrieve_rules()` triggers lazy decay: a rule unused for 60 days has
  confidence × `0.99^30`.
- After `phase5_reflect`, new repair rules' confidence equals their creation
  value (0.6), not 0.55.
- No duplicated confidence-update loop remains in the codebase
  (`grep "update_rule_confidence" scripts/orchestration/` returns nothing).

## Test strategy

Each slice has a focused test surface on the Bank's interface — no
subprocess mocks, no LLM mocks for retrieval/lifecycle logic.

| Slice | New tests | Updated tests |
|-------|-----------|---------------|
| 1 | `retrieve_rules` filter/sort/dedupe/quality/`auto`-wildcard | orchestrator input-type judgment |
| 2 | KG 1-hop expansion, `query_anchors`, `uses_anchor` edge creation | prompt_builder provenance rendering |
| 3 | signature preference, `record_success_pattern` schema completeness | signature_matcher rename |
| 4 | `apply_outcome` SUCCESS/FAILURE/archive, lazy decay, `last_used` update | `phase5_reflect` new-rule-no-penalty |

## Risks

- **Data migration:** Existing `"auto"` rules continue to work as wildcards.
  No migration script needed; the `auto` semantics are forward-compatible.
- **Behavioral change:** Slice 1's quality filter (< 0.3 rules no longer
  reach the prompt) may change extraction results for templates with many
  low-confidence rules. This is the intended bug fix, not a regression.
- **Slice ordering:** Slices must ship in order 1→2→3→4. Slice 2 depends on
  slice 1's `retrieve_rules` existing; slice 3 depends on slice 2's
  `_source` tagging; slice 4's lazy decay must run inside slice 1's
  `retrieve_rules`.

## Open questions deferred to `/implement`

These are implementation details, not design decisions. Each `/implement`
session resolves them in context:

- Exact `pattern_id` format (sequential `P001` vs UUID).
- Whether `add_rule` should auto-write to disk or batch.
- Whether `decay_inactive_rules` writes the decayed state immediately or
  lets the next `save_rules` persist it.

## Reference

- Architecture review HTML: `/tmp/architecture-review-20260627-040427.html`
- Domain glossary: [`CONTEXT.md`](../../CONTEXT.md)
- ADR: [`0001-reference-bank-owns-persistence.md`](0001-reference-bank-owns-persistence.md)
- Design spec: [`docs/superpowers/specs/2026-04-05-reference-bank-v2-design.md`](../superpowers/specs/2026-04-05-reference-bank-v2-design.md)
