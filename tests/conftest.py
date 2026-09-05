import sys
from pathlib import Path

# Make `fake_backend` importable from every test module.
sys.path.insert(0, str(Path(__file__).parent))
