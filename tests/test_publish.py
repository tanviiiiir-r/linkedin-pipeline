import sys
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

import os

os.environ["DATA_DIR"] = str(repo / "test_data_publish")
os.environ["TOKEN_SECRET"] = "test_secret_for_publish_tests_only_!!!"

import shutil
from datetime import datetime, timezone

from pipeline.drafting import Draft
from pipeline.publishers.linkedin import DirectLinkedInPublisher, DryRunPublisher, get_publisher


def setup_module():
    data_dir = Path(os.environ["DATA_DIR"])
    if data_dir.exists():
        shutil.rmtree(data_dir)


def teardown_module():
    data_dir = Path(os.environ["DATA_DIR"])
    if data_dir.exists():
        shutil.rmtree(data_dir)


def make_draft(approved: bool = True) -> Draft:
    return Draft(
        item_id="abc123",
        pillar="tool_drop",
        title="Test title",
        linkedin_post="Test post",
        newsletter_section="Test newsletter",
        hashtags=["#AI"],
        source_url="https://example.com",
        created_at=datetime.now(timezone.utc).isoformat(),
        approved=approved,
    )


def test_dry_run_publisher_requires_approval():
    pub = DryRunPublisher()
    draft = make_draft(approved=False)
    result = pub.publish(draft)
    assert result["ok"] is False
    assert "not approved" in result["error"]


def test_dry_run_publisher_succeeds_when_approved():
    pub = DryRunPublisher()
    draft = make_draft(approved=True)
    result = pub.publish(draft)
    assert result["ok"] is True
    assert result["dry_run"] is True


def test_direct_publisher_missing_author_urn():
    pub = DirectLinkedInPublisher(access_token="fake-token", author_urn="")
    draft = make_draft(approved=True)
    result = pub.publish(draft)
    assert result["ok"] is False
    assert "author URN" in result["error"]


def test_publisher_factory_falls_back_to_dry_run():
    # No tokens in DB, so factory should return DryRunPublisher
    pub = get_publisher()
    assert isinstance(pub, DryRunPublisher)


if __name__ == "__main__":
    setup_module()
    test_dry_run_publisher_requires_approval()
    test_dry_run_publisher_succeeds_when_approved()
    test_direct_publisher_missing_author_urn()
    test_publisher_factory_falls_back_to_dry_run()
    teardown_module()
    print("publish tests passed")
