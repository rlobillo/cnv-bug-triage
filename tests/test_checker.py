"""Tests for triage/checker.py — field checks and TriageResult."""

from __future__ import annotations

import pytest

from cnv_bug_triage.triage.checker import (
    FieldCheck,
    TriageResult,
    TriageSuggestion,
    check_triage_fields,
)
from tests.conftest import make_bug


class TestCheckTriageFields:
    def test_fully_triaged_bug(self, sample_cfg):
        bug = make_bug(
            assignee_id="dev-001",
            assignee_name="Alice",
            qa_contact_id="qe-001",
            qa_contact_name="Carol",
            sprint_name="Sprint 10",
            sprint_id=100,
            sprint_state="active",
            priority="Major",
            fix_versions=["CNV v4.22.0"],
        )
        checks = check_triage_fields(bug, sample_cfg)
        assert all(c.is_ok for c in checks)
        assert len(checks) == 5

    def test_all_fields_missing(self, sample_cfg):
        bug = make_bug()
        checks = check_triage_fields(bug, sample_cfg)
        missing = [c.field_name for c in checks if not c.is_ok]
        assert set(missing) == {"assignee", "qa_contact", "sprint", "priority", "fix_version"}

    def test_placeholder_assignee_counts_as_missing(self, sample_cfg):
        bug = make_bug(
            assignee_id="placeholder-id",
            assignee_name="Placeholder User",
        )
        checks = check_triage_fields(bug, sample_cfg)
        assignee_check = next(c for c in checks if c.field_name == "assignee")
        assert not assignee_check.is_ok

    def test_closed_sprint_counts_as_missing(self, sample_cfg):
        bug = make_bug(
            sprint_name="Old Sprint",
            sprint_id=50,
            sprint_state="closed",
        )
        checks = check_triage_fields(bug, sample_cfg)
        sprint_check = next(c for c in checks if c.field_name == "sprint")
        assert not sprint_check.is_ok
        assert "(closed)" in sprint_check.current_value

    def test_future_sprint_is_ok(self, sample_cfg):
        bug = make_bug(
            sprint_name="Future Sprint",
            sprint_id=101,
            sprint_state="future",
        )
        checks = check_triage_fields(bug, sample_cfg)
        sprint_check = next(c for c in checks if c.field_name == "sprint")
        assert sprint_check.is_ok

    def test_undefined_priority_is_missing(self, sample_cfg):
        bug = make_bug(priority="Undefined")
        checks = check_triage_fields(bug, sample_cfg)
        priority_check = next(c for c in checks if c.field_name == "priority")
        assert not priority_check.is_ok

    def test_case_insensitive_undefined(self, sample_cfg):
        bug = make_bug(priority="undefined")
        checks = check_triage_fields(bug, sample_cfg)
        priority_check = next(c for c in checks if c.field_name == "priority")
        assert not priority_check.is_ok

    def test_valid_priority_is_ok(self, sample_cfg):
        for p in ["Critical", "Major", "Normal", "Minor"]:
            bug = make_bug(priority=p)
            checks = check_triage_fields(bug, sample_cfg)
            priority_check = next(c for c in checks if c.field_name == "priority")
            assert priority_check.is_ok, f"{p} should be ok"


class TestTriageResult:
    def test_is_triaged_all_ok(self):
        result = TriageResult(
            bug=make_bug(),
            checks=[
                FieldCheck("a", True, "v", ""),
                FieldCheck("b", True, "v", ""),
            ],
        )
        assert result.is_triaged

    def test_is_triaged_one_failing(self):
        result = TriageResult(
            bug=make_bug(),
            checks=[
                FieldCheck("a", True, "v", ""),
                FieldCheck("b", False, "v", "missing"),
            ],
        )
        assert not result.is_triaged

    def test_missing_fields(self):
        result = TriageResult(
            bug=make_bug(),
            checks=[
                FieldCheck("a", False, "", "missing"),
                FieldCheck("b", True, "v", ""),
                FieldCheck("c", False, "", "missing"),
            ],
        )
        assert result.missing_fields == ["a", "c"]

    def test_suggestion_for_found(self):
        sug = TriageSuggestion("priority", "Major", "Major", "reason")
        result = TriageResult(
            bug=make_bug(),
            suggestions=[sug],
        )
        assert result.suggestion_for("priority") is sug

    def test_suggestion_for_not_found(self):
        result = TriageResult(bug=make_bug())
        assert result.suggestion_for("priority") is None
