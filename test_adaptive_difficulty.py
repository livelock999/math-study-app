"""教材範囲・履歴の隔離・日別の段階変化を検証。実DBに触れない。"""
from datetime import datetime, timedelta, timezone
import random
import unittest
from unittest.mock import patch

import adaptive_difficulty as adaptive
from daily_review import JST
from learning import problem_pool
from japanese_questions import QUESTIONS


NOW = datetime(2026, 10, 8, 12, tzinfo=JST)


def math_rows(level, day=1, correct=True, hint=False, count=5, **overrides):
    pool = [p for p in problem_pool("addition", 10) if adaptive.math_level(p) == level][:count]
    rows = [{**p, "user_id": "user_001", "attempt_id": f"a_{level}_{day}_{i}", "attempt_count": 1,
             "selection_type": "normal", "datetime": (NOW - timedelta(days=day, minutes=i)).isoformat(),
             "is_correct": correct, "hint_used": hint, "hint_level": 1 if hint else 0,
             "dont_know_used": False, **overrides} for i, p in enumerate(pool)]
    return rows


def jp_rows(level, day=1, correct=True, hint=False):
    pool = [q for q in QUESTIONS if q["category"] == "particles" and q["difficulty"] == level][:5]
    return [{**q, "user_id": "user_001", "attempt_id": f"j_{level}_{day}_{i}", "attempt_count": 1,
             "selection_type": "normal", "datetime": (NOW - timedelta(days=day, minutes=i)).isoformat(),
             "correct": correct, "hint_used": hint, "hint_level": 1 if hint else 0} for i, q in enumerate(pool)]


