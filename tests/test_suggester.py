"""Tests for llm/suggester.py — LLM response validation logic.

These tests exercise the extraction/validation functions directly,
mocking the LLM call itself.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cnv_bug_triage.llm.suggester import (
    _extract_backport,
    _extract_fix_version,
    _extract_person,
    _extract_priority,
    _extract_sprint,
    suggest_triage,
)
from cnv_bug_triage.triage.checker import BackportAnalysis, TriageSuggestion
from tests.conftest import make_bug


class TestExtractPriority:
    def test_valid_priority(self, sample_cfg):
        result = _extract_priority(
            {"value": "Major", "reasoning": "High impact"},
            sample_cfg,
        )
        assert result is not None
        assert result.suggested_value == "Major"
        assert result.reasoning == "High impact"

    def test_invalid_priority_rejected(self, sample_cfg):
        result = _extract_priority(
            {"value": "Urgent", "reasoning": "Made up"},
            sample_cfg,
        )
        assert result is None

    def test_none_data(self, sample_cfg):
        assert _extract_priority(None, sample_cfg) is None

    def test_case_normalization(self, sample_cfg):
        result = _extract_priority(
            {"value": "critical", "reasoning": "test"},
            sample_cfg,
        )
        assert result is not None
        assert result.suggested_value == "Critical"

    def test_feature_disabled(self, sample_cfg):
        sample_cfg.llm.features.suggest_priority = False
        result = _extract_priority(
            {"value": "Major", "reasoning": "test"},
            sample_cfg,
        )
        assert result is None


class TestExtractPerson:
    def test_valid_dev(self, sample_cfg):
        result = _extract_person(
            {"account_id": "dev-001", "name": "Alice Dev", "reasoning": "HCO expert"},
            "assignee", sample_cfg, role="dev",
        )
        assert result is not None
        assert result.suggested_display == "Alice Dev"
        assert result.suggested_value == "dev-001"

    def test_unknown_account_rejected(self, sample_cfg):
        result = _extract_person(
            {"account_id": "unknown-999", "name": "Ghost", "reasoning": "test"},
            "assignee", sample_cfg, role="dev",
        )
        assert result is None

    def test_wrong_role_rejected(self, sample_cfg):
        result = _extract_person(
            {"account_id": "qe-001", "name": "Carol QE", "reasoning": "test"},
            "assignee", sample_cfg, role="dev",
        )
        assert result is None

    def test_valid_qe(self, sample_cfg):
        result = _extract_person(
            {"account_id": "qe-001", "name": "Carol QE", "reasoning": "QE expert"},
            "qa_contact", sample_cfg, role="qe",
        )
        assert result is not None
        assert result.field_name == "qa_contact"

    def test_both_role_accepted_as_dev(self, sample_cfg):
        result = _extract_person(
            {"account_id": "both-001", "name": "Dana Both", "reasoning": "test"},
            "assignee", sample_cfg, role="dev",
        )
        assert result is not None

    def test_both_role_accepted_as_qe(self, sample_cfg):
        result = _extract_person(
            {"account_id": "both-001", "name": "Dana Both", "reasoning": "test"},
            "qa_contact", sample_cfg, role="qe",
        )
        assert result is not None

    def test_none_data(self, sample_cfg):
        assert _extract_person(None, "assignee", sample_cfg, role="dev") is None


class TestExtractSprint:
    def test_valid_sprint(self, sample_cfg):
        result = _extract_sprint(
            {"sprint_id": 100, "sprint_name": "Sprint 10", "reasoning": "Active sprint"},
            sample_cfg,
        )
        assert result is not None
        assert result.suggested_display == "Sprint 10"
        assert result.suggested_value == "100"

    def test_unknown_sprint_rejected(self, sample_cfg):
        result = _extract_sprint(
            {"sprint_id": 9999, "sprint_name": "Ghost Sprint", "reasoning": "test"},
            sample_cfg,
        )
        assert result is None

    def test_none_data(self, sample_cfg):
        assert _extract_sprint(None, sample_cfg) is None

    def test_feature_disabled(self, sample_cfg):
        sample_cfg.llm.features.suggest_sprint = False
        result = _extract_sprint(
            {"sprint_id": 100, "sprint_name": "Sprint 10", "reasoning": "test"},
            sample_cfg,
        )
        assert result is None


class TestExtractFixVersion:
    def test_valid_version(self, sample_cfg):
        result = _extract_fix_version(
            {"value": "CNV v4.22.0", "reasoning": "GA target"},
            sample_cfg,
        )
        assert result is not None
        assert result.suggested_value == "CNV v4.22.0"

    def test_unknown_version_rejected(self, sample_cfg):
        result = _extract_fix_version(
            {"value": "CNV v9.99.0", "reasoning": "made up"},
            sample_cfg,
        )
        assert result is None

    def test_none_data(self, sample_cfg):
        assert _extract_fix_version(None, sample_cfg) is None

    def test_feature_disabled(self, sample_cfg):
        sample_cfg.llm.features.suggest_fix_version = False
        result = _extract_fix_version(
            {"value": "CNV v4.22.0", "reasoning": "test"},
            sample_cfg,
        )
        assert result is None


class TestExtractBackport:
    def test_valid_backport(self, sample_cfg):
        result = _extract_backport({
            "needs_backport": True,
            "backport_versions": [
                {"version": "4.21", "branch": "release-4.21", "urgency": "must", "reasoning": "Critical"},
                {"version": "4.20", "branch": "release-4.20", "urgency": "should", "reasoning": "Low risk"},
            ],
            "overall_reasoning": "Backport to all supported",
        }, sample_cfg)
        assert result is not None
        assert result.needs_backport is True
        assert len(result.recommendations) == 2
        assert result.recommendations[0].version == "4.21"
        assert result.recommendations[0].urgency == "must"

    def test_eol_version_filtered_out(self, sample_cfg):
        result = _extract_backport({
            "needs_backport": True,
            "backport_versions": [
                {"version": "4.19", "branch": "release-4.19", "urgency": "must", "reasoning": "EOL"},
            ],
            "overall_reasoning": "test",
        }, sample_cfg)
        assert result is not None
        assert len(result.recommendations) == 0
        assert result.needs_backport is False

    def test_dev_version_filtered_out(self, sample_cfg):
        result = _extract_backport({
            "needs_backport": True,
            "backport_versions": [
                {"version": "4.23", "branch": "release-4.23", "urgency": "must", "reasoning": "Dev"},
            ],
            "overall_reasoning": "test",
        }, sample_cfg)
        assert result is not None
        assert len(result.recommendations) == 0

    def test_no_backport_needed(self, sample_cfg):
        result = _extract_backport({
            "needs_backport": False,
            "backport_versions": [],
            "overall_reasoning": "Minor bug, no backport",
        }, sample_cfg)
        assert result is not None
        assert result.needs_backport is False
        assert result.recommendations == []

    def test_none_data(self, sample_cfg):
        assert _extract_backport(None, sample_cfg) is None

    def test_branch_from_config_overrides_llm(self, sample_cfg):
        result = _extract_backport({
            "needs_backport": True,
            "backport_versions": [
                {"version": "4.22", "branch": "wrong-branch", "urgency": "must", "reasoning": "test"},
            ],
            "overall_reasoning": "test",
        }, sample_cfg)
        assert result.recommendations[0].branch == "release-4.22"


class TestSuggestTriage:
    @patch("cnv_bug_triage.llm.suggester.complete")
    def test_full_suggestion(self, mock_complete, sample_cfg):
        mock_complete.return_value = json.dumps({
            "priority": {"value": "Major", "reasoning": "High impact"},
            "assignee": {"account_id": "dev-001", "name": "Alice Dev", "reasoning": "HCO expert"},
            "qa_contact": {"account_id": "qe-001", "name": "Carol QE", "reasoning": "QE coverage"},
            "sprint": {"sprint_id": 100, "sprint_name": "Sprint 10", "reasoning": "Active"},
            "fix_version": {"value": "CNV v4.22.0", "reasoning": "GA target"},
            "backport": {
                "needs_backport": True,
                "backport_versions": [
                    {"version": "4.21", "branch": "release-4.21", "urgency": "must", "reasoning": "Critical"},
                ],
                "overall_reasoning": "Backport needed",
            },
        })

        bug = make_bug()
        missing = ["priority", "assignee", "qa_contact", "sprint", "fix_version"]
        suggestions, backport = suggest_triage(bug, sample_cfg, missing)

        assert len(suggestions) == 5
        field_names = {s.field_name for s in suggestions}
        assert field_names == {"priority", "assignee", "qa_contact", "sprint", "fix_version"}
        assert backport is not None
        assert backport.needs_backport is True

    @patch("cnv_bug_triage.llm.suggester.complete")
    def test_llm_error_returns_empty(self, mock_complete, sample_cfg):
        from cnv_bug_triage.llm.client import LLMError
        mock_complete.side_effect = LLMError("timeout")

        bug = make_bug()
        suggestions, backport = suggest_triage(bug, sample_cfg, ["priority"])

        assert suggestions == []
        assert backport is None

    @patch("cnv_bug_triage.llm.suggester.complete")
    def test_only_requested_fields(self, mock_complete, sample_cfg):
        mock_complete.return_value = json.dumps({
            "priority": {"value": "Major", "reasoning": "test"},
            "assignee": None,
            "qa_contact": None,
            "sprint": None,
            "fix_version": None,
            "backport": None,
        })

        bug = make_bug()
        suggestions, backport = suggest_triage(bug, sample_cfg, ["priority"])

        field_names = {s.field_name for s in suggestions}
        assert "priority" in field_names
        assert "assignee" not in field_names
