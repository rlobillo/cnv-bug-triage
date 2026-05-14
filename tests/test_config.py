"""Tests for schemas/config.py — AppConfig loading & validation."""

from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from cnv_bug_triage.schemas.config import AppConfig, ConfigError


class TestFromDict:
    def test_minimal_dict(self):
        cfg = AppConfig.from_dict({})
        assert cfg.jira.url == "https://your-instance.atlassian.net"
        assert cfg.llm.default_model == "gpt-4o"
        assert cfg.triage.comment_cooldown_days == 7
        assert cfg.duplicates.threshold == 0.8

    def test_overrides(self):
        cfg = AppConfig.from_dict({
            "jira": {"url": "https://custom.example.com"},
            "llm": {"default_model": "gpt-3.5-turbo", "temperature": 0.5},
            "triage": {"comment_cooldown_days": 14},
        })
        assert cfg.jira.url == "https://custom.example.com"
        assert cfg.llm.default_model == "gpt-3.5-turbo"
        assert cfg.llm.temperature == 0.5
        assert cfg.triage.comment_cooldown_days == 14

    def test_team_members_parsed(self):
        cfg = AppConfig.from_dict({
            "team": {
                "members": [
                    {
                        "account_id": "abc",
                        "name": "Alice",
                        "role": "dev",
                        "areas": ["HCO", "upgrade"],
                    },
                    {
                        "account_id": "def",
                        "name": "Bob",
                        "role": "qe",
                        "areas": ["CDI"],
                    },
                ],
            },
        })
        assert len(cfg.team.members) == 2
        assert cfg.team.members[0].name == "Alice"
        assert cfg.team.members[0].role == "dev"
        assert cfg.team.members[0].areas == ["HCO", "upgrade"]

    def test_team_devs_and_qes(self, sample_cfg):
        devs = sample_cfg.team.devs()
        qes = sample_cfg.team.qes()
        assert any(m.name == "Alice Dev" for m in devs)
        assert any(m.name == "Carol QE" for m in qes)
        assert any(m.name == "Dana Both" for m in devs)
        assert any(m.name == "Dana Both" for m in qes)

    def test_team_by_account_id(self, sample_cfg):
        member = sample_cfg.team.by_account_id("dev-001")
        assert member is not None
        assert member.name == "Alice Dev"
        assert sample_cfg.team.by_account_id("nonexistent") is None

    def test_sprints_parsed(self):
        cfg = AppConfig.from_dict({
            "planning": {
                "sprints": [
                    {"id": 42, "name": "Sprint 42", "state": "active", "goal": "GA"},
                ],
                "fix_versions": ["v1.0"],
            },
        })
        assert len(cfg.planning.sprints) == 1
        assert cfg.planning.sprints[0].id == 42
        assert cfg.planning.sprints[0].state == "active"

    def test_releases_parsed_and_supported(self):
        cfg = AppConfig.from_dict({
            "releases": {
                "current_dev": "4.23",
                "versions": [
                    {"version": "4.23", "status": "dev", "branch": "release-4.23"},
                    {"version": "4.22", "status": "ga", "branch": "release-4.22"},
                    {"version": "4.21", "status": "maintenance", "branch": "release-4.21"},
                    {"version": "4.19", "status": "eol", "branch": "release-4.19"},
                ],
            },
        })
        supported = cfg.releases.supported_versions()
        assert len(supported) == 2
        assert {v.version for v in supported} == {"4.22", "4.21"}

    def test_llm_features_defaults(self):
        cfg = AppConfig.from_dict({})
        assert cfg.llm.features.suggest_priority is True
        assert cfg.llm.features.detect_duplicates is True

    def test_llm_features_override(self):
        cfg = AppConfig.from_dict({
            "llm": {"features": {"suggest_priority": False, "detect_duplicates": False}},
        })
        assert cfg.llm.features.suggest_priority is False
        assert cfg.llm.features.detect_duplicates is False

    def test_filters_extra_jql(self):
        cfg = AppConfig.from_dict({
            "filters": {"extra_jql": "AND labels = 'test'"},
        })
        assert cfg.filters.extra_jql == "AND labels = 'test'"


class TestFromYaml:
    def test_loads_real_config(self):
        cfg = AppConfig.from_yaml("config.yaml.example")
        assert cfg.filters.project == "Your Project"
        assert len(cfg.team.members) > 0

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            AppConfig.from_yaml("nonexistent.yaml")

    def test_non_mapping_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("just a string")
        with pytest.raises(ConfigError, match="YAML mapping"):
            AppConfig.from_yaml(str(p))


class TestValidation:
    def test_negative_cooldown_rejected(self):
        with pytest.raises(ConfigError, match="comment_cooldown_days"):
            AppConfig.from_dict({"triage": {"comment_cooldown_days": -1}})

    def test_temperature_out_of_range(self):
        with pytest.raises(ConfigError, match="temperature"):
            AppConfig.from_dict({"llm": {"temperature": 3.0}})

    def test_max_candidates_zero(self):
        with pytest.raises(ConfigError, match="max_candidates"):
            AppConfig.from_dict({"duplicates": {"max_candidates": 0}})

    def test_threshold_out_of_range(self):
        with pytest.raises(ConfigError, match="threshold"):
            AppConfig.from_dict({"duplicates": {"threshold": 1.5}})

    def test_valid_config_passes(self):
        cfg = AppConfig.from_dict({
            "llm": {"temperature": 1.0},
            "triage": {"comment_cooldown_days": 0},
            "duplicates": {"max_candidates": 1, "threshold": 0.0},
        })
        assert cfg.llm.temperature == 1.0


class TestParsing:
    def test_parse_str_list_from_string(self):
        result = AppConfig._parse_str_list("a, b, c", "test")
        assert result == ["a", "b", "c"]

    def test_parse_str_list_from_list(self):
        result = AppConfig._parse_str_list(["x", "y"], "test")
        assert result == ["x", "y"]

    def test_parse_str_list_bad_type(self):
        with pytest.raises(ConfigError):
            AppConfig._parse_str_list(42, "test")

    def test_parse_int_valid(self):
        assert AppConfig._parse_int("42", "test") == 42

    def test_parse_int_invalid(self):
        with pytest.raises(ConfigError):
            AppConfig._parse_int("abc", "test")

    def test_parse_float_valid(self):
        assert AppConfig._parse_float("0.5", "test") == 0.5

    def test_parse_float_invalid(self):
        with pytest.raises(ConfigError):
            AppConfig._parse_float("abc", "test")
