"""The board, as a static site for GitHub Pages.

A column per topic in the configured layout, yesterday's cards with Full
coverage and Developments, a focus grid per topic, and search across every
archived day. Nothing needs a server: editing is a commit to config/ and
running is CI's job.

Static on purpose: plain files, no framework, no build step, so it keeps
working with nobody maintaining it. What gets written to public/:

    index.html        the shell, with the topics, layout and day list inline
    style.css, app.js authored as real files in assets/
    days/<day>.json   one board day, each story carrying its cluster's
                      timeline so Developments needs no second request
    search.json       every story, compact, fetched on the first search only
    feed.xml, feed    RSS 2.0 feed of curated stories for RSS readers

The archive is several megabytes, so the page loads one day at a time
instead of embedding everything. Each JSON file is also written gzipped,
which hosts that look for precompressed files serve as-is.

Feed content is attacker-influenced - anyone who can publish to a feed we
read controls these strings - so the script puts every value into the DOM
through textContent, never innerHTML, and rejects any link whose scheme is
not http(s): escaping a javascript: URL still leaves a working javascript:
URL.
"""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import shutil
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from email.utils import format_datetime
from pathlib import Path

from .archive import Archive
from .config import Config, ConfigError
from .models import Story

ASSETS = Path(__file__).parent / "assets"
SAFE_SCHEMES = ("https://", "http://")
# What search.json keeps of each summary. Enough to match on and to read.
SEARCH_SUMMARY_CHARS = 400
# An image on this many different stories is a logo, not a picture of any of
# them: Google News' own logo is the og:image of every news.google.com link,
# and some publishers use one default image site-wide. The card's gradient
# placeholder is better than the same logo thirty times.
GENERIC_IMAGE_STORIES = 5


def _safe_url(url: str | None) -> str:
    return url if url and url.lower().startswith(SAFE_SCHEMES) else ""


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if path.suffix in (".json", ".xml") or path.name in ("feed", "rss"):
        # mtime=0 so an unchanged day gzips to identical bytes every build.
        path.with_name(path.name + ".gz").write_bytes(gzip.compress(content.encode("utf-8"), 9, mtime=0))


def _event(story: Story) -> dict:
    return {
        "id": story["id"],
        "day": story["day"],
        "topic": story["topic"],
        "title": story["title"],
        "url": _safe_url(story["url"]),
        "isUpdate": bool(story.get("is_update")),
        "text": story.get("what_changed") or story.get("summary") or "",
    }


def _card(story: Story, timeline: list[dict], generic_images: set[str]) -> dict:
    image = story.get("image") or ""
    return {
        "id": story["id"],
        "topic": story["topic"],
        "rank": story.get("rank", 0),
        "title": story["title"],
        "summary": story.get("summary", ""),
        "url": _safe_url(story["url"]),
        "image": "" if image in generic_images else _safe_url(image),
        "sources": story.get("sources") or [],
        "labels": story.get("labels") or [],
        "rationale": story.get("rationale", ""),
        "isUpdate": bool(story.get("is_update")),
        "whatChanged": story.get("what_changed") or "",
        "published": story.get("published"),
        "coverage": [
            {**c, "url": _safe_url(c.get("url"))} for c in story.get("coverage") or [] if _safe_url(c.get("url"))
        ],
        # Only worth sending when there is more than this one event.
        "timeline": timeline if len(timeline) > 1 else [],
    }


