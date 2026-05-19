"""Team discovery from historical Jira bug data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from cnv_bug_triage.jira.client import _escape_jql, search_all
from cnv_bug_triage.jira.fields import parse_user_field
from cnv_bug_triage.llm.client import LLMError, complete, parse_json_response
from cnv_bug_triage.schemas.config import AppConfig, TeamMember

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 180
DEFAULT_CACHE_PATH = ".team_cache.yaml"
MIN_BUG_COUNT = 2
MAX_SUMMARIES_PER_PERSON = 40


@dataclass
class _PersonAccum:
    account_id: str
    name: str
    assigned_count: int = 0
    qa_count: int = 0
    summaries: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)


@dataclass
class TeamCache:
    discovered_at: str
    lookback_days: int
    bug_count: int
    members: list[TeamMember]

    def to_dict(self) -> dict[str, Any]:
        return {
            "discovered_at": self.discovered_at,
            "lookback_days": self.lookback_days,
            "bug_count": self.bug_count,
            "members": [
                {
                    "account_id": m.account_id,
                    "name": m.name,
                    "role": m.role,
                    "areas": m.areas,
                }
                for m in self.members
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TeamCache:
        members = []
        for m in d.get("members", []):
            members.append(TeamMember(
                account_id=str(m.get("account_id", "")),
                name=str(m.get("name", "")),
                role=str(m.get("role", "dev")),
                areas=m.get("areas", []),
            ))
        return cls(
            discovered_at=str(d.get("discovered_at", "")),
            lookback_days=int(d.get("lookback_days", DEFAULT_LOOKBACK_DAYS)),
            bug_count=int(d.get("bug_count", 0)),
            members=members,
        )


def build_discovery_jql(cfg: AppConfig, days: int = DEFAULT_LOOKBACK_DAYS) -> str:
    f = cfg.filters
    types_clause = ", ".join(f'"{_escape_jql(t)}"' for t in f.issue_types)
    jql = (
        f'project = "{_escape_jql(f.project)}"'
        f" AND issuetype IN ({types_clause})"
        f' AND status IN ("Closed", "Verified", "Resolved")'
        f" AND resolved >= -{days}d"
    )
    if f.component:
        jql += f' AND component = "{_escape_jql(f.component)}"'
    return jql


def _build_areas_prompt(person: _PersonAccum) -> str:
    role = "dev"
    if person.assigned_count > 0 and person.qa_count > 0:
        role = "both (dev + QE)"
    elif person.qa_count > 0:
        role = "qe"

    total = person.assigned_count + person.qa_count

    unique_components = sorted(set(person.components))
    unique_labels = sorted(set(person.labels))
    unique_summaries = list(dict.fromkeys(person.summaries))
    sample = unique_summaries[:MAX_SUMMARIES_PER_PERSON]

    lines = [
        "You are analyzing a team member's bug history to determine "
        "their areas of expertise.",
        "",
        f"Person: {person.name}",
        f"Role: {role}",
        f"Bugs worked on: {total}",
        "",
    ]

    if unique_components:
        lines.append(
            f"Components they worked on: {', '.join(unique_components)}"
        )
    if unique_labels:
        lines.append(f"Labels from their bugs: {', '.join(unique_labels)}")

    lines.append("")
    lines.append("Bug summaries (sample):")
    for s in sample:
        lines.append(f"- {s}")

    lines.append("")
    lines.append(
        'Return a JSON object with a single key "areas" containing '
        "a list of 3-8 concise expertise area strings. Each area "
        "should be 1-3 words, specific to the domain (e.g. "
        '"live migration", "HCO lifecycle", "storage import", '
        '"SRIOV networking"). Group related bugs into coherent areas '
        "rather than listing individual keywords."
    )

    return "\n".join(lines)


def _build_areas_with_llm(
    person: _PersonAccum,
    model: str,
    temperature: float,
) -> list[str]:
    prompt = _build_areas_prompt(person)
    try:
        raw = complete(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        data = parse_json_response(raw)
        areas = data.get("areas", [])
        if isinstance(areas, list):
            return [str(a) for a in areas[:8]]
        logger.warning("LLM returned non-list areas for %s", person.name)
        return []
    except (LLMError, Exception):
        logger.warning(
            "LLM area extraction failed for %s, using empty areas",
            person.name, exc_info=True,
        )
        return []


def extract_team_from_issues(
    issues: list[Any],
    cfg: AppConfig,
    model: str = "",
    temperature: float = 0.0,
) -> list[TeamMember]:
    people: dict[str, _PersonAccum] = {}

    for issue in issues:
        fields = issue.fields
        summary = str(getattr(fields, "summary", "") or "")
        labels = getattr(fields, "labels", []) or []

        components_raw = getattr(fields, "components", []) or []
        component_names = [
            str(getattr(c, "name", "") or "")
            for c in components_raw
            if getattr(c, "name", None)
        ]

        assignee_id, assignee_name = parse_user_field(
            getattr(fields, "assignee", None),
        )
        if assignee_id and assignee_name:
            if assignee_id not in people:
                people[assignee_id] = _PersonAccum(
                    account_id=assignee_id, name=assignee_name,
                )
            p = people[assignee_id]
            p.assigned_count += 1
            p.summaries.append(summary)
            p.labels.extend(labels)
            p.components.extend(component_names)

        qa_field = getattr(fields, cfg.jira.qa_contact_field, None)
        qa_id, qa_name = parse_user_field(qa_field)
        if qa_id and qa_name:
            if qa_id not in people:
                people[qa_id] = _PersonAccum(
                    account_id=qa_id, name=qa_name,
                )
            p = people[qa_id]
            p.qa_count += 1
            p.summaries.append(summary)
            p.labels.extend(labels)
            p.components.extend(component_names)

    members: list[TeamMember] = []
    for person in people.values():
        total = person.assigned_count + person.qa_count
        if total < MIN_BUG_COUNT:
            logger.debug(
                "Skipping %s (%s): only %d appearances",
                person.name, person.account_id, total,
            )
            continue

        if person.assigned_count > 0 and person.qa_count > 0:
            role = "both"
        elif person.qa_count > 0:
            role = "qe"
        else:
            role = "dev"

        logger.info("Profiling %s (%s) with LLM...", person.name, role)
        areas = _build_areas_with_llm(person, model, temperature)

        members.append(TeamMember(
            account_id=person.account_id,
            name=person.name,
            role=role,
            areas=areas,
        ))

    members.sort(key=lambda m: m.name)
    return members


def save_team_cache(
    cache: TeamCache,
    path: str = DEFAULT_CACHE_PATH,
) -> None:
    header = (
        f"# Team discovered by cnv-bug-triage --discover-team\n"
        f"# Generated: {cache.discovered_at}\n"
        f"# Based on {cache.bug_count} resolved bugs "
        f"from the last {cache.lookback_days} days\n"
        f"#\n"
        f"# Copy the 'members' section to config.yaml under team.members\n"
        f"# to lock in your team roster.\n\n"
    )
    content = header + yaml.dump(
        cache.to_dict(),
        default_flow_style=False,
        sort_keys=False,
    )
    Path(path).write_text(content, encoding="utf-8")
    logger.info("Team cache written to %s", path)


def load_team_cache(path: str = DEFAULT_CACHE_PATH) -> TeamCache | None:
    cache_path = Path(path)
    if not cache_path.exists():
        logger.debug("No team cache at %s", path)
        return None
    try:
        raw = yaml.safe_load(cache_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            logger.warning("Team cache %s is not a YAML mapping", path)
            return None
        cache = TeamCache.from_dict(raw)
        logger.info(
            "Loaded team cache from %s (%d members, discovered %s)",
            path, len(cache.members), cache.discovered_at,
        )
        return cache
    except Exception:
        logger.warning("Failed to load team cache %s", path, exc_info=True)
        return None


def discover_team(
    client: Any,
    cfg: AppConfig,
    *,
    days: int = DEFAULT_LOOKBACK_DAYS,
    cache_path: str = DEFAULT_CACHE_PATH,
    model: str = "",
    temperature: float = 0.0,
) -> TeamCache:
    jql = build_discovery_jql(cfg, days=days)
    logger.info("Discovery JQL: %s", jql)

    issues = search_all(client, jql)
    logger.info("Found %d resolved bugs for team discovery", len(issues))

    members = extract_team_from_issues(
        issues, cfg, model=model, temperature=temperature,
    )
    logger.info("Discovered %d team members", len(members))

    cache = TeamCache(
        discovered_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        lookback_days=days,
        bug_count=len(issues),
        members=members,
    )
    save_team_cache(cache, path=cache_path)
    return cache


def format_team_report(cache: TeamCache) -> str:
    lines: list[str] = [
        "Team Discovery Report",
        f"Discovered: {cache.discovered_at}",
        f"Analyzed: {cache.bug_count} resolved bugs "
        f"(last {cache.lookback_days} days)",
        "=" * 60,
        "",
    ]

    devs = [m for m in cache.members if m.role in ("dev", "both")]
    qes = [m for m in cache.members if m.role in ("qe", "both")]

    if devs:
        lines.append(f"DEVELOPERS ({len(devs)}):")
        for m in devs:
            areas_str = ", ".join(m.areas) if m.areas else "(none)"
            both_tag = " [also QE]" if m.role == "both" else ""
            lines.append(f"  {m.name}{both_tag}")
            lines.append(f"    ID: {m.account_id}")
            lines.append(f"    Areas: {areas_str}")
        lines.append("")

    if qes:
        lines.append(f"QE ENGINEERS ({len(qes)}):")
        for m in qes:
            areas_str = ", ".join(m.areas) if m.areas else "(none)"
            both_tag = " [also dev]" if m.role == "both" else ""
            lines.append(f"  {m.name}{both_tag}")
            lines.append(f"    ID: {m.account_id}")
            lines.append(f"    Areas: {areas_str}")
        lines.append("")

    lines.append(
        f"Total: {len(cache.members)} members "
        f"({len(devs)} devs, {len(qes)} QEs)"
    )
    lines.append(f"Cache saved to: {DEFAULT_CACHE_PATH}")

    return "\n".join(lines)
