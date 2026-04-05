# tests/orchestration/test_learning_orchestrator.py
import json
import tempfile
from pathlib import Path
import openpyxl
from scripts.orchestration.learning_orchestrator import RALPHLoop

def test_ralph_loop_analyze_phase():
    """Test Phase 1: ANALYZE - LLM analyzes sample and generates anchors/schema."""
    with tempfile.TemporaryDirectory() as tmpdir:
        template_dir = Path(tmpdir)

        # Create sample input and target
        sample_input = template_dir / "sample.pdf"
        sample_input.write_text("Invoice #12345\nVendor: ABC Corp\nTotal: $1,000")

        target_excel = template_dir / "target.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["B2"] = "12345"
        ws["B3"] = "ABC Corp"
        ws["B4"] = "1000"
        ws["D5"] = "=SUM(D2:D4)"
        wb.save(target_excel)

        ralph = RALPHLoop(str(template_dir))

        # Mock LLM response for analysis
        def mock_analyze(content, target_info):
            return {
                "anchors": {
                    "invoice_number": {
                        "type": "regex",
                        "pattern": "Invoice #(\\d+)",
                        "role": "value_matcher"
                    },
                    "vendor": {
                        "type": "text_match",
                        "patterns": ["Vendor:"],
                        "role": "label"
                    }
                },
                "fields": {
                    "Invoice_Number": {"cell": "B2", "type": "string"},
                    "Vendor_Name": {"cell": "B3", "type": "string"}
                },
                "formula_constraints": [
                    {"cell": "D5", "formula": "=SUM(D2:D4)"}
                ]
            }

        ralph._llm_analyze = mock_analyze

        result = ralph.phase1_analyze(str(sample_input), str(target_excel))

        assert "anchors" in result
        assert "fields" in result
        assert result["anchors"]["invoice_number"]["type"] == "regex"


def test_ralph_loop_draft_phase():
    """Test Phase 2: DRAFT - Generate initial rules from anchors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        template_dir = Path(tmpdir)

        ralph = RALPHLoop(str(template_dir))

        anchors = {
            "invoice_number": {
                "type": "regex",
                "pattern": "Invoice #(\\d+)"
            }
        }
        fields = {
            "Invoice_Number": {"cell": "B2", "type": "string"}
        }

        def mock_draft_rules(anchors, fields):
            return [
                {
                    "id": "R001",
                    "when": {"input_type": "pdf", "trigger": "field_extraction"},
                    "condition": {"field": "Invoice_Number"},
                    "then": {"action": "extract_by_regex", "pattern": "Invoice #(\\d+)"},
                    "confidence": 0.9,
                    "support": 0
                }
            ]

        ralph._draft_rules = mock_draft_rules

        result = ralph.phase2_draft(anchors, fields)

        assert len(result) >= 1
        assert result[0]["id"] == "R001"
        assert result[0]["confidence"] >= 0.5


def test_ralph_loop_test_and_commit_phases():
    """Test Phase 3-4: TEST and COMMIT - Execute extraction and record success."""
    with tempfile.TemporaryDirectory() as tmpdir:
        template_dir = Path(tmpdir)

        # Setup template
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["B2"] = ""
        ws["B3"] = ""
        wb.save(template_dir / "template.xlsx")

        schema = {
            "meta": {"signature": "test"},
            "fields": {
                "Invoice_Number": {"cell": "B2", "type": "string"},
                "Vendor_Name": {"cell": "B3", "type": "string"}
            }
        }
        with open(template_dir / "schema.json", "w") as f:
            json.dump(schema, f)

        ralph = RALPHLoop(str(template_dir))

        # Mock extraction that succeeds
        def mock_execute_extraction(content):
            return {"Invoice_Number": "12345", "Vendor_Name": "ABC Corp"}

        ralph._execute_extraction = mock_execute_extraction

        # Mock validation that passes
        def mock_validate(extracted, schema):
            return True, []

        ralph._validate = mock_validate

        test_input = "Invoice #12345\nVendor: ABC Corp"
        success, result = ralph.phase3_test(test_input, schema)

        assert success == True

        # Phase 4: COMMIT
        commit_result = ralph.phase4_commit(test_input, result)
        assert commit_result["status"] == "committed"


def test_ralph_loop_reflect_phase():
    """Test Phase 5: REFLECT - Analyze failure and update rules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        template_dir = Path(tmpdir)

        ralph = RALPHLoop(str(template_dir))

        # Simulate a failure
        failure_info = {
            "missing_fields": ["Vendor_Name"],
            "error": "Extraction incomplete"
        }

        existing_rules = [
            {"id": "R001", "confidence": 0.9, "support": 5}
        ]

        def mock_analyze_failure(failure_info, rules):
            return [
                {
                    "id": "R002",
                    "when": {"trigger": "field_extraction"},
                    "condition": {"field": "Vendor_Name"},
                    "then": {"action": "extract_after_anchor", "anchor": "Vendor:"},
                    "confidence": 0.7,
                    "support": 0
                }
            ]

        ralph._analyze_failure = mock_analyze_failure

        new_rules = ralph.phase5_reflect(failure_info, existing_rules)

        assert len(new_rules) >= 1
        assert new_rules[0]["id"] == "R002"


def test_ralph_loop_full_cycle():
    """Test complete RALPH Loop with all 5 phases."""
    with tempfile.TemporaryDirectory() as tmpdir:
        template_dir = Path(tmpdir)

        # Setup
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["B2"] = ""
        wb.save(template_dir / "template.xlsx")

        sample_input = template_dir / "sample.txt"
        sample_input.write_text("Invoice #12345")

        target_excel = template_dir / "target.xlsx"
        wb2 = openpyxl.Workbook()
        ws2 = wb2.active
        ws2["B2"] = "12345"
        wb2.save(target_excel)

        ralph = RALPHLoop(str(template_dir))

        # Mock all phases
        ralph._llm_analyze = lambda c, t: {
            "anchors": {},
            "fields": {"Invoice_Number": {"cell": "B2", "type": "string"}},
            "formula_constraints": []
        }
        ralph._draft_rules = lambda a, f: [
            {"id": "R001", "when": {}, "condition": {}, "then": {}, "confidence": 0.9, "support": 0}
        ]
        ralph._execute_extraction = lambda c: {"Invoice_Number": "12345"}
        ralph._validate = lambda e, s: (True, [])

        result = ralph.run_full_cycle(str(sample_input), str(target_excel), max_retries=3)

        assert result["status"] in ["committed", "reflected"]
        assert result["phase_reached"] >= 4  # Should reach at least COMMIT phase