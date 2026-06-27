import os
import re
import json
from datetime import datetime


class ReferenceBank:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.anchors_file = os.path.join(self.base_dir, "anchors.json")
        self.rules_file = os.path.join(self.base_dir, "rules.jsonl")
        self.patterns_file = os.path.join(self.base_dir, "success_patterns.jsonl")
        self.graph_file = os.path.join(self.base_dir, "knowledge_graph.json")
        # IDs issued by add_rule() but not yet persisted via save_rules().
        # Tracked so successive unsaved add_rule() calls (e.g. phase2_draft
        # building a batch in a loop) produce unique IDs. Cleared on save.
        self._pending_rule_ids: set[str] = set()

    def _next_rule_id(self) -> str:
        """Generate the next rule ID as max(existing numeric IDs)+1.

        Considers both on-disk rules AND IDs issued by add_rule() since the
        last save_rules() — so a batch of unsaved add_rule() calls produces
        unique IDs (fixes the phase2_draft collision where every rule got
        R001 because the disk was still empty mid-batch).
        """
        max_n = 0
        for r in self.load_rules():
            rid = r.get("id", "")
            m = re.match(r"^R(\d+)$", rid)
            if m:
                max_n = max(max_n, int(m.group(1)))
        for rid in self._pending_rule_ids:
            m = re.match(r"^R(\d+)$", rid)
            if m:
                max_n = max(max_n, int(m.group(1)))
        return f"R{max_n + 1:03d}"

    def add_rule(
        self,
        input_type: str,
        trigger: str,
        field: str,
        action: str,
        confidence: float = 0.5,
        **extra,
    ) -> dict:
        """Construct a rule dict with a unique ID and required fields.

        Does NOT auto-save — caller batches via save_rules(). This keeps
        add_rule cheap and lets callers build a transaction before commit.
        """
        rid = self._next_rule_id()
        rule = {
            "id": rid,
            "when": {"input_type": input_type, "trigger": trigger},
            "condition": {"field": field},
            "then": {"action": action},
            "confidence": confidence,
            "support": 0,
            "created_at": datetime.now().isoformat(),
        }
        rule.update(extra)
        # Track the issued ID so the next unsaved add_rule() doesn't reuse it.
        self._pending_rule_ids.add(rid)
        return rule

    def save_anchors(self, anchors: dict):
        with open(self.anchors_file, 'w', encoding='utf-8') as f:
            json.dump(anchors, f, ensure_ascii=False, indent=2)

    def load_anchors(self) -> dict:
        if not os.path.exists(self.anchors_file):
            return {}
        with open(self.anchors_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_rules(self, rules: list):
        with open(self.rules_file, 'w', encoding='utf-8') as f:
            for rule in rules:
                f.write(json.dumps(rule, ensure_ascii=False) + '\n')
        # Disk is now the source of truth — pending IDs are reconciled.
        self._pending_rule_ids.clear()

    def load_rules(self) -> list:
        return self._load_jsonl(self.rules_file)

    def retrieve_rules(
        self,
        input_type: str,
        trigger: str = "field_extraction",
        input_signature=None,
        top_k: int = 10,
    ) -> list:
        """Slice 1: filter rules by input_type + trigger.

        Reserved parameters (input_signature) and behaviors (KG expansion,
        signature preference, lazy decay) land in slices 2-4.
        """
        rules = self.load_rules()
        matched = [
            r for r in rules
            if r.get("when", {}).get("trigger") == trigger
            and r.get("when", {}).get("input_type") in (input_type, "auto")
            and r.get("confidence", 0.0) >= 0.3
        ]
        # Dedupe by rule ID — keep highest-confidence copy.
        # Sort first so the first occurrence of each ID is the one we keep.
        matched.sort(key=lambda r: r.get("confidence", 0.0), reverse=True)
        seen_ids = set()
        deduped = []
        for r in matched:
            rid = r.get("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            deduped.append(r)
        # Tag each returned rule with in-memory provenance. _source is NOT
        # persisted — it lives only on the returned copies.
        return [{**r, "_source": "direct"} for r in deduped[:top_k]]
        
    def save_success_patterns(self, patterns: list):
        with open(self.patterns_file, 'w', encoding='utf-8') as f:
            for pattern in patterns:
                f.write(json.dumps(pattern, ensure_ascii=False) + '\n')

    def load_success_patterns(self) -> list:
        return self._load_jsonl(self.patterns_file)
        
    def save_knowledge_graph(self, graph: dict):
        with open(self.graph_file, 'w', encoding='utf-8') as f:
            json.dump(graph, f, ensure_ascii=False, indent=2)

    def load_knowledge_graph(self) -> dict:
        if not os.path.exists(self.graph_file):
            return {"schema_version": "1.0", "edges": []}
        with open(self.graph_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _load_jsonl(self, filepath: str) -> list:
        if not os.path.exists(filepath):
            return []
        items = []
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
        return items
