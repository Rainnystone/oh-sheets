# ADR-0001: Reference Bank owns its persistence

Date: 2026-06-27
Status: Accepted

## Context

The oh-sheets! v2 design spec ([§7.3][spec-7-3]) defines a strict layering:
`core/` is for "核心业务逻辑" (core business logic), and `io/` is for
"文件读写, 格式转换" (file read/write, format conversion). File I/O is
forbidden in `core/`.

An architecture review (2026-06-27) flagged `scripts/core/reference_bank.py`
as a §7.3 violation: the module is 100% file I/O — eight methods, each a
2-4 line `json.dump` / `json.load` / `_load_jsonl` wrapper. The natural fix
per the spec would be to move the file I/O to `io/` and let `core/` hold
only the business logic.

However, the same review found that the deeper problem is the Reference Bank
being **too shallow**: it stores things, but retrieval, knowledge-graph
expansion, and rule lifecycle — the actual domain behavior described in
spec §4.2 step 2 — are smeared across the orchestrators and four other
files. The fix is to **deepen** the Bank: make it own retrieval, expansion,
and lifecycle, with file I/O becoming a private implementation detail.

## Decision

The Reference Bank stays in `core/` and owns its file I/O as private methods
(`_load_jsonl`, `_save_jsonl`, `_load_json`, `_save_json`). We do **not**
下沉 the persistence to `io/`.

The Bank's public interface exposes domain behaviors only:
`retrieve_rules`, `expand_via_knowledge_graph`, `apply_outcome`,
`decay_inactive_rules`, etc. No caller touches `rules.jsonl`,
`anchors.json`, `success_patterns.jsonl`, or `knowledge_graph.json`
directly — those paths are private to the Bank.

## Rationale

The Reference Bank's core value is **encapsulating four files behind one
concept**. Splitting persistence to `io/` would re-fragment the concept the
Bank exists to unify — exactly the disease the architecture review
diagnosed (candidate 01: "Reference Bank is storage, not a domain concept").
Deep modules hide their persistence; the spec's §7.3 layering rule is a
means, not an end. The end is "a Reference Bank you can ask questions of,"
and that end is better served by keeping the file handles private.

This is the standard deep-module tradeoff (Ousterhout, _A Philosophy of
Software Design_): a module whose interface is small but whose
implementation is large. The four JSON files are the implementation; the
retrieval/expansion/lifecycle methods are the interface.

## Consequences

- **Positive:** Callers (orchestrators, prompt_builder) stop reaching into
  JSON files. The Bank's interface becomes the test surface. Dead code
  (`load_knowledge_graph` write-only, `record_success_pattern` second
  writer, `calculate_input_signature` bridge) gets either a caller or a
  deletion.
- **Positive:** Future architecture reviews will not re-suggest moving the
  file I/O to `io/`, because this ADR records the decision and its reason.
- **Negative:** `core/` technically violates §7.3's "no file I/O" rule.
  This is a documented, intentional deviation for one module, not a
  precedent. Other `core/` modules remain pure.
- **Neutral:** If a future storage backend is needed (e.g. SQLite for
  larger rule sets), the swap is contained inside the Bank — exactly
  because persistence is already private.

## Alternatives considered

1. **Move file I/O to `io/reference_bank_storage.py`, keep Bank in
   `core/`.** Rejected: this is the fragmentation the review diagnosed.
   The Bank would become a thin delegator to `io/`, regaining the
   shallowness we're trying to eliminate.
2. **Move the whole Bank to `io/`.** Rejected: the Bank's domain behavior
   (retrieval, expansion, lifecycle) is business logic, not I/O. `io/`
   forbids business logic per §7.3.
3. **Keep status quo (Bank = file I/O only, retrieval in orchestrator).**
   Rejected: this is the bug surface the review identified. The Bank
   stays shallow; orchestrators stay god modules.

## References

- Architecture review: `/tmp/architecture-review-20260627-040427.html`,
  candidate 01
- Design spec: [`docs/superpowers/specs/2026-04-05-reference-bank-v2-design.md`][spec]
  (§4.2 step 2 RETRIEVE CONTEXT, §7.3 layering rules)
- Domain glossary: [`CONTEXT.md`](../../CONTEXT.md) — Reference Bank entry

[spec]: ../superpowers/specs/2026-04-05-reference-bank-v2-design.md
[spec-7-3]: ../superpowers/specs/2026-04-05-reference-bank-v2-design.md#73-模块职责边界
