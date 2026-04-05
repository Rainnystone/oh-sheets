# oh-sheets! 📄✨

[English](README.md) | [中文](README_zh.md)

**oh-sheets!** is an open-source, meta-skill extension for coding agents (like Gemini CLI, Claude Code) designed to solve the painful task of extracting unstructured or semi-structured data (from PDFs, Images, Word docs, or messy Excel files) into strict, fixed-format Excel templates.

Instead of relying on brittle regex rules or hardcoded scripts, `oh-sheets! v2` introduces a dynamic **Semantic Reference Bank**. It learns from user-provided examples through an adaptive **RALPH (Reflect & Fix)** loop, autonomously building a structured knowledge graph of anchors, rules, and success patterns to guide LLM-first data extraction.

## 🚀 What it is & Why it exists

Data extraction into Excel often involves brittle scripts that break when source layouts change. `oh-sheets!` acts as the orchestrator:
- **Zero-Config Learning:** Show it a sample input and your desired filled Excel template. It learns the semantic structure and creates its own extraction rules.
- **LLM-First Execution:** Uses LLMs with a rich context payload (few-shot rules, spatial anchors, formula constraints) to semantically extract data, making it highly resilient to layout changes.
- **Non-Destructive:** Uses `openpyxl` to inject data without destroying your template's styling, formulas, or macros.
- **Rule Evolution:** The system continuously learns. Successful extractions boost rule confidence, failed ones penalize them, and unused rules decay over time.

## 🛠 Prerequisites & Environment

Before running `oh-sheets!`, ensure your environment has the necessary tools. The built-in `Environment Sentinel` will automatically check for these upon invocation.

- **Python 3.x**
- **Python Packages:** `docling`, `pdf2image`, `pandas`, `openpyxl`, `Pillow`, `google-genai` (or equivalent SDK)
- **System Dependencies:** `poppler` (Required for PDF-to-image conversion)
  - macOS: `brew install poppler`
  - Ubuntu/Debian: `sudo apt-get install poppler-utils`

## 📦 Installation

Since `oh-sheets!` is an AI agent meta-skill extension, you install it by cloning this repository into your agent's extension/skills directory.

### For Gemini CLI
```bash
# Clone the repository into your extensions directory
git clone https://github.com/Rainnystone/oh-sheets.git ~/.gemini/extensions/oh-sheets

# Install required Python dependencies
pip install docling pdf2image pandas openpyxl Pillow google-genai
```

### For Claude Code
```bash
# Clone into your global or project-specific skills directory
git clone https://github.com/Rainnystone/oh-sheets.git ~/.claude/skills/oh-sheets

# Install required Python dependencies
pip install docling pdf2image pandas openpyxl Pillow google-genai
```

## 📖 How to Use

Because `oh-sheets!` is a meta-skill, you do not run a traditional CLI binary. Instead, you **talk to your AI agent** (Gemini CLI, Claude Code) and ask it to invoke the skill.

### 1. Interactive Learning Flow
To teach `oh-sheets!` a new template, simply tell your agent:
> "Use the oh-sheets skill to learn a new template"
*(Or conceptually trigger `oh-sheets learn`)*

The agent will interactively prompt you for:
1. **Template Name:** (e.g., `ProjectTemplate`)
2. **Blank Base Template:** The empty target Excel file.
3. **Sample Input & Target Output:** A sample PDF/Image and the perfectly filled Excel file based on that input.
4. **Test Set:** A secondary set of files to validate the learned rules.

The Agent will run its internal **RALPH Loop**, identifying spatial anchors, drafting extraction rules, testing them, and refining its knowledge graph until it achieves 100% data match against your Test Set.

`schema.json` acts as the contract, defining field types and automatically extracting formula constraints (e.g., protecting `=SUM(A1:A5)`) so the LLM never overwrites calculated cells.

### 2. Daily Execution
Once trained, ask your agent to extract data for your daily tasks:
> "Use oh-sheets to extract data from source_file.pdf into the ProjectTemplate"
*(Or conceptually trigger `oh-sheets extract --template 'ProjectTemplate' --input source_file.pdf --output out.xlsx`)*

### 3. Management
You can also ask your agent to manage your templates:
> "List all learned oh-sheets templates"  
> "Delete the ProjectTemplate from oh-sheets"

## 🧠 Deep Dive: The Semantic Reference Bank (v2)

Dealing with diverse PDF layouts mapped to the same Excel template? Here's how `oh-sheets! v2` handles the chaos:

1. **Structured Memory:** Instead of a simple `rules.md` file, knowledge is split into explicit components under `~/.oh-sheets/templates/<name>/reference_bank/`:
   - `anchors.json`: Spatial and visual locators (e.g., "The vendor name is always below the string 'Vendor:'").
   - `rules.jsonl`: Structured predicate rules mapping conditions to extraction strategies.
   - `success_patterns.jsonl`: MD5 signatures of known successful document layouts to fast-track processing.
   - `knowledge_graph.json`: Tracks the relationships and dependencies between different rules and anchors.
