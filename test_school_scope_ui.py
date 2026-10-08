"""学校設定の画面保存・おまかせ・保護者テストを実進行で検証。"""
import unittest
from unittest.mock import patch

import school_scope as school
import test_daily_review_ui as review_test


class SchoolScopeUIAppTests(unittest.TestCase):
    def setUp(self):
        review_test.DailyReviewAppTests.setUp(self)
        self.scope_path = self.math_path.with_name("school.sqlite3")
        setting = patch("learning_extensions.DB_PATH", self.scope_path)
        setting.start()
        self.addCleanup(setting.stop)

    math_save = review_test.DailyReviewAppTests.math_save
    jp_save = review_test.DailyReviewAppTests.jp_save
    math_rows = review_test.DailyReviewAppTests.math_rows
    jp_rows = review_test.DailyReviewAppTests.jp_rows
    click = review_test.DailyReviewAppTests.click
    click_label = review_test.DailyReviewAppTests.click_label
    math_event = review_test.DailyReviewAppTests.math_event
    jp_event = review_test.DailyReviewAppTests.jp_event

    def choose(self, math="subtraction_20_with", japanese="particles_2"):
        user = self.app.session_state.user_id
        self.app.selectbox(key=f"school_scope_math_{user}").set_value(math)
        self.app.selectbox(key=f"school_scope_japanese_{user}").set_value(japanese)

    def test_save_applies_to_adaptive_manual_independent_and_other_child(self):
        self.click("select_user_001")
        self.click("school_scope_open")
        self.choose()
        self.click_label("学校の範囲を保存")
        self.assertEqual(school.read_scope("user_001")["math_unit"], "subtraction_20_with")
        self.assertEqual(school.read_scope("user_002"), school.default_scope("user_002"))
        self.click("school_scope_back")
        self.click("math_adaptive_start")
        state = self.app.session_state.round
        self.assertTrue(all(q["number_range"] == 20 and q["operation"] == "subtraction" and q["borrowing"] for q in state["problems"]))
        self.assertIn("scope_label", state["difficulty_plan"])
        self.math_event("pause")
        self.click_label("れんしゅう スタート")
        self.assertTrue(all(q["number_range"] == 10 and q["operation"] == "addition" for q in self.app.session_state.round["problems"]))
        self.app.session_state.screen = "jp_settings"
        self.app.run()
        self.click("jp_adaptive_start")
        self.assertTrue(all(q["category"] == "particles" and q["level"] <= 2 for q in self.app.session_state.jp_round["questions"]))

    def test_test_preview_changes_practice_not_saved_and_exit_restores(self):
        school.save_scope("user_001", "addition_10", "words")
        self.click("parent_test_start")
        self.click("select_user_001")
        self.click("school_scope_open")
        self.choose()
        self.click_label("保存せずに範囲を試す")
        self.assertEqual(school.read_scope("user_001")["math_unit"], "addition_10")
        self.click("school_scope_back")
        self.click("math_adaptive_start")
        self.assertTrue(all(q["operation"] == "subtraction" for q in self.app.session_state.round["problems"]))
        self.math_event("dont_know")
        self.assertEqual(len(self.math_rows()), 5)
        self.click("parent_test_end")
        self.assertFalse(any(k.startswith("school_scope_") for k in self.app.session_state))
        self.click("select_user_001")
        self.click("math_adaptive_start")
        self.assertTrue(all(q["operation"] == "addition" for q in self.app.session_state.round["problems"]))

    def test_saved_lost_response_retry_keeps_same_settings(self):
        self.click("select_user_001")
        self.click("school_scope_open")
        self.choose("mix_20", "words")
        original = school.save_scope
        deliveries = []
        def save(**kwargs):
            deliveries.append(dict(kwargs))
            result = original(**kwargs)
            if len(deliveries) == 1:
                raise OSError("response lost")
            return result
        with patch("school_scope.save_scope", side_effect=save):
            self.click_label("学校の範囲を保存")
            self.assertTrue(self.app.error)
            self.assertTrue(self.app.selectbox(key="school_scope_math_user_001").disabled)
            self.click("school_scope_retry")
        self.assertEqual(deliveries[0], deliveries[1])
        self.assertEqual(school.read_scope("user_001")["japanese_unit"], "words")
        self.assertEqual(len(self.math_rows()), 5)

    def test_read_failure_stops_adaptive_review_and_can_retry(self):
        self.click("select_user_001")
        with patch("school_scope.read_scope", side_effect=OSError("offline")):
            self.click("school_scope_open")
            self.assertTrue(self.app.error)
            self.assertFalse(self.app.selectbox)
        self.click("school_scope_reload")
        self.choose("addition_10", "words")
        self.click_label("学校の範囲を保存")
        self.click("school_scope_back")
        with patch("school_scope.read_scope", side_effect=OSError("offline")):
            self.click("math_adaptive_start")
            self.assertEqual(self.app.session_state.screen, "settings")
            self.click("math_daily_review")
            self.assertEqual(self.app.session_state.screen, "settings")
            self.click_label("れんしゅう スタート")
            self.assertEqual(self.app.session_state.screen, "practice")
        self.app.session_state.screen = "jp_settings"
        self.app.run()
        with patch("school_scope.read_scope", side_effect=OSError("offline")):
            self.click("jp_adaptive_start")
            self.assertEqual(self.app.session_state.screen, "jp_settings")
            self.click("jp_daily_review")
            self.assertEqual(self.app.session_state.screen, "jp_settings")
        self.click("jp_adaptive_start")
        self.assertEqual(self.app.session_state.screen, "jp_practice")

    def test_review_and_forecast_retain_previous_unit(self):
        school.save_scope("user_001", "addition_20_none", "words")
        self.click("select_user_001")
        self.click("math_review_forecast")
        self.assertTrue(any("きょう：5問" in e.value for e in self.app.markdown))
        self.click("math_daily_review")
        self.assertTrue(all(q["operation"] == "subtraction" and q["number_range"] == 10 for q in self.app.session_state.round["problems"]))
        self.math_event("pause")
        self.click("subject_japanese")
        self.click("jp_review_forecast")
        self.assertTrue(any("きょう：5問" in e.value for e in self.app.markdown))
        self.click("jp_daily_review")
        self.assertTrue(all(q["category"] == "sentence" for q in self.app.session_state.jp_round["questions"]))


if __name__ == "__main__":
    unittest.main()
