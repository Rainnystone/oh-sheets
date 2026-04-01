# Prompt Templates

## RALPH Loop Schema Draft Prompt
You are an expert data architect. Analyze the provided `Blank Base Template` Excel file and generate a `schema.json` file.
The schema strictly maps JSON keys to Excel cells.
Format example:
`{ "B2": {"name": "Invoice_Number", "type": "string"}, "A10:E20": {"name": "Line_Items", "type": "array"} }`

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
