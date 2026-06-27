# Roadmap: Orchestration & IO cleanup (post Reference-Bank deepening)

**Source:** Re-diagnosis 2026-06-27, after candidate 01 (Reference Bank) merged
**Status:** Proposed — slices 5 & 6 approved for this session
**Predecessor:** [`deepen-reference-bank.md`](deepen-reference-bank.md) (candidate 01, DONE)
**Domain glossary:** [`CONTEXT.md`](../../CONTEXT.md)

## Where we are

Candidate 01 deepened the Reference Bank into a real domain concept — it owns
retrieval, KG expansion, signature preference, and rule lifecycle behind one
interface (4 slices, merged via PR #2 and #3). Candidates 05 (rule schema
fragmentation) and 06 (confidence-update duplication) were absorbed into 01.

This roadmap covers what 01 deliberately left as non-goals: the orchestrator
god modules and `sys.exit` leaking out of `io/`. It also records one new
finding the re-diagnosis surfaced.

## Remaining candidates (re-derived from current code)

### Candidate 02 — `execution_orchestrator` is a god function

`run_orchestrator` ([execution_orchestrator.py:95](../../scripts/orchestration/execution_orchestrator.py)) is one ~175-line
function inlining seven responsibilities: load schema/input → retrieve rules →
match patterns → detect signature mismatch → degradation extraction →
validation → formula-conflict detection → temp-file → `write_excel` → logging
→ `apply_outcome` → `record_success_pattern` → result formatting. Each branch
duplicates the `print(json) + log_execution + return 1` failure shape.

Symptom of candidate 04 leaking in: the call site wraps `write_excel` in
`except SystemExit` (line 198) because `write_excel` exits the process instead
of returning. That hack disappears once candidate 04 is fixed.

### Candidate 03 — `learning_orchestrator` layering violations

`RALPHLoop` phases do file I/O directly (`phase1_analyze` opens `sample_input`
at line 120; `run_full_cycle` writes `schema.json`) and the orchestrator owns
its own `log_execution` helper. Per `CONTEXT.md` layering rules, `orchestration/`
is forbidden from file I/O — that belongs in `io/` or behind the Bank. Less
urgent than 02 because the phases are individually coherent; deferred.

### Candidate 04 — `sys.exit` inside `io/` and `utils/` function bodies

`sys.exit` is a process-level control-flow primitive. It belongs only in
`__main__` blocks. Today it is called **inside** library functions:

- [`excel_writer.write_excel`](../../scripts/io/excel_writer.py) lines 112, 115 —
  forces `execution_orchestrator` to catch `SystemExit`
- [`data_diff.compare_excel`](../../scripts/io/data_diff.py) lines 26, 29, 32
- [`utils/env_check.check_env`](../../scripts/utils/env_check.py) lines 19, 26, 29

This makes the functions un-testable as libraries (a test import can't call
them without killing the test process) and propagates the exit-code protocol
into every caller. The orchestrator `__main__` blocks (`sys.exit(run_orchestrator(args))`)
are **correct** — that is where exit belongs.

### Candidate 07 (NEW) — orphaned `local_few_shot_memory` module

Re-diagnosis finding: [`local_few_shot_memory.py`](../../scripts/memory/local_few_shot_memory.py)
has **zero production callers** (`grep "from scripts.memory" scripts/` returns
nothing). It is a parallel memory system with its own rule IDs (`R001` in
`summary_rules.json`), its own execution-log writer (`record_execution` writes
to the same `execution_log.jsonl` that `execution_orchestrator.log_execution`
writes to — but the two are never connected), and failure-clustering/repair
logic that overlaps the Reference Bank's domain. Only its own CLI `main()` and
the test suite touch it.

Decision deferred: fold the still-useful clustering behavior into the Bank, or
delete the dead code. Not in this session.

## Proposed slices for this session

Two sequential slices on one branch, one PR. Slice 5 is small and mechanical;
slice 6 is the payoff that 5 enables (the `except SystemExit` hack vanishes).

### Slice 5 — kill `sys.exit` inside `io/` and `utils/` functions

**Behavior:** `write_excel`, `compare_excel`, and `check_env` stop calling
`sys.exit`. They raise a typed exception (or return a result) instead; only
their `__main__` blocks translate that to a process exit code. Callers can now
use them as libraries.

