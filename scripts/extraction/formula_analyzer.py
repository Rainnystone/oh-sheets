# scripts/extraction/formula_analyzer.py

def extract_formulas_from_schema(schema: dict) -> list:
    """
    Extract formula constraints from schema definition.
    """
    return schema.get("formula_constraints", [])
