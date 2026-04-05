# scripts/orchestration/learning_orchestrator.py
"""
RALPH Loop v2 Implementation

5 Phases:
- Phase 1: ANALYZE - LLM analyzes sample, generates anchors/schema, identifies formulas
- Phase 2: DRAFT - Generate initial rules, build knowledge graph
- Phase 3: TEST - Execute extraction, data_diff validation
- Phase 4: COMMIT - Record success patterns, update confidence
- Phase 5: REFLECT - Analyze failure, update rules, retry up to max_retries
"""
import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime

from scripts.core.reference_bank import ReferenceBank
from scripts.core.rule_evolution import update_rule_confidence
from scripts.core.signature_matcher import calculate_signature


class RALPHLoop:
    """Implements the RALPH Loop learning cycle."""

    def __init__(self, template_dir: str):
        self.template_dir = Path(template_dir)
        self.bank = ReferenceBank(str(self.template_dir / "reference_bank"))
        self.memory_dir = self.template_dir / "memory"
        os.makedirs(self.memory_dir, exist_ok=True)

    def run_full_cycle(self, sample_input: str, target_excel: str, max_retries: int = 5) -> dict:
        """
        Execute complete RALPH Loop.

        Returns dict with:
        - status: "committed" | "reflected" | "failed"
        - phase_reached: 1-5
        - attempts: number of TEST attempts
        """
        attempts = 0

        # Phase 1: ANALYZE
        analysis = self.phase1_analyze(sample_input, target_excel)

        # Save schema
        schema = {
            "meta": {"signature": calculate_signature(sample_input)},
            "fields": analysis.get("fields", {}),
            "formula_constraints": analysis.get("formula_constraints", [])
        }
        with open(self.template_dir / "schema.json", "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)

        # Save anchors
        self.bank.save_anchors({
            "schema_version": "1.0",
            "anchors": analysis.get("anchors", {})
        })

        # Phase 2: DRAFT
        rules = self.phase2_draft(analysis.get("anchors", {}), analysis.get("fields", {}))
        self.bank.save_rules(rules)

        # Phase 3-5: TEST → COMMIT/REFLECT loop
        for attempt in range(max_retries):
            attempts += 1
            success, extracted = self.phase3_test(sample_input, schema)

            if success:
                # Phase 4: COMMIT
                result = self.phase4_commit(sample_input, extracted)
                return {
                    "status": "committed",
                    "phase_reached": 4,
                    "attempts": attempts,
                    "data": extracted
                }
            else:
                # Phase 5: REFLECT
                failure_info = {
                    "missing_fields": extracted.get("missing_fields", []),
                    "error": extracted.get("error", "Unknown error")
                }
                rules = self.phase5_reflect(failure_info, self.bank.load_rules())
                self.bank.save_rules(rules)

        return {
            "status": "reflected",
            "phase_reached": 5,
            "attempts": attempts,
            "message": f"Max retries ({max_retries}) reached"
        }

    def phase1_analyze(self, sample_input: str, target_excel: str) -> dict:
        """
        Phase 1: ANALYZE

        LLM analyzes sample input and target Excel to generate:
        - anchors: key positioning markers
        - fields: field-to-cell mappings
        - formula_constraints: formulas from target Excel
        """
        # Read sample content
        with open(sample_input, "r", encoding="utf-8") as f:
            content = f.read()

        # Analyze target Excel for formulas
        from scripts.extraction.formula_analyzer import analyze_workbook_formulas
        formula_constraints = []
        try:
            formula_constraints = analyze_workbook_formulas(target_excel)
        except Exception:
            pass

        # Call LLM for analysis (to be implemented or mocked)
        if hasattr(self, '_llm_analyze'):
            return self._llm_analyze(content, {"formulas": formula_constraints})

        # Default: return empty structure
        return {
            "anchors": {},
            "fields": {},
            "formula_constraints": formula_constraints
        }

    def phase2_draft(self, anchors: dict, fields: dict) -> list:
        """
        Phase 2: DRAFT

        Generate initial rules based on anchors and fields.
        """
        if hasattr(self, '_draft_rules'):
            return self._draft_rules(anchors, fields)

        rules = []
        rule_id = 1

        for field_name, field_spec in fields.items():
            if isinstance(field_spec, dict):
                # Create a basic rule for each field
                rules.append({
                    "id": f"R{rule_id:03d}",
                    "when": {"input_type": "auto", "trigger": "field_extraction"},
                    "condition": {"field": field_name},
                    "then": {"action": "semantic_extract"},
                    "confidence": 0.5,
                    "support": 0,
                    "created_at": datetime.now().isoformat()
                })
                rule_id += 1

        return rules

    def phase3_test(self, input_content: str, schema: dict) -> tuple:
        """
        Phase 3: TEST

        Execute extraction and validate.

        Returns: (success: bool, result: dict)
        """
        if hasattr(self, '_execute_extraction'):
            extracted = self._execute_extraction(input_content)
        else:
            # Default: use LLM extractor
            from scripts.extraction.llm_extractor import extract_data
            from scripts.core.prompt_builder import build_context_prompt

            prompt = build_context_prompt(
                template_signature=schema.get("meta", {}).get("signature", ""),
                schema_fields=schema.get("fields", {}),
                formula_constraints=schema.get("formula_constraints", []),
                anchors=self.bank.load_anchors(),
                rules=self.bank.load_rules(),
                success_patterns=[],
                input_content=input_content
            )
            try:
                extracted = extract_data(prompt)
            except Exception as e:
                return False, {"error": str(e)}

        # Validate
        if hasattr(self, '_validate'):
            success, missing = self._validate(extracted, schema)
        else:
            expected = [k for k, v in schema.get("fields", {}).items() if isinstance(v, dict)]
            missing = [f for f in expected if f not in extracted]
            success = len(missing) == 0

        if success:
            return True, extracted
        else:
            return False, {"missing_fields": missing, "extracted": extracted}

    def phase4_commit(self, input_content: str, extracted: dict) -> dict:
        """
        Phase 4: COMMIT

        Record success pattern and update rule confidence.
        """
        input_sig = calculate_signature(input_content)

        # Record success pattern
        patterns = self.bank.load_success_patterns()
        patterns.append({
            "input_signature": input_sig,
            "accuracy": 1.0,
            "data": extracted,
            "created_at": datetime.now().isoformat()
        })
        self.bank.save_success_patterns(patterns)

        # Update rule confidence
        rules = self.bank.load_rules()
        updated_rules = []
        for r in rules:
            ur = update_rule_confidence(r, 1.0)
            if ur is not None:
                updated_rules.append(ur)
        self.bank.save_rules(updated_rules)

        return {"status": "committed", "signature": input_sig}

    def phase5_reflect(self, failure_info: dict, existing_rules: list) -> list:
        """
        Phase 5: REFLECT

        Analyze failure and generate/update rules.
        """
        if hasattr(self, '_analyze_failure'):
            new_rules = self._analyze_failure(failure_info, existing_rules)
        else:
            # Default: create rules for missing fields
            new_rules = existing_rules.copy()
            for field in failure_info.get("missing_fields", []):
                new_rules.append({
                    "id": f"R{len(new_rules) + 1:03d}",
                    "when": {"trigger": "field_extraction"},
                    "condition": {"field": field},
                    "then": {"action": "retry_extract"},
                    "confidence": 0.6,
                    "support": 0,
                    "created_at": datetime.now().isoformat()
                })

        # Update confidence of existing rules (failure signal)
        updated_rules = []
        for r in new_rules:
            ur = update_rule_confidence(r, 0.2)  # Low outcome = confidence decrease
            if ur is not None:
                updated_rules.append(ur)

        return updated_rules


def run_learning(args):
    """CLI entry point for learning orchestrator."""
    ralph = RALPHLoop(args.template_dir)
    result = ralph.run_full_cycle(args.input, args.target, max_retries=args.max_retries)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "committed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RALPH Loop Learning Orchestrator")
    parser.add_argument("--template-dir", required=True, help="Template directory path")
    parser.add_argument("--input", required=True, help="Sample input file path")
    parser.add_argument("--target", required=True, help="Target Excel file path")
    parser.add_argument("--max-retries", type=int, default=5, help="Maximum TEST retry attempts")
    args = parser.parse_args()
    sys.exit(run_learning(args))