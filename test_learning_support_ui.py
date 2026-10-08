"""段階ヒント・わからない・類題・問題報告の実画面進行を確認します。"""

from pathlib import Path
import unittest
from unittest.mock import patch

import learning
import japanese as jp
import learning_extensions as extensions
import test_daily_review_ui as review_test


class LearningSupportUIAppTests(unittest.TestCase):
    # 同じ隔離DBと実際のアプリ進行を使用し、既存テスト自体は継承しません。
    setUp = review_test.DailyReviewAppTests.setUp
    math_save = review_test.DailyReviewAppTests.math_save
    jp_save = review_test.DailyReviewAppTests.jp_save
    math_rows = review_test.DailyReviewAppTests.math_rows
    jp_rows = review_test.DailyReviewAppTests.jp_rows
    click = review_test.DailyReviewAppTests.click
    click_label = review_test.DailyReviewAppTests.click_label
    math_event = review_test.DailyReviewAppTests.math_event
    jp_event = review_test.DailyReviewAppTests.jp_event

    def test_math_hint_levels_survive_pause_and_unknown_is_a_distinct_answer(self):
        self.click("select_user_001")
        self.click("math_daily_review")
        for expected in (1, 2):
            self.math_event("show_hint", draft={"answer": "4"})
            self.assertEqual(self.app.session_state.round["drafts"][0]["hint_level"], expected)
        self.math_event("pause", draft={"answer": "4"})
        self.click("math_resume")
        self.assertEqual(self.app.session_state.round["drafts"][0]["hint_level"], 2)
        self.assertEqual(self.app.session_state.round["drafts"][0]["answer"], "4")
        self.math_event("show_hint")
        self.math_event("show_hint")  # UI上限に加え、古いイベントも3を超えない。
        p = self.app.session_state.round["problems"][0]
        self.math_event("answer", p["correct_answer"])
        first = self.app.session_state.round["answers"][0]
        self.assertTrue(first["is_correct"])
        self.assertTrue(first["hint_used"])
        self.assertEqual(first["hint_level"], 3)
        self.math_event("next")
        self.math_event("dont_know")
        unknown = self.app.session_state.round["answers"][-1]
        self.assertIsNone(unknown["user_answer"])
        self.assertTrue(unknown["dont_know_used"])
        self.assertFalse(unknown["is_correct"])
        self.assertFalse(unknown["hint_used"])
        self.assertEqual(unknown["hint_level"], 0)
        self.assertEqual(len(self.math_rows()), 7)
        self.math_event("open_history")
        self.assertIn("わからない", self.app.dataframe[0].value["自分の回答"].tolist())

    def test_math_word_unknown_before_an_equation_can_finish_and_retry(self):
        self.click("select_user_001")
        self.app.radio(key="problem_format").set_value("word_problem").run()
        self.click_label("れんしゅう スタート")
        self.app.session_state.round["problems"] = self.app.session_state.round["problems"][:1]
        self.app.run()
        self.assertEqual(self.app.session_state.round["phase"], "choose")
        self.math_event("dont_know")
        record = self.app.session_state.round["answers"][0]
        self.assertTrue(record["dont_know_used"])
        self.assertIsNone(record["operation_selection_correct"])
        self.assertIsNone(record["calculation_correct"])
        self.math_event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(self.app.metric[1].value, "0%")
        self.click_label("まちがえた もんだいを もういちど")
        p = self.app.session_state.round["problems"][0]
        self.math_event("choose_operation", selected_operation=p["operation"])
        self.math_event("submit_equation", selected_operation=p["operation"],
                        equation_left=p["left_operand"], equation_right=p["right_operand"])
        self.math_event("answer", p["correct_answer"])
        retry = self.app.session_state.round["answers"][0]
        self.assertFalse(retry["dont_know_used"])
        self.assertTrue(retry["is_correct"])
        self.assertEqual(retry["attempt_count"], 2)

    def test_japanese_hint_pause_unknown_and_retry_keep_chain(self):
        self.click("select_user_001")
        self.click("subject_japanese")
        self.click("jp_daily_review")
        self.jp_event("back", hint_used=True, hint_level=2, draft_order=[])
        self.click("jp_resume")
        self.assertEqual(self.app.session_state.jp_round["draft"]["hint_level"], 2)
        self.jp_event("dont_know", hint_used=True, hint_level=3)
        record = self.app.session_state.jp_round["answers"][0]
        self.assertTrue(record["dont_know_used"])
        self.assertIsNone(record["selected_answer"])
        self.assertEqual(record["selected_answer_text"], "わからない")
        self.assertEqual(record["error_cause_tags"], [])
        self.assertTrue(record["hint_used"])
        self.assertEqual(record["hint_level"], 3)
        for _ in range(4):
            self.jp_event("next")
            q = self.app.session_state.jp_round["questions"][self.app.session_state.jp_round["index"]]
            self.jp_event("answer", q["answer"])
        self.jp_event("next")
        self.assertEqual(self.app.session_state.screen, "jp_results")
        self.click("jp_retry")
        q = self.app.session_state.jp_round["questions"][0]
        self.jp_event("answer", q["answer"])
        retry = self.app.session_state.jp_round["answers"][0]
        self.assertEqual(retry["chain_id"], record["chain_id"])
        self.assertEqual(retry["attempt_count"], 2)
        self.assertFalse(retry["dont_know_used"])
        self.assertEqual(retry["hint_level"], 0)

    def test_unknown_lost_response_retry_keeps_the_same_answer_id(self):
        self.click("select_user_001")
        self.click("math_daily_review")
        self.math_lost_response = True
        self.math_event("dont_know")
        pending = self.app.session_state.round["pending_record"]
        self.assertTrue(pending["dont_know_used"])
        self.assertEqual(len(self.math_rows()), 6)
        self.click("retry_save")
        self.assertEqual(self.app.session_state.round["answers"][0]["attempt_id"], pending["attempt_id"])
        self.assertEqual(len(self.math_rows()), 6)
        self.app.session_state.screen = "jp_settings"
        self.app.run()
        self.click("jp_daily_review")
        self.jp_lost_response = True
        self.jp_event("dont_know", hint_used=True, hint_level=2)
        pending = self.app.session_state.jp_round["pending"]
        self.click("jp_retry_save")
        self.assertEqual(self.app.session_state.jp_round["answers"][0]["attempt_id"], pending["attempt_id"])
        self.assertEqual(len(self.jp_rows()), 6)

    def test_parent_test_unknown_hints_and_reports_never_persist(self):
        extension_path = Path(self.temp.name) / "extensions.sqlite3"
        with patch("learning_extensions.DB_PATH", extension_path):
            self.click("parent_test_start")
            self.click("select_user_001")
            self.click("math_daily_review")
            state = self.app.session_state.round
            key = f"math_feedback_save_{state['session_id']}_0"
            self.click(key)
            self.math_event("show_hint")
            self.math_event("dont_know")
            self.assertEqual(len(self.math_rows()), 5)
            self.app.session_state.screen = "jp_settings"
            self.app.run()
            self.click("jp_daily_review")
            state = self.app.session_state.jp_round
            self.click(f"jp_feedback_save_{state['session_id']}_0")
            self.jp_event("dont_know", hint_used=True, hint_level=3)
            self.assertEqual(len(self.jp_rows()), 5)
            self.assertFalse(extension_path.exists())

    def test_feedback_saved_then_response_lost_retries_one_id_and_payload(self):
        path = Path(self.temp.name) / "extensions.sqlite3"
        save = extensions.save_feedback
        deliveries = []

        def lost_response(record, test_mode=False):
            deliveries.append(dict(record))
            save(record, path=path, test_mode=test_mode)
            if len(deliveries) == 1:
                raise OSError("保存後に応答が失われた")

        with patch("learning_extensions.save_feedback", side_effect=lost_response):
            self.click("select_user_001")
            self.click("math_daily_review")
            state = self.app.session_state.round
            self.app.selectbox(key=f"math_feedback_reason_{state['session_id']}_0").set_value("reading").run()
            button = f"math_feedback_save_{state['session_id']}_0"
            self.click(button)
            self.assertFalse(state["problem_feedback"][0].get("saved"))
            self.click(button)
            self.assertEqual(deliveries[0], deliveries[1])
            self.assertEqual(deliveries[0]["problem_id"], state["problems"][0]["problem_id"])
            rows = extensions.read_feedback("user_001", path=path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["reason"], "reading")
            self.assertEqual(extensions.read_feedback("user_002", path=path), [])

    def test_similar_buttons_respect_subject_setting_and_use_normal_analysis_type(self):
        self.click("select_user_001")
        self.app.radio[1].set_value(20).run()
        p = learning.make_problem("addition", 20, 12, 1)
        # AppTestはapp.pyを__main__として読み込むため、定義元をパッチします。
        with patch("parent_insights.adaptive_math", return_value={"items": [p], "reasons": {}, "message": ""}) as select:
            self.click("math_similar")
            self.assertEqual(select.call_args.kwargs, {"limit": 20, "count": 5})
            self.assertEqual(self.app.session_state.round["selection_type"], "weak_area")
            self.assertEqual(self.app.session_state.round["problems"][0]["problem_id"], p["problem_id"])
        self.app.session_state.screen = "jp_settings"
        self.app.run()
        self.app.radio(key="jp_category").set_value("particles").run()
        self.app.radio(key="jp_particle_level").set_value(1).run()
        q = next(q for q in jp.QUESTIONS if q["category"] == "particles" and q["level"] == 1)
        with patch("japanese_ui.adaptive_japanese", return_value={"items": [q], "reasons": {}, "message": ""}) as select:
            self.click("jp_similar")
            self.assertEqual(select.call_args.kwargs, {"particle_level": 1, "count": 5})
            self.assertEqual(self.app.session_state.jp_round["selection"], "weak_area")

    def test_forecast_does_not_write_answers_and_dashboard_opens(self):
        self.click("select_user_001")
        self.click("math_review_forecast")
        self.assertTrue(any("きょう：5問" in item.value for item in self.app.markdown))
        self.assertEqual(len(self.math_rows()), 5)
        self.click("subject_japanese")
        self.click("jp_review_forecast")
        self.assertTrue(any("きょう：5問" in item.value for item in self.app.markdown))
        with patch("parent_features_ui.render_dashboard") as dashboard:
            self.click("parent_dashboard_open")
            dashboard.assert_called_once()
            self.assertEqual(self.app.session_state.parent_dashboard_return, "jp_settings")
        self.assertEqual(len(self.jp_rows()), 5)

    def test_invalid_hint_stage_does_not_save_a_japanese_answer(self):
        self.click("select_user_001")
        self.click("subject_japanese")
        self.click("jp_daily_review")
        self.jp_event("dont_know", hint_used=True, hint_level=4)
        self.assertEqual(len(self.jp_rows()), 5)
        self.assertEqual(self.app.session_state.jp_round["phase"], "question")


if __name__ == "__main__":
    unittest.main()
