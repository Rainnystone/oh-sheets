import os
import json

class ReferenceBank:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.anchors_file = os.path.join(self.base_dir, "anchors.json")
        self.rules_file = os.path.join(self.base_dir, "rules.jsonl")
        self.patterns_file = os.path.join(self.base_dir, "success_patterns.jsonl")
        self.graph_file = os.path.join(self.base_dir, "knowledge_graph.json")

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

    def load_rules(self) -> list:
        return self._load_jsonl(self.rules_file)
        
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
