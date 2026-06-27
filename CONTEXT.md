# oh-sheets! Domain Glossary

The ubiquitous language for the oh-sheets! project. Terms here are the canonical
names used in code, docs, and conversation. When a term is sharpened during
design, update it here.

> Source of truth for the v2 design:
> [`docs/superpowers/specs/2026-04-05-reference-bank-v2-design.md`](docs/superpowers/specs/2026-04-05-reference-bank-v2-design.md)

## Core concepts

### Reference Bank
**The load-bearing domain concept.** A structured scene reference library that
owns three behaviors: **retrieval** (filter rules by input type/trigger, query
anchors by field), **knowledge-graph expansion** (activate related rules via
edges), and **rule lifecycle** (confidence updates, decay, archival).

Not merely a JSON store — the retrieval and lifecycle behavior is what makes it
a Reference Bank rather than four file paths. Persistence is a private
implementation detail behind the interface.

See [ADR-0001](docs/adr/0001-reference-bank-owns-persistence.md) for the
decision to keep file I/O inside the Reference Bank rather than下沉 to `io/`.

### RALPH Loop
The 5-phase learning cycle: ANALYZE → DRAFT → TEST → COMMIT / REFLECT.
On TEST failure, REFLECT generates repair rules and retries TEST, up to 5
rounds. The retry policy is the defining behavior — not the individual phases.

### Signature Guard
Routes an input file by comparing its signature against known success
patterns. Decides: execute directly / retrieve similar patterns / trigger
learning. Note: "signature" is overloaded in the codebase — see _Signatures_
below.

## Data structures

### Anchor
A spatial or visual locator. Types: `text_match`, `regex`, `spatial`,
`visual`. Roles: `label`, `value_matcher`, `section_start`, `section_end`,
`table_start`, `visual_locator`.

### Rule
A predicate-style structured assertion: `WHEN + CONDITION → THEN`, with
`confidence` (0.0–1.0) and `support` (integer times-used count). Rules with
`confidence < 0.3` are archived (filtered out of retrieval, not deleted).

The `when.input_type` field tags a rule by the input type it was learned from
(`pdf` / `excel` / `word` / `md`). The special value `"auto"` is a **wildcard**
matching any input type — used by legacy rules created before input-type
tagging. New rules always carry a real input type.

Rules retrieved from the Bank carry an internal `_source` field
(`"direct"` / `"via_kg"` / `"via_signature"`) so the prompt builder can
optionally show provenance. `_source` is not persisted.

### Success Pattern
A record of a successful extraction: input signature, accuracy, rules used,
anchors matched, fields extracted. Used to (a) fast-track identical inputs
(exact signature match) and (b) prefer rules that succeeded on similar inputs.

### Knowledge Graph
A graph of relationships between rules and anchors. Edge types:
`uses_anchor` (rule depends on anchor) and `often_follows` (rule frequently
fires after another rule). Used during retrieval to expand the active rule set
by 1 hop from directly-matched rules.

### Schema
The field mapping contract between input and target Excel. Fields map to
cells with types; `formula_constraints` list cells whose formulas must not be
overwritten. The schema is the validation surface for extracted data.

## Operational terms

### Outcome
An enum describing extraction result, passed to the Bank's lifecycle method:
`SUCCESS` (reward all rules), `FAILURE` (penalize all rules), `PARTIAL`
(reserved for future partial-success semantics). Replaces magic numbers
`1.0` / `0.2` previously inline at call sites.

### Decay
Long-unused rules lose confidence over time. Decay is applied lazily — at
retrieval time, not on a schedule — so stale rules are always pruned before
they reach the prompt. Threshold: 30 days inactive → confidence ×
`0.99^(days - 30)`.

## Layering rules

From spec §7.3, with one documented deviation:

| Layer | Responsibility | Forbidden |
|-------|---------------|-----------|
| `orchestration/` | Flow orchestration | Direct LLM calls, file I/O, concrete logic |
| `core/` | Core business logic | Cross-layer calls |
| `extraction/` | LLM calls, multimodal | File I/O |
| `io/` | File I/O, format conversion | Business logic |
| `memory/` | Persistence, history | LLM calls |
| `utils/` | Stateless utilities | Stateful operations |

**Deviation (ADR-0001):** The Reference Bank lives in `core/` and owns its
file I/O privately. Rationale: encapsulating four files behind one concept is
the Bank's core value; splitting persistence to `io/` would re-fragment the
concept the Bank exists to unify.

## _Signatures_ (disambiguation)

The word "signature" is overloaded in the codebase. Three distinct meanings:

1. **Input signature** — MD5 of input file content. Used by `match_patterns`
   for exact-match routing. (Currently the only one wired end-to-end.)
2. **Template signature** — SHA256 of a layout profile. Used by
   `compare_layout_profiles` for layout similarity. (Currently dead code.)
3. **Signature field** — the `signature` / `input_signature` / `template_signature`
   fields stored in success patterns and memory's summary rules.

When the spec says "签名守卫" / "SIGNATURE CHECK" it means #1.
