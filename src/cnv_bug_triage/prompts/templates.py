"""System prompt and per-field prompt builders for bug triage."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from cnv_bug_triage.schemas.bug_doc import BugDoc
from cnv_bug_triage.schemas.config import AppConfig

TRIAGE_JSON_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "triage_suggestions",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "priority": {
                    "type": ["object", "null"],
                    "properties": {
                        "value": {"type": "string"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["value", "reasoning"],
                    "additionalProperties": False,
                },
                "assignee": {
                    "type": ["object", "null"],
                    "properties": {
                        "account_id": {"type": "string"},
                        "name": {"type": "string"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["account_id", "name", "reasoning"],
                    "additionalProperties": False,
                },
                "qa_contact": {
                    "type": ["object", "null"],
                    "properties": {
                        "account_id": {"type": "string"},
                        "name": {"type": "string"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["account_id", "name", "reasoning"],
                    "additionalProperties": False,
                },
                "sprint": {
                    "type": ["object", "null"],
                    "properties": {
                        "sprint_id": {"type": "integer"},
                        "sprint_name": {"type": "string"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["sprint_id", "sprint_name", "reasoning"],
                    "additionalProperties": False,
                },
                "fix_version": {
                    "type": ["object", "null"],
                    "properties": {
                        "value": {"type": "string"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["value", "reasoning"],
                    "additionalProperties": False,
                },
                "backport": {
                    "type": ["object", "null"],
                    "properties": {
                        "needs_backport": {"type": "boolean"},
                        "backport_versions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "version": {"type": "string"},
                                    "branch": {"type": "string"},
                                    "urgency": {
                                        "type": "string",
                                        "enum": [
                                            "must", "should", "nice_to_have",
                                        ],
                                    },
                                    "reasoning": {"type": "string"},
                                },
                                "required": [
                                    "version", "branch",
                                    "urgency", "reasoning",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "overall_reasoning": {"type": "string"},
                    },
                    "required": [
                        "needs_backport",
                        "backport_versions",
                        "overall_reasoning",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": [
                "priority", "assignee", "qa_contact",
                "sprint", "fix_version", "backport",
            ],
            "additionalProperties": False,
        },
    },
}

DUPLICATE_JSON_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "duplicate_detection",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "duplicates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "candidate_key": {"type": "string"},
                            "confidence": {"type": "number"},
                            "reasoning": {"type": "string"},
                        },
                        "required": [
                            "candidate_key", "confidence", "reasoning",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["duplicates"],
            "additionalProperties": False,
        },
    },
}

SYSTEM_PROMPT = """\
You are a Jira bug triage assistant for the OpenShift Virtualization (CNV) \
project. Your job is to analyze bugs and suggest values for missing triage \
fields: priority, assignee, QA contact, sprint, and fix version. You also \
assess whether a bug fix needs to be backported to older supported releases.

Be precise and concise in your reasoning. Base suggestions on the bug's \
summary, description, type, and the team expertise/planning context provided.

For priority, use: Critical, Blocker, Major, Normal, Minor, Trivial.

For assignee and QA contact, ONLY suggest people from the provided team list. \
Match based on their expertise areas. Return their exact account_id and name.

For sprint and fix version, ONLY suggest from the provided options list.

For backport analysis, evaluate based on the release calendar, EOL dates, \
and backport policy. Never suggest backporting to EOL versions.