2. **Dynamic Evolution:** When `oh-sheets!` successfully extracts a document, the `learning_orchestrator` boosts the `confidence` score of the rules used. If validation fails (e.g., missing a required field), the rules are penalized. Rules that drop below a confidence threshold (0.3) are automatically archived, ensuring the system doesn't get bloated with outdated logic.
3. **Validation & Feedback:** The orchestrator strictly validates the LLM's output against the `schema.json` contract before writing to Excel. If data is missing or malformed, the failure is logged to `execution_log.jsonl` and fed back into the RALPH loop for immediate reflection and repair.

## 🔄 RALPH Loop v2: 5-Phase Learning Cycle

The learning orchestrator implements a complete **RALPH (Reflect & Fix)** loop with 5 phases:

| Phase | Description |
|-------|-------------|
| **1. ANALYZE** | LLM analyzes sample input + target Excel → generates anchors, schema, identifies formulas |
| **2. DRAFT** | Creates initial rules based on anchors, builds knowledge graph |
| **3. TEST** | Executes extraction using LLM + Reference Bank, validates against schema |
| **4. COMMIT** | On success: records success_pattern, boosts rule confidence |
| **5. REFLECT** | On failure: analyzes error, generates/updates rules, retries (max 5 attempts) |

### Degradation Strategy

When extraction fails, the system automatically degrades through 4 levels:

```
Level 1: LLM + Reference Bank (full semantic extraction)
    ↓ failed
Level 2: LLM + Anchors only (reduced rule dependency)
    ↓ failed
Level 3: Deterministic extractors (if available in extractors/)
    ↓ failed
Level 4: Request user intervention
```

### Formula Protection

The system automatically:
- Analyzes Excel templates to identify formula cells (`=SUM()`, `=IF()`, etc.)
- Protects formula cells from being overwritten during extraction
- Uses formula dependencies for validation

## 📁 Directory Structure

```
oh-sheets!/
├── SKILL.md                          # Skill definition for AI agents
├── README.md                         # English documentation
├── README_zh.md                      # Chinese documentation
│
├── scripts/
│   ├── core/                         # Core modules
│   │   ├── reference_bank.py         # Reference Bank CRUD operations
│   │   ├── rule_evolution.py         # Rule confidence update & decay
│   │   ├── prompt_builder.py         # LLM prompt construction
│   │   └── signature_matcher.py      # MD5 signature & pattern matching
│   │
│   ├── extraction/                   # Extraction modules
│   │   ├── llm_extractor.py          # LLM extraction (google-genai)
│   │   └── formula_analyzer.py       # Excel formula analysis
│   │
│   ├── io/                           # Input/Output
│   │   ├── excel_writer.py           # Non-destructive Excel writing
│   │   └── data_diff.py              # Data comparison & validation
│   │
│   ├── memory/                       # Memory system
│   │   └── local_few_shot_memory.py  # Few-shot example storage
│   │
│   ├── orchestration/                # Orchestration layer
│   │   ├── execution_orchestrator.py # Main extraction flow
│   │   └── learning_orchestrator.py  # RALPH Loop implementation
│   │
│   └── utils/                        # Utilities
│       ├── template_layout_signature.py
│       └── env_check.py
│
├── references/
│   ├── prompt_templates.md           # Prompt templates
│   └── config_schema.md              # Configuration schema
│
├── docs/
│   └── superpowers/specs/            # Design specifications
│
├── tests/                            # Test suite (mirrors scripts/)
│   ├── core/
│   ├── extraction/
│   ├── io/
│   ├── memory/
│   ├── orchestration/
│   └── utils/
│
└── examples/                         # Example templates
```

### Template Directory Structure

Each learned template is stored under `~/.oh-sheets/templates/<name>/`:

```
~/.oh-sheets/templates/<template-name>/
├── template.xlsx                    # Target Excel template
├── schema.json                      # Field mapping contract
├── reference_bank/                  # Semantic Reference Bank
│   ├── anchors.json                 # Spatial/visual locators
│   ├── rules.jsonl                  # Extraction rules
│   ├── success_patterns.jsonl       # Known successful layouts
│   └── knowledge_graph.json         # Rule relationships
├── extractors/                      # Optional deterministic scripts
│   └── *.py
└── memory/                          # Execution memory
    ├── execution_log.jsonl          # Execution history
    ├── failure_clusters.json        # Failure patterns
    └── summary_rules.json           # Rule summaries
```

## 🔧 Configuration

### schema.json Structure

```json
{
  "meta": {
    "signature": "abc123...",
    "version": "2.0"
  },
  "fields": {
    "Field_A": {"cell": "B2", "type": "string", "required": true},
    "Field_B": {"cell": "B3", "type": "number"}
  },
  "formula_constraints": [
    {"cell": "D5", "formula": "=SUM(D2:D4)", "depends_on": ["D2", "D3", "D4"]}
  ]
}
```

### Rule Structure (rules.jsonl)

```jsonl
{"id":"R001","when":{"input_type":"pdf"},"condition":{"field":"vendor_name"},"then":{"action":"extract_after_anchor"},"confidence":0.92,"support":5}
```

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.
