"""Lightweight Jira bug model for triage analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cnv_bug_triage.jira.fields import parse_sprint_field, parse_user_field
from cnv_bug_triage.schemas.config import AppConfig


@dataclass
class BugDoc:
    key: str
    summary: str
    description: str
    status: str
    issue_type: str
    assignee_id: str | None
    assignee_name: str
    qa_contact_id: str | None
    qa_contact_name: str
    sprint_name: str
    sprint_id: int | None
    sprint_state: str
    priority: str
    fix_versions: list[str]
    labels: list[str]
    url: str

    @classmethod
    def from_jira(cls, issue: Any, cfg: AppConfig) -> BugDoc:
        fields = issue.fields

        assignee_id, assignee_name = parse_user_field(
            getattr(fields, "assignee", None),
        )
        qa_contact_id, qa_contact_name = parse_user_field(
            getattr(fields, cfg.jira.qa_contact_field, None),
        )
        sprint_name, sprint_id, sprint_state = parse_sprint_field(
            getattr(fields, cfg.jira.sprint_field, None),
        )

        priority_obj = getattr(fields, "priority", None)
        priority = str(getattr(priority_obj, "name", "Undefined") or "Undefined")

        fix_versions_raw = getattr(fields, "fixVersions", []) or []
        fix_versions = [
            str(getattr(v, "name", "") or "") for v in fix_versions_raw
        ]

        status_obj = getattr(fields, "status", None)
        status = str(getattr(status_obj, "name", "") or "")

        issue_type_obj = getattr(fields, "issuetype", None)
        issue_type = str(getattr(issue_type_obj, "name", "") or "")

        jira_url = cfg.jira.url.rstrip("/")

        return cls(
            key=issue.key,
            summary=str(getattr(fields, "summary", "") or ""),
            description=str(getattr(fields, "description", "") or ""),
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
            fix_versions=fix_versions,
            labels=getattr(fields, "labels", []) or [],
            url=f"{jira_url}/browse/{issue.key}",
        )
