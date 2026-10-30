# Architecture & Pipeline

BlastRadius is a serverless, Git-backed static cybersecurity news board. It fetches security news from dozens of feeds, curates stories using LLMs with strict factual verification, archives the result in version-controlled YAML files, and deploys a pure HTML/CSS/JS frontend to GitHub Pages.

---

## High-Level Overview

```
                      ┌──────────────────────┐
                      │  RSS / Atom Feeds    │
                      │  Google News Topics  │
                      │  Web Search Queries  │
                      └──────────┬───────────┘
                                 │ Fetch & Normalise
                                 ▼
                      ┌──────────────────────┐
                      │ Candidate Pool       │
                      └──────────┬───────────┘
                                 │
           ┌─────────────────────┼─────────────────────┐
           │                     │                     │
           ▼                     ▼                     ▼
┌─────────────────────┐┌─────────────────────┐┌─────────────────────┐
│ Curation: Breaches  ││ Curation: Threats   ││ Curation: Vulns ... │
└──────────┬──────────┘└──────────┬──────────┘└──────────┬──────────┘
           │                      │                      │
           └─────────────────────┼──────────────────────┘
                                 ▼
                      ┌──────────────────────┐
                      │ Cross-Topic Review   │
                      │ (Dedupe & Placement) │
                      └──────────┬───────────┘
                                 │
                                 ▼
                      ┌──────────────────────┐
                      │ archive/YYYY/MM/DD   │
                      └──────────┬───────────┘
                                 │ Build
                                 ▼
                      ┌──────────────────────┐
                      │ public/ (GitHub Pages│
                      │ HTML, JSON, RSS Feed │
                      └──────────────────────┘
```

---

## How a Daily Run Works

### 1. Windowing
Every run computes a precise time window:
- Starts from when the previous run finished (`archive/state.yaml`), minus a 30-minute safety overlap.
- Clamped between `window.min_hours` (default 6h) and `window.max_hours` (default 96h).
- If a scheduled run is delayed or skipped, the subsequent run automatically widens its window to capture any missed stories.

### 2. Parallel Source Ingestion
All configured sources are fetched concurrently:
- **Shared Feeds** (`config/sources/shared.yaml`): Major security outlets read by every column.
- **Topic Feeds** (`config/sources/<column>.yaml`): Specialized feeds relevant to a single topic.
- **Google News & Web Search**: Queries targeting real-time disclosures and advisories.
- **Resilience**: A slow or failing source never breaks the pipeline. Individual failures are logged as `FAIL` and skipped.
- **Safety**: Downloads are capped at 10 MB per feed to protect the runner from unbounded streams.

### 3. LLM Curation Engine
Each column is curated independently through an OpenRouter LLM call:
- **Input**: The column brief, all candidates within the time window, the board's recent publication history (up to 300 stories across 14 days), and the existing label vocabulary.
- **Zero-Hallucination Enforcement**: The model cannot invent stories or links. Every URL in the response must resolve directly back to a known candidate (`blastradius/urlmatch.py`). Any unresolved pick is rejected.
- **History & Updates**: Candidates matching an already-published story are dropped unless they represent a material development. Significant updates link to the original story and appear in its **Developments** timeline.
- **Auto-Repair**: If a column returns fewer than its target items due to mis-copied URLs or formatting flaws, a targeted repair prompt runs to salvage valid stories.

### 4. Cross-Topic Review
Because shared sources feed multiple columns, different columns can independently pick the same major breaking story (e.g., a ransomware incident reported as both an active threat and a breach).
- A lightweight post-curation prompt inspects all chosen stories across columns.
- The review keeps the event in the single best-fitting column and merges any related coverage links into that card.

### 5. Archive Persistence
- The day's curated stories are written to `archive/<YYYY>/<MM>/<DD>.yaml`.
- The run updates `archive/state.yaml` with the completion timestamp, statistics, and LLM call costs.
- Days older than `archive.keep_days` (default 120 days) are pruned.
- The workflow commits `archive/` directly to the repository with `github-actions[bot]`.

### 6. Static Site Compilation
The generator (`blastradius/site.py`) outputs plain static assets to `public/`:
- `index.html`: Fast shell with embedded bootstrap configuration.
- `days/<YYYY-MM-DD>.json`: Lazy-loaded daily cards with complete coverage and timelines.
- `search.json`: Compact index downloaded only when the user opens search (`/`).
- `feed.xml` & `feed`: RSS 2.0 feed containing the latest 3 days of curated news.
- Precompressed `.gz` counterparts for immediate gzip delivery.
