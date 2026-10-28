"""Reading the API key from a .env file for local runs.

In CI the key arrives as a real environment variable - a repository secret in GitHub
variable - so nothing special is needed there. Locally, a `.env` file at the
repo root is read instead.

Precedence: **a real environment variable always wins over the file**, the
usual dotenv convention, so a stale `.env` can never override what CI
injected. `load()` reports where each value came from and the CLI prints it,
because an exported variable you forgot about quietly beating the file is the
confusing case.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_FILENAME = ".env"

# Only these are read from the file. An unknown key in a .env is far more
# likely to be a typo than something we should put in the environment.
KNOWN_KEYS = ("OPENROUTER_API_KEY",)


@dataclass
class Loaded:
    path: Path | None = None
    from_file: list[str] = field(default_factory=list)
    shadowed: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if self.path is None:
            return "no .env file; using the environment as-is"
        parts = [f"read {self.path.name}"]
        if self.from_file:
            parts.append(f"set {', '.join(self.from_file)}")
        if self.shadowed:
            parts.append(f"ignored {', '.join(self.shadowed)} (already set in the environment)")
        if self.unknown:
            parts.append(f"skipped unknown {', '.join(self.unknown)}")
        return "; ".join(parts)


def parse(text: str) -> dict[str, str]:
    """Comments, blank lines, an optional `export ` prefix and quoted values.
    No interpolation - an API key containing `$` must stay as written."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif "#" in value:
            value = value.split("#", 1)[0].strip()
        if key:
            values[key] = value
    return values


def load(root: Path | None = None) -> Loaded:
    """Fill gaps in the environment from <root>/.env, if there is one."""
    path = (root or Path(__file__).resolve().parent.parent) / DEFAULT_FILENAME
    if not path.exists():
        return Loaded()

    result = Loaded(path=path)
    for key, value in parse(path.read_text(encoding="utf-8")).items():
        if key not in KNOWN_KEYS:
            result.unknown.append(key)
        elif os.environ.get(key):
            result.shadowed.append(key)
        elif value:
            os.environ[key] = value
            result.from_file.append(key)
    return result
