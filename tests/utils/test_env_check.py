"""Tests for utils/env_check — check_env is a library function.

Candidate 04 (roadmap slice 5): check_env called sys.exit inside its
body, making it un-testable as a library. Now it returns the list of
missing deps (empty = ok); only __main__ exits.
"""
import builtins
import subprocess


_TARGET_PACKAGES = ("docling", "pdf2image", "pandas", "openpyxl", "PIL")


def test_check_env_returns_empty_list_when_all_present(monkeypatch):
    """When every required package imports and poppler is on PATH,
    check_env returns an empty list. It does NOT call sys.exit."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in _TARGET_PACKAGES:
            return object()  # present
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: object())

    from scripts.utils.env_check import check_env
    result = check_env()
    assert isinstance(result, list)
    assert result == []


def test_check_env_returns_missing_list_not_sys_exit(monkeypatch):
    """When deps are missing, check_env returns a non-empty list of
    missing identifiers — it does not sys.exit(1)."""
    real_import = builtins.__import__
    missing = {"docling", "pdf2image"}

    def fake_import(name, *args, **kwargs):
        if name in missing:
            raise ImportError(f"simulated missing: {name}")
        if name in _TARGET_PACKAGES:
            return object()  # present
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: object())

    from scripts.utils.env_check import check_env
    result = check_env()
    assert isinstance(result, list)
    assert len(result) > 0
    # The missing python packages show up by name.
    assert "docling" in result
    assert "pdf2image" in result
