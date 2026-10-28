"""Data shapes passed between the pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SOURCE_TYPES = ("rss", "google_news", "web_search")


@dataclass(frozen=True)
class Topic:
    """One column of the board, as configured in config/topics.yaml."""

    id: str
    name: str
    language: str = "en"
    min_items: int = 0
    max_items: int = 15
    color: int | None = None
    enabled: bool = True
    # config/briefs/<id>.md, or "" when the topic has none.
    brief: str = ""


@dataclass(frozen=True)
class Source:
    """One source, as configured in config/sources/<topic>.yaml. Which of the type
    specific fields matter depends on `type`."""

    id: str
    topic: str
    type: str
    name: str
    enabled: bool = True
    max_age_hours: float | None = None
    max_items: int | None = None
    notes: str = ""
    # rss
    url: str = ""
    # google_news
    google_topic: str = ""
    google_section: str = ""
    language: str = "en-US"
    country: str = "US"
    # google_news search, and web_search
    query: str = ""
    # web_search
    engine: str = ""
    max_results: int | None = None


@dataclass
class Candidate:
    """A single item from a source, cleaned up and ready for curation."""

    url: str
    title: str
    excerpt: str
    source_name: str
    source_id: str
    topic: str
    published: datetime | None
    image: str = ""


@dataclass
class FetchResult:
    """Outcome of fetching one source. Errors are values, not exceptions: one
    dead feed must never take the run down."""

    source: Source
    candidates: list[Candidate] = field(default_factory=list)
    # Items the source returned before the age and count limits.
    parsed_count: int = 0
    error: str = ""
    elapsed_seconds: float = 0.0
    # OpenRouter's own figure, for web_search.
    cost_usd: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.error


# A story as stored in archive/<YYYY>/<MM>/<DD>.yaml and shown on the site.
# Kept as a plain dict on purpose: it is written and read as YAML, and the
# site's script reads the same keys.
Story = dict[str, Any]