class AdaptiveDifficultyTests(unittest.TestCase):
    def math(self, rows, **kw):
        return adaptive.plan_math(rows, "user_001", now=NOW, rng=random.Random(1), **kw)

    def jp(self, rows, **kw):
        return adaptive.plan_japanese(rows, "user_001", category="particles", now=NOW, rng=random.Random(1), **kw)

    def level(self, rows):
        return self.math(rows)["decisions"]["addition"]["level"]

    def test_no_history_and_unique_items(self):
        plan = self.math([], count=5)
        self.assertEqual(plan["decisions"]["addition"]["level"], 1)
        self.assertEqual(len({p["problem_id"] for p in plan["items"]}), 5)
        self.assertTrue(all(adaptive.math_level(p) == 1 for p in plan["items"]))
        self.assertEqual(self.jp([])["decisions"]["particles"]["level"], 1)

    def test_raise_lower_and_hint_reset(self):
        first = math_rows(1, day=3)
        second = math_rows(2, day=2)
        self.assertEqual(self.level(first), 2)
        self.assertEqual(self.level(first + second), 3)
        self.assertEqual(self.level(first + second + math_rows(3, day=1, correct=False)), 2)
        self.assertEqual(self.level(first + math_rows(2, day=2, hint=True)), 1)
        self.assertEqual(self.level(first + math_rows(2, day=2, dont_know_used=True)), 1)

    def test_japanese_difficulty_separate_from_manual_particle_level(self):
        rows = jp_rows(1, 3) + jp_rows(2, 2)
        self.assertEqual(self.jp(rows)["decisions"]["particles"]["level"], 3)
        self.assertTrue(all(q["level"] == 2 for q in self.jp(rows, particle_level=2)["items"]))

    def test_isolation_future_retries_unknown_hint(self):
        for changes in ({"user_id": "user_002"}, {"selection_type": "review"},
                        {"selection_type": "review_retry"}, {"selection_type": "retry"},
                        {"selection_type": "weak_area"}, {"attempt_count": 2}, {"test_mode": True},
                        {"datetime": (NOW + timedelta(seconds=1)).isoformat()}, {"datetime": "invalid"},
                        {"hint_used": None}, {"number_range": 20}, {"operation": "subtraction"},
                        {"problem_format": "word_problem"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.level(math_rows(1, **changes)), 1)

    def test_same_day_repeated_old_evidence_does_not_advance(self):
        rows = math_rows(1, day=0) + math_rows(2, day=0)
        self.assertEqual(self.level(rows), 2)
        self.assertEqual(self.level(rows * 3), 2)
        # 同じ問題を新しい通常セットで解き直しても、その日の最初の回答のみ。
        copies = [{**r, "attempt_id": r["attempt_id"] + "_new"} for r in rows]
        self.assertEqual(self.level(rows + copies), 2)
        later = adaptive.plan_math(rows, "user_001", now=NOW + timedelta(days=5))
        self.assertEqual(later["decisions"]["addition"]["level"], 2)

    def test_small_history_and_date_boundary(self):
        self.assertEqual(self.level(math_rows(1, count=4)), 1)
        rows = math_rows(1, day=0)
        # 23:59 JSTと翌日00:00 JSTを別の学習日として判定。
        for i, r in enumerate(rows):
            r["datetime"] = datetime(2026, 10, 7, 23, 59, i, tzinfo=JST).astimezone(timezone.utc).isoformat()
        harder = math_rows(2, day=0)
        for i, r in enumerate(harder):
            r["datetime"] = datetime(2026, 10, 8, 0, 0, i, tzinfo=JST).isoformat()
        self.assertEqual(self.level(rows + harder), 3)

    def test_constraints_and_short_pool(self):
        plan = self.math([], mode="mix", limit=20, special="none", problem_format="word_problem", count=20)
        self.assertEqual(len(plan["items"]), 20)
        self.assertEqual(sum(p["operation"] == "addition" for p in plan["items"]), 10)
        self.assertEqual(len({p["problem_id"] for p in plan["items"]}), 20)
        self.assertTrue(all(p["number_range"] == 20 and p["problem_format"] == "word_problem"
                            and not p["carry"] and not p["borrowing"] for p in plan["items"]))
        self.assertEqual(len(self.math([], special="with")["items"]), 9)
        self.assertEqual(len(self.math([], mode="subtraction", special="with")["items"]), 9)
        with patch("adaptive_difficulty.problem_pool", return_value=[]):
            empty = self.math([])
        self.assertEqual(empty["items"], [])
        self.assertTrue(empty["message"])

    def test_mix_japanese_balances_categories_preserves_source(self):
        import copy
        before = copy.deepcopy(QUESTIONS)
        plan = adaptive.plan_japanese([], "user_001", now=NOW, count=10, rng=random.Random(1))
        self.assertEqual(len({q["question_id"] for q in plan["items"]}), 10)
        self.assertEqual(len({q["category"] for q in plan["items"]}), 7)
        self.assertEqual(QUESTIONS, before)

    def test_reading_help_does_not_count_as_solution_hint(self):
        self.assertEqual(self.level(math_rows(1, reading_help_used=True)), 2)
        rows = math_rows(1)
        for r in rows[:2]:
            r["is_correct"] = False
        self.assertEqual(self.level(rows), 1)

    def test_short_daily_mix_accumulates_evidence_across_days(self):
        rows = math_rows(1, day=3, count=3) + math_rows(1, day=2, count=3)
        self.assertEqual(self.level(rows), 2)
        rows += math_rows(2, day=1, count=3, correct=False) + math_rows(2, day=0, count=3, correct=False)
        self.assertEqual(self.level(rows), 1)
        jp = jp_rows(1, day=3)[:2] + jp_rows(1, day=2)[:2] + jp_rows(1, day=1)[:2]
        self.assertEqual(self.jp(jp)["decisions"]["particles"]["level"], 2)
        later = adaptive.plan_japanese(jp, "user_001", category="particles", now=NOW + timedelta(days=5))
        self.assertEqual(later["decisions"]["particles"]["level"], 2)

    def test_first_decision_is_fixed_when_later_same_day_answers_arrive(self):
        rows = math_rows(1, day=0, count=10)
        for i, row in enumerate(rows):
            row["datetime"] = NOW.replace(hour=8 if i < 5 else 9, minute=i).isoformat()
            row["is_correct"] = i < 5
        self.assertEqual(self.level(rows[:5]), 2)
        self.assertEqual(self.level(rows), 2)
        self.assertEqual(self.level(list(reversed(rows))), 2)


if __name__ == "__main__":
    unittest.main()
