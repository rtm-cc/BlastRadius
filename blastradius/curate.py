"""Curation: one model call per topic picks, dedupes and summarises.

The model sees the topic's brief, every candidate in the run window, and what
the topic already published recently, and answers with JSON. Nothing it says
is trusted as-is:

* every URL must resolve to a candidate it was shown (urlmatch.py) - the one
  check that stops it inventing stories;
* source names are derived from the verified candidates, never from its text;
* two picks reporting one event are merged even when the model missed it;
* "this updates <earlier story>" only sticks when that story really is in the
  topic's recent history.

A topic can come back short not because the news was thin but because the
model fumbled the paperwork - mis-copied URLs (one day cost a topic 14 of
its 15 cards), or a bare `{"stories": []}` for a topic holding 111
candidates. One repair call, naming what went wrong, recovers both. It is
deliberately not "pad to min_items": a topic that genuinely had little to say
still publishes short.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from . import openrouter
from .models import Candidate, Story, Topic
from .textutil import cluster_key, short_hash
from .urlmatch import CandidateIndex, build_index, resolve

SYSTEM_PROMPT = """You are the curation engine for a personal news board. You will be given, \
for one or more topics, a pool of candidate articles and a list of stories already published for \
that topic. For each topic, pick the best stories per its instructions, summarize them, and skip \
anything that just repeats what's already published.

