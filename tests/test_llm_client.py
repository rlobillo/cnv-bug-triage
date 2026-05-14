"""Tests for llm/client.py — JSON parsing."""

from __future__ import annotations

import pytest

from cnv_bug_triage.llm.client import parse_json_response


class TestParseJsonResponse:
    def test_plain_json(self):
        result = parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_code_fence(self):
        text = '```json\n{"key": "value"}\n```'
        result = parse_json_response(text)
        assert result == {"key": "value"}

    def test_json_in_plain_code_fence(self):
        text = '```\n{"key": "value"}\n```'
        result = parse_json_response(text)
        assert result == {"key": "value"}

    def test_json_with_surrounding_text(self):
        text = 'Here is the result: {"key": "value"} hope that helps!'
        result = parse_json_response(text)
        assert result == {"key": "value"}

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = parse_json_response(text)
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            parse_json_response("not json at all")

    def test_whitespace_handling(self):
        text = '  \n  {"key": "value"}  \n  '
        result = parse_json_response(text)
        assert result == {"key": "value"}
