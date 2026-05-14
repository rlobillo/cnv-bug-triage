"""Tests for cli.py — argument parsing."""

from __future__ import annotations

from cnv_bug_triage.cli import build_parser


class TestBuildParser:
    def test_defaults(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.apply is False
        assert args.bug is None
        assert args.jql is None
        assert args.no_llm is False
        assert args.model is None
        assert args.config is None
        assert args.output is None
        assert args.verbose is False

    def test_apply_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--apply"])
        assert args.apply is True

    def test_single_bug(self):
        parser = build_parser()
        args = parser.parse_args(["--bug", "CNV-42"])
        assert args.bug == ["CNV-42"]

    def test_multiple_bugs(self):
        parser = build_parser()
        args = parser.parse_args(["--bug", "CNV-1", "--bug", "CNV-2"])
        assert args.bug == ["CNV-1", "CNV-2"]

    def test_jql_override(self):
        parser = build_parser()
        args = parser.parse_args(["--jql", "project = X"])
        assert args.jql == "project = X"

    def test_no_llm_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--no-llm"])
        assert args.no_llm is True

    def test_model_override(self):
        parser = build_parser()
        args = parser.parse_args(["--model", "gemini-pro"])
        assert args.model == "gemini-pro"

    def test_config_short(self):
        parser = build_parser()
        args = parser.parse_args(["-c", "/tmp/custom.yaml"])
        assert args.config == "/tmp/custom.yaml"

    def test_output_short(self):
        parser = build_parser()
        args = parser.parse_args(["-o", "report.xlsx"])
        assert args.output == "report.xlsx"

    def test_verbose_short(self):
        parser = build_parser()
        args = parser.parse_args(["-v"])
        assert args.verbose is True

    def test_combined_flags(self):
        parser = build_parser()
        args = parser.parse_args([
            "--apply", "--bug", "CNV-1", "--model", "gpt-4o",
            "-v", "-o", "out.xlsx",
        ])
        assert args.apply is True
        assert args.bug == ["CNV-1"]
        assert args.model == "gpt-4o"
        assert args.verbose is True
        assert args.output == "out.xlsx"
