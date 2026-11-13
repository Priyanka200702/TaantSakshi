"""
conftest.py — repo root
Makes `import engine` work when pytest is run from the repo root.
"""
import sys
from pathlib import Path

# Ensure headless Agg backend for matplotlib before any imports
import matplotlib
matplotlib.use("Agg")

# Insert the repo root into sys.path so `import engine` resolves correctly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

