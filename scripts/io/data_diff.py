import argparse
import sys
import pandas as pd

def compare_excel(gen_path, bench_path):
    try:
        df_gen = pd.read_excel(gen_path)
        df_bench = pd.read_excel(bench_path)
        
        # Normalize strings
        df_gen = df_gen.map(lambda x: str(x).strip() if isinstance(x, str) else x)
        df_bench = df_bench.map(lambda x: str(x).strip() if isinstance(x, str) else x)
        
        # Round floats
        df_gen = df_gen.round(2)
        df_bench = df_bench.round(2)
        
        # Align numeric types to avoid false mismatches due to inferred int vs float types
        for col in df_gen.select_dtypes(include='number').columns:
            df_gen[col] = df_gen[col].astype('float64')
        for col in df_bench.select_dtypes(include='number').columns:
            df_bench[col] = df_bench[col].astype('float64')

        if df_gen.equals(df_bench):
            print("100% accurate")
            sys.exit(0)
        else:
            print("Mismatch Error: Data does not match exactly.")
            sys.exit(1)
    except Exception as e:
        print(f"Error during diff: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--generated', required=True)
    parser.add_argument('--benchmark', required=True)
    args = parser.parse_args()
    compare_excel(args.generated, args.benchmark)
