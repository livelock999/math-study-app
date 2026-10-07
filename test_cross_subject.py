import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from cross_subject import build_report, load_records
from activity import JST

NOW = datetime(2026, 10, 7, 21, tzinfo=JST)


def math_row(identifier="m1", **changes):
    return {"attempt_id": identifier, "user_id": "user_001", "datetime": "2026-10-07T10:00:00+09:00",
            "selection_type": "normal", "is_correct": False, "problem_format": "calculation", **changes}


def jp_row(identifier="j1", **changes):
    return {"attempt_id": identifier, "user_id": "user_001", "datetime": "2026-10-07T10:00:00+09:00",
            "selection_type": "normal", "correct": True, "attempt_count": 1,
            "reading_mode": "self_read", "category": "sentence", **changes}


class CrossSubjectTests(unittest.TestCase):
    def test_user_separation_dedup_and_initial_retry(self):
        m = math_row()
        report = build_report([m, m, math_row("other", user_id="user_002"),
                               math_row("retry", selection_type="retry", is_correct=True)],
                              [jp_row(), jp_row("weak", selection_type="weak_area"),
                               jp_row("retry", selection_type="retry", attempt_count=2, correct=False)],
                              "user_001", now=NOW)
        self.assertEqual(report["total"], 5)
        self.assertEqual(report["days"], 1)
        self.assertEqual(report["subjects"]["math"]["initial"]["rate"], 0)
        self.assertEqual(report["subjects"]["japanese"]["initial"]["count"], 2)
        self.assertEqual(report["subjects"]["japanese"]["retry"]["rate"], 0)

    def test_jst_inclusive_day_boundary_future_and_all_period(self):
        rows = [math_row("start", datetime="2026-09-30T15:00:00+00:00"),
                math_row("old", datetime="2026-09-30T14:59:59+00:00"),
                math_row("future", datetime="2026-10-07T21:01:00+09:00")]
        report = build_report(rows, [], "user_001", days=7, now=NOW)
        self.assertEqual(report["total"], 1)
        self.assertEqual(next(iter(report["daily"])).isoformat(), "2026-10-01")
        self.assertEqual(build_report(rows, [], "user_001", days=None, now=NOW)["total"], 2)

    def test_word_components_legacy_null_and_audio_separation(self):
        words = [math_row(str(i), problem_format="word_problem", operation_selection_correct=True,
                          equation_correct=None if i == 0 else False, calculation_correct=True) for i in range(5)]
        report = build_report(words, [jp_row(), jp_row("audio", reading_mode="audio")], "user_001", now=NOW)
        groups = report["groups"]
        self.assertEqual(groups[0]["count"], 0)
        self.assertEqual(groups[2]["rate"], 1)
        self.assertEqual(groups[3]["count"], 4)
        self.assertEqual(groups[3]["status"], "判断保留（5問未満）")
        self.assertEqual(groups[4]["rate"], 1)
        self.assertEqual(groups[5]["count"], 1)

    def test_suggestions_use_five_initial_answers_and_threshold(self):
        for correct, expected in ((3, "練習を提案"), (4, "練習を継続")):
            report = build_report([math_row(str(i), is_correct=i < correct) for i in range(5)], [],
                                  "user_001", now=NOW)
            self.assertEqual(report["groups"][0]["status"], expected)
        empty = build_report([], [], "user_001", now=NOW)
        self.assertIsNone(empty["subjects"]["math"]["initial"]["rate"])

    def test_loader_reads_beyond_500_and_propagates_failure(self):
        batches = [([math_row(str(i)) for i in range(100)], True)] * 6 + [([], False)]
        with patch("learning.read_attempts", side_effect=batches) as read, patch("japanese.init_db"), \
                patch("japanese.read_all", return_value=[]):
            math, _ = load_records("user_001")
        self.assertEqual(len(math), 600)
        self.assertEqual(read.call_count, 7)
        with patch("learning.read_attempts", return_value=([], False)), patch("japanese.init_db"), \
                patch("japanese.read_all", side_effect=OSError("private_secret")):
            with self.assertRaises(OSError):
                load_records("user_001")

    def test_ui_both_subjects_back_preserves_progress_and_failure(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as directory, \
                patch("learning.DB_PATH", Path(directory) / "math.sqlite3"), \
                patch("japanese.DB_PATH", Path(directory) / "jp.sqlite3"), \
                patch("learning.get_supabase_config", return_value=None), \
                patch.dict("os.environ", {"MATH_REQUIRE_PASSWORD": "false"}):
            app = AppTest.from_file("app.py").run()
            app.button(key="select_user_001").click().run()
            app.session_state["round"] = {"sentinel": "math progress"}
            app.session_state["jp_round"] = {"sentinel": "jp progress"}
            app.button(key="cross_open").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.screen, "cross_report")
            app.button(key="cross_back").click().run()
            self.assertEqual(app.session_state.screen, "settings")
            app.button(key="subject_japanese").click().run()
            with patch("cross_subject_ui.load_records", side_effect=OSError("private_secret")):
                app.button(key="cross_open").click().run()
            self.assertEqual(len(app.error), 1)
            self.assertNotIn("private_secret", app.error[0].value)
            app.button(key="cross_reload").click().run()
            self.assertFalse(app.exception)
            app.button(key="cross_back").click().run()
            self.assertEqual(app.session_state.screen, "jp_settings")
            self.assertEqual(app.session_state.round, {"sentinel": "math progress"})
            self.assertEqual(app.session_state.jp_round, {"sentinel": "jp progress"})


if __name__ == "__main__":
    unittest.main()
