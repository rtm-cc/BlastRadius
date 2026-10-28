"""Matching a URL the model quoted back to the candidate it came from.

"Reject any story whose url is not in the candidate set" is the check that
stops the model inventing stories, and it has to stay strict. But a byte-exact
comparison also rejects *real* candidates whenever the model tidies the URL on
its way back out, which, found live, it does constantly:

    candidate  https://news.google.com/rss/articles/CBMiyg…?ceid=US:en&gl=US&hl=en-US&oc=5
    model      https://news.google.com/rss/articles/CBMiyg…

The ~300 character token that identifies the article was copied perfectly;
only Google's presentation suffix was dropped. One day that cost a
topic 14 of its 15 stories.

So resolution is layered, most specific first, and never guesses:

1. exact string match;
2. normalised match (tracking parameters stripped, scheme and `www.`
   ignored);
3. host and path, ignoring the query entirely - but only when exactly one
   candidate has that host and path, and only when the model dropped a query
   rather than invented one, so an invented `?id=` is never mapped onto a real
   article.

A URL that resolves through none of these is still rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import SplitResult, urlsplit

from .textutil import normalize_url


@dataclass
class CandidateIndex:
    exact: set[str] = field(default_factory=set)
    normalized: dict[str, str] = field(default_factory=dict)
    # host+path -> the one candidate with it, or None when several share it.
    by_path: dict[str, str | None] = field(default_factory=dict)


def _clean(raw: str) -> str:
    """Models quote URLs inside prose punctuation more often than you would hope."""
    return re.sub(r"[>\"')\].,;]+$", "", re.sub(r"^[<\"'(\[]+", "", raw.strip()))


def _parse(raw: str) -> SplitResult | None:
    try:
        parts = urlsplit(normalize_url(_clean(raw)))
    except ValueError:
        return None
    return parts if parts.scheme and parts.netloc else None


def _host(parts: SplitResult) -> str:
    return parts.netloc.removeprefix("www.")


def _normalized_key(parts: SplitResult) -> str:
    return f"{_host(parts)}{parts.path}?{parts.query}"


def _path_key(parts: SplitResult) -> str:
    return f"{_host(parts)}{parts.path}"


def build_index(candidate_urls: Iterable[str]) -> CandidateIndex:
    index = CandidateIndex()
    for url in candidate_urls:
        index.exact.add(url)
        parts = _parse(url)
        if parts is None:
            continue
        index.normalized.setdefault(_normalized_key(parts), url)
        # Two candidates sharing a path but not a query are genuinely
        # different articles (/story?id=1, /story?id=2). Poison the entry
        # rather than pick one, so tier 3 stays a safe last resort.
        path = _path_key(parts)
        if path in index.by_path and index.by_path[path] != url:
            index.by_path[path] = None
        else:
            index.by_path.setdefault(path, url)
    return index


def resolve(index: CandidateIndex, raw_url: str) -> str | None:
    """The candidate URL this one refers to, or None if it refers to none."""
    if not isinstance(raw_url, str):
        return None
    if raw_url in index.exact:
        return raw_url
    parts = _parse(raw_url)
    if parts is None:
        return None
    found = index.normalized.get(_normalized_key(parts))
    if found:
        return found
    if parts.query:
        return None
    return index.by_path.get(_path_key(parts))
