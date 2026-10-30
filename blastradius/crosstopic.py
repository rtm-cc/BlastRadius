"""One event, one topic.

Each topic is curated in its own call, from the same shared feeds, so
nothing stops two topics picking the same event: a ransomware attack is
both a breach and an active threat, a hijacked npm package both supply chain
and malware. Curating every topic in one call would catch it, but that call
outgrows the model's output limit - which is why they are split.

So once every topic is curated, one more call reads only what is about to be
published - a short line per story, not the hundreds of candidates - and
names the events that appear in more than one topic, with the topic each fits
best. Code then holds the line:

* every id must be one the model was shown, and a pair must span two topics
  (within a topic, curation already merged duplicates);
* a story a group keeps can never also be removed by another group - a
  contradictory answer changes nothing;
* stories from topics this run did not curate (a `--topic` rerun) can be
  kept but never removed;
* nothing is lost from the board: the removed card's coverage joins the kept
  card's Full coverage.

The asymmetry is deliberate. A missed duplicate costs one repeated card; a
wrong merge hides a story from the topic that wanted it. The prompt asks for
same-event matches only, and a failed or unusable answer removes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from . import openrouter
from .curate import extract_json
from .models import Story, Topic

SYSTEM_PROMPT = """You review a news board whose topics were curated independently, so the same \
real-world event can appear under more than one topic. Find every event that appears in two or more \
topics, and decide which single topic it fits best.

Rules:
- Only group stories that report the SAME event: the same incident, announcement, decision or \
development. Stories that are merely related - the same country, the same company, the same ongoing \
crisis but a different development - are NOT duplicates. When unsure, leave them alone.
- Keep the story in the topic whose focus it matches most directly. A company disclosing that its \
data was stolen belongs in Breaches, while the ransomware group's campaign across many victims \
belongs in Active Threats; a malicious npm package belongs in Supply Chain rather than Active Threats; \
the arrest of a ransomware operator belongs in Policy & Enforcement; a breach at an AI company \
belongs in AI Security only if the AI system itself was the way in.
- Stories marked (fixed) can be kept but never removed.
- Respond with strict JSON only, nothing else:
{"duplicates": [{"keep": "<id>", "remove": ["<id>", ...], "reason": "<one short sentence>"}]}
Return {"duplicates": []} when there are none."""


@dataclass
class Removal:
    topic: str
    story: Story
    kept_topic: str
    reason: str


@dataclass
class ReviewResult:
    removed: list[Removal] = field(default_factory=list)
    calls: int = 0
    cost_usd: float = 0.0
    error: str = ""


@dataclass
class _Entry:
    topic: str
    story: Story
    removable: bool


def _prompt(entries: dict[str, _Entry], topics: dict[str, Topic]) -> str:
    lines: list[str] = []
    current = None
    for sid, entry in entries.items():
        if entry.topic != current:
            current = entry.topic
            name = topics[current].name if current in topics else current
            lines.append(f"\n## {name}")
        summary = (entry.story.get("summary") or "")[:200]
        fixed = " (fixed)" if not entry.removable else ""
        lines.append(f"[{sid}]{fixed} {entry.story['title']} — {summary}")
    return "STORIES:" + "\n".join(lines)


def _parse(content: str) -> tuple[list[dict] | None, str]:
    payload = extract_json(content)
    if payload is None:
        return None, "the response contained no complete JSON object"
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    groups = data.get("duplicates") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        return None, 'expected an object with a "duplicates" array'
    valid = []
    for group in groups:
        if (
            isinstance(group, dict)
            and isinstance(group.get("keep"), str)
            and isinstance(group.get("remove"), list)
            and all(isinstance(r, str) for r in group["remove"])
        ):
            valid.append(group)
    return valid, ""


def _merge_into(keeper: Story, removed: Story) -> None:
    """The removed card's reporting joins the kept card's Full coverage."""
    known = {c["url"] for c in keeper.get("coverage") or []}
    extra = [c for c in removed.get("coverage") or [] if c["url"] not in known]
    keeper["coverage"] = (keeper.get("coverage") or []) + extra
    keeper["sources"] = list(dict.fromkeys((keeper.get("sources") or []) + (removed.get("sources") or [])))


def review(
    board: dict[str, list[Story]],
    fixed: dict[str, list[Story]],
    topics: dict[str, Topic],
    model: str,
    max_attempts: int,
    timeout: float,
    chat: Callable[[str, str, str, float], openrouter.Reply] | None = None,
) -> ReviewResult:
    """Find cross-topic duplicates and remove them from `board`, in place.
    Ranks are renumbered in every topic that lost a card."""
    chat = chat or openrouter.chat_json
    result = ReviewResult()

    entries: dict[str, _Entry] = {}
    for source, removable in ((board, True), (fixed, False)):
        for topic_id, stories in source.items():
            for story in stories:
                entries[f"s{len(entries) + 1}"] = _Entry(topic_id, story, removable)
    if len({e.topic for e in entries.values()}) < 2 or not any(e.removable for e in entries.values()):
        return result

    prompt = _prompt(entries, topics)
    groups = None
    message = prompt
    for _ in range(max_attempts):
        result.calls += 1
        try:
            reply = chat(model, SYSTEM_PROMPT, message, timeout)
        except openrouter.OpenRouterError as exc:
            result.error = str(exc)
            continue
        result.cost_usd += reply.cost_usd
        groups, problem = _parse(reply.content)
        if groups is not None:
            result.error = ""
            break
        result.error = problem
        message = f"{prompt}\n\n---\nYour previous response was invalid: {problem}\nReturn ONLY the JSON object."
    if groups is None:
        result.error = f"after {result.calls} calls: {result.error} - nothing removed"
        return result

    keepers = {g["keep"] for g in groups if g["keep"] in entries}
    doomed: dict[str, tuple[str, str]] = {}
    for group in groups:
        keep = entries.get(group["keep"])
        if keep is None:
            continue
        for sid in group["remove"]:
            entry = entries.get(sid)
            # Unknown, fixed, the keeper itself, the same topic, or kept by
            # another group: a contradictory or invented answer does nothing.
            if entry is None or not entry.removable or sid in keepers or entry.topic == keep.topic:
                continue
            doomed.setdefault(sid, (group["keep"], str(group.get("reason") or "")))

    for sid, (keep_sid, reason) in doomed.items():
        entry, keeper = entries[sid], entries[keep_sid]
        if keeper.removable:
            _merge_into(keeper.story, entry.story)
        board[entry.topic] = [s for s in board[entry.topic] if s is not entry.story]
        result.removed.append(Removal(entry.topic, entry.story, keeper.topic, reason))

    for topic_id in {r.topic for r in result.removed}:
        for rank, story in enumerate(board[topic_id], start=1):
            story["rank"] = rank
    return result
