import unittest

from blastradius.urlmatch import build_index, resolve

GOOGLE = "https://news.google.com/rss/articles/CBMiyg1234"


class ResolveTest(unittest.TestCase):
    def test_exact(self):
        index = build_index(["https://example.com/a"])
        self.assertEqual(resolve(index, "https://example.com/a"), "https://example.com/a")

    def test_scheme_www_and_tracking_are_ignored(self):
        index = build_index(["https://www.example.com/a?id=1"])
        self.assertEqual(resolve(index, "http://example.com/a?utm_source=x&id=1"), "https://www.example.com/a?id=1")

    def test_dropped_query_resolves_when_unambiguous(self):
        index = build_index(["https://example.com/story?ref=feed&page=1"])
        self.assertEqual(resolve(index, "https://example.com/story"), "https://example.com/story?ref=feed&page=1")

    def test_invented_query_never_resolves(self):
        index = build_index(["https://example.com/story"])
        self.assertIsNone(resolve(index, "https://example.com/story?id=9"))

    def test_shared_path_is_ambiguous(self):
        index = build_index(["https://example.com/s?id=1", "https://example.com/s?id=2"])
        self.assertIsNone(resolve(index, "https://example.com/s"))

    def test_prose_punctuation(self):
        index = build_index([GOOGLE])
        self.assertEqual(resolve(index, f"<{GOOGLE}>."), GOOGLE)

    def test_unknown(self):
        self.assertIsNone(resolve(build_index(["https://a.example/x"]), "https://b.example/x"))


if __name__ == "__main__":
    unittest.main()
