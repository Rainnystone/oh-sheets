import argparse
import json
import sys
import tempfile
import os
from pathlib import Path
from scripts.core.reference_bank import ReferenceBank
from scripts.core.prompt_builder import build_context_prompt
from scripts.core.signature_matcher import match_patterns, calculate_signature
from scripts.extraction.formula_analyzer import extract_formulas_from_schema
from scripts.extraction.llm_extractor import extract_data
from scripts.io.excel_writer import write_excel
from scripts.core.rule_evolution import update_rule_confidence

def log_execution(memory_dir: Path, record: dict):
    os.makedirs(memory_dir, exist_ok=True)
    log_file = memory_dir / "execution_log.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def _read_schema_field_names(schema):
    fields = schema.get("fields", {})
    return [str(name) for name, spec in fields.items() if isinstance(spec, dict)]

def run_orchestrator(args):
    template_dir = Path(args.template_dir).expanduser()
    schema_path = template_dir / "schema.json"
    memory_dir = template_dir / "memory"
    
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
        
    with open(args.input, "r", encoding="utf-8") as f:
        content = f.read()
        
    input_sig = calculate_signature(content)
    bank = ReferenceBank(str(template_dir / "reference_bank"))
    
    rules = bank.load_rules()
    anchors = bank.load_anchors()
    patterns = bank.load_success_patterns()
    formulas = extract_formulas_from_schema(schema)
    
    matched = match_patterns(input_sig, patterns)
    
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
    except Exception as e:
        error_msg = str(e)
        print(json.dumps({"status": "failed", "stage": "extractor_output", "error": error_msg}, ensure_ascii=False, indent=2))
        log_execution(memory_dir, {
            "status": "failed",
            "stage": "extractor_output",
            "error": error_msg,
            "input_signature": input_sig
        })
        return 1
        
    # Validation Phase
    expected_fields = _read_schema_field_names(schema)
    missing_fields = [field for field in expected_fields if field not in extracted]
    
    if missing_fields:
        error_msg = "Extracted data missing required fields."
        result = {
            "status": "failed",
            "stage": "validation",
            "missing_fields": missing_fields,
            "error": error_msg
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        log_execution(memory_dir, {
            "status": "failed",
            "stage": "validation",
            "missing_fields": missing_fields,
            "error": error_msg,
            "input_signature": input_sig
        })
        return 1
    
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as tmp:
        json.dump(extracted, tmp, ensure_ascii=False, indent=2)
        tmp_data_path = tmp.name

    try:
        write_excel(str(template_dir / "template.xlsx"), tmp_data_path, str(schema_path), str(args.output))
    except SystemExit as e:
        if e.code != 0:
            error_msg = f"write_excel failed with exit code {e.code}"
            print(json.dumps({"status": "failed", "stage": "write_excel", "error": error_msg}, ensure_ascii=False, indent=2))
            log_execution(memory_dir, {
                "status": "failed",
                "stage": "write_excel",
                "error": error_msg,
                "input_signature": input_sig
            })
            os.remove(tmp_data_path)
            return 1
    except Exception as e:
        error_msg = str(e)
        print(json.dumps({"status": "failed", "stage": "write_excel", "error": error_msg}, ensure_ascii=False, indent=2))
        log_execution(memory_dir, {
            "status": "failed",
            "stage": "write_excel",
            "error": error_msg,
            "input_signature": input_sig
        })
        os.remove(tmp_data_path)
        return 1
        
    os.remove(tmp_data_path)

    log_execution(memory_dir, {
        "status": "success",
        "input_signature": input_sig,
        "output": str(args.output)
    })

    updated_rules = []
    for r in rules:
        ur = update_rule_confidence(r, 1.0)
        if ur is not None:
            updated_rules.append(ur)
    bank.save_rules(updated_rules)

    patterns.append({
        "input_signature": input_sig,
        "accuracy": 1.0,
        "data": extracted
    })
    bank.save_success_patterns(patterns)
        
    print(json.dumps({"status": "success", "output": str(args.output)}))
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-dir", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    sys.exit(run_orchestrator(args))
