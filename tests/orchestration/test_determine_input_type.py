"""Tests for determine_input_type (slice 1).

The orchestrator needs to map a file path's extension to the input_type
tag used by ReferenceBank.retrieve_rules. This is a pure function; tests
are parametrized over extensions. Lives in scripts/core/input_type.py so
both orchestrators share it without drift.
"""
import pytest
from scripts.core.input_type import determine_input_type


@pytest.mark.parametrize("path,expected", [
    # PDF
    ("invoice.pdf", "pdf"),
    ("/abs/path/REPORT.PDF", "pdf"),
    # Excel
    ("data.xlsx", "excel"),
    ("data.xls", "excel"),
    ("data.xlsm", "excel"),
    ("data.xlsb", "excel"),
    ("data.xltx", "excel"),
    ("data.xltm", "excel"),
    # Word
    ("doc.doc", "word"),
    ("doc.docx", "word"),
    # Markdown / text / unknown default to md (text)
    ("notes.md", "md"),
    ("notes.txt", "md"),
    ("no_extension", "md"),
    ("weird.xyz", "md"),
])
def test_determine_input_type(path, expected):
    assert determine_input_type(path) == expected