Return null for any field you were not asked to suggest.\
"""


def build_triage_prompt(
    bug: BugDoc,
    cfg: AppConfig,
    missing_fields: list[str],
) -> str:
    sections: list[str] = []

    sections.append(
        f"## Bug Details\n"
        f"- Key: {bug.key}\n"
        f"- Type: {bug.issue_type}\n"
        f"- Summary: {bug.summary}\n"
        f"- Status: {bug.status}\n"
        f"- Current Priority: {bug.priority}\n"
        f"- Current Assignee: {bug.assignee_name or '(unassigned)'}\n"
        f"- Current QA Contact: {bug.qa_contact_name or '(unassigned)'}\n"
        f"- Current Sprint: {bug.sprint_name or '(none)'}\n"
        f"- Current Fix Versions: {', '.join(bug.fix_versions) or '(none)'}\n"
    )

    desc = bug.description[:3000] if bug.description else "(no description)"
    sections.append(f"## Description\n{desc}")

    sections.append(
        f"## Missing Fields to Suggest\n"
        f"{', '.join(missing_fields) if missing_fields else '(none — backport analysis only)'}"
    )

    if "priority" in missing_fields and cfg.llm.features.suggest_priority:
        sections.append(
            "## Priority Guidance\n"
            "Suggest one of: Critical, Blocker, Major, Normal, Minor, Trivial.\n"
            "Consider: impact on users, availability of workaround, "
            "how many versions are affected, security implications."
        )

    if "assignee" in missing_fields and cfg.llm.features.suggest_assignee:
        devs = cfg.team.devs()
        if devs:
            lines = ["## Available Developers"]
            for m in devs:
                lines.append(
                    f"- {m.name} (id: {m.account_id}) — "
                    f"areas: {', '.join(m.areas)}"
                )
            sections.append("\n".join(lines))

    if "qa_contact" in missing_fields and cfg.llm.features.suggest_qa_contact:
        qes = cfg.team.qes()
        if qes:
            lines = ["## Available QE Engineers"]
            for m in qes:
                lines.append(
                    f"- {m.name} (id: {m.account_id}) — "
                    f"areas: {', '.join(m.areas)}"
                )
            sections.append("\n".join(lines))

    if "sprint" in missing_fields and cfg.llm.features.suggest_sprint:
        sprints = cfg.planning.sprints
        if sprints:
            lines = ["## Available Sprints"]
            for s in sprints:
                lines.append(
                    f"- {s.name} (id: {s.id}, state: {s.state}) — "
                    f"goal: {s.goal}"
                )
            if cfg.planning.sprint_guidance:
                lines.append(f"\nGuidance: {cfg.planning.sprint_guidance}")
            sections.append("\n".join(lines))

    if "fix_version" in missing_fields and cfg.llm.features.suggest_fix_version:
        versions = cfg.planning.fix_versions
        if versions:
            lines = ["## Available Fix Versions"]
            for v in versions:
                lines.append(f"- {v}")
            if cfg.planning.fix_version_guidance:
                lines.append(
                    f"\nGuidance: {cfg.planning.fix_version_guidance}"
                )
            sections.append("\n".join(lines))

    if cfg.llm.features.suggest_backport:
        today = date.today().isoformat()
        lines = [f"## Release Calendar (today: {today})"]
        for rv in cfg.releases.versions:
            eol_info = f", EOL: {rv.eol_date}" if rv.eol_date else ""
            ga_info = f", GA: {rv.ga_date}" if rv.ga_date else ""
            z_info = f", latest z-stream: {rv.latest_z}" if rv.latest_z else ""
            lines.append(
                f"- {rv.version} (status: {rv.status}, "
                f"branch: {rv.branch}{ga_info}{eol_info}{z_info})"
            )
        if cfg.releases.backport_policy:
            lines.append(f"\nBackport Policy:\n{cfg.releases.backport_policy}")
        sections.append("\n".join(lines))

    sections.append(
        "## Instructions\n"
        "Return a JSON object with suggestions for the missing fields. "
        "Set fields you were NOT asked to suggest to null. "
        "Always include the backport analysis (unless you have no release "
        "calendar context). "
        "Be specific in your reasoning — reference the bug content, "
        "team expertise areas, sprint goals, or release dates."
    )

    return "\n\n".join(sections)


def build_duplicate_prompt(
    bug: BugDoc,
    candidates: list[dict[str, str]],
    threshold: float,
) -> str:
    lines = [
        f"## Bug to Check\n"
        f"- Key: {bug.key}\n"
        f"- Summary: {bug.summary}\n",
        f"## Open Bugs to Compare Against",
    ]
    for c in candidates:
        lines.append(f"- {c['key']}: {c['summary']}")

    lines.append(
        f"\n## Instructions\n"
        f"Identify which of the candidate bugs are likely duplicates of "
        f"{bug.key}. Only report candidates with confidence >= {threshold} "
        f"(0.0 to 1.0 scale). Consider: similar symptoms, same component, "
        f"overlapping error messages or stack traces. "
        f"Return an empty array if no duplicates found."
    )
    return "\n".join(lines)
