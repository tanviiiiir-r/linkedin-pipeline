#!/usr/bin/env python3
"""Entry point that ensures repo root is on PYTHONPATH."""
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from pipeline.hermes import main

if __name__ == "__main__":
    try:
        os.chmod(Path(__file__), 0o755)
    except OSError:
        pass
    sys.exit(main())
