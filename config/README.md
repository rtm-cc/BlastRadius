# config/

Everything the board does is decided by the files in this folder. Edit one, push, and the next run uses it. A push to `main` also redeploys the site straight away without calling the model.

Before pushing, check your edit; CI runs the same check and fails on a mistake:

```sh
.venv/bin/python -m top10 check
```

| Path | What it holds |
| --- | --- |
| [`topics.yaml`](topics.yaml) | The columns, and the board's layout. |
| [`briefs/<column>.md`](briefs/) | What each column picks and skips, in plain prose. This is what the model reads. |
| [`sources/shared.yaml`](sources/shared.yaml) | Feeds every column sees. |
| [`sources/<column>.yaml`](sources/) | A column's own sources. |
| [`settings.yaml`](settings.yaml) | Models, timezone, run window, cost limits, archive length, site title. Every key is commented. |

The **column id** (`breaches`, `vulnerabilities`, …) ties everything together: it names the column in `topics.yaml`, its brief `briefs/<id>.md`, its sources `sources/<id>.yaml`, and its place in the layout.

## How the columns share the news

Security outlets do not split their feeds by subject: BleepingComputer runs a breach, a zero-day and a phishing campaign on the same morning. So the general feeds live in **`sources/shared.yaml`**, are fetched once, and every column is offered all of them. Each **brief** then picks its slice and says where the near misses belong ("leave the ransomware group's campaign to Active Threats"). A story two columns still both pick is settled by the cross-topic review, which keeps it in the one it fits best.

A column's own file is for what only it needs: its web search, and feeds about its subject alone (DataBreaches.net for Breaches, Embrace The Red for AI Security).

So, to steer a column, edit its **brief**; to add a general security feed, add it to **`shared.yaml`**; to add a feed about one subject, add it to **that column's file**.

## The layout

The columns, left to right, are `board.columns` at the bottom of [`topics.yaml`](topics.yaml):

```yaml
board:
  columns:
    - [breaches]                       # a full-height column
    - [vulnerabilities]
    - [threats]
    - [supply_chain, ai_security]      # two columns stacked, half the height each
    - [fraud_phishing, policy]
```

- Each line is one column. One topic fills it; two share it, the first on top. At most two.
- Reorder the lines to move columns; put two ids in the same brackets to stack them; split them onto two lines to give each its own.
- An enabled topic missing from the list still shows, at the right end.
- On a phone, every topic is its own swipeable column, in the same order.
- A topic's colour is `color` in `topics.yaml`: a hue from 0 to 359 (0 red, 45 amber, 160 green, 225 blue, 280 purple).

## Adding a column

1. Add it to `topics.yaml` with a new snake_case `id` (not `shared`, which is reserved).
2. Write `briefs/<id>.md`: what belongs, what does not, and which existing column gets the near misses. Also tell the neighbouring briefs what to leave to it.
3. Optionally create `sources/<id>.yaml` with a web search or feeds of its own; it already sees everything in `shared.yaml`.
4. Put it in `board.columns`.

Each column is one model call a day, so a new one adds about a cent.

### `topics.yaml` fields

| Field | |
| --- | --- |
| `id` | Required, unique, snake_case. Never rename it: its history stops counting as "already published". |
| `name` | The column heading. |
| `language` | The language summaries are written in. |
| `max_items` | A ceiling, never a target. |
| `min_items` | If the model returns fewer because it mis-copied URLs or returned nothing, it is asked once more. Never padding. |
| `color` | Column accent, a hue 0–359. |
| `enabled` | `false` stops curating it; its past days stay on the site. |

## Sources

```yaml
sources:
  - id: databreaches_net
    type: rss
    name: DataBreaches.net
    url: https://databreaches.net/feed/
    notes: ~10/day.
```

Check a feed before adding it - it shows what the feed returns and how many items a day:

```sh
.venv/bin/python -m top10 check-feed https://example.com/feed.xml
```

Mind the volume: a shared feed is offered to all seven columns, so its cost counts seven times. A feed posting 100 a day needs a `max_items`, and no column sends the model more than `curation.candidate_limit` (in `settings.yaml`) anyway.

### Fields for every type

| Field | |
| --- | --- |
| `id` | Required, snake_case, unique across all the files. |
| `type` | `rss`, `google_news` or `web_search`. |
| `name` | Shown on the card for `rss`; `google_news` shows each item's own publisher. |
| `enabled` | `false` parks it without deleting it. |
| `max_age_hours` | Drop items older than this, on top of the run window. |
| `max_items` | Keep at most this many, newest first, after the age filter. |
| `notes` | Why it is here, and what to watch out for. |

### `rss`

| Field | |
| --- | --- |
| `url` | The RSS or Atom URL. |

### `google_news`

| Field | |
| --- | --- |
| `google_topic` | A section (`WORLD`, `TECHNOLOGY`, `SCIENCE`, …) or an opaque topic id from a `news.google.com/topics/<id>` URL. See [docs/google-news-topics.md](../docs/google-news-topics.md). |
| `google_section` | Optional tab within an opaque topic. |
| `query` | Instead of `google_topic`: a search. `max_age_hours` is also sent to Google as `when:`. |
| `language`, `country` | Default `en-US` and `US`. |
| `max_items` | Default 25; Google never returns more than 100. |

### `web_search`

One paid search through OpenRouter per run, about half a cent.

| Field | |
| --- | --- |
| `query` | Plain language. |
| `engine` | `native`, `exa`, `firecrawl`, `parallel` or `perplexity`. `native` needs a model with its own search (`models.search` in `settings.yaml`). |
| `max_results` | Default 5. |

Every result is loaded before it becomes a candidate, so a citation that does not open is dropped.
