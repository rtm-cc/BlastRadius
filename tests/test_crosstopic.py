import json
import unittest

from blastradius import crosstopic, openrouter

from .factories import topic

TOPICS = {
    "world": topic(id="world", name="World News"),
    "brazil": topic(id="brazil", name="Brazil"),
    "ai": topic(id="ai", name="AI"),
}


def story(title, url, source="Src"):
    return {
        "title": title,
        "summary": "",
        "url": url,
        "rank": 1,
        "sources": [source],
        "coverage": [{"title": title, "url": url, "source": source, "published": None}],
    }


class FakeChat:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, model, system, user, timeout):
        self.prompts.append(user)
        return openrouter.Reply(content=self.replies.pop(0), cost_usd=0.001)


def board():
    return {
        "world": [story("Lula wins", "https://w/1"), story("Summit ends", "https://w/2")],
        "brazil": [story("Lula reeleito", "https://b/1", "g1")],
        "ai": [story("New model", "https://a/1")],
    }


def answer(*groups):
    return json.dumps({"duplicates": list(groups)})


class ReviewTest(unittest.TestCase):
    def run_review(self, reply, b=None, fixed=None):
        b = b if b is not None else board()
        chat = FakeChat(reply)
        result = crosstopic.review(b, fixed or {}, TOPICS, "m", 3, 10, chat=chat)
        return b, result, chat

    def test_ids_follow_topic_order(self):
        _, _, chat = self.run_review(answer())
        self.assertIn("## World News\n[s1] Lula wins", chat.prompts[0])
        self.assertIn("## Brazil\n[s3] Lula reeleito", chat.prompts[0])

    def test_duplicate_is_removed_and_its_coverage_kept(self):
        b, result, _ = self.run_review(answer({"keep": "s3", "remove": ["s1"], "reason": "Brazilian politics"}))
        self.assertEqual([s["title"] for s in b["world"]], ["Summit ends"])
        self.assertEqual(b["world"][0]["rank"], 1)
        kept = b["brazil"][0]
        self.assertEqual([c["url"] for c in kept["coverage"]], ["https://b/1", "https://w/1"])
        self.assertEqual(kept["sources"], ["g1", "Src"])
        self.assertEqual((result.removed[0].topic, result.removed[0].kept_topic), ("world", "brazil"))

    def test_invented_same_topic_and_contradictory_answers_change_nothing(self):
        reply = answer(
            {"keep": "s9", "remove": ["s1"]},  # unknown keeper
            {"keep": "s1", "remove": ["s2"]},  # same topic
            {"keep": "s1", "remove": ["s3"]},  # s3 is kept below...
            {"keep": "s3", "remove": ["s1"]},  # ...and s1 is kept above
        )
        b, result, _ = self.run_review(reply)
        self.assertEqual(result.removed, [])
        self.assertEqual(b, board())

    def test_fixed_stories_are_never_removed(self):
        fixed = {"brazil": [story("Lula reeleito", "https://b/1")]}
        b = {"world": [story("Lula wins", "https://w/1")]}
        _, result, _ = self.run_review(answer({"keep": "s1", "remove": ["s2"]}), b, fixed)
        self.assertEqual(result.removed, [])

    def test_unusable_answer_removes_nothing(self):
        chat = FakeChat("nope", "nope", "nope")
        b = board()
        result = crosstopic.review(b, {}, TOPICS, "m", 3, 10, chat=chat)
        self.assertIn("nothing removed", result.error)
        self.assertEqual(b, board())

    def test_one_topic_needs_no_call(self):
        _, result, _ = self.run_review("unused", {"ai": [story("x", "https://a/1")]})
        self.assertEqual(result.calls, 0)

    def test_duplicate_is_always_removed_even_if_topic_becomes_empty(self):
        # A true duplicate must never remain on the board just because a topic is short
        b = {
            "world": [story("Lula wins", "https://w/1"), story("Summit ends", "https://w/2")],
            "brazil": [story("Lula reeleito", "https://b/1", "g1")],
        }
        b, result, _ = self.run_review(answer({"keep": "s1", "remove": ["s3"], "reason": "World fit"}), b=b)
        self.assertEqual(len(result.removed), 1)
        self.assertEqual(len(b["brazil"]), 0)
        self.assertEqual(len(b["world"]), 2)

    def test_exact_url_overlap_is_removed_even_if_llm_misses_it(self):
        # Even if the LLM returns no duplicates, identical URLs are deduplicated
        b = {
            "world": [story("Shared story", "https://shared/url")],
            "brazil": [story("Shared story headline", "https://shared/url")],
        }
        b, result, _ = self.run_review(answer(), b=b)
        self.assertEqual(len(result.removed), 1)
        self.assertEqual(sum(len(slist) for slist in b.values()), 1)


if __name__ == "__main__":
    unittest.main()


def btcpay_pair():
    """The 2026-11-03 case: yesterday's card, carried over into Active
    Threats, and today's update of it in Vulnerabilities. Different
    outlets and headlines, one cluster."""
    old = {
        **story("BTCPay Server Urges Operators to Shut Down", "https://cybersecuritynews.com/btcpay-server-warns"),
        "id": "a46e5b2bfea3",
        "cluster": "a46e5b2bfea3",
        "is_carryover": True,
    }
    update = {
        **story(
            "BTCPay Server tells operators to update after hot-wallet thefts", "https://bleepingcomputer.com/btcpay"
        ),
        "id": "0f68334e8489",
        "cluster": "a46e5b2bfea3",
        "supersedes": "a46e5b2bfea3",
        "is_update": True,
    }
    return old, update


class CarryoverTest(unittest.TestCase):
    topics = {"threats": topic(id="threats", name="Active Threats"), "vulns": topic(id="vulns", name="Vulnerabilities")}

    def test_one_cluster_is_one_event_even_when_the_model_misses_it(self):
        old, update = btcpay_pair()
        b = {"threats": [old], "vulns": [update]}
        result = crosstopic.review(b, {}, self.topics, "m", 3, 10, chat=FakeChat(answer()))
        self.assertEqual(b["threats"], [])
        self.assertEqual([s["id"] for s in b["vulns"]], ["0f68334e8489"])
        self.assertEqual(result.removed[0].story["id"], "a46e5b2bfea3")

    def test_a_carryover_loses_even_when_the_model_keeps_it(self):
        old, update = btcpay_pair()
        del update["cluster"], update["supersedes"]  # only the model can tell
        b = {"threats": [old], "vulns": [update]}
        chat = FakeChat(answer({"keep": "s1", "remove": ["s2"], "reason": "fits threats better"}))
        crosstopic.review(b, {}, self.topics, "m", 3, 10, chat=chat)
        self.assertEqual(b["threats"], [])
        self.assertEqual([s["id"] for s in b["vulns"]], ["0f68334e8489"])
        self.assertIn("(carried over) BTCPay Server Urges", chat.prompts[0])


class KeeperTopicTest(unittest.TestCase):
    def test_a_poisoned_package_stays_in_supply_chain(self):
        """It nearly always carries malware, so the threats rule used to win."""
        threats = story("Malicious npm package drops infostealer", "https://t/1")
        supply = story("Malicious npm package drops infostealer", "https://s/1")
        keeper_topic, *_ = crosstopic._pick_keeper_topic("threats", threats, "supply_chain", supply, {})
        self.assertEqual(keeper_topic, "supply_chain")
