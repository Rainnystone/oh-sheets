# oh-sheets! Design Spec

## Overview
`oh-sheets!` is a meta-skill extension for coding agents (Gemini CLI, Claude Code, etc.) designed to automate the extraction of unstructured/semi-structured data (PDFs, Images, Word docs, Messy Excel files) into fixed-format Excel templates. Instead of hardcoding rules, it learns from user-provided examples (Input + Target Excel + Test Set) through an adaptive learning loop, generating specialized extraction scripts and knowledge references for each target template.

## Human Usability & CLI UX

The system prioritizes a clean, explicit, and guided user experience. It is deployed as a standard Agent Skill (e.g., in `~/.gemini/extensions/oh-sheets/`).

### Interactive Initialization & Learning Flow
To ensure the system has all necessary data to generate a robust script, the initialization and learning process is highly interactive:

1.  **Trigger:** User initiates the learning process: `oh-sheets learn`
2.  **Workspace Confirmation:** The agent confirms the working directory or prompts the user for the path to the folder containing their files.
3.  **Sample Data Prompt:** The agent asks for the paths to:
    - `Sample Input` (e.g., a PDF, an image, or a messy Excel file)
    - `Sample Target Output` (the specific fixed-format Excel template populated with data from the sample input)
4.  **Test Set Prompt:** Once samples are provided, the agent *requires* a test set to validate its learning. It prompts for:
    - `Test Set Input` (another instance of the same input type/layout)
    - `Test Set Benchmark Output` (the correctly filled Excel file for the test input)

### Daily Execution & Management Commands
*   **Daily Execution:** 
    `"oh-sheets extract --template 'VendorInvoices' --input new_invoice.pdf --output out.xlsx"`
*   **Management:** 
    `"oh-sheets list"` (Shows all learned target templates)
    `"oh-sheets delete 'VendorInvoices'"`

## Architecture, File Structure & Orchestration

The system relies on two distinct directory structures: the **Extension Source Structure** (the immutable tool itself) and the **Template Storage Structure** (the dynamically generated scripts and rules).

### 1. Extension Source Directory (The oh-sheets Tool)
This is where the plugin/skill itself is installed (e.g., `~/.gemini/extensions/oh-sheets/`).

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
~/.oh-sheets/templates/VendorInvoices/
├── template.xlsx        # The blank target Excel file
├── schema.json          # Strict schema mapping 1:1 to target Excel cells
├── rules.md             # Global reference rules for this TARGET template
└── extractors/          # Deterministic scripts grouped by INPUT variant
    ├── pdf_variant_a.py # Script specifically for PDF layout 'A'
    ├── img_variant_b.py # Script specifically for Image layout 'B'
    └── xls_messy_c.py   # Script specifically for Messy Excel format 'C'
