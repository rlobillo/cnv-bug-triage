"""Tests for jira/fields.py — sprint & user field parsing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cnv_bug_triage.jira.fields import parse_sprint_field, parse_user_field


class TestParseUserField:
    def test_none_returns_empty(self):
        assert parse_user_field(None) == (None, "")

    def test_dict_with_account_id(self):
        assert parse_user_field({
            "accountId": "abc123",
            "displayName": "Alice",
        }) == ("abc123", "Alice")

    def test_dict_with_key_fallback(self):
        assert parse_user_field({
            "key": "bob_key",
            "displayName": "Bob",
        }) == ("bob_key", "Bob")

    def test_dict_missing_name(self):
        assert parse_user_field({"accountId": "x"}) == ("x", "")

    def test_object_with_attributes(self):
        user = SimpleNamespace(accountId="obj-id", displayName="Carol")
        assert parse_user_field(user) == ("obj-id", "Carol")

    def test_object_with_key_fallback(self):
        user = SimpleNamespace(key="key-id", displayName="Dave")
        assert parse_user_field(user) == ("key-id", "Dave")


class TestParseSprintField:
    def test_none_returns_empty(self):
        assert parse_sprint_field(None) == ("", None, "")

    def test_dict_single(self):
        sprint = {"name": "Sprint 1", "id": 42, "state": "ACTIVE"}
        assert parse_sprint_field(sprint) == ("Sprint 1", 42, "active")

    def test_dict_list(self):
        sprints = [
            {"name": "Sprint 1", "id": 10, "state": "closed"},
            {"name": "Sprint 2", "id": 20, "state": "active"},
        ]
        name, sid, state = parse_sprint_field(sprints)
        assert name == "Sprint 2"
        assert sid == 20
        assert state == "active"

    def test_object_form(self):
        sprint = SimpleNamespace(name="Sprint X", id=99, state="future")
        assert parse_sprint_field(sprint) == ("Sprint X", 99, "future")

    def test_greenhopper_string_format(self):
        raw = (
            "com.atlassian.greenhopper.service.sprint.Sprint"
            "@2abc[id=123,rapidViewId=456,"
            "name=IUO Sprint 42,goal=,state=ACTIVE,"
            "startDate=2026-01-01]"
        )
        name, sid, state = parse_sprint_field(raw)
        assert name == "IUO Sprint 42"
        assert sid == 123
        assert state == "active"

    def test_list_of_greenhopper_strings(self):
        closed = (
            "com.atlassian.greenhopper.service.sprint.Sprint"
            "@1[id=100,name=Sprint Old,state=CLOSED]"
        )
        active = (
            "com.atlassian.greenhopper.service.sprint.Sprint"
            "@2[id=200,name=Sprint Current,state=ACTIVE]"
        )
        name, sid, state = parse_sprint_field([closed, active])
        assert name == "Sprint Current"
        assert sid == 200
        assert state == "active"

    def test_active_preferred_over_future(self):
        sprints = [
            {"name": "Future Sprint", "id": 2, "state": "future"},
            {"name": "Active Sprint", "id": 1, "state": "active"},
        ]
        name, sid, state = parse_sprint_field(sprints)
        assert state == "active"
        assert name == "Active Sprint"

    def test_future_preferred_over_closed(self):
        sprints = [
            {"name": "Closed Sprint", "id": 1, "state": "closed"},
            {"name": "Future Sprint", "id": 2, "state": "future"},
        ]
        name, _, state = parse_sprint_field(sprints)
        assert state == "future"
        assert name == "Future Sprint"

    def test_empty_list(self):
        assert parse_sprint_field([]) == ("", None, "")

    def test_dict_without_name(self):
        sprint = {"id": 5, "state": "active"}
        assert parse_sprint_field(sprint) == ("", None, "")
