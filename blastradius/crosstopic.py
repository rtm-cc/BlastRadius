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
from .textutil import cluster_key, is_article_url, normalize_url

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
the arrest of a ransomware operator belongs in Policy & Enforcement; vulnerabilities in AI systems, \
AI assistants, and LLMs, malicious AI developer extensions, or attacks abusing AI models belong in \
AI Security rather than general Vulnerabilities, Supply Chain, or Active Threats; a breach at an AI \
company belongs in AI Security only if the AI system itself was the way in.
- Stories marked (fixed) can be kept but never removed.
- Stories marked (carried over) were already published on an earlier day and fill a short column. \
When one reports the same event as a story without that mark - including a later development of it - \
keep the unmarked story and remove the carried-over one.
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
        carried = " (carried over)" if entry.story.get("is_carryover") else ""
        lines.append(f"[{sid}]{fixed}{carried} {entry.story['title']} — {summary}")
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
    extra = [
        c for c in removed.get("coverage") or [] if c.get("url") and c["url"] not in known and is_article_url(c["url"])
    ]
    keeper["coverage"] = [c for c in (keeper.get("coverage") or []) if is_article_url(c.get("url", ""))] + extra
    keeper["sources"] = list(
        dict.fromkeys([c["source"] for c in keeper["coverage"] if c.get("source")] or keeper.get("sources") or [])
    )


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
        result.error = (
            f"after {result.calls} calls: {result.error} - nothing removed"
            if not result.removed
            else f"after {result.calls} calls: {result.error}"
        )
    else:
        keepers = {g["keep"] for g in groups if g["keep"] in entries}
        doomed: dict[str, tuple[str, str]] = {}
        for group in groups:
            keep_sid = group["keep"]
            keep = entries.get(keep_sid)
            if keep is None:
                continue
            reason = str(group.get("reason") or "")
            for sid in group["remove"]:
                entry = entries.get(sid)
                if entry is None or entry.topic == keep.topic:
                    continue
                # Yesterday's card never beats today's report of the same
                # event: when the model keeps a carryover over a fresh story,
                # the carryover is the one that goes.
                if keep.removable and keep.story.get("is_carryover") and not entry.story.get("is_carryover"):
                    doomed.setdefault(keep_sid, (sid, reason))
                    continue
                # Unknown, fixed, the keeper itself, or kept by another group:
                # a contradictory or invented answer does nothing.
                if not entry.removable or sid in keepers:
                    continue
                doomed.setdefault(sid, (keep_sid, reason))

        for sid, (keep_sid, reason) in doomed.items():
            entry, keeper = entries[sid], entries[keep_sid]
            if keeper.removable and keep_sid not in doomed:
                _merge_into(keeper.story, entry.story)
            board[entry.topic] = [s for s in board[entry.topic] if s is not entry.story]
            result.removed.append(Removal(entry.topic, entry.story, keeper.topic, reason))

    # Safety net: eliminate any remaining exact URL overlap or identical cluster key matches
    _dedup_exact_matches(board, fixed, topics, result)

    for topic_id in {r.topic for r in result.removed}:
        for rank, story in enumerate(board[topic_id], start=1):
            story["rank"] = rank
    return result


def _story_urls(story: Story) -> set[str]:
    urls = set()
    raw = story.get("url")
    if raw:
        urls.add(normalize_url(raw))
    for c in story.get("coverage", []):
        if isinstance(c, dict) and c.get("url"):
            urls.add(normalize_url(c["url"]))
    return urls


