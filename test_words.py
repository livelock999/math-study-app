"""文章題の範囲と、演算判断・計算結果の別々の保存を検証します。"""

from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from learning import COLUMNS, generate_problems, init_db, make_attempt, save_attempt, selection_error
from words import make_word_problem, word_pool


class WordTests(unittest.TestCase):
    def test_six_story_types_have_correct_arithmetic_and_unknown_tags(self):
        for story in ("increase", "decrease", "combine", "separate", "compare", "difference"):
            addition = story in ("increase", "combine")
            left, right = (8, 5) if addition else (13, 8)
            problem = make_word_problem(story, 20, left, right)
            self.assertEqual(problem["problem_format"], "word_problem")
            self.assertEqual(problem["story_type"], story)
            self.assertEqual(problem["operation"], "addition" if addition else "subtraction")
            self.assertEqual(problem["correct_answer"], left + right if addition else left - right)
            self.assertEqual(problem["unknown_type"], "difference" if story in ("compare", "difference") else "result")
            self.assertIsNone(problem["equation_correct"])
            self.assertNotIn("=", problem["question_text"])
            self.assertNotIn("+", problem["question_text"])
            self.assertNotIn("−", problem["question_text"])

    def test_word_sets_respect_range_filter_size_and_do_not_repeat_text(self):
        for limit in (10, 20):
            for count in (5, 10, 20):
                for mode in ("addition", "subtraction", "mix"):
                    for special in ("auto", "none", "with"):
                        if selection_error(mode, limit, count, special, "word_problem"):
                            with self.assertRaises(ValueError):
                                generate_problems(mode, limit, count=count, special=special,
                                                  problem_format="word_problem")
                            continue
                        problems = generate_problems(mode, limit, count=count, special=special,
                                                     problem_format="word_problem")
                        self.assertEqual(len(problems), count)
                        self.assertEqual(len({problem["problem_id"] for problem in problems}), count)
                        self.assertEqual(len({problem["question_text"] for problem in problems}), count)
                        for problem in problems:
                            self.assertEqual(problem["problem_format"], "word_problem")
                            self.assertTrue(0 <= problem["correct_answer"] <= limit)
                            self.assertTrue(0 <= problem["left_operand"] <= limit)
                            self.assertTrue(0 <= problem["right_operand"] <= limit)
                            if special != "auto":
                                flag = problem["carry"] if problem["operation"] == "addition" else problem["borrowing"]
                                self.assertEqual(flag, special == "with")

    def test_operation_and_calculation_judgments_are_independent(self):
        problem = make_word_problem("decrease", 20, 13, 8)
        outcomes = [("subtraction", 5, True, True, True),
                    ("subtraction", 4, True, False, False),
                    ("addition", 21, False, True, False),
                    ("addition", 5, False, False, False)]
        for selected, answer, op_correct, calc_correct, overall in outcomes:
            with self.subTest(selected=selected, answer=answer):
                record = make_attempt(problem, "user_001", "word_session", 1, "normal", answer, 2.5, 1,
                                      round_size=5, selected_operation=selected)
                self.assertEqual(record["operation_selection_correct"], op_correct)
                self.assertEqual(record["calculation_correct"], calc_correct)
                self.assertEqual(record["is_correct"], overall)
                self.assertIsNone(record["equation_correct"])
                self.assertEqual(set(record), set(COLUMNS))
        negative = make_word_problem("combine", 20, 3, 8)
        record = make_attempt(negative, "user_001", "word_session", 1, "normal", 0, 2, 1,
                              selected_operation="subtraction")
        self.assertIsNone(record["calculation_correct"])
        self.assertFalse(record["is_correct"])
        for selected in (None, "multiplication"):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                make_attempt(problem, "user_001", "word_session", 1, "normal", 5, 2, 1,
                             selected_operation=selected)

    def test_initial_and_retry_word_records_persist_without_overwriting(self):
        problem = make_word_problem("decrease", 20, 13, 8)
        first = make_attempt(problem, "user_001", "first", 1, "normal", 21, 4, 1,
                             round_size=1, selected_operation="addition")
        retry = make_attempt(problem, "user_001", "retry", 1, "retry", 5, 2, 2,
                             round_size=1, selected_operation="subtraction")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "words.sqlite3"
            init_db(path)
            for record in (first, retry, retry):
                save_attempt(record, path)
            with closing(sqlite3.connect(path)) as db:
                rows = db.execute("SELECT selection_type, attempt_count, operation_selection_correct, "
                                  "calculation_correct, equation_correct, is_correct, round_completed "
                                  "FROM attempts ORDER BY rowid").fetchall()
            self.assertEqual(rows, [("normal", 1, 0, 1, None, 0, 1), ("retry", 2, 1, 1, None, 1, 1)])


if __name__ == "__main__":
    unittest.main()
