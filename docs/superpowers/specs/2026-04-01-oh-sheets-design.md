# oh-sheets! Design Spec

## Overview
`oh-sheets!` is a meta-skill extension for coding agents (Gemini CLI, Claude Code, etc.) designed to automate the extraction of unstructured/semi-structured data (PDFs, Images, Word docs, Messy Excel files) into fixed-format Excel templates. Instead of hardcoding rules, it learns from user-provided examples (Input + Target Excel + Test Set) through an adaptive learning loop, generating specialized extraction scripts and knowledge references for each template.

## Human Usability & CLI UX

The system prioritizes a clean, explicit user experience from initialization to daily use. It is deployed as a standard Agent Skill (e.g., in `~/.gemini/extensions/oh-sheets/`).

### Command Line Interface (CLI)
Users interact with the unified `oh-sheets` entry point using natural language commands or explicit CLI flags (if supported by the agent platform):

*   **Initialization (Automatic):** Handled transparently during the first run (see Workflow 0).
*   **Learning (First-time or New Variant):** 
    `"oh-sheets learn --name 'VendorInvoices' --base base_template.xlsx --sample sample1.pdf"`
    *(The agent prompts for the Test Set if not provided).*
*   **Daily Execution:** 
    `"oh-sheets extract --template 'VendorInvoices' --input new_invoice.pdf --output out.xlsx"`
*   **Management:** 
    `"oh-sheets list"` (Shows all learned templates)
    `"oh-sheets delete 'VendorInvoices'"`

## Architecture & Workflow

The system uses a **Unified Routing Architecture** orchestrated by the overarching Agent. The Agent is the smart orchestrator; the generated Python scripts are "dumb," deterministic executors.

### 1. Template Storage Structure (Local & Private)
For each learned template, the system stores configurations in `~/.oh-sheets/templates/<template-name>/`:
- `schema.json`: A strict schema defining expected fields/data types, mapped 1:1 to target Excel cells.
- `extractors/`: A directory containing variant-specific deterministic scripts (e.g., `variant_hash_abc.py`, `variant_hash_xyz.py`) to handle different layout variations or input MIME types for the *same* template.
- `rules.md`: Agent-generated notes on semantic mappings, common OCR errors, and edge cases.
- `template.xlsx`: The blank target Excel file.

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

#### Workflow A: The Learner (Adaptive Training via RALPH Loop)
* **Trigger:** User provides Training Input, Target Excel, and a Test Set.
* **Process:**
  1. **Schema Generation:** Agent creates `schema.json` from `template.xlsx`.
  2. **Draft:** Agent drafts an initial variant script (e.g., `variant_hash_abc.py`).
  3. **Test:** Agent runs the script on the Test Input.
  4. **Data-Level Diff:** A Python diff tool normalizes outputs (e.g., flat CSV via pandas) to strictly compare *data values*, ignoring styling.
  5. **Reflect & Fix (RALPH):** Agent updates the script and `rules.md` until 100% accurate.

#### Workflow B: The Multi-modal Extractor (Execution with Variant Routing)
* **Trigger:** User provides a new document and specifies the template.
* **Process:**
  1. **Routing:** Agent briefly inspects the document (MIME type, basic headers) to select the correct script from `extractors/`.
  2. **Deterministic Script Execution:** Executes the script via the strict I/O contract.
  3. **LLM Agent Intervention (Fallback):** If the script fails (exit `1`) or data is missing:
     - *Visual Inputs (PDF/Image/Word):* Convert to images (`pdf2image`), utilize native Vision + `rules.md`.
     - *Data Inputs (Messy Excel):* Bypass Vision. Utilize LLM-driven `pandas` manipulation.

#### Workflow C: The Sanity Checker (Independent LLM Review)
* **Role:** Semantic validation of the intermediate JSON against common sense and `rules.md`.
* **Correction:** Outputs either validated JSON OR an array of contextual errors (e.g., `["Row 4: Expected dollar amount, got 'N/A'."]`), feeding back into Workflow B's fallback loop.

#### Workflow D: The Continuous Learning Trigger
* **Role:** If Workflow B relies heavily on LLM fallback, it prompts the user: "I had to use LLM fallback for this document format. Should I run a background RALPH loop to create a new extractor script variant for this layout?"

#### Workflow E: The Non-Destructive Writer
* **Role:** Inject the verified JSON into the target Excel using `openpyxl`, preserving all styles, formulas, and macros.

## Phased Implementation Plan

To manage complexity, the development of `oh-sheets!` will be phased:
*   **Phase 1: Core Deterministic Pipeline.** Implement Workflow 0 (Environment), Workflow A (Learner loop without fallback), straightforward Workflow B (Execution of script), and Workflow E (Non-destructive writer).
*   **Phase 2: Semantic Resilience.** Implement Workflow B fallback (Vision & Pandas rescue) and Workflow C (Sanity Checker).
*   **Phase 3: Continuous Evolution.** Implement Workflow D (Continuous Learning / Variant Management) and the full CLI UX management commands (`list`, `delete`).