import argparse
import json
import sys
from pathlib import Path
from scripts.core.reference_bank import ReferenceBank
from scripts.core.prompt_builder import build_context_prompt
from scripts.core.signature_matcher import match_patterns, calculate_signature
from scripts.extraction.formula_analyzer import extract_formulas_from_schema
from scripts.extraction.llm_extractor import extract_data
from scripts.io.excel_writer import write_excel

def _read_schema_field_names(schema):
    fields = schema.get("fields", {})
    return [str(name) for name, spec in fields.items() if isinstance(spec, dict)]

def run_orchestrator(args):
    template_dir = Path(args.template_dir).expanduser()
    schema_path = template_dir / "schema.json"
    
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
        print(json.dumps({"status": "failed", "stage": "extractor_output", "error": str(e)}, ensure_ascii=False, indent=2))
        return 1
        
    # Validation Phase
    expected_fields = _read_schema_field_names(schema)
    missing_fields = [field for field in expected_fields if field not in extracted]
    
    if missing_fields:
        result = {
            "status": "failed",
            "stage": "validation",
            "missing_fields": missing_fields,
            "error": "Extracted data missing required fields."
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(extracted, f, ensure_ascii=False, indent=2)
        
    print(json.dumps({"status": "success", "output": str(args.output)}))
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-dir", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    sys.exit(run_orchestrator(args))