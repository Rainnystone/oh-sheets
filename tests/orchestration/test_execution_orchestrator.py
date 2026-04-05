import json
import os
import openpyxl
import subprocess
import tempfile
from pathlib import Path

from scripts.utils.template_layout_signature import build_template_profile


def _write_template(path: Path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet['A1'] = 'Field_A'
    sheet['A2'] = 'Field_B'
    workbook.save(path)


def _write_schema(path: Path, signature=""):
    schema = {
        "meta": {
            "version": "2",
            "signature": signature,
        },
        "fields": {
            "Field_A": {"cell": "B2", "type": "string"},
            "Field_B": {"relative_to": "Field_A", "row_offset": 1, "col_offset": 0, "type": "string"},
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schema, f)


def _write_extractor(path: Path, payload: dict):
    content = f'''import argparse, json\n\nparser = argparse.ArgumentParser()\nparser.add_argument("--input", required=True)\nparser.add_argument("--output", required=True)\nargs = parser.parse_args()\n\nwith open(args.output, "w", encoding="utf-8") as f:\n    json.dump({json.dumps(payload)}, f)\n'''
    path.write_text(content)


def _run_orchestrator(template_dir: Path, input_path: Path, extractor_path: Path, output_path: Path, expected_path: Path = None, profile: Path = None, min_support: int = 2):
    cmd = [
        "python3",
        "scripts/orchestration/execution_orchestrator.py",
        "--template-dir", str(template_dir),
        "--input", str(input_path),
        "--extractor", str(extractor_path),
        "--output", str(output_path),
        "--min-support", str(min_support),
    ]
    if expected_path:
        cmd += ["--expected", str(expected_path)]
    if profile:
        cmd += ["--signature-profile", str(profile)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_signature_mismatch_blocks_and_logs_to_memory():
    with tempfile.TemporaryDirectory() as workdir:
        template_dir = Path(workdir)
        template_path = template_dir / "template.xlsx"
        schema_path = template_dir / "schema.json"
        profile_path = template_dir / "signature_profile.json"
        memory_dir = template_dir / "memory"
        input_path = template_dir / "input.dat"
        output_path = template_dir / "out.xlsx"
        extractor_path = template_dir / "extractor.py"

        _write_template(template_path)
        _write_schema(schema_path, signature="reference-mismatch")

        reference = build_template_profile(str(template_path))
        # write a deliberately different signature profile
        reference["signature"] = "different-signature"
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(reference, f)

        input_path.write_text("dummy")
        _write_extractor(extractor_path, {"Field_A": "A", "Field_B": "B"})

        result = subprocess.run(
            [
                "python3", "scripts/orchestration/execution_orchestrator.py",
                "--template-dir", str(template_dir),
                "--input", str(input_path),
                "--extractor", str(extractor_path),
                "--output", str(output_path),
                "--signature-profile", str(profile_path),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
        payload = json.loads(result.stdout)
        assert payload["status"] == "blocked"

        execution_log = memory_dir / "execution_log.jsonl"
        lines = execution_log.read_text(encoding="utf-8").strip().splitlines()
        assert lines
        last = json.loads(lines[-1])
        assert last["error_type"] == "signature_mismatch"


def test_missing_field_is_recorded_and_suggests_review():
    with tempfile.TemporaryDirectory() as workdir:
        template_dir = Path(workdir)
        template_path = template_dir / "template.xlsx"
        schema_path = template_dir / "schema.json"
        profile_path = template_dir / "signature_profile.json"
        memory_dir = template_dir / "memory"
        input_path = template_dir / "input.dat"
        output_path = template_dir / "out.xlsx"
        extractor_path = template_dir / "extractor.py"

        _write_template(template_path)
        reference = build_template_profile(str(template_path))
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(reference, f)
        _write_schema(schema_path, signature=reference.get("signature", ""))

        input_path.write_text("dummy")
        _write_extractor(extractor_path, {"Field_A": "only-first"})

        result = _run_orchestrator(template_dir, input_path, extractor_path, output_path, profile=profile_path)
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "failed"
        assert payload["stage"] == "validation"
        assert payload["missing_fields"] == ["Field_B"]

        execution_log = memory_dir / "execution_log.jsonl"
        lines = execution_log.read_text(encoding="utf-8").strip().splitlines()
        assert lines
        last = json.loads(lines[-1])
        assert last["error_type"] == "missing_fields"
        assert "Field_B" in last["missing_fields"]


def test_successful_run_writes_output_and_passes_signature_guard():
    with tempfile.TemporaryDirectory() as workdir:
        template_dir = Path(workdir)
        template_path = template_dir / "template.xlsx"
        schema_path = template_dir / "schema.json"
        profile_path = template_dir / "signature_profile.json"
        memory_dir = template_dir / "memory"
        input_path = template_dir / "input.dat"
        output_path = template_dir / "out.xlsx"
        extractor_path = template_dir / "extractor.py"
        expected_path = template_dir / "expected.xlsx"

        _write_template(template_path)
        reference = build_template_profile(str(template_path))
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(reference, f)
        _write_schema(schema_path, signature=reference.get("signature", ""))

        # prebuild expected output once using same writer logic
        expected_payload = {"Field_A": "A", "Field_B": "B"}
        temp_path = template_dir / "tmp.json"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(expected_payload, f)
        subprocess.check_call([
            "python3", "scripts/io/excel_writer.py",
            "--template", str(template_path),
            "--data", str(temp_path),
            "--schema", str(schema_path),
            "--output", str(expected_path),
        ])

        input_path.write_text("dummy")
        _write_extractor(extractor_path, expected_payload)

        result = _run_orchestrator(
            template_dir,
            input_path,
            extractor_path,
            output_path,
            expected_path=expected_path,
            profile=profile_path,
        )

        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "success"
        assert Path(payload["output"]).exists()
        assert payload["signature_guard"]["hard_mismatch"] is False

        assert output_path.exists()
