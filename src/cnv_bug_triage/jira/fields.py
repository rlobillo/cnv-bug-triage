"""Sprint and QA contact field parsing helpers.

Jira custom fields come back in varied formats depending on the
instance configuration and API version.  These helpers normalize
them into clean Python values.
"""

from __future__ import annotations

import re
from typing import Any


def parse_user_field(value: Any) -> tuple[str | None, str]:
    """Extract (account_id, display_name) from a Jira user field.

    The field may be None, a dict, or an object with attributes.
    Returns (None, "") when the field is empty.
    """
    if value is None:
        return None, ""
    if isinstance(value, dict):
        return (
            value.get("accountId") or value.get("key"),
            value.get("displayName", ""),
        )
    account_id = (
        getattr(value, "accountId", None)
        or getattr(value, "key", None)
    )
    display_name = getattr(value, "displayName", "") or ""
    return account_id, display_name


_SPRINT_PATTERN = re.compile(
    r"id=(\d+).*?name=([^,\]]+).*?state=(\w+)",
    re.IGNORECASE,
)


def parse_sprint_field(
    value: Any,
) -> tuple[str, int | None, str]:
    """Extract (sprint_name, sprint_id, sprint_state) from the sprint field.

    The sprint custom field can be:
    - None
    - A list of sprint objects/dicts (Jira Cloud returns a list)
    - A list of strings like "com.atlassian.greenhopper...[@id=123,name=...,state=ACTIVE]"
    - A single object with attributes

    When multiple sprints are present, picks the most relevant one
    (active > future > closed) from the last entries.
    """
    if value is None:
        return "", None, ""

    items: list[Any] = value if isinstance(value, list) else [value]

    parsed: list[tuple[str, int | None, str]] = []

    for item in items:
        if isinstance(item, str):
            m = _SPRINT_PATTERN.search(item)
            if m:
                parsed.append((
                    m.group(2).strip(),
                    int(m.group(1)),
                    m.group(3).lower(),
                ))
            continue

        if isinstance(item, dict):
            name = item.get("name", "")
            sid = item.get("id")
            state = str(item.get("state", "")).lower()
        else:
            name = getattr(item, "name", "") or ""
            sid = getattr(item, "id", None)
            state = str(getattr(item, "state", "") or "").lower()

        if name:
            parsed.append((name, int(sid) if sid else None, state))

    if not parsed:
        return "", None, ""

    priority = {"active": 0, "future": 1}
    parsed.sort(key=lambda x: priority.get(x[2], 99))
    return parsed[0]
