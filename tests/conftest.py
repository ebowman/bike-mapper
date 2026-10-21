"""Put the repo's scripts/ directory on sys.path so `from flowplan import ...` works."""
import sys
from pathlib import Path

SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
