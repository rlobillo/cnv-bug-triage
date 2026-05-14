"""Tests for runner.py — terminal report formatting and RunResult."""

from __future__ import annotations

from cnv_bug_triage.runner import (
    CommentRecord,
    RunCounters,
    RunResult,
    format_terminal_report,
)
from cnv_bug_triage.triage.checker import (
    BackportAnalysis,
    BackportRecommendation,
    DuplicateCandidate,
    FieldCheck,
    TriageResult,
    TriageSuggestion,
)
from tests.conftest import failing_check, make_bug, passing_check


def _make_run_result(
    results: list[TriageResult] | None = None,
    counters: RunCounters | None = None,
    mode: str = "dry-run",
    model: str = "gpt-4o",
    comment_records: list[CommentRecord] | None = None,
) -> RunResult:
    return RunResult(
        run_id="abc123",
        mode=mode,
        model=model,
        timestamp="2026-05-14 10:00 UTC",
        jql_used="(default filters)",
        results=results or [],
        counters=counters or RunCounters(),
        comment_records=comment_records or [],
    )


class TestFormatTerminalReport:
    def test_header_contains_mode_and_model(self):
        rr = _make_run_result(mode="dry-run", model="gpt-4o")
        report = format_terminal_report(rr)
        assert "DRY-RUN" in report
        assert "gpt-4o" in report

    def test_header_contains_timestamp(self):
        rr = _make_run_result()
        report = format_terminal_report(rr)
        assert "2026-05-14 10:00 UTC" in report

    def test_summary_totals(self):
        counters = RunCounters(total=10, triaged=7, untriaged=3)
        rr = _make_run_result(counters=counters)
        report = format_terminal_report(rr)
        assert "Total:        10" in report
        assert "Triaged:      7 (70%)" in report
        assert "Untriaged:    3 (30%)" in report

    def test_zero_bugs_no_crash(self):
        rr = _make_run_result(counters=RunCounters())
        report = format_terminal_report(rr)
        assert "Total:        0" in report

    def test_untriaged_bug_listed(self):
        bug = make_bug(key="CNV-42", summary="VM crash", issue_type="Bug")
        checks = [
            failing_check("assignee"),
            passing_check("priority"),
        ]
        result = TriageResult(bug=bug, checks=checks)
        counters = RunCounters(total=1, untriaged=1)
        rr = _make_run_result(results=[result], counters=counters)
        report = format_terminal_report(rr)
        assert "CNV-42" in report
        assert "VM crash" in report
        assert "assignee" in report

    def test_suggestions_shown(self):
        bug = make_bug(key="CNV-42")
        checks = [failing_check("priority")]
        suggestion = TriageSuggestion(
            field_name="priority",
            suggested_value="Major",
            suggested_display="Major",
            reasoning="High impact",
            source="llm",
        )
        result = TriageResult(bug=bug, checks=checks, suggestions=[suggestion])
        counters = RunCounters(
            total=1, untriaged=1,
            suggestions_by_field={"priority": 1},
        )
        rr = _make_run_result(results=[result], counters=counters)
        report = format_terminal_report(rr)
        assert "Priority: Major" in report
        assert "High impact" in report
        assert "LLM suggestions: 1" in report

    def test_backport_shown_for_untriaged(self):
        bug = make_bug(key="CNV-42")
        checks = [failing_check("priority")]
        backport = BackportAnalysis(
            needs_backport=True,
            recommendations=[
                BackportRecommendation("4.21", "release-4.21", "must", "Critical"),
            ],
            overall_reasoning="Backport needed",
        )
        result = TriageResult(bug=bug, checks=checks, backport=backport)
        counters = RunCounters(
            total=1, untriaged=1, backport_needed=1,
            backport_by_urgency={"must": 1},
        )
        rr = _make_run_result(results=[result], counters=counters)
        report = format_terminal_report(rr)
        assert "4.21 (MUST)" in report
        assert "Backport needed: 1" in report

    def test_backport_shown_for_triaged(self):
        bug = make_bug(
            key="CNV-99",
            assignee_id="dev-001", assignee_name="Alice",
            qa_contact_id="qe-001", qa_contact_name="Carol",
            sprint_name="Sprint 10", sprint_id=100, sprint_state="active",
            priority="Major", fix_versions=["CNV v4.22.0"],
        )
        checks = [passing_check(f) for f in ["assignee", "qa_contact", "sprint", "priority", "fix_version"]]
        backport = BackportAnalysis(
            needs_backport=True,
            recommendations=[
                BackportRecommendation("4.21", "release-4.21", "should", "Low risk"),
            ],
            overall_reasoning="test",
        )
        result = TriageResult(bug=bug, checks=checks, backport=backport)
        counters = RunCounters(total=1, triaged=1, backport_needed=1)
        rr = _make_run_result(results=[result], counters=counters)
        report = format_terminal_report(rr)
        assert "TRIAGED BUGS NEEDING BACKPORT" in report
        assert "CNV-99" in report

    def test_duplicates_shown(self):
        bug = make_bug(key="CNV-42")
        checks = [failing_check("priority")]
        dup = DuplicateCandidate(
            candidate_key="CNV-99",
            candidate_summary="Similar",
            confidence=0.85,
            reasoning="Same trace",
        )
        result = TriageResult(bug=bug, checks=checks, duplicates=[dup])
        counters = RunCounters(total=1, untriaged=1, duplicates_found=1)
        rr = _make_run_result(results=[result], counters=counters)
        report = format_terminal_report(rr)
        assert "CNV-99" in report
        assert "85%" in report
        assert "Duplicates found: 1" in report

    def test_apply_mode_shows_comment_stats(self):
        counters = RunCounters(
            total=2, untriaged=2,
            comments_posted=1, comments_skipped=1,
        )
        rr = _make_run_result(mode="apply", counters=counters)
        report = format_terminal_report(rr)
        assert "posted=1" in report
        assert "skipped=1" in report

    def test_dry_run_hides_comment_stats(self):
        counters = RunCounters(total=1, triaged=1)
        rr = _make_run_result(mode="dry-run", counters=counters)
        report = format_terminal_report(rr)
        assert "Comments:" not in report
