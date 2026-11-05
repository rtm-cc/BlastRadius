"""When the last run read its sources, which is where the next run's window
starts - and where the window of today's first run started, which is where a
rerun of today starts.

It lives in archive/, beside the day files, because that is what CI commits:
anywhere else a fresh checkout would never see the previous run, believe
every run was the first, and fall back to the default window.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .archive import dump, load

STATE_FILENAME = "state.yaml"
# Before the archive moved to YAML. Read if it is all there is; the next
# run writes state.yaml and removes it.
LEGACY_FILENAME = "state.json"


class State:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / STATE_FILENAME

    def _read(self) -> dict:
        try:
            if self.path.exists():
                data = load(self.path.read_text(encoding="utf-8"))
            elif (self.directory / LEGACY_FILENAME).exists():
                data = json.loads((self.directory / LEGACY_FILENAME).read_text(encoding="utf-8"))
            else:
                return {}
        except (yaml.YAMLError, json.JSONDecodeError, OSError):
            # A corrupt state file must not block a run; the window falls
            # back to its default.
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def last_run(self) -> datetime | None:
        raw = self._read().get("last_run_utc")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def board_since(self, day: str) -> datetime | None:
        """Where the window of `day`'s first run started, if a run already
        published `day`. A rerun starts there too: it replaces the day's
        columns, so a window of only the hours since the first run would
        drop everything the first run had found."""
        data = self._read()
        if data.get("board_day") != day or not data.get("board_since"):
            return None
        try:
            parsed = datetime.fromisoformat(str(data["board_since"]))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def record_run(
        self, fetched_at: datetime, stories: int, cost_usd: float, day: str | None = None, since: datetime | None = None
    ) -> None:
        """`fetched_at` is the window's end - when the run read its sources,
        not when it finished. Anything published while the run curated is
        then still inside the next run's window, however long curation took."""
        self.directory.mkdir(parents=True, exist_ok=True)
        data = self._read()
        if day is not None and since is not None:
            earlier = self.board_since(day)
            if earlier is None or since < earlier:
                data["board_day"] = day
                data["board_since"] = since.astimezone(UTC).isoformat(timespec="seconds")
        data["last_run_utc"] = fetched_at.astimezone(UTC).isoformat(timespec="seconds")
        data["last_run_stories"] = stories
        data["last_run_cost_usd"] = round(cost_usd, 4)
        data["runs"] = int(data.get("runs", 0)) + 1
        self.path.write_text(dump(data), encoding="utf-8")
        (self.directory / LEGACY_FILENAME).unlink(missing_ok=True)