Rules:
- Only ever use a URL that appears verbatim in the candidate list you were given. Never invent or \
modify a URL. Copy the whole "url:" line character for character, including everything after "?" — \
a URL with the query string trimmed off does not count as the same URL and the story will be dropped.
- Exclude any candidate that covers a story already in that topic's "ALREADY PUBLISHED" list, \
UNLESS it contains materially new information. "Material" means: exploitation status changed, a \
patch was released, scope significantly widened, attribution established or retracted, or earlier \
reporting was corrected. If you do re-surface one of these, set isUpdate to true, set supersedes to \
the title of the story it updates from the ALREADY PUBLISHED list, and fill in whatChanged.
- If the same real-world story is covered by candidates under more than one topic below, choose the \
single best-fitting topic for it and output it under that topic only. Do not duplicate it.
- Within each topic, collapse every candidate that reports the same real-world event into exactly one \
story, even when headlines use different wording or another language. Compare the people, places, \
dates, actions, and context in the title and excerpt — never rely on URL or headline-word overlap alone. \
Choose the strongest lead and put every alternate candidate URL for that event in coverageUrls. Do not \
output a second card for a later article unless it contains a material development; then mark it as an \
update and name the earlier card in supersedes.
- For every selected story, set coverageUrls to the URLs of other candidate articles that report the \
same event. Include the selected story URL too when it is the only available coverage. Only use URLs \
from that topic's candidate list. This is for a "Full coverage" view, not a second ranking.
- Never pad the list to hit a topic's target item count — if fewer candidates clear the bar, return \
fewer stories. Respect each topic's max item count as a ceiling, not a target.
- If a topic has eligible candidates, do not omit it entirely. Return stories for every topic you were given candidates for unless all candidates are invalid or already published.
- Write summaries in the language each topic specifies.
- Labels are short, useful tags for finding related stories. Prefer an exact tag from the EXISTING TAGS vocabulary when it accurately describes the story; create a new tag only when no existing tag fits. Never force an existing tag that is only loosely related.
- Respond with strict JSON only, matching this exact shape, and nothing else (no markdown fences, \
no commentary):
{"stories": [{"topic": string, "rank": number, "title": string, "summary": string, "url": string, \
"coverageUrls": string[], "otherSources": string[], "labels": string[], "rationale": string, "isUpdate": boolean, \
"supersedes": string | null, "whatChanged": string | null}]}"""

# The model picked a story that exists but wrote its URL down wrong. The
# repair round keys off this exact string.
UNRESOLVED_URL = "url not in candidate set"
UNKNOWN_TOPIC = "unknown topic"
REPAIR_URL_SAMPLE = 10
MAX_TAGS = 200


# --- the prompt -------------------------------------------------------------


def _format_candidate(c: Candidate, index: int) -> str:
    when = c.published.isoformat() if c.published else "unknown date"
    return (
        f"[{index}] {c.title}\n    url: {c.url}\n    source: {c.source_name} | {when}\n"
        f"    excerpt: {c.excerpt[:500]}"
    )


def _format_published(story: Story, topic_names: dict[str, str] | None) -> str:
    summary = (story.get("summary") or "")[:300]
    column = f"[{topic_names.get(story['topic'], story['topic'])}] " if topic_names else ""
    return f"- {story['day']} | {column}{story['title']}{f' — {summary}' if summary else ''}"


def build_prompt(
    topic: Topic,
    candidates: list[Candidate],
    published: list[Story],
    tags: list[str],
    topic_names: dict[str, str] | None = None,
) -> str:
    """The user message for one topic's call. With `topic_names` - the
    board-wide history - each published story is labelled with its topic,
    and the model is told an update may continue a story from another."""
    vocabulary = ", ".join(tags) if tags else "(none yet — create concise tags where useful)"
    already = "\n".join(_format_published(s, topic_names) for s in published) or "(none)"
    pool = "\n\n".join(_format_candidate(c, i) for i, c in enumerate(candidates)) or "(no candidates in this run's window)"
    if topic_names:
        heading = (
            "ALREADY PUBLISHED ON THE WHOLE BOARD, in every topic, labelled [topic] (do not repeat any of "
            "these unless materially new - whichever topic it ran in; an update may continue a story that "
            "first ran in another topic, and supersedes then names that story's title):"
        )
    else:
        heading = "ALREADY PUBLISHED (do not repeat unless materially new):"
    return (
        f"EXISTING TAGS (reuse exact matches whenever they fit):\n{vocabulary}\n\n---\n\n"
        f"## Topic: {topic.name}\n"
        f"Instructions: {topic.brief or '(no custom instructions — use editorial judgement)'}\n"
        f'Target: {topic.min_items}-{topic.max_items} items, summaries in "{topic.language}"\n\n'
        f"{heading}\n{already}\n\n"
        f"CANDIDATES:\n{pool}"
    )


def _words(value: str) -> list[str]:
    return re.findall(r"[^\W_]{2,}", value.lower())


def tag_vocabulary(counts: Counter[tuple[str, str]], context: dict[str, list[Candidate]], topics: dict[str, Topic]) -> list[str]:
    """The tags offered to the model, so the same idea keeps the same tag.

    Tags of the topics being curated come first, and a tag whose words
    appear in this run's candidates is promoted further - popularity alone
    would keep offering yesterday's subjects.
    """
    words_by_topic = {
        topic_id: set(_words(" ".join([topics[topic_id].name, topics[topic_id].brief] + [f"{c.title} {c.excerpt}" for c in candidates])))
        for topic_id, candidates in context.items()
    }
    best: dict[str, tuple[int, int, str]] = {}
    for (topic_id, tag), uses in counts.items():
        tag_words = _words(tag)
        if not tag_words:
            continue
        in_run = words_by_topic.get(topic_id)
        matched = sum(1 for w in tag_words if w in in_run) if in_run else 0
        score = (100 if in_run is not None else 0) + matched * 50 + min(uses, 25)
        key = tag.lower()
        if key not in best or (score, uses) > best[key][:2]:
            best[key] = (score, uses, tag)
    ranked = sorted(best.values(), key=lambda e: (-e[0], -e[1], e[2]))
    return [tag for _, _, tag in ranked[:MAX_TAGS]]


# --- reading the answer ---------------------------------------------------


def extract_json(content: str) -> str | None:
    """The outermost JSON object or array in a model answer.

    json_object mode is requested, but plenty of models still wrap the object
    in a ```json fence, open with "Here's the result:" or add a closing
    remark. Braces inside strings are skipped. None when there is no JSON at
    all, or it was cut off.
    """
    text = content.strip()
    match = re.search(r"[{\[]", text)
    if not match:
        return None
    start = match.start()
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(text)):
        char = text[i]
        if escaped:
            escaped = False
        elif in_string and char == "\\":
            escaped = True
        elif char == '"':
            in_string = not in_string
        elif not in_string:
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


_FIELDS: dict[str, tuple[type | tuple[type, ...], bool]] = {
    # name: (type, required)
    "topic": (str, True),
    "rank": ((int, float), True),
    "title": (str, True),
    "summary": (str, True),
    "url": (str, True),
    "coverageUrls": (list, False),
    "otherSources": (list, False),
    "labels": (list, True),
    "rationale": (str, True),
    "isUpdate": (bool, True),
    "supersedes": ((str, type(None)), False),
    "whatChanged": ((str, type(None)), False),
}


def parse_answer(content: str) -> tuple[list[dict[str, Any]] | None, str]:
    """(stories, "") or (None, why it is unusable) - one shape, so the
    caller retries on bad JSON and on a bad schema alike."""
    payload = extract_json(content)
    if payload is None:
        if re.search(r"[{\[]", content):
            return None, "Invalid JSON: the model's response was cut off before its JSON ended."
        return None, "Invalid JSON: the model's response contained no JSON object."
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"
    if not isinstance(data, dict) or not isinstance(data.get("stories"), list):
        return None, 'Schema mismatch: expected an object with a "stories" array.'

    for i, story in enumerate(data["stories"]):
        if not isinstance(story, dict):
            return None, f"Schema mismatch: stories[{i}] is not an object."
        for name, (kind, required) in _FIELDS.items():
            if name not in story:
                if required:
                    return None, f'Schema mismatch: stories[{i}] is missing "{name}".'
                continue
            value = story[name]
            # bool is an int in Python; a rank of true is not a rank.
            if not isinstance(value, kind) or (name == "rank" and isinstance(value, bool)):
                return None, f'Schema mismatch: stories[{i}].{name} has the wrong type.'
            if kind is list and not all(isinstance(v, str) for v in value):
                return None, f"Schema mismatch: stories[{i}].{name} must be a list of strings."
    return data["stories"], ""


# --- checking the answer --------------------------------------------------

# A small, high precision fallback for the model's event grouping. Unicode
# words are kept, so it works across languages; these are the connectives of
# the two languages the board mostly carries, so "the news of ..." cannot
# make a false cluster.
_STOP_WORDS = frozenset(
    """
    about after against ainda antes apos aos as com como das dos desde during em entre
    esta este for from mais nas news nos noticia noticias para pela pelo por sobre that
    the this uma with
    """.split()
)

# A fixed stop list is not enough, because every topic has its own filler.
# Found live: CyberSecurity cards were merged on "vulnerability",
# "attackers", "remote", "injection" - words that describe the beat, not the
# event. In one pool those ran at 19-58% document frequency while the words
# that identify stories ("wordpress", "switchvox") ran at 4-8%, so a
# WordPress plugin flaw was folded into a Switchvox exploit. Distinctiveness
# is therefore measured against the topic's own candidates for this run.
GENERIC_TERM_DF_RATIO = 0.15
# Two articles sharing a word is not evidence the word is filler, so a small
# pool leans on this floor instead of the ratio.
GENERIC_TERM_MIN_DOCS = 3
MIN_SHARED_DISTINCTIVE_TERMS = 2


def _terms(text: str) -> set[str]:
    folded = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    return {t for t in re.findall(r"[^\W_]{4,}", folded.lower()) if t not in _STOP_WORDS}


def distinctive(candidates: list[Candidate]) -> Callable[[str], bool]:
    frequency: Counter[str] = Counter()
    for c in candidates:
        frequency.update(_terms(f"{c.title} {c.excerpt}"))
    generic_at = max(GENERIC_TERM_MIN_DOCS, len(candidates) * GENERIC_TERM_DF_RATIO)
    return lambda term: frequency[term] < generic_at


def _same_event(a: dict, b: dict, is_distinctive: Callable[[str], bool]) -> bool:
    a_terms, b_terms = _terms(f"{a['title']} {a['summary']}"), _terms(f"{b['title']} {b['summary']}")
    shared = a_terms & b_terms
    if len(shared) < 3 or len(shared) / min(len(a_terms), len(b_terms)) < 0.2:
        return False
    # The overlap must include real subject matter - names, products,
    # places - not just the vocabulary every story in the topic uses.
    return sum(1 for t in shared if is_distinctive(t)) >= MIN_SHARED_DISTINCTIVE_TERMS


@dataclass
class Verified:
    accepted: list[dict] = field(default_factory=list)
    rejected: list[tuple[dict, str]] = field(default_factory=list)


def _other_sources(urls: list[str], lead: str, by_url: dict[str, Candidate]) -> list[str]:
    lead_source = by_url[lead].source_name
    return list(dict.fromkeys(by_url[u].source_name for u in urls if by_url[u].source_name != lead_source))


def verify(stories: list[dict], topic: Topic, by_url: dict[str, Candidate], index: CandidateIndex) -> Verified:
    """Keep what is real, collapse what is one event, cap at max_items."""
    out = Verified()
    resolved: list[dict] = []
    for story in stories:
        if story["topic"].strip().casefold() != topic.name.casefold():
            out.rejected.append((story, f'{UNKNOWN_TOPIC} "{story["topic"]}"'))
            continue
        url = resolve(index, story["url"])
        if url is None:
            out.rejected.append((story, UNRESOLVED_URL))
            continue
        # The lead stays even if the model left it out; invented alternates
        # are dropped; everything downstream sees only real candidate URLs.
        quoted = [url, *(story.get("coverageUrls") or [])]
        coverage = list(dict.fromkeys(u for u in (resolve(index, x) for x in quoted) if u))
        resolved.append({**story, "url": url, "coverageUrls": coverage, "otherSources": _other_sources(coverage, url, by_url)})

    is_distinctive = distinctive(list(by_url.values()))
    used: set[str] = set()
    for story in sorted(resolved, key=lambda s: s["rank"]):
        if any(u in used for u in story["coverageUrls"]):
            out.rejected.append((story, "duplicates another selected event through overlapping coverage"))
            continue
        twin = next((kept for kept in out.accepted if _same_event(kept, story, is_distinctive)), None)
        if twin is not None:
            twin["coverageUrls"] = list(dict.fromkeys(twin["coverageUrls"] + story["coverageUrls"]))
            twin["otherSources"] = _other_sources(twin["coverageUrls"], twin["url"], by_url)
            used.update(story["coverageUrls"])
            out.rejected.append((story, "duplicates another selected event through matching title and context"))
            continue
        if len(out.accepted) >= topic.max_items:
            out.rejected.append((story, f"exceeds max items ({topic.max_items}) for topic"))
            continue
        out.accepted.append(story)
        used.update(story["coverageUrls"])
    return out


def _recoverable(reason: str) -> bool:
    """A mis-copied URL or invented topic name is the model getting the
    paperwork wrong on a real pick. A duplicate or an over-the-ceiling
    rejection is the verifier working, and must never trigger a retry."""
    return reason == UNRESOLVED_URL or reason.startswith(UNKNOWN_TOPIC)


# --- one topic --------------------------------------------------------------


@dataclass
class TopicResult:
    topic: Topic
    candidates: int
    accepted: list[dict] = field(default_factory=list)
    rejected: list[tuple[dict, str]] = field(default_factory=list)
    calls: int = 0
    cost_usd: float = 0.0
    error: str = ""


Chat = Callable[[str, str, str, float], openrouter.Reply]


def curate_topic(
    topic: Topic,
    candidates: list[Candidate],
    published: list[Story],
    tags: list[str],
    model: str,
    max_attempts: int,
    repair_rounds: int,
    timeout: float,
    chat: Chat | None = None,
    topic_names: dict[str, str] | None = None,
) -> TopicResult:
    chat = chat or openrouter.chat_json
    result = TopicResult(topic=topic, candidates=len(candidates))
    by_url = {c.url: c for c in candidates}
    index = build_index(by_url)
    prompt = build_prompt(topic, candidates, published, tags, topic_names)

    def ask(user: str) -> list[dict] | None:
        """One answer, retrying on unusable JSON with the reason quoted."""
        message = user
        for _ in range(max_attempts):
            result.calls += 1
            try:
                reply = chat(model, SYSTEM_PROMPT, message, timeout)
            except openrouter.OpenRouterError as exc:
                result.error = str(exc)
                continue
            result.cost_usd += reply.cost_usd
            stories, problem = parse_answer(reply.content)
            if stories is not None:
                return stories
            result.error = problem
            message = (
                f"{user}\n\n---\nYour previous response was invalid: {problem}\n"
                "Return ONLY the corrected JSON object now, matching the schema exactly."
            )
        return None

    answer = ask(prompt)
    if answer is None:
        result.error = f"after {result.calls} calls: {result.error}"
        return result
    result.error = ""

    verified = verify(answer, topic, by_url, index)
    returned_nothing = not answer
    target = max(topic.min_items, 1)
    for _ in range(repair_rounds):
        if len(verified.accepted) >= target:
            break
        recoverable = [(s, r) for s, r in verified.rejected if _recoverable(r)]
        # Nothing a second ask can fix: the news really was thin, or the
        # verifier correctly collapsed everything into one event.
        if not recoverable and not returned_nothing:
            break
        if returned_nothing:
            complaint = (
                f"You returned no stories at all for this topic, even though it has {len(candidates)} "
                "candidates and your instructions say not to omit a topic that has eligible ones."
            )
        else:
            unresolved = [s["url"] for s, r in recoverable if r == UNRESOLVED_URL][:REPAIR_URL_SAMPLE]
            complaint = (
                f'{len(recoverable)} of your previous selections were discarded because their "url" or '
                f'"topic" did not match the list above, leaving only {len(verified.accepted)} of the '
                f"{target} stories this topic needs."
            )
            if unresolved:
                complaint += "\nThese URLs did not match:\n" + "\n".join(f"- {u}" for u in unresolved)
        repaired = ask(
            f"{prompt}\n\n---\n{complaint}\n\nRedo the selection for this topic. Set \"topic\" to exactly "
            f'"{topic.name}". For every story, copy the "url:" line of its candidate character for character '
            '— the full string including any query parameters after "?" — or pick a different candidate. '
            "If the news genuinely is thin, returning a few solid stories is fine; returning none is not. "
            "Return ONLY the JSON object."
        )
        if repaired is None:
            break
        returned_nothing = not repaired
        retried = verify(repaired, topic, by_url, index)
        if len(retried.accepted) > len(verified.accepted):
            verified = retried

    # A failed repair call leaves its error behind; the first answer stands.
    result.error = ""
    result.accepted, result.rejected = verified.accepted, verified.rejected
    return result


# --- into the archive -----------------------------------------------------


def to_records(
    result: TopicResult,
    day: str,
    by_url: dict[str, Candidate],
    published: list[Story],
    existing_today: list[Story],
) -> list[Story]:
    """The accepted picks as archive records, linked to earlier coverage.

    A rerun of the same day keeps each story's cluster and update link, so a
    rerun never turns "Update" back into a new story or the reverse. Otherwise
    an update joins the cluster of the story it supersedes - but only one
    actually in the recent history the model was shown (the topic's own, or
    with history_scope board every topic's, so a story can move from one
    topic to another and keep its timeline), found by its exact title or,
    when the model paraphrased it, by its headline fingerprint.
    """
    by_title = {}
    by_key = {}
    for story in published:
        by_title.setdefault(story["title"], story)
        if story.get("cluster_key"):
            by_key.setdefault(story["cluster_key"], story)
    today_by_url = {s["url"]: s for s in existing_today}
    today_by_key = {s["cluster_key"]: s for s in existing_today if s.get("cluster_key")}

    records = []
    for rank, pick in enumerate(result.accepted, start=1):
        lead = by_url[pick["url"]]
        key = cluster_key(pick["title"])
        story_id = short_hash(day, result.topic.id, pick["url"])

        same = today_by_url.get(pick["url"]) or (today_by_key.get(key) if key else None)
        prior = None
        if same is None and pick["isUpdate"]:
            prior = (by_title.get(pick["supersedes"]) if pick.get("supersedes") else None) or by_key.get(key)

        if same is not None:
            cluster = same.get("cluster") or story_id
            is_update, supersedes, what_changed = same.get("is_update", False), same.get("supersedes"), same.get("what_changed")
        elif prior is not None:
            cluster = prior.get("cluster") or prior["id"]
            is_update, supersedes, what_changed = True, prior["id"], pick.get("whatChanged")
        else:
            cluster, is_update, supersedes, what_changed = story_id, False, None, None

        records.append(
            {
                "id": story_id,
                "rank": rank,
                "title": pick["title"].strip(),
                "summary": pick["summary"].strip(),
                "url": pick["url"],
                "image": lead.image,
                "sources": list(dict.fromkeys([lead.source_name, *pick["otherSources"]])),
                "labels": list(dict.fromkeys(t.strip() for t in pick["labels"] if t.strip())),
                "rationale": pick["rationale"].strip(),
                "is_update": is_update,
                "supersedes": supersedes,
                "what_changed": what_changed,
                "cluster": cluster,
                "cluster_key": key,
                "coverage": [
                    {
                        "title": by_url[u].title,
                        "url": u,
                        "source": by_url[u].source_name,
                        "published": by_url[u].published.isoformat() if by_url[u].published else None,
                    }
                    for u in pick["coverageUrls"]
                ],
                "published": lead.published.isoformat() if lead.published else None,
            }
        )
    return records
