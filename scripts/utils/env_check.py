import sys
import subprocess

# "poppler" is added to the missing list (returned by check_env) when the
# system dependency is absent; python package names appear verbatim.
_POPPLER = "poppler"


def check_env():
    """Return the list of missing dependencies (empty = environment ok).

    Library function — does not call sys.exit. Only the __main__ block
    prints the hints and translates a non-empty list into exit code 1.
    The list contains python package names that failed to import, plus
    "poppler" if the pdftoppm system binary is not on PATH.
    """
    required_packages = ['docling', 'pdf2image', 'pandas', 'openpyxl', 'PIL']
    missing = []
    for pkg in required_packages:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    try:
        subprocess.run(['pdftoppm', '-v'], capture_output=True, check=False)
    except FileNotFoundError:
        missing.append(_POPPLER)

    return missing

if __name__ == "__main__":
    missing = check_env()
    if not missing:
        print("Environment check passed.")
        sys.exit(0)

    packages = [m for m in missing if m != _POPPLER]
    if packages:
        print(f"Missing Python packages: {', '.join(packages)}")
        print("Please run: pip install docling pdf2image pandas openpyxl Pillow")
    if _POPPLER in missing:
        print("Missing system dependency: poppler")
        print("Please install poppler (e.g. brew install poppler or apt install poppler-utils)")
    sys.exit(1)
