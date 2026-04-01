# oh-sheets! Design Spec

## Overview
`oh-sheets!` is a meta-skill extension for coding agents (Gemini CLI, Claude Code, etc.) designed to automate the extraction of unstructured/semi-structured data (PDFs, Images, Word docs, Messy Excel files) into fixed-format Excel templates. Instead of hardcoding rules, it learns from user-provided examples (Input + Target Excel + Test Set) through an adaptive learning loop, generating specialized extraction scripts and knowledge references for each target template.

## Installation & First Run

`oh-sheets!` is deployed as a standard Agent extension.
*   **Installation:** Users clone or copy the extension into their agent's designated directory (e.g., `git clone <repo> ~/.gemini/extensions/oh-sheets`).
*   **First Run / Help:** Running `oh-sheets` or `oh-sheets --help` outputs a welcome message, verifies the directory structure, and explains the primary commands (`learn`, `extract`, `list`, `delete`).

## Human Usability & CLI UX

The system prioritizes a clean, explicit, and guided user experience.

### Interactive Initialization & Learning Flow
To ensure the system has all necessary data to generate a robust script, the initialization and learning process is highly interactive:

1.  **Trigger & Naming:** User initiates: `oh-sheets learn`. The Agent prompts: *"What would you like to name this template? (e.g., ProjectTemplate)"*. This establishes the `<template-name>` for storage.
2.  **Workspace Confirmation:** The agent confirms the working directory.
3.  **Sample Data Prompt:** The agent asks for the paths to:
    - `Blank Base Template` (the empty target Excel file structure)
    - `Sample Input` (e.g., a PDF, an image, or a messy Excel file)
    - `Sample Target Output` (the base template correctly populated with data from the sample input)
