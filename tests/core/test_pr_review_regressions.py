"""Regression tests for codex PR review comments on slice 1.

Each test pins a behavior that was broken in the initial slice-1 commit
and fixed in a follow-up commit on this PR. The test name cites the bug.

P1 test drives the real execution_orchestrator via subprocess (matching
the existing test pattern in test_execution_orchestrator.py) so it
exercises the actual save path that was buggy.
P2 tests are unit-level on ReferenceBank.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import openpyxl

from scripts.core.reference_bank import ReferenceBank


def _rule(rule_id, input_type="auto", confidence=0.5, trigger="field_extraction"):
    return {
        "id": rule_id,
        "when": {"input_type": input_type, "trigger": trigger},
        "condition": {"field": "x"},
        "then": {"action": "semantic_extract"},
        "confidence": confidence,
        "support": 0,
    }


def _write_template(path: Path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["A1"] = "Field_A"
    sheet["A2"] = "Field_B"
    workbook.save(path)


def _write_schema(path: Path):
    schema = {
        "meta": {"version": "2", "signature": "abc"},
        "fields": {
            "Field_A": {"cell": "B2", "type": "string"},
            "Field_B": {"relative_to": "Field_A", "row_offset": 1, "col_offset": 0, "type": "string"},
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schema, f)


# ---------------------------------------------------------------------------
# P1 (codex comment 1): preserve the full rule bank when saving confidence
# updates. retrieve_rules returns a filtered subset; the orchestrator must
# merge confidence updates back into load_rules() rather than overwrite the
# bank with the subset (which would delete every non-retrieved rule and
# persist the in-memory _source tag).
# ---------------------------------------------------------------------------

def test_orchestrator_save_path_preserves_non_retrieved_rules():
    """A successful extraction must not delete rules outside the retrieved
    subset. Pre-seed the bank with rules for multiple input types; the pdf
    extraction should bump only pdf-rule confidences and leave excel rules
    intact, and must not persist _source to disk.
    """
    with tempfile.TemporaryDirectory() as workdir:
        template_dir = Path(workdir)
        template_path = template_dir / "template.xlsx"
        schema_path = template_dir / "schema.json"
        input_path = template_dir / "input.pdf"   # pdf → retrieve_rules("pdf")
        output_path = template_dir / "out.xlsx"

        _write_template(template_path)
        _write_schema(schema_path)
        input_path.write_text("dummy pdf content")

        # Pre-seed the bank with rules for two input types. retrieve_rules("pdf")
        # will return only the 3 pdf rules; the 2 excel rules must survive the
        # orchestrator's save_rules() call on the success path.
        bank_dir = template_dir / "reference_bank"
        bank_dir.mkdir()
        (bank_dir / "rules.jsonl").write_text("".join(
            json.dumps(r) + "\n" for r in [
                _rule("R001", input_type="pdf", confidence=0.5),
                _rule("R002", input_type="pdf", confidence=0.5),
                _rule("R003", input_type="pdf", confidence=0.5),
                _rule("R004", input_type="excel", confidence=0.5),
                _rule("R005", input_type="excel", confidence=0.5),
            ]
        ))

        mock_extractor_path = template_dir / "mock_extractor.py"
        mock_extractor_content = """import sys, json
import scripts.orchestration.execution_orchestrator as eo
import scripts.io.excel_writer

def mock_extract(prompt):
    return {"Field_A": "A", "Field_B": "B"}

eo.extract_data = mock_extract
scripts.io.excel_writer.write_excel = lambda t, d, s, o: open(o, "w").write("dummy excel")

if __name__ == "__main__":
    class Args:
        template_dir = sys.argv[1]
        input = sys.argv[2]
        output = sys.argv[3]
    sys.exit(eo.run_orchestrator(Args()))
"""
        mock_extractor_path.write_text(mock_extractor_content)

        result = subprocess.run(
            [sys.executable, str(mock_extractor_path), str(template_dir), str(input_path), str(output_path)],
            capture_output=True, text=True,
            env={"PYTHONPATH": ".", **os.environ},
        )
        assert result.returncode == 0, f"orchestrator failed: {result.stderr}"
        payload = json.loads(result.stdout)
        assert payload["status"] == "success"

        # Inspect the bank after the orchestrator ran
        bank = ReferenceBank(str(bank_dir))
        on_disk = bank.load_rules()

        # ALL 5 rules must survive — excel rules (R004, R005) must not be deleted
        ids = [r["id"] for r in on_disk]
        assert ids == ["R001", "R002", "R003", "R004", "R005"], \
            f"P1 regression: orchestrator deleted non-retrieved rules. Got {ids}"

        # _source must NOT have been persisted (it's in-memory only)
        assert all("_source" not in r for r in on_disk), \
            "P1 regression: _source was persisted to rules.jsonl"


# ---------------------------------------------------------------------------
# P2 (codex comment 2): a rule with NO input_type field (legacy
# phase5_reflect output before slice 1) should still be retrieved — it was
# silently dropped by strict input_type matching.
# ---------------------------------------------------------------------------

def test_retrieve_rules_treats_missing_input_type_as_legacy_auto(tmp_path):
    """Rules with no `when.input_type` (pre-slice-1 phase5_reflect output)
    must match every input_type query, like the "auto" wildcard.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        # Legacy rule: `when` has only `trigger`, no `input_type`
        {"id": "R001", "when": {"trigger": "field_extraction"},
         "condition": {"field": "vendor"}, "then": {"action": "retry_extract"},
         "confidence": 0.6, "support": 0},
        _rule("R002", input_type="pdf", confidence=0.7),
    ])
    pdf_ids = [r["id"] for r in bank.retrieve_rules("pdf")]
    excel_ids = [r["id"] for r in bank.retrieve_rules("excel")]
    assert pdf_ids == ["R002", "R001"]   # R002 higher conf, then legacy R001
    assert excel_ids == ["R001"]         # legacy R001 matches excel too


# ---------------------------------------------------------------------------
# P2 (codex comment 3): a rule with input_type but NO trigger (older README
# schema) should still be retrieved as field_extraction — strict equality
# silently dropped it from every prompt.
# ---------------------------------------------------------------------------

def test_retrieve_rules_defaults_missing_trigger_to_field_extraction(tmp_path):
    """Rules with input_type but no `when.trigger` (older schema) default
    to field_extraction so they aren't silently dropped from prompts.
    """
    bank = ReferenceBank(str(tmp_path / "bank"))
    bank.save_rules([
        # Older-schema rule: `when` has only `input_type`, no `trigger`
        {"id": "R001", "when": {"input_type": "pdf"},
         "condition": {"field": "vendor"}, "then": {"action": "semantic_extract"},
         "confidence": 0.7, "support": 0},
    ])
    ids = [r["id"] for r in bank.retrieve_rules("pdf")]
    assert ids == ["R001"]

    # A different trigger must still exclude it (not "match everything")
    none_ids = [r["id"] for r in bank.retrieve_rules("pdf", trigger="table_extract")]
    assert none_ids == []
