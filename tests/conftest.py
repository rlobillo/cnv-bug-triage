"""Shared fixtures for cnv-bug-triage tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cnv_bug_triage.schemas.bug_doc import BugDoc
from cnv_bug_triage.triage.checker import FieldCheck
from cnv_bug_triage.schemas.config import (
    AppConfig,
    DuplicatesConfig,
    FiltersConfig,
    JiraConfig,
    LLMConfig,
    LLMFeaturesConfig,
    PlanningConfig,
    ReleasesConfig,
    ReleaseVersion,
    SprintOption,
    TeamConfig,
    TeamMember,
    TriageConfig,
)


@pytest.fixture()
def sample_cfg() -> AppConfig:
    return AppConfig(
        jira=JiraConfig(
            url="https://jira.example.com",
            qa_contact_field="customfield_12315948",
            sprint_field="customfield_12310940",
        ),
        filters=FiltersConfig(
            project="TestProject",
            component="TestComponent",
            issue_types=["Bug", "Vulnerability"],
            excluded_statuses=["Closed"],
        ),
        triage=TriageConfig(
            placeholder_user_id="placeholder-id",
            comment_cooldown_days=7,
            comment_prefix="[Bug Triage Agent]",
        ),
        llm=LLMConfig(
            default_model="gpt-4o",
            temperature=0.0,
            features=LLMFeaturesConfig(),
        ),
        team=TeamConfig(members=[
            TeamMember(
                account_id="dev-001",
                name="Alice Dev",
                role="dev",
                areas=["HCO", "upgrade"],
            ),
            TeamMember(
                account_id="dev-002",
                name="Bob Dev",
                role="dev",
                areas=["CDI", "storage"],
            ),
            TeamMember(
                account_id="qe-001",
                name="Carol QE",
                role="qe",
                areas=["HCO", "upgrade", "install"],
            ),
            TeamMember(
                account_id="both-001",
                name="Dana Both",
                role="both",
                areas=["networking", "DPDK"],
            ),
        ]),
        planning=PlanningConfig(
            sprints=[
                SprintOption(id=100, name="Sprint 10", state="active", goal="GA"),
                SprintOption(id=101, name="Sprint 11", state="future", goal="Next"),
            ],
            fix_versions=["CNV v4.22.0", "CNV v4.22.z", "CNV v4.23.0"],
            sprint_guidance="Assign critical to active sprint.",
            fix_version_guidance="Critical to current GA.",
        ),
        releases=ReleasesConfig(
            current_dev="4.23",
            versions=[
                ReleaseVersion("4.23", "dev", "", "", "release-4.23"),
                ReleaseVersion("4.22", "ga", "2026-03-15", "2027-03-15", "release-4.22", "4.22.1"),
                ReleaseVersion("4.21", "maintenance", "2025-10-01", "2026-10-01", "release-4.21", "4.21.4"),
                ReleaseVersion("4.20", "maintenance", "2025-05-01", "2026-05-01", "release-4.20", "4.20.6"),
                ReleaseVersion("4.19", "eol", "2024-12-01", "2025-12-01", "release-4.19", "4.19.8"),
            ],
            backport_policy="Backport critical to all supported versions.",
        ),
        duplicates=DuplicatesConfig(max_candidates=50, threshold=0.8),
    )


def make_bug(
    key: str = "CNV-100",
    summary: str = "Test bug",
    description: str = "Bug description",
    status: str = "NEW",
    issue_type: str = "Bug",
    assignee_id: str | None = None,
    assignee_name: str = "",
    qa_contact_id: str | None = None,
    qa_contact_name: str = "",
    sprint_name: str = "",
    sprint_id: int | None = None,
    sprint_state: str = "",
    priority: str = "Undefined",
    fix_versions: list[str] | None = None,
    labels: list[str] | None = None,
    url: str = "",
) -> BugDoc:
    return BugDoc(
        key=key,
        summary=summary,
        description=description,
        status=status,
        issue_type=issue_type,
        assignee_id=assignee_id,
        assignee_name=assignee_name,
        qa_contact_id=qa_contact_id,
        qa_contact_name=qa_contact_name,
        sprint_name=sprint_name,
        sprint_id=sprint_id,
        sprint_state=sprint_state,
        priority=priority,
        fix_versions=fix_versions or [],
        labels=labels or [],
        url=url or f"https://jira.example.com/browse/{key}",
    )


@pytest.fixture()
def untriaged_bug() -> BugDoc:
    """Bug missing all 5 triage fields."""
    return make_bug()


@pytest.fixture()
def triaged_bug() -> BugDoc:
    """Bug with all 5 triage fields filled."""
    return make_bug(
        key="CNV-200",
        assignee_id="dev-001",
        assignee_name="Alice Dev",
        qa_contact_id="qe-001",
        qa_contact_name="Carol QE",
        sprint_name="Sprint 10",
        sprint_id=100,
        sprint_state="active",
        priority="Major",
        fix_versions=["CNV v4.22.0"],
    )


def make_jira_issue(
    key: str = "CNV-100",
    summary: str = "Test bug",
    description: str = "Bug description",
    status: str = "NEW",
    issue_type: str = "Bug",
    assignee: dict | None = None,
    priority: str = "Undefined",
    fix_versions: list[dict] | None = None,
    sprint_field: str = "customfield_12310940",
    sprint_value: object = None,
    qa_contact_field: str = "customfield_12315948",
    qa_contact_value: object = None,
    labels: list[str] | None = None,
) -> SimpleNamespace:
    """Build a mock Jira issue object matching the jira library structure."""
    fields_dict: dict = {
        "summary": summary,
        "description": description,
        "status": SimpleNamespace(name=status),
        "issuetype": SimpleNamespace(name=issue_type),
        "assignee": (
            SimpleNamespace(accountId=assignee["id"], displayName=assignee["name"])
            if assignee else None
        ),
        "priority": SimpleNamespace(name=priority),
        "fixVersions": [
            SimpleNamespace(name=v["name"]) for v in (fix_versions or [])
        ],
        "labels": labels or [],
        sprint_field: sprint_value,
        qa_contact_field: qa_contact_value,
    }
    fields = SimpleNamespace(**fields_dict)
    return SimpleNamespace(key=key, fields=fields)


def passing_check(field: str) -> FieldCheck:
    return FieldCheck(field_name=field, is_ok=True, current_value="set", reason="ok")


def failing_check(field: str) -> FieldCheck:
    return FieldCheck(field_name=field, is_ok=False, current_value="", reason="missing")
