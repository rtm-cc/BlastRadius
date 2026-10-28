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
from datetime import datetime
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
    if path.suffix == ".json":
        # mtime=0 so an unchanged day gzips to identical bytes every build.
        path.with_name(path.name + ".gz").write_bytes(gzip.compress(content.encode("utf-8"), 9, mtime=0))


def _event(story: Story) -> dict:
    return {
        "id": story["id"],
        "day": story["day"],
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
        raise ConfigError(f"site.directory '{settings.directory}' contains the working directory; refusing to delete it.")
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
        "topics": [
            {"id": t.id, "name": t.name, "color": t.color, "enabled": t.enabled}
            for t in config.topics
        ],
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

    _write(out / "index.html", _page(settings.title, boot, version, wallpaper, _credit(settings.author, settings.author_url)))
    return out


def _embed(data: object) -> str:
    """JSON safe inside a <script> element: escaping `<` is what stops a
    `</script>` in any string from ending the element early."""
    return _json(data).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _credit(author: str, url: str) -> str:
    """"by <author>" beside the title; a link when the URL is http(s)."""
    if not author:
        return ""
    e = html.escape
    href = _safe_url(url)
    if href:
        return f'<a class="credit" href="{e(href)}" target="_blank" rel="noopener">by {e(author)}</a>'
    return f'<span class="credit">by {e(author)}</span>'


def _page(title: str, boot: dict, version: str, wallpaper: str = "", credit: str = "") -> str:
    e = html.escape
    # The name is ours (background.<ext>?v=<hash>), never config text, so it
    # is safe inside url(). The stylesheet does the rest.
    body = f'<body data-wallpaper="true" style="--wallpaper-image: url(\'{e(wallpaper)}\')">' if wallpaper else "<body>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="color-scheme" content="light dark">
<title>{e(title)}</title>
<link rel="icon" type="image/svg+xml" href="favicon.svg?v={version}">
<link rel="apple-touch-icon" href="apple-touch-icon.png?v={version}">
<meta name="theme-color" content="#2a0a10">
<link rel="stylesheet" href="style.css?v={version}">
</head>
{body}
<a class="skip" href="#board">Skip to stories</a>
<header class="bar">
  <div class="brand-wrap">
    <h1 class="brand"><a href="./" id="home">{e(title)}</a></h1>
    {credit}
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
  <form class="search" id="search-form" role="search">
    <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="6"/><path d="M13.5 13.5 18 18"/></svg>
    <input type="search" id="q" placeholder="Search every day" autocomplete="off" aria-label="Search stories">
    <kbd>/</kbd>
  </form>
</header>
<p id="status" class="status" role="status"></p>
<main id="board" tabindex="-1"></main>
<noscript><p class="empty">This board needs JavaScript. The same stories are in archive/ in the repository, one YAML file per day.</p></noscript>
<script type="application/json" id="boot">{_embed(boot)}</script>
<script src="app.js?v={version}"></script>
</body>
</html>
"""
