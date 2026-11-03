import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from blastradius.archive import Archive
from blastradius.cli import _backfill_empty_topics
from blastradius.models import Topic


def make_story(title: str, url: str, rank: int = 1, coverage: list | None = None) -> dict:
    return {
        # Unique per story, as real ids are: the top-up never carries one id twice.
        "id": "id_" + url,
        "title": title,
        "url": url,
        "rank": rank,
        "summary": "Summary of " + title,
        "sources": ["Src"],
        "labels": ["tag"],
        "coverage": coverage or [{"title": title, "url": url, "source": "Src"}],
    }


class BackfillTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp_dir)
        self.archive = Archive(self.temp_dir)

    def test_tops_up_topics_to_meet_min_items_quota(self):
        topic_a = Topic(id="a", name="Topic A", min_items=2)
        topic_b = Topic(id="b", name="Topic B", min_items=2)

        # Yesterday's archive
        self.archive.save_day(
            "2026-10-31",
            {
                "a": [
                    make_story("Old A1", "https://example.com/a1"),
                    make_story("Old A2", "https://example.com/a2"),
                ],
                "b": [
                    make_story("Old B1", "https://example.com/b1"),
                ],
            },
            datetime.now(UTC),
        )

        # Today's board: Topic A has 1 fresh story, Topic B has 0
        board = {
            "a": [make_story("Fresh A", "https://example.com/fresh-a")],
            "b": [],
        }

        _backfill_empty_topics(board, [topic_a, topic_b], self.archive, "2026-11-01")

        # Topic A had 1 fresh story, min_items=2 -> topped up with Old A1 to reach 2
        self.assertEqual(len(board["a"]), 2)
        self.assertFalse(board["a"][0].get("is_carryover", False))
        self.assertEqual(board["a"][0]["title"], "Fresh A")
        self.assertEqual(board["a"][0]["rank"], 1)
        self.assertTrue(board["a"][1]["is_carryover"])
        self.assertEqual(board["a"][1]["title"], "Old A1")
        self.assertEqual(board["a"][1]["rank"], 2)

        # Topic B was empty, should be backfilled with Old B1
        self.assertEqual(len(board["b"]), 1)
        self.assertTrue(board["b"][0]["is_carryover"])
        self.assertEqual(board["b"][0]["title"], "Old B1")
        self.assertEqual(board["b"][0]["rank"], 1)

    def test_skips_stories_overlapping_with_today(self):
        topic_a = Topic(id="a", name="Topic A", min_items=2)
        topic_b = Topic(id="b", name="Topic B", min_items=2)

        # Yesterday has Old B1 which shares a coverage URL with Today's fresh A story
        shared_url = "https://example.com/shared-article"
        self.archive.save_day(
            "2026-10-31",
            {
                "b": [
                    make_story("Old B1", shared_url),
                    make_story("Old B2", "https://example.com/unique-b2"),
                ],
            },
            datetime.now(UTC),
        )

        board = {
            "a": [make_story("Fresh A", "https://example.com/fresh-a", coverage=[{"url": shared_url}])],
            "b": [],
        }

        _backfill_empty_topics(board, [topic_a, topic_b], self.archive, "2026-11-01")

        # B should have skipped B1 due to URL collision and selected B2
        self.assertEqual(len(board["b"]), 1)
        self.assertEqual(board["b"][0]["title"], "Old B2")
        self.assertTrue(board["b"][0]["is_carryover"])

    def test_accumulates_across_multiple_days(self):
        topic = Topic(id="tech", name="Tech", min_items=2)

        # 2 days ago has 1 story
        self.archive.save_day(
            "2026-10-30",
            {"tech": [make_story("Story 10-30", "https://example.com/tech-10-30")]},
            datetime.now(UTC),
        )
        # Yesterday has 1 story
        self.archive.save_day(
            "2026-10-31",
            {"tech": [make_story("Story 10-31", "https://example.com/tech-10-31")]},
            datetime.now(UTC),
        )

        board = {"tech": []}
        _backfill_empty_topics(board, [topic], self.archive, "2026-11-01")

        self.assertEqual(len(board["tech"]), 2)
        self.assertEqual(board["tech"][0]["title"], "Story 10-31")
        self.assertEqual(board["tech"][0]["rank"], 1)
        self.assertEqual(board["tech"][1]["title"], "Story 10-30")
        self.assertEqual(board["tech"][1]["rank"], 2)

    def test_skips_a_story_today_already_carries_in_another_column(self):
        """The 2026-11-03 case: today's update joined yesterday's cluster, in
        another column, under another outlet's URL."""
        threats = Topic(id="threats", name="Active Threats", min_items=2)
        vulns = Topic(id="vulns", name="Vulnerabilities", min_items=1)
        btcpay = make_story("BTCPay Server Urges Operators to Shut Down", "https://cybersecuritynews.com/btcpay")
        btcpay.update(id="a46e5b2bfea3", cluster="a46e5b2bfea3")
        other = make_story("Unrelated ransomware campaign", "https://example.com/ransom")
        other.update(id="b1", cluster="b1")
        self.archive.save_day("2026-11-02", {"threats": [btcpay, other]}, datetime.now(UTC))

        update = make_story("BTCPay Server tells operators to update", "https://bleepingcomputer.com/btcpay")
        update.update(id="0f68334e8489", cluster="a46e5b2bfea3", supersedes="a46e5b2bfea3")
        board = {"threats": [], "vulns": [update]}

        _backfill_empty_topics(board, [threats, vulns], self.archive, "2026-11-03")

        self.assertEqual([s["id"] for s in board["threats"]], ["b1"])

    def test_skips_a_story_superseded_today_even_without_a_cluster(self):
        topic = Topic(id="threats", name="Active Threats", min_items=1)
        old = make_story("Old story", "https://example.com/old")
        old["id"] = "old1"
        self.archive.save_day("2026-11-02", {"threats": [old]}, datetime.now(UTC))
        board = {"threats": [], "vulns": [{**make_story("New", "https://example.com/new"), "supersedes": "old1"}]}

        _backfill_empty_topics(board, [topic], self.archive, "2026-11-03")

        self.assertEqual(board["threats"], [])
