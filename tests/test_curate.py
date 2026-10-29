import json
import unittest
from collections import Counter

from blastradius import curate, openrouter
from blastradius.urlmatch import build_index

from .factories import candidate, pick, topic

A, B, C = "https://example.com/a", "https://example.com/b", "https://example.com/c"


def answer(*stories: dict) -> str:
    return json.dumps({"stories": list(stories)})


class FakeChat:
    """Replies in order and records every prompt it was sent."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, model, system, user, timeout):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return openrouter.Reply(content=reply, cost_usd=0.01)


class ExtractJsonTest(unittest.TestCase):
    def test_fenced_and_chatty(self):
        self.assertEqual(curate.extract_json('Here you go:\n```json\n{"a": "}"}\n```\nDone.'), '{"a": "}"}')

    def test_truncated(self):
        stories, problem = curate.parse_answer('{"stories": [{"title": "x"')
        self.assertIsNone(stories)
        self.assertIn("cut off", problem)

    def test_schema(self):
        stories, problem = curate.parse_answer(answer({**pick(A), "labels": "ai"}))
        self.assertIsNone(stories)
        self.assertIn("labels", problem)

    def test_optional_fields_may_be_missing(self):
        story = pick(A)
        del story["otherSources"], story["supersedes"]
        stories, problem = curate.parse_answer(answer(story))
        self.assertEqual(problem, "")
        self.assertEqual(len(stories), 1)


class VerifyTest(unittest.TestCase):
    def verify(self, stories, candidates, **topic_overrides):
        by_url = {c.url: c for c in candidates}
        return curate.verify(stories, topic(**topic_overrides), by_url, build_index(by_url))

    def test_invented_url_and_topic_are_rejected(self):
        out = self.verify([pick("https://example.com/nope"), pick(A, topic="Sport")], [candidate(A)])
        self.assertEqual(out.accepted, [])
        self.assertEqual([r for _, r in out.rejected], [curate.UNRESOLVED_URL, 'unknown topic "Sport"'])

    def test_sources_come_from_candidates_not_the_model(self):
        out = self.verify(
            [pick(A, coverageUrls=[A, B, "https://made.up/x"], otherSources=["Invented"])],
            [candidate(A, source_name="One"), candidate(B, source_name="Two")],
        )
        self.assertEqual(out.accepted[0]["coverageUrls"], [A, B])
        self.assertEqual(out.accepted[0]["otherSources"], ["Two"])

    def test_overlapping_coverage_is_one_event(self):
        out = self.verify([pick(A, coverageUrls=[A, B]), pick(B, rank=2)], [candidate(A), candidate(B)])
        self.assertEqual([s["url"] for s in out.accepted], [A])

    def test_same_event_is_merged_on_distinctive_words(self):
        pool = [candidate(A), candidate(B)] + [candidate(f"https://example.com/{i}", f"filler {i}") for i in range(20)]
        out = self.verify(
            [
                pick(A, "Sangoma Switchvox flaw exploited", summary="Attackers exploit Switchvox appliances from Sangoma"),
                pick(B, "Switchvox bug hits Sangoma users", rank=2, summary="Sangoma Switchvox appliances exploited in attacks"),
            ],
            pool,
        )
        self.assertEqual(len(out.accepted), 1)
        self.assertEqual(out.accepted[0]["coverageUrls"], [A, B])

    def test_beat_vocabulary_alone_does_not_merge(self):
        # Every candidate in the pool talks about "vulnerability" and
        # "attackers"; that is the topic, not the event.
        pool = [candidate(f"https://example.com/{i}", "vulnerability attackers remote injection") for i in range(10)]
        pool += [candidate(A), candidate(B)]
        out = self.verify(
            [
                pick(A, "WordPress plugin vulnerability", summary="attackers remote injection vulnerability"),
                pick(B, "Router firmware vulnerability", rank=2, summary="attackers remote injection vulnerability"),
            ],
            pool,
        )
        self.assertEqual(len(out.accepted), 2)

    def test_max_items_is_a_ceiling(self):
        out = self.verify([pick(A), pick(B, rank=2)], [candidate(A), candidate(B)], max_items=1)
        self.assertEqual(len(out.accepted), 1)
        self.assertIn("exceeds max items", out.rejected[0][1])


class CurateTopicTest(unittest.TestCase):
    def run_topic(self, chat, candidates, **topic_overrides):
        return curate.curate_topic(topic(**topic_overrides), candidates, [], [], "m", 3, 1, 10, chat=chat)

    def test_invalid_json_is_retried_with_the_reason(self):
        chat = FakeChat("not json", answer(pick(A)))
        result = self.run_topic(chat, [candidate(A)])
        self.assertEqual(result.error, "")
        self.assertEqual(len(result.accepted), 1)
        self.assertIn("previous response was invalid", chat.prompts[1])

    def test_gives_up_after_max_attempts(self):
        chat = FakeChat(openrouter.OpenRouterError("HTTP 500"), "nope", "nope")
        result = self.run_topic(chat, [candidate(A)])
        self.assertTrue(result.error.startswith("after 3 calls"))
        self.assertEqual(result.accepted, [])

    def test_miscopied_urls_get_one_repair_round(self):
        chat = FakeChat(answer(pick("https://example.com/typo")), answer(pick(A)))
        result = self.run_topic(chat, [candidate(A)])
        self.assertEqual(len(result.accepted), 1)
        self.assertIn("https://example.com/typo", chat.prompts[1])

    def test_empty_answer_for_a_full_pool_is_challenged(self):
        chat = FakeChat(answer(), answer(pick(A)))
        result = self.run_topic(chat, [candidate(A), candidate(B)])
        self.assertEqual(len(result.accepted), 1)
        self.assertIn("returned no stories at all", chat.prompts[1])

    def test_thin_news_is_not_padded(self):
        # Short of min_items, but nothing a second ask could fix.
        chat = FakeChat(answer(pick(A)))
        result = self.run_topic(chat, [candidate(A), candidate(B)], min_items=5)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(len(chat.prompts), 1)

    def test_a_worse_repair_keeps_the_first_answer(self):
        chat = FakeChat(answer(pick(A), pick("https://example.com/typo", rank=2)), answer())
        result = self.run_topic(chat, [candidate(A), candidate(B)], min_items=2)
        self.assertEqual([s["url"] for s in result.accepted], [A])


class RecordsTest(unittest.TestCase):
    published = [
        {"id": "old1", "day": "2026-10-26", "title": "Mars rover finds water", "cluster": "c1", "cluster_key": "finds-mars-rover-water"},
    ]

    def records(self, picks, existing_today=()):
        result = curate.TopicResult(topic=topic(), candidates=1, accepted=picks)
        by_url = {u: candidate(u) for u in (A, B)}
        return curate.to_records(result, "2026-10-27", by_url, self.published, list(existing_today))

    def test_update_joins_the_earlier_cluster(self):
        [record] = self.records([pick(A, isUpdate=True, supersedes="Mars rover finds water", whatChanged="More water")])
        self.assertEqual((record["is_update"], record["supersedes"], record["cluster"]), (True, "old1", "c1"))

    def test_update_continues_a_story_from_another_topic(self):
        # Board-wide history: yesterday's story ran in another topic; today's
        # update in this one joins its cluster all the same.
        published = [{"id": "v1", "day": "2026-10-26", "topic": "vulnerabilities",
                      "title": "FortiMail zero-day patched", "cluster": "cv", "cluster_key": "x"}]
        result = curate.TopicResult(topic=topic(id="threats", name="Active Threats"), candidates=1,
                                    accepted=[pick(A, isUpdate=True, supersedes="FortiMail zero-day patched")])
        [record] = curate.to_records(result, "2026-10-27", {A: candidate(A)}, published, [])
        self.assertEqual((record["supersedes"], record["cluster"]), ("v1", "cv"))

    def test_paraphrased_supersedes_falls_back_to_the_headline_fingerprint(self):
        [record] = self.records([pick(A, "Water finds Mars rover", isUpdate=True, supersedes="something else")])
        self.assertEqual(record["supersedes"], "old1")

    def test_update_of_nothing_real_is_a_new_story(self):
        [record] = self.records([pick(A, "Unrelated", isUpdate=True, supersedes="Invented")])
        self.assertFalse(record["is_update"])
        self.assertEqual(record["cluster"], record["id"])

    def test_same_day_rerun_keeps_the_link(self):
        earlier = {"url": A, "cluster": "c1", "cluster_key": "x", "is_update": True, "supersedes": "old1", "what_changed": "w"}
        [record] = self.records([pick(A, "Retitled")], existing_today=[earlier])
        self.assertEqual((record["cluster"], record["is_update"], record["supersedes"]), ("c1", True, "old1"))

    def test_ranks_are_renumbered(self):
        records = self.records([pick(A, rank=3), pick(B, rank=7)])
        self.assertEqual([r["rank"] for r in records], [1, 2])


class PromptTest(unittest.TestCase):
    published = [{"id": "v1", "day": "2026-10-26", "topic": "vulnerabilities", "title": "FortiMail zero-day", "summary": "s"}]

    def test_own_history_is_unlabelled(self):
        prompt = curate.build_prompt(topic(), [candidate(A)], self.published, [])
        self.assertIn("ALREADY PUBLISHED (do not repeat unless materially new):\n- 2026-10-26 | FortiMail zero-day", prompt)

    def test_board_history_names_each_story_topic(self):
        prompt = curate.build_prompt(topic(), [candidate(A)], self.published, [], {"vulnerabilities": "Vulnerabilities & Patches"})
        self.assertIn("ALREADY PUBLISHED ON THE WHOLE BOARD", prompt)
        self.assertIn("- 2026-10-26 | [Vulnerabilities & Patches] FortiMail zero-day", prompt)


class TagVocabularyTest(unittest.TestCase):
    def test_active_topic_and_matching_words_rank_first(self):
        counts = Counter({("tech", "Space"): 1, ("tech", "Chips"): 30, ("other", "Football"): 99})
        tags = curate.tag_vocabulary(counts, {"tech": [candidate(A, "New space telescope")]}, {"tech": topic()})
        self.assertEqual(tags, ["Space", "Chips", "Football"])


if __name__ == "__main__":
    unittest.main()
