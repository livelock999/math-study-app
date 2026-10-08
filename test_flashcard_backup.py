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


class CardBackupTests(unittest.TestCase):
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

    def test_normal_three_digit_error_preserved_but_card_and_voice_are_two_digits(self):
        row = learning.make_attempt(learning.make_problem("addition", 10, 2, 3),
                                    "user_001", "normal_session", 1, "normal", 999, 2.5, 1)
        result = roundtrip(row)["math"][0]
        self.assertEqual(result["user_answer"], 999)
        self.assertIs(result["first_attempt_correct"], False)
        with self.assertRaises(ValueError):
            roundtrip(record(user_answer=999, parsed_answer=999, is_correct=False,
                             first_attempt_correct=False))
        with self.assertRaises(ValueError):
            roundtrip(record(input_method="keypad", recognized_text=None, parsed_answer=None,
                             recognition_success=None, user_answer=999, is_correct=False,
                             first_attempt_correct=False))

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
