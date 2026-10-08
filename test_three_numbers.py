"""3つの数：順序、範囲、両段階の属性、教材IDと保存互換性。"""

from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import learning
import practice_mode
import three_numbers as three
import words


class ThreeNumbersTests(unittest.TestCase):
    def test_four_patterns_calculate_from_left_with_stable_ids(self):
        examples = [
            ("addition", "addition", 2, 3, 4, "2 + 3 + 4 = ?", 9),
            ("addition", "subtraction", 5, 3, 2, "5 + 3 − 2 = ?", 6),
            ("subtraction", "addition", 8, 3, 2, "8 − 3 + 2 = ?", 7),
            ("subtraction", "subtraction", 8, 3, 2, "8 − 3 − 2 = ?", 3),
        ]
        for op1, op2, a, b, c, text, answer in examples:
            q = three.make_three_problem(op1, op2, 10, a, b, c)
            self.assertEqual(q["correct_answer"], answer)
            self.assertEqual(q["question_text"], text)
            self.assertEqual((q["operation"], q["second_operation"]), (op1, op2))
            self.assertEqual((q["left_operand"], q["right_operand"], q["third_operand"]), (a, b, c))
            self.assertEqual(q["problem_id"], f"three_numbers_v1_{op1}_{op2}_10_{a}_{b}_{c}")
            self.assertEqual(q["problem_format"], "three_numbers")
            self.assertEqual(q["blank_position"], "answer")
            self.assertIsNone(q["commutative_pair"])
            self.assertTrue(set(q) <= set(learning.COLUMNS))
        # 足し算を先にまとめると別の値になる問題でも、左から解く。
        q = three.make_three_problem("subtraction", "addition", 10, 8, 3, 2)
        self.assertEqual(q["correct_answer"], 7)
        self.assertNotEqual(q["correct_answer"], 8 - (3 + 2))

    def test_both_stage_carry_and_borrow_and_zero_ten_flags(self):
        examples = [
            ("addition", "addition", 8, 5, 2, True, None),
            ("addition", "addition", 3, 5, 7, True, None),
            ("subtraction", "subtraction", 13, 8, 2, None, True),
            ("subtraction", "subtraction", 19, 7, 8, None, True),
            ("subtraction", "addition", 13, 8, 9, True, True),
            ("addition", "subtraction", 8, 5, 7, True, True),
            ("addition", "subtraction", 2, 3, 1, False, False),
        ]
        for op1, op2, a, b, c, carry, borrowing in examples:
            q = three.make_three_problem(op1, op2, 20, a, b, c)
            self.assertEqual(q["carry"], carry)
            self.assertEqual(q["borrowing"], borrowing)
        q = three.make_three_problem("addition", "subtraction", 20, 10, 0, 0)
        self.assertTrue(q["answer_is_10"])
        self.assertTrue(q["operand_contains_10"])
        self.assertTrue(q["zero_included"])
        self.assertEqual(q["correct_answer"], 10)
        q = three.make_three_problem("subtraction", "addition", 20, 20, 20, 20)
        self.assertEqual(q["correct_answer"], 20)
        self.assertFalse(q["zero_included"])
        self.assertFalse(q["operand_contains_10"])
        self.assertFalse(q["answer_is_10"])

    def test_intermediate_bounds_and_invalid_arguments(self):
        invalid = [
            ("addition", "subtraction", 10, 8, 5, 3),  # final10 but intermediate13
            ("subtraction", "addition", 10, 2, 3, 5),  # final4 but intermediate-1
            ("subtraction", "subtraction", 10, 8, 3, 6),
            ("addition", "addition", 20, 10, 10, 1),
            ("multiply", "addition", 10, 2, 3, 4),
            ("addition", "multiply", 10, 2, 3, 4),
            ("addition", "addition", 10.0, 2, 3, 4),
            ("addition", "addition", 10, True, 3, 4),
            ("addition", "addition", 10, 2, -1, 4),
        ]
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                three.make_three_problem(*args)
        for args in (("addition", 10, "bad"), ("addition", 10, "auto", "multiply")):
            with self.assertRaises(ValueError):
                three.three_pool(*args)
        for mode in ("invalid",):
            with self.assertRaises(ValueError):
                three.mode_pool(mode, 10)
        for count in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                three.generate_three("mix", 10, count)

    def test_pools_respect_all_bounds_specials_and_fixed_second_operation(self):
        for limit in (10, 20):
            for first in three.OPERATIONS:
                all_items = three.three_pool(first, limit)
                self.assertEqual(len(all_items), len({q["problem_id"] for q in all_items}))
                self.assertEqual(len(all_items), len({q["question_text"] for q in all_items}))
                self.assertEqual({q["second_operation"] for q in all_items}, set(three.OPERATIONS))
                for q in all_items:
                    a, b, c = q["left_operand"], q["right_operand"], q["third_operand"]
                    intermediate = a + b if first == "addition" else a - b
                    result = intermediate + c if q["second_operation"] == "addition" else intermediate - c
                    self.assertTrue(all(0 <= n <= limit for n in (a, b, c, intermediate, result)))
                    self.assertEqual(result, q["correct_answer"])
                for special in ("none", "with"):
                    items = three.three_pool(first, limit, special)
                    self.assertTrue(items)
                    self.assertTrue(all(bool(q["carry"] or q["borrowing"]) == (special == "with") for q in items))
                for second in three.OPERATIONS:
                    fixed = three.three_pool(first, limit, second_operation=second)
                    self.assertTrue(all(q["second_operation"] == second for q in fixed))

    def test_balanced_mix_and_standard_dispatch_without_duplicate_ids(self):
        self.assertIs(learning.get_problem_pool("three_numbers"), three.three_pool)
        for limit in (10, 20):
            for special in ("auto", "none", "with"):
                for mode in ("addition", "subtraction", "mix"):
                    for count in (5, 10, 20):
                        self.assertIsNone(learning.selection_error(mode, limit, count, special, "three_numbers"))
                        items = learning.generate_problems(mode, limit, count, special, "three_numbers")
                        self.assertEqual(len(items), count)
                        self.assertEqual(len({q["problem_id"] for q in items}), count)
                        counts = Counter((q["operation"], q["second_operation"]) for q in items)
                        if mode == "mix":
                            self.assertEqual(set(counts), set(three.PATTERNS))
                            self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
                        else:
                            self.assertEqual(set(counts), {(mode, mode)})
                        self.assertTrue(all(q["number_range"] == limit for q in items))
        self.assertIsNotNone(learning.selection_error("addition", 10, 1000, "with", "three_numbers"))
        with self.assertRaises(ValueError):
            learning.generate_problems("addition", 10, 1000, "with", "three_numbers")

    def test_hints_scaffold_first_step_then_intermediate_but_not_final_answer(self):
        for op1, op2 in three.PATTERNS:
            a, b, c = (8, 3, 2) if op1 == "subtraction" else (5, 3, 2)
            q = three.make_three_problem(op1, op2, 20, a, b, c)
            steps = three.hint_steps(q)
            self.assertEqual(len(steps), 3)
            self.assertTrue(all("=" not in step and "さいごの こたえは" not in step for step in steps))
            self.assertEqual(three.guidance(q), steps[0])
            self.assertEqual(words.guidance(q), steps[0])
            intermediate = a + b if op1 == "addition" else a - b
            self.assertEqual(steps[1], f"まず {a} {'+' if op1 == 'addition' else '−'} {b} を けいさんしよう。")
            self.assertIn(f"はじめの こたえは {intermediate}", steps[2])
            self.assertIn(f"つぎに {intermediate} {'+' if op2 == 'addition' else '−'} {c}", steps[2])
            self.assertNotIn(f"こたえは {q['correct_answer']} だよ", steps[2])
            revealed = three.guidance(q, True)
            self.assertIn(f"{a} {'+' if op1 == 'addition' else '−'} {b} = {intermediate}", revealed)
            self.assertIn(f"{intermediate} {'+' if op2 == 'addition' else '−'} {c} = {q['correct_answer']}", revealed)
            self.assertEqual(words.guidance(q, True), revealed)
        # 0を足す/引く場合は途中の値と最終値が一致するが、最後の計算は残す。
        zero = three.make_three_problem("addition", "subtraction", 10, 2, 3, 0)
        self.assertTrue(three.hint_steps(zero)[2].endswith("つぎに 5 − 0 を けいさんしよう。"))

    def test_answer_record_final_result_unknown_and_idempotent_storage(self):
        q = three.make_three_problem("subtraction", "addition", 20, 13, 8, 9)
        correct = learning.make_attempt(q, "user_001", "three", 1, "normal", 14, 3, 1, round_size=1)
        wrong = learning.make_attempt(q, "user_001", "review", 1, "review", 5, 3, 1)
        unknown = learning.make_attempt(q, "user_001", "unknown", 1, "normal", None, 3, 1, dont_know_used=True)
        self.assertTrue(correct["is_correct"])
        self.assertTrue(correct["calculation_correct"])
        self.assertFalse(wrong["is_correct"])
        self.assertFalse(unknown["is_correct"])
        self.assertIsNone(unknown["user_answer"])
        self.assertIsNone(unknown["calculation_correct"])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "three.sqlite3"
            learning.init_db(path)
            for row in (correct, wrong, unknown):
                learning.save_attempt(row, path)
                learning.save_attempt(row, path)
            rows, more = learning.read_attempts("user_001", path=path)
            self.assertEqual(len(rows), 3)
            self.assertFalse(more)
            self.assertTrue(all(r["third_operand"] == 9 and r["second_operation"] == "addition" for r in rows))
            self.assertEqual(learning.read_attempts("user_002", path=path)[0], [])

    def test_old_ids_and_nullable_migration_preserve_old_records(self):
        from fill_blank import make_fill_problem
        old = learning.make_attempt(learning.make_problem("addition", 10, 2, 3), "user_001", "old", 1, "normal", 5, 2, 1)
        self.assertEqual(old["problem_id"], "calculation_addition_10_2_3")
        self.assertEqual(words.make_word_problem("increase", 10, 2, 3)["problem_id"], "word_v1_increase_10_2_3")
        self.assertEqual(make_fill_problem("addition", 10, 2, 3, "left_operand")["problem_id"], "fill_blank_v1_addition_10_left_operand_2_3")
        old.pop("third_operand")
        old.pop("second_operation")
        columns = {k: v for k, v in learning.COLUMNS.items() if k not in ("third_operand", "second_operation")}
        with TemporaryDirectory() as folder:
            path = Path(folder) / "old.sqlite3"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE attempts (" + ", ".join(f'"{k}" {v}' for k, v in columns.items()) + ")")
                db.execute("INSERT INTO attempts (" + ", ".join(columns) + ") VALUES (" + ", ".join("?" for _ in columns) + ")", [old[k] for k in columns])
            learning.init_db(path)
            learning.init_db(path)
            learning.save_attempt(old, path)
            rows, _ = learning.read_attempts("user_001", path=path)
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0]["third_operand"])
            self.assertIsNone(rows[0]["second_operation"])
            self.assertEqual(rows[0]["problem_id"], old["problem_id"])

    def test_cloud_roundtrip_and_legacy_reads_need_no_local_fallback(self):
        q = three.make_three_problem("addition", "subtraction", 20, 8, 5, 7)
        row = learning.make_attempt(q, "user_001", "cloud", 1, "normal", 6, 3, 1)
        with patch.object(learning, "get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
             patch.object(learning, "supabase_urlopen") as remote, \
             patch.object(learning.sqlite3, "connect", side_effect=AssertionError("local fallback")):
            response = remote.return_value.__enter__.return_value
            response.status = 201
            learning.save_attempt(row)
            posted = json.loads(remote.call_args.args[0].data)
            self.assertEqual(posted["third_operand"], 7)
            self.assertEqual(posted["second_operation"], "subtraction")
            response.status = 200
            response.read.return_value = json.dumps([posted]).encode()
            self.assertEqual(learning.read_attempts("user_001")[0], [row])
            old = learning.make_attempt(learning.make_problem("addition", 10, 2, 3), "user_001", "legacy", 1, "normal", 5, 2, 1)
            old.pop("third_operand")
            old.pop("second_operation")
            response.read.return_value = json.dumps([old]).encode()
            restored = learning.read_attempts("user_001")[0][0]
            self.assertIsNone(restored["third_operand"])
            self.assertIsNone(restored["second_operation"])

    def test_parent_test_does_not_read_or_save_any_store(self):
        row = learning.make_attempt(three.make_three_problem("addition", "addition", 10, 2, 3, 4),
                                    "user_001", "test", 1, "normal", 9, 2, 1)
        with patch.object(learning, "get_supabase_config", side_effect=AssertionError("config read")), \
             patch.object(learning.sqlite3, "connect", side_effect=AssertionError("DB")), \
             patch.object(learning, "supabase_urlopen", side_effect=AssertionError("cloud")):
            learning.save_attempt(row, test_mode=True)
        with patch.object(learning, "save_attempt", side_effect=AssertionError("write")):
            practice_mode.write_learning_answer({"test_mode": True}, {}, learning.save_attempt, row)
            practice_mode.write_learning_answer({}, {"parent_test_mode": True}, learning.save_attempt, row)


if __name__ == "__main__":
    unittest.main()
