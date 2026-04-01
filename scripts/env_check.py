import sys
import subprocess

def check_env():
    required_packages = ['docling', 'pdf2image', 'pandas', 'openpyxl', 'PIL']
    missing = []
    for pkg in required_packages:
        try:
            if pkg == 'PIL':
                __import__('PIL')
            else:
                __import__(pkg)
        except ImportError:
            missing.append(pkg)
            
    if missing:
        print(f"Missing Python packages: {', '.join(missing)}")
        print("Please run: pip install docling pdf2image pandas openpyxl Pillow")
        sys.exit(1)
        
    try:
        subprocess.run(['pdftoppm', '-v'], capture_output=True, check=False)
    except FileNotFoundError:
        print("Missing system dependency: poppler")
        print("Please install poppler (e.g., brew install poppler or apt install poppler-utils)")
        sys.exit(1)
        
    print("Environment check passed.")
    sys.exit(0)

if __name__ == "__main__":
    check_env()
