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

    def query_anchors(self, field: str | None = None):
        """Slice 2: query the anchor store.

        - field=None → return all anchors (the full dict).
        - field given → return that field's anchor (a dict). Returns None
          if the field has no anchor.
        """
        anchors = self.load_anchors()
        if field is None:
            return anchors
        return anchors.get(field)

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
        """Filter rules by input_type + trigger, then expand 1 hop via the
        knowledge graph (slice 2).

        Reserved parameters (input_signature) and behaviors (signature
        preference, lazy decay) land in slices 3-4.
        """
        rules = self.load_rules()
        direct = [
            r for r in rules
            if r.get("when", {}).get("trigger", "field_extraction") == trigger
            and r.get("when", {}).get("input_type", "auto") in (input_type, "auto")
            and r.get("confidence", 0.0) >= 0.3
        ]
        direct_ids = {r.get("id") for r in direct}
        # Slice 2: expand via KG. _expand_via_kg returns neighbor rules
        # (not in direct_ids) tagged with _source="via_kg".
        via_kg = self._expand_via_kg(direct_ids)

        # Combine direct + via_kg. Sort by confidence desc.
        combined = direct + via_kg
        combined.sort(key=lambda r: r.get("confidence", 0.0), reverse=True)

        # Dedupe by rule ID. If a rule is both direct and via_kg, direct
        # wins — keep _source="direct". Sort already puts the direct copy
        # first only if its confidence is >= the via_kg copy's, which isn't
        # guaranteed, so track seen IDs and prefer direct on collision.
        seen: dict[str, dict] = {}
        for r in combined:
            rid = r.get("id")
            if rid not in seen:
                seen[rid] = r
            else:
                # Collision: prefer direct over via_kg
                if r.get("_source") == "direct" and seen[rid].get("_source") != "direct":
                    seen[rid] = r
        deduped = list(seen.values())

        # Tag any untagged (direct) rules with _source="direct". via_kg
        # rules already carry _source from _expand_via_kg.
        result = []
        for r in deduped[:top_k]:
            if "_source" not in r:
                result.append({**r, "_source": "direct"})
            else:
                result.append(r)
        return result

    def _expand_via_kg(self, direct_rule_ids: set) -> list:
        """Slice 2: find 1-hop neighbor rules via the knowledge graph.

        Edge semantics:
        - uses_anchor: symmetric among rules. If R001 and R002 both use
          anchor A1, each is a neighbor of the other.
        - often_follows: directional. Edge {from: R001, to: R002} means
          R002 is a neighbor of R001 (not the reverse).

        Only 1 hop — no transitive expansion. Neighbor rules already in
        direct_rule_ids are excluded (they'll be tagged "direct" upstream).
        Returns neighbor rule dicts with _source="via_kg" set (in-memory).
        """
        graph = self.load_knowledge_graph()
        edges = graph.get("edges", [])

        # Build anchor → rules map for uses_anchor symmetry, and collect
        # directional often_follows neighbors.
        anchor_to_rules: dict[str, set[str]] = {}
        often_follows_neighbors: dict[str, set[str]] = {}
        for e in edges:
            rel = e.get("relation")
            src = e.get("from")
            dst = e.get("to")
            if rel == "uses_anchor":
                # src is a rule, dst is an anchor
                anchor_to_rules.setdefault(dst, set()).add(src)
            elif rel == "often_follows":
                # directional: src → dst (both rules)
                often_follows_neighbors.setdefault(src, set()).add(dst)

        # Collect neighbor rule IDs reachable in 1 hop from direct rules.
        neighbor_ids: set[str] = set()
        for rid in direct_rule_ids:
            # uses_anchor: find anchors used by rid, then other rules
            # using the same anchor.
            for anchor, rule_set in anchor_to_rules.items():
                if rid in rule_set:
                    neighbor_ids.update(rule_set - {rid})
            # often_follows: directional neighbors
            neighbor_ids.update(often_follows_neighbors.get(rid, set()))

        # Exclude rules already in the direct set.
        neighbor_ids -= direct_rule_ids
        if not neighbor_ids:
            return []

        # Load neighbor rule dicts, apply quality filter (consistency with
        # direct path), tag with _source="via_kg".
        all_rules = self.load_rules()
        neighbors = [
            {**r, "_source": "via_kg"}
            for r in all_rules
            if r.get("id") in neighbor_ids
            and r.get("confidence", 0.0) >= 0.3
        ]
        return neighbors
        
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
