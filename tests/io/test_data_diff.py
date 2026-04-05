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
