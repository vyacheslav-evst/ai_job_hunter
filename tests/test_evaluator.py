"""
tests/test_evaluator.py — юнит-тесты для модуля оценки
"""

import pytest
from modules.evaluator import compute_metrics, OUTCOME_LABELS


class TestComputeMetrics:
    def test_empty_feedback(self):
        assert compute_metrics({}) == {}

    def test_precision_apply_perfect(self):
        feedback = {
            "v1": {"agent_recommendation": "APPLY", "relevance_score": 80, "outcome": "applied",
                   "vacancy_title": "T", "company": "C"},
            "v2": {"agent_recommendation": "APPLY", "relevance_score": 70, "outcome": "applied",
                   "vacancy_title": "T", "company": "C"},
        }
        m = compute_metrics(feedback)
        assert m["precision_apply"] == 100.0

    def test_precision_apply_half(self):
        feedback = {
            "v1": {"agent_recommendation": "APPLY", "relevance_score": 80, "outcome": "applied",
                   "vacancy_title": "T", "company": "C"},
            "v2": {"agent_recommendation": "APPLY", "relevance_score": 60, "outcome": "ignored",
                   "vacancy_title": "T", "company": "C"},
        }
        m = compute_metrics(feedback)
        assert m["precision_apply"] == 50.0

    def test_invite_rate(self):
        # v1: applied (не invited), v2: invited
        # applied_all = [v1], invites = [v2] → invite_rate = 1/1 = 100%
        feedback = {
            "v1": {"agent_recommendation": "APPLY", "relevance_score": 80, "outcome": "applied",
                   "vacancy_title": "T", "company": "C"},
            "v2": {"agent_recommendation": "APPLY", "relevance_score": 70, "outcome": "invited",
                   "vacancy_title": "T", "company": "C"},
        }
        m = compute_metrics(feedback)
        # applied_all содержит только v1 (outcome == "applied"), invites только v2
        # invite_rate = len(invites) / len(applied_all) = 1/1 = 100%
        assert m["invite_rate"] == 100.0

    def test_total_counts(self):
        feedback = {
            "v1": {"agent_recommendation": "APPLY", "relevance_score": 80, "outcome": "applied",
                   "vacancy_title": "T", "company": "C"},
            "v2": {"agent_recommendation": "SKIP",  "relevance_score": 30, "outcome": "ignored",
                   "vacancy_title": "T", "company": "C"},
        }
        m = compute_metrics(feedback)
        assert m["total_recorded"] == 2
        assert m["accuracy"] == 100.0


class TestOutcomeLabels:
    def test_all_outcomes_have_labels(self):
        outcomes = ["applied", "ignored", "invited", "rejected_by_me"]
        for o in outcomes:
            assert o in OUTCOME_LABELS
