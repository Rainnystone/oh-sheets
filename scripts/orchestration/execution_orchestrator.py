import argparse
import json
import sys
import tempfile
import os
from collections import namedtuple
from pathlib import Path
from scripts.core.reference_bank import ReferenceBank
from scripts.core.prompt_builder import build_context_prompt
from scripts.core.signature_matcher import match_patterns, calculate_signature
from scripts.core.input_type import determine_input_type as _determine_input_type
from scripts.extraction.formula_analyzer import extract_formulas_from_schema, analyze_workbook_formulas
from scripts.extraction.llm_extractor import extract_data
from scripts.io.excel_writer import write_excel
from scripts.core.rule_evolution import Outcome


def log_execution(memory_dir: Path, record: dict):
    os.makedirs(memory_dir, exist_ok=True)
    log_file = memory_dir / "execution_log.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def _read_schema_field_names(schema):
    fields = schema.get("fields", {})
    return [str(name) for name, spec in fields.items() if isinstance(spec, dict)]

def _fail(memory_dir: Path, input_sig: str, payload: dict) -> int:
    """Print a failure payload as JSON, log it with the input signature,
    and return exit code 1.

    Collapses the duplicated print + log_execution + return 1 shape that
    previously appeared verbatim in the exhausted_degradation, validation,
    and write_excel failure branches of run_orchestrator.
    """
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    log_execution(memory_dir, {**payload, "input_signature": input_sig})
    return 1


# Assembled extraction context returned by _retrieve_context. Named fields
# (not a positional tuple) so callers and tests read ctx.input_sig etc.
# without memorising an order.
_RetrievalContext = namedtuple(
    "_RetrievalContext",
    [
        "rules",
        "anchors",
        "patterns",
        "matched",
        "input_sig",
        "input_type",
        "signature_mismatch",
    ],
)


def _retrieve_context(bank, content: str, input_path: str) -> "_RetrievalContext":
    """Build the extraction context from the Reference Bank and the input.

    Single-responsibility step extracted from run_orchestrator (slice 6b,
    candidate 02 — god-function decomposition). Assembles everything the
    orchestrator needs before invoking the extractor:

    - input_sig:        MD5 of the input content (used for retrieval,
                         logging, and success-pattern recording)
    - input_type:       extension-derived tag threaded into retrieve_rules
                         and record_success_pattern
    - rules/anchors/patterns: loaded from the bank
    - matched:          patterns whose signature matches this input
                         (exact match preferred, accuracy fallback otherwise)
    - signature_mismatch: True when stored patterns exist but none share
                         this input's signature — i.e. a new variant

    Accepts the bank as a dependency rather than constructing one, so a
    unit test can pass a duck-typed stub instead of standing up a real
    ReferenceBank on disk. Formula extraction stays in the orchestrator:
    it derives from the schema, not the bank, so it does not belong here.
    """
    input_sig = calculate_signature(content)
    input_type = _determine_input_type(input_path)
    rules = bank.retrieve_rules(input_type, input_signature=input_sig)
    anchors = bank.load_anchors()
    patterns = bank.load_success_patterns()
    matched = match_patterns(input_sig, patterns)
    signature_mismatch = bool(
        patterns and not any(p.get("input_signature") == input_sig for p in patterns)
    )
    return _RetrievalContext(
        rules=rules,
        anchors=anchors,
        patterns=patterns,
        matched=matched,
        input_sig=input_sig,
        input_type=input_type,
        signature_mismatch=signature_mismatch,
    )


def _detect_formula_conflicts(schema, extracted, template_dir):
    """Detect schema fields that would overwrite template formula cells.

    Single-responsibility step extracted from run_orchestrator (slice 6c,
    candidate 02 — god-function decomposition). For each schema field
    whose target cell holds a formula in the template AND is present in
    the extracted data, record a conflict and drop the field so the
    formula is preserved on write.

    Returns (cleaned_extracted, conflicts). Does not mutate the input
    extracted dict — returns a new dict with conflicting fields removed,
    so callers and tests get a predictable value back. If formula
    analysis itself fails (missing template, corrupt workbook), the step
    is a no-op: it returns the extracted data untouched with no conflicts,
    mirroring the original `except Exception: pass` guard.
    """
    conflicts = []
    try:
        template_formulas = analyze_workbook_formulas(str(template_dir / "template.xlsx"))
        formula_cells = {f["cell"] for f in template_formulas}
        for field_name, field_spec in schema.get("fields", {}).items():
            if isinstance(field_spec, dict):
                cell = field_spec.get("cell", "")
                if cell in formula_cells and field_name in extracted:
                    conflicts.append({"field": field_name, "cell": cell})
    except Exception:
        pass  # formula analysis failure is non-fatal
    conflict_fields = {c["field"] for c in conflicts}
    cleaned = {k: v for k, v in extracted.items() if k not in conflict_fields}
    return cleaned, conflicts


