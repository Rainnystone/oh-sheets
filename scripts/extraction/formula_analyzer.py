# scripts/extraction/formula_analyzer.py
import re
import openpyxl

def extract_formulas_from_schema(schema: dict) -> list:
    """
    Extract formula constraints from schema definition.
    """
    return schema.get("formula_constraints", [])

def analyze_workbook_formulas(template_path: str) -> list:
    """
    Extract formulas from an Excel workbook.

    Returns a list of formula constraints with cell, formula, depends_on, and description.
    """
    wb = openpyxl.load_workbook(template_path, data_only=False)
    formulas = []

    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str) and cell.value.startswith('='):
                    formulas.append({
                        "cell": cell.coordinate,
                        "formula": cell.value,
                        "depends_on": extract_formula_dependencies(cell.value),
                        "description": ""
                    })

    return formulas

def extract_formula_dependencies(formula: str) -> list:
    """
    Extract cell references from a formula string.

    Handles single cell references (A1), ranges (D2:D4), and complex formulas.
    """
    # Remove the leading '=' if present
    if formula.startswith('='):
        formula = formula[1:]

    # Find all cell references (e.g., A1, $B$2, D2, etc.)
    # Pattern matches: optional $ prefix, column letters, optional $, row number
    cell_pattern = r'\$?[A-Z]+\$?\d+'
    refs = re.findall(cell_pattern, formula)

    # Remove $ signs from absolute references
    refs = [ref.replace('$', '') for ref in refs]

    return refs