def _pick_keeper_topic(
    topic1: str, story1: Story, topic2: str, story2: Story, topics: dict[str, Topic]
) -> tuple[str, Story, str, Story]:
    """Pick which of two duplicate stories across topic1 and topic2 to keep.
    Returns (keeper_topic, keeper_story, removed_topic, removed_story)."""
    text = (story1.get("title", "") + " " + story2.get("title", "")).lower()
    labels = [lbl.lower() for lbl in (story1.get("labels") or []) + (story2.get("labels") or [])]
    has_ai = any("ai" in lbl for lbl in labels) or "agentic" in text or "prompt injection" in text

    if has_ai and "ai_security" in (topic1, topic2):
        if "northflank" in text:
            keeper_topic = "breaches" if "breaches" in (topic1, topic2) else "ai_security"
        else:
            keeper_topic = "ai_security"
    elif "breaches" in (topic1, topic2) and ("breach" in text or "data breach" in text):
        keeper_topic = "breaches"
    # Before threats: a poisoned package nearly always carries malware, and
    # the review prompt puts a malicious npm package in Supply Chain.
    elif "supply_chain" in (topic1, topic2) and ("package" in text or "npm" in text or "pypi" in text):
        keeper_topic = "supply_chain"
    elif "threats" in (topic1, topic2) and ("malware" in text or "infostealer" in text or "ransomware" in text):
        keeper_topic = "threats"
    elif "vulnerabilities" in (topic1, topic2) and ("cve" in text or "vulnerability" in text or "patch" in text):
        keeper_topic = "vulnerabilities"
    else:
        r1 = story1.get("rank", 999)
        r2 = story2.get("rank", 999)
        keeper_topic = topic1 if r1 <= r2 else topic2

    if keeper_topic == topic1:
        return topic1, story1, topic2, story2
    return topic2, story2, topic1, story1


def _is_same_event(story1: Story, story2: Story) -> bool:
    """Return True if two stories definitively report the exact same article or event."""
    u1 = _story_urls(story1)
    u2 = _story_urls(story2)
    if u1 & u2:
        return True
    # One running story, as curation already recorded it: an update joins
    # the cluster of the story it supersedes. Different outlets, different
    # headlines - so the URL and headline checks below cannot see it. Found
    # on 2026-11-03: a carried-over BTCPay card and today's update of it.
    c1, c2 = story1.get("cluster"), story2.get("cluster")
    if c1 and c1 == c2:
        return True
    if story1.get("supersedes") and story1["supersedes"] == story2.get("id"):
        return True
    if story2.get("supersedes") and story2["supersedes"] == story1.get("id"):
        return True
    t1 = story1.get("title", "").strip().lower()
    t2 = story2.get("title", "").strip().lower()
    if t1 and t1 == t2 and len(t1) >= 15:
        return True
    ck1 = story1.get("cluster_key") or cluster_key(story1.get("title", ""))
    ck2 = story2.get("cluster_key") or cluster_key(story2.get("title", ""))
    if ck1 and ck1 == ck2 and len(ck1.split("-")) >= 4:
        return True
    return False


def _dedup_exact_matches(
    board: dict[str, list[Story]],
    fixed: dict[str, list[Story]],
    topics: dict[str, Topic],
    result: ReviewResult,
) -> None:
    """Safety net: detect and remove any remaining exact URL overlap or identical
    cluster_key matches across different topics."""
    changed = True
    while changed:
        changed = False
        all_stories: list[tuple[str, Story, bool]] = []
        for t, slist in board.items():
            for s in slist:
                all_stories.append((t, s, True))
        for t, slist in fixed.items():
            for s in slist:
                all_stories.append((t, s, False))

        for i in range(len(all_stories)):
            t1, s1, r1 = all_stories[i]
            if r1 and s1 not in board.get(t1, []):
                continue

            for j in range(i + 1, len(all_stories)):
                t2, s2, r2 = all_stories[j]
                if t1 == t2:
                    continue
                if r2 and s2 not in board.get(t2, []):
                    continue
                if not r1 and not r2:
                    continue

                if _is_same_event(s1, s2):
                    if not r1:
                        keeper_t, keeper_s, remove_t, remove_s = t1, s1, t2, s2
                    elif not r2:
                        keeper_t, keeper_s, remove_t, remove_s = t2, s2, t1, s1
                    # Yesterday's card never beats today's report of the
                    # same event, whichever column fits better.
                    elif s1.get("is_carryover") and not s2.get("is_carryover"):
                        keeper_t, keeper_s, remove_t, remove_s = t2, s2, t1, s1
                    elif s2.get("is_carryover") and not s1.get("is_carryover"):
                        keeper_t, keeper_s, remove_t, remove_s = t1, s1, t2, s2
                    else:
                        keeper_t, keeper_s, remove_t, remove_s = _pick_keeper_topic(t1, s1, t2, s2, topics)

                    _merge_into(keeper_s, remove_s)
                    board[remove_t] = [s for s in board[remove_t] if s is not remove_s]
                    result.removed.append(Removal(remove_t, remove_s, keeper_t, "duplicate URL or headline match"))
                    changed = True
                    break
            if changed:
                break
