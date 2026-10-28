"""Loading and validating the files under config/.

These files are the whole configuration - there is no settings page any
more - so every problem found here is reported as a plain sentence naming the
file and the entry at fault, and CI runs `check` on every push so a bad edit
fails there rather than costing a morning's board.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .models import SOURCE_TYPES, Source, Topic

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

_ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")
# config/sources/shared.yaml: sources that feed every topic. Its sources
# carry this as their topic, so it can never be a topic id itself.
SHARED = "shared"
WEB_SEARCH_ENGINES = {"native", "exa", "firecrawl", "parallel", "perplexity"}
DATE_FORMATS = {"dmy", "mdy", "ymd"}
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


class ConfigError(Exception):
    """Something in config/ is wrong and a human has to fix it."""


@dataclass(frozen=True)
class ModelSettings:
    curate: str = "deepseek/deepseek-v4-flash"
    search: str = "deepseek/deepseek-v4-flash"


@dataclass(frozen=True)
class FetchSettings:
    timeout_seconds: float = 45
    retries: int = 2
    max_workers: int = 8
    user_agent: str = "top10fromyesterday/0.2 (+RSS reader)"


@dataclass(frozen=True)
class WindowSettings:
    default_hours: float = 24
    min_hours: float = 6
    max_hours: float = 96
    overlap_minutes: float = 30


@dataclass(frozen=True)
class CurationSettings:
    workers: int = 4
    max_attempts: int = 3
    repair_rounds: int = 1
    timeout_seconds: float = 600
    published_days: int = 30
    published_limit: int = 150
    candidate_limit: int | None = None
    cross_topic_review: bool = True


@dataclass(frozen=True)
class WebSearchSettings:
    max_results: int = 5
    timeout_seconds: float = 360
    verify_timeout_seconds: float = 30


@dataclass(frozen=True)
class ImageSettings:
    resolve: bool = True
    timeout_seconds: float = 30
    workers: int = 8


@dataclass(frozen=True)
class ArchiveSettings:
    directory: str = "archive"
    keep_days: int = 120


@dataclass(frozen=True)
class SiteSettings:
    directory: str = "public"
    title: str = "Top 10 from yesterday"
    repo_url: str = ""
    date_format: str = "dmy"
    colored_tags: bool = True
    # "by <author>" beside the title, linking to author_url when it is set.
    author: str = ""
    author_url: str = ""
    # A path relative to config/ in settings.yaml; load_settings() makes it
    # absolute, so the site build does not need to know where config/ is.
    background: str = ""


@dataclass(frozen=True)
class Settings:
    timezone: str = "UTC"
    models: ModelSettings = field(default_factory=ModelSettings)
    fetch: FetchSettings = field(default_factory=FetchSettings)
    window: WindowSettings = field(default_factory=WindowSettings)
    curation: CurationSettings = field(default_factory=CurationSettings)
    web_search: WebSearchSettings = field(default_factory=WebSearchSettings)
    images: ImageSettings = field(default_factory=ImageSettings)
    archive: ArchiveSettings = field(default_factory=ArchiveSettings)
    site: SiteSettings = field(default_factory=SiteSettings)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@dataclass(frozen=True)
class Config:
    settings: Settings
    topics: list[Topic]
    # Desktop columns, left to right, each one or two topic ids. Normalised:
    # every enabled topic appears exactly once.
    columns: list[list[str]]
    sources: list[Source]

    def topic(self, topic_id: str) -> Topic:
        return next(t for t in self.topics if t.id == topic_id)

    @property
    def enabled_topics(self) -> list[Topic]:
        return [t for t in self.topics if t.enabled]

    @property
    def enabled_sources(self) -> list[Source]:
        enabled = {t.id for t in self.enabled_topics}
        return [s for s in self.sources if s.enabled and (s.topic in enabled or s.topic == SHARED)]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"{path} is missing.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level.")
    return data


def _section(cls: type, raw: Any, where: str) -> Any:
    """Build one settings dataclass, naming any key it does not have."""
    if raw is None:
        return cls()
    if not isinstance(raw, dict):
        raise ConfigError(f"settings.yaml: '{where}' must be a mapping.")
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(
            f"settings.yaml: unknown key {', '.join(f'{where}.{k}' for k in unknown)}. "
            f"Known keys: {', '.join(sorted(known))}."
        )
    return cls(**raw)


def load_settings(config_dir: Path | None = None) -> Settings:
    config_dir = config_dir or CONFIG_DIR
    raw = _read_yaml(config_dir / "settings.yaml")
    sections = {
        "models": ModelSettings,
        "fetch": FetchSettings,
        "window": WindowSettings,
        "curation": CurationSettings,
        "web_search": WebSearchSettings,
        "images": ImageSettings,
        "archive": ArchiveSettings,
        "site": SiteSettings,
    }
    unknown = sorted(set(raw) - set(sections) - {"timezone"})
    if unknown:
        raise ConfigError(f"settings.yaml: unknown section {', '.join(unknown)}.")

    settings = Settings(
        timezone=str(raw.get("timezone") or "UTC"),
        **{name: _section(cls, raw.get(name), name) for name, cls in sections.items()},
    )

    try:
        settings.tz
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(
            f"settings.yaml: timezone '{settings.timezone}' is unknown. "
            "Use an IANA name such as Europe/Lisbon."
        ) from exc
    if settings.window.min_hours > settings.window.max_hours:
        raise ConfigError("settings.yaml: window.min_hours is above window.max_hours.")
    if settings.curation.published_days >= settings.archive.keep_days:
        raise ConfigError(
            "settings.yaml: curation.published_days must be below archive.keep_days - "
            "'already published' is read from the archive, so it cannot reach "
            "further back than the archive keeps."
        )
    if settings.site.date_format not in DATE_FORMATS:
        raise ConfigError(
            f"settings.yaml: site.date_format '{settings.site.date_format}' is unknown. "
            f"Use one of: {', '.join(sorted(DATE_FORMATS))}."
        )
    if settings.site.background:
        image = (config_dir / settings.site.background).resolve()
        if image.suffix.lower() not in IMAGE_TYPES:
            raise ConfigError(
                f"settings.yaml: site.background must be one of {', '.join(sorted(IMAGE_TYPES))}."
            )
        if not image.is_file():
            raise ConfigError(f"settings.yaml: site.background '{settings.site.background}' is not a file in {config_dir}.")
        settings = replace(settings, site=replace(settings.site, background=str(image)))
    return settings


def load_topics(config_dir: Path) -> tuple[list[Topic], list[list[str]]]:
    path = config_dir / "topics.yaml"
    raw = _read_yaml(path)
    entries = raw.get("topics")
    if not entries or not isinstance(entries, list):
        raise ConfigError(f"{path}: 'topics' must be a non-empty list.")

    topics: list[Topic] = []
    seen: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        where = f"{path} entry #{position}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} is not a mapping.")
        topic_id = str(entry.get("id") or "").strip()
        if not _ID.match(topic_id):
            raise ConfigError(f"{where}: id '{topic_id}' must be snake_case.")
        if topic_id in seen:
            raise ConfigError(f"{where}: id '{topic_id}' is used twice.")
        if topic_id == SHARED:
            raise ConfigError(f"{where}: '{SHARED}' is reserved for sources/shared.yaml; pick another id.")
        seen.add(topic_id)
        if not str(entry.get("name") or "").strip():
            raise ConfigError(f"{where} ('{topic_id}') is missing 'name'.")

        min_items = int(entry.get("min_items", 0))
        max_items = int(entry.get("max_items", 15))
        if max_items < 1 or min_items < 0 or min_items > max_items:
            raise ConfigError(
                f"{where} ('{topic_id}'): need 0 <= min_items <= max_items and max_items >= 1."
            )
        color = entry.get("color")
        if color is not None and not (isinstance(color, int) and 0 <= color < 360):
            raise ConfigError(f"{where} ('{topic_id}'): color must be a hue from 0 to 359.")

        brief_path = config_dir / "briefs" / f"{topic_id}.md"
        brief = brief_path.read_text(encoding="utf-8").strip() if brief_path.exists() else ""

        topics.append(
            Topic(
                id=topic_id,
                name=str(entry["name"]).strip(),
                language=str(entry.get("language") or "en").strip(),
                min_items=min_items,
                max_items=max_items,
                color=color,
                enabled=bool(entry.get("enabled", True)),
                brief=brief,
            )
        )

    briefs_dir = config_dir / "briefs"
    if briefs_dir.exists():
        orphans = sorted(p.stem for p in briefs_dir.glob("*.md") if p.stem not in seen)
        if orphans:
            raise ConfigError(
                f"{briefs_dir}: {', '.join(o + '.md' for o in orphans)} "
                "matches no topic id. Rename it, or delete it."
            )

    enabled = [t.id for t in topics if t.enabled]
    if not enabled:
        raise ConfigError(f"{path}: every topic is disabled, nothing to curate.")
    return topics, _columns(raw.get("board") or {}, enabled, path)


def _columns(board: dict[str, Any], enabled: list[str], path: Path) -> list[list[str]]:
    """The configured layout, plus any enabled topic it forgot."""
    columns: list[list[str]] = []
    placed: set[str] = set()
    for column in board.get("columns") or []:
        ids = column if isinstance(column, list) else [column]
        if len(ids) > 2:
            raise ConfigError(f"{path}: board column {ids} holds more than two topics.")
        for topic_id in ids:
            if topic_id not in enabled:
                raise ConfigError(
                    f"{path}: board column names '{topic_id}', which is not an enabled topic."
                )
            if topic_id in placed:
                raise ConfigError(f"{path}: '{topic_id}' appears in two board columns.")
            placed.add(topic_id)
        if ids:
            columns.append(list(ids))
    columns += [[t] for t in enabled if t not in placed]
    return columns


def load_sources(config_dir: Path, topics: list[Topic]) -> list[Source]:
    """config/sources/shared.yaml, then every <topic id>.yaml in topics.yaml
    order.

    One file per topic, and the file name is the topic: an entry needs no
    `topic:` line, and adding a topic's sources is adding a file. A file
    named after no topic is an error rather than skipped, so a typo in a
    file name cannot quietly take a topic's sources off the board.

    shared.yaml is for a board whose topics are slices of one subject:
    every security feed carries breaches, vulnerabilities and fraud alike.
    Its sources are fetched once and offered to every topic, and each
    topic's brief picks its slice.
    """
    directory = config_dir / "sources"
    if not directory.is_dir():
        raise ConfigError(f"{directory} is missing. It holds one <topic id>.yaml per topic.")
    files = {p.stem: p for p in directory.iterdir() if p.suffix in (".yaml", ".yml")}
    topic_ids = [t.id for t in topics]
    orphans = sorted(set(files) - set(topic_ids) - {SHARED})
    if orphans:
        raise ConfigError(
            f"{directory}: {', '.join(files[o].name for o in orphans)} matches no topic id in "
            f"topics.yaml. Rename it to one of: {', '.join([SHARED, *topic_ids])}."
        )

    sources: list[Source] = []
    seen: dict[str, str] = {}
    # shared.yaml first: its sources feed every topic, and when two sources
    # carry one article, the one listed first names it.
    for topic_id in [SHARED, *topic_ids]:
        if topic_id in files:
            sources += _load_topic_sources(files[topic_id], topic_id, seen)
    if not sources:
        raise ConfigError(f"{directory}: no file lists any source.")
    return sources


def _load_topic_sources(path: Path, topic_id: str, seen: dict[str, str]) -> list[Source]:
    raw = _read_yaml(path)
    entries = raw.get("sources")
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise ConfigError(f"{path}: 'sources' must be a list.")

    known = {f.name for f in fields(Source)}
    sources: list[Source] = []
    for position, entry in enumerate(entries, start=1):
        where = f"{path} entry #{position}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} is not a mapping.")
        source_id = str(entry.get("id") or "").strip()
        if not _ID.match(source_id):
            raise ConfigError(f"{where}: id '{source_id}' must be snake_case.")
        where = f"{where} ('{source_id}')"
        # Unique across every file: the id is how the run report names it.
        if source_id in seen:
            raise ConfigError(f"{where}: id is already used in {seen[source_id]}.")
        seen[source_id] = path.name

        unknown = sorted(set(entry) - known)
        if unknown:
            raise ConfigError(f"{where}: unknown field {', '.join(unknown)}.")
        if entry.get("topic", topic_id) != topic_id:
            raise ConfigError(
                f"{where}: topic '{entry['topic']}' contradicts the file, which is {topic_id}'s. "
                "Move the entry to that topic's file, or drop the topic line."
            )
        entry = {**entry, "topic": topic_id}
        source_type = entry.get("type")
        if source_type not in SOURCE_TYPES:
            raise ConfigError(
                f"{where}: type '{source_type}' is unknown. Use one of: {', '.join(SOURCE_TYPES)}."
            )
        if not str(entry.get("name") or "").strip():
            raise ConfigError(f"{where} is missing 'name'.")

        values = {k: v for k, v in entry.items() if v is not None}
        values["id"] = source_id
        values["name"] = str(values["name"]).strip()
        for key in ("url", "google_topic", "google_section", "query", "engine", "notes"):
            if key in values:
                values[key] = str(values[key]).strip()
        source = Source(**values)
        _check_source(source, where)
        sources.append(source)

    return sources


def _check_source(source: Source, where: str) -> None:
    for key in ("max_age_hours", "max_items", "max_results"):
        value = getattr(source, key)
        if value is not None and (not isinstance(value, (int, float)) or value <= 0):
            raise ConfigError(f"{where}: {key} must be a positive number.")

    if source.type == "rss":
        if not source.url.startswith(("http://", "https://")):
            raise ConfigError(f"{where}: an rss source needs a url starting with http(s)://.")
    elif source.type == "google_news":
        if bool(source.google_topic) == bool(source.query):
            raise ConfigError(
                f"{where}: a google_news source needs exactly one of google_topic or query."
            )
    elif source.type == "web_search":
        if not source.query:
            raise ConfigError(f"{where}: a web_search source needs a query.")
        if source.engine and source.engine not in WEB_SEARCH_ENGINES:
            raise ConfigError(
                f"{where}: engine '{source.engine}' is unknown. "
                f"Use one of: {', '.join(sorted(WEB_SEARCH_ENGINES))}."
            )


def load(config_dir: Path | None = None) -> Config:
    config_dir = config_dir or CONFIG_DIR
    settings = load_settings(config_dir)
    topics, columns = load_topics(config_dir)
    sources = load_sources(config_dir, topics)
    return Config(settings=settings, topics=topics, columns=columns, sources=sources)
