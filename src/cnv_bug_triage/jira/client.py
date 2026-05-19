"""Jira REST helpers: authentication, querying, and comment posting."""

from __future__ import annotations

import functools
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from jira import JIRA

from cnv_bug_triage.schemas.config import AppConfig

logger = logging.getLogger(__name__)

_PAGE_SIZE = 200
_MAX_RETRIES = 3
_INITIAL_BACKOFF_S = 1.0


def _escape_jql(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _retry_on_jira_error(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status and status < 500 and status != 429:
                    raise
                last_err = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _INITIAL_BACKOFF_S * (2 ** attempt)
                    logger.warning(
                        "Jira API %s failed (attempt %d/%d), "
                        "retrying in %.1fs: %s",
                        func.__name__, attempt + 1,
                        _MAX_RETRIES, delay, exc,
                    )
                    time.sleep(delay)
        raise last_err  # type: ignore[misc]
    return wrapper


def search_all(
    client: JIRA,
    jql: str,
    page_size: int = _PAGE_SIZE,
) -> list[Any]:
    all_issues: list[Any] = []
    start_at = 0
    while True:
        page = client.search_issues(
            jql, startAt=start_at, maxResults=page_size,
        )
        all_issues.extend(page)
        if len(page) < page_size:
            break
        start_at += page_size
    return all_issues


def get_jira_client(cfg: AppConfig) -> JIRA:
    url = os.environ.get("JIRA_URL", cfg.jira.url)
    token = os.environ.get("JIRA_TOKEN", "")
    email = os.environ.get("JIRA_EMAIL", "")
    if not token:
        raise RuntimeError("JIRA_TOKEN environment variable is required")
    if not email:
        raise RuntimeError("JIRA_EMAIL environment variable is required")
    return JIRA(server=url, basic_auth=(email, token))


def build_bug_jql(cfg: AppConfig) -> str:
    f = cfg.filters
    types_clause = ", ".join(f'"{_escape_jql(t)}"' for t in f.issue_types)
    statuses_clause = ", ".join(
        f'"{_escape_jql(s)}"' for s in f.excluded_statuses
    )

    jql = (
        f'project = "{_escape_jql(f.project)}"'
        f" AND issuetype IN ({types_clause})"
        f" AND status NOT IN ({statuses_clause})"
    )
    if f.component:
        jql += f' AND component = "{_escape_jql(f.component)}"'
    if f.extra_jql:
        jql += f" {f.extra_jql}"
    return jql


@_retry_on_jira_error
def search_bugs(
    client: JIRA,
    cfg: AppConfig,
    jql: str | None = None,
) -> list[Any]:
    if jql is None:
        jql = build_bug_jql(cfg)
    logger.info("Searching bugs with JQL: %s", jql)
    return search_all(client, jql)


@_retry_on_jira_error
def fetch_bug(client: JIRA, key: str) -> Any:
    return client.issue(key)


def days_since_last_agent_comment(
    client: JIRA,
    issue_key: str,
    prefix: str,
) -> float | None:
    try:
        issue = client.issue(issue_key, fields="comment")
    except Exception:
        logger.warning(
            "Could not fetch comments for %s", issue_key,
            exc_info=True,
        )
        return None

    comments = issue.fields.comment.comments if issue.fields.comment else []
    for comment in reversed(comments):
        body = getattr(comment, "body", "") or ""
        if body.startswith(prefix):
            created = getattr(comment, "created", None)
            if not created:
                continue
            ts = datetime.fromisoformat(
                created.replace("+0000", "+00:00"),
            )
            delta = datetime.now(timezone.utc) - ts
            return delta.total_seconds() / 86400.0
    return None


@_retry_on_jira_error
def post_comment(client: JIRA, issue_key: str, body: str) -> None:
    client.add_comment(issue_key, body)
    logger.info("Posted comment on %s", issue_key)
