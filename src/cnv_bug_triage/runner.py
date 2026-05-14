"""Orchestrator pipeline: fetch → check → suggest → report/comment."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from jira import JIRA

from cnv_bug_triage.jira.client import (
    fetch_bug,
    get_jira_client,
    search_bugs,
)
from cnv_bug_triage.llm.duplicates import detect_duplicates
from cnv_bug_triage.llm.suggester import suggest_triage
from cnv_bug_triage.schemas.bug_doc import BugDoc
from cnv_bug_triage.schemas.config import AppConfig
from cnv_bug_triage.triage.checker import TriageResult, check_triage_fields
from cnv_bug_triage.triage.commenter import (
    build_comment_text,
    post_triage_comment,
)

logger = logging.getLogger(__name__)


@dataclass
class RunCounters:
    total: int = 0
    triaged: int = 0
    untriaged: int = 0
    suggestions_by_field: dict[str, int] = field(default_factory=dict)
    backport_needed: int = 0
    backport_by_urgency: dict[str, int] = field(default_factory=dict)
    duplicates_found: int = 0
    comments_posted: int = 0
    comments_skipped: int = 0
    comments_errored: int = 0


@dataclass
class CommentRecord:
    bug_key: str
    status: str
    reason: str
    text: str = ""


@dataclass
class RunResult:
    run_id: str
    mode: str
    model: str
    timestamp: str
    jql_used: str
    results: list[TriageResult]
    counters: RunCounters
    comment_records: list[CommentRecord] = field(default_factory=list)


def _generate_run_id() -> str:
    ts = str(time.time()).encode()
    return hashlib.sha256(ts).hexdigest()[:8]


def run_triage(
    cfg: AppConfig,
    *,
    apply: bool = False,
    bug_keys: list[str] | None = None,
    jql_override: str | None = None,
    use_llm: bool = True,
    model_override: str | None = None,
) -> RunResult:
    run_id = _generate_run_id()
    model = model_override or cfg.llm.default_model
    mode = "apply" if apply else "dry-run"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    client = get_jira_client(cfg)

    if bug_keys:
        raw_issues = [fetch_bug(client, k) for k in bug_keys]
        jql_used = f"key IN ({', '.join(bug_keys)})"
    else:
        jql_used = jql_override if jql_override else "(default filters)"
        raw_issues = search_bugs(client, cfg, jql=jql_override)

    bugs = [BugDoc.from_jira(issue, cfg) for issue in raw_issues]
    logger.info("Fetched %d bugs", len(bugs))

    counters = RunCounters(total=len(bugs))
    results: list[TriageResult] = []
    comment_records: list[CommentRecord] = []

    for bug in bugs:
        checks = check_triage_fields(bug, cfg)
        result = TriageResult(bug=bug, checks=checks)
        missing = result.missing_fields

        if result.is_triaged:
            counters.triaged += 1
        else:
            counters.untriaged += 1

        if use_llm and (missing or cfg.llm.features.suggest_backport):
            suggestions, backport = suggest_triage(
                bug, cfg, missing, model=model,
            )
            result.suggestions = suggestions
            result.backport = backport

            for s in suggestions:
                counters.suggestions_by_field[s.field_name] = (
                    counters.suggestions_by_field.get(s.field_name, 0) + 1
                )

            if backport and backport.needs_backport:
                counters.backport_needed += 1
                for rec in backport.recommendations:
                    counters.backport_by_urgency[rec.urgency] = (
                        counters.backport_by_urgency.get(rec.urgency, 0) + 1
                    )

        if use_llm and cfg.llm.features.detect_duplicates:
            result.duplicates = detect_duplicates(
                bug, bugs, cfg, model=model,
            )
            if result.duplicates:
                counters.duplicates_found += 1

        results.append(result)

        if apply:
            posted, reason = post_triage_comment(
                result, client, cfg, run_id=run_id,
            )
            text = build_comment_text(result, run_id=run_id) if posted else ""
            if posted:
                counters.comments_posted += 1
                status = "posted"
            elif "error" in reason:
                counters.comments_errored += 1
                status = "error"
            else:
                counters.comments_skipped += 1
                status = "skipped"
            comment_records.append(CommentRecord(
                bug_key=bug.key,
                status=status,
                reason=reason,
                text=text,
            ))

    return RunResult(
        run_id=run_id,
        mode=mode,
        model=model if use_llm else "(disabled)",
        timestamp=timestamp,
        jql_used=jql_used,
        results=results,
        counters=counters,
        comment_records=comment_records,
    )


def format_terminal_report(result: RunResult) -> str:
    c = result.counters
    lines: list[str] = []

    header = f"Bug Triage Report ({result.mode.upper()}) — Model: {result.model}"
    lines.append(header)
    lines.append(f"Date: {result.timestamp}")
    lines.append(f"Filters: {result.jql_used}")
    lines.append("=" * 60)
    lines.append("")

    untriaged = [r for r in result.results if not r.is_triaged]
    if untriaged:
        lines.append(f"UNTRIAGED BUGS ({len(untriaged)} of {c.total}):")
        lines.append("")
        for r in untriaged:
            bug = r.bug
            missing_str = ", ".join(r.missing_fields)
            lines.append(f"  {bug.key}  [{bug.issue_type}] {bug.summary}")
            lines.append(f"     Missing: {missing_str}")
            for s in r.suggestions:
                lines.append(
                    f'     → {_field_label(s.field_name)}: '
                    f'{s.suggested_display} — "{s.reasoning}"'
                )
            if r.backport and r.backport.needs_backport:
                bp_parts = [
                    f"{rec.version} ({rec.urgency.upper()})"
                    for rec in r.backport.recommendations
                ]
                lines.append(f"     → Backport: {', '.join(bp_parts)}")
            for dup in r.duplicates:
                pct = int(dup.confidence * 100)
                lines.append(
                    f"     ⚠ Possible dup: {dup.candidate_key} ({pct}%)"
                )
            lines.append("")

    triaged_with_backport = [
        r for r in result.results
        if r.is_triaged and r.backport and r.backport.needs_backport
    ]
    if triaged_with_backport:
        lines.append("TRIAGED BUGS NEEDING BACKPORT:")
        lines.append("")
        for r in triaged_with_backport:
            bug = r.bug
            bp_parts = [
                f"{rec.version} ({rec.urgency.upper()})"
                for rec in r.backport.recommendations
            ]
            lines.append(f"  {bug.key}  [{bug.issue_type}] {bug.summary}")
            lines.append(f"     → Backport: {', '.join(bp_parts)}")
            lines.append("")

    lines.append("SUMMARY:")
    pct = (c.triaged / c.total * 100) if c.total else 0
    lines.append(f"  Total:        {c.total}")
    lines.append(f"  Triaged:      {c.triaged} ({pct:.0f}%)")
    lines.append(f"  Untriaged:    {c.untriaged} ({100 - pct:.0f}%)")

    if c.suggestions_by_field:
        total_sug = sum(c.suggestions_by_field.values())
        field_parts = [
            f"{k}: {v}" for k, v in sorted(c.suggestions_by_field.items())
        ]
        lines.append(
            f"  LLM suggestions: {total_sug} ({', '.join(field_parts)})"
        )

    if c.backport_needed:
        urg_parts = [
            f"{k}: {v}" for k, v in sorted(c.backport_by_urgency.items())
        ]
        lines.append(
            f"  Backport needed: {c.backport_needed} bugs "
            f"({', '.join(urg_parts)})"
        )

    if c.duplicates_found:
        lines.append(f"  Duplicates found: {c.duplicates_found}")

    if result.mode == "apply":
        lines.append(
            f"  Comments: posted={c.comments_posted}, "
            f"skipped={c.comments_skipped}, "
            f"errored={c.comments_errored}"
        )

    return "\n".join(lines)


_FIELD_LABELS = {
    "assignee": "Assignee",
    "qa_contact": "QA Contact",
    "sprint": "Sprint",
    "priority": "Priority",
    "fix_version": "Fix Version",
}


def _field_label(name: str) -> str:
    return _FIELD_LABELS.get(name, name)
