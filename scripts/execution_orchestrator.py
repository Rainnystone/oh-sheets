import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from scripts.excel_writer import write_excel
from scripts.local_few_shot_memory import record_execution, rebuild_failure_summary, suggest_repairs
from scripts.template_layout_signature import build_template_profile, compare_layout_profiles


def _load_json(path, default=None):
    if default is None:
        default = {}
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_schema_field_names(schema):
    if not isinstance(schema, dict):
        return []

    fields = schema.get("fields")
    if isinstance(fields, dict):
        return [str(name) for name, spec in fields.items() if isinstance(spec, dict)]

    names = []
    for key, spec in schema.items():
        if key in {"fields", "meta", "version"}:
            continue
        if isinstance(spec, dict):
            field_name = spec.get("name")
            if isinstance(field_name, str) and field_name.strip():
                names.append(field_name)
                continue
        names.append(key)
    return list(dict.fromkeys(names))


def _schema_signature(schema_path, template_profile_path=None):
    schema_obj = _load_json(schema_path, {})
    meta = schema_obj.get("meta", {}) if isinstance(schema_obj, dict) else {}
    if isinstance(meta, dict) and meta.get("signature"):
        return str(meta.get("signature"))

    if template_profile_path and template_profile_path.exists():
        stored = _load_json(template_profile_path, {})
        signature = stored.get("signature")
        if signature:
            return str(signature)

    return ""


def _signature_check(template_path, signature_profile_path, schema_path):
    current_profile = build_template_profile(str(template_path))
    current_signature = current_profile.get("signature", "")

    stored_profile = {}
    if signature_profile_path.exists():
        stored_profile = _load_json(signature_profile_path, {})
    else:
        schema_signature = _schema_signature(schema_path, signature_profile_path)
        if schema_signature:
            stored_profile = {"signature": schema_signature}

    if not stored_profile:
        return {
            "compatibility": "compatible",
            "score": 1.0,
            "reason": "No stored signature profile",
            "hard_mismatch": False,
            "base_signature": "",
            "candidate_signature": current_signature,
            "details": [],
        }

    result = compare_layout_profiles(stored_profile, current_profile)
    result["candidate_signature"] = current_signature
    return result


def _is_missing_fields_error(error):
    return error.get("error_type") == "missing_fields"


def _record(event):
    result = record_execution(event["memory_dir"], event["payload"])
    if event.get("rebuild_summary"):
        rebuild_failure_summary(event["memory_dir"], min_support=event.get("min_support", 2))
    return result


