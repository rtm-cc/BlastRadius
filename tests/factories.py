"""Small builders so tests say only what they are about."""

from __future__ import annotations

from datetime import UTC, datetime

from blastradius.models import Candidate, Topic

NOW = datetime(2026, 10, 27, 7, 0, tzinfo=UTC)


def topic(**overrides) -> Topic:
    values = {"id": "tech", "name": "Technology", "language": "en", "min_items": 0, "max_items": 15}
    values.update(overrides)
    return Topic(**values)


def candidate(url: str, title: str = "A story", **overrides) -> Candidate:
    values = {
        "url": url,
        "title": title,
        "excerpt": "",
        "source_name": "Example",
        "source_id": "example",
        "topic": "tech",
        "published": NOW,
    }
    values.update(overrides)
    return Candidate(**values)


def pick(url: str, title: str = "A story", rank: int = 1, **overrides) -> dict:
    """One story as the model would return it."""
    values = {
        "topic": "Technology",
        "rank": rank,
        "title": title,
        "summary": "",
        "url": url,
        "coverageUrls": [url],
        "otherSources": [],
        "labels": [],
        "rationale": "why",
        "isUpdate": False,
        "supersedes": None,
        "whatChanged": None,
    }
    values.update(overrides)
    return values
