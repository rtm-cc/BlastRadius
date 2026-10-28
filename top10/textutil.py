"""Text and URL tidying.

Feed items arrive as HTML fragments wrapped around tracking URLs. Curation,
the history and the site all work better on plain text and on a URL that is
stable between runs.
"""

from __future__ import annotations

import hashlib
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_WHITESPACE = re.compile(r"\s+")

# Query parameters that change between runs or readers, and so must not be
# part of an article's identity. `at_*` is BBC's syndication tagging
# (at_campaign=rss&at_medium=RSS) - found live: without it BBC candidates
# kept a suffix the model correctly dropped when quoting the story back,
# which made a real story look like an invented URL.
_TRACKING_PREFIXES = ("utm_", "mc_", "at_", "ns_")
_TRACKING_EXACT = frozenset(
    """
    fbclid gclid dclid gbraid wbraid msclkid yclid igshid igsh ref ref_src
    ref_url spm ito cmp cmpid ocid intcid _ga _gl si srsltid
    """.split()
)

# Hosts whose links are opaque interstitials: the path is the whole identity
# and the query is the host's own presentation state. Google News appends
# ?oc=5&hl=…&gl=…&ceid=US:en to every link, which the model dropped when
# quoting a story back, so a real candidate looked invented. Dropping the
# query here fixes it at the source; urlmatch.py is the second line.
_OPAQUE_HOSTS = (re.compile(r"^news\.google\.com$", re.IGNORECASE),)


class _TagStripper(HTMLParser):
    """Minimal HTML to text. Feed summaries are small fragments, so this keeps
    the dependency list short."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def strip_html(value: str | None) -> str:
    """Turn a feed summary into a single line of plain text."""
    if not value:
        return ""
    parser = _TagStripper()
    try:
        parser.feed(value)
        parser.close()
        text = parser.text()
    except Exception:
        # Malformed markup should degrade, not crash the run.
        text = re.sub(r"<[^>]+>", " ", value)
    return _WHITESPACE.sub(" ", unescape(text)).strip()


def truncate(text: str, max_chars: int) -> str:
    """Cut to max_chars on a word boundary, with an ellipsis."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(",.;:-")
    return f"{cut}…"


def is_opaque_interstitial(host: str) -> bool:
    return any(pattern.match(host) for pattern in _OPAQUE_HOSTS)


def normalize_url(url: str) -> str:
    """The article URL with what varies between fetches removed.

    Unlike a pure identity key this stays a working link - the scheme is
    kept, since it is what the card links to. Anything unparseable comes back
    trimmed rather than thrown away.
    """
    url = (url or "").strip()
    # Click-tracking redirectors that carry the article URL after a "*" in
    # their path - Folha's feeds link every item as
    # https://redir.folha.com.br/redir/online/emcimadahora/rss091/*https://www1.folha...
    # The article is the identity; the wrapper would stop it deduping.
    wrapped = re.search(r"/\*(https?://.+)$", url)
    if wrapped:
        url = wrapped.group(1)
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.scheme or not parts.netloc:
        return url

    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    if (scheme == "http" and host.endswith(":80")) or (scheme == "https" and host.endswith(":443")):
        host = host.rsplit(":", 1)[0]
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    if is_opaque_interstitial(host):
        query = ""
    else:
        kept = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_EXACT and not k.lower().startswith(_TRACKING_PREFIXES)
        ]
        query = urlencode(sorted(kept))
    return urlunsplit((scheme, host, path, query, ""))


def short_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


def cluster_key(title: str) -> str:
    """A rough fingerprint of a headline, used to find the earlier story an
    update refers to when the model names it imprecisely. Sorted so word
    order does not matter.

    Same recipe as the old app's clusterKeyFor - the first twelve words,
    then sorted - so the keys stored in imported history still match."""
    words = re.sub(r"[^\w\s]|_", " ", title.lower()).split()
    return "-".join(sorted([w for w in words if len(w) > 2][:12]))
