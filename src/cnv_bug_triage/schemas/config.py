"""Typed configuration hierarchy for cnv-bug-triage.

Provides validated, typed access to config.yaml values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when config.yaml has invalid or missing values."""


@dataclass
class JiraConfig:
    url: str = "https://your-instance.atlassian.net"
    qa_contact_field: str = "customfield_XXXXX"
    sprint_field: str = "customfield_XXXXX"


@dataclass
class FiltersConfig:
    project: str = "OpenShift Virtualization"
    component: str = "CNV Install, Upgrade and Operators"
    issue_types: list[str] = field(
        default_factory=lambda: ["Bug", "Vulnerability", "Weakness"],
    )
    excluded_statuses: list[str] = field(
        default_factory=lambda: ["Closed", "Verified"],
    )
    extra_jql: str = ""


@dataclass
class TriageConfig:
    placeholder_user_id: str = ""
    comment_cooldown_days: int = 7
    comment_prefix: str = "[Bug Triage Agent]"


@dataclass
class LLMFeaturesConfig:
    suggest_priority: bool = True
    suggest_assignee: bool = True
    suggest_qa_contact: bool = True
    suggest_sprint: bool = True
    suggest_fix_version: bool = True
    suggest_backport: bool = True
    detect_duplicates: bool = True


@dataclass
class LLMConfig:
    default_model: str = "gpt-4o"
    temperature: float = 0.0
    features: LLMFeaturesConfig = field(
        default_factory=LLMFeaturesConfig,
    )


@dataclass
class TeamMember:
    account_id: str = ""
    name: str = ""
    role: str = "dev"
    areas: list[str] = field(default_factory=list)


@dataclass
class TeamConfig:
    members: list[TeamMember] = field(default_factory=list)

    def devs(self) -> list[TeamMember]:
        return [m for m in self.members if m.role in ("dev", "both")]

    def qes(self) -> list[TeamMember]:
        return [m for m in self.members if m.role in ("qe", "both")]

    def by_account_id(self, account_id: str) -> TeamMember | None:
        for m in self.members:
            if m.account_id == account_id:
                return m
        return None


@dataclass
class SprintOption:
    id: int = 0
    name: str = ""
    state: str = ""
    goal: str = ""


@dataclass
class PlanningConfig:
    sprints: list[SprintOption] = field(default_factory=list)
    fix_versions: list[str] = field(default_factory=list)
    sprint_guidance: str = ""
    fix_version_guidance: str = ""


@dataclass
class ReleaseVersion:
    version: str = ""
    status: str = ""
    ga_date: str = ""
    eol_date: str = ""
    branch: str = ""
    latest_z: str = ""


@dataclass
class ReleasesConfig:
    current_dev: str = ""
    versions: list[ReleaseVersion] = field(default_factory=list)
    backport_policy: str = ""

    def supported_versions(self) -> list[ReleaseVersion]:
        return [v for v in self.versions if v.status in ("ga", "maintenance")]


@dataclass
class DuplicatesConfig:
    max_candidates: int = 50
    threshold: float = 0.8


