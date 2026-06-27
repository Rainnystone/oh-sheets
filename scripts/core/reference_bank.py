import os
import re
import json
from datetime import datetime

from scripts.core.signature_matcher import match_patterns
from scripts.core.rule_evolution import Outcome, update_rule_confidence

# Slice 3: _source precedence for retrieve_rules dedupe. Highest wins when
# the same rule is reachable via multiple paths. A rule that historically
# succeeded on a signature-matched input (via_signature) is a stronger
# signal than a mere type match (direct), which beats a KG neighbor (via_kg).
_SOURCE_PRECEDENCE = {"via_signature": 3, "direct": 2, "via_kg": 1}


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
        """Filter rules by input_type + trigger, expand via the knowledge
        graph (slice 2), then apply signature preference (slice 3).

        Source precedence (highest wins on dedupe):
            via_signature > direct > via_kg

        - direct: matched the input_type+trigger filter.
        - via_kg: 1-hop KG neighbor (uses_anchor symmetric, often_follows
          directional). Slice 2.
        - via_signature: succeeded on a signature-matched input before
          (rules_used in a matched success pattern). Slice 3.

        Slice 4: runs decay_inactive_rules() first so stale rules are
        pruned before reaching the prompt.
        """
        # Slice 4: lazy decay. Prune stale rules on read so the bank
        # never serves a decayed-confidence rule to the prompt. This is
        # the only place decay runs — no separate cron/tick.
        self.decay_inactive_rules()
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

        # Slice 3: signature preference. If an input_signature is given,
        # find success patterns that matched it and collect their
        # rules_used. Those rules enter the result set (or get upgraded)
        # with _source="via_signature" — the strongest provenance signal.
        via_signature: list[dict] = []
        if input_signature is not None:
            matched = match_patterns(
                input_signature, self.load_success_patterns(), top_k=3
            )
            preferred_ids: set[str] = set()
            for p in matched:
                preferred_ids.update(p.get("rules_used", []))
            if preferred_ids:
                via_signature = [
                    {**r, "_source": "via_signature"}
                    for r in rules
                    if r.get("id") in preferred_ids
                    and r.get("confidence", 0.0) >= 0.3
                ]

        # Combine all sources. Sort by confidence desc.
        combined = direct + via_kg + via_signature
        combined.sort(key=lambda r: r.get("confidence", 0.0), reverse=True)

        # Dedupe by rule ID, keeping the highest-precedence _source.
        # via_signature (3) > direct (2) > via_kg (1). A rule reachable
        # multiple ways keeps its strongest provenance.
        seen: dict[str, dict] = {}
        for r in combined:
            rid = r.get("id")
            src = r.get("_source", "direct")
            if rid not in seen:
                seen[rid] = r
            else:
                existing_src = seen[rid].get("_source", "direct")
                if _SOURCE_PRECEDENCE.get(src, 0) > _SOURCE_PRECEDENCE.get(existing_src, 0):
                    seen[rid] = r
        deduped = list(seen.values())

        # Tag any untagged (direct) rules with _source="direct". via_kg
        # and via_signature rules already carry _source from above.
        result = []
        for r in deduped[:top_k]:
            if "_source" not in r:
                result.append({**r, "_source": "direct"})
            else:
                result.append(r)

        # Slice 4: freshen last_used for retrieved rules. A rule that
        # reached the prompt was "used" — reset its inactivity clock so
        # it doesn't decay on the next retrieval. Persist without
        # _source (that's in-memory only — reloaded rules never carry it).
        retrieved_ids = {r.get("id") for r in result}
        if retrieved_ids:
            now_iso = datetime.now().isoformat()
            persisted = self.load_rules()
            for r in persisted:
                if r.get("id") in retrieved_ids:
                    r["last_used"] = now_iso
            self.save_rules(persisted)
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

    def _next_pattern_id(self) -> str:
        """Generate the next pattern ID as max(existing numeric IDs)+1.

        Same convention as _next_rule_id: P001, P002, ... Considers
        on-disk patterns only (record_success_pattern persists on every
        call, so there's no pending set to track).
        """
        max_n = 0
        for p in self.load_success_patterns():
            pid = p.get("pattern_id", "")
            m = re.match(r"^P(\d+)$", pid)
            if m:
                max_n = max(max_n, int(m.group(1)))
        return f"P{max_n + 1:03d}"

    def record_success_pattern(
        self,
        input_signature: str,
        input_type: str,
        extracted: dict,
        rules_used: list,
        anchors_matched: list,
        accuracy: float = 1.0,
    ) -> None:
        """Single writer for success patterns (slice 3).

        Populates the full spec §3.4 schema and persists immediately
        (append) to success_patterns.jsonl. Replaces the two inline
        appenders in the orchestrators and the dead writer in
        local_few_shot_memory.
        """
        pattern = {
            "pattern_id": self._next_pattern_id(),
            "input_signature": input_signature,
            "input_type": input_type,
            "fields_extracted": list(extracted.keys()),
            "accuracy": accuracy,
            "rules_used": list(rules_used),
            "anchors_matched": list(anchors_matched),
            "created_at": datetime.now().isoformat(),
        }
        patterns = self.load_success_patterns()
        patterns.append(pattern)
        self.save_success_patterns(patterns)

    def apply_outcome(self, outcome: "Outcome") -> int:
        """Slice 4: reward/penalize all rules per outcome.

        Replaces the three duplicated confidence-update loops in
        execution_orchestrator, learning_orchestrator.phase4_commit, and
        learning_orchestrator.phase5_reflect. Archives rules that drop
        below 0.3. Persists the updated rule set. Returns the count
        archived.
        """
        rules = self.load_rules()
        kept: list[dict] = []
        archived_count = 0
        for r in rules:
            ur = update_rule_confidence(r, outcome.value)
            if ur is None:
                archived_count += 1
            else:
                kept.append(ur)
        self.save_rules(kept)
        return archived_count

    def decay_inactive_rules(self, days: int = 30) -> int:
        """Slice 4: prune long-unused rules.

        A rule unused for > `days` has confidence multiplied by
        0.99^(days_since_use - days). Rules that drop below 0.3 are
        archived. Persists the updated rule set. Returns count archived.

        Absorbs the dead decay_rules function from rule_evolution.py —
        same math, but reads from / writes to the Bank's own files.
        Called lazily by retrieve_rules() so stale rules are always
        pruned before reaching the prompt.
        """
        rules = self.load_rules()
        now = datetime.now()
        kept: list[dict] = []
        archived_count = 0
        for rule in rules:
            decayed = rule.copy()
            last_used_str = decayed.get("last_used")
            if last_used_str:
                try:
                    last_used = datetime.fromisoformat(last_used_str)
                    # Normalize tz-aware timestamps (e.g. UTC written by
                    # another process) to naive local wall-clock so the
                    # subtraction against our naive `now` doesn't raise
                    # TypeError. Day-granularity decay tolerates the
                    # offset shift. astimezone() on a naive datetime is
                    # a no-op, so this branch handles both shapes.
                    if last_used.tzinfo is not None:
                        last_used = last_used.astimezone().replace(tzinfo=None)
                    days_since_use = (now - last_used).days
                    if days_since_use > days:
                        decay_factor = 0.99 ** (days_since_use - days)
                        decayed["confidence"] = round(
                            decayed.get("confidence", 0.5) * decay_factor, 4
                        )
                except ValueError:
                    pass
            if decayed.get("confidence", 0.5) >= 0.3:
                kept.append(decayed)
            else:
                archived_count += 1
        self.save_rules(kept)
        return archived_count
        
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
