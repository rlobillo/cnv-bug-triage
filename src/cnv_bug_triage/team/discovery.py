"""Team discovery from historical Jira bug data."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from cnv_bug_triage.jira.client import _escape_jql, search_all
from cnv_bug_triage.jira.fields import parse_user_field
from cnv_bug_triage.schemas.config import AppConfig, TeamMember

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 180
DEFAULT_CACHE_PATH = ".team_cache.yaml"
MIN_BUG_COUNT = 2
TOP_AREAS = 8
MIN_KEYWORD_FREQ = 3

STOP_WORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "are", "was",
    "were", "been", "being", "have", "has", "had", "not", "but", "can",
    "could", "should", "would", "will", "shall", "may", "might",
    "does", "did", "doing", "done", "its", "into", "over", "such",
    "than", "too", "very", "just", "about", "also", "after", "before",
    "between", "each", "other", "some", "only", "when", "where", "which",
    "while", "during", "through", "then", "there", "here", "all", "any",
    "both", "more", "most", "same", "own",
    "bug", "issue", "error", "fix", "test", "tests", "testing", "fails",
    "failed", "failure", "failing", "broken", "break", "breaks",
    "cnv", "openshift", "virtualization",
    "need", "needs", "needed",
    "version", "release", "update", "updated", "updates",
    "please", "check", "see", "using", "used", "use",
})

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{2,}")


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


def extract_keywords(
    summaries: list[str],
    min_freq: int = MIN_KEYWORD_FREQ,
    top_n: int = TOP_AREAS,
) -> list[str]:
    counts: Counter[str] = Counter()
    for summary in summaries:
        tokens = _TOKEN_RE.findall(summary)
        unique_tokens = {t.lower() for t in tokens} - STOP_WORDS
        counts.update(unique_tokens)

    filtered = {k: v for k, v in counts.items() if v >= min_freq}
    ranked = sorted(filtered.items(), key=lambda x: (-x[1], x[0]))
    return [word for word, _ in ranked[:top_n]]


def _build_areas(person: _PersonAccum) -> list[str]:
    area_set: set[str] = set()
    areas: list[str] = []

    comp_counts = Counter(c.lower() for c in person.components)
    for comp, _ in comp_counts.most_common():
        if comp not in area_set:
            areas.append(comp)
            area_set.add(comp)

    label_counts = Counter(la.lower() for la in person.labels)
    for label, count in label_counts.most_common():
        if count >= 2 and label not in area_set and label not in STOP_WORDS:
            areas.append(label)
            area_set.add(label)

    keywords = extract_keywords(person.summaries)
    for kw in keywords:
        if kw not in area_set:
            areas.append(kw)
            area_set.add(kw)
        if len(areas) >= TOP_AREAS:
            break

    return areas[:TOP_AREAS]


def extract_team_from_issues(
    issues: list[Any],
    cfg: AppConfig,
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

        members.append(TeamMember(
            account_id=person.account_id,
            name=person.name,
            role=role,
            areas=_build_areas(person),
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
) -> TeamCache:
    jql = build_discovery_jql(cfg, days=days)
    logger.info("Discovery JQL: %s", jql)

    issues = search_all(client, jql)
    logger.info("Found %d resolved bugs for team discovery", len(issues))

    members = extract_team_from_issues(issues, cfg)
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
