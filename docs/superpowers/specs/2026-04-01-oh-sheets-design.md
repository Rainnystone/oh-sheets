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

## Architecture & Workflow

The system uses a **Unified Routing Architecture** orchestrated by the overarching Agent. The Agent is the smart orchestrator; the generated Python scripts are "dumb," deterministic executors.

### 1. Template Storage Structure (Local & Private)
Configurations are grouped by the **Target Output Excel Template**. For each learned target template, the system stores data in `~/.oh-sheets/templates/<template-name>/`:

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

*   **`rules.md` Management:** This reference is specific to the *target template*. It contains semantic mappings (e.g., "The field 'total' must always be a float"). It guides the LLM during fallbacks, regardless of the input type.
*   **`extractors/` Management:** Scripts are strictly bound to an *input type and layout variant*. A single target template can be fed by many different input types, each with its own generated Python script.

### 2. Technical Management & Boundaries

#### The Script I/O Contract
All scripts in `extractors/` must adhere to a strict I/O contract to ensure the Agent can orchestrate them reliably:
*   **Inputs:** Accept standard CLI arguments: `--input <file_path>` and `--output <json_path>`.
*   **Outputs:** Must write extracted data to the `<json_path>` strictly matching `schema.json`.
*   **Exit Codes:** Exit `0` on success. Exit `1` with a clean `stderr` message if parsing fails (e.g., wrong layout).

#### Boundary Definition
If a script exits with a non-zero code or throws an exception, the Agent *catches* it and handles the routing (either trying another variant script or escalating to the LLM Agent Intervention fallback).

### 3. Core Workflows

#### Workflow 0: The Environment Sentinel (Pre-flight Check)
* **Trigger:** Runs automatically at the start of ANY `oh-sheets` invocation.
* **Role:** Ensures required packages (`docling`, `pdf2image`, `pandas`, `openpyxl`, `Pillow`) and system dependencies (`poppler`) are installed. Halts with an actionable installation command if missing.

#### Workflow A: The Learner (Adaptive Training via Internal RALPH Loop)
* **Trigger:** User completes the Interactive Initialization Flow (providing samples and test set).
* **Note on RALPH Loop:** The Reflect & Fix (RALPH) loop is a *lightweight, internal agentic mechanism* built directly into `oh-sheets!`. It requires zero external tools or installation from the user. It simply uses the LLM to write code, test it, read errors, and rewrite it.
* **Process:**
  1. **Schema Generation:** Agent creates `schema.json` from the provided Target Output Excel.
  2. **Draft:** Agent drafts an initial variant script (e.g., `pdf_variant_a.py`) based on the input type.
  3. **Test:** Agent runs the script on the Test Set Input.
  4. **Data-Level Diff:** A Python diff tool normalizes outputs to strictly compare *data values* against the Test Set Benchmark Output.
  5. **Reflect & Fix (Internal RALPH):** Agent automatically reads the diff report, updates the Python script and `rules.md`, and loops until 100% accurate.

#### Workflow B: The Multi-modal Extractor (Execution with Variant Routing)
* **Trigger:** User provides a new document and specifies the target template.
* **Process:**
  1. **Routing:** Agent inspects the input document (MIME type, basic headers) to select the correct Python script from the target template's `extractors/` directory.
  2. **Deterministic Script Execution:** Executes the script via the strict I/O contract.
  3. **LLM Agent Intervention (Fallback):** If the script fails (exit `1`) or data is missing:
     - *Visual Inputs (PDF/Image/Word):* Convert to images (`pdf2image`), utilize native Vision + `rules.md`.
     - *Data Inputs (Messy Excel):* Bypass Vision. Utilize LLM-driven `pandas` manipulation.

#### Workflow C: The Sanity Checker (Independent LLM Review)
* **Role:** Semantic validation of the intermediate JSON against common sense and `rules.md`.
* **Correction:** Outputs either validated JSON OR an array of contextual errors (e.g., `["Row 4: Expected dollar amount, got 'N/A'."]`), feeding back into Workflow B's fallback loop.

#### Workflow D: The Continuous Learning Trigger
* **Role:** If Workflow B relies heavily on LLM fallback, it prompts the user: "I had to use LLM fallback for this document format. Should I run an internal background RALPH loop to create a new extractor script variant for this specific input layout?"

#### Workflow E: The Non-Destructive Writer
* **Role:** Inject the verified JSON into the blank target Excel using `openpyxl`, preserving all styles, formulas, and macros.

## Phased Implementation Plan

To manage complexity, the development of `oh-sheets!` will be phased:
*   **Phase 1: Core Deterministic Pipeline.** Implement Workflow 0 (Environment), Workflow A (Learner loop without fallback), straightforward Workflow B (Execution of script), and Workflow E (Non-destructive writer).
*   **Phase 2: Semantic Resilience.** Implement Workflow B fallback (Vision & Pandas rescue) and Workflow C (Sanity Checker).
*   **Phase 3: Continuous Evolution.** Implement Workflow D (Continuous Learning / Variant Management) and the full CLI UX management commands (`list`, `delete`).