def build(config: Config, archive: Archive, generated_at: datetime) -> Path:
    settings = config.settings.site
    out = Path(settings.directory)
    # The directory is wiped first, so it had better not be the repo.
    if Path.cwd().resolve().is_relative_to(out.resolve()):
        raise ConfigError(
            f"site.directory '{settings.directory}' contains the working directory; refusing to delete it."
        )
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    stories = archive.stories()
    clusters: dict[str, list[dict]] = defaultdict(list)
    for story in stories:
        clusters[story.get("cluster") or story["id"]].append(_event(story))
    for events in clusters.values():
        events.sort(key=lambda e: e["day"])

    image_use = Counter(s["image"] for s in stories if s.get("image"))
    generic = {image for image, uses in image_use.items() if uses >= GENERIC_IMAGE_STORIES}

    by_day: dict[str, list[dict]] = defaultdict(list)
    for story in stories:
        by_day[story["day"]].append(_card(story, clusters[story.get("cluster") or story["id"]], generic))
    for day, cards in by_day.items():
        _write(out / "days" / f"{day}.json", _json({"date": day, "stories": cards}))

    _write(
        out / "search.json",
        _json(
            [
                {
                    "id": s["id"],
                    "day": s["day"],
                    "topic": s["topic"],
                    "title": s["title"],
                    "summary": s.get("summary", "")[:SEARCH_SUMMARY_CHARS],
                    "url": _safe_url(s["url"]),
                    "labels": s.get("labels") or [],
                    "sources": s.get("sources") or [],
                }
                for s in stories
            ]
        ),
    )

    style = (ASSETS / "style.css").read_text(encoding="utf-8")
    script = (ASSETS / "app.js").read_text(encoding="utf-8")
    _write(out / "style.css", style)
    _write(out / "app.js", script)
    # GitHub Pages deployed from a branch runs Jekyll, which drops files it
    # does not like; this opts out. Deployed from Actions it is ignored.
    _write(out / ".nojekyll", "")
    # SVG for browser tabs; the PNG is for phone home screens, where iOS
    # does not take SVG and rounds the corners itself.
    for icon in ("favicon.svg", "apple-touch-icon.png"):
        shutil.copyfile(ASSETS / icon, out / icon)
    # A browser must never pair new HTML with cached old CSS or JS.
    digest = hashlib.sha256((style + script).encode("utf-8"))
    for icon in ("favicon.svg", "apple-touch-icon.png"):
        digest.update((ASSETS / icon).read_bytes())
    version = digest.hexdigest()[:8]

    boot = {
        "title": settings.title,
        "timezone": config.settings.timezone,
        "dateFormat": settings.date_format,
        "coloredTags": settings.colored_tags,
        "generatedAt": generated_at.isoformat(timespec="seconds"),
        "repoUrl": _safe_url(settings.repo_url),
        "days": sorted(by_day),
        "topics": [{"id": t.id, "name": t.name, "color": t.color, "enabled": t.enabled} for t in config.topics],
        # Retired topics still have archived days; show them after the rest.
        "columns": config.columns
        + [[t] for t in sorted({s["topic"] for s in stories} - {i for c in config.columns for i in c})],
    }
    wallpaper = ""
    if settings.background:
        image = Path(settings.background)
        data = image.read_bytes()
        name = f"background{image.suffix.lower()}"
        (out / name).write_bytes(data)
        wallpaper = f"{name}?v={hashlib.sha256(data).hexdigest()[:8]}"

    feed_xml = _rss(config, stories, generic, generated_at)
    _write(out / "feed.xml", feed_xml)
    _write(out / "feed", feed_xml)
    _write(out / "rss.xml", feed_xml)
    _write(out / "rss", feed_xml)

    _write(
        out / "index.html",
        _page(
            settings.title,
            boot,
            version,
            wallpaper,
            _credit(settings.author, settings.author_url),
            description=settings.description,
            repo_url=settings.repo_url or "https://github.com/rtm-cc/BlastRadius",
            rss_url="feed.xml",
        ),
    )
    return out


def _embed(data: object) -> str:
    """JSON safe inside a <script> element: escaping `<` is what stops a
    `</script>` in any string from ending the element early."""
    return _json(data).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _credit(author: str, url: str) -> str:
    """ "by <author>" beside the title; a link when the URL is http(s)."""
    if not author:
        return ""
    e = html.escape
    href = _safe_url(url)
    if href:
        return f'<a class="credit" href="{e(href)}" target="_blank" rel="noopener">by {e(author)}</a>'
    return f'<span class="credit">by {e(author)}</span>'


def _description(desc: str) -> str:
    """ "A small tagline/description under the title in the header."""
    if not desc:
        return ""
    return f'<p class="brand-desc">{html.escape(desc)}</p>'


def _github_link(url: str) -> str:
    """A GitHub icon link pointing to the repository."""
    href = _safe_url(url) or "https://github.com/rtm-cc/BlastRadius"
    e = html.escape
    return (
        f'<a href="{e(href)}" class="icon-btn github-link" target="_blank" rel="noopener noreferrer" '
        f'aria-label="GitHub repository" title="GitHub repository">'
        f'<svg class="github-icon" viewBox="0 0 16 16" aria-hidden="true">'
        f'<path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>'
        f"</svg></a>"
    )


def _rss_link(url: str = "feed.xml") -> str:
    """An RSS icon link pointing to the RSS feed."""
    e = html.escape
    href = url if url in ("feed.xml", "feed", "rss.xml", "rss") or url.startswith(SAFE_SCHEMES) else "feed.xml"
    return (
        f'<a href="{e(href)}" class="icon-btn rss-link" target="_blank" rel="alternate" '
        f'aria-label="RSS Feed" title="RSS Feed (/feed)">'
        f'<svg class="rss-icon" viewBox="0 0 16 16" aria-hidden="true">'
        f'<path fill-rule="evenodd" d="M2.002 2.725a.75.75 0 0 1 .797-.699C8.79 2.42 13.58 7.21 13.974 13.201a.75.75 0 0 1-1.497.098 10.502 10.502 0 0 0-9.776-9.776.75.75 0 0 1-.7-.798zM2 8.75a.75.75 0 0 1 .75-.75 5.5 5.5 0 0 1 5.5 5.5.75.75 0 0 1-1.5 0 4 4 0 0 0-4-4 .75.75 0 0 1-.75-.75zM3.5 14a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0z"/>'
        f"</svg></a>"
    )


