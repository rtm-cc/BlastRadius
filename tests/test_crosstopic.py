import json
import unittest

from top10 import crosstopic, openrouter

from .factories import topic

TOPICS = {
    "world": topic(id="world", name="World News"),
    "brazil": topic(id="brazil", name="Brazil"),
    "ai": topic(id="ai", name="AI"),
}


def story(title, url, source="Src"):
    return {"title": title, "summary": "", "url": url, "rank": 1, "sources": [source],
            "coverage": [{"title": title, "url": url, "source": source, "published": None}]}


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
            {"keep": "s9", "remove": ["s1"]},             # unknown keeper
            {"keep": "s1", "remove": ["s2"]},             # same topic
            {"keep": "s1", "remove": ["s3"]},             # s3 is kept below...
            {"keep": "s3", "remove": ["s1"]},             # ...and s1 is kept above
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


if __name__ == "__main__":
    unittest.main()
