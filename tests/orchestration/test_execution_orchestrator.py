import json
import subprocess
import tempfile
import sys
import os
from pathlib import Path
import openpyxl

def _write_template(path: Path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["A1"] = "Field_A"
    sheet["A2"] = "Field_B"
    workbook.save(path)

def _write_schema(path: Path):
    schema = {
        "meta": {
            "version": "2",
            "signature": "abc",
        },
        "fields": {
            "Field_A": {"cell": "B2", "type": "string"},
            "Field_B": {"relative_to": "Field_A", "row_offset": 1, "col_offset": 0, "type": "string"},
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schema, f)

def test_missing_field_fails_validation():
    with tempfile.TemporaryDirectory() as workdir:
        template_dir = Path(workdir)
        template_path = template_dir / "template.xlsx"
        schema_path = template_dir / "schema.json"
        input_path = template_dir / "input.dat"
        output_path = template_dir / "out.xlsx"

        _write_template(template_path)
        _write_schema(schema_path)

        input_path.write_text("dummy content")

        mock_extractor_path = template_dir / "mock_extractor.py"
        mock_extractor_content = """import sys, json
import scripts.orchestration.execution_orchestrator as eo

def mock_extract(prompt):
    return {"Field_A": "Only-first"}

eo.extract_data = mock_extract

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
            capture_output=True,
            text=True,
            env={"PYTHONPATH": ".", **os.environ}
        )

        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "failed"
        assert payload["stage"] == "validation"
        assert "Field_B" in payload["missing_fields"]


def test_successful_run_writes_output():
    with tempfile.TemporaryDirectory() as workdir:
        template_dir = Path(workdir)
        template_path = template_dir / "template.xlsx"
        schema_path = template_dir / "schema.json"
        input_path = template_dir / "input.dat"
        output_path = template_dir / "out.xlsx"

        _write_template(template_path)
        _write_schema(schema_path)
        input_path.write_text("dummy content")

        mock_extractor_path = template_dir / "mock_extractor.py"
        mock_extractor_content = """import sys, json
import scripts.orchestration.execution_orchestrator as eo
import scripts.io.excel_writer

def mock_extract(prompt):
    return {"Field_A": "A", "Field_B": "B"}

eo.extract_data = mock_extract
eo.write_excel = lambda t, d, s, o: open(o, "w").write("dummy excel")
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
            capture_output=True,
            text=True,
            env={"PYTHONPATH": ".", **os.environ}
        )

        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "success"
