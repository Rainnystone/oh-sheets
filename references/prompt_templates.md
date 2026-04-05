# Prompt Templates

## RALPH Loop Schema Draft Prompt
You are an expert data architect. Analyze the provided `Blank Base Template` Excel file and generate a `schema.json` file.
The schema must capture semantic meaning plus row/column relationships, not just one-off cell coordinates.
Format example:
```
{
  "meta": {
    "signature": "<template_signature>",
    "version": 1
  },
  "fields": {
    "Field_A": {"cell": "B2", "type": "string"},
    "Field_B": {"cell": "B3", "type": "string"},
    "Field_C": {
      "relative_to": "Field_B",
      "row_offset": 0,
      "col_offset": 1,
      "type": "string"
    }
  }
}
```
`relative_to` means this field is positioned by offset from another field. Keep this rule for any repeated pattern you can infer in the template.
`schema.json` should also keep a stable row/column structure contract so later versions can be compared safely before execution.

## RALPH Execution Guard Prompt
When routing execution, compare template signatures before filling any fields.
Run `python scripts/template_layout_signature.py --template <template-to-check> --output <tmp_profile> --compare-with <stored_profile_json>`.
If compatibility is `incompatible` or `hard_mismatch` is true, do not continue to write output.
Return to learn mode with this exact note: `template signature mismatch; requires structural re-learn before execution`.

## Local Few-Shot Feedback Prompt
For every execution with any validation failure, persist a compact event:
`{"template_signature","error_type","missing_fields","repair_action","human_confirmed","confidence","rule_ids"}`.
Save it with:
`python scripts/local_few_shot_memory.py --memory-dir <template_memory_dir> --record '<json>'`.
After each run, rebuild compact rules with:
`python scripts/local_few_shot_memory.py --memory-dir <template_memory_dir> --rebuild-summary --min-support 2`.
On next run, query:
`python scripts/local_few_shot_memory.py --memory-dir <template_memory_dir> --query <template_signature> <error_type> <comma_fields>`
and apply matched `repair_action` candidates before any manual assumptions.

## RALPH Loop Code Draft Prompt
You are an expert Python script generator.
Your task is to write an extractor script that parses the provided `Sample Input` and outputs a JSON file that perfectly matches the `schema.json`.
The script MUST accept `--input` and `--output` arguments.
It must exit 0 on success, and exit 1 on failure.
Dependencies allowed: docling, pandas, pdf2image, re, json.

## RALPH Loop Fix Prompt
Your previous script failed the `data_diff.py` check.
Here is the error output from `data_diff.py`.

Please rewrite the extractor script to fix these errors. Update `rules.md` if you discover a new global rule or field mapping quirk.

## REFLECT Phase (Reference Bank v2)
- Input: execution logs, error fields, feedback signal
- Output: Generate rules in rules.jsonl, extract success cases to success_patterns.jsonl
