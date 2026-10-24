"""Card backup compatibility without touching family or cloud histories."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import re
import unittest

import history_backup as backup
import learning
import japanese


def record(**changes):
    row = learning.make_attempt(learning.make_problem("addition", 10, 2, 3),
                                "user_001", "session", 1, "normal", 5, 2.5, 1, round_size=5)
    row.update(learning_mode="flashcard", answer_range_min=1, answer_range_max=10,
               input_method="voice", recognized_text="ご", parsed_answer=5,
               recognition_success=True, recognition_retry_count=2,
               first_attempt_correct=True, session_elapsed_sec=3.0,
               total_recognition_retry_count=2)
    row.update(changes)
    return row


def roundtrip(row):
    return backup.parse_backup(backup.export_backup("user_001", [row], []), "user_001")


def extended_record(operation='addition', left=100, right=100, answer=None, method='voice'):
    problem = learning.make_problem(operation, 200, left, right)
    answer = problem['correct_answer'] if answer is None else answer
    row = learning.make_attempt(problem, 'user_001', 'expanded-session', 1, 'normal', answer, 2, 1)
    row.update(learning_mode='flashcard', answer_range_min=0, answer_range_max=200,
               input_method=method, recognized_text=str(answer) if method == 'voice' else None,
               parsed_answer=answer if method == 'voice' else None,
               recognition_success=True if method == 'voice' else None,
               recognition_retry_count=0, total_recognition_retry_count=0,
               first_attempt_correct=row['is_correct'], session_elapsed_sec=2)
    return row


class CardBackupTests(unittest.TestCase):
    def test_expanded_cards_save_export_and_restore_preserve_200_zero_and_recognized_error(self):
        rows = [extended_record(), extended_record('addition', 0, 0),
                extended_record('subtraction', 100, 0), extended_record('subtraction', 100, 100),
                extended_record(answer=999), extended_record(method='keypad'), record()]
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'source.sqlite3'
            target = Path(folder) / 'restored.sqlite3'
            jp_path = Path(folder) / 'jp.sqlite3'
            learning.init_db(source)
            learning.init_db(target)
            japanese.init_db(jp_path)
            for row in rows:
                learning.save_attempt(row, source)
            saved, _ = learning.read_attempts('user_001', path=source)
            data = backup.export_backup('user_001', saved, [])
            imported = backup.parse_backup(data, 'user_001')
            self.assertEqual(backup.restore_backup(imported, math_path=target, japanese_path=jp_path)['math_added'], 7)
            self.assertEqual(backup.restore_backup(imported, math_path=target, japanese_path=jp_path)['math_existing'], 7)
            actual, _ = learning.read_attempts('user_001', path=target)
            self.assertEqual({r['attempt_id']: r for r in actual}, {r['attempt_id']: r for r in saved})
            self.assertIn(200, [r['correct_answer'] for r in actual])
            wrong = next(r for r in actual if r['user_answer'] == 999)
            self.assertEqual(wrong['parsed_answer'], 999)
            self.assertFalse(wrong['is_correct'])

    def test_range_200_is_restricted_to_calculation_flashcards(self):
        invalid = ({'learning_mode': 'normal'}, {'learning_mode': None}, {'learning_mode': 'retry'},
                   {'problem_format': 'word_problem'}, {'problem_format': 'fill_blank'},
                   {'problem_format': 'three_numbers'}, {'problem_format': 'three_word_problem'},
                   {'number_range': 201}, {'number_range': 100})
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                roundtrip({**extended_record(), **fields})

    def test_expanded_cards_reject_operands_over_100_negative_results_and_invalid_ranges(self):
        invalid = ({'left_operand': 101, 'right_operand': 0, 'correct_answer': 101},
                   {'left_operand': 0, 'right_operand': 101, 'correct_answer': 101},
                   {'left_operand': -1, 'right_operand': 2, 'correct_answer': 1},
                   {'operation': 'subtraction', 'left_operand': 0, 'right_operand': 1, 'correct_answer': -1},
                   {'correct_answer': 199}, {'answer_range_max': 201}, {'answer_range_min': 201},
                   {'answer_range_min': None}, {'user_answer': 1000, 'parsed_answer': 1000},
                   {'user_answer': -1, 'parsed_answer': -1}, {'parsed_answer': 199},
                   {'parsed_answer': True})
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                roundtrip({**extended_record(), **fields})
        with self.assertRaises(ValueError):
            roundtrip(record(answer_range_max=200))  # Existing 10/20 records keep their range.

    def test_subtraction_zero_and_mixed_session_roundtrip_without_new_columns(self):
        records = []
        for index, (operation, left, right, method) in enumerate((('subtraction', 5, 5, 'voice'),
                                                               ('subtraction', 13, 4, 'keypad'),
                                                               ('addition', 9, 4, 'keyboard')), 1):
            problem = learning.make_problem(operation, 20, left, right)
            answer = problem['correct_answer']
            row = learning.make_attempt(problem, 'user_001', 'mixed-session', index, 'normal', answer, 2, 1, round_size=3)
            row.update(learning_mode='flashcard', answer_range_min=0, answer_range_max=18,
                       input_method=method, recognized_text='れい' if method == 'voice' else None,
                       parsed_answer=answer if method == 'voice' else None,
                       recognition_success=True if method == 'voice' else None,
                       recognition_retry_count=1, total_recognition_retry_count=index,
                       session_elapsed_sec=index * 3, first_attempt_correct=True)
            records.append(row)
        value = backup.parse_backup(backup.export_backup('user_001', records, []), 'user_001')
        self.assertEqual(value['math'], records)
        self.assertEqual(value['math'][0]['parsed_answer'], 0)
        with TemporaryDirectory() as folder:
            math_path, jp_path = Path(folder) / 'math.sqlite3', Path(folder) / 'jp.sqlite3'
            learning.init_db(math_path)
            japanese.init_db(jp_path)
            self.assertEqual(backup.restore_backup(value, math_path=math_path, japanese_path=jp_path)['math_added'], 3)
            self.assertEqual(backup.restore_backup(value, math_path=math_path, japanese_path=jp_path)['math_existing'], 3)
            rows, _ = learning.read_attempts('user_001', path=math_path)
            self.assertEqual({row['operation'] for row in rows}, {'addition', 'subtraction'})
            self.assertEqual(sum(row['round_completed'] for row in rows), 1)

    def test_voice_roundtrip_and_boolean_normalization(self):
        result = roundtrip(record(recognition_success=1, first_attempt_correct=1))["math"][0]
        self.assertIs(result["recognition_success"], True)
        self.assertIs(result["first_attempt_correct"], True)
        self.assertEqual(result["recognized_text"], "ご")
        self.assertEqual(result["recognition_retry_count"], 2)

    def test_legacy_missing_fields_remain_null(self):
        row = record()
        for name in learning.FLASHCARD_COLUMNS:
            row.pop(name)
        restored = roundtrip(row)["math"][0]
        for name in learning.FLASHCARD_COLUMNS:
            self.assertIsNone(restored[name], name)

    def test_three_digit_errors_preserved_for_normal_voice_and_keypad_answers(self):
        row = learning.make_attempt(learning.make_problem("addition", 10, 2, 3),
                                    "user_001", "normal_session", 1, "normal", 999, 2.5, 1)
        result = roundtrip(row)["math"][0]
        self.assertEqual(result["user_answer"], 999)
        self.assertIs(result["first_attempt_correct"], False)
        voice = roundtrip(record(user_answer=999, parsed_answer=999, is_correct=False,
                                 first_attempt_correct=False))['math'][0]
        self.assertEqual(voice['parsed_answer'], 999)
        keypad = roundtrip(record(input_method="keypad", recognized_text=None, parsed_answer=None,
                                 recognition_success=None, user_answer=999, is_correct=False,
                                 first_attempt_correct=False))['math'][0]
        self.assertEqual(keypad['user_answer'], 999)
        self.assertIsNone(keypad['parsed_answer'])

    def test_voice_metadata_and_semantic_corruption_rejected(self):
        changes = ({"recognition_success": False}, {"recognition_success": 2},
                   {"parsed_answer": 9}, {"recognized_text": None},
                   {"recognition_retry_count": -1}, {"recognition_retry_count": True},
                   {"total_recognition_retry_count": 1}, {"session_elapsed_sec": 1},
                   {"first_attempt_correct": False}, {"input_method": "keyboard"},
                   {"answer_range_min": 6}, {"answer_range_max": None},
                   {"learning_mode": "unknown"})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                roundtrip(record(**change))

    def test_keyboard_card_preserves_prior_voice_failures_without_voice_answer(self):
        row = record(input_method="keypad", recognized_text=None, parsed_answer=None,
                     recognition_success=None, recognition_retry_count=2)
        result = roundtrip(row)["math"][0]
        self.assertEqual(result["input_method"], "keypad")
        self.assertEqual(result["recognition_retry_count"], 2)
        self.assertEqual(result["total_recognition_retry_count"], 2)
        for field in ("recognized_text", "parsed_answer", "recognition_success"):
            self.assertIsNone(result[field])
        row["recognition_retry_count"] = None
        self.assertIsNone(roundtrip(row)["math"][0]["recognition_retry_count"])

    def test_restore_twice_is_additive_and_preserves_card_fields(self):
        with TemporaryDirectory() as folder:
            math_path, jp_path = Path(folder) / "math.sqlite3", Path(folder) / "jp.sqlite3"
            learning.init_db(math_path)
            japanese.init_db(jp_path)
            value = roundtrip(record())
            first = backup.restore_backup(value, math_path=math_path, japanese_path=jp_path)
            second = backup.restore_backup(value, math_path=math_path, japanese_path=jp_path)
            self.assertEqual(first["math_added"], 1)
            self.assertEqual(second["math_existing"], 1)
            rows, _ = learning.read_attempts("user_001", path=math_path)
            self.assertEqual(rows[0]["recognized_text"], "ご")
            self.assertEqual(rows[0]["total_recognition_retry_count"], 2)

    def test_rpc_spec_matches_all_columns_and_migration_is_additive(self):
        sql = Path("supabase_history_restore.sql").read_text(encoding="utf-8")
        spec = json.loads(re.search(r"spec := '(.*?)'::jsonb;", sql).group(1))
        self.assertEqual(set(spec), set(learning.COLUMNS))
        for name in ("recognition_success", "first_attempt_correct"):
            self.assertEqual(spec[name], ["boolean", False])
        migration = Path("supabase_flashcards.sql").read_text(encoding="utf-8").lower()
        self.assertEqual(migration.count("add column if not exists"), len(learning.FLASHCARD_COLUMNS))
        for forbidden in ("update public", "delete from", "grant ", "revoke ", "default "):
            self.assertNotIn(forbidden, migration)


if __name__ == "__main__":
    unittest.main()
