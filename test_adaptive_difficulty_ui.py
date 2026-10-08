"""おまかせの実画面進行と、保存・中断・保護者テストの契約。"""
from copy import deepcopy
import unittest
from unittest.mock import patch

import test_daily_review_ui as review_test


class AdaptiveDifficultyUIAppTests(unittest.TestCase):
    setUp = review_test.DailyReviewAppTests.setUp
    math_save = review_test.DailyReviewAppTests.math_save
    jp_save = review_test.DailyReviewAppTests.jp_save
    math_rows = review_test.DailyReviewAppTests.math_rows
    jp_rows = review_test.DailyReviewAppTests.jp_rows
    click = review_test.DailyReviewAppTests.click
    click_label = review_test.DailyReviewAppTests.click_label
    math_event = review_test.DailyReviewAppTests.math_event
    jp_event = review_test.DailyReviewAppTests.jp_event

    def test_math_five_answers_pause_retry_save_then_next_set(self):
        self.click("select_user_001")
        self.app.radio(key="problem_count").set_value(5).run()
        self.click("math_adaptive_start")
        state = self.app.session_state.round
        plan = deepcopy(state["difficulty_plan"])
        self.assertEqual(state["selection_type"], "normal")
        self.assertEqual(len(state["problems"]), 5)
        self.math_event("pause", draft={"answer": "2"})
        self.click("math_resume")
        self.assertEqual(self.app.session_state.round["difficulty_plan"], plan)
        self.math_lost_response = True
        first = state["problems"][0]
        self.math_event("answer", first["correct_answer"])
        pending = self.app.session_state.round["pending_record"]
        self.click("retry_save")
        self.assertEqual(self.app.session_state.round["answers"][0]["attempt_id"], pending["attempt_id"])
        self.assertEqual(self.app.session_state.round["difficulty_plan"], plan)
        self.math_event("next")
        for i in range(1, 5):
            self.math_event("answer", self.app.session_state.round["problems"][i]["correct_answer"])
            self.math_event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(self.app.metric[1].value, "100%")
        self.assertEqual(len(self.math_rows()), 10)
        self.click("new_practice")
        self.click("math_adaptive_start")
        self.assertEqual(self.app.session_state.round["difficulty_plan"]["decisions"]["addition"]["level"], 2)

    def test_japanese_five_answers_pause_retry_and_next_set(self):
        self.click("select_user_001")
        self.click("subject_japanese")
        self.app.radio(key="jp_category").set_value("particles").run()
        self.app.radio(key="jp_count").set_value(5).run()
        self.click("jp_adaptive_start")
        state = self.app.session_state.jp_round
        plan = deepcopy(state["difficulty_plan"])
        self.jp_event("back")
        self.click("jp_resume")
        self.assertEqual(self.app.session_state.jp_round["difficulty_plan"], plan)
        self.jp_lost_response = True
        self.jp_event("answer", state["questions"][0]["answer"])
        pending = self.app.session_state.jp_round["pending"]
        self.click("jp_retry_save")
        self.assertEqual(self.app.session_state.jp_round["answers"][0]["attempt_id"], pending["attempt_id"])
        self.jp_event("next")
        for i in range(1, 5):
            self.jp_event("answer", self.app.session_state.jp_round["questions"][i]["answer"])
            self.jp_event("next")
        self.assertEqual(self.app.session_state.screen, "jp_results")
        self.assertEqual(self.app.metric[1].value, "100%")
        self.assertEqual(len(self.jp_rows()), 10)
        self.click("jp_new")
        self.click("jp_adaptive_start")
        self.assertEqual(self.app.session_state.jp_round["difficulty_plan"]["decisions"]["particles"]["level"], 2)

    def test_parent_test_cannot_advance_or_persist_either_subject(self):
        self.click("parent_test_start")
        self.click("select_user_001")
        self.app.radio(key="problem_count").set_value(5).run()
        self.click("math_adaptive_start")
        for i in range(5):
            self.math_event("answer", self.app.session_state.round["problems"][i]["correct_answer"])
            self.math_event("next")
        self.click("new_practice")
        self.click("math_adaptive_start")
        self.assertEqual(self.app.session_state.round["difficulty_plan"]["decisions"]["addition"]["level"], 1)
        self.assertEqual(len(self.math_rows()), 5)
        self.app.session_state.screen = "jp_settings"
        self.app.run()
        self.app.radio(key="jp_category").set_value("particles").run()
        self.app.radio(key="jp_count").set_value(5).run()
        self.click("jp_adaptive_start")
        for i in range(5):
            self.jp_event("answer", self.app.session_state.jp_round["questions"][i]["answer"])
            self.jp_event("next")
        self.click("jp_new")
        self.click("jp_adaptive_start")
        self.assertEqual(self.app.session_state.jp_round["difficulty_plan"]["decisions"]["particles"]["level"], 1)
        self.assertEqual(len(self.jp_rows()), 5)
        self.click("parent_test_end")
        self.assertNotIn("round", self.app.session_state)
        self.assertNotIn("jp_round", self.app.session_state)

    def test_loading_failure_stops_start_and_can_retry(self):
        self.click("select_user_001")
        with patch("learning.read_attempts", side_effect=OSError("offline")):
            self.click("math_adaptive_start")
            self.assertEqual(self.app.session_state.screen, "settings")
            self.assertTrue(self.app.error)
        self.click("math_adaptive_start")
        self.assertEqual(self.app.session_state.screen, "practice")
        self.app.session_state.screen = "jp_settings"
        self.app.run()
        with patch("japanese.read_all", side_effect=OSError("offline")):
            self.click("jp_adaptive_start")
            self.assertEqual(self.app.session_state.screen, "jp_settings")
            self.assertTrue(self.app.error)
        self.click("jp_adaptive_start")
        self.assertEqual(self.app.session_state.screen, "jp_practice")


if __name__ == "__main__":
    unittest.main()
