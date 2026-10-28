"""The parts around curation: window, config, archive, feeds, site, and a
whole run against fakes."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import textwrap
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from top10 import cli, config, fetch, googlenews, openrouter, site
from top10.archive import Archive
from top10.archive import load as load_yaml
from top10.state import State
from top10.config import ConfigError, WindowSettings
from top10.models import FetchResult, Source
from top10.window import Window, resolve

from .factories import NOW, candidate, pick
from .test_curate import answer

REPO = Path(__file__).resolve().parent.parent


class WindowTest(unittest.TestCase):
    settings = WindowSettings(default_hours=24, min_hours=6, max_hours=96, overlap_minutes=30)

    def test_since_the_last_run(self):
        window = resolve(NOW, NOW - timedelta(hours=20), self.settings)
        self.assertEqual(window.hours, 20.5)

    def test_first_run(self):
        self.assertEqual(resolve(NOW, None, self.settings).hours, 24)

    def test_clamped(self):
        self.assertEqual(resolve(NOW, NOW - timedelta(days=14), self.settings).hours, 96)
        self.assertEqual(resolve(NOW, NOW - timedelta(hours=1), self.settings).hours, 6)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        shutil.copytree(REPO / "config", self.dir, dirs_exist_ok=True)

    def edit(self, name, old, new):
        path = self.dir / name
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1))

    def test_the_real_config_loads(self):
        cfg = config.load(self.dir)
        self.assertTrue(cfg.enabled_sources)
        self.assertEqual(sorted(i for c in cfg.columns for i in c), sorted(t.id for t in cfg.enabled_topics))

    def test_unknown_source_type(self):
        self.edit("sources/breaches.yaml", "type: rss", "type: atom")
        with self.assertRaisesRegex(ConfigError, "type 'atom' is unknown"):
            config.load(self.dir)

    def test_each_file_is_its_topic(self):
        cfg = config.load(self.dir)
        self.assertEqual({s.topic for s in cfg.sources if s.id in ("databreaches_net", "hibp_breaches")}, {"breaches"})

    def test_shared_sources_are_marked_shared_and_enabled(self):
        cfg = config.load(self.dir)
        shared = [s for s in cfg.sources if s.topic == config.SHARED]
        self.assertIn("bleeping_computer", [s.id for s in shared])
        self.assertTrue(set(shared) <= set(cfg.enabled_sources) | {s for s in shared if not s.enabled})

    def test_shared_is_not_a_topic_id(self):
        self.edit("topics.yaml", "  - id: policy\n", "  - id: shared\n")
        with self.assertRaisesRegex(ConfigError, "reserved"):
            config.load(self.dir)

    def test_file_named_after_no_topic(self):
        (self.dir / "sources" / "breaches.yaml").rename(self.dir / "sources" / "breach.yaml")
        with self.assertRaisesRegex(ConfigError, "breach.yaml matches no topic id"):
            config.load(self.dir)

    def test_topic_line_contradicting_the_file(self):
        self.edit("sources/breaches.yaml", "  - id: databreaches_net\n", "  - id: databreaches_net\n    topic: policy\n")
        with self.assertRaisesRegex(ConfigError, "contradicts the file"):
            config.load(self.dir)

    def test_ids_are_unique_across_files(self):
        self.edit("sources/breaches.yaml", "  - id: databreaches_net\n", "  - id: bleeping_computer\n")
        with self.assertRaisesRegex(ConfigError, "already used in shared.yaml"):
            config.load(self.dir)

    def test_misspelt_setting(self):
        self.edit("settings.yaml", "max_attempts:", "max_attempt:")
        with self.assertRaisesRegex(ConfigError, "curation.max_attempt"):
            config.load(self.dir)

    def test_orphan_brief(self):
        (self.dir / "briefs" / "sport.md").write_text("x")
        with self.assertRaisesRegex(ConfigError, "sport.md"):
            config.load(self.dir)

    def test_topic_missing_from_board_gets_a_column(self):
        self.edit("topics.yaml", "    - [threats]\n", "")
        self.assertEqual(config.load(self.dir).columns[-1], ["threats"])


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.archive = Archive(self.dir)

    def story(self, title):
        return {"id": title, "title": title, "url": f"https://x/{title}", "labels": ["Tag"]}

    def test_publish_replaces_only_the_given_topics(self):
        self.archive.publish("2026-10-27", {"a": [self.story("a1")], "b": [self.story("b1")]}, NOW)
        self.archive.publish("2026-10-27", {"a": [self.story("a2")]}, NOW)
        day = self.archive.load_day("2026-10-27")
        self.assertEqual([s["id"] for s in day["a"]], ["a2"])
        self.assertEqual([s["id"] for s in day["b"]], ["b1"])

    def test_recent_leaves_out_today_and_old_days(self):
        for day in ("2026-10-01", "2026-10-25", "2026-10-26", "2026-10-27"):
            self.archive.publish(day, {"a": [self.story(day)]}, NOW)
        recent = self.archive.recent("a", "2026-10-27", days=10, limit=50)
        self.assertEqual([s["id"] for s in recent], ["2026-10-26", "2026-10-25"])

    def test_prune(self):
        for day in ("2026-06-01", "2026-10-26"):
            self.archive.publish(day, {"a": [self.story(day)]}, NOW)
        self.assertEqual(self.archive.prune("2026-10-27", 120), ["2026-06-01"])
        self.assertEqual(self.archive.days(), ["2026-10-26"])
        # The emptied month and year folders go too.
        self.assertFalse((self.dir / "2026" / "06").exists())

    def test_day_files_are_yyyy_mm_dd(self):
        path = self.archive.publish("2026-10-27", {"a": [self.story("x")]}, NOW)
        self.assertEqual(path, self.dir / "2026" / "10" / "27.yaml")

    def test_values_that_look_like_other_types_round_trip(self):
        # Unquoted, YAML would read these back as a date, a bool, a number
        # and null. safe_dump has to quote them.
        tricky = {
            "id": "x", "title": "no", "summary": "2026-10-27", "url": "https://x/1",
            "rank": 1, "labels": ["yes", "1.0", "null", "Côja: «fogo»"], "published": "2026-10-27T07:00:00+00:00",
            "what_changed": None, "is_update": False,
        }
        self.archive.publish("2026-10-27", {"a": [tricky]}, NOW)
        reread = Archive(self.dir).load_day("2026-10-27")["a"][0]
        self.assertEqual(reread, tricky)

    def test_state_reads_the_old_json_and_replaces_it(self):
        (self.dir / "state.json").write_text('{"last_run_utc": "2026-10-27T06:00:00+00:00", "runs": 3}')
        state = State(self.dir)
        self.assertEqual(state.last_run.isoformat(), "2026-10-27T06:00:00+00:00")
        state.record_run(NOW, 5, 0.07)
        self.assertFalse((self.dir / "state.json").exists())
        self.assertEqual(load_yaml((self.dir / "state.yaml").read_text())["runs"], 4)


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
<item><title>New &amp; fresh</title><link>https://example.com/new?utm_source=rss</link>
<description>&lt;p&gt;Body&lt;/p&gt;</description><pubDate>Tue, 27 Oct 2026 06:00:00 GMT</pubDate>
<enclosure url="https://example.com/i.jpg" type="image/jpeg" length="1"/></item>
<item><title>Old</title><link>https://example.com/old</link><pubDate>Mon, 19 Oct 2026 06:00:00 GMT</pubDate></item>
<item><title>Undated</title><link>https://example.com/undated</link></item>
</channel></rss>"""

