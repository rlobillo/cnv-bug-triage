# cnv-bug-triage

LLM-assisted bug triage agent for Jira. Scans open bugs, identifies missing triage fields, uses an LLM to suggest intelligent values, detects duplicates, and evaluates backport needs.

**The tool never modifies bug fields.** In `--apply` mode it posts a Jira comment with suggestions. The human decides whether to act.

## What It Does

A bug is considered "triaged" when it has all five fields set: **assignee**, **QA contact**, **sprint** (active/future), **priority** (not Undefined), and **fixVersion**.

| Mode | Behavior |
|------|----------|
| Default (dry-run) | Fetch bugs, check triage fields, LLM suggests values + backport analysis, print report |
| `--apply` | Same + post a structured Jira comment on each untriaged bug |
| `--no-llm` | Report missing fields only, no LLM suggestions |

### LLM Features

- **Priority** — suggests Critical/Major/Normal/Minor/Trivial with reasoning
- **Assignee** — matches bug content against the team expertise map (`role: dev`)
- **QA Contact** — same, filtered to `role: qe`
- **Sprint** — suggests from configured active/future sprints
- **Fix Version** — suggests from configured version list
- **Backport analysis** — evaluates whether the fix needs backporting to older supported versions, based on the release calendar and backport policy
- **Duplicate detection** — compares against open bugs and reports potential duplicates above a confidence threshold

All triage suggestions for a single bug are made in **one LLM call**. Responses are validated against config (team members, sprints, versions, releases) — hallucinated values are rejected.

## Installation

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv sync --extra dev
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `JIRA_TOKEN` | Yes | Jira API token |
| `JIRA_EMAIL` | Yes | Atlassian account email for basic auth |
| `JIRA_URL` | No | Override Jira URL from config |
| `LLM_MODEL` | No | Override LLM model (e.g. `gpt-4o`, `gemini/gemini-2.5-flash`) |
| LLM provider key | Yes | e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` — depends on model |

## Configuration

Copy the example config and fill in your values:

```bash
cp config.yaml.example config.yaml
```

The `config.yaml` file is gitignored to prevent leaking sensitive data (account IDs, internal project names, Jira custom field IDs). Only `config.yaml.example` is tracked — it contains placeholder values.

Key sections to customize:

### Jira & Filters

```yaml
jira:
  url: "https://your-instance.atlassian.net"
  qa_contact_field: "customfield_XXXXX"   # discover with jira.fields()
  sprint_field: "customfield_XXXXX"

filters:
  project: "Your Project"
  component: "Your Component"
  issue_types: [Bug, Vulnerability, Weakness]
  excluded_statuses: [Closed, Verified]
  extra_jql: ""  # e.g. "AND labels = 'my-label'"
```

### Team Expertise Map

The LLM uses this to suggest the right assignee and QA contact based on bug content. You can populate it manually or use automatic discovery:

```bash
# Discover team from resolved bugs (last 180 days)
cnv-bug-triage --discover-team

# Custom lookback period
cnv-bug-triage --discover-team --discovery-days 90
```

This queries Jira for resolved bugs matching your configured filters, extracts assignees and QA contacts, determines each person's role and expertise areas (from components, labels, and summary keywords), and caches the result to `.team_cache.yaml`. Normal triage runs auto-load this cache when `team.members` is empty in config.

You can also configure the team manually in `config.yaml`:

```yaml
team:
  members:
    - account_id: "atlassian-account-id-1"
      name: "Alice Dev"
      role: dev          # dev | qe | both
      areas: [component-a, feature-x, upgrade]
    - account_id: "atlassian-account-id-2"
      name: "Carol QE"
      role: qe
      areas: [component-a, upgrade, install]
```

### Sprint & Version Planning

```yaml
planning:
  sprints:
    - id: 12345
      name: "Sprint 42"
      state: active      # active | future
      goal: "v1.2 GA stabilization"
  fix_versions:
    - "v1.2.0"
    - "v1.2.z"
    - "v1.3.0"
```

### Release Calendar (Backport Analysis)

```yaml
releases:
  current_dev: "1.3"
  versions:
    - version: "1.2"
      status: ga         # dev | ga | maintenance | eol
      ga_date: "2026-03-15"
      eol_date: "2027-03-15"
      branch: "release-1.2"
  backport_policy: >-
    Critical/Security bugs: backport to ALL supported versions...