def _try_extraction_with_degradation(
    content: str,
    schema: dict,
    rules: list,
    anchors: dict,
    patterns: list,
    matched: list,
    formulas: list,
    template_dir: Path
) -> tuple:
    """
    Try extraction with degradation strategy.

    Returns: (extracted_data, degraded_level, error_message)
    - degraded_level: 1 (full), 2 (anchors only), 3 (deterministic), 4 (failed)
    """
    # Level 1: LLM + Reference Bank (full)
    prompt = build_context_prompt(
        template_signature=schema.get("meta", {}).get("signature", ""),
        schema_fields=schema.get("fields", {}),
        formula_constraints=formulas,
        anchors=anchors,
        rules=rules,
        success_patterns=matched,
        input_content=content
    )

    try:
        extracted = extract_data(prompt)
        return extracted, 1, None
    except Exception as e:
        level1_error = str(e)

    # Level 2: LLM + anchors only (no rules, no success patterns)
    prompt_level2 = build_context_prompt(
        template_signature=schema.get("meta", {}).get("signature", ""),
        schema_fields=schema.get("fields", {}),
        formula_constraints=formulas,
        anchors=anchors,
        rules=[],  # No rules
        success_patterns=[],  # No patterns
        input_content=content
    )

    try:
        extracted = extract_data(prompt_level2)
        return extracted, 2, None
    except Exception as e:
        level2_error = str(e)

    # Level 3: Deterministic extractor (if exists)
    extractor_path = template_dir / "extractors" / "main.py"
    if extractor_path.exists():
        try:
            # Import and run deterministic extractor
            import importlib.util
            spec = importlib.util.spec_from_file_location("deterministic_extractor", extractor_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, 'extract'):
                extracted = module.extract(content, schema)
                return extracted, 3, None
        except Exception as e:
            level3_error = str(e)

    # Level 4: Failed - user intervention required
    return None, 4, f"All extraction levels failed. Level 1: {level1_error}, Level 2: {level2_error}"


# Loaded inputs returned by _load_inputs. Named fields so the orchestrator
# reads inputs.schema / inputs.content without memorising a tuple order.
_Inputs = namedtuple("_Inputs", ["template_dir", "memory_dir", "schema", "content"])


