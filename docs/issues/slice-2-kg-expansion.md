# Issue: Slice 2 — Knowledge-graph expansion (1 hop)

**PRD:** [`docs/prd/deepen-reference-bank.md`](deepen-reference-bank.md)
**Domain glossary:** [`CONTEXT.md`](../../CONTEXT.md)
**ADR:** [`0001-reference-bank-owns-persistence.md`](../adr/0001-reference-bank-owns-persistence.md)
**Slice:** 2 of 4 (depends on slice 1's `retrieve_rules` existing)
**Estimate:** Medium

## Context

The knowledge graph (`knowledge_graph.json`) is currently write-only —
`load_knowledge_graph` has zero callers. Spec §4.2 step 2 says retrieval
should "知识图谱扩展: 激活关联规则" (expand via knowledge graph: activate
related rules). This slice wires the graph into `retrieve_rules()` as a
1-hop expansion.

Slice 1 already added `retrieve_rules()` with `_source="direct"` tagging.
This slice adds a 4th step to retrieval: after filtering+sorting, expand
the result set by 1 hop via `uses_anchor` and `often_follows` edges, tagging
expanded rules `_source="via_kg"`.

Read the PRD's "Confirmed design decisions" table (rows 6, 7, 8) and the
"Slice 2" section before starting.

## Tasks

### 1. Add `_expand_via_kg()` private method to `ReferenceBank`

File: `scripts/core/reference_bank.py`

```python
def _expand_via_kg(self, direct_rule_ids: set[str]) -> list[dict]:
    """
    Load the knowledge graph. For each rule in direct_rule_ids, find
    1-hop neighbors via 'uses_anchor' and 'often_follows' edges.
    Return the neighbor rules (not already in direct_rule_ids) with
    _source="via_kg" set.
    """
```

Edge semantics:
- `uses_anchor`: if rule R001 uses anchor A1, and rule R002 also uses A1,
  then R001 → R002 (and R002 → R001). Symmetric for this edge type.
- `often_follows`: if edge {from: R001, to: R002, relation:
  "often_follows"}, then when R001 is in the direct set, R002 is a
  candidate. Directional.

1 hop means: only direct neighbors of direct rules. Do not recurse.

### 2. Integrate KG expansion into `retrieve_rules()`

Same file. Insert as step 4 (after quality filter, before sort):

```
1. Filter by input_type ("auto" wildcard) + trigger
2. Quality filter: drop confidence < 0.3
3. (Slice 2) Expand: collect direct rule IDs, call _expand_via_kg,
   append the neighbors with _source="via_kg"
4. Sort by confidence desc
5. Dedupe by ID (keep highest-confidence; if a rule is both direct and
   via_kg, direct wins — keep _source="direct")
6. Return top_k
```

Note on dedupe: if a rule appears both as direct and via_kg, keep the
direct version (preferred source). This prevents the same rule appearing
twice and ensures provenance reflects the primary match path.

### 3. Add `query_anchors()` method

Same file.

```python
def query_anchors(self, field: str | None = None) -> dict | list:
    """
    If field is given, return the anchor(s) for that field (dict if one,
    list if multiple — match the existing anchors.json structure).
    If field is None, return all anchors.
    """
```

This is the anchor-side retrieval that spec §4.2 step 2 also implies
("检索相关 … 锚点"). Slice 1 didn't touch anchors; slice 2 adds the
retrieval interface.

### 4. Auto-create `uses_anchor` edges in `phase2_draft`

File: `scripts/orchestration/learning_orchestrator.py`

When `phase2_draft` creates a rule that references an anchor (via
`add_rule`'s `**extra` or an explicit anchor parameter), auto-create a
`uses_anchor` edge in the knowledge graph:

```python
{"from": rule_id, "to": anchor_id, "relation": "uses_anchor", "weight": 1.0}
```

Use `bank.save_knowledge_graph()` to persist. If the edge already exists,
skip (idempotent).

Implementation note: this requires `phase2_draft` to know which anchor a
rule uses. If the current `phase2_draft` doesn't carry that info, add it
to the rule's `then` dict (e.g. `then: {action: "extract_after_anchor",
anchor: "anchor_id"}`) and read it from there.

### 5. Optionally render `_source` in prompt_builder

File: `scripts/core/prompt_builder.py`

In `format_rules_as_few_shot`, if a rule has `_source != "direct"`, append
a provenance note to the few-shot line:

```
规则 R005 [置信度: 0.78, 来源: 知识图谱关联]:
```

This is optional polish — the LLM benefits from knowing a rule was inferred
rather than directly matched. Keep it minimal; don't restructure the
prompt.

### 6. Tests

File: `tests/core/test_reference_bank.py`

Add:
- `test_retrieve_rules_expands_via_uses_anchor` — given rules R001, R002
  both using anchor A1, `retrieve_rules` matching R001 also returns R002
  with `_source="via_kg"`.
- `test_retrieve_rules_expands_via_often_follows` — given edge
  `R001 →often_follows→ R002`, `retrieve_rules` matching R001 returns R002
  via KG.
- `test_retrieve_rules_direct_wins_over_via_kg` — if a rule is both direct
  and via_kg, the returned rule has `_source="direct"`.
- `test_retrieve_rules_kg_1_hop_only` — R001 → R002 → R003; matching R001
  returns R002 but NOT R003.
- `test_query_anchors_by_field` — returns the anchor for the given field.
- `test_query_anchors_all` — returns all anchors when field is None.

File: `tests/orchestration/test_learning_orchestrator.py`

Add:
- `test_phase2_draft_creates_uses_anchor_edge` — after phase2_draft with a
  rule referencing anchor A1, the knowledge graph has a `uses_anchor` edge
  from that rule to A1.
- `test_phase2_draft_edge_creation_idempotent` — running phase2_draft twice
  for the same rule+anchor doesn't duplicate the edge.

## Acceptance criteria

- [ ] Given a rule R001 with a `uses_anchor` edge to anchor A1, and a rule
      R002 also using A1, `retrieve_rules("pdf")` for an input matching
      R001 also returns R002 with `_source="via_kg"`.
- [ ] KG expansion is 1 hop only — no transitive expansion.
- [ ] A rule that is both direct and via_kg is returned once with
      `_source="direct"`.
- [ ] `query_anchors("vendor_name")` returns the anchor for that field.
- [ ] `phase2_draft` auto-creates `uses_anchor` edges; edge creation is
      idempotent.
- [ ] `load_knowledge_graph` now has a caller (was zero callers before).
- [ ] All existing tests pass.

## Out of scope

- `often_follows` auto-construction (the edge type is supported in
  expansion, but not auto-created — reserved for future work).
- Multi-hop expansion (1 hop only; extensible later).
- Signature preference (slice 3).
- Lifecycle fold (slice 4).

## How to verify

```bash
cd /workspace
python -m pytest tests/core/test_reference_bank.py -v
python -m pytest tests/orchestration/test_learning_orchestrator.py -v
python -m pytest tests/ -v
```
