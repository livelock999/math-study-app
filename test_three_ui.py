"""3つの数の画面進行・図・独立集計・保護者テストを確認します。"""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest

import test_fill_visuals_ui as helpers
from activity import JST
from cross_subject import build_report
from fill_blank import make_fill_problem
from learning import make_attempt
from math_visuals import visual_model
from three_numbers import make_three_problem
import canonical_text


class ThreeAppTests(unittest.TestCase):
    setUp = helpers.FillVisualAppTests.setUp
    save = helpers.FillVisualAppTests.save
    click = helpers.FillVisualAppTests.click
    click_label = helpers.FillVisualAppTests.click_label
    event = helpers.FillVisualAppTests.event
    rows = helpers.FillVisualAppTests.rows
    visual_checkbox = helpers.FillVisualAppTests.visual_checkbox

    def begin(self, mode="mix", limit=20, visual=False, parent=False, special="auto"):
        if parent:
            self.click("parent_test_start")
        self.click("select_user_001")
        next(r for r in self.app.radio if r.label == "もんだい").set_value(mode)
        next(r for r in self.app.radio if r.label == "かずの はんい").set_value(limit)
        self.app.radio(key="problem_format").set_value("three_numbers")
        self.app.radio(key="problem_count").set_value(5)
        self.app.radio(key="special_mode").set_value(special)
        self.visual_checkbox().set_value(visual).run()
        self.click_label("れんしゅう スタート")
        self.assertEqual(len(self.app.session_state.round["problems"]), 5)

    def test_mixed_start_pause_hint_result_retry_history_and_report(self):
        self.begin()
        problems = self.app.session_state.round["problems"]
        self.assertEqual(len({(p["operation"], p["second_operation"]) for p in problems}), 4)
        self.event("show_visual", draft={"answer": "3"})
        self.event("show_hint")
        self.event("pause")
        self.click("math_resume")
        draft = self.app.session_state.round["drafts"][0]
        self.assertEqual((draft["answer"], draft["hint_level"], draft["visual_visible"]), ("3", 1, True))
        for index in range(5):
            p = self.app.session_state.round["problems"][index]
            self.event("answer", p["correct_answer"] + (index == 0))
            self.event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(self.app.metric[1].value, "80%")
        self.assertEqual(len(self.rows()), 5)
        self.assertTrue(all(r["third_operand"] is not None and r["second_operation"] for r in self.rows()))
        self.click_label("まちがえた もんだいを もういちど")
        p = self.app.session_state.round["problems"][0]
        self.event("answer", p["correct_answer"])
        record = deepcopy(self.app.session_state.round["answers"][0])
        self.event("show_visual")
        self.assertEqual(record, self.app.session_state.round["answers"][0])
        self.event("next")
        self.assertEqual(self.app.metric[1].value, "100%")
        self.click("report_results")
        self.assertTrue(any("3つの数の練習" in m.value for m in self.app.markdown))
        self.assertEqual([m.value for m in self.app.metric if m.label == "初回の回答"], ["0問"])
        self.click("report_back")
        self.click("history_results")
        self.assertEqual(set(self.app.dataframe[0].value["形式"]), {"3つの数"})

    def test_parent_three_visual_hints_do_not_persist(self):
        self.begin(visual=True, parent=True)
        for index in range(5):
            p = self.app.session_state.round["problems"][index]
            self.event("show_hint")
            self.event("answer", p["correct_answer"])
            self.assertTrue(self.app.session_state.round["answers"][-1]["visual_help_used"])
            self.event("next")
        self.assertEqual(self.rows(), [])
        self.click("parent_test_end")
        self.click("select_user_001")
        self.assertFalse(self.visual_checkbox().value)

    def test_subtraction_special_and_save_retry(self):
        self.begin(mode="subtraction", special="with")
        self.assertTrue(all(p["operation"] == p["second_operation"] == "subtraction" and p["borrowing"]
                            for p in self.app.session_state.round["problems"]))
        self.lost_response = True
        p = self.app.session_state.round["problems"][0]
        self.event("answer", p["correct_answer"])
        identifier = self.app.session_state.round["pending_record"]["attempt_id"]
        self.click("retry_save")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["attempt_id"], identifier)


class ThreeDisplayTests(unittest.TestCase):
    def test_four_visual_sequences_hide_only_final_answer_and_do_not_mutate_problem(self):
        for first, second, values in (("addition", "addition", (2, 3, 4)),
                                      ("subtraction", "subtraction", (9, 2, 3)),
                                      ("addition", "subtraction", (5, 4, 2)),
                                      ("subtraction", "addition", (9, 3, 2))):
            p = make_three_problem(first, second, 10, *values)
            before = deepcopy(p)
            hidden, shown = visual_model(p), visual_model(p, True)
            self.assertEqual([r["count"] for r in hidden["rows"]], [*values, None])
            self.assertEqual([r["count"] for r in shown["rows"]], [*values, p["correct_answer"]])
            self.assertEqual([r["tone"] for r in hidden["rows"]],
                             ["start", "add" if first == "addition" else "remove",
                              "add" if second == "addition" else "remove", "result"])
            self.assertEqual(before, p)
            fields = canonical_text.canonical_fields("math", p)
            self.assertEqual(fields, {"question": {}, "question_text": {}, "hint_text": {}, "explanation_text": {}})
            for change in ({"third_operand": 21}, {"second_operation": "division"},
                           {"correct_answer": 99}, {"question_text": "はし"}):
                altered = {**p, **change}
                self.assertEqual(canonical_text.canonical_fields("math", altered), {})
                if "question_text" not in change:
                    with self.assertRaises(ValueError):
                        visual_model(altered)

    def test_common_report_keeps_three_and_fill_suggestions_independent(self):
        now = datetime(2026, 10, 8, 12, tzinfo=JST)
        three = make_three_problem("addition", "subtraction", 10, 5, 4, 2)
        fill = make_fill_problem("addition", 10, 5, 3, "left_operand")
        records = []
        for index in range(5):
            for p, correct in ((three, False), (fill, True)):
                r = make_attempt(p, "user_001", str(index), 1, "normal", p["correct_answer"] if correct else 99,
                                 2, 1, visual_help_used=True)
                r["datetime"] = (now - timedelta(days=1)).isoformat()
                records.append(r)
        review = make_attempt(three, "user_001", "review", 1, "review", three["correct_answer"], 2, 1)
        review["datetime"] = now.isoformat()
        foreign = {**records[0], "attempt_id": "foreign", "user_id": "user_002"}
        future = {**records[0], "attempt_id": "future", "datetime": (now + timedelta(days=1)).isoformat()}
        report = build_report(records + [review, records[0], foreign, future], [], "user_001", now=now)
        self.assertEqual(report["groups"][0]["count"], 0)
        group = next(g for g in report["groups"] if g["label"] == "算数：3つの数")
        self.assertEqual((group["count"], group["visual_used_count"], group["rate"]), (5, 5, 0))
        self.assertTrue(any("3つの数を5問" in s for s in report["suggestions"]))
        self.assertFalse(any("□に入る数を5問" in s for s in report["suggestions"]))
        self.assertEqual(report["subjects"]["math"]["review"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
