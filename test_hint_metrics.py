import unittest

from hint_metrics import summarize_hints


class HintMetricsTests(unittest.TestCase):
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