def _load_inputs(args) -> "_Inputs":
    """Load the schema and input content for a run.

    Single-responsibility step extracted from run_orchestrator (slice 6d,
    candidate 02 — god-function decomposition). Resolves the template
    directory, derives the memory-dir path, and reads schema.json plus the
    input file. Pure I/O setup — no bank, no extraction, no validation.
    """
    template_dir = Path(args.template_dir).expanduser()
    memory_dir = template_dir / "memory"
    with open(template_dir / "schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    with open(args.input, "r", encoding="utf-8") as f:
        content = f.read()
    return _Inputs(
        template_dir=template_dir,
        memory_dir=memory_dir,
        schema=schema,
        content=content,
    )


def _validate(extracted, schema) -> list:
    """Return the list of required schema fields missing from extracted.

    Single-responsibility step extracted from run_orchestrator (slice 6d).
    An empty list means extracted satisfies the schema's required fields.
    """
    expected_fields = _read_schema_field_names(schema)
    return [field for field in expected_fields if field not in extracted]


def _write_output(template_dir: Path, extracted: dict, output: str) -> None:
    """Write extracted data into the template Excel file.

    Single-responsibility step extracted from run_orchestrator (slice 6d).
    Spills extracted to a temporary JSON file (the format write_excel
    reads), delegates to write_excel, and guarantees the temp file is
    removed whether write_excel succeeds or raises — via try/finally, so
    there is a single cleanup site instead of one per branch.

    Raises whatever write_excel raises; only run_orchestrator translates
    that into a _fail payload + exit code. (write_excel itself stopped
    calling sys.exit in slice 5a, so no SystemExit escapes here.)
    """
    template_path = template_dir / "template.xlsx"
    schema_path = template_dir / "schema.json"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as tmp:
        json.dump(extracted, tmp, ensure_ascii=False, indent=2)
        tmp_data_path = tmp.name
    try:
        write_excel(str(template_path), tmp_data_path, str(schema_path), str(output))
    finally:
        os.remove(tmp_data_path)


def _record_outcome(bank, ctx: "_RetrievalContext", extracted: dict, degraded_level: int) -> None:
    """Record a successful extraction in the Reference Bank.

    Single-responsibility step extracted from run_orchestrator (slice 6d).
    Bundles the two success-side bank writes:

    - apply_outcome(SUCCESS): the single outcome writer (slice 4) rewards
      all rules (+0.02 confidence, +1 support) and persists. Loading from
      disk inside apply_outcome means _source never leaks into rules.jsonl.
    - record_success_pattern: the single success-pattern writer (slice 3)
      populates the full §3.4 schema (pattern_id, input_type,
      fields_extracted, rules_used, anchors_matched, ...).

    Codex PR #3 review (P2): when degradation dropped to Level 2+ the
    rules were never sent to the LLM (Level 2 builds its prompt with
    rules=[]; Level 3 is a deterministic extractor with no LLM at all).
    Recording them in rules_used would corrupt signature preference — a
    future input matching this signature would be told these rules worked
    when they were never in the prompt. Omit them when degraded.
    """
    bank.apply_outcome(Outcome.SUCCESS)
    rules_used = [] if degraded_level > 1 else [r["id"] for r in ctx.rules]
    bank.record_success_pattern(
        input_signature=ctx.input_sig,
        input_type=ctx.input_type,
        extracted=extracted,
        rules_used=rules_used,
        anchors_matched=list(ctx.anchors.keys()) if isinstance(ctx.anchors, dict) else [],
        accuracy=1.0,
    )


def run_orchestrator(args):
    inputs = _load_inputs(args)
    template_dir = inputs.template_dir
    memory_dir = inputs.memory_dir
    schema = inputs.schema
    content = inputs.content
    bank = ReferenceBank(str(template_dir / "reference_bank"))
    ctx = _retrieve_context(bank, content, args.input)
    formulas = extract_formulas_from_schema(schema)

    extracted, degraded_level, error_msg = _try_extraction_with_degradation(
        content=content,
        schema=schema,
        rules=ctx.rules,
        anchors=ctx.anchors,
        patterns=ctx.patterns,
        matched=ctx.matched,
        formulas=formulas,
        template_dir=template_dir,
    )
    if extracted is None:
        return _fail(memory_dir, ctx.input_sig, {
            "status": "failed",
            "stage": "exhausted_degradation",
            "level": degraded_level,
            "error": error_msg,
        })

    missing_fields = _validate(extracted, schema)
    if missing_fields:
        return _fail(memory_dir, ctx.input_sig, {
            "status": "failed",
            "stage": "validation",
            "missing_fields": missing_fields,
            "error": "Extracted data missing required fields.",
        })

    extracted, formula_conflicts = _detect_formula_conflicts(schema, extracted, template_dir)

    try:
        _write_output(template_dir, extracted, args.output)
    except Exception as e:
        return _fail(memory_dir, ctx.input_sig, {
            "status": "failed",
            "stage": "write_excel",
            "error": str(e),
        })

    log_execution(memory_dir, {
        "status": "success",
        "input_signature": ctx.input_sig,
        "output": str(args.output),
    })
    _record_outcome(bank, ctx, extracted, degraded_level)

    result = {"status": "success", "output": str(args.output)}
    if formula_conflicts:
        result["formula_conflict"] = True
        result["conflicts"] = formula_conflicts
        result["message"] = f"Formula cells protected: {[c['cell'] for c in formula_conflicts]}"
    if degraded_level > 1:
        result["status"] = "degraded"
        result["degraded_level"] = degraded_level
        result["message"] = f"Extraction succeeded at degradation level {degraded_level}"
    if ctx.signature_mismatch:
        result["signature_mismatch"] = True
        result["message"] = "New variant detected. Pattern added to success_patterns."
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-dir", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    sys.exit(run_orchestrator(args))
