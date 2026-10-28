"""When the last run finished, which is where the next run's window starts.

It lives in archive/, beside the day files, because that is what CI commits:
anywhere else a fresh checkout would never see the previous run, believe
every run was the first, and fall back to the default window.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
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
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def record_run(self, finished_at: datetime, stories: int, cost_usd: float) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        data = self._read()
        data["last_run_utc"] = finished_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        data["last_run_stories"] = stories
        data["last_run_cost_usd"] = round(cost_usd, 4)
        data["runs"] = int(data.get("runs", 0)) + 1
        self.path.write_text(dump(data), encoding="utf-8")
        (self.directory / LEGACY_FILENAME).unlink(missing_ok=True)
