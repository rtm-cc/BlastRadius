# Blast Radius Digest

Yesterday's security news, curated into a daily board: breaches, vulnerabilities and patches, active threats, supply chain, AI security, fraud and phishing, and policy and enforcement. A scheduled GitHub Actions run pulls security feeds, Google News and OpenRouter web searches, has one OpenRouter call per column pick, dedupe and summarise against what was already published, commits the result to `archive/`, and publishes the board to GitHub Pages.

**Board:** https://news.rtm.cc/

There is no server and no settings page. **The configuration is the files in `config/`**: edit one, push, and the next run uses it.

> **Running it day to day? Start with [OPERATIONS.md](OPERATIONS.md).** It covers checking a run, every setting, an "I want to…" table, costs, and what to do when something breaks. [config/README.md](config/README.md) covers the config files themselves.

The code is the `blastradius` Python package: `python -m blastradius <command>`.

## How a run works

1. **Window.** Everything since the previous run finished (`archive/state.yaml`), less a 30 minute overlap, clamped to 6–96 hours. A late or skipped run is covered by the next one instead of losing a day.
2. **Fetch.** Every enabled source, in parallel. The general security feeds are in `config/sources/shared.yaml` and every column sees them; a column's own sources (a web search each, plus feeds only it needs) are in `config/sources/<column>.yaml`. One dead feed never breaks a run; it shows as `FAIL` in the report.
3. **Curate.** One call per column with its brief, every candidate in the window, the whole board's recent stories (up to 300 from the last two weeks, each labelled with its column) and the tag vocabulary. The answer is checked rather than trusted: every URL must be a candidate the model was shown, source names come from the candidates, two picks of the same event are merged, an "update" only links to a story that is really in the history, and a column that comes back short because of mis-copied URLs gets one repair call.
4. **One event, one column.** With every column reading the same feeds, the same story can be picked twice - a ransomware breach is both a breach and an active threat. A last call reads only the stories about to be published and keeps each event in the column it fits best; the other card's coverage joins it.
5. **Publish.** Today's board goes into `archive/<YYYY>/<MM>/<DD>.yaml`, replacing only the columns that produced stories. Days older than `archive.keep_days` are deleted.
6. **Site.** `public/` is rebuilt from the archive and deployed to GitHub Pages.

## Configuration

**[config/README.md](config/README.md) is the full guide.**

| File | What it holds |
| --- | --- |
| `config/topics.yaml` | The columns (name, min/max items, colour) and, at the bottom, `board.columns`: the layout. |
| `config/briefs/<column>.md` | Each column's brief: what belongs in it, what does not, and which other column gets the near misses. |
| `config/sources/shared.yaml` | Feeds every column sees. |
| `config/sources/<column>.yaml` | A column's own sources. |
| `config/settings.yaml` | Models, timezone, window, cost limits, archive length, site title. |

`python -m blastradius check` validates all of it. CI runs the same check on every push and pull request.

## GitHub setup

Once, in the repository:

1. **Settings → Secrets and variables → Actions → New repository secret:** `OPENROUTER_API_KEY`, your OpenRouter key. It is the only secret; the workflow commits with the built-in `GITHUB_TOKEN`.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
3. **Actions → Board → Run workflow** for the first board, rather than waiting for the schedule.

The workflow is `.github/workflows/board.yml`:

| Trigger | Runs |
| --- | --- |
| Every day at 06:10 UTC (07:10 Lisbon in summer), with backups at 07:40 and 10:10 UTC that stop early once the day is done | `test`, `digest`, `pages` |
| **Run workflow**, "curate" ticked | `test`, `digest`, `pages` |
| **Run workflow**, "curate" unticked | `test`, `pages`: redeploy without calling the model |
| Push to `main` | `test`, `pages` |
| Pull request | `test` |

A `digest` that published but had a column fail to curate passes with a **warning**; one that published nothing **fails**, and GitHub emails you. Each run's full report is in its summary page.

GitHub switches off scheduled workflows in a public repository after 60 days without a commit. The daily "Board for <date>" commit is a commit, so it keeps itself alive - unless the runs stop for two months.

## Running it locally

From the repository root; CI uses Python 3.13.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then put your OpenRouter key after OPENROUTER_API_KEY=

.venv/bin/python -m blastradius check                            # validate config/ (free)
.venv/bin/python -m blastradius check-feed <feed url>            # what one feed returns (free)
.venv/bin/python -m unittest discover -s tests -t .        # the tests (free)
.venv/bin/python -m blastradius build-site                       # public/ from the archive (free)
.venv/bin/python -m http.server 8765 --directory public    # then open http://127.0.0.1:8765
.venv/bin/python -m blastradius run --dry-run                    # curate and print, write nothing (~$0.08)
.venv/bin/python -m blastradius run --dry-run --topic breaches   # one column, while tuning its brief
```

> **Seeing your freshest changes locally:**
> The website is a static site generated into `public/`. **Whenever you edit configuration** (`config/settings.yaml`, `config/topics.yaml`), **change the wallpaper** (`config/background.jpg`), or **edit assets**, you must rebuild the site to update `public/`:
> ```sh
> .venv/bin/python -m blastradius build-site
> ```
> Then hard-refresh your browser (`Ctrl+Shift+R` / `Cmd+Shift+R` to bypass cached assets) to view the changes immediately.

A real local `run` changes `archive/` just as CI does, so commit it or discard it with `git checkout archive/`.

## The board

Columns of cards with **Full coverage** and **Developments** timelines; ← and → step through days, `/` searches every archived day, and a tag on any card lists every story carrying it. Expanding a column shows it as a grid with the lead story featured; a tile opens the full story in a sheet. Links are shareable: `?date=2026-10-28`, `?date=…&topic=breaches`, `?q=ransomware`, `?tag=Zero-Day`, `?theme=light`.
