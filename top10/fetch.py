"""Fetching every source into candidates.

Two rules shape this module:

* One broken source must never break the run. Every failure is captured on
  its FetchResult for the report instead of raising.
* Everything that leaves here is normalised - plain text, a stable URL, an
  aware UTC timestamp, already inside the run window - so curation never has
  to care that RSS, Atom, Google News and a web search describe an item
  differently.

Limits apply in a fixed order: the window and max_age_hours first, then
max_items, so "24h + 10 items" means the ten newest of the last day rather
than whichever of the newest ten happen to be recent.
"""

from __future__ import annotations

import calendar
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import feedparser
import requests

from . import googlenews, openrouter, pages
from .config import Settings
from .models import Candidate, FetchResult, Source
from .textutil import normalize_url, strip_html, truncate
from .window import Window

# What the prompt shows of each candidate. More costs tokens without helping
# the model pick.
EXCERPT_CHARS = 500
# Feed dates that parse to something absurd mean a broken feed, not a scoop.
_EARLIEST_SANE = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _parse_time(parsed: object) -> datetime | None:
    if not parsed:
        return None
    try:
        # feedparser has already normalised these to UTC.
        when = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)  # type: ignore[arg-type]
    except (ValueError, OverflowError, TypeError):
        return None
    return when if when >= _EARLIEST_SANE else None


def _entry_date(entry: feedparser.FeedParserDict) -> datetime | None:
    """Publication date, falling back to the update date. The fallback is
    wrong for anything revised, but far better than discarding the item."""
    return _parse_time(entry.get("published_parsed")) or _parse_time(entry.get("updated_parsed"))


def _entry_link(entry: feedparser.FeedParserDict) -> str:
    """Prefer rel="alternate": FeedBurner items carry several links and the
    plain .link is not always the article."""
    for link in entry.get("links") or []:
        if link.get("rel") == "alternate" and link.get("href"):
            return str(link["href"])
    return str(entry.get("link") or "")


def _entry_text(entry: feedparser.FeedParserDict) -> str:
    """Longest available description, as plain text."""
    texts = [entry.get("summary") or ""] + [c.get("value") or "" for c in entry.get("content") or []]
    return max((strip_html(t) for t in texts), key=len, default="")


def _entry_image(entry: feedparser.FeedParserDict) -> str:
    for enclosure in entry.get("enclosures") or []:
        if enclosure.get("href") and str(enclosure.get("type") or "image/").startswith("image/"):
            return str(enclosure["href"])
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key) or []:
            if media.get("url"):
                return str(media["url"])
    return ""


def _download(url: str, settings: Settings) -> bytes:
    """GET with retries for transient failures. Raises on final failure."""
    headers = {
        "User-Agent": settings.fetch.user_agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    }
    last_error: Exception | None = None
    for attempt in range(settings.fetch.retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=settings.fetch.timeout_seconds)
            # A 4xx means the configured URL is wrong or we are blocked;
            # retrying will not fix it, and the report should say so now.
            if 400 <= response.status_code < 500:
                raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
            response.raise_for_status()
            return response.content
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if 400 <= status < 500:
                raise
            last_error = exc
        except requests.RequestException as exc:
            last_error = exc
        if attempt < settings.fetch.retries:
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError("download failed")


def _cutoff(source: Source, window: Window) -> datetime:
    if source.max_age_hours:
        return max(window.since, window.until - timedelta(hours=source.max_age_hours))
    return window.since


def _limit(candidates: list[Candidate], source: Source, window: Window, cap: int | None) -> list[Candidate]:
    """Age first, then count - in the source's own order."""
    since = _cutoff(source, window)
    kept = [c for c in candidates if c.published and c.published >= since and window.contains(c.published)]
    return kept[:cap] if cap else kept


