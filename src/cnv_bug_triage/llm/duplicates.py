"""LLM-based duplicate bug detection."""

from __future__ import annotations

import logging
from typing import Any

from cnv_bug_triage.llm.client import LLMError, complete, parse_json_response
from cnv_bug_triage.prompts.templates import (
    DUPLICATE_JSON_SCHEMA,
    SYSTEM_PROMPT,
    build_duplicate_prompt,
)
from cnv_bug_triage.schemas.bug_doc import BugDoc
from cnv_bug_triage.schemas.config import AppConfig
from cnv_bug_triage.triage.checker import DuplicateCandidate

logger = logging.getLogger(__name__)


def detect_duplicates(
    bug: BugDoc,
    all_bugs: list[BugDoc],
    cfg: AppConfig,
    model: str | None = None,
) -> list[DuplicateCandidate]:
    if not cfg.llm.features.detect_duplicates:
        return []

    candidates = [
        {"key": b.key, "summary": b.summary}
        for b in all_bugs
        if b.key != bug.key
    ]
    candidates = candidates[: cfg.duplicates.max_candidates]

    if not candidates:
        return []

    llm_model = model or cfg.llm.default_model
    prompt = build_duplicate_prompt(bug, candidates, cfg.duplicates.threshold)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        raw = complete(
            model=llm_model,
            messages=messages,
            response_format=DUPLICATE_JSON_SCHEMA,
            temperature=0.0,
        )
    except LLMError:
        logger.error(
            "Duplicate detection LLM call failed for %s",
            bug.key, exc_info=True,
        )
        return []

    try:
        data = parse_json_response(raw)
    except Exception:
        logger.error(
            "Failed to parse duplicate detection response for %s",
            bug.key, exc_info=True,
        )
        return []

    valid_keys = {c["key"] for c in candidates}
    summary_map = {c["key"]: c["summary"] for c in candidates}

    results: list[DuplicateCandidate] = []
    for d in data.get("duplicates", []):
        key = str(d.get("candidate_key", "")).strip()
        conf = float(d.get("confidence", 0.0))
        reasoning = str(d.get("reasoning", ""))

        if key not in valid_keys:
            logger.warning("LLM suggested unknown duplicate key: %s", key)
            continue
        if conf < cfg.duplicates.threshold:
            continue

        results.append(DuplicateCandidate(
            candidate_key=key,
            candidate_summary=summary_map.get(key, ""),
            confidence=conf,
            reasoning=reasoning,
        ))

    return results
