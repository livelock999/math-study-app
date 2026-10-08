"""穴埋めの答え・基礎式属性・保存は画面と外部DBから独立して検証。"""

from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

import fill_blank as fill
import learning
import practice_mode
import words


class FillBlankTests(unittest.TestCase):
    def test_four_operation_position_patterns_have_hidden_answer(self):
        examples = [
            ("addition", 5, 3, "left_operand", "□ + 3 = 8", 5),
            ("addition", 5, 3, "right_operand", "5 + □ = 8", 3),
            ("subtraction", 8, 3, "left_operand", "□ − 3 = 5", 8),
            ("subtraction", 8, 3, "right_operand", "8 − □ = 5", 3),
        ]
        for operation, left, right, position, text, answer in examples:
            with self.subTest(operation=operation, position=position):
                q = fill.make_fill_problem(operation, 10, left, right, position)
                self.assertEqual(q["question_text"], text)
                self.assertEqual(q["correct_answer"], answer)
                self.assertEqual(q["blank_position"], position)
                self.assertEqual(q["problem_format"], "fill_blank")
                self.assertEqual(q["problem_id"], f"fill_blank_v1_{operation}_10_{position}_{left}_{right}")
                self.assertEqual((q["left_operand"], q["right_operand"]), (left, right))
                record = learning.make_attempt(q, "user_001", "fill", 1, "normal", answer, 2, 1)
                self.assertTrue(record["is_correct"])
                self.assertTrue(record["calculation_correct"])
                self.assertIsNone(record["operation_selection_correct"])
                self.assertIsNone(record["equation_correct"])
                wrong = learning.make_attempt(q, "user_001", "fill", 1, "normal", answer + 1, 2, 1)
                self.assertFalse(wrong["is_correct"])
                self.assertFalse(wrong["calculation_correct"])

    def test_all_valid_base_equations_keep_original_flags_and_old_ids(self):
        for limit in (10, 20):
            for operation in ("addition", "subtraction"):
                for base in learning.problem_pool(operation, limit):
                    for position in fill.POSITIONS:
                        q = fill.make_fill_problem(operation, limit, base["left_operand"], base["right_operand"], position)
                        for field in ("carry", "borrowing", "crosses_10", "zero_included", "doubles", "near_10", "commutative_pair", "operand_contains_10"):
                            self.assertEqual(q[field], base[field])
                        self.assertEqual(q["correct_answer"], base[position])
                        self.assertEqual(q["answer_is_10"], base[position] == 10)
                        self.assertTrue(0 <= q["correct_answer"] <= limit)
                        self.assertTrue(set(q) <= set(learning.COLUMNS))
                    self.assertEqual(base["problem_id"], f"calculation_{operation}_{limit}_{base['left_operand']}_{base['right_operand']}")
                    self.assertEqual(base["blank_position"], "answer")
        legacy = words.make_word_problem("increase", 10, 3, 2)
        self.assertEqual(legacy["problem_id"], "word_v1_increase_10_3_2")
        self.assertEqual(legacy["question_text"], "りんごが 3こ あります。2こ もらいました。いま なんこ ありますか。")

    def test_zero_twenty_and_answer_is_ten_refer_to_hidden_number(self):
        examples = [
            ("addition", 0, 20, "left_operand", 0),
            ("addition", 0, 20, "right_operand", 20),
            ("subtraction", 20, 0, "right_operand", 0),
            ("subtraction", 20, 20, "left_operand", 20),
            ("addition", 10, 2, "left_operand", 10),
            ("addition", 10, 2, "right_operand", 2),
            ("subtraction", 20, 10, "left_operand", 20),
            ("subtraction", 20, 10, "right_operand", 10),
        ]
        for operation, left, right, position, answer in examples:
            q = fill.make_fill_problem(operation, 20, left, right, position)
            self.assertEqual(q["correct_answer"], answer)
            self.assertEqual(q["answer_is_10"], answer == 10)
            self.assertEqual(q["zero_included"], 0 in (left, right))

    def test_common_pool_entry_and_bad_conditions(self):
        self.assertIs(learning.get_problem_pool("calculation"), learning.problem_pool)
        self.assertIs(learning.get_problem_pool("word_problem"), words.word_pool)
        self.assertIs(learning.get_problem_pool("fill_blank"), fill.fill_pool)
        with self.assertRaises(ValueError):
            learning.get_problem_pool("unknown")
        invalid = [
            ("multiply", 10, 2, 3, "left_operand"),
            ("addition", 10.0, 2, 3, "left_operand"),
            ("addition", 10, True, 3, "left_operand"),
            ("addition", 10, 8, 3, "left_operand"),
            ("subtraction", 10, 2, 3, "right_operand"),
            ("addition", 10, 2, 3, "answer"),
            ("addition", 10, -1, 3, "left_operand"),
        ]
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                fill.make_fill_problem(*args)
        with self.assertRaises(ValueError):
            fill.fill_pool("addition", 20, "invalid")

    def test_special_filter_and_balanced_unique_mix_sets(self):
        for limit in (10, 20):
            for mode in ("addition", "subtraction", "mix"):
                for special in ("auto", "none", "with"):
                    for count in (5, 10, 20):
                        error = learning.selection_error(mode, limit, count, special, "fill_blank")
                        if error:
                            with self.assertRaises(ValueError):
                                learning.generate_problems(mode, limit, count, special, "fill_blank")
                            continue
                        items = learning.generate_problems(mode, limit, count, special, "fill_blank")
                        self.assertEqual(len(items), count)
                        self.assertEqual(len({q["problem_id"] for q in items}), count)
                        self.assertEqual(len({q["question_text"] for q in items}), count)
                        left_count = sum(q["blank_position"] == "left_operand" for q in items)
                        self.assertLessEqual(abs(left_count - (count - left_count)), 1)
                        if mode == "mix":
                            self.assertEqual(sum(q["operation"] == "addition" for q in items), (count + 1) // 2)
                        for q in items:
                            self.assertEqual(q["number_range"], limit)
                            flag = q["carry"] if q["operation"] == "addition" else q["borrowing"]
                            if special != "auto":
                                self.assertEqual(flag, special == "with")
        self.assertIsNotNone(learning.selection_error("subtraction", 10, 20, "with", "fill_blank"))
        self.assertIsNotNone(learning.selection_error("addition", 10, 1000, "auto", "fill_blank"))

    def test_three_hints_do_not_reveal_and_explanation_fills_the_original_equation(self):
        for operation in ("addition", "subtraction"):
            for position in fill.POSITIONS:
                left, right = (5, 3) if operation == "addition" else (13, 8)
                q = fill.make_fill_problem(operation, 20, left, right, position)
                hints = fill.hint_steps(q)
                self.assertEqual(len(hints), 3)
                self.assertTrue(all("=" not in hint and not any(c.isdigit() for c in hint) for hint in hints))
                self.assertEqual(fill.guidance(q), hints[0])
                self.assertEqual(words.guidance(q), fill.guidance(q))
                self.assertEqual(words.guidance(q, True), fill.guidance(q, True))
                self.assertIn(f"□は {q['correct_answer']}", fill.guidance(q, True))
                result = left + right if operation == "addition" else left - right
                self.assertIn(f"{left} {'+' if operation == 'addition' else '−'} {right} = {result}", fill.guidance(q, True))

    def test_hidden_answer_persists_once_per_attempt_including_review_and_retry(self):
        q = fill.make_fill_problem("addition", 10, 5, 3, "left_operand")
        with TemporaryDirectory() as folder:
            path = Path(folder) / "fill.sqlite3"
            learning.init_db(path)
            for selection in ("normal", "retry", "review", "review_retry"):
                row = learning.make_attempt(q, "user_001", selection, 1, selection, 5, 2, 1,
                                             round_size=1, hint_level=2)
                learning.save_attempt(row, path)
                learning.save_attempt(row, path)
            rows, more = learning.read_attempts("user_001", path=path)
            self.assertEqual(len(rows), 4)
            self.assertFalse(more)
            for row in rows:
                self.assertEqual(row["correct_answer"], 5)
                self.assertEqual(row["question_text"], "□ + 3 = 8")
                self.assertTrue(row["is_correct"])
                self.assertEqual(row["blank_position"], "left_operand")
                self.assertEqual(row["hint_level"], 2)
            self.assertEqual(learning.read_attempts("user_002", path=path)[0], [])

    def test_parent_test_never_initializes_or_writes_database(self):
        q = fill.make_fill_problem("subtraction", 20, 13, 8, "right_operand")
        row = learning.make_attempt(q, "user_001", "test", 1, "normal", 8, 2, 1)
        with patch.object(learning, "get_supabase_config", side_effect=AssertionError("config read")), \
             patch.object(learning.sqlite3, "connect", side_effect=AssertionError("db read")), \
             patch.object(learning, "supabase_urlopen", side_effect=AssertionError("cloud write")):
            learning.save_attempt(row, test_mode=True)
        with TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.sqlite3"
            learning.save_attempt(row, missing, test_mode=True)
            self.assertFalse(missing.exists())
        with patch.object(learning, "save_attempt", side_effect=AssertionError("write")):
            practice_mode.write_learning_answer({"test_mode": True}, {}, learning.save_attempt, row)
            practice_mode.write_learning_answer({}, {"parent_test_mode": True}, learning.save_attempt, row)

    def test_visual_help_is_separate_from_text_hint_level_and_counts_as_hint(self):
        q = fill.make_fill_problem("addition", 10, 5, 3, "left_operand")
        row = learning.make_attempt(q, "user_001", "visual", 1, "normal", 5, 2, 1, visual_help_used=True)
        self.assertTrue(row["visual_help_used"])
        self.assertTrue(row["hint_used"])
        self.assertEqual(row["hint_level"], 0)
        self.assertTrue(row["is_correct"])
        for invalid in (None, 0, 1, "true"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                learning.make_attempt(q, "user_001", "invalid", 1, "normal", 5, 2, 1, visual_help_used=invalid)

    def test_visual_migration_and_legacy_save_preserve_unknown(self):
        q = fill.make_fill_problem("addition", 10, 5, 3, "left_operand")
        old = learning.make_attempt(q, "user_001", "legacy", 1, "normal", 5, 2, 1)
        old.pop("visual_help_used")
        with TemporaryDirectory() as folder:
            path = Path(folder) / "old.sqlite3"
            columns = {k: v for k, v in learning.COLUMNS.items() if k != "visual_help_used"}
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE attempts (" + ", ".join(f'"{k}" {v}' for k, v in columns.items()) + ")")
                db.execute("INSERT INTO attempts (" + ", ".join(columns) + ") VALUES (" + ", ".join("?" for _ in columns) + ")", [old[k] for k in columns])
            learning.init_db(path)
            learning.init_db(path)
            learning.save_attempt(old, path)
            current = learning.make_attempt(q, "user_001", "current", 1, "normal", 5, 2, 1, visual_help_used=True)
            learning.save_attempt(current, path)
            rows, _ = learning.read_attempts("user_001", path=path)
            self.assertEqual(len(rows), 2)
            self.assertIsNone(next(r for r in rows if r["session_id"] == "legacy")["visual_help_used"])
            self.assertEqual(next(r for r in rows if r["session_id"] == "current")["visual_help_used"], 1)
        # 追加SQL前のクラウド読み込みだけは記録なしで表示できる。
        with patch.object(learning, "get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
             patch.object(learning, "supabase_urlopen") as remote:
            response = remote.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = json.dumps([old]).encode()
            rows, more = learning.read_attempts("user_001")
            self.assertFalse(more)
            self.assertIsNone(rows[0]["visual_help_used"])


if __name__ == "__main__":
    unittest.main()
