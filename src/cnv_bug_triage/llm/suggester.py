"""LLM-based triage field suggestions with validation."""

from __future__ import annotations

import logging
from typing import Any

from cnv_bug_triage.llm.client import LLMError, complete, parse_json_response
from cnv_bug_triage.prompts.templates import (
    SYSTEM_PROMPT,
    TRIAGE_JSON_SCHEMA,
    build_triage_prompt,
)
from cnv_bug_triage.schemas.bug_doc import BugDoc
from cnv_bug_triage.schemas.config import AppConfig
from cnv_bug_triage.triage.checker import (
    BackportAnalysis,
    BackportRecommendation,
    TriageSuggestion,
)

logger = logging.getLogger(__name__)


def suggest_triage(
    bug: BugDoc,
    cfg: AppConfig,
    missing_fields: list[str],
    model: str | None = None,
) -> tuple[list[TriageSuggestion], BackportAnalysis | None]:
    """Run a single LLM call to get suggestions for all missing fields + backport.

    Returns (suggestions, backport_analysis).
    Validates LLM output against config (team members, sprints, versions, releases).
    """
    llm_model = model or cfg.llm.default_model
    prompt = build_triage_prompt(bug, cfg, missing_fields)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        raw = complete(
            model=llm_model,
            messages=messages,
            response_format=TRIAGE_JSON_SCHEMA,
            temperature=cfg.llm.temperature,
        )
    except LLMError:
        logger.error("LLM call failed for %s", bug.key, exc_info=True)
        return [], None

    try:
        data = parse_json_response(raw)
    except Exception:
        logger.error(
            "Failed to parse LLM response for %s", bug.key, exc_info=True,
        )
        return [], None

    suggestions: list[TriageSuggestion] = []
    backport: BackportAnalysis | None = None

    if "priority" in missing_fields:
        s = _extract_priority(data.get("priority"), cfg)
        if s:
            suggestions.append(s)

    if "assignee" in missing_fields:
        s = _extract_person(data.get("assignee"), "assignee", cfg, role="dev")
        if s:
            suggestions.append(s)

    if "qa_contact" in missing_fields:
        s = _extract_person(data.get("qa_contact"), "qa_contact", cfg, role="qe")
        if s:
            suggestions.append(s)

    if "sprint" in missing_fields:
        s = _extract_sprint(data.get("sprint"), cfg)
        if s:
            suggestions.append(s)

    if "fix_version" in missing_fields:
        s = _extract_fix_version(data.get("fix_version"), cfg)
        if s:
            suggestions.append(s)

    if cfg.llm.features.suggest_backport:
        backport = _extract_backport(data.get("backport"), cfg)

    return suggestions, backport


_VALID_PRIORITIES = {
    "critical", "blocker", "major", "normal", "minor", "trivial",
}


def _extract_priority(
    data: dict | None,
    cfg: AppConfig,
) -> TriageSuggestion | None:
    if not data or not cfg.llm.features.suggest_priority:
        return None
    value = str(data.get("value", "")).strip()
    if value.lower() not in _VALID_PRIORITIES:
        logger.warning("LLM suggested invalid priority: %s", value)
        return None
    return TriageSuggestion(
        field_name="priority",
        suggested_value=value.capitalize(),
        suggested_display=value.capitalize(),
        reasoning=str(data.get("reasoning", "")),
    )


def _extract_person(
    data: dict | None,
    field_name: str,
    cfg: AppConfig,
    role: str,
) -> TriageSuggestion | None:
    if not data:
        return None
    account_id = str(data.get("account_id", "")).strip()
    name = str(data.get("name", "")).strip()
    reasoning = str(data.get("reasoning", ""))

    member = cfg.team.by_account_id(account_id)
    if not member:
        logger.warning(
            "LLM suggested unknown %s account_id: %s (%s)",
            field_name, account_id, name,
        )
        return None

    valid_roles = {"dev", "both"} if role == "dev" else {"qe", "both"}
    if member.role not in valid_roles:
        logger.warning(
            "LLM suggested %s %s but their role is %s, not %s",
            field_name, name, member.role, role,
        )
        return None

    return TriageSuggestion(
        field_name=field_name,
        suggested_value=account_id,
        suggested_display=member.name,
        reasoning=reasoning,
    )


def _extract_sprint(
    data: dict | None,
    cfg: AppConfig,
) -> TriageSuggestion | None:
    if not data or not cfg.llm.features.suggest_sprint:
        return None
    sprint_id = data.get("sprint_id")
    sprint_name = str(data.get("sprint_name", "")).strip()
    reasoning = str(data.get("reasoning", ""))

    valid_ids = {s.id for s in cfg.planning.sprints}
    if sprint_id not in valid_ids:
        logger.warning(
            "LLM suggested unknown sprint id: %s (%s)",
            sprint_id, sprint_name,
        )
        return None

    matched = next(
        (s for s in cfg.planning.sprints if s.id == sprint_id), None,
    )
    display = matched.name if matched else sprint_name

    return TriageSuggestion(
        field_name="sprint",
        suggested_value=str(sprint_id),
        suggested_display=display,
        reasoning=reasoning,
    )


def _extract_fix_version(
    data: dict | None,
    cfg: AppConfig,
) -> TriageSuggestion | None:
    if not data or not cfg.llm.features.suggest_fix_version:
        return None
    value = str(data.get("value", "")).strip()
    reasoning = str(data.get("reasoning", ""))

    if value not in cfg.planning.fix_versions:
        logger.warning("LLM suggested unknown fix version: %s", value)
        return None

    return TriageSuggestion(
        field_name="fix_version",
        suggested_value=value,
        suggested_display=value,
        reasoning=reasoning,
    )


def _extract_backport(
    data: dict | None,
    cfg: AppConfig,
) -> BackportAnalysis | None:
    if not data:
        return None

    needs = bool(data.get("needs_backport", False))
    overall = str(data.get("overall_reasoning", ""))
    raw_versions = data.get("backport_versions", []) or []

    supported = {v.version for v in cfg.releases.supported_versions()}
    branch_map = {v.version: v.branch for v in cfg.releases.versions}

    recommendations: list[BackportRecommendation] = []
    for rv in raw_versions:
        version = str(rv.get("version", "")).strip()
        if version not in supported:
            logger.warning(
                "LLM suggested backport to unsupported version: %s", version,
            )
            continue
        recommendations.append(BackportRecommendation(
            version=version,
            branch=branch_map.get(version, str(rv.get("branch", ""))),
            urgency=str(rv.get("urgency", "nice_to_have")),
            reasoning=str(rv.get("reasoning", "")),
        ))

    return BackportAnalysis(
        needs_backport=needs and bool(recommendations),
        recommendations=recommendations,
        overall_reasoning=overall,
    )
