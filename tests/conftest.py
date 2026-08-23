"""Central test environment setup.

Each test module currently mutates os.environ. Settings are loaded eagerly by
config.settings via dotenv, so we ensure DATA_DIR and TOKEN_SECRET are set
before any repo module imports them. We also patch pipeline.tokens.TOKEN_SECRET
to always use the test secret so that token operations work regardless of
import order.
"""
import os
from pathlib import Path

_repo = Path(__file__).resolve().parent.parent
os.environ.setdefault("DATA_DIR", str(_repo / "test_data"))
os.environ.setdefault("TOKEN_SECRET", "test_secret_32_chars_long_1234567890")