**Interface:**
- `write_excel(...) -> None` — raises on failure (let `__main__` catch & exit).
  Return value unchanged (still `None` on success).
- `compare_excel(gen, bench) -> bool` — returns True/False; `__main__` exits 0/1.
- `check_env() -> list[str]` — returns the list of missing deps (empty = ok);
  `__main__` exits 1 if non-empty.

**Files touched:**
- `scripts/io/excel_writer.py` — remove `sys.exit` from `write_excel`; `__main__` wraps.
- `scripts/io/data_diff.py` — `compare_excel` returns bool; `__main__` exits.
- `scripts/utils/env_check.py` — `check_env` returns missing-deps list; `__main__` exits.
- `scripts/orchestration/execution_orchestrator.py` — replace `except SystemExit`
  around `write_excel` with a normal exception catch (the call site change that
  slice 6 will build on; minimal here — just stop catching `SystemExit`).
- `tests/io/test_excel_writer.py` (new) — call `write_excel` directly, assert it
  raises/returns without exiting.
- `tests/io/test_data_diff.py` — update for `compare_excel` returning bool.
- `tests/utils/test_env_check.py` (new) — `check_env` returns list.

**Acceptance:**
- No `sys.exit` call inside any function body in `scripts/io/` or `scripts/utils/`
  (`grep -n "sys.exit" scripts/io/ scripts/utils/` matches only `__main__` lines,
  or none at all).
- `write_excel` is callable from a test without `SystemExit` escaping.
- All existing tests pass.

### Slice 6 — decompose `execution_orchestrator` into a named pipeline

**Behavior:** `run_orchestrator` becomes a short top-level flow that calls a
sequence of named, single-responsibility steps. Each step returns a result or
signals failure uniformly; the duplicated `print + log + return 1` shape
collapses into one failure-handling helper. The `except SystemExit` hack is
gone (slice 5 removed it).

**Proposed step functions (each independently testable):**
- `_load_inputs(args) -> (schema, content, template_dir, memory_dir)`
- `_retrieve_context(bank, content, args) -> (rules, anchors, patterns, matched, input_sig, input_type, signature_mismatch)`
- `_extract(content, schema, rules, anchors, matched, formulas, template_dir) -> (extracted, degraded_level, error_msg)` (existing `_try_extraction_with_degradation`, lightly wrapped)
- `_validate(extracted, schema) -> missing_fields`
- `_detect_formula_conflicts(schema, extracted, template_dir) -> (extracted, conflicts)`
- `_write_output(template_dir, schema_path, extracted, output) -> None` (raises on failure; no `SystemExit`)
- `_record_outcome(bank, input_sig, input_type, rules, extracted, anchors, degraded_level) -> None`

`run_orchestrator` orchestrates these; a single `_fail(stage, payload, memory_dir, input_sig)`
helper handles the print + log + return-1 shape.

**Files touched:**
- `scripts/orchestration/execution_orchestrator.py` — decompose; keep public
  `run_orchestrator(args) -> int` signature stable (it's the CLI entry).
- `tests/orchestration/test_execution_orchestrator.py` — existing subprocess
  tests stay green (behavior preserved). Add unit tests for 2-3 of the new
  step functions where they have real logic (e.g. `_retrieve_context` signature
  threading, `_detect_formula_conflicts`).

**Acceptance:**
- `run_orchestrator` body is a short sequence of named calls, no inline
  business logic.
- No duplicated `print(json) + log_execution + return 1` block (one helper).
- No `except SystemExit` anywhere in the orchestrator.
- All existing tests pass (subprocess-level behavior unchanged).

## Out of scope for this session

- Candidate 03 (learning_orchestrator layering) — deferred.
- Candidate 07 (orphaned memory module) — decision deferred.
- Auto-populating `often_follows` KG edges — still reserved (per candidate 01 PRD).

## Test strategy

| Slice | New tests | Updated tests |
|-------|-----------|---------------|
| 5 | `write_excel` library-call test, `check_env` returns-list test | `test_data_diff` for bool return |
| 6 | unit tests for `_retrieve_context`, `_detect_formula_conflicts` | existing subprocess tests stay green |

TDD discipline: one RED → one GREEN → commit, per behavior. `traeagent` as
co-author on every commit. New branch `slice-5-6-io-orchestration`, one PR via
the GitHub REST API (AI-created, as before).
