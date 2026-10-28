"""Deciding how far back a run looks.

"The last 24 hours" is the wrong rule on its own: a run that is late, or
skipped because the runner was down, silently loses whatever fell between.
So the window starts where the previous run finished, less a small overlap so
nothing falls in the seam, and is clamped between min_hours and max_hours -
two weeks of downtime produces a four day board, not a two week one. The
archive's "already published" list is what stops the overlap from repeating
a story.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import WindowSettings

# Some feeds stamp items a little ahead, from a skewed clock or scheduled
# publishing. Dropping those would lose the newest stories.
FUTURE_TOLERANCE = timedelta(hours=6)


@dataclass(frozen=True)
class Window:
    since: datetime
    until: datetime
    reason: str

    @property
    def hours(self) -> float:
        return (self.until - self.since).total_seconds() / 3600

    def contains(self, when: datetime | None) -> bool:
        return when is not None and self.since <= when <= self.until + FUTURE_TOLERANCE


def resolve(
    now: datetime,
    last_run: datetime | None,
    settings: WindowSettings,
    override_hours: float | None = None,
) -> Window:
    if override_hours is not None:
        return Window(now - timedelta(hours=override_hours), now, f"--since-hours {override_hours:g}")

    if last_run is not None:
        start = last_run - timedelta(minutes=settings.overlap_minutes)
        reason = f"since the previous run at {last_run:%Y-%m-%d %H:%M} UTC"
    else:
        start = now - timedelta(hours=settings.default_hours)
        reason = f"first run, {settings.default_hours:g}h default"

    floor = now - timedelta(hours=settings.max_hours)
    ceiling = now - timedelta(hours=settings.min_hours)
    if start < floor:
        start, reason = floor, f"{reason}, capped at {settings.max_hours:g}h"
    elif start > ceiling:
        start, reason = ceiling, f"{reason}, widened to the {settings.min_hours:g}h minimum"
    return Window(start, now, reason)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
