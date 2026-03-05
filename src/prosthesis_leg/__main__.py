"""Entry point: python -m prosthesis_leg  or  prosthesis-wizard"""
import subprocess
import sys
from pathlib import Path


def main():
    wizard = Path(__file__).parent.parent.parent / "scripts" / "00_wizard.py"
    raise SystemExit(subprocess.run([sys.executable, str(wizard)]).returncode)


if __name__ == "__main__":
    main()
