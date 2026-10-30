# Operating the board

How to run, change and fix this without reading the code. The board is at **https://news.rtm.cc/**.

- [What happens every day](#what-happens-every-day)
- [Was today's run all right?](#was-todays-run-all-right)
- [I want to…](#i-want-to)
- [Every setting](#every-setting)
- [The archive](#the-archive)
- [Costs](#costs)
- [When something breaks](#when-something-breaks)

## What happens every day

At 06:10 UTC (06:10 in Lisbon in winter, 07:10 in summer) GitHub Actions runs the **Board** workflow on `main`. GitHub treats schedules as best-effort and sometimes drops one, so it is also scheduled at 07:40 and 10:10 UTC as backups: whichever runs first curates, and the later ones see today's board already in `archive/` and stop in seconds, without calling the model. A run:

The reliable trigger is outside GitHub: the GitLab project [jobs/secnews-github-runner-caller](https://git.rtm.cc/jobs/secnews-github-runner-caller) calls GitHub's "Run workflow" API every day at 07:00 Lisbon time, with `only_if_due` set, so it curates only if no scheduled run has yet. Its README covers the GitHub token it uses, which expires and has to be renewed.

1. **`test`** runs the tests and checks `config/`.
2. **`digest`** fetches every source, asks the model to curate each column, writes today's board to `archive/<YYYY>/<MM>/<DD>.yaml`, and commits it as **"Board for <date>"** (author: github-actions[bot]).
3. **`pages`** rebuilds the site from `archive/` and deploys it to GitHub Pages.

Everything runs on GitHub's own runners; there is no server.

| Where | What |
| --- | --- |
| `config/` | Everything you are meant to edit. Its own guide: [config/README.md](config/README.md). |
| `archive/` | The published boards, one YAML file per day, plus `state.yaml` (when the last run finished). Written by the workflow. |
| `blastradius/` | The code. `blastradius/assets/` is the site's CSS, JavaScript and icons. |
| `.github/workflows/board.yml` | The three jobs above, and when they run. |
| GitHub → Settings → Secrets and variables → Actions | `OPENROUTER_API_KEY`, the only secret. |
| GitHub → Settings → Pages | Source must be **GitHub Actions**. |

## Was today's run all right?

Open the **Actions** tab, then the latest **Board** run.

| The run shows | Meaning | Archive committed? |
| --- | --- | --- |
| green | Every column published. | yes |
| green with a **Partial board** warning | Published, but at least one column failed to curate and kept its previous board. | yes |
| red, `digest` failed | Nothing published: bad config, no API key, every source failed, or every column failed. GitHub emails you. | no |
| red, `test` failed | A config or code mistake; nothing ran. | no |

The run's **Summary** page has the full report:

```text
board 2026-10-29, window 24.5h (since the previous run at 2026-10-28 06:14 UTC)

Sources
  bleeping_computer   rss          10 in window of 15    0.1s      <- 10 usable items
  some_feed           rss         FAIL HTTP 403          0.2s      <- this feed is broken
  web_breaches        web_search    4 in window of 5     9.5s  $0.0052

Topics
  breaches          9 published of 84 candidates  2 rejected  1 updates  1 calls  $0.0061
      rejected: duplicates another selected event ...: <title>

Cross-topic review  6 removed  1 calls  $0.0030
  threats -> kept in breaches: <title> (<why>)

OpenRouter cost $0.0790
```

A source `FAIL` does not fail the run; that feed just contributed nothing. Fix or disable it when it keeps failing.

## I want to…

| …do this | Edit / do | Notes |
| --- | --- | --- |
| keep the archive longer or shorter | `archive.keep_days` in `config/settings.yaml` | Default 120 days. Older days go from the archive and the site on the next run. |
| change what a column picks | `config/briefs/<column>.md` | Try it first: `run --dry-run --topic <column>` locally. |
| add a general security feed | `config/sources/shared.yaml` | Every column sees it. Check it first with `check-feed <url>`. |
| add a feed about one subject | `config/sources/<column>.yaml` | Only that column sees it. |
| pause a feed | `enabled: false` on it | |
| add, pause or reorder a column | `topics.yaml` | [config/README.md](config/README.md). |
| change a column's size or colour | `max_items`, `min_items`, `color` in `topics.yaml` | Never change its `id`. |
| change the site title or credit | `site.title`, `site.author`, `site.author_url` in `settings.yaml` | |
| add a wallpaper | put an image in `config/` and set `site.background` in `settings.yaml` | The columns turn to frosted glass over it. |
| use a different model | `models.curate` in `settings.yaml` | Any OpenRouter model id. Dry-run first. |
| change the run time | the `cron:` line in `.github/workflows/board.yml` | UTC only. |
| run it now | Actions → Board → **Run workflow**, "curate" ticked | Replaces today's board, column by column. |
| redeploy the site without the model | push anything to `main`, or **Run workflow** with "curate" unticked | |
| look back further or less | **Run workflow** with "since_hours" | One run only. |
| rotate the OpenRouter key | Settings → Secrets and variables → Actions → `OPENROUTER_API_KEY` → Update | Also your local `.env`. |

After an edit: `.venv/bin/python -m blastradius check` locally, commit, push. The push redeploys the site (no model call); content changes show from the next run.

## Every setting

All in `config/settings.yaml`; every key is optional.

| Key | Value | Meaning |
| --- | --- | --- |
| `timezone` | `Europe/Lisbon` | "Today" is the run's date here; times on cards use it. The schedule itself is UTC. |
| `models.curate` | `deepseek/deepseek-v4-flash-0731` | Curates every column and runs the cross-topic review. |
| `models.search` | `deepseek/deepseek-v4-flash` | Runs the `web_search` sources only. |
| `window.default_hours` | 24 | The very first run. |
| `window.overlap_minutes` | 30 | Each run starts this long before the previous one ended. |
| `window.min_hours` / `max_hours` | 6 / 96 | Limits on the window. |
| `curation.candidate_limit` | 300 | At most this many candidates per column reach the model. The cost ceiling. |
| `curation.history_scope` | `board` | Every column sees the whole board's recent stories, labelled by column, so a story is never repeated in another column and an update keeps its Developments timeline when it moves between columns. `topic`: each column sees only its own. |
| `curation.published_days` / `published_limit` | 14 / 300 | How far back, and how many, of those stories each column sees - about a week of the whole board. Each story costs ~100 prompt tokens per column: 300 is about $0.02 a run; 150 halves that but remembers about three days. |
| `curation.cross_topic_review` | true | Keep each event in one column. |
| `curation.max_attempts` / `repair_rounds` | 3 / 1 | Retries for unusable or short answers. |
| `curation.timeout_seconds` / `workers` | 600 / 4 | Per call; columns curated at once. |
| `fetch.*`, `web_search.*`, `images.*` | | Timeouts, retries, parallelism. |
| `archive.keep_days` | 120 | **How many days the archive and the site keep.** |
| `site.title` | Blast Radius Digest | Page title and header. |
| `site.description` | Daily curated cybersecurity news and threat intel | Tagline under the title. |
| `site.site_url` | https://news.rtm.cc | Canonical site URL used for the RSS feed and self links. |
| `site.feed_days` | 3 | How many recent board days are included in `/feed` (default 3). |
| `site.author` / `author_url` | RTM / https://rtm.cc | The "by RTM" link. |
| `site.date_format`, `colored_tags` | `dmy`, true | |

## The archive

`archive/<YYYY>/<MM>/<DD>.yaml` is one board day: every column's stories, in order, with summary, sources, tags, coverage and update links. `archive/state.yaml` records when the last run finished, which is where the next window starts.

It is the pipeline's memory: each run shows every column the last two weeks of it (up to 300 stories, from every column), so a story is not published twice, and a follow-up is marked **Update** and joins the earlier story's Developments timeline - even when it lands in a different column. That is why the workflow commits it.

- **Remove a story:** delete its entry from that day's file, commit, push. The site rebuilds without it.
- **Remove a day:** delete its file, commit, push.
- **Redo today:** Run workflow again. Each column that produces stories replaces its part of today.

## Costs

About **$0.08 a day**, so roughly $2.50 a month: seven web searches at about half a cent each, seven curation calls at about a cent each, and the cross-topic review. GitHub Actions is free for public repositories.

- Each run's cost is the last line of its report, and `last_run_cost_usd` in `archive/state.yaml`.
- OpenRouter's dashboard shows every call, attributed to "Blast Radius Digest".
- The levers: fewer `web_search` sources, fewer or lower-volume shared feeds (each counts once per column), a lower `curation.candidate_limit`, a cheaper `models.curate`.

## When something breaks

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `digest` fails: `OPENROUTER_API_KEY is not set` | The secret is missing or misspelt. | Settings → Secrets and variables → Actions. |
| `digest` fails, columns `FAIL HTTP 401` / `402` | Key revoked, or OpenRouter credit ran out. | Top up or replace the key. |
| `digest` fails at "Commit the archive": push rejected | Branch protection on `main` blocks the bot. | Allow GitHub Actions to push to `main`, or drop the rule. |
| `pages` fails: "Pages site not found" or "not enabled" | Pages source is not GitHub Actions. | Settings → Pages → Source: GitHub Actions. |
| Warning **Partial board** | One column's answer was unusable three times. | Usually transient. If it repeats, try another model, or dry-run that column. |
| A source shows `FAIL` every day | Feed moved, blocked us, or died. | `check-feed <url>`; fix the URL or `enabled: false`. |
| No board this morning, and no failed run | The GitLab trigger did not run or failed (check its pipeline; an expired token shows as HTTP 401), and GitHub dropped its own scheduled slots too. | Actions → Board → **Run workflow**; if the workflow shows as disabled, **Enable workflow** first. |
| The same story in two columns | The cross-topic review missed it. | Sharpen the two briefs about which gets it. |
| Site unchanged after a push | Browser cache, or `pages` did not run. | Hard refresh (Ctrl+Shift+R); check the run. |