def _page(
    title: str,
    boot: dict,
    version: str,
    wallpaper: str = "",
    credit: str = "",
    description: str = "",
    repo_url: str = "",
    rss_url: str = "feed.xml",
) -> str:
    e = html.escape
    # The name is ours (background.<ext>?v=<hash>), never config text, so it
    # is safe inside url(). The stylesheet does the rest.
    body = f'<body data-wallpaper="true" style="--wallpaper-image: url(\'{e(wallpaper)}\')">' if wallpaper else "<body>"
    desc_html = _description(description)
    github_btn = _github_link(repo_url)
    rss_btn = _rss_link(rss_url)
    meta_desc = f'<meta name="description" content="{e(description)}">\n' if description else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="color-scheme" content="light dark">
{meta_desc}<title>{e(title)}</title>
<link rel="alternate" type="application/rss+xml" title="{e(title)}" href="feed.xml">
<link rel="alternate" type="application/rss+xml" title="{e(title)} (/feed)" href="feed">
<link rel="icon" type="image/svg+xml" href="favicon.svg?v={version}">
<link rel="apple-touch-icon" href="apple-touch-icon.png?v={version}">
<meta name="theme-color" content="#2a0a10">
<link rel="stylesheet" href="style.css?v={version}">
<script>
  try {{
    var urlParams = new URLSearchParams(window.location.search);
    var urlTheme = urlParams.get("theme");
    var theme = (urlTheme === "light" || urlTheme === "dark") ? urlTheme : localStorage.getItem("theme");
    if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
  }} catch (_) {{}}
</script>
</head>
{body}
<a class="skip" href="#board">Skip to stories</a>
<header class="bar">
  <div class="brand-block">
    <div class="brand-wrap">
      <h1 class="brand">
        <a href="./" id="home" class="brand-link">
          <img src="favicon.svg?v={version}" alt="" class="brand-icon" width="28" height="28">
          <span>{e(title)}</span>
        </a>
      </h1>
      {credit}
    </div>
    {desc_html}
  </div>
  <nav class="days" aria-label="Board day">
    <button type="button" id="prev" class="icon-btn" aria-label="Previous day">
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 5 8l5 5"/></svg>
    </button>
    <label class="day-pick">
      <span id="day-label"></span>
      <input type="date" id="day" aria-label="Jump to a day">
    </label>
    <button type="button" id="next" class="icon-btn" aria-label="Next day">
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3 5 5-5 5"/></svg>
    </button>
    <button type="button" id="latest" class="text-btn">Latest</button>
  </nav>
  <div class="bar-actions">
    <form class="search" id="search-form" role="search">
      <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="6"/><path d="M13.5 13.5 18 18"/></svg>
      <input type="search" id="q" placeholder="Search all stories" autocomplete="off" aria-label="Search stories">
      <kbd>/</kbd>
    </form>
    <button type="button" id="theme-toggle" class="icon-btn theme-toggle" aria-label="Switch theme" title="Switch theme">
      <svg class="theme-icon-sun" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="3.2"/>
        <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1"/>
      </svg>
      <svg class="theme-icon-moon" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M13.2 10.2A6 6 0 1 1 5.8 2.8a6.5 6.5 0 0 0 7.4 7.4Z"/>
      </svg>
    </button>
    {rss_btn}
    {github_btn}
  </div>
