import os
import pandas as pd
import subprocess

def test_data_diff():
    # Setup mock data
    df1 = pd.DataFrame({'A': [1.001, 2.0], 'B': [' test ', 'string']})
    df2 = pd.DataFrame({'A': [1.00, 2.0], 'B': ['test', 'string']})
    df1.to_excel('test_gen.xlsx', index=False)
    df2.to_excel('test_bench.xlsx', index=False)

    result = subprocess.run(['python', 'scripts/io/data_diff.py', '--generated', 'test_gen.xlsx', '--benchmark', 'test_bench.xlsx'], capture_output=True, text=True)

    os.remove('test_gen.xlsx')
    os.remove('test_bench.xlsx')

    assert result.returncode == 0
    assert "100% accurate" in result.stdout


def test_compare_excel_returns_bool_match(tmp_path):
    """compare_excel is a library function returning bool, not sys.exit.

    Candidate 04 (roadmap slice 5): the old code called sys.exit(0) on
    match and sys.exit(1) on mismatch, forcing callers into subprocess
    shells. Now it returns True on match / False on mismatch; only
    __main__ exits.
    """
    df = pd.DataFrame({'A': [1.0, 2.0], 'B': ['x', 'y']})
    gen = tmp_path / "gen.xlsx"
    bench = tmp_path / "bench.xlsx"
    df.to_excel(gen, index=False)
    df.to_excel(bench, index=False)

    from scripts.io.data_diff import compare_excel
    assert compare_excel(str(gen), str(bench)) is True


def test_compare_excel_returns_bool_mismatch(tmp_path):
    """compare_excel returns False on mismatch (not sys.exit(1))."""
    df1 = pd.DataFrame({'A': [1.0, 2.0]})
    df2 = pd.DataFrame({'A': [9.0, 2.0]})
    gen = tmp_path / "gen.xlsx"
    bench = tmp_path / "bench.xlsx"
    df1.to_excel(gen, index=False)
    df2.to_excel(bench, index=False)

    from scripts.io.data_diff import compare_excel
    assert compare_excel(str(gen), str(bench)) is False
