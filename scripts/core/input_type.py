"""Map a file path to the input_type tag used by ReferenceBank.retrieve_rules.

Pure module — no I/O, no state. Shared by execution_orchestrator (which
retrieves rules at extraction time) and learning_orchestrator (which tags
rules at learning time) so the two never drift.
"""

from pathlib import Path


# "auto" (legacy wildcard) is NOT produced here — new rules always carry a
# real type. Unknown extensions default to "md" (treated as text).
_INPUT_TYPE_BY_EXTENSION = {
    "pdf": "pdf",
    "xls": "excel", "xlsx": "excel", "xlsm": "excel", "xlsb": "excel",
    "xltx": "excel", "xltm": "excel",
    "doc": "word", "docx": "word",
    "md": "md", "txt": "md",
}


def determine_input_type(file_path: str) -> str:
    """Map a file path's extension to the input_type tag for retrieve_rules.

    Unknown extensions default to "md" (treated as text). Case-insensitive.
    """
    ext = Path(file_path).suffix.lstrip(".").lower()
    return _INPUT_TYPE_BY_EXTENSION.get(ext, "md")
