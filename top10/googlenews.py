"""Google News feed URLs.

A source names either a section (WORLD, TECHNOLOGY, ...), an opaque topic id
copied from a news.google.com/topics/<id> URL, or a search query. Section
URLs redirect to the section's own opaque topic, so typing WORLD is enough;
docs/google-news-topics.md covers finding a narrower topic id.
"""

from __future__ import annotations

import math
import re
from urllib.parse import quote, urlencode

from .models import Source

SECTIONS = ("WORLD", "NATION", "BUSINESS", "TECHNOLOGY", "ENTERTAINMENT", "SPORTS", "SCIENCE", "HEALTH")
# Google's front page has no id of its own.
TOP_STORIES = "TOP"
DEFAULT_MAX_ITEMS = 25
# A feed never holds more, and there is no paging.
MAX_ITEMS = 100


def _when(max_age_hours: float | None) -> str:
    """Search supports `when:`, so an age limit is applied by Google as well
    as locally and the ranking and the filter agree. Topic feeds have no
    equivalent."""
    if not max_age_hours or max_age_hours <= 0:
        return ""
    if max_age_hours < 24:
        return f"when:{max(1, round(max_age_hours))}h"
    return f"when:{min(math.ceil(max_age_hours / 24), 365)}d"


def feed_url(source: Source) -> str:
    language = source.language or "en-US"
    country = source.country or "US"
    params: list[tuple[str, str]] = []

    if source.query:
        query = source.query.strip()
        when = _when(source.max_age_hours)
        # A when: written into the query wins - two would contradict.
        if when and not re.search(r"\bwhen:", query, re.IGNORECASE):
            query = f"{query} {when}"
        params.append(("q", query))
        path = "/search"
    elif source.google_topic.upper() == TOP_STORIES:
        path = ""
    elif source.google_topic.upper() in SECTIONS:
        path = f"/headlines/section/topic/{source.google_topic.upper()}"
    else:
        path = f"/topics/{quote(source.google_topic, safe='')}"
        if source.google_section:
            path += f"/sections/{quote(source.google_section, safe='')}"

    # ceid pairs the country with the bare language: "US:en", not "US:en-US".
    params += [("hl", language), ("gl", country), ("ceid", f"{country}:{language.split('-')[0]}")]
    return f"https://news.google.com/rss{path}?{urlencode(params).replace('%3A', ':')}"
