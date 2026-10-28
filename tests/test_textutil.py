import unittest

from top10.textutil import cluster_key, normalize_url, strip_html, truncate


class NormalizeUrlTest(unittest.TestCase):
    def test_strips_tracking_and_sorts(self):
        self.assertEqual(
            normalize_url("https://Example.com/a/?utm_source=x&b=2&a=1&fbclid=z#frag"),
            "https://example.com/a?a=1&b=2",
        )

    def test_bbc_syndication_tags_are_tracking(self):
        self.assertEqual(
            normalize_url("https://www.bbc.co.uk/news/world-1?at_medium=RSS&at_campaign=rss"),
            "https://www.bbc.co.uk/news/world-1",
        )

    def test_google_news_query_is_presentation_only(self):
        self.assertEqual(
            normalize_url("https://news.google.com/rss/articles/CBMi123?oc=5&hl=en-US&gl=US&ceid=US:en"),
            "https://news.google.com/rss/articles/CBMi123",
        )

    def test_keeps_scheme_and_real_parameters(self):
        self.assertEqual(normalize_url("http://example.com/story?id=7"), "http://example.com/story?id=7")

    def test_redirect_wrapper_is_unwrapped(self):
        self.assertEqual(
            normalize_url("https://redir.folha.com.br/redir/online/emcimadahora/rss091/*https://www1.folha.uol.com.br/poder/x.shtml"),
            "https://www1.folha.uol.com.br/poder/x.shtml",
        )

    def test_unparseable_is_returned_trimmed(self):
        self.assertEqual(normalize_url("  not a url "), "not a url")


class ClusterKeyTest(unittest.TestCase):
    def test_matches_the_old_apps_stored_keys(self):
        # Taken from the backup: the key the TypeScript app stored for this title.
        self.assertEqual(
            cluster_key("ShinyHunters Uses WAF Bypass Trick to Keep Exploiting Oracle PeopleSoft Flaw"),
            "bypass-exploiting-flaw-keep-oracle-peoplesoft-shinyhunters-trick-uses-waf",
        )

    def test_word_order_does_not_matter(self):
        self.assertEqual(cluster_key("Mars rover lands"), cluster_key("lands rover Mars"))


class TextTest(unittest.TestCase):
    def test_strip_html(self):
        self.assertEqual(strip_html("<p>One &amp; <b>two</b></p><script>x()</script>"), "One & two")

    def test_truncate_on_word_boundary(self):
        self.assertEqual(truncate("alpha beta gamma", 12), "alpha beta…")


if __name__ == "__main__":
    unittest.main()