</header>
<p id="status" class="status" role="status"></p>
<main id="board" tabindex="-1"></main>
<noscript><p class="empty">This board needs JavaScript. The same stories are in archive/ in the repository, one YAML file per day.</p></noscript>
<script type="application/json" id="boot">{_embed(boot)}</script>
<script src="app.js?v={version}"></script>
</body>
</html>
"""


def _xml(text: object) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _parse_story_date(published: str | None, day: str) -> datetime:
    if published:
        try:
            dt = datetime.fromisoformat(published)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except (ValueError, TypeError):
            pass
    try:
        d = date.fromisoformat(day)
        return datetime(d.year, d.month, d.day, 7, 0, 0, tzinfo=UTC)
    except (ValueError, TypeError):
        return datetime.now(UTC)


def _story_sort_key(story: Story) -> tuple:
    dt = _parse_story_date(story.get("published"), story.get("day", ""))
    rank = story.get("rank", 99)
    return (story.get("day", ""), dt.isoformat(), -rank)


def _rss_item(story: Story, topic_names: dict[str, str], generic_images: set[str], base_url: str) -> str:
    guid = story["id"]
    title = _xml(story.get("title", ""))
    url = _safe_url(story.get("url")) or f"{base_url}/#{guid}"
    dt = _parse_story_date(story.get("published"), story.get("day", ""))
    pub_date = format_datetime(dt)

    topic_id = story.get("topic", "")
    topic_name = topic_names.get(topic_id, topic_id.replace("_", " ").title())
    labels = story.get("labels") or []

    categories = [f"      <category>{_xml(topic_name)}</category>"]
    for label in labels:
        if label:
            categories.append(f"      <category>{_xml(str(label))}</category>")
    categories_xml = "\n".join(categories)

    image = story.get("image") or ""
    safe_image = _safe_url(image) if image not in generic_images else ""
    enclosure_xml = ""
    if safe_image:
        mime = (
            "image/png"
            if ".png" in safe_image.lower()
            else ("image/webp" if ".webp" in safe_image.lower() else "image/jpeg")
        )
        enclosure_xml = f'      <enclosure url="{_xml(safe_image)}" length="0" type="{mime}"/>\n'

    summary = story.get("summary") or ""
    what_changed = story.get("what_changed") or ""
    is_update = bool(story.get("is_update"))
    coverage = story.get("coverage") or []
    sources = story.get("sources") or []

    desc_parts = []
    if safe_image:
        desc_parts.append(
            f'<p><img src="{html.escape(safe_image)}" alt="{html.escape(story.get("title", ""))}" style="max-width:100%;height:auto;border-radius:6px;" /></p>'
        )
    if summary:
        desc_parts.append(f"<p>{html.escape(summary)}</p>")
    if is_update and what_changed:
        desc_parts.append(f"<p><strong>Update:</strong> {html.escape(what_changed)}</p>")
    if coverage:
        cov_items = []
        for c in coverage:
            cov_url = _safe_url(c.get("url"))
            cov_title = html.escape(c.get("title", ""))
            cov_src = html.escape(c.get("source", ""))
            if cov_url and cov_title:
                prefix = f"{cov_src}: " if cov_src else ""
                cov_items.append(
                    f'<li><a href="{html.escape(cov_url)}" target="_blank" rel="noopener">{prefix}{cov_title}</a></li>'
                )
        if cov_items:
            desc_parts.append(f"<p><strong>Related Coverage:</strong></p><ul>{''.join(cov_items)}</ul>")

    meta_parts = [f"Topic: {html.escape(topic_name)}"]
    if sources:
        meta_parts.append(f"Sources: {html.escape(', '.join(sources))}")
    meta_html = " | ".join(meta_parts)
    desc_parts.append(
        f'<p style="color:#666;font-size:0.9em;"><small>{meta_html} | <a href="{html.escape(url)}">Original Article</a> | <a href="{html.escape(base_url)}/">Blast Radius</a></small></p>'
    )

    desc_html = "\n".join(desc_parts)
    desc_cdata = desc_html.replace("]]>", "]]]]><![CDATA[>")

    return (
        f"    <item>\n"
        f"      <title>{title}</title>\n"
        f"      <link>{_xml(url)}</link>\n"
        f'      <guid isPermaLink="false">{_xml(guid)}</guid>\n'
        f"      <pubDate>{pub_date}</pubDate>\n"
        f"{categories_xml}\n"
        f"{enclosure_xml}"
        f"      <description><![CDATA[{desc_cdata}]]></description>\n"
        f"    </item>"
    )


def _rss(
    config: Config,
    stories: list[Story],
    generic_images: set[str],
    generated_at: datetime,
) -> str:
    settings = config.settings.site
    title = _xml(settings.title)
    description = _xml(settings.description)
    base_url = (settings.site_url or "https://news.rtm.cc").rstrip("/")
    site_link = _xml(base_url + "/")
    feed_link = _xml(base_url + "/feed")
    last_build = format_datetime(generated_at.astimezone(UTC))

    topic_names = {t.id: t.name for t in config.topics}
    available_days = sorted({s["day"] for s in stories if s.get("day")})
    feed_days = settings.feed_days if settings.feed_days > 0 else 3
    cutoff_days = set(available_days[-feed_days:])
    filtered = [s for s in stories if s.get("day") in cutoff_days]
    recent_stories = sorted(filtered, key=_story_sort_key, reverse=True)
    items_xml = "\n".join(_rss_item(s, topic_names, generic_images, base_url) for s in recent_stories)

    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        f"  <channel>\n"
        f"    <title>{title}</title>\n"
        f"    <link>{site_link}</link>\n"
        f"    <description>{description}</description>\n"
        f"    <language>en</language>\n"
        f"    <lastBuildDate>{last_build}</lastBuildDate>\n"
        f'    <atom:link href="{feed_link}" rel="self" type="application/rss+xml"/>\n'
        f"    <generator>BlastRadius</generator>\n"
        f"{items_xml}\n"
        f"  </channel>\n"
        f"</rss>\n"
    )
