# oh-sheets! Design Spec

## Overview
`oh-sheets!` is a meta-skill extension for coding agents (Gemini CLI, Claude Code, etc.) designed to automate the extraction of unstructured/semi-structured data (PDFs, Images, Word docs, Messy Excel files) into fixed-format Excel templates. Instead of hardcoding rules, it learns from user-provided examples (Input + Target Excel + Test Set) through an adaptive learning loop, generating specialized extraction scripts and knowledge references for each template.

## Architecture & Workflow

The system uses a **Unified Routing Architecture**. There is one main `oh-sheets` entry point that dynamically loads template-specific configurations and scripts from a local storage directory (e.g., `~/.oh-sheets/templates/<template-name>/`).

### 1. Template Storage Structure (Local & Private)
For each learned template, the system stores:
- `schema.json`: A strict schema defining the expected fields and data types, mapped 1:1 to the target Excel cells. Generated during the initial learning phase.
- `extractors/`: A directory containing variant-specific deterministic scripts (e.g., `extractor_pdf.py`, `extractor_excel.py`) to handle different input MIME types for the same template.
- `rules.md`: Agent-generated notes on semantic mappings, common OCR errors, and edge cases.
- `template.xlsx`: The blank target Excel file used as the base.

### 2. Core Workflows

#### Workflow 0: The Environment Sentinel (Pre-flight Check)
* **Trigger:** Runs automatically at the start of ANY `oh-sheets` invocation (learning or execution).
* **Role:** Ensures the host environment has all necessary system and Python dependencies to execute the deterministic scripts and fallback mechanisms.
* **Process:**
  1. Checks for required Python packages: 
     - `docling` (advanced document parsing)
     - `pdf2image` (PDF to image conversion for vision fallback)
     - `pandas` (data manipulation and messy Excel handling)
     - `openpyxl` (non-destructive Excel writing - preserves styles/macros)
     - `Pillow` (image processing)
  2. Checks for required system dependencies: 
     - `poppler` (required by `pdf2image` for PDF rendering).
  3. **Action:** If any dependency is missing, the execution halts immediately. The agent outputs a clear, OS-specific error message and an actionable installation command (e.g., `pip install docling pdf2image pandas openpyxl Pillow && brew install poppler`).

#### Workflow A: The Learner (Adaptive Training via RALPH Loop)
* **Trigger:** User provides Training Input (knowing its MIME type), Target Excel, and a Test Set.
* **Process:**
  1. **Schema Generation:** Agent analyzes `template.xlsx` and creates a strict `schema.json`.
  2. **Draft:** Agent drafts an initial variant-specific script (e.g., `extractor_pdf.py`).
  3. **Test:** Agent runs the script on the Test Input.
  4. **Data-Level Diff:** A Python diff tool converts both the generated output and the Benchmark Excel into a normalized data format (e.g., flat CSV or JSON via pandas) to compare strictly *data values*, ignoring binary/styling differences.
  5. **Reflect & Fix (RALPH):** Agent analyzes the data diff report, updates the script and `rules.md`, and loops until 100% accurate.

#### Workflow B: The Multi-modal Extractor (Execution with Forking)
* **Trigger:** User provides a new document and specifies the target template.
* **Process:**
  1. **Load:** Agent retrieves `schema.json`, `rules.md`, and the appropriate `extractor_<type>.py` based on the input file type.
  2. **Deterministic Script Execution:** Executes the Python script to produce intermediate JSON data matching `schema.json`.
  3. **LLM Agent Intervention (Fallback):** If the deterministic script fails or data is missing:
     - *Visual Inputs (PDF/Image/Word):* Convert to images (`pdf2image`), utilize native Vision combined with `rules.md` to visually locate and extract data.
     - *Data Inputs (Messy Excel):* Bypass Vision. Utilize LLM-driven DataFrame manipulation (`pandas`) to semantically map messy rows/cols to the target schema.

#### Workflow C: The Sanity Checker (Independent LLM Review)
* **Role:** An explicit LLM prompt step for semantic validation of the intermediate JSON before final writing.
* **Process:** Takes the extracted JSON, `schema.json`, and `rules.md` as context. Evaluates data against common sense (e.g., "Is '12/31/2023' a valid company name?").
* **Correction:** Outputs either the validated JSON OR an array of contextual errors (e.g., `["Row 4: Expected a dollar amount, got 'N/A'. Check rules.md."]`). These errors feed directly back into Workflow B's LLM Agent Intervention loop for targeted re-extraction.

#### Workflow D: The Continuous Learning Trigger
* **Role:** If Workflow B relies heavily on LLM Agent Intervention to pass Workflow C, it flags the document as a "new variant".
* **Process:** After serving the user, the agent prompts: "I had to use LLM fallback for this document format. Should I run a background RALPH loop to update the specific extractor script for this new variant?"

#### Workflow E: The Non-Destructive Writer
* **Role:** Inject the verified JSON into the target Excel.
* **Process:** Uses libraries like `openpyxl` strictly to populate cell values while preserving 100% of the base template's styling, formulas, and macros.