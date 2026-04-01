import argparse
import sys
import json
import openpyxl

def write_excel(template_path, data_path, schema_path, output_path):
    try:
        wb = openpyxl.load_workbook(template_path)
        ws = wb.active
        
        with open(data_path, 'r') as f:
            data = json.load(f)
            
        with open(schema_path, 'r') as f:
            schema = json.load(f)
            
        for cell_ref, value in data.items():
            if cell_ref in schema:
                ws[cell_ref] = value
                
        wb.save(output_path)
        sys.exit(0)
    except Exception as e:
        print(f"Error writing excel: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--template', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--schema', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    write_excel(args.template, args.data, args.schema, args.output)
