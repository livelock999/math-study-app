import unittest

from hint_metrics import summarize_hints


class HintMetricsTests(unittest.TestCase):
    def test_reading_confirmation_keeps_its_own_denominator_and_hint_groups(self):
        rows = [{"is_correct": True, "hint_used": False, "reading_help_used": True},
                {"is_correct": False, "hint_used": True, "reading_help_used": False},
                {"is_correct": True, "hint_used": None, "reading_help_used": 1},
                {"is_correct": False, "hint_used": False, "reading_help_used": None},
                {"is_correct": True, "hint_used": False},
                {"is_correct": True, "hint_used": False, "reading_help_used": "false"},
                {"is_correct": True, "hint_used": False, "reading_help_used": 2}]
        stats = summarize_hints(rows)
        self.assertEqual((stats["reading_known_count"], stats["reading_unknown_count"]), (3, 4))
        self.assertEqual(stats["reading_help_count"], 2)
        self.assertAlmostEqual(stats["reading_help_rate"], 2 / 3)
        # Reading a word is independent of getting a solving hint or being correct.
        self.assertEqual(stats["hint_count"], 1)
        self.assertAlmostEqual(stats["hint_rate"], 1 / 6)
        self.assertEqual((stats["unaided_count"], stats["unaided_correct"]), (5, 4))
        self.assertEqual((stats["assisted_count"], stats["assisted_correct"]), (1, 0))

    def test_legacy_reading_information_remains_unknown(self):
        for value in (None, "true", "false", 2, -1, .0, [], {}):
            with self.subTest(value=value):
                stats = summarize_hints([{"is_correct": True, "hint_used": False,
                                          "reading_help_used": value}])
                self.assertEqual(stats["reading_known_count"], 0)
                self.assertIsNone(stats["reading_help_rate"])
                self.assertEqual(stats["unaided_rate"], 1)

    def test_correctness_and_unknown_are_separate(self):
        rows = [{"hint_used": False, "is_correct": True},
                {"hint_used": 0, "is_correct": False},
                {"hint_used": True, "is_correct": True},
                {"hint_used": 1, "is_correct": True},
                {"hint_used": None, "is_correct": True}, {"is_correct": False}]
        stats = summarize_hints(rows)
        self.assertEqual(stats["hint_rate"], .5)
        self.assertEqual(stats["hint_unknown_count"], 2)
        self.assertEqual((stats["unaided_count"], stats["unaided_rate"]), (2, .5))
        self.assertEqual((stats["assisted_count"], stats["assisted_rate"]), (2, 1))

    def test_empty_and_invalid_records_do_not_claim_no_hint(self):
        for rows in ([], [{"hint_used": "false"}, {"hint_used": 2}]):
            stats = summarize_hints(rows)
            self.assertIsNone(stats["hint_rate"])
            self.assertIsNone(stats["unaided_rate"])
            self.assertIsNone(stats["assisted_rate"])

    def test_japanese_correct_field(self):
        stats = summarize_hints([{"hint_used": True, "correct": False}], "correct")
        self.assertEqual(stats["hint_rate"], 1)
        self.assertEqual(stats["assisted_rate"], 0)
