"""Tests for prompts/templates.py — prompt building."""

from __future__ import annotations

import pytest

from cnv_bug_triage.prompts.templates import (
    DUPLICATE_JSON_SCHEMA,
    TRIAGE_JSON_SCHEMA,
    build_duplicate_prompt,
    build_triage_prompt,
)
from tests.conftest import make_bug


class TestBuildTriagePrompt:
    def test_contains_bug_details(self, sample_cfg):
        bug = make_bug(key="CNV-42", summary="VM crash", description="Steps...")
        prompt = build_triage_prompt(bug, sample_cfg, ["priority"])
        assert "CNV-42" in prompt
        assert "VM crash" in prompt

    def test_missing_fields_listed(self, sample_cfg):
        bug = make_bug()
        prompt = build_triage_prompt(bug, sample_cfg, ["priority", "assignee"])
        assert "priority" in prompt
        assert "assignee" in prompt

    def test_team_devs_included_for_assignee(self, sample_cfg):
        bug = make_bug()
        prompt = build_triage_prompt(bug, sample_cfg, ["assignee"])
        assert "Alice Dev" in prompt
        assert "dev-001" in prompt
        assert "HCO" in prompt

    def test_team_qes_included_for_qa_contact(self, sample_cfg):
        bug = make_bug()
        prompt = build_triage_prompt(bug, sample_cfg, ["qa_contact"])
        assert "Carol QE" in prompt
        assert "qe-001" in prompt

    def test_sprints_included_for_sprint(self, sample_cfg):
        bug = make_bug()
        prompt = build_triage_prompt(bug, sample_cfg, ["sprint"])
        assert "Sprint 10" in prompt
        assert "Sprint 11" in prompt
        assert "active" in prompt.lower()

    def test_fix_versions_included(self, sample_cfg):
        bug = make_bug()
        prompt = build_triage_prompt(bug, sample_cfg, ["fix_version"])
        assert "CNV v4.22.0" in prompt
        assert "CNV v4.23.0" in prompt

    def test_release_calendar_included(self, sample_cfg):
        bug = make_bug()
        prompt = build_triage_prompt(bug, sample_cfg, [])
        assert "4.22" in prompt
        assert "ga" in prompt.lower()
        assert "release-4.22" in prompt

    def test_backport_policy_included(self, sample_cfg):
        bug = make_bug()
        prompt = build_triage_prompt(bug, sample_cfg, [])
        assert "Backport critical" in prompt

    def test_description_truncated(self, sample_cfg):
        long_desc = "x" * 5000
        bug = make_bug(description=long_desc)
        prompt = build_triage_prompt(bug, sample_cfg, [])
        assert len(prompt) < len(long_desc)

    def test_no_team_no_crash(self, sample_cfg):
        sample_cfg.team.members.clear()
        bug = make_bug()
        prompt = build_triage_prompt(bug, sample_cfg, ["assignee", "qa_contact"])
        assert "Bug Details" in prompt


class TestBuildDuplicatePrompt:
    def test_contains_bug_key(self):
        bug = make_bug(key="CNV-42", summary="VM crash")
        prompt = build_duplicate_prompt(bug, [], 0.8)
        assert "CNV-42" in prompt

    def test_candidates_listed(self):
        bug = make_bug(key="CNV-42")
        candidates = [
            {"key": "CNV-100", "summary": "Similar crash"},
            {"key": "CNV-101", "summary": "Different issue"},
        ]
        prompt = build_duplicate_prompt(bug, candidates, 0.8)
        assert "CNV-100" in prompt
        assert "CNV-101" in prompt
        assert "Similar crash" in prompt

    def test_threshold_mentioned(self):
        bug = make_bug()
        prompt = build_duplicate_prompt(bug, [], 0.85)
        assert "0.85" in prompt


class TestJsonSchemas:
    def test_triage_schema_structure(self):
        schema = TRIAGE_JSON_SCHEMA["json_schema"]["schema"]
        required = schema["required"]
        assert "priority" in required
        assert "assignee" in required
        assert "qa_contact" in required
        assert "sprint" in required
        assert "fix_version" in required
        assert "backport" in required

    def test_duplicate_schema_structure(self):
        schema = DUPLICATE_JSON_SCHEMA["json_schema"]["schema"]
        assert "duplicates" in schema["required"]
