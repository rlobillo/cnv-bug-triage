# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

cnv-bug-triage is an LLM-assisted CLI tool that triages CNV (OpenShift Virtualization) bugs on Jira. It finds bugs missing triage fields (assignee, QA contact, sprint, priority, fixVersion), uses an LLM to suggest values, detects duplicates, and evaluates backport needs. The tool **never modifies bug fields** — in `--apply` mode it posts a structured Jira comment with suggestions.

## Common Commands

- Install dependencies: `uv sync`
- Run in report mode: `uv run cnv-bug-triage`
- Run on a single bug: `uv run cnv-bug-triage --bug CNV-12345 -v`
- Run without LLM: `uv run cnv-bug-triage --bug CNV-12345 --no-llm`
- Discover team: `uv run cnv-bug-triage --discover-team`
- Discover team (90 days): `uv run cnv-bug-triage --discover-team --discovery-days 90`
- Post comments: `uv run cnv-bug-triage --apply`
- Generate XLSX: `uv run cnv-bug-triage --output report.xlsx`
- Override model: `uv run cnv-bug-triage --model anthropic/claude-sonnet-4-20250514`

## Required Environment Variables

- `JIRA_TOKEN` — Jira API token (required)
- `JIRA_EMAIL` — Jira email for Cloud basic auth (optional, uses bearer token if omitted)
- `JIRA_URL` — override Jira URL (optional, defaults to config.yaml)
- `LLM_MODEL` — override LLM model (optional)
- LLM provider keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. (depends on model chosen)

## Architecture

```
src/cnv_bug_triage/
├── cli.py              # argparse entrypoint
├── runner.py            # orchestrator: fetch → check → suggest → report/comment
├── jira/
│   ├── client.py        # get_jira_client, search_bugs, build_bug_jql, post_comment
│   └── fields.py        # parse_sprint_field, parse_user_field
├── triage/
│   ├── checker.py       # check_triage_fields → FieldCheck, TriageResult
│   └── commenter.py     # build_comment_text, should_post_comment, post_triage_comment
├── llm/
│   ├── client.py        # complete() litellm wrapper with retry
│   ├── suggester.py     # suggest_triage → (suggestions, backport_analysis)
│   └── duplicates.py    # detect_duplicates → DuplicateCandidate list
├── prompts/
│   └── templates.py     # SYSTEM_PROMPT, TRIAGE_JSON_SCHEMA, build_triage_prompt
├── team/
│   └── discovery.py     # --discover-team: mine Jira history → team roster + cache
├── export/
│   └── xlsx_report.py   # multi-sheet XLSX workbook
└── schemas/
    ├── config.py        # AppConfig dataclass hierarchy with from_yaml()
    └── bug_doc.py       # BugDoc.from_jira() — defensive field extraction
```

## Key Data Flow

0. `cli.py --discover-team` → `team/discovery.py` mines resolved bugs → `.team_cache.yaml`
1. `cli.py` parses args → loads `AppConfig` from config.yaml
2. `runner.run_triage()` orchestrates the pipeline (auto-loads team cache if `team.members` is empty)
3. `jira/client.py` fetches bugs via JQL (configurable filters)
4. `schemas/bug_doc.py` normalizes raw Jira issues into `BugDoc`
5. `triage/checker.py` checks 5 triage fields → `TriageResult`
6. `llm/suggester.py` makes one LLM call per bug → suggestions + backport
7. `llm/duplicates.py` compares against other bugs → `DuplicateCandidate`
8. `triage/commenter.py` builds comment text + posts (with cooldown)
9. `export/xlsx_report.py` writes multi-sheet XLSX

## Config Structure

`config.yaml` is gitignored (contains sensitive data). Copy `config.yaml.example` to `config.yaml` and fill in your values. Key sections: `jira`, `filters`, `triage`, `llm`, `team`, `planning`, `releases`, `duplicates`.

## Conventions

- Single LLM call per bug (combined schema for all suggestions + backport)
- LLM responses are validated against config (team members, sprints, versions, releases)
- Comment cooldown prevents re-commenting within `comment_cooldown_days`
- Backport analysis rejects EOL versions automatically
