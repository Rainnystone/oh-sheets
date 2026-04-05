import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _ensure_memory_dir(memory_dir):
    memory_root = Path(memory_dir)
    memory_root.mkdir(parents=True, exist_ok=True)
    return {
        "execution_log": memory_root / "execution_log.jsonl",
        "failure_clusters": memory_root / "failure_clusters.json",
        "summary_rules": memory_root / "summary_rules.json",
    }


def _load_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _dump_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _event_id(event):
    digest = hashlib.sha1(json.dumps(event, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return digest[:12]


def _normalize_missing_fields(event):
    missing = event.get("missing_fields", [])
    if isinstance(missing, list):
        return sorted([str(item).strip() for item in missing if str(item).strip()])
    return []


def _failure_cluster_key(event):
    return "|".join([
        str(event.get("error_type", "unknown")),
        ",".join(_normalize_missing_fields(event)),
        str(event.get("template_signature", "")),
    ])


def _read_execution_log(execution_log_path):
    events = []
    if not execution_log_path.exists():
        return events
    with open(execution_log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                # keep going; ignore malformed historical lines
                continue
    return events


def record_execution(memory_dir, event):
    paths = _ensure_memory_dir(memory_dir)
    payload = dict(event)
    payload.setdefault("ts", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    payload.setdefault("event_id", _event_id(payload))
    payload["missing_fields"] = _normalize_missing_fields(payload)
    payload["cluster_key"] = _failure_cluster_key(payload)

    with open(paths["execution_log"], "a", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
        f.write("\n")
    return payload


def rebuild_failure_summary(memory_dir, min_support=2):
    paths = _ensure_memory_dir(memory_dir)
    events = _read_execution_log(paths["execution_log"])
    clusters = {}
    for event in events:
        if not event.get("error_type"):
            continue
        key = event.get("cluster_key") or _failure_cluster_key(event)
        cluster = clusters.setdefault(key, {
            "cluster_key": key,
            "signature": event.get("template_signature", ""),
            "error_type": event.get("error_type", "unknown"),
            "missing_fields": _normalize_missing_fields(event),
            "samples": 0,
            "repair_actions": defaultdict(int),
            "events": [],
            "last_ts": "",
        })
        cluster["samples"] += 1
        cluster["events"].append(event.get("event_id"))
        cluster["last_ts"] = event.get("ts", "")
        if event.get("repair_action"):
            cluster["repair_actions"][event.get("repair_action")] += 1

    # keep top repair_action, sorted by vote
    cluster_list = []
    for cluster in clusters.values():
        best_action = ""
        best_votes = 0
        for action, votes in cluster["repair_actions"].items():
            if votes > best_votes:
                best_action = action
                best_votes = votes
        cluster["top_repair_action"] = best_action
        cluster["top_repair_votes"] = best_votes
        # remove non-JSON-safe defaultdict
        cluster["repair_actions"] = dict(cluster["repair_actions"])
        cluster_list.append(cluster)

    by_support = sorted(cluster_list, key=lambda item: item["samples"], reverse=True)
    summary = {"schema_version": "1.0", "clusters": by_support}
    _dump_json(paths["failure_clusters"], summary)

    # build reusable summary rules (only clusters with support >= min_support)
    rules = []
    rule_no = 1
    for cluster in by_support:
        if cluster["samples"] < min_support:
            continue
        if not cluster["top_repair_action"]:
            continue
        rules.append({
            "id": f"R{rule_no:03d}",
            "template_signature": cluster["signature"],
            "error_type": cluster["error_type"],
            "missing_fields": cluster["missing_fields"],
            "repair_action": cluster["top_repair_action"],
            "support": cluster["samples"],
            "vote_rate": cluster["top_repair_votes"] / cluster["samples"],
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
        rule_no += 1

    _dump_json(paths["summary_rules"], {"schema_version": "1.0", "rules": rules})
    return {"clusters": summary, "rules": {"schema_version": "1.0", "rules": rules}}


def suggest_repairs(memory_dir, template_signature, error_type, missing_fields=None):
    paths = _ensure_memory_dir(memory_dir)
    data = _load_json(paths["summary_rules"], {"schema_version": "1.0", "rules": []})
    missing_fields = sorted([str(item).strip() for item in (missing_fields or []) if str(item).strip()])
    rules = []
    for rule in data.get("rules", []):
        if str(rule.get("template_signature", "")) != str(template_signature):
            continue
        if str(rule.get("error_type", "")) != str(error_type):
            continue
        rule_fields = sorted(rule.get("missing_fields", []))
        if rule_fields != missing_fields and missing_fields:
            continue
        rules.append(rule)
    return rules


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-dir", required=True)
    parser.add_argument("--record", help="Record one event by JSON string")
    parser.add_argument("--rebuild-summary", action="store_true")
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument("--query", nargs=3, metavar=("SIGNATURE", "ERROR_TYPE", "FIELDS"), help="Query rules by signature,error_type,comma-separated-fields")
    args = parser.parse_args()

    if args.record:
        event = json.loads(args.record)
        payload = record_execution(args.memory_dir, event)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.rebuild_summary:
        report = rebuild_failure_summary(args.memory_dir, min_support=args.min_support)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    if args.query:
        signature, error_type, fields = args.query
        fields_list = [item for item in fields.split(",") if item]
        rules = suggest_repairs(args.memory_dir, signature, error_type, fields_list)
        print(json.dumps(rules, ensure_ascii=False, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()


def record_success_pattern(memory_dir: str, pattern: dict):
    """Wrapper to interact with Reference Bank success patterns."""
    from scripts.core.reference_bank import ReferenceBank
    bank = ReferenceBank(memory_dir)
    patterns = bank.load_success_patterns()
    patterns.append(pattern)
    bank.save_success_patterns(patterns)
