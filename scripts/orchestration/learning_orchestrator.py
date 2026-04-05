# scripts/orchestration/learning_orchestrator.py
import argparse
import sys
from scripts.core.reference_bank import ReferenceBank
from scripts.core.rule_evolution import update_rule_confidence

def run_learning(args):
    bank = ReferenceBank(args.bank_dir)
    rules = bank.load_rules()
    
    # Simulate outcome feedback
    updated_rules = []
    archived_count = 0
    for r in rules:
        updated = update_rule_confidence(r, args.outcome)
        if updated is not None:
            updated_rules.append(updated)
        else:
            archived_count += 1
            
    bank.save_rules(updated_rules)
    
    print(f"Learning complete. Retained {len(updated_rules)} rules. Archived {archived_count} rules. Outcome {args.outcome}.")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-dir", required=True)
    parser.add_argument("--outcome", type=float, required=True)
    args = parser.parse_args()
    sys.exit(run_learning(args))