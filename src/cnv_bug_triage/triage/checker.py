"""Pure triage field checks and result types."""

from __future__ import annotations

from dataclasses import dataclass, field

from cnv_bug_triage.schemas.bug_doc import BugDoc
from cnv_bug_triage.schemas.config import AppConfig


@dataclass
class FieldCheck:
    field_name: str
    is_ok: bool
    current_value: str
    reason: str


@dataclass
class TriageSuggestion:
    field_name: str
    suggested_value: str
    suggested_display: str
    reasoning: str
    source: str = "llm"


@dataclass
class BackportRecommendation:
    version: str
    branch: str
    urgency: str
    reasoning: str


@dataclass
class BackportAnalysis:
    needs_backport: bool
    recommendations: list[BackportRecommendation]
    overall_reasoning: str


@dataclass
class DuplicateCandidate:
    candidate_key: str
    candidate_summary: str
    confidence: float
    reasoning: str


@dataclass
class TriageResult:
    bug: BugDoc
    checks: list[FieldCheck] = field(default_factory=list)
    suggestions: list[TriageSuggestion] = field(default_factory=list)
    backport: BackportAnalysis | None = None
    duplicates: list[DuplicateCandidate] = field(default_factory=list)

    @property
    def is_triaged(self) -> bool:
        return all(c.is_ok for c in self.checks)

    @property
    def missing_fields(self) -> list[str]:
        return [c.field_name for c in self.checks if not c.is_ok]

    def suggestion_for(self, field_name: str) -> TriageSuggestion | None:
        for s in self.suggestions:
            if s.field_name == field_name:
                return s
        return None


def check_triage_fields(bug: BugDoc, cfg: AppConfig) -> list[FieldCheck]:
    placeholder = cfg.triage.placeholder_user_id
    checks: list[FieldCheck] = []

    has_assignee = bool(
        bug.assignee_id
        and bug.assignee_id != placeholder
    )
    checks.append(FieldCheck(
        field_name="assignee",
        is_ok=has_assignee,
        current_value=bug.assignee_name or "(unassigned)",
        reason="" if has_assignee else "No assignee set",
    ))

    has_qa = bool(
        bug.qa_contact_id
        and bug.qa_contact_id != placeholder
    )
    checks.append(FieldCheck(
        field_name="qa_contact",
        is_ok=has_qa,
        current_value=bug.qa_contact_name or "(unassigned)",
        reason="" if has_qa else "No QA contact set",
    ))

    has_sprint = bool(
        bug.sprint_name
        and bug.sprint_state in ("active", "future")
    )
    sprint_display = bug.sprint_name or "(none)"
    if bug.sprint_name and bug.sprint_state == "closed":
        sprint_display = f"{bug.sprint_name} (closed)"
    checks.append(FieldCheck(
        field_name="sprint",
        is_ok=has_sprint,
        current_value=sprint_display,
        reason="" if has_sprint else "No active/future sprint",
    ))

    has_priority = bool(
        bug.priority
        and bug.priority.lower() != "undefined"
    )
    checks.append(FieldCheck(
        field_name="priority",
        is_ok=has_priority,
        current_value=bug.priority or "Undefined",
        reason="" if has_priority else "Priority is Undefined",
    ))

    has_fix_version = bool(bug.fix_versions)
    checks.append(FieldCheck(
        field_name="fix_version",
        is_ok=has_fix_version,
        current_value=", ".join(bug.fix_versions) if bug.fix_versions else "(none)",
        reason="" if has_fix_version else "No fix version set",
    ))

    return checks