GOOGLE = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>World - Latest - Google News</title>
<item><title>Summit ends - Reuters</title><link>https://news.google.com/rss/articles/CBMi1?oc=5</link>
<pubDate>Tue, 27 Oct 2026 05:00:00 GMT</pubDate><description>Summit ends</description>
<source url="https://www.reuters.com">Reuters</source></item>
</channel></rss>"""


class FeedTest(unittest.TestCase):
    window = Window(NOW - timedelta(hours=24), NOW, "test")

    def fetch(self, body, source):
        settings = config.Settings()
        with mock.patch.object(fetch, "_download", return_value=body):
            return fetch.fetch_source(source, settings, self.window)

    def test_rss_window_and_cleanup(self):
        result = self.fetch(RSS, Source(id="f", topic="t", type="rss", name="Feed", url="https://example.com/feed"))
        self.assertEqual(result.parsed_count, 3)
        [c] = result.candidates
        self.assertEqual((c.title, c.url, c.excerpt, c.image), ("New & fresh", "https://example.com/new", "Body", "https://example.com/i.jpg"))

    def test_google_news_publisher(self):
        result = self.fetch(GOOGLE, Source(id="g", topic="t", type="google_news", name="GN", google_topic="WORLD"))
        [c] = result.candidates
        self.assertEqual((c.title, c.source_name, c.url), ("Summit ends", "Reuters", "https://news.google.com/rss/articles/CBMi1"))

    def test_a_broken_feed_is_a_value(self):
        result = self.fetch(b"<html>nope</html>", Source(id="f", topic="t", type="rss", name="Feed", url="https://example.com/feed"))
        self.assertIn("no items in feed", result.error)

    def test_google_news_urls(self):
        section = Source(id="g", topic="t", type="google_news", name="g", google_topic="world")
        self.assertEqual(googlenews.feed_url(section), "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en")
        search = Source(id="g", topic="t", type="google_news", name="g", query="nasa", max_age_hours=24, language="pt-BR", country="BR")
        self.assertEqual(googlenews.feed_url(search), "https://news.google.com/rss/search?q=nasa+when:1d&hl=pt-BR&gl=BR&ceid=BR:pt")


class SiteTest(unittest.TestCase):
    def test_unsafe_values_never_reach_the_page(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        archive = Archive(tmp / "archive")
        archive.publish(
            "2026-10-27",
            {"tech": [{"id": "s1", "rank": 1, "title": "</script><b>x", "url": "javascript:alert(1)", "image": "data:x", "cluster": "s1"}]},
            NOW,
        )
        cfg = config.load(REPO / "config")
        cfg = config.Config(
            settings=config.Settings(site=config.SiteSettings(directory=str(tmp / "public"), title="T")),
            topics=cfg.topics,
            columns=cfg.columns,
            sources=cfg.sources,
        )
        out = site.build(cfg, archive, NOW)
        page = (out / "index.html").read_text()
        self.assertNotIn("</script><b>", page)
        card = json.loads((out / "days" / "2026-10-27.json").read_text())["stories"][0]
        self.assertEqual((card["url"], card["image"]), ("", ""))
        self.assertIn(["tech"], json.loads(page.split('id="boot">')[1].split("</script>")[0])["columns"])
        self.assertTrue((out / "search.json.gz").exists())


class RunTest(unittest.TestCase):
    """A whole run, with the network replaced."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)
        config_dir = self.dir / "config"
        (config_dir / "briefs").mkdir(parents=True)
        (config_dir / "settings.yaml").write_text("timezone: Europe/Lisbon\nimages:\n  resolve: false\n")
        (config_dir / "topics.yaml").write_text(textwrap.dedent("""\
            topics:
              - {id: tech, name: Technology}
              - {id: space, name: Space}
            """))
        (config_dir / "sources").mkdir()
        (config_dir / "sources" / "tech.yaml").write_text(
            'sources:\n  - {id: t, type: rss, name: T, url: "https://t.example/feed"}\n'
        )
        (config_dir / "sources" / "space.yaml").write_text(
            'sources:\n  - {id: s, type: rss, name: S, url: "https://s.example/feed"}\n'
        )
        (config_dir / "sources" / "shared.yaml").write_text(
            'sources:\n  - {id: x, type: rss, name: X, url: "https://x.example/feed"}\n'
        )
        patches = [
            mock.patch.object(config, "CONFIG_DIR", config_dir),
            mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}),
            mock.patch.object(cli.env, "load", return_value=cli.env.Loaded()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_with(self, replies, results):
        """`replies` maps a topic name to what the model answers for it.
        Topics are curated in parallel, so routing by topic rather than by
        call order keeps the test deterministic."""

        def fake_fetch(sources, settings, window):
            return [FetchResult(source=s, candidates=results.get(s.id, []), parsed_count=1) for s in sources]

        def chat(model, system, user, timeout):
            if "## Topic: " not in user:  # the cross-topic review
                return openrouter.Reply(content=replies.get("review", '{"duplicates": []}'), cost_usd=0.001)
            name = user.split("## Topic: ", 1)[1].split("\n", 1)[0]
            return openrouter.Reply(content=replies[name], cost_usd=0.01)

        with mock.patch.object(cli.fetch, "fetch_all", fake_fetch), mock.patch.object(openrouter, "chat_json", chat):
            with contextlib.redirect_stdout(io.StringIO()):
                return cli.main(["run"])

    def test_publishes_and_builds(self):
        code = self.run_with(
            {"Technology": answer(pick("https://t.example/1"))},
            {"t": [candidate("https://t.example/1", topic="tech")]},
        )
        self.assertEqual(code, cli.EXIT_OK)
        [path] = (self.dir / "archive").glob("*/*/*.yaml")
        self.assertEqual(list(load_yaml(path.read_text())["topics"]), ["tech"])
        self.assertTrue((self.dir / "archive" / "state.yaml").exists())
        self.assertTrue((self.dir / "public" / "index.html").exists())

    def test_a_shared_source_reaches_every_topic(self):
        code = self.run_with(
            {
                "Technology": answer(pick("https://x.example/1")),
                "Space": answer(pick("https://x.example/1", topic="Space")),
            },
            {"x": [candidate("https://x.example/1", topic="shared")]},
        )
        self.assertEqual(code, cli.EXIT_OK)
        [path] = (self.dir / "archive").glob("*/*/*.yaml")
        self.assertEqual(sorted(load_yaml(path.read_text())["topics"]), ["space", "tech"])

    def test_a_failed_topic_is_partial_and_keeps_the_rest(self):
        code = self.run_with(
            {"Technology": "nope", "Space": answer(pick("https://s.example/1", topic="Space"))},
            {
                "t": [candidate("https://t.example/1", topic="tech")],
                "s": [candidate("https://s.example/1", topic="space")],
            },
        )
        self.assertEqual(code, cli.EXIT_PARTIAL)
        [path] = (self.dir / "archive").glob("*/*/*.yaml")
        self.assertEqual(list(load_yaml(path.read_text())["topics"]), ["space"])

    def test_every_topic_failing_writes_nothing(self):
        code = self.run_with({"Technology": "nope"}, {"t": [candidate("https://t.example/1", topic="tech")]})
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertFalse((self.dir / "archive" / "state.yaml").exists())

    def test_every_source_failing_writes_nothing(self):
        def broken(sources, settings, window):
            return [FetchResult(source=s, error="HTTP 500") for s in sources]

        with mock.patch.object(cli.fetch, "fetch_all", broken), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["run"]), cli.EXIT_FAILED)
        self.assertFalse((self.dir / "archive").exists())


if __name__ == "__main__":
    unittest.main()
