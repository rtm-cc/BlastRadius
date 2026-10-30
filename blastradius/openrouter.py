"""The two OpenRouter calls: curation, and the web search behind web_search
sources. Both report OpenRouter's own cost figure, which the run report adds
up - unlike an estimate, it includes the search fee.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import requests

URL = "https://openrouter.ai/api/v1/chat/completions"
# OpenRouter's app attribution; shows up on its activity page.
HEADERS: dict[str, str] = {}


def attribute(app_name: str, app_url: str) -> None:
    """Name the app on OpenRouter's activity page (site.title and
    site.repo_url), so two boards on one key can be told apart."""
    HEADERS.clear()
    if app_name:
        HEADERS["X-Title"] = app_name
    if app_url:
        HEADERS["HTTP-Referer"] = app_url


# Reaching the host is never slow; answering legitimately can be. Separate
# timeouts, so an unreachable host fails in seconds rather than minutes.
CONNECT_TIMEOUT = 10.0


class OpenRouterError(Exception):
    pass


@dataclass
class Reply:
    content: str
    cost_usd: float = 0.0
    citations: list[dict] = field(default_factory=list)


def api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def _post(body: dict, timeout: float) -> dict:
    key = api_key()
    if not key:
        raise OpenRouterError("OPENROUTER_API_KEY is not set")
    try:
        response = requests.post(
            URL,
            headers={"Authorization": f"Bearer {key}", **HEADERS},
            json=body,
            timeout=(CONNECT_TIMEOUT, timeout),
        )
    except requests.RequestException as exc:
        raise OpenRouterError(f"{type(exc).__name__}: {exc}") from exc
    if not response.ok:
        raise OpenRouterError(f"HTTP {response.status_code} from OpenRouter: {response.text[:500]}")
    try:
        data = response.json()
    except ValueError as exc:
        # Do not echo the body: it can be a large, truncated model answer.
        raise OpenRouterError(f"OpenRouter returned invalid JSON ({len(response.content)} bytes)") from exc
    if isinstance(data.get("error"), dict):
        raise OpenRouterError(f"OpenRouter error: {json.dumps(data['error'])[:500]}")
    return data


def _cost(data: dict) -> float:
    try:
        return float((data.get("usage") or {}).get("cost") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _message(data: dict) -> dict:
    choices = data.get("choices") or [{}]
    return choices[0].get("message") or {}


def chat_json(model: str, system: str, user: str, timeout: float) -> Reply:
    """One call asking for a JSON object.

    `response_format: json_object` rather than a strict schema, because the
    model is any OpenRouter id and plenty do not support strict structured
    output. The caller validates and retries instead - and plenty of models
    ignore json_object too, which is what curate.extract_json is for.
    """
    data = _post(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout,
    )
    # Content can be absent; the cost is still real, so return both and let
    # the caller treat the empty answer as an invalid one.
    return Reply(content=_message(data).get("content") or "", cost_usd=_cost(data))


def web_search(model: str, query: str, engine: str, max_results: int, timeout: float) -> Reply:
    """One search through OpenRouter's `web` plugin.

    The plugin rather than the agentic web_search tool on purpose: the plugin
    searches exactly once per request, so one web_search source is one paid
    search per run, every run. The model's answer is thrown away; the
    citations are the result.
    """
    plugin: dict = {"id": "web", "max_results": max_results}
    if engine:
        plugin["engine"] = engine
    data = _post(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": f"Search the web for: {query}\n\n"
                    "Just perform the search - a one-sentence acknowledgement is enough, no report needed.",
                }
            ],
            "plugins": [plugin],
        },
        timeout,
    )
    citations = [
        a["url_citation"]
        for a in _message(data).get("annotations") or []
        if a.get("type") == "url_citation" and (a.get("url_citation") or {}).get("url")
    ]
    return Reply(content="", cost_usd=_cost(data), citations=citations)
