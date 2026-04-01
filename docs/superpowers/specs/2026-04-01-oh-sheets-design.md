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
    - `Blank Base Template` (the empty target Excel file structure)
    - `Sample Input` (e.g., a PDF, an image, or a messy Excel file)
    - `Sample Target Output` (the base template correctly populated with data from the sample input)
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

#### B. Calling Rules (Orchestration & Variant Routing)
The Agent (orchestrator) handles the execution. It NEVER calls these scripts blindly.
1.  **Selection (LLM Fast Classification):** Agent briefly inspects the document (MIME type and the first few lines of text) and uses a fast LLM classification to match it to a known variant script. 
2.  **Execution:** The Agent calls the selected script using standard bash execution:
    `python ~/.oh-sheets/templates/VendorInvoices/extractors/pdf_variant_a.py --input /path/to/invoice.pdf --output /tmp/out.json`
3.  **Boundary & Chain Routing:** If the script returns Exit `1`, the Agent falls back to sequentially testing other variant scripts for that MIME type. To prevent infinite loops, the maximum sequential fallback depth is 3. If all fail, the Agent escalates to LLM Vision Fallback.

#### C. Management Rules (Continuous Improvement & Structures)
*   **`rules.md` Format:** Must strictly adhere to defined Markdown sections:
    - `# Global Rules`: General template requirements (e.g., "All dates must be YYYY-MM-DD").
    - `# Field Mappings`: Specific quirks for fields (e.g., "The field 'total' is sometimes labeled 'Amount Due' in PDF layouts").
*   **Variant Scripts (`extractors/*.py`):** Immutable once verified by the Test Set. If a new input layout breaks an existing script, the system DOES NOT modify the old script. Instead, it creates a *new* variant script (e.g., `pdf_variant_d.py`) via Workflow D.

### 4. Core Workflows

#### Workflow 0: The Environment Sentinel (Pre-flight Check)
* **Trigger:** Runs automatically via `scripts/env_check.py` at the start of ANY invocation.
* **Role:** Ensures required packages (`docling`, `pdf2image`, `pandas`, `openpyxl`, `Pillow`) and system dependencies (`poppler`) are installed. Halts with an actionable installation command if missing.

#### Workflow A: The Learner (Adaptive Training via Agent-Driven RALPH Loop)
* **Trigger:** User completes the Interactive Initialization Flow.
* **Note on Agent-Driven RALPH Loop:** To avoid requiring users to manage API keys or install brittle third-party LLM wrappers like `litellm`, the RALPH loop is handled entirely via **Inversion of Control**. The host Agent (e.g., Gemini CLI) acts as the loop orchestrator, utilizing its native tool-calling permissions and existing session authentication.
* **Process:**
  1. **Schema Generation:** Agent analyzes the `Blank Base Template` to create `schema.json`.
  2. **Draft:** Agent drafts an initial variant script (e.g., `pdf_variant_a.py`) using its native file-writing tools.
  3. **Test:** Agent natively executes the drafted script on the Test Set Input.
  4. **Data-Level Diff:** Agent natively executes `scripts/data_diff.py` to strictly compare *data values* against the Benchmark Output.
  5. **Reflect & Fix (The Agent Loop):** The Agent reads the `stdout` of the diff tool. If errors exist, the Agent uses its context window to iteratively rewrite the Python script and re-run the tests.
  6. **End Conditions & Error Handling:** 
     - *Success:* Terminates when `data_diff.py` reports 100% accuracy.
     - *Mismatch Error:* Guided by `prompt_templates.md`, if the Agent fails after 5 iterations, it halts and prompts the user: *"Extraction failed to converge. Please check if the Sample Input actually contains all the data required by the Target Output."*

#### Workflow B: The Multi-modal Extractor (Execution with Variant Routing)
* **Trigger:** User provides a new document and specifies the target template.
* **Process:**
  1. **Routing & Execution:** Agent selects the correct script via LLM Fast Classification and calls it.
  2. **LLM Agent Intervention (Fallback):** If the script fails and max fallback depth is reached:
     - *Visual Inputs (PDF/Image/Word):* Convert to images (`pdf2image`), utilize native Vision + `rules.md`.
     - *Data Inputs (Messy Excel):* Bypass Vision. Utilize LLM-driven `pandas` manipulation.
     - *Fatal Error:* If Vision/LLM fallback itself fails to find the data, the process halts and notifies the user that manual data entry is required.

#### Workflow C: The Sanity Checker (Independent LLM Review)
* **Role:** Semantic validation of the intermediate JSON against common sense and `rules.md`.
* **Correction Loop:** Outputs either validated JSON OR an array of contextual errors feeding back into Workflow B's fallback loop. 
* **Loop Limit:** To prevent endless looping, the B → C → B loop is capped at a maximum of 3 attempts. If it fails on the 3rd attempt, execution halts for human intervention.

#### Workflow D: The Continuous Learning Trigger
* **Role:** If Workflow B relies heavily on LLM fallback, it prompts: "I had to use LLM fallback for this document format. Should I run an Agent-driven RALPH loop to create a new extractor script variant for this layout?" 
* **Requirement:** To run this loop safely for the new layout variant, the system *must* pause and ask the user to provide a verified Test Set Benchmark Output for this specific new document before proceeding.

#### Workflow E: The Non-Destructive Writer
* **Role:** Calls `scripts/excel_writer.py` to inject the verified JSON into the blank target Excel using `openpyxl`, preserving all styles, formulas, and macros.

## Phased Implementation Plan

To manage complexity, the development of `oh-sheets!` will be phased:
*   **Phase 1: Core Deterministic Pipeline.** Implement Workflow 0 (Environment), Workflow A (Agent-driven Learner loop), Workflow B (Basic Execution), and Workflow E (Non-destructive writer).
*   **Phase 2: Semantic Resilience.** Implement Workflow B fallback (Vision & Pandas rescue) and Workflow C (Sanity Checker).
*   **Phase 3: Continuous Evolution.** Implement Workflow D (Continuous Learning / Variant Management) and the CLI management commands (`list`, `delete`).