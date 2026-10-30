# <img src="blastradius/assets/favicon.svg" alt="Blast Radius logo" width="30" height="30" valign="bottom"> Blast Radius Digest

A serverless daily cybersecurity news board curated by AI. It aggregates threat intelligence, zero-day vulnerabilities, data breaches, and policy updates from trusted security sources into a clean, searchable dashboard.

- **Live Board:** [news.rtm.cc](https://news.rtm.cc/)
- **RSS Feed:** [news.rtm.cc/feed](https://news.rtm.cc/feed)
- **Operations Guide:** [OPERATIONS.md](OPERATIONS.md)

---

## Highlights

- **Serverless & Static:** Runs entirely on GitHub Actions and deploys to GitHub Pages. No servers, no databases, no maintenance.
- **Fact-Checked LLM Curation:** OpenRouter models curate and summarize stories against strict candidate constraints. The model cannot hallucinate or invent URLs.
- **Deduplication & Developments:** Merges duplicate reports across outlets and tracks story updates over time in interactive timelines.
- **RSS & Full-Text Search:** Native RSS 2.0 feed with autodiscovery and instant client-side full-text search across all archived days.
- **Robust CI/CD:** Automated pre-flight checks with Ruff (lint/formatting), Mypy (types), TruffleHog (secret scanning), and `pip-audit` (vulnerabilities).

---

## Quick Start (Local Setup)

Requires Python 3.13+.

```bash
# 1. Set up virtual environment
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# 2. Configure environment
cp .env.example .env
# Edit .env and set your OPENROUTER_API_KEY (only needed for live curation)

# 3. Validate configuration & run tests
.venv/bin/python -m blastradius check
.venv/bin/python -m unittest discover -s tests -t .

# 4. Build site and preview locally
.venv/bin/python -m blastradius build-site
.venv/bin/python -m http.server 8765 --directory public
# Open http://localhost:8765 in your browser
```

---

## Project Structure

```text
├── blastradius/          # Core Python engine & frontend static assets
│   └── assets/           # Frontend vanilla CSS, JavaScript, and SVGs
├── config/               # Repository configuration (topics, sources, settings)
│   ├── briefs/           # Markdown editorial briefs for each topic column
│   └── sources/          # RSS, Google News, and search source definitions
├── archive/              # Published daily boards stored as YAML (YYYY/MM/DD.yaml)
├── docs/                 # In-depth architectural and operational guides
└── tests/                # Automated test suite
```

---

## Documentation

- **[Operations Guide](OPERATIONS.md):** Managing daily runs, settings reference, costs, and troubleshooting.
- **[Architecture & Pipeline](docs/architecture.md):** How the windowing, ingestion, LLM curation, and deduplication engine works.
- **[Configuration Guide](config/README.md):** Adding topics, tuning briefs, and managing news sources.
- **[Setup & Deployment](docs/setup.md):** GitHub secrets, branch protection rules, and Actions triggers.
- **[Google News Topics](docs/google-news-topics.md):** How to discover and configure curated Google News topic feeds.

---

## License & Credits

Built and maintained by [RTM](https://rtm.cc). Published under the [MIT License](LICENSE).