def _run_extractor(extractor_path, input_path, data_path):
    cmd = [sys.executable, str(extractor_path), "--input", str(input_path), "--output", str(data_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {
            "ok": False,
            "stderr": proc.stderr.strip(),
            "stdout": proc.stdout.strip(),
        }
    return {
        "ok": True,
        "stderr": proc.stderr.strip(),
        "stdout": proc.stdout.strip(),
    }


def run_template_orchestrator(args):
    template_dir = Path(args.template_dir).expanduser()
    template_path = Path(args.template or (template_dir / "template.xlsx")).expanduser()
    schema_path = Path(args.schema or (template_dir / "schema.json")).expanduser()
    memory_dir = Path(args.memory_dir or (template_dir / "memory")).expanduser()
    signature_profile_path = Path(args.signature_profile or (template_dir / "signature_profile.json")).expanduser()

    signature_check = _signature_check(template_path, signature_profile_path, schema_path)
    if signature_check.get("hard_mismatch"):
        event = {
            "template_signature": signature_check.get("candidate_signature", ""),
            "input_type": "extractor_input",
            "error_type": "signature_mismatch",
            "missing_fields": [],
            "repair_action": "learn_required",
            "human_confirmed": False,
            "confidence": 0.0,
            "rule_ids": [],
            "note": "template signature mismatch; requires structural re-learn before execution",
        }
        _record({
            "memory_dir": str(memory_dir),
            "payload": event,
            "rebuild_summary": True,
            "min_support": args.min_support,
        })
        result = {
            "status": "blocked",
            "action": "learn_required",
            "signature_guard": signature_check,
            "note": "template signature mismatch; requires structural re-learn before execution",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    extractor_path = Path(args.extractor).expanduser()
    output_path = Path(args.output).expanduser()
    with NamedTemporaryFile(delete=False, suffix=".json") as generated_file:
        generated_json = Path(generated_file.name)

    extractor_result = _run_extractor(extractor_path, args.input, generated_json)
    if not extractor_result["ok"]:
        event = {
            "template_signature": signature_check.get("candidate_signature", ""),
            "input_type": "extractor_input",
            "error_type": "extractor_failed",
            "missing_fields": [],
            "repair_action": "reroute_variant_or_model",
            "human_confirmed": False,
            "confidence": 0.35,
            "rule_ids": [],
        }
        _record({
            "memory_dir": str(memory_dir),
            "payload": event,
            "rebuild_summary": True,
            "min_support": args.min_support,
        })
        result = {
            "status": "failed",
            "stage": "extractor",
            "signature_guard": signature_check,
            "error": extractor_result["stderr"],
        }
        generated_json.unlink(missing_ok=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    try:
        with open(generated_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        event = {
            "template_signature": signature_check.get("candidate_signature", ""),
            "input_type": "extractor_input",
            "error_type": "extracted_data_invalid",
            "missing_fields": [],
            "repair_action": "rewrite_extractor",
            "human_confirmed": False,
            "confidence": 0.4,
            "rule_ids": [],
            "error_message": str(exc),
        }
        _record({
            "memory_dir": str(memory_dir),
            "payload": event,
            "rebuild_summary": True,
            "min_support": args.min_support,
        })
        generated_json.unlink(missing_ok=True)
        print(json.dumps({"status": "failed", "stage": "extractor_output", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    schema_obj = _load_json(schema_path, {})
    expected_fields = _read_schema_field_names(schema_obj)
    missing_fields = [field for field in expected_fields if field not in data]
    if missing_fields:
        rules = suggest_repairs(str(memory_dir), signature_check.get("candidate_signature", ""), "missing_fields", missing_fields)
        repair_action = rules[0]["repair_action"] if rules else "manual_review"

        event = {
            "template_signature": signature_check.get("candidate_signature", ""),
            "input_type": "extractor_input",
            "error_type": "missing_fields",
            "missing_fields": missing_fields,
            "repair_action": repair_action,
            "human_confirmed": False,
            "confidence": 0.85 if rules else 0.55,
            "rule_ids": [item.get("id") for item in rules if item.get("id")],
            "candidate_repairs": [item.get("repair_action") for item in rules],
        }
        _record({
            "memory_dir": str(memory_dir),
            "payload": event,
            "rebuild_summary": True,
            "min_support": args.min_support,
        })
        result = {
            "status": "failed",
            "stage": "validation",
            "signature_guard": signature_check,
            "missing_fields": missing_fields,
            "candidate_repairs": event["candidate_repairs"],
        }
        generated_json.unlink(missing_ok=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    try:
        write_excel(str(template_path), str(generated_json), str(schema_path), str(output_path))
    except Exception as exc:
        event = {
            "template_signature": signature_check.get("candidate_signature", ""),
            "input_type": "extractor_input",
            "error_type": "writer_failed",
            "missing_fields": [],
            "repair_action": "check_writer_contract",
            "human_confirmed": False,
            "confidence": 0.5,
            "rule_ids": [],
            "error_message": str(exc),
        }
        _record({
            "memory_dir": str(memory_dir),
            "payload": event,
            "rebuild_summary": True,
            "min_support": args.min_support,
        })
        generated_json.unlink(missing_ok=True)
        print(json.dumps({"status": "failed", "stage": "writer", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    generated_json.unlink(missing_ok=True)

    if args.expected:
        diff_result = subprocess.run([sys.executable, "scripts/data_diff.py", "--generated", str(output_path), "--benchmark", str(args.expected)], capture_output=True, text=True)
        if diff_result.returncode != 0:
            event = {
                "template_signature": signature_check.get("candidate_signature", ""),
                "input_type": "extractor_input",
                "error_type": "validation_mismatch",
                "missing_fields": [],
                "repair_action": "learn_or_refine_rules",
                "human_confirmed": False,
                "confidence": 0.6,
                "rule_ids": [],
                "error_message": diff_result.stdout.strip() or diff_result.stderr.strip(),
            }
            _record({
                "memory_dir": str(memory_dir),
                "payload": event,
                "rebuild_summary": True,
                "min_support": args.min_support,
            })
            print(json.dumps({"status": "failed", "stage": "validation", "diff": diff_result.stdout.strip(), "signature_guard": signature_check}, ensure_ascii=False, indent=2))
            return 1

    print(json.dumps({"status": "success", "output": str(output_path), "signature_guard": signature_check}, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-dir", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--extractor", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--template")
    parser.add_argument("--schema")
    parser.add_argument("--memory-dir")
    parser.add_argument("--signature-profile")
    parser.add_argument("--expected")
    parser.add_argument("--min-support", type=int, default=2)
    args = parser.parse_args()

    rc = run_template_orchestrator(args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
