"""CLI entrypoint for cnv-bug-triage."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from cnv_bug_triage.runner import format_terminal_report, run_triage
from cnv_bug_triage.schemas.config import AppConfig, ConfigError


def _find_config() -> str:
    candidates = [
        Path("config.yaml"),
        Path(__file__).resolve().parent.parent.parent / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return "config.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cnv-bug-triage",
        description="LLM-assisted bug triage for CNV Jira",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Post a Jira comment on each untriaged bug with suggestions",
    )
    parser.add_argument(
        "--bug",
        action="append",
        metavar="KEY",
        help="Process a single bug (repeatable: --bug CNV-1 --bug CNV-2)",
    )
    parser.add_argument(
        "--jql",
        metavar="JQL",
        help="Raw JQL override (bypasses filters section entirely)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable all LLM features (report missing fields only)",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help="Override LLM model (or set LLM_MODEL env var)",
    )
    parser.add_argument(
        "--config", "-c",
        metavar="PATH",
        help="Config file path (default: config.yaml in project root)",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="PATH",
        help="Write XLSX report (e.g. --output report.xlsx)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Debug logging",
    )
    parser.add_argument(
        "--discover-team",
        action="store_true",
        help="Discover team members from resolved bugs and cache to .team_cache.yaml",
    )
    parser.add_argument(
        "--discovery-days",
        type=int,
        default=180,
        metavar="DAYS",
        help="Lookback period for --discover-team (default: 180)",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config_path = args.config or _find_config()
    try:
        cfg = AppConfig.from_yaml(config_path)
    except FileNotFoundError:
        print(f"Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    model = args.model or os.environ.get("LLM_MODEL") or cfg.llm.default_model

    if args.discover_team:
        from cnv_bug_triage.jira.client import get_jira_client
        from cnv_bug_triage.team.discovery import discover_team, format_team_report

        client = get_jira_client(cfg)
        cache = discover_team(
            client, cfg,
            days=args.discovery_days,
            model=model,
            temperature=cfg.llm.temperature,
        )
        print(format_team_report(cache))
        return

    result = run_triage(
        cfg,
        apply=args.apply,
        bug_keys=args.bug,
        jql_override=args.jql,
        use_llm=not args.no_llm,
        model_override=model,
    )

    print(format_terminal_report(result))

    if args.output:
        from cnv_bug_triage.export.xlsx_report import build_xlsx

        build_xlsx(args.output, result=result, cfg=cfg)
        print(f"\nXLSX report written to: {args.output}")


if __name__ == "__main__":
    main()