@dataclass
class AppConfig:
    jira: JiraConfig = field(default_factory=JiraConfig)
    filters: FiltersConfig = field(default_factory=FiltersConfig)
    triage: TriageConfig = field(default_factory=TriageConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
    planning: PlanningConfig = field(default_factory=PlanningConfig)
    releases: ReleasesConfig = field(default_factory=ReleasesConfig)
    duplicates: DuplicatesConfig = field(default_factory=DuplicatesConfig)

    raw: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def _parse_int(val: Any, field_name: str) -> int:
        try:
            return int(val)
        except (ValueError, TypeError):
            raise ConfigError(
                f"{field_name} must be an integer, got {val!r}"
            )

    @staticmethod
    def _parse_float(val: Any, field_name: str) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            raise ConfigError(
                f"{field_name} must be a number, got {val!r}"
            )

    @staticmethod
    def _parse_str_list(val: Any, field_name: str) -> list[str]:
        if isinstance(val, str):
            return [v.strip() for v in val.split(",") if v.strip()]
        if isinstance(val, list):
            return [str(v) for v in val]
        raise ConfigError(
            f"{field_name} must be a list or comma-separated string, "
            f"got {type(val).__name__}"
        )

    @classmethod
    def _parse_team_members(cls, raw: list[dict]) -> list[TeamMember]:
        members = []
        for m in raw:
            members.append(TeamMember(
                account_id=str(m.get("account_id", "")),
                name=str(m.get("name", "")),
                role=str(m.get("role", "dev")),
                areas=cls._parse_str_list(
                    m.get("areas", []), "team.members[].areas",
                ),
            ))
        return members

    @classmethod
    def _parse_sprints(cls, raw: list[dict]) -> list[SprintOption]:
        sprints = []
        for s in raw:
            sprints.append(SprintOption(
                id=cls._parse_int(s.get("id", 0), "planning.sprints[].id"),
                name=str(s.get("name", "")),
                state=str(s.get("state", "")),
                goal=str(s.get("goal", "")),
            ))
        return sprints

    @classmethod
    def _parse_release_versions(cls, raw: list[dict]) -> list[ReleaseVersion]:
        versions = []
        for v in raw:
            versions.append(ReleaseVersion(
                version=str(v.get("version", "")),
                status=str(v.get("status", "")),
                ga_date=str(v.get("ga_date", "")),
                eol_date=str(v.get("eol_date", "")),
                branch=str(v.get("branch", "")),
                latest_z=str(v.get("latest_z", "")),
            ))
        return versions

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AppConfig:
        j = d.get("jira", {}) or {}
        f = d.get("filters", {}) or {}
        t = d.get("triage", {}) or {}
        l = d.get("llm", {}) or {}
        lf = l.get("features", {}) or {}
        team_raw = d.get("team", {}) or {}
        p = d.get("planning", {}) or {}
        r = d.get("releases", {}) or {}
        dup = d.get("duplicates", {}) or {}

        cfg = cls(
            jira=JiraConfig(
                url=str(j.get("url", JiraConfig.url)),
                qa_contact_field=str(j.get(
                    "qa_contact_field", JiraConfig.qa_contact_field,
                )),
                sprint_field=str(j.get(
                    "sprint_field", JiraConfig.sprint_field,
                )),
            ),
            filters=FiltersConfig(
                project=str(f.get("project", FiltersConfig.project)),
                component=str(f.get("component", FiltersConfig.component)),
                issue_types=cls._parse_str_list(
                    f.get("issue_types", ["Bug", "Vulnerability", "Weakness"]),
                    "filters.issue_types",
                ),
                excluded_statuses=cls._parse_str_list(
                    f.get("excluded_statuses", ["Closed", "Verified"]),
                    "filters.excluded_statuses",
                ),
                extra_jql=str(f.get("extra_jql", "")),
            ),
            triage=TriageConfig(
                placeholder_user_id=str(t.get("placeholder_user_id", "")),
                comment_cooldown_days=cls._parse_int(
                    t.get("comment_cooldown_days", 7),
                    "triage.comment_cooldown_days",
                ),
                comment_prefix=str(t.get(
                    "comment_prefix", TriageConfig.comment_prefix,
                )),
            ),
            llm=LLMConfig(
                default_model=str(l.get("default_model", LLMConfig.default_model)),
                temperature=cls._parse_float(
                    l.get("temperature", 0.0), "llm.temperature",
                ),
                features=LLMFeaturesConfig(
                    suggest_priority=bool(lf.get("suggest_priority", True)),
                    suggest_assignee=bool(lf.get("suggest_assignee", True)),
                    suggest_qa_contact=bool(lf.get("suggest_qa_contact", True)),
                    suggest_sprint=bool(lf.get("suggest_sprint", True)),
                    suggest_fix_version=bool(lf.get("suggest_fix_version", True)),
                    suggest_backport=bool(lf.get("suggest_backport", True)),
                    detect_duplicates=bool(lf.get("detect_duplicates", True)),
                ),
            ),
            team=TeamConfig(
                members=cls._parse_team_members(
                    team_raw.get("members", []) or [],
                ),
            ),
            planning=PlanningConfig(
                sprints=cls._parse_sprints(p.get("sprints", []) or []),
                fix_versions=cls._parse_str_list(
                    p.get("fix_versions", []), "planning.fix_versions",
                ),
                sprint_guidance=str(p.get("sprint_guidance", "")),
                fix_version_guidance=str(p.get("fix_version_guidance", "")),
            ),
            releases=ReleasesConfig(
                current_dev=str(r.get("current_dev", "")),
                versions=cls._parse_release_versions(
                    r.get("versions", []) or [],
                ),
                backport_policy=str(r.get("backport_policy", "")),
            ),
            duplicates=DuplicatesConfig(
                max_candidates=cls._parse_int(
                    dup.get("max_candidates", 50),
                    "duplicates.max_candidates",
                ),
                threshold=cls._parse_float(
                    dup.get("threshold", 0.8), "duplicates.threshold",
                ),
            ),
            raw=d,
        )
        cfg._validate()
        return cfg

    @classmethod
    def from_yaml(cls, path: str) -> AppConfig:
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            raise ConfigError(
                f"{path} must be a YAML mapping, got {type(raw).__name__}"
            )
        return cls.from_dict(raw)

    def _validate(self) -> None:
        if self.triage.comment_cooldown_days < 0:
            raise ConfigError("triage.comment_cooldown_days must be >= 0")
        if not 0.0 <= self.llm.temperature <= 2.0:
            raise ConfigError(
                f"llm.temperature must be between 0.0 and 2.0, "
                f"got {self.llm.temperature}"
            )
        if self.duplicates.max_candidates < 1:
            raise ConfigError("duplicates.max_candidates must be >= 1")
        if not 0.0 <= self.duplicates.threshold <= 1.0:
            raise ConfigError(
                f"duplicates.threshold must be between 0.0 and 1.0, "
                f"got {self.duplicates.threshold}"
            )
