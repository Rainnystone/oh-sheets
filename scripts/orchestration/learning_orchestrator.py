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
from scripts.core.input_type import determine_input_type as _determine_input_type


class RALPHLoop:
    """Implements the RALPH Loop learning cycle."""

    def __init__(self, template_dir: str):
        self.template_dir = Path(template_dir)
        self.bank = ReferenceBank(str(self.template_dir / "reference_bank"))
        self.memory_dir = self.template_dir / "memory"
        os.makedirs(self.memory_dir, exist_ok=True)
        # input_type is set per-run by run_full_cycle, threaded to phases
        # that create rules (phase2_draft, phase5_reflect) and phases that
        # retrieve them (phase3_test). Defaults to "md" for direct callers.
        self.input_type = "md"

    def run_full_cycle(self, sample_input: str, target_excel: str, max_retries: int = 5) -> dict:
        """
        Execute complete RALPH Loop.

        Returns dict with:
        - status: "committed" | "reflected" | "failed"
        - phase_reached: 1-5
        - attempts: number of TEST attempts
        """
        attempts = 0

        # Slice 1: tag the sample input's type so rules learned from it are
        # retrievable by future inputs of the same type. Falls back to "md".
        self.input_type = _determine_input_type(sample_input)

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

        Generate initial rules based on anchors and fields. Rules are tagged
        with self.input_type (set by run_full_cycle) so future inputs of the
        same type can retrieve them. Uses bank.add_rule() for unique IDs.

        Slice 2: when a field_spec carries an `anchor` key, the rule's
        `then` block records it AND a `uses_anchor` edge is written to
        the knowledge graph. This is the write-side that makes slice 2's
        KG expansion (retrieve_rules → _expand_via_kg) observable: edges
        written here become neighbors in future retrievals.
        """
        if hasattr(self, '_draft_rules'):
            return self._draft_rules(anchors, fields)

        rules = []
        new_edges: list[dict] = []
        for field_name, field_spec in fields.items():
            if not isinstance(field_spec, dict):
                continue
            anchor_id = field_spec.get("anchor")
            then_clause: dict = {"action": "semantic_extract"}
            if anchor_id:
                then_clause["anchor"] = anchor_id
            rule = self.bank.add_rule(
                input_type=self.input_type,
                trigger="field_extraction",
                field=field_name,
                action="semantic_extract",
                confidence=0.5,
                then=then_clause,
            )
            rules.append(rule)
            if anchor_id:
                new_edges.append({
                    "from": rule["id"],
                    "to": anchor_id,
                    "relation": "uses_anchor",
                    "weight": 1.0,
                })

        if new_edges:
            self._add_kg_edges_idempotent(new_edges)
        return rules

    def _add_kg_edges_idempotent(self, new_edges: list[dict]) -> None:
        """Append edges to the knowledge graph, skipping duplicates.

        A duplicate is an edge with the same (from, to, relation) triple.
        Keeps the graph clean when phase2_draft is re-run over the same
        rule+anchor pairs (e.g. a re-learning pass over the same sample).
        """
        graph = self.bank.load_knowledge_graph()
        existing = {
            (e.get("from"), e.get("to"), e.get("relation"))
            for e in graph.get("edges", [])
        }
        changed = False
        for e in new_edges:
            key = (e["from"], e["to"], e["relation"])
            if key not in existing:
                graph.setdefault("edges", []).append(e)
                existing.add(key)
                changed = True
        if changed:
            self.bank.save_knowledge_graph(graph)

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
                rules=self.bank.retrieve_rules(self.input_type),
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

        # Slice 3: single writer. phase4_commit doesn't carry the retrieved
        # rule set in scope (phase3_test used them internally), so
        # rules_used/anchors_matched are empty here — the learning loop
        # records that this input succeeded; rule association can be
        # enriched later when phase3 returns the rules it used.
        self.bank.record_success_pattern(
            input_signature=input_sig,
            input_type=self.input_type,
            extracted=extracted,
            rules_used=[],
            anchors_matched=[],
            accuracy=1.0,
        )

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

        Slice 4: new repair rules keep their creation confidence (0.6) —
        they're not penalized for the failure they were created to fix.
        Only rules that existed before this reflection receive the
        failure penalty. A rule just invented to repair a missing field
        hasn't been tested yet, so penalizing it would snuff it out
        before it ever got a fair trial.
        """
        if hasattr(self, '_analyze_failure'):
            new_rules = self._analyze_failure(failure_info, existing_rules)
        else:
            # Default: create rules for missing fields. Use bank.add_rule()
            # for unique IDs (max+1, not len+1) and real input_type tagging.
            new_rules = list(existing_rules)
            # Reserve existing rule IDs so add_rule won't reuse them. In
            # production existing_rules == bank.load_rules() (already on
            # disk, so add_rule sees them), but phase5_reflect must also
            # work when called directly with rules not yet on disk —
            # otherwise a new rule collides with an existing ID, inherits
            # its "existing" status, and gets wrongly penalized.
            for r in existing_rules:
                rid = r.get("id")
                if rid:
                    self.bank._pending_rule_ids.add(rid)
            for field in failure_info.get("missing_fields", []):
                new_rules.append(self.bank.add_rule(
                    input_type=self.input_type,
                    trigger="field_extraction",
                    field=field,
                    action="retry_extract",
                    confidence=0.6,
                ))

        # Penalize existing rules only (failure signal). New rules created
        # above keep their creation confidence — they haven't been tested.
        existing_ids = {r.get("id") for r in existing_rules}
        updated_rules = []
        for r in new_rules:
            if r.get("id") in existing_ids:
                ur = update_rule_confidence(r, 0.2)  # Low outcome = confidence decrease
                if ur is not None:
                    updated_rules.append(ur)
            else:
                updated_rules.append(r)

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