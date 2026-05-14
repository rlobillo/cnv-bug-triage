"""Tests for jira/client.py — JQL building, retry, auth."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cnv_bug_triage.jira.client import (
    _escape_jql,
    build_bug_jql,
    days_since_last_agent_comment,
    get_jira_client,
    search_all,
)
from cnv_bug_triage.schemas.config import AppConfig


class TestEscapeJql:
    def test_plain_string(self):
        assert _escape_jql("hello") == "hello"

    def test_quotes_escaped(self):
        assert _escape_jql('say "hi"') == 'say \\"hi\\"'

    def test_backslash_escaped(self):
        assert _escape_jql("path\\to") == "path\\\\to"


class TestBuildBugJql:
    def test_default_filters(self, sample_cfg):
        jql = build_bug_jql(sample_cfg)
        assert '"TestProject"' in jql
        assert '"Bug"' in jql
        assert '"Vulnerability"' in jql
        assert '"Closed"' in jql
        assert '"TestComponent"' in jql

    def test_extra_jql_appended(self, sample_cfg):
        sample_cfg.filters.extra_jql = "AND labels = 'test'"
        jql = build_bug_jql(sample_cfg)
        assert "AND labels = 'test'" in jql

    def test_no_component(self, sample_cfg):
        sample_cfg.filters.component = ""
        jql = build_bug_jql(sample_cfg)
        assert "component" not in jql


class TestGetJiraClient:
    def test_missing_token_raises(self, sample_cfg):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="JIRA_TOKEN"):
                get_jira_client(sample_cfg)

    @patch("cnv_bug_triage.jira.client.JIRA")
    def test_basic_auth_with_email(self, mock_jira, sample_cfg):
        with patch.dict("os.environ", {"JIRA_TOKEN": "tok", "JIRA_EMAIL": "a@b.c"}):
            get_jira_client(sample_cfg)
        mock_jira.assert_called_once_with(
            server=sample_cfg.jira.url,
            basic_auth=("a@b.c", "tok"),
        )

    @patch("cnv_bug_triage.jira.client.JIRA")
    def test_token_auth_without_email(self, mock_jira, sample_cfg):
        with patch.dict("os.environ", {"JIRA_TOKEN": "tok"}, clear=True):
            get_jira_client(sample_cfg)
        mock_jira.assert_called_once_with(
            server=sample_cfg.jira.url,
            token_auth="tok",
        )

    @patch("cnv_bug_triage.jira.client.JIRA")
    def test_url_env_override(self, mock_jira, sample_cfg):
        with patch.dict("os.environ", {"JIRA_TOKEN": "tok", "JIRA_URL": "https://custom.example.com"}):
            get_jira_client(sample_cfg)
        mock_jira.assert_called_once_with(
            server="https://custom.example.com",
            token_auth="tok",
        )


class TestSearchAll:
    def test_single_page(self):
        client = MagicMock()
        client.search_issues.return_value = ["a", "b"]
        result = search_all(client, "project = X", page_size=10)
        assert result == ["a", "b"]
        client.search_issues.assert_called_once()

    def test_pagination(self):
        client = MagicMock()
        page1 = list(range(3))
        page2 = [3, 4]
        client.search_issues.side_effect = [page1, page2]
        result = search_all(client, "project = X", page_size=3)
        assert result == [0, 1, 2, 3, 4]
        assert client.search_issues.call_count == 2


class TestDaysSinceLastAgentComment:
    def test_no_agent_comment(self):
        issue = MagicMock()
        issue.fields.comment.comments = [
            MagicMock(body="User comment", created="2026-05-10T10:00:00+0000"),
        ]
        client = MagicMock()
        client.issue.return_value = issue
        result = days_since_last_agent_comment(client, "CNV-1", "[Bug Triage Agent]")
        assert result is None

    def test_agent_comment_found(self):
        issue = MagicMock()
        issue.fields.comment.comments = [
            MagicMock(body="[Bug Triage Agent] analysis", created="2026-05-13T10:00:00+0000"),
        ]
        client = MagicMock()
        client.issue.return_value = issue
        result = days_since_last_agent_comment(client, "CNV-1", "[Bug Triage Agent]")
        assert result is not None
        assert isinstance(result, float)

    def test_exception_returns_none(self):
        client = MagicMock()
        client.issue.side_effect = Exception("network error")
        result = days_since_last_agent_comment(client, "CNV-1", "[Bug Triage Agent]")
        assert result is None

    def test_no_comments_at_all(self):
        issue = MagicMock()
        issue.fields.comment = None
        client = MagicMock()
        client.issue.return_value = issue
        result = days_since_last_agent_comment(client, "CNV-1", "[Bug Triage Agent]")
        assert result is None