4.  **Pre-validation:** Before proceeding, the Agent briefly inspects the Sample Input and Sample Target Output to verify a baseline correlation (ensuring the user didn't provide mismatched files).
5.  **Test Set Prompt:** The agent *requires* a test set. It prompts for:
    - `Test Set Input` (another instance of the same input type/layout)
    - `Test Set Benchmark Output` (the correctly filled Excel file for the test input)
6.  **Success Feedback:** Upon successful completion of the learning loop, the agent outputs: *"Learning complete! Created template '<template-name>'. You can now extract data using: `oh-sheets extract --template '<template-name>' --input <file> --output <file>`"*.

### Daily Execution & Management Commands
*   **Daily Execution:** 
    `"oh-sheets extract --template 'ProjectTemplate' --input source_file.pdf --output out.xlsx"` *(Note: `--output` overwrites the destination file by default).*
*   **Management:** 
    `"oh-sheets list"` (Outputs a table showing: Template Name, Number of Variants, Last Updated).
    `"oh-sheets delete 'ProjectTemplate'"` (Prompts for confirmation before deleting the template directory).

## Architecture, File Structure & Orchestration

The system relies on two distinct directory structures: the **Extension Source Structure** (the immutable tool itself) and the **Template Storage Structure** (the dynamically generated scripts and rules).

### 1. Extension Source Directory (The oh-sheets Tool)

```
oh-sheets/
├── SKILL.md                # The primary agent instructions and routing logic
├── scripts/                # Immutable core utility scripts
│   ├── env_check.py        # Validates docling, pandas, openpyxl, etc.
│   ├── data_diff.py        # The deterministic JSON/CSV diff tool for the RALPH loop
│   └── excel_writer.py     # The non-destructive openpyxl writer
└── references/
    └── prompt_templates.md # Pre-defined LLM prompts for the Sanity Checker and RALPH Loop
```

### 2. Template Storage Structure (Generated Artifacts)
Configurations are grouped by the **Target Output Excel Template** in `~/.oh-sheets/templates/<template-name>/`:

```
~/.oh-sheets/templates/ProjectTemplate/
├── template.xlsx        # The blank target Excel file
├── schema.json          # Strict schema mapping JSON keys to Target Excel cells
├── rules.md             # Global reference rules for this TARGET template
└── extractors/          # Deterministic scripts grouped by INPUT variant
    ├── pdf_variant_1.py # Script specifically for PDF layout variant 1
    ├── img_variant_1.py # Script specifically for Image layout variant 1
    └── xls_messy_1.py   # Script specifically for Messy Excel format variant 1
```

### 3. Technical Management: Rules for Writing, Calling, and Updating Scripts

#### A. Schema Format (`schema.json`)
The schema strictly maps intermediate JSON keys to Excel cells or ranges, acting as the contract between the extractors and the `excel_writer.py`.
Format example:
```
{
  "meta": {
    "version": "2",
    "signature": "<template_layout_signature>"
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
`relative_to` records row/column structure so the system can compare template versions before execution.

#### B. Writing Rules (The Script I/O Contract)
Generated scripts in `extractors/` MUST adhere to:
*   **Inputs:** Accept standard CLI arguments: `--input <file_path>` and `--output <json_path>`.
*   **Outputs:** Write extracted data to `<json_path>` using keys that strictly map to the cells defined in `schema.json`.
*   **Exit Codes:** Exit `0` on success. Exit `1` with a clean `stderr` message if parsing fails.

#### C. Calling Rules (Orchestration & Variant Routing)
1.  **Selection (LLM Fast Classification):** Agent briefly inspects the document and matches it to a known variant script.
2.  **Execution:** The Agent calls the script using standard bash execution.
3.  **Boundary & Chain Routing:** If the script returns Exit `1`, the Agent falls back to sequentially testing other variant scripts for that MIME type. The maximum sequential fallback depth is strictly **3**. If all fail, escalate to LLM Vision Fallback.

#### D. Management Rules (Continuous Improvement)
*   **`rules.md` Format:** Must adhere to Markdown sections: `# Global Rules` and `# Field Mappings`.
*   **Variant Scripts:** Immutable once verified. New layouts result in new scripts (e.g., `pdf_variant_2.py`) rather than modifying old ones.

### 4. Core Workflows

#### Workflow 0: The Environment Sentinel (Pre-flight Check)
* **Trigger:** Runs automatically via `scripts/env_check.py` at the start of ANY invocation.
* **Role:** Ensures required packages (`docling`, `pdf2image`, `pandas`, `openpyxl`, `Pillow`) and system dependencies (`poppler`) are installed. Halts with an actionable installation command if missing.

#### Workflow A: The Learner (Adaptive Training via Agent-Driven RALPH Loop)
* **Trigger:** User completes Interactive Initialization Flow.
* **Note on Agent-Driven RALPH Loop:** The loop is handled via **Inversion of Control**. The host Agent (e.g., Gemini CLI) acts as the loop orchestrator, utilizing its native tool-calling permissions.
* **Process:**
  1. **Schema Generation:** Agent analyzes the `Blank Base Template` to create `schema.json`.
  2. **Draft:** Agent drafts an initial variant script using native file-writing tools.
  3. **Test:** Agent executes the drafted script on the Test Set Input.
  4. **Data-Level Diff:** Agent executes `scripts/data_diff.py` to compare data values. *Rule: Exact string match (trimmed); floats rounded to 2 decimal places.*
  5. **Reflect & Fix (The Agent Loop):** The Agent reads the `stdout` of the diff tool. If errors exist, it rewrites the Python script and re-runs the tests.
  6. **End Conditions:** 
     - *Success:* Terminates when `data_diff.py` reports 100% accuracy.
     - *Mismatch Error:* Halts after exactly **5 iterations** with prompt: *"Extraction failed to converge. Please check if the Sample Input actually contains all the data required by the Target Output."*

#### Workflow B: The Multi-modal Extractor (Execution with Variant Routing)
* **Trigger:** User provides a new document and specifies the target template.
* **Process:**
  1. **Routing & Execution:** Agent selects the correct script and calls it.
  2. **LLM Agent Intervention (Fallback):** If the script fails and max fallback depth (3) is reached:
     - *Visual Inputs:* Convert to images, utilize native Vision + `rules.md`.
     - *Data Inputs:* Bypass Vision. Utilize LLM-driven `pandas` manipulation.
     - *Fatal Error:* If fallback fails, halt and notify user manual entry is required.

#### Workflow C: The Sanity Checker (Independent LLM Review)
* **Role:** Semantic validation of intermediate JSON against common sense and `rules.md`.
* **Correction Loop:** Outputs validated JSON OR contextual errors feeding back into Workflow B's fallback loop. 
* **Loop Limit:** The B → C → B loop is capped at strictly **3 attempts**. If it fails, execution halts for human intervention.

#### Workflow D: The Continuous Learning Trigger
* **Role:** If Workflow B relies heavily on LLM fallback, prompt user to run an Agent-driven RALPH loop to create a new extractor script. 
* **Requirement:** Must pause and ask user to provide a verified Test Set Benchmark Output for this specific new document before proceeding.

#### Workflow E: The Non-Destructive Writer
* **Role:** Calls `scripts/excel_writer.py` to inject verified JSON into the blank target Excel using `openpyxl`, preserving all styles, formulas, and macros.

## Phased Implementation Plan

*   **Phase 1: Core Deterministic Pipeline.** Implement Workflow 0, Workflow A, Workflow B (Basic Execution), and Workflow E.
*   **Phase 2: Semantic Resilience.** Implement Workflow B fallback and Workflow C.
*   **Phase 3: Continuous Evolution.** Implement Workflow D and CLI management commands.
