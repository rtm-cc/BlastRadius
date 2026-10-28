"""Reading an article page's own metadata.

Two things need it. A web search citation is only trusted once the page
actually loads, and the page is also the only reliable place to learn its
title and publication date. And a card whose feed carried no image gets the
page's og:image, or failing that its first substantial <img>.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests

from .textutil import strip_html

_ICONISH = re.compile(r"icon|logo|sprite|avatar|pixel|1x1|spacer", re.IGNORECASE)
MIN_IMAGE_SIDE = 100
# Metadata lives in <head>; a megabyte is plenty and caps a runaway page.
MAX_BYTES = 1_000_000


@dataclass
class PageMeta:
    url: str
    title: str = ""
    published: datetime | None = None
    image: str = ""
    site_name: str = ""


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.meta: dict[str, str] = {}
        self.time = ""
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title" and not self.title:
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and "content" in a:
                self.meta.setdefault(key, a["content"])
        elif tag == "time" and a.get("datetime") and not self.time:
            self.time = a["datetime"]
        elif tag == "img" and a.get("src") and len(self.images) < 40:
            self.images.append(a)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def _date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _side(value: str) -> int:
    return int(value) if value.isdigit() else 0


def parse(url: str, html: str) -> PageMeta:
    parser = _MetaParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    meta = parser.meta

    image = meta.get("og:image") or meta.get("twitter:image") or ""
    if not image:
        for img in parser.images:
            src = img["src"]
            if _ICONISH.search(src):
                continue
            width, height = _side(img.get("width", "")), _side(img.get("height", ""))
            if (width and width < MIN_IMAGE_SIDE) or (height and height < MIN_IMAGE_SIDE):
                continue
            image = src
            break

    return PageMeta(
        url=url,
        title=strip_html(meta.get("og:title") or parser.title),
        published=_date(
            meta.get("article:published_time") or meta.get("date") or parser.time
        ),
        image=urljoin(url, image) if image and not image.startswith("data:") else "",
        site_name=strip_html(meta.get("og:site_name", "")),
    )


def fetch(url: str, user_agent: str, timeout: float) -> PageMeta | None:
    """The page's metadata, or None when it does not load."""
    try:
        with requests.get(
            url, headers={"User-Agent": user_agent}, timeout=(10, timeout), stream=True
        ) as response:
            if not response.ok or "html" not in response.headers.get("Content-Type", "html"):
                return None
            body = response.raw.read(MAX_BYTES, decode_content=True)
            # requests assumes ISO-8859-1 for text/html without a charset,
            # which mangles every accented headline; nearly all of the web is
            # UTF-8.
            declared = "charset" in response.headers.get("Content-Type", "").lower()
            encoding = (response.encoding or "utf-8") if declared else "utf-8"
            text = body.decode(encoding, errors="replace")
    except (requests.RequestException, OSError):
        return None
    return parse(response.url or url, text)