```

### 3. Technical Management: Rules for Writing, Calling, and Updating Scripts

To ensure the Agent can reliably orchestrate these dynamically generated Python scripts, the system enforces strict rules:

#### A. Writing Rules (The Script I/O Contract)
When the internal RALPH loop generates a script in `extractors/`, it MUST adhere to this contract:
*   **Inputs:** Accept standard CLI arguments: `--input <file_path>` and `--output <json_path>`.
*   **Outputs:** Must write extracted data to the `<json_path>` strictly matching the parent directory's `schema.json`.
*   **Dependencies:** Allowed to use `docling`, `pandas`, `pdf2image`, `re`, `json`.
*   **Exit Codes:** Exit `0` on success. Exit `1` with a clean `stderr` message if parsing fails (e.g., layout mismatch).

#### B. Calling Rules (Orchestration)
The Agent (orchestrator) handles the execution. It NEVER calls these scripts blindly.
1.  **Selection:** Agent inspects the MIME type of the input file. If it's a PDF, it scans the `extractors/` folder for `pdf_variant_*.py` scripts.
2.  **Execution:** The Agent calls the script using standard bash execution:
    `python ~/.oh-sheets/templates/VendorInvoices/extractors/pdf_variant_a.py --input /path/to/invoice.pdf --output /tmp/out.json`
3.  **Boundary & Routing:** If the script returns Exit `0`, the Agent moves to the Sanity Checker. If it returns Exit `1`, the Agent *catches* the error and either calls the next variant script or escalates to LLM Vision Fallback.

#### C. Management Rules (Continuous Improvement)
*   **`rules.md`:** Governs the *target template*. Updated exclusively by the Agent when it learns a new business rule (e.g., "The 'total' must always be parsed as a float") during either the initial RALPH loop or a Continuous Learning cycle.
*   **Variant Scripts (`extractors/*.py`):** Immutable once verified by the Test Set. If a new input layout breaks an existing script, the system DOES NOT modify the old script. Instead, it creates a *new* variant script (e.g., `pdf_variant_d.py`) via Workflow D.

### 4. Core Workflows

#### Workflow 0: The Environment Sentinel (Pre-flight Check)
* **Trigger:** Runs automatically via `scripts/env_check.py` at the start of ANY invocation.
* **Role:** Ensures required packages (`docling`, `pdf2image`, `pandas`, `openpyxl`, `Pillow`) and system dependencies (`poppler`) are installed. Halts with an actionable installation command if missing.

#### Workflow A: The Learner (Adaptive Training via Internal RALPH Loop)
* **Trigger:** User completes the Interactive Initialization Flow.
* **Note on RALPH Loop:** A lightweight, internal mechanism. The LLM writes code, tests it using `scripts/data_diff.py`, reads errors, and rewrites it without external frameworks.
* **Process:**
  1. **Schema Generation:** Agent creates `schema.json` from the provided Target Output Excel.
  2. **Draft:** Agent drafts an initial variant script (e.g., `pdf_variant_a.py`).
  3. **Test:** Agent runs the script on the Test Set Input.
  4. **Data-Level Diff:** `scripts/data_diff.py` strictly compares *data values* against the Test Set Benchmark Output.
  5. **Reflect & Fix:** Agent automatically reads the diff report, updates the Python script and `rules.md`, and loops until 100% accurate.

#### Workflow B: The Multi-modal Extractor (Execution with Variant Routing)
* **Trigger:** User provides a new document and specifies the target template.
* **Process:**
  1. **Routing & Execution:** Agent selects the correct script based on input type and calls it via the strict Calling Rules.
  2. **LLM Agent Intervention (Fallback):** If all appropriate variant scripts fail (exit `1`):
     - *Visual Inputs (PDF/Image/Word):* Convert to images (`pdf2image`), utilize native Vision + `rules.md`.
     - *Data Inputs (Messy Excel):* Bypass Vision. Utilize LLM-driven `pandas` manipulation.

#### Workflow C: The Sanity Checker (Independent LLM Review)
* **Role:** Semantic validation of the intermediate JSON against common sense and `rules.md`.
* **Correction:** Outputs either validated JSON OR an array of contextual errors feeding back into Workflow B's fallback loop.

#### Workflow D: The Continuous Learning Trigger
* **Role:** If Workflow B relies on LLM fallback, it prompts: "I had to use LLM fallback for this document format. Should I run an internal RALPH loop to create a new extractor script variant for this layout?" (Generates `pdf_variant_new.py`).

#### Workflow E: The Non-Destructive Writer
* **Role:** Calls `scripts/excel_writer.py` to inject the verified JSON into the blank target Excel using `openpyxl`, preserving all styles, formulas, and macros.

## Phased Implementation Plan

To manage complexity, the development of `oh-sheets!` will be phased:
*   **Phase 1: Core Deterministic Pipeline.** Implement Workflow 0 (Environment), Workflow A (Learner loop), Workflow B (Basic Execution), and Workflow E (Non-destructive writer).
*   **Phase 2: Semantic Resilience.** Implement Workflow B fallback (Vision & Pandas rescue) and Workflow C (Sanity Checker).
*   **Phase 3: Continuous Evolution.** Implement Workflow D (Continuous Learning / Variant Management) and the CLI management commands (`list`, `delete`).