def _feed_candidates(body: bytes, source: Source, google: bool) -> tuple[list[Candidate], int]:
    parsed = feedparser.parse(body)
    entries = parsed.entries or []
    if not entries:
        detail = str(parsed.get("bozo_exception") or "").strip()
        raise ValueError(f"no items in feed{f' ({detail})' if detail else ''}")

    candidates = []
    for entry in entries:
        title, url = strip_html(entry.get("title") or ""), _entry_link(entry)
        if not title or not url:
            continue
        source_name = source.name
        excerpt = _entry_text(entry)
        if google:
            # Google puts the publisher in <source> and also appends
            # " - Publisher" to every headline.
            publisher = strip_html((entry.get("source") or {}).get("title") or "")
            if publisher:
                source_name = publisher
                title = title.removesuffix(f" - {publisher}").strip()
            # On topic feeds the description lists the other outlets running
            # the story - useful context for the model, so it is kept.
            excerpt = f"{excerpt} Reported by {source_name}, via Google News.".strip()
        candidates.append(
            Candidate(
                url=normalize_url(url),
                title=title,
                excerpt=truncate(excerpt, EXCERPT_CHARS),
                source_name=source_name,
                source_id=source.id,
                topic=source.topic,
                published=_entry_date(entry),
                image="" if google else _entry_image(entry),
            )
        )
    return candidates, len(entries)


def _fetch_rss(source: Source, settings: Settings, window: Window, result: FetchResult) -> None:
    candidates, result.parsed_count = _feed_candidates(_download(source.url, settings), source, google=False)
    result.candidates = _limit(candidates, source, window, source.max_items)


def _fetch_google_news(source: Source, settings: Settings, window: Window, result: FetchResult) -> None:
    url = googlenews.feed_url(source)
    candidates, result.parsed_count = _feed_candidates(_download(url, settings), source, google=True)
    cap = min(source.max_items or googlenews.DEFAULT_MAX_ITEMS, googlenews.MAX_ITEMS)
    result.candidates = _limit(candidates, source, window, cap)


def _fetch_web_search(source: Source, settings: Settings, window: Window, result: FetchResult) -> None:
    reply = openrouter.web_search(
        settings.models.search,
        source.query,
        source.engine,
        source.max_results or settings.web_search.max_results,
        settings.web_search.timeout_seconds,
    )
    result.cost_usd = reply.cost_usd
    result.parsed_count = len(reply.citations)

    candidates = []
    for citation in reply.citations:
        # Loading the page is the check that the story exists, and the only
        # reliable source of its title and date.
        page = pages.fetch(citation["url"], settings.fetch.user_agent, settings.web_search.verify_timeout_seconds)
        if page is None:
            continue
        host = urlsplit(page.url).netloc.removeprefix("www.")
        candidates.append(
            Candidate(
                url=normalize_url(citation["url"]),
                title=page.title or strip_html(citation.get("title") or "") or "(untitled)",
                excerpt=truncate(strip_html(citation.get("content") or ""), EXCERPT_CHARS),
                source_name=page.site_name or host,
                source_id=source.id,
                topic=source.topic,
                # No date on the page: search results are current by nature,
                # so the window's end rather than dropping it. Not "now" - that
                # is after window.until and the window would drop it.
                published=page.published or window.until,
                image=page.image,
            )
        )
    result.candidates = _limit(candidates, source, window, None)


_FETCHERS = {
    "rss": _fetch_rss,
    "google_news": _fetch_google_news,
    "web_search": _fetch_web_search,
}


def fetch_source(source: Source, settings: Settings, window: Window) -> FetchResult:
    started = time.monotonic()
    result = FetchResult(source=source)
    try:
        _FETCHERS[source.type](source, settings, window, result)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        result.error = f"HTTP {status}" if status else str(exc)
    except (requests.RequestException, openrouter.OpenRouterError, ValueError) as exc:
        result.error = f"{type(exc).__name__}: {exc}" if isinstance(exc, requests.RequestException) else str(exc)
    except Exception as exc:  # one source must never take the run down
        result.error = f"unexpected {type(exc).__name__}: {exc}"
    result.elapsed_seconds = time.monotonic() - started
    return result


def fetch_all(sources: list[Source], settings: Settings, window: Window) -> list[FetchResult]:
    """Every source in parallel, in config order: topics.yaml, then each file."""
    workers = max(1, min(settings.fetch.max_workers, len(sources)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda s: fetch_source(s, settings, window), sources))
