"""Three-number history backups retain operands, operations and stable IDs."""

from contextlib import closing
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError
import json
import re
import sqlite3
import unittest

import history_backup as backup
import japanese
import learning
import three_numbers
from test_history_backup import Response, encoded_changed, japanese_record, math_record, parsed
from test_restore_fill_blank import fill_record


def three_record(op1="addition", op2="subtraction", limit=10, left=5, right=3, third=2, **updates):
    problem = learning.make_problem(op1, limit, left, right)
    middle = problem["correct_answer"]
    result = middle + third if op2 == "addition" else middle - third
    problem.update(problem_format="three_numbers", third_operand=third, second_operation=op2,
                   problem_id=f"three_numbers_v1_{op1}_{op2}_{limit}_{left}_{right}_{third}",
                   question_text=f"{left} {'+' if op1 == 'addition' else '−'} {right} {'+' if op2 == 'addition' else '−'} {third} = ?",
                   correct_answer=result)
    row = learning.make_attempt(problem, "user_001", "three_session", 1, "normal", result, 1, 1, round_size=5)
    row.update(updates)
    if 'is_correct' in updates and 'first_attempt_correct' not in updates:
        row['first_attempt_correct'] = updates['is_correct']
    return row


class ThreeNumberBackupTests(unittest.TestCase):
    def test_actual_material_builder_records_roundtrip_all_operation_patterns(self):
        examples = [("addition", "addition", 20, 9, 5, 6),
                    ("addition", "subtraction", 20, 9, 5, 7),
                    ("subtraction", "addition", 20, 13, 5, 7),
                    ("subtraction", "subtraction", 20, 20, 8, 7)]
        rows = []
        for args in examples:
            problem = three_numbers.make_three_problem(*args)
            rows.append(learning.make_attempt(problem, "user_001", "s", 1, "normal", problem["correct_answer"], 1, 1))
        self.assertEqual(parsed(rows, [])["math"], rows)

    def test_four_operations_and_boundary_numbers_are_preserved(self):
        examples = [("addition", "addition", 10, 2, 3, 4, 9),
                    ("addition", "subtraction", 10, 8, 2, 3, 7),
                    ("subtraction", "addition", 10, 8, 3, 4, 9),
                    ("subtraction", "subtraction", 10, 9, 2, 3, 4),
                    ("addition", "addition", 20, 9, 5, 6, 20),
                    ("addition", "subtraction", 20, 9, 5, 7, 7),
                    ("subtraction", "addition", 20, 13, 5, 7, 15),
                    ("subtraction", "subtraction", 20, 20, 8, 7, 5),
                    ("addition", "addition", 10, 0, 0, 0, 0),
                    ("subtraction", "addition", 20, 20, 20, 20, 20)]
        rows = [three_record(*example[:-1]) for example in examples]
        value = parsed(rows, [])
        for before, after, example in zip(rows, value["math"], examples):
            for field in ("left_operand", "right_operand", "third_operand", "operation", "second_operation", "problem_id", "question_text"):
                self.assertEqual(after[field], before[field])
            self.assertEqual(after["correct_answer"], example[-1])

    def test_invalid_third_operand_operation_identity_and_answer_are_rejected_before_io(self):
        value = parsed([three_record()], [])
        changes = ({"third_operand": None}, {"third_operand": True}, {"third_operand": -1}, {"third_operand": 11},
                   {"second_operation": None}, {"second_operation": "multiply"},
                   {"correct_answer": 8}, {"problem_id": "calculation_addition_10_5_3"},
                   {"problem_id": "three_numbers_v1_addition_addition_10_5_3_2"})
        for change in changes:
            with self.subTest(change=change), patch.object(backup.sqlite3, "connect", side_effect=AssertionError("DB read")), \
                 patch.object(learning, "get_supabase_config", side_effect=AssertionError("config read")), \
                 patch.object(learning, "supabase_urlopen", side_effect=AssertionError("network")), self.assertRaises(ValueError):
                backup.parse_backup(encoded_changed(value, lambda data: data["math"][0].update(change)), "user_001")

    def test_intermediate_and_final_must_both_fit_selected_range(self):
        for args in (("addition", "subtraction", 10, 9, 9, 9),  # final 9 but middle 18
                     ("subtraction", "addition", 10, 3, 5, 8),  # final 6 but middle -2
                     ("addition", "addition", 10, 5, 3, 3),  # middle 8 but final 11
                     ("subtraction", "subtraction", 20, 15, 8, 9)):  # middle 7 but final -2
            with self.subTest(args=args), self.assertRaises(ValueError):
                parsed([three_record(*args)], [])

    def test_old_json_missing_new_fields_and_two_number_formats_keep_nulls(self):
        rows = [math_record(), fill_record(), math_record(problem_format="word_problem", story_type="increase")]
        for row in rows:
            row.pop("third_operand", None)
            row.pop("second_operation", None)
        # This checksum describes an actual pre-migration file, not normalized data.
        value = parsed(rows, [])
        for row in value["math"]:
            self.assertIsNone(row["third_operand"])
            self.assertIsNone(row["second_operation"])
        for index in range(3):
            for fields in ({"third_operand": 2}, {"second_operation": "addition"}):
                with self.subTest(index=index, fields=fields), self.assertRaises(ValueError):
                    backup.parse_backup(encoded_changed(value, lambda data: data["math"][index].update(fields)), "user_001")

    def test_three_digit_error_and_both_arithmetic_flags_roundtrip(self):
        row = three_record("addition", "subtraction", 20, 9, 5, 7, user_answer=999,
                           is_correct=False, calculation_correct=False, carry=True, borrowing=True,
                           visual_help_used=True, hint_used=True, hint_level=0)
        actual = parsed([row], [])["math"][0]
        self.assertEqual(actual["user_answer"], 999)
        self.assertEqual(actual["correct_answer"], 7)
        self.assertTrue(actual["carry"] and actual["borrowing"] and actual["visual_help_used"])
        self.assertEqual(actual["hint_level"], 0)

    def test_parent_dry_run_and_malformed_restore_do_no_store_io(self):
        value = parsed([three_record()], [japanese_record()])
        with patch.object(learning, "get_supabase_config", side_effect=AssertionError("config read")), \
             patch.object(backup.sqlite3, "connect", side_effect=AssertionError("DB read")), \
             patch.object(learning, "supabase_urlopen", side_effect=AssertionError("network")):
            self.assertTrue(backup.restore_backup(value, test_mode=True)["test_mode"])
            wrong = deepcopy(value)
            wrong["math"][0]["third_operand"] = None
            wrong["checksum"] = backup._checksum(wrong)
            with self.assertRaises(ValueError):
                backup.restore_backup(wrong, test_mode=True)


class ThreeNumberRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.math_path = Path(self.temp.name) / "math.sqlite3"
        self.jp_path = Path(self.temp.name) / "japanese.sqlite3"
        learning.init_db(self.math_path)
        japanese.init_db(self.jp_path)

    def restore(self, value):
        return backup.restore_backup(value, math_path=self.math_path, japanese_path=self.jp_path)

    def test_additive_restore_and_repeat_preserve_old_and_three_number_meanings(self):
        old = math_record(attempt_id="old_math")
        learning.save_attempt(old, self.math_path)
        rows = [three_record(), three_record("subtraction", "addition", 20, 13, 5, 7, selection_type="review")]
        value = parsed(rows, [japanese_record()])
        self.assertEqual(self.restore(value), dict(math_added=2, japanese_added=1, math_existing=0, japanese_existing=0))
        self.assertEqual(self.restore(value), dict(math_added=0, japanese_added=0, math_existing=2, japanese_existing=1))
        restored = learning.read_attempts("user_001", path=self.math_path)[0]
        self.assertEqual(len(restored), 3)
        for row in restored:
            if row["attempt_id"] == "old_math":
                self.assertIsNone(row["third_operand"])
                self.assertIsNone(row["second_operation"])
                self.assertEqual(row["correct_answer"], 5)
            else:
                source = next(item for item in rows if item["attempt_id"] == row["attempt_id"])
                self.assertEqual((row["third_operand"], row["second_operation"], row["correct_answer"]),
                                 (source["third_operand"], source["second_operation"], source["correct_answer"]))

    def test_other_learner_or_second_subject_id_conflict_has_no_partial_writes(self):
        row, jp_row = three_record(), japanese_record()
        japanese.save_record({**jp_row, "user_id": "user_002"}, self.jp_path)
        with self.assertRaises(ValueError):
            self.restore(parsed([row], [jp_row]))
        self.assertEqual(learning.read_attempts("user_001", path=self.math_path)[0], [])
        learning.save_attempt({**row, "user_id": "user_002"}, self.math_path)
        with self.assertRaises(ValueError):
            self.restore(parsed([row], []))
        self.assertEqual(learning.read_attempts("user_001", path=self.math_path)[0], [])

    def test_failure_in_second_subject_rolls_back_and_same_ids_retry_safely(self):
        value = parsed([three_record()], [japanese_record()])
        with closing(sqlite3.connect(self.jp_path)) as db, db:
            db.execute("CREATE TRIGGER reject_restore BEFORE INSERT ON japanese_attempts BEGIN SELECT RAISE(ABORT,'temporary failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.restore(value)
        self.assertEqual(learning.read_attempts("user_001", path=self.math_path)[0], [])
        with closing(sqlite3.connect(self.jp_path)) as db, db:
            db.execute("DROP TRIGGER reject_restore")
        self.assertEqual(self.restore(value)["math_added"], 1)
        self.assertEqual(self.restore(value)["math_existing"], 1)


class ThreeNumberCloudRestoreTests(unittest.TestCase):
    def test_uncertain_cloud_retry_uses_one_transaction_and_exact_same_payload(self):
        value = parsed([three_record()], [])
        counts = dict(math_added=0, japanese_added=0, math_existing=1, japanese_existing=0)
        with patch.object(learning, "get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
             patch.object(learning, "supabase_urlopen", side_effect=[URLError("timeout"), Response(counts)]) as call, \
             patch.object(backup.sqlite3, "connect", side_effect=AssertionError("local fallback")):
            with self.assertRaises(OSError):
                backup.restore_backup(value)
            self.assertEqual(backup.restore_backup(value), counts)
        request = call.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/rpc/restore_answer_history"))
        self.assertEqual(call.call_args_list[0].args[0].data, request.data)
        payload = json.loads(request.data)["backup"]["math"][0]
        self.assertEqual((payload["third_operand"], payload["second_operation"], payload["correct_answer"]), (2, "subtraction", 6))

    def test_additive_sql_keeps_legacy_rows_and_rejects_skipped_column_migration(self):
        addition = Path("supabase_three_numbers.sql").read_text(encoding="utf-8").lower()
        restore = Path("supabase_history_restore.sql").read_text(encoding="utf-8").lower()
        setup = Path("supabase_setup.sql").read_text(encoding="utf-8").lower()
        self.assertIn("add column if not exists third_operand integer", addition)
        self.assertIn("add column if not exists second_operation text", addition)
        self.assertNotIn("update ", addition)
        self.assertNotIn("delete ", addition)
        self.assertIn("third_operand integer", setup)
        self.assertIn("second_operation text", setup)
        self.assertIn("apply supabase_three_numbers.sql before restoring history", restore)
        self.assertIn("invalid three-number operand, operation, answer or id", restore)
        self.assertNotIn("grant update", restore)
        spec = json.loads(re.search(r"spec := '(.+?)'::jsonb", restore).group(1))
        self.assertEqual(set(spec), set(learning.COLUMNS))
        self.assertEqual(spec["third_operand"], ["integer", False])
        self.assertEqual(spec["second_operation"], ["string", False])


if __name__ == "__main__":
    unittest.main()
