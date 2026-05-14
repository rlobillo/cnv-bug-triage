"""Tests for llm/duplicates.py — duplicate detection."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cnv_bug_triage.llm.duplicates import detect_duplicates
from tests.conftest import make_bug


class TestDetectDuplicates:
    @patch("cnv_bug_triage.llm.duplicates.complete")
    def test_detects_duplicate(self, mock_complete, sample_cfg):
        mock_complete.return_value = json.dumps({
            "duplicates": [
                {
                    "candidate_key": "CNV-200",
                    "confidence": 0.9,
                    "reasoning": "Same stack trace in virt-handler",
                },
            ],
        })

        bug = make_bug(key="CNV-100", summary="VM crash on upgrade")
        others = [
            make_bug(key="CNV-200", summary="virt-handler crash during upgrade"),
            make_bug(key="CNV-300", summary="Unrelated storage issue"),
        ]

        results = detect_duplicates(bug, others, sample_cfg)
        assert len(results) == 1
        assert results[0].candidate_key == "CNV-200"
        assert results[0].confidence == 0.9

    @patch("cnv_bug_triage.llm.duplicates.complete")
    def test_below_threshold_filtered(self, mock_complete, sample_cfg):
        mock_complete.return_value = json.dumps({
            "duplicates": [
                {"candidate_key": "CNV-200", "confidence": 0.5, "reasoning": "Weak match"},
            ],
        })

        bug = make_bug(key="CNV-100")
        others = [make_bug(key="CNV-200")]

        results = detect_duplicates(bug, others, sample_cfg)
        assert results == []

    @patch("cnv_bug_triage.llm.duplicates.complete")
    def test_unknown_key_filtered(self, mock_complete, sample_cfg):
        mock_complete.return_value = json.dumps({
            "duplicates": [
                {"candidate_key": "CNV-999", "confidence": 0.95, "reasoning": "test"},
            ],
        })

        bug = make_bug(key="CNV-100")
        others = [make_bug(key="CNV-200")]

        results = detect_duplicates(bug, others, sample_cfg)
        assert results == []

    def test_feature_disabled(self, sample_cfg):
        sample_cfg.llm.features.detect_duplicates = False
        bug = make_bug()
        results = detect_duplicates(bug, [make_bug(key="CNV-200")], sample_cfg)
        assert results == []

    @patch("cnv_bug_triage.llm.duplicates.complete")
    def test_self_excluded_from_candidates(self, mock_complete, sample_cfg):
        mock_complete.return_value = json.dumps({"duplicates": []})

        bug = make_bug(key="CNV-100")
        others = [bug, make_bug(key="CNV-200")]

        detect_duplicates(bug, others, sample_cfg)

        call_args = mock_complete.call_args
        prompt = call_args[1]["messages"][1]["content"] if "messages" in call_args[1] else call_args[0][1][1]["content"]
        assert "CNV-200" in prompt

    @patch("cnv_bug_triage.llm.duplicates.complete")
    def test_empty_candidates(self, mock_complete, sample_cfg):
        bug = make_bug(key="CNV-100")
        results = detect_duplicates(bug, [bug], sample_cfg)
        assert results == []
        mock_complete.assert_not_called()

    @patch("cnv_bug_triage.llm.duplicates.complete")
    def test_no_duplicates_found(self, mock_complete, sample_cfg):
        mock_complete.return_value = json.dumps({"duplicates": []})

        bug = make_bug(key="CNV-100")
        others = [make_bug(key="CNV-200")]

        results = detect_duplicates(bug, others, sample_cfg)
        assert results == []

    @patch("cnv_bug_triage.llm.duplicates.complete")
    def test_max_candidates_respected(self, mock_complete, sample_cfg):
        sample_cfg.duplicates.max_candidates = 3
        mock_complete.return_value = json.dumps({"duplicates": []})

        bug = make_bug(key="CNV-100")
        others = [make_bug(key=f"CNV-{i}") for i in range(200, 210)]

        detect_duplicates(bug, others, sample_cfg)

        call_args = mock_complete.call_args
        prompt = call_args[1]["messages"][1]["content"] if "messages" in call_args[1] else call_args[0][1][1]["content"]
        candidate_keys = [f"CNV-{i}" for i in range(200, 210)]
        found_count = sum(1 for k in candidate_keys if k in prompt)
        assert found_count <= 3
