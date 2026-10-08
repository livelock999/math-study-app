"""3つの数の文章題の画面・独立集計・表示を、隔離DBで確認します。"""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest

import test_fill_visuals_ui as helpers
from activity import JST
from cross_subject import build_report
from learning import make_attempt, make_problem
from math_visuals import visual_model
from three_word import make_three_word_problem, STORIES
from words import make_word_problem
import canonical_text


class ThreeWordAppTests(unittest.TestCase):
    setUp = helpers.FillVisualAppTests.setUp
    save = helpers.FillVisualAppTests.save
    click = helpers.FillVisualAppTests.click
    click_label = helpers.FillVisualAppTests.click_label
    event = helpers.FillVisualAppTests.event
    rows = helpers.FillVisualAppTests.rows
    visual_checkbox = helpers.FillVisualAppTests.visual_checkbox

    def begin(self, parent=False):
        if parent:
            self.click("parent_test_start")
        self.click("select_user_001")
        next(r for r in self.app.radio if r.label == "もんだい").set_value("mix")
        next(r for r in self.app.radio if r.label == "かずの はんい").set_value(20)
        self.app.radio(key="problem_format").set_value("three_word_problem")
        self.app.radio(key="problem_count").set_value(5).run()
        self.click_label("れんしゅう スタート")
        self.assertEqual(self.app.session_state.round["phase"], "choose")
        self.assertEqual(len({p["story_type"] for p in self.app.session_state.round["problems"]}), 4)

    def solve(self, p, second=None, answer=None):
        second = second or p["second_operation"]
        self.event("choose_operation", selected_operation=p["operation"])
        self.assertEqual(self.app.session_state.round["phase"], "choose_second")
        self.event("choose_operation", selected_operation=second)
        self.assertEqual(self.app.session_state.round["phase"], "equation")
        self.event("submit_equation", selected_operation=p["operation"], selected_second_operation=second,
                   equation_left=p["left_operand"], equation_right=p["right_operand"], equation_third=p["third_operand"])
        self.assertEqual(self.app.session_state.round["phase"], "question")
        self.event("answer", p["correct_answer"] if answer is None else answer)
        self.event("next")

    def test_two_choices_three_numbers_result_retry_independent_report_and_history(self):
        self.begin()
        cases = [make_three_word_problem(story, 20, *values) for story, values in (
            ("increase_twice", (3, 2, 1)), ("decrease_twice", (15, 7, 3)),
            ("increase_then_decrease", (5, 4, 2)), ("decrease_then_increase", (13, 8, 9)),
            ("increase_then_decrease", (3, 2, 5)))]
        self.app.session_state.round["problems"] = cases
        self.app.run()
        for index, p in enumerate(cases):
            self.solve(p, second="subtraction" if index == 0 else None, answer=4 if index == 0 else None)
        self.assertEqual(self.app.metric[1].value, "80%")
        failed = next(r for r in self.rows() if not r["is_correct"])
        self.assertEqual((failed["operation_selection_correct"], failed["equation_correct"], failed["calculation_correct"]), (False, True, True))
        self.assertEqual(failed["user_equation"], "3 + 2 − 1")
        self.click_label("まちがえた もんだいを もういちど")
        self.solve(cases[0])
        self.assertEqual(self.app.metric[1].value, "100%")
        self.assertEqual(len(self.rows()), 6)
        self.click("report_results")
        self.assertTrue(any("3つの数の文章題の練習" in m.value for m in self.app.markdown))
        self.assertEqual([m.value for m in self.app.metric if m.label == "初回の回答"], ["0問"])
        self.click("report_back")
        self.click("history_results")
        self.assertEqual(set(self.app.dataframe[0].value["形式"]), {"3つの数の文章題"})

    def test_equation_pause_resume_edit_and_invalid_missing_third(self):
        self.begin()
        p = self.app.session_state.round["problems"][0]
        self.event("choose_operation", selected_operation=p["operation"])
        self.event("pause")
        self.click("math_resume")
        self.assertEqual(self.app.session_state.round["phase"], "choose_second")
        self.event("choose_operation", selected_operation=p["second_operation"])
        self.event("submit_equation", selected_operation=p["operation"], selected_second_operation=p["second_operation"],
                   equation_left=p["left_operand"], equation_right=p["right_operand"])
        self.assertEqual(self.app.session_state.round["phase"], "equation")
        self.event("show_hint", draft={"equation_left": "13", "equation_right": "8", "equation_third": "9",
                                       "selected_operation": "subtraction", "selected_second_operation": "addition"})
        self.event("pause")
        self.click("math_resume")
        draft = self.app.session_state.round["drafts"][0]
        self.assertEqual((draft["equation_third"], draft["selected_second_operation"], draft["hint_level"]), ("9", "addition", 1))
        self.event("submit_equation", selected_operation="subtraction", selected_second_operation="addition",
                   equation_left=13, equation_right=8, equation_third=9)
        self.event("edit_equation")
        self.assertEqual(self.app.session_state.round["phase"], "equation")
        self.assertEqual(self.app.session_state.round["user_equations"][0]["third"], 9)

    def test_parent_test_dont_know_at_both_choice_stages_is_unassessed(self):
        self.begin(parent=True)
        for index in range(5):
            if index % 2:
                self.event("choose_operation", selected_operation="addition")
            self.event("dont_know")
            record = self.app.session_state.round["answers"][-1]
            self.assertTrue(record["dont_know_used"])
            for field in ("operation_selection_correct", "equation_correct", "calculation_correct", "user_answer"):
                self.assertIsNone(record[field])
            self.event("next")
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.app.metric[1].value, "0%")

    def test_save_response_lost_retries_the_same_full_equation(self):
        self.begin()
        p = self.app.session_state.round["problems"][0]
        self.event("choose_operation", selected_operation=p["operation"])
        self.event("choose_operation", selected_operation=p["second_operation"])
        self.event("submit_equation", selected_operation=p["operation"], selected_second_operation=p["second_operation"],
                   equation_left=p["left_operand"], equation_right=p["right_operand"], equation_third=p["third_operand"])
        self.lost_response = True
        self.event("answer", p["correct_answer"])
        pending = deepcopy(self.app.session_state.round["pending_record"])
        self.click("retry_save")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual((self.rows()[0]["attempt_id"], self.rows()[0]["user_equation"]),
                         (pending["attempt_id"], pending["user_equation"]))


