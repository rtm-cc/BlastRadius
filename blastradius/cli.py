"""Command line entry point: `python -m blastradius <command>`.

    run            fetch, curate, write today's board, rebuild the site
    check          validate config/ and list what a run would fetch
    check-feed     fetch one RSS/Atom URL and show what a source would get
    build-site     rebuild public/ from the archive, no fetching

Exit codes, which CI relies on:

    0  a clean run
    1  nothing was published - bad config, no API key, every source failed,
       or every topic failed to curate
    2  the board was published, but at least one topic failed to curate;
       CI shows it as a warning so it gets noticed
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import config as config_module
from . import crosstopic, curate, env, fetch, openrouter, pages, site
from .archive import Archive
from .config import SHARED, Config, ConfigError
from .models import Candidate, FetchResult, Source, Story
from .state import State
from .textutil import is_opaque_interstitial
from .window import Window, resolve, utc_now

EXIT_OK, EXIT_FAILED, EXIT_PARTIAL = 0, 1, 2

def _print(line: str = "") -> None:
    print(line, flush=True)

# --- run ----------------------------------------------------------------------

def _pool(results: list[FetchResult], topic_ids: list[str], limit: int | None) -> dict[str, list[Candidate]]:
    """Each topic's candidates: one per URL, in config order, so when
    two sources carry the same article the one listed first names it. A
    shared source's candidates go to every topic."""
    pools: dict[str, dict[str, Candidate]] = {t: {} for t in topic_ids}
    for result in results:
        for candidate in result.candidates:
            for topic_id in topic_ids if candidate.topic == SHARED else [candidate.topic]:
                pools[topic_id].setdefault(candidate.url, replace(candidate, topic=topic_id))
    out = {}
    for topic_id, by_url in pools.items():
        candidates = list(by_url.values())
        if limit is not None:
            # Newest first, so a smaller prompt is still a predictable one.
            candidates.sort(key=lambda c: (c.published or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
            candidates = candidates[:limit]
        out[topic_id] = candidates
    return out

def _report_sources(results: list[FetchResult]) -> None:
    _print("Sources")
    width = max(len(r.source.id) for r in results)
    for r in results:
        cost = f"  ${r.cost_usd:.4f}" if r.cost_usd else ""
        if r.ok:
            line = f"{len(r.candidates):>4} in window of {r.parsed_count:<4}"
        else:
            line = f"FAIL {r.error}"
        _print(f"  {r.source.id:<{width}}  {r.source.type:<11} {line}  {r.elapsed_seconds:5.1f}s{cost}")
    _print()

def _resolve_images(records: list[Story], cfg: Config) -> None:
    """og:image for every card whose feed carried none. Only cards that made
    the board, never every candidate."""
    images = cfg.settings.images
    # A Google News link's page is Google's redirect, whose og:image is
    # Google's logo; the site shows a placeholder instead.
    missing = [r for r in records if not r["image"] and not is_opaque_interstitial(urlsplit(r["url"]).netloc)]
    if not images.resolve or not missing:
        return

    def find(record: Story) -> None:
        page = pages.fetch(record["url"], cfg.settings.fetch.user_agent, images.timeout_seconds)
        if page and page.image:
            record["image"] = page.image

    with ThreadPoolExecutor(max_workers=max(1, images.workers)) as pool:
        list(pool.map(find, missing))

def cmd_run(args: argparse.Namespace) -> int:
    _print(f"env: {env.load().describe()}")
    cfg = config_module.load()
    settings = cfg.settings
    openrouter.attribute(settings.site.title, settings.site.repo_url)
    if not openrouter.api_key():
        _print("OPENROUTER_API_KEY is not set - every topic needs it to be curated.")
        return EXIT_FAILED

    topics = cfg.enabled_topics
    if args.topic:
        unknown = sorted(set(args.topic) - {t.id for t in topics})
        if unknown:
            _print(f"Unknown or disabled topic: {', '.join(unknown)}")
            return EXIT_FAILED
        topics = [t for t in topics if t.id in args.topic]
    topic_ids = [t.id for t in topics]
    sources = [s for s in cfg.enabled_sources if s.topic in topic_ids or s.topic == SHARED]
    if not sources:
        _print("No enabled sources for these topics.")
        return EXIT_FAILED

    archive = Archive(Path(settings.archive.directory))
    state = State(archive.directory)
    started = utc_now()
    window = resolve(started, state.last_run, settings.window, args.since_hours)
    today = started.astimezone(settings.tz).date().isoformat()
    _print(f"board {today}, window {window.hours:.1f}h ({window.reason})")
    _print(f"topics {', '.join(topic_ids)}; {len(sources)} sources\n")

    results = fetch.fetch_all(sources, settings, window)
    _report_sources(results)
    cost = sum(r.cost_usd for r in results)
    if all(not r.ok for r in results):
        _print("Every source failed. Nothing to curate; the board is unchanged.")
        return EXIT_FAILED

    pools = _pool(results, topic_ids, settings.curation.candidate_limit)
    by_id = {t.id: t for t in cfg.topics}
    tags = curate.tag_vocabulary(archive.tag_counts(), {t: c for t, c in pools.items() if c}, by_id)
    existing_today = archive.load_day(today)

    def run_topic(topic_id: str) -> tuple[curate.TopicResult, list[Story]]:
        topic = by_id[topic_id]
        candidates = pools[topic_id]
        if not candidates:
            return curate.TopicResult(topic=topic, candidates=0), []
        published = archive.recent(topic_id, today, settings.curation.published_days, settings.curation.published_limit)
        result = curate.curate_topic(
            topic,
            candidates,
            published,
            tags,
            settings.models.curate,
            settings.curation.max_attempts,
            settings.curation.repair_rounds,
            settings.curation.timeout_seconds,
        )
        by_url = {c.url: c for c in candidates}
        records = curate.to_records(result, today, by_url, published, existing_today.get(topic_id, []))
        return result, records

    with ThreadPoolExecutor(max_workers=max(1, settings.curation.workers)) as pool:
        outcomes = list(pool.map(run_topic, topic_ids))

    _print("Topics")
    board: dict[str, list[Story]] = {}
    failed = []
    for result, records in outcomes:
        cost += result.cost_usd
        name = f"{result.topic.id:<{max(len(t) for t in topic_ids)}}"
        if result.error:
            failed.append(result.topic.id)
            _print(f"  {name}  FAIL {result.error}")
            continue
        if not result.candidates:
            _print(f"  {name}     0 candidates - board left as it was")
            continue
        if records:
            board[result.topic.id] = records
        updates = sum(1 for r in records if r["is_update"])
        _print(
            f"  {name}  {len(records):>3} published of {result.candidates:<4} candidates"
            f"  {len(result.rejected)} rejected  {updates} updates  {result.calls} calls  ${result.cost_usd:.4f}"
        )
        for story, reason in result.rejected:
            _print(f"      rejected: {reason}: {story.get('title', '')[:90]}")

    attempted = [r for r, _ in outcomes if r.candidates]
    if attempted and len(failed) == len(attempted):
        _print(f"\nOpenRouter cost ${cost:.4f}")
        _print("Every topic failed to curate. The board is unchanged.")
        return EXIT_FAILED

    if settings.curation.cross_topic_review and board:
        # Today's cards of topics this run did not curate: context only.
        fixed = {t: s for t, s in existing_today.items() if t not in board and t in by_id and by_id[t].enabled}
        review = crosstopic.review(
            board, fixed, by_id, settings.models.curate, settings.curation.max_attempts, settings.curation.timeout_seconds
        )
        cost += review.cost_usd
        _print(f"\nCross-topic review  {len(review.removed)} removed  {review.calls} calls  ${review.cost_usd:.4f}")
        if review.error:
            _print(f"  FAIL {review.error}")
        for r in review.removed:
            _print(f"  {r.topic} -> kept in {r.kept_topic}: {r.story['title'][:80]}" + (f" ({r.reason})" if r.reason else ""))
        # A topic the review emptied stays in `board` as []: publishing it
        # clears that topic for today rather than leaving an earlier rerun's
        # cards behind.

    # Only now, so no page is fetched for a card the review removed.
    _resolve_images([r for records in board.values() for r in records], cfg)
    _print(f"\nOpenRouter cost ${cost:.4f}")

    if args.dry_run:
        _print("\nDry run: nothing written. What would have been published:")
        for topic_id, records in board.items():
            _print(f"\n## {by_id[topic_id].name}")
            for r in records:
                flag = " [UPDATE]" if r["is_update"] else ""
                _print(f"{r['rank']:>3}. {r['title']}{flag}\n     {r['url']}")
        return EXIT_PARTIAL if failed else EXIT_OK

    finished = utc_now()
    path = archive.publish(today, board, finished)
    removed = archive.prune(today, settings.archive.keep_days)
    state.record_run(finished, sum(len(r) for r in board.values()), cost)
    out = site.build(cfg, archive, finished)
    _print(f"\nwrote {path}; site in {out}/")
    if removed:
        _print(f"pruned {len(removed)} days older than {settings.archive.keep_days}: {', '.join(removed)}")
    if failed:
        _print(f"\n{len(failed)} topic(s) failed to curate and kept their previous board: {', '.join(failed)}")
        return EXIT_PARTIAL
    return EXIT_OK

# --- the other commands ---------------------------------------------------

def cmd_check(args: argparse.Namespace) -> int:
    cfg = config_module.load()
    by_topic: dict[str, list[Source]] = {}
    for source in cfg.sources:
        by_topic.setdefault(source.topic, []).append(source)
    shared = by_topic.get(SHARED, [])
    if shared:
        _print(f"shared: every topic sees these {sum(s.enabled for s in shared)} enabled sources")
        for s in shared:
            target = s.url or s.google_topic or s.query
            _print(f"  {'+' if s.enabled else '-'} {s.id:<28} {s.type:<11} {target}")
        _print()
    for topic in cfg.topics:
        state = "" if topic.enabled else "  (disabled)"
        brief = "brief" if topic.brief else "no brief"
        _print(f"{topic.id}: {topic.name}, {topic.min_items}-{topic.max_items} items in {topic.language}, {brief}{state}")
        for s in by_topic.get(topic.id, []):
            target = s.url or s.google_topic or s.query
            _print(f"  {'+' if s.enabled else '-'} {s.id:<28} {s.type:<11} {target}")
        if not any(s.enabled for s in by_topic.get(topic.id, []) + shared) and topic.enabled:
            _print("  ! no enabled sources - this topic will never publish")
    _print(f"\nboard columns: {cfg.columns}")
    _print(f"{len(cfg.enabled_sources)} enabled sources in {len(cfg.enabled_topics)} topics. Config OK.")
    return EXIT_OK

def cmd_check_feed(args: argparse.Namespace) -> int:
    settings = config_module.load_settings()
    source = Source(id="check", topic="check", type="rss", name="check", url=args.url)
    now = utc_now()
    window = Window(now - timedelta(days=args.days), now, f"last {args.days} days")
    result = fetch.fetch_source(source, settings, window)
    if not result.ok:
        _print(f"FAIL {result.error}")
        return EXIT_FAILED
    _print(f"{result.parsed_count} items in the feed, {len(result.candidates)} from the last {args.days} days:")
    for c in result.candidates[: args.limit]:
        when = c.published.strftime("%Y-%m-%d %H:%M") if c.published else "no date"
        _print(f"  {when}  {c.title[:100]}")
    if result.candidates:
        span = (now - min(c.published for c in result.candidates if c.published)).total_seconds() / 86400
        _print(f"\nabout {len(result.candidates) / max(span, 1):.1f} items/day")
    return EXIT_OK

def cmd_build_site(args: argparse.Namespace) -> int:
    cfg = config_module.load()
    out = site.build(cfg, Archive(Path(cfg.settings.archive.directory)), utc_now())
    _print(f"site in {out}/")
    return EXIT_OK

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m blastradius", description=__doc__.split("\n\n")[0])
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="fetch, curate and publish today's board")
    run.add_argument("--dry-run", action="store_true", help="curate and print, write nothing")
    run.add_argument("--since-hours", type=float, help="override the window, in hours")
    run.add_argument("--topic", action="append", help="only this topic id (repeatable)")
    run.set_defaults(handler=cmd_run)

    commands.add_parser("check", help="validate config/").set_defaults(handler=cmd_check)

    feed = commands.add_parser("check-feed", help="fetch one RSS/Atom URL")
    feed.add_argument("url")
    feed.add_argument("--days", type=int, default=7)
    feed.add_argument("--limit", type=int, default=20)
    feed.set_defaults(handler=cmd_check_feed)

    commands.add_parser("build-site", help="rebuild public/ from the archive").set_defaults(handler=cmd_build_site)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        return args.handler(args)
    except ConfigError as exc:
        _print(f"Config error: {exc}")
        return EXIT_FAILED
