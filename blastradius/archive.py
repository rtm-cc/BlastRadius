"""The pipeline's memory: one YAML file per board day.

archive/<YYYY>/<MM>/<DD>.yaml holds that day's published stories, per topic.
It is the only generated thing that has to survive, so CI commits it:
tomorrow's run reads it to know what is already published, and the site is
built from it. Everything in public/ can be thrown away and rebuilt.

A file per day rather than one growing file because it keeps every commit's
diff to the day it touched, makes pruning a delete, and makes a same-day
rerun replace that day's topics instead of appending to them. Year and month
folders keep a four-month archive browsable on GitHub. YAML rather than JSON
so a day reads like the board: titles and summaries as plain text, in the
same format as config/.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from .models import Story

# libyaml when the wheel has it (the Linux ones do); a four-month archive is
# several thousand stories and the pure-Python parser is ten times slower.
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_Dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
_DAY_PATH = re.compile(r"^(\d{4})/(\d{2})/(\d{2})\.yaml$")


def dump(data: object) -> str:
    """YAML for the archive and state: block style, readable unicode, keys
    in the order written. safe_dump quotes any string that would otherwise
    read back as a date, number or boolean, so every value round-trips."""
    return yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, default_flow_style=False, width=100)


def load(text: str) -> object:
    return yaml.load(text, Loader=_Loader)


class Archive:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        # A run reads the same day files once per topic; parse each once.
        # Topics are curated in threads, but they only read, and a write
        # replaces the entry.
        self._cache: dict[str, dict[str, list[Story]]] = {}

    def days(self) -> list[str]:
        """Every archived day as YYYY-MM-DD, oldest first."""
        if not self.directory.exists():
            return []
        found = []
        for path in self.directory.glob("*/*/*.yaml"):
            match = _DAY_PATH.match(path.relative_to(self.directory).as_posix())
            if match:
                found.append("-".join(match.groups()))
        return sorted(found)

    def path(self, day: str) -> Path:
        year, month, dom = day.split("-")
        return self.directory / year / month / f"{dom}.yaml"

    def load_day(self, day: str) -> dict[str, list[Story]]:
        """topic id -> that topic's stories in rank order. Empty if the day
        has no file."""
        if day not in self._cache:
            path = self.path(day)
            data = load(path.read_text(encoding="utf-8")) if path.exists() else None
            self._cache[day] = (data or {}).get("topics") or {}
        # A shallow copy, so a caller adding a topic cannot edit the cache.
        return dict(self._cache[day])

    def save_day(self, day: str, topics: dict[str, list[Story]], updated_at: datetime) -> Path:
        payload = {
            "date": day,
            "updated_at": updated_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "topics": {t: topics[t] for t in sorted(topics) if topics[t]},
        }
        path = self.path(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump(payload), encoding="utf-8")
        self._cache[day] = payload["topics"]
        return path

    def publish(self, day: str, by_topic: dict[str, list[Story]], updated_at: datetime) -> Path:
        """Replace the given topics for the day, leaving every other topic as
        it was. A topic that produced nothing this run is simply not passed,
        so a failed or empty curation never blanks a board that has cards."""
        topics = self.load_day(day)
        topics.update(by_topic)
        return self.save_day(day, topics, updated_at)

    def stories(self) -> list[Story]:
        """Every archived story, newest day first, each tagged with its day."""
        out: list[Story] = []
        for day in reversed(self.days()):
            for topic, stories in self.load_day(day).items():
                out += [{**s, "day": day, "topic": topic} for s in stories]
        return out

    def recent(self, topic: str, today: str, days: int, limit: int) -> list[Story]:
        """The topic's stories from the last `days` days before today, newest
        first. Today is left out on purpose: a rerun replaces today's board,
        so its own earlier picks are not "already published"."""
        earliest = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
        out: list[Story] = []
        for day in reversed(self.days()):
            if day >= today:
                continue
            if day < earliest or len(out) >= limit:
                break
            out += [{**s, "day": day} for s in self.load_day(day).get(topic, [])]
        return out[:limit]

    def tag_counts(self) -> Counter[tuple[str, str]]:
        """(topic, tag) -> how many stories carry it, across the archive."""
        counts: Counter[tuple[str, str]] = Counter()
        for day in self.days():
            for topic, stories in self.load_day(day).items():
                for story in stories:
                    for tag in story.get("labels") or []:
                        if str(tag).strip():
                            counts[(topic, str(tag).strip())] += 1
        return counts

    def prune(self, today: str, keep_days: int) -> list[str]:
        """Delete days older than keep_days, and any month or year folder
        that leaves empty. Returns the days removed."""
        earliest = (date.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
        removed = [d for d in self.days() if d < earliest]
        for day in removed:
            path = self.path(day)
            path.unlink()
            self._cache.pop(day, None)
            for folder in (path.parent, path.parent.parent):
                if not any(folder.iterdir()):
                    folder.rmdir()
        return removed