class ThreeWordDisplayTests(unittest.TestCase):
    def test_approved_templates_display_without_mutation_and_no_answer_revealing_picture(self):
        for story, template in STORIES.items():
            p = make_three_word_problem(story, 20, 5, 2, 1)
            before = deepcopy(p)
            self.assertEqual(template[2], canonical_text._THREE_WORD_STORIES[story])
            fields = canonical_text.canonical_fields("math", p)
            self.assertIn("question", fields)
            self.assertEqual(fields["hint_text"], {})
            self.assertEqual(fields["explanation_text"], {})
            self.assertIsNone(visual_model(p))
            self.assertEqual(p, before)
            for changed in ({"question_text": "はしが 5こ"}, {"second_operation": "division"},
                            {"third_operand": 0}, {"story_type": "unknown"}):
                self.assertEqual(canonical_text.canonical_fields("math", {**p, **changed}), {})

    def test_common_report_stage_scores_are_separate_from_old_words_and_calculations(self):
        now = datetime(2026, 10, 8, 12, tzinfo=JST)
        p = make_three_word_problem("increase_then_decrease", 10, 5, 4, 2)
        records = []
        for index in range(5):
            record = make_attempt(p, "user_001", str(index), 1, "normal", 3, 2, 1,
                                  selected_operation="subtraction", selected_second_operation="addition",
                                  equation_left=5, equation_right=4, equation_third=2)
            record["datetime"] = (now - timedelta(days=1)).isoformat()
            records.append(record)
        before = build_report([], [], "user_001", now=now)
        foreign = {**records[0], "attempt_id": "foreign", "user_id": "user_002"}
        future = {**records[0], "attempt_id": "future", "datetime": (now + timedelta(days=1)).isoformat()}
        report = build_report(records + [records[0], foreign, future], [], "user_001", now=now)
        self.assertEqual(before["groups"], report["groups"][:7])
        groups = {g["label"]: g for g in report["groups"][7:]}
        self.assertEqual(groups["算数：3つの数の文章題の全体正解"]["rate"], 0)
        self.assertEqual(groups["算数：3つの数の文章題の2回のたす・ひく選択"]["rate"], 0)
        self.assertEqual(groups["算数：3つの数の文章題の3つの数・順序"]["rate"], 1)
        self.assertEqual(groups["算数：3つの数の文章題の自分の式の計算"]["rate"], 1)
        self.assertTrue(any("3つの数の文章題を5問" in s for s in report["suggestions"]))


if __name__ == "__main__":
    unittest.main()
