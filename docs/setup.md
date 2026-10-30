# Setup & Deployment Guide

This guide covers initial repository setup, required secrets, and deployment configurations for BlastRadius.

---

## 1. Initial GitHub Setup

1. **Repository Secrets**:
   - Go to **Settings → Secrets and variables → Actions → New repository secret**.
   - `OPENROUTER_API_KEY`: Your OpenRouter API key (used for LLM curation calls).
   - `ARCHIVE_PUSH_TOKEN` (optional but recommended): A Personal Access Token (PAT) with `repo` scope from a repository admin. This allows the daily digest job to push `archive/` commits while bypassing the pull request approval rule.

2. **GitHub Pages Deployment**:
   - Go to **Settings → Pages**.
   - Under **Build and deployment → Source**, select **GitHub Actions**.

3. **Branch Protection (Repository Ruleset)**:
   - Configured via **Settings → Rules → Rulesets** on `main` (`~DEFAULT_BRANCH`).
   - Requires 1 approving review on pull requests with stale review dismissal.
   - Deletion and force-pushes are blocked.
   - The **Bypass List** grants bypass permissions to **Organization Admin** and **Repository Admin** (`ARCHIVE_PUSH_TOKEN`).

---

## 2. Workflow Triggers & Execution

The primary workflow is located at `.github/workflows/board.yml`:

| Trigger | Description | Jobs Executed |
| :--- | :--- | :--- |
| **Scheduled (06:10, 07:40, 10:10 UTC)** | Daily curation and site deployment. Subsequent slots exit in seconds if today is already published. | `lint`, `typecheck`, `security`, `test`, `digest`, `pages` |
| **Workflow Dispatch ("curate" checked)** | Manual run to curate today's stories and update the archive. | `lint`, `typecheck`, `security`, `test`, `digest`, `pages` |
| **Workflow Dispatch ("curate" unchecked)** | Recompiles and redeploys the site from existing archive files without calling the LLM. | `lint`, `typecheck`, `security`, `test`, `pages` |
| **Push to `main`** | Triggered when config, code, or archives are pushed. Redeploys site immediately. | `lint`, `typecheck`, `security`, `test`, `pages` |
| **Pull Request** | Validates code style, types, secrets, and test suite. | `lint`, `typecheck`, `security`, `test` |

---

## 3. External Daily Runner (GitLab Webhook)

Because GitHub's scheduled cron runners can occasionally experience queue delays under platform load, an external scheduler can trigger the workflow via the GitHub API:
- Endpoint: `POST /repos/{owner}/{repo}/actions/workflows/board.yml/dispatches`
- Payload: `{"ref": "main", "inputs": {"curate": true, "only_if_due": true}}`
- When `only_if_due: true` is passed, the job immediately exits if today's YAML archive already exists.