```

### LLM Features Toggle

Each feature can be individually disabled:

```yaml
llm:
  default_model: "gpt-4o"
  temperature: 0.0
  features:
    suggest_priority: true
    suggest_assignee: true
    suggest_qa_contact: true
    suggest_sprint: true
    suggest_fix_version: true
    suggest_backport: true
    detect_duplicates: true
```

## Usage

```bash
# Dry-run: report triage status with LLM suggestions
cnv-bug-triage

# Single bug
cnv-bug-triage --bug PROJ-12345

# Multiple bugs
cnv-bug-triage --bug PROJ-12345 --bug PROJ-12346

# Post comments on Jira
cnv-bug-triage --apply

# Without LLM (field check only)
cnv-bug-triage --no-llm

# Override model
cnv-bug-triage --model gemini/gemini-2.5-flash

# Custom JQL
cnv-bug-triage --jql "project = PROJ AND status = NEW AND created >= -7d"

# XLSX report
cnv-bug-triage --output report.xlsx

# Custom config
cnv-bug-triage -c /path/to/config.yaml

# Debug logging
cnv-bug-triage -v

# Discover team from Jira history
cnv-bug-triage --discover-team

# Discover with shorter lookback
cnv-bug-triage --discover-team --discovery-days 90
```

## Jira Comment Format

When using `--apply`, the agent posts comments like:

```
[Bug Triage Agent] Triage analysis (run abc123)

This bug is missing the following triage fields:

▸ Priority (currently: Undefined)
  Suggestion: Major
  Reasoning: "Affects live migration on upgrade path."

▸ Assignee (currently: unassigned)
  Suggestion: Alice Dev
  Reasoning: "Bug is in upgrade reconciler, Alice's primary area."

▸ Backport assessment:
  The fix targets v1.2.0. Backport recommended:
  • 1.1 (release-1.1) — MUST: "Critical bug, 1.1 in maintenance."

⚠ Potential duplicates:
  • PROJ-54321 (85%) — "Both describe migration failure during upgrade."
```

A cooldown prevents re-commenting on the same bug within a configurable window (default: 7 days).

## XLSX Report

`--output report.xlsx` generates a multi-sheet workbook:

| Sheet | Content |
|-------|---------|
| Run Info | Metadata, totals, release calendar summary |
| All Bugs | All bugs with triage status |
| Untriaged | Untriaged bugs with LLM suggestions and reasoning |
| Backport | Backport recommendations per bug/version |
| Duplicates | Potential duplicate pairs with confidence |
| Comments | (`--apply` only) Comment posting status |

## Testing

```bash
uv run pytest tests/ -v
```

Tests cover all modules: config parsing/validation, Jira field parsing, triage field checks, LLM response extraction and validation, prompt building, comment generation, terminal report formatting, CLI argument parsing, and XLSX export.

Tests run automatically on every PR via GitHub Actions (Python 3.11, 3.12, 3.13).

## Maintenance

Update these sections in `config.yaml` each release/sprint cycle:

- `planning.sprints` — add new sprints, remove completed ones
- `planning.fix_versions` — update available versions
- `releases.versions` — add new versions, update statuses (ga -> maintenance -> eol)
- `team.members` — add/remove team members, update areas of expertise (or re-run `--discover-team`)

## Project Structure

```
src/cnv_bug_triage/
├── cli.py              # CLI entrypoint
├── runner.py            # Orchestrator pipeline
├── jira/
│   ├── client.py        # Jira auth, search, JQL building
│   └── fields.py        # Sprint/QA contact field parsing
├── triage/
│   ├── checker.py       # Field checks, data models
│   └── commenter.py     # Comment building and posting
├── llm/
│   ├── client.py        # litellm wrapper with retry
│   ├── suggester.py     # Triage field suggestions + backport
│   └── duplicates.py    # Duplicate detection
├── prompts/
│   └── templates.py     # Prompt construction and JSON schemas
├── team/
│   └── discovery.py     # Team discovery from Jira history
├── export/
│   └── xlsx_report.py   # Multi-sheet XLSX workbook
└── schemas/
    ├── config.py        # AppConfig dataclass hierarchy
    └── bug_doc.py       # BugDoc Jira issue model
```
