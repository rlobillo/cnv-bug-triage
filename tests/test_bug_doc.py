"""Tests for schemas/bug_doc.py — BugDoc.from_jira."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cnv_bug_triage.schemas.bug_doc import BugDoc
from cnv_bug_triage.schemas.config import AppConfig
from tests.conftest import make_jira_issue


class TestBugDocFromJira:
    def test_basic_fields(self, sample_cfg):
        issue = make_jira_issue(
            key="CNV-999",
            summary="VM crash on upgrade",
            description="Steps to reproduce...",
            status="NEW",
            issue_type="Bug",
            priority="Major",
        )
        bug = BugDoc.from_jira(issue, sample_cfg)
        assert bug.key == "CNV-999"
        assert bug.summary == "VM crash on upgrade"
        assert bug.description == "Steps to reproduce..."
        assert bug.status == "NEW"
        assert bug.issue_type == "Bug"
        assert bug.priority == "Major"

    def test_assignee_extraction(self, sample_cfg):
        issue = make_jira_issue(
            assignee={"id": "user-123", "name": "Alice"},
        )
        bug = BugDoc.from_jira(issue, sample_cfg)
        assert bug.assignee_id == "user-123"
        assert bug.assignee_name == "Alice"

    def test_no_assignee(self, sample_cfg):
        issue = make_jira_issue(assignee=None)
        bug = BugDoc.from_jira(issue, sample_cfg)
        assert bug.assignee_id is None
        assert bug.assignee_name == ""

    def test_fix_versions(self, sample_cfg):
        issue = make_jira_issue(
            fix_versions=[{"name": "CNV v4.22.0"}, {"name": "CNV v4.22.z"}],
        )
        bug = BugDoc.from_jira(issue, sample_cfg)
        assert bug.fix_versions == ["CNV v4.22.0", "CNV v4.22.z"]

    def test_empty_fix_versions(self, sample_cfg):
        issue = make_jira_issue(fix_versions=[])
        bug = BugDoc.from_jira(issue, sample_cfg)
        assert bug.fix_versions == []

    def test_sprint_dict(self, sample_cfg):
        sprint = {"name": "Sprint 10", "id": 100, "state": "active"}
        issue = make_jira_issue(sprint_value=sprint)
        bug = BugDoc.from_jira(issue, sample_cfg)
        assert bug.sprint_name == "Sprint 10"
        assert bug.sprint_id == 100
        assert bug.sprint_state == "active"

    def test_qa_contact_dict(self, sample_cfg):
        qa = SimpleNamespace(accountId="qa-abc", displayName="QA Person")
        issue = make_jira_issue(qa_contact_value=qa)
        bug = BugDoc.from_jira(issue, sample_cfg)
        assert bug.qa_contact_id == "qa-abc"
        assert bug.qa_contact_name == "QA Person"

    def test_url_construction(self, sample_cfg):
        issue = make_jira_issue(key="CNV-555")
        bug = BugDoc.from_jira(issue, sample_cfg)
        assert bug.url == "https://jira.example.com/browse/CNV-555"

    def test_labels(self, sample_cfg):
        issue = make_jira_issue(labels=["blocker", "regression"])
        bug = BugDoc.from_jira(issue, sample_cfg)
        assert bug.labels == ["blocker", "regression"]

    def test_undefined_priority_default(self, sample_cfg):
        issue = make_jira_issue()
        issue.fields.priority = None
        bug = BugDoc.from_jira(issue, sample_cfg)
        assert bug.priority == "Undefined"
