"""
evaluator.py — модуль оценки качества рекомендаций агента.

Логика:
- Пользователь отмечает реальный исход по каждой вакансии:
    applied (откликнулся), ignored (проигнорировал), invited (пригласили)
- Модуль считает метрики: precision APPLY, recall, accuracy
- Данные хранятся в output/feedback.json между сессиями
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

import config


FEEDBACK_PATH = config.OUTPUT_DIR / "feedback.json"

# Возможные исходы
OUTCOMES = ["applied", "ignored", "invited", "rejected_by_me"]
OUTCOME_LABELS = {
    "applied":         "✅ Откликнулся",
    "ignored":         "⏭ Пропустил",
    "invited":         "🎉 Пригласили",
    "rejected_by_me":  "❌ Не подошло мне",
}


def load_feedback() -> dict:
    """Загружает сохранённый фидбэк из файла."""
    if FEEDBACK_PATH.exists():
        try:
            with open(FEEDBACK_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_feedback(feedback: dict) -> None:
    """Сохраняет фидбэк в файл."""
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    with open(FEEDBACK_PATH, "w", encoding="utf-8") as f:
        json.dump(feedback, f, ensure_ascii=False, indent=2)


def record_outcome(
    vacancy_id: str,
    vacancy_title: str,
    company: str,
    agent_recommendation: str,
    relevance_score: int,
    outcome: str,
) -> None:
    """Записывает реальный исход для вакансии."""
    feedback = load_feedback()
    feedback[vacancy_id] = {
        "vacancy_title": vacancy_title,
        "company": company,
        "agent_recommendation": agent_recommendation,
        "relevance_score": relevance_score,
        "outcome": outcome,
        "recorded_at": datetime.now().isoformat(),
    }
    save_feedback(feedback)


def compute_metrics(feedback: dict) -> dict:
    """
    Считает метрики качества рекомендаций агента.

    Метрики:
    - precision_apply: доля APPLY-вакансий где пользователь действительно откликнулся
    - apply_to_invite_rate: доля откликов где пригласили
    - accuracy: доля вакансий где решение агента совпало с реальным исходом
    - total_recorded: сколько вакансий оценено
    """
    if not feedback:
        return {}

    total = len(feedback)
    apply_recs = [v for v in feedback.values() if v["agent_recommendation"] == "APPLY"]
    applied_after_apply = [v for v in apply_recs if v["outcome"] == "applied"]
    invites = [v for v in feedback.values() if v["outcome"] == "invited"]
    applied_all = [v for v in feedback.values() if v["outcome"] == "applied"]

    precision_apply = (
        len(applied_after_apply) / len(apply_recs) * 100
        if apply_recs else None
    )
    invite_rate = (
        len(invites) / len(applied_all) * 100
        if applied_all else None
    )

    # Accuracy: APPLY → applied/invited считается правильным; SKIP → ignored/rejected считается правильным
    correct = 0
    for v in feedback.values():
        rec = v["agent_recommendation"]
        out = v["outcome"]
        if rec == "APPLY" and out in ("applied", "invited"):
            correct += 1
        elif rec == "SKIP" and out in ("ignored", "rejected_by_me"):
            correct += 1
        elif rec == "MAYBE":
            correct += 1  # MAYBE — нейтрально, всегда считаем корректным

    accuracy = correct / total * 100 if total else None

    return {
        "total_recorded": total,
        "apply_recommendations": len(apply_recs),
        "precision_apply": round(precision_apply, 1) if precision_apply is not None else None,
        "invite_rate": round(invite_rate, 1) if invite_rate is not None else None,
        "accuracy": round(accuracy, 1) if accuracy is not None else None,
        "total_applied": len(applied_all),
        "total_invited": len(invites),
    }
