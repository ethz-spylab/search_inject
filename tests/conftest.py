"""Make `import search_inject` work when running the tests in-place (without an install).

The repo root *is* the package directory (`package-dir = {"search_inject" = "."}`), so the
importable location is the directory that *contains* the repo. After `pip install -e .`
this path insert is a harmless no-op.
"""
import sys
from pathlib import Path

# parents[0]=tests, [1]=search_inject (repo root/package), [2]=dir containing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
