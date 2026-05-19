"""Tests for team/discovery.py — team discovery from Jira bug data."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from cnv_bug_triage.schemas.config import TeamMember
from cnv_bug_triage.team.discovery import (
    TeamCache,
    build_discovery_jql,
    extract_keywords,
    extract_team_from_issues,
    format_team_report,
    load_team_cache,
    save_team_cache,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_issue(
    key: str = "CNV-100",
    summary: str = "Test bug",
    assignee_id: str | None = None,
    assignee_name: str = "",
    qa_contact_id: str | None = None,
    qa_contact_name: str = "",
    labels: list[str] | None = None,
    components: list[str] | None = None,
    qa_field: str = "customfield_12315948",
) -> SimpleNamespace:
    fields_dict = {
        "summary": summary,
        "assignee": (
            SimpleNamespace(accountId=assignee_id, displayName=assignee_name)
            if assignee_id else None
        ),
        "labels": labels or [],
        "components": [
            SimpleNamespace(name=c) for c in (components or [])
        ],
        qa_field: (
            SimpleNamespace(accountId=qa_contact_id, displayName=qa_contact_name)
            if qa_contact_id else None
        ),
    }
    return SimpleNamespace(key=key, fields=SimpleNamespace(**fields_dict))


# ── build_discovery_jql ──────────────────────────────────────────


class TestBuildDiscoveryJql:
    def test_targets_resolved_statuses(self, sample_cfg):
        jql = build_discovery_jql(sample_cfg)
        assert '"Closed"' in jql
        assert '"Verified"' in jql
        assert '"Resolved"' in jql

    def test_includes_project(self, sample_cfg):
        jql = build_discovery_jql(sample_cfg)
        assert 'project = "TestProject"' in jql

    def test_includes_issue_types(self, sample_cfg):
        jql = build_discovery_jql(sample_cfg)
        assert '"Bug"' in jql
        assert '"Vulnerability"' in jql

    def test_includes_component(self, sample_cfg):
        jql = build_discovery_jql(sample_cfg)
        assert 'component = "TestComponent"' in jql

    def test_no_component_when_empty(self, sample_cfg):
        sample_cfg.filters.component = ""
        jql = build_discovery_jql(sample_cfg)
        assert "component" not in jql

    def test_custom_days(self, sample_cfg):
        jql = build_discovery_jql(sample_cfg, days=90)
        assert "resolved >= -90d" in jql

    def test_default_days(self, sample_cfg):
        jql = build_discovery_jql(sample_cfg)
        assert "resolved >= -180d" in jql


# ── extract_keywords ─────────────────────────────────────────────


class TestExtractKeywords:
    def test_frequent_words_returned(self):
        summaries = [
            "VM migration fails during upgrade",
            "Live migration broken after upgrade",
            "Migration timeout on upgrade path",
        ]
        keywords = extract_keywords(summaries, min_freq=2)
        assert "migration" in keywords
        assert "upgrade" in keywords

    def test_stop_words_filtered(self):
        summaries = [
            "Bug in the test with error",
            "Bug in the test with error again",
            "Bug in the test with error once more",
        ]
        keywords = extract_keywords(summaries, min_freq=2)
        assert "bug" not in keywords
        assert "the" not in keywords
        assert "error" not in keywords
        assert "test" not in keywords

    def test_min_frequency_threshold(self):
        summaries = [
            "migration fails",
            "storage broken",
            "network down",
        ]
        keywords = extract_keywords(summaries, min_freq=2)
        assert keywords == []

    def test_max_results_capped(self):
        summaries = [f"word{i} appears here" for i in range(20)] * 3
        keywords = extract_keywords(summaries, min_freq=2, top_n=5)
        assert len(keywords) <= 5

    def test_empty_summaries(self):
        assert extract_keywords([]) == []
        assert extract_keywords(["", ""]) == []

    def test_dedup_per_summary(self):
        summaries = [
            "migration migration migration migration",
        ]
        keywords = extract_keywords(summaries, min_freq=1)
        assert "migration" in keywords

    def test_short_tokens_excluded(self):
        summaries = ["VM is up", "VM is up", "VM is up"]
        keywords = extract_keywords(summaries, min_freq=2)
        assert "is" not in keywords
        assert "up" not in keywords


# ── extract_team_from_issues ─────────────────────────────────────


class TestExtractTeamFromIssues:
    def test_assignee_becomes_dev(self, sample_cfg):
        issues = [
            _make_issue(assignee_id="dev-1", assignee_name="Alice"),
            _make_issue(assignee_id="dev-1", assignee_name="Alice"),
        ]
        members = extract_team_from_issues(issues, sample_cfg)
        alice = next(m for m in members if m.account_id == "dev-1")
        assert alice.role == "dev"

    def test_qa_contact_becomes_qe(self, sample_cfg):
        issues = [
            _make_issue(qa_contact_id="qe-1", qa_contact_name="Bob"),
            _make_issue(qa_contact_id="qe-1", qa_contact_name="Bob"),
        ]
        members = extract_team_from_issues(issues, sample_cfg)
        bob = next(m for m in members if m.account_id == "qe-1")
        assert bob.role == "qe"

    def test_both_roles(self, sample_cfg):
        issues = [
            _make_issue(
                assignee_id="both-1", assignee_name="Carol",
                qa_contact_id="both-1", qa_contact_name="Carol",
            ),
            _make_issue(
                assignee_id="both-1", assignee_name="Carol",
            ),
        ]
        members = extract_team_from_issues(issues, sample_cfg)
        carol = next(m for m in members if m.account_id == "both-1")
        assert carol.role == "both"

    def test_min_bug_count_filters_low_activity(self, sample_cfg):
        issues = [
            _make_issue(assignee_id="one-timer", assignee_name="Ghost"),
        ]
        members = extract_team_from_issues(issues, sample_cfg)
        assert not any(m.account_id == "one-timer" for m in members)

    def test_components_in_areas(self, sample_cfg):
        issues = [
            _make_issue(
                assignee_id="dev-1", assignee_name="Alice",
                components=["HCO"],
            ),
            _make_issue(
                assignee_id="dev-1", assignee_name="Alice",
                components=["HCO", "CDI"],
            ),
        ]
        members = extract_team_from_issues(issues, sample_cfg)
        alice = next(m for m in members if m.account_id == "dev-1")
        assert "hco" in alice.areas

    def test_labels_in_areas(self, sample_cfg):
        issues = [
            _make_issue(
                assignee_id="dev-1", assignee_name="Alice",
                labels=["upgrade", "upgrade", "install"],
            ),
            _make_issue(
                assignee_id="dev-1", assignee_name="Alice",
                labels=["upgrade"],
            ),
        ]
        members = extract_team_from_issues(issues, sample_cfg)
        alice = next(m for m in members if m.account_id == "dev-1")
        assert "upgrade" in alice.areas

    def test_sorted_by_name(self, sample_cfg):
        issues = [
            _make_issue(assignee_id="z-1", assignee_name="Zara"),
            _make_issue(assignee_id="z-1", assignee_name="Zara"),
            _make_issue(assignee_id="a-1", assignee_name="Anna"),
            _make_issue(assignee_id="a-1", assignee_name="Anna"),
        ]
        members = extract_team_from_issues(issues, sample_cfg)
        names = [m.name for m in members]
        assert names == sorted(names)

    def test_empty_issues(self, sample_cfg):
        assert extract_team_from_issues([], sample_cfg) == []

    def test_no_assignee_or_qa(self, sample_cfg):
        issues = [_make_issue(), _make_issue()]
        assert extract_team_from_issues(issues, sample_cfg) == []


# ── TeamCache ────────────────────────────────────────────────────


class TestTeamCache:
    def test_round_trip(self):
        members = [
            TeamMember("id-1", "Alice", "dev", ["hco", "upgrade"]),
            TeamMember("id-2", "Bob", "qe", ["storage"]),
        ]
        cache = TeamCache(
            discovered_at="2026-05-19 14:00 UTC",
            lookback_days=180,
            bug_count=42,
            members=members,
        )
        restored = TeamCache.from_dict(cache.to_dict())
        assert restored.discovered_at == cache.discovered_at
        assert restored.lookback_days == cache.lookback_days
        assert restored.bug_count == cache.bug_count
        assert len(restored.members) == 2
        assert restored.members[0].name == "Alice"
        assert restored.members[0].areas == ["hco", "upgrade"]
        assert restored.members[1].role == "qe"

    def test_from_dict_defaults(self):
        cache = TeamCache.from_dict({})
        assert cache.discovered_at == ""
        assert cache.lookback_days == 180
        assert cache.bug_count == 0
        assert cache.members == []


# ── Cache I/O ────────────────────────────────────────────────────


class TestCacheIO:
    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "cache.yaml")
        members = [TeamMember("id-1", "Alice", "dev", ["hco"])]
        cache = TeamCache("2026-05-19", 180, 10, members)
        save_team_cache(cache, path=path)
        loaded = load_team_cache(path=path)
        assert loaded is not None
        assert len(loaded.members) == 1
        assert loaded.members[0].name == "Alice"
        assert loaded.discovered_at == "2026-05-19"

    def test_load_missing_file(self, tmp_path):
        result = load_team_cache(path=str(tmp_path / "nope.yaml"))
        assert result is None

    def test_load_corrupt_file(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("not: [valid: yaml: {{", encoding="utf-8")
        result = load_team_cache(path=str(bad))
        assert result is None

    def test_load_non_mapping(self, tmp_path):
        bad = tmp_path / "list.yaml"
        bad.write_text("- item1\n- item2\n", encoding="utf-8")
        result = load_team_cache(path=str(bad))
        assert result is None

    def test_cache_file_is_valid_yaml(self, tmp_path):
        path = str(tmp_path / "cache.yaml")
        members = [TeamMember("id-1", "Alice", "dev", ["hco"])]
        cache = TeamCache("2026-05-19", 90, 5, members)
        save_team_cache(cache, path=path)
        raw = yaml.safe_load(open(path, encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["bug_count"] == 5
        assert raw["lookback_days"] == 90


# ── format_team_report ───────────────────────────────────────────


class TestFormatTeamReport:
    def _make_cache(self) -> TeamCache:
        return TeamCache(
            discovered_at="2026-05-19 14:00 UTC",
            lookback_days=180,
            bug_count=100,
            members=[
                TeamMember("d1", "Alice Dev", "dev", ["hco", "upgrade"]),
                TeamMember("d2", "Bob Dev", "dev", ["storage"]),
                TeamMember("q1", "Carol QE", "qe", ["hco", "install"]),
                TeamMember("b1", "Dana Both", "both", ["networking"]),
            ],
        )

    def test_contains_member_names(self):
        report = format_team_report(self._make_cache())
        assert "Alice Dev" in report
        assert "Bob Dev" in report
        assert "Carol QE" in report
        assert "Dana Both" in report

    def test_shows_dev_and_qe_sections(self):
        report = format_team_report(self._make_cache())
        assert "DEVELOPERS" in report
        assert "QE ENGINEERS" in report

    def test_shows_bug_count(self):
        report = format_team_report(self._make_cache())
        assert "100 resolved bugs" in report

    def test_shows_totals(self):
        report = format_team_report(self._make_cache())
        assert "4 members" in report

    def test_both_tagged_in_devs(self):
        report = format_team_report(self._make_cache())
        assert "[also QE]" in report

    def test_areas_displayed(self):
        report = format_team_report(self._make_cache())
        assert "hco, upgrade" in report
        assert "storage" in report

    def test_empty_team(self):
        cache = TeamCache("2026-05-19", 180, 0, [])
        report = format_team_report(cache)
        assert "0 members" in report


# ── CLI flags ────────────────────────────────────────────────────


class TestDiscoverTeamCLI:
    def test_discover_team_flag(self):
        from cnv_bug_triage.cli import build_parser
        args = build_parser().parse_args(["--discover-team"])
        assert args.discover_team is True

    def test_discover_team_default_false(self):
        from cnv_bug_triage.cli import build_parser
        args = build_parser().parse_args([])
        assert args.discover_team is False

    def test_discovery_days_default(self):
        from cnv_bug_triage.cli import build_parser
        args = build_parser().parse_args(["--discover-team"])
        assert args.discovery_days == 180

    def test_discovery_days_custom(self):
        from cnv_bug_triage.cli import build_parser
        args = build_parser().parse_args(["--discover-team", "--discovery-days", "90"])
        assert args.discovery_days == 90
