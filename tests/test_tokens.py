import os
import shutil
import sys
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

# Must set DATA_DIR and TOKEN_SECRET before importing settings/tokens
os.environ["DATA_DIR"] = str(repo / "test_data_tokens")
os.environ["TOKEN_SECRET"] = "a_very_secret_key_for_testing_only_123"

from pipeline.tokens import clear_tokens, has_tokens, load_tokens, save_tokens


def setup_module():
    data_dir = Path(os.environ["DATA_DIR"])
    if data_dir.exists():
        shutil.rmtree(data_dir)


def teardown_module():
    data_dir = Path(os.environ["DATA_DIR"])
    if data_dir.exists():
        shutil.rmtree(data_dir)


def test_save_and_load_tokens():
    save_tokens("access-xyz", "refresh-abc", 3600, "urn:li:person:TEST")
    loaded = load_tokens()
    assert loaded is not None
    assert loaded["access_token"] == "access-xyz"
    assert loaded["refresh_token"] == "refresh-abc"
    assert loaded["author_urn"] == "urn:li:person:TEST"
    assert has_tokens()


def test_clear_tokens():
    save_tokens("access", "refresh", 0, "")
    clear_tokens()
    assert not has_tokens()
    assert load_tokens() is None


if __name__ == "__main__":
    setup_module()
    test_save_and_load_tokens()
    test_clear_tokens()
    teardown_module()
    print("token tests passed")
