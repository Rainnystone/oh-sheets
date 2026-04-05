# tests/extraction/test_formula_analyzer.py
from scripts.extraction.formula_analyzer import extract_formulas_from_schema

def test_extract_formulas_from_schema():
    schema = {
        "formula_constraints": [
            {"cell": "D5", "formula": "=SUM(D2:D4)"}
        ]
    }
    formulas = extract_formulas_from_schema(schema)
    assert len(formulas) == 1
    assert formulas[0]["cell"] == "D5"
