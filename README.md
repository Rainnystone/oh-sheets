# oh-sheets! 📄✨

[English](README.md) | [中文](README_zh.md)

**oh-sheets!** is an open-source, meta-skill extension for coding agents (like Gemini CLI, Claude Code) designed to solve the painful task of extracting unstructured or semi-structured data (from PDFs, Images, Word docs, or messy Excel files) into strict, fixed-format Excel templates.

Instead of hardcoding brittle regex rules, `oh-sheets!` learns from user-provided examples through an adaptive **RALPH (Reflect & Fix)** loop. It autonomously generates specialized, deterministic Python extraction scripts and knowledge references for each of your specific target templates.

## 🚀 What it is & Why it exists

Data extraction into Excel often involves brittle scripts that break when source layouts change. `oh-sheets!` acts as the orchestrator:
- **Zero-Config Learning:** Show it a sample input and your desired filled Excel template. It writes its own extraction code.
- **Non-Destructive:** Uses `openpyxl` to inject data without destroying your template's styling, formulas, or macros.
- **Vision Fallback & Sanity Checking:** If a deterministic script fails due to an unexpected layout change, it gracefully falls back to native Vision capabilities and semantic reasoning to ensure data integrity.

## 🛠 Prerequisites & Environment

Before running `oh-sheets!`, ensure your environment has the necessary tools. The built-in `Environment Sentinel` will automatically check for these upon invocation.

- **Python 3.x**
- **Python Packages:** `docling`, `pdf2image`, `pandas`, `openpyxl`, `Pillow`
- **System Dependencies:** `poppler` (Required for PDF-to-image conversion)
  - macOS: `brew install poppler`
  - Ubuntu/Debian: `sudo apt-get install poppler-utils`

## 📖 How to Use

The workflow is divided into two phases: **Learning** and **Daily Execution**.

### 1. Interactive Learning Flow
To teach `oh-sheets!` a new template, simply run:
```bash
oh-sheets learn
```
The agent will interactively prompt you for:
1. **Template Name:** (e.g., `ProjectTemplate`)
2. **Blank Base Template:** The empty target Excel file.
3. **Sample Input & Target Output:** A sample PDF/Image and the perfectly filled Excel file based on that input.
4. **Test Set:** A secondary set of files to validate the generated code.

The Agent will run its internal **RALPH Loop**, writing, testing, and refining a Python extractor script until it achieves 100% data match against your Test Set.

`schema.json` can now record row/column relations between fields using `relative_to`, `row_offset`, and `col_offset` so future template versions can be compared and migrated by structure rather than raw cell positions alone.

### 2. Daily Execution
Once trained, use the unified routing command for your daily tasks:
```bash
oh-sheets extract --template 'ProjectTemplate' --input source_file.pdf --output out.xlsx
```

### 3. Management
List all learned templates:
```bash
oh-sheets list
```
Delete a template:
```bash
oh-sheets delete 'ProjectTemplate'
```

## 🧠 Deep Dive: Handling Diverse Excel Needs

Dealing with five different PDF layouts mapped to the same Excel template? Here's how `oh-sheets!` handles the chaos:

1. **Variant Isolation:** Scripts are generated and bound to an *input type and layout variant*. If you feed the system 3 different PDF formats for the same template, it generates `pdf_variant_1.py`, `pdf_variant_2.py`, etc., cleanly organizing them in `~/.oh-sheets/templates/<name>/extractors/`.
2. **Schema & Global Rules:** For every target template, a strict `schema.json` acts as the mapping contract. A `rules.md` file holds global logic (e.g., "The total must always be parsed as a float").
3. **Multi-modal Fallback:** If a layout changes and the deterministic Python script throws an error (`Exit 1`), the Agent catches it. It sequentially tests other known variants. If all fail, it seamlessly converts the document to images and uses Native LLM Vision to extract the data based on your `rules.md`.
4. **Continuous Learning:** If the Vision fallback was used, the Agent will prompt: *"I had to use LLM fallback. Should I learn this new layout in the background?"*
