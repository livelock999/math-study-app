"""逆思考の文章題：既存教材の保持、式の採点、復習と画面進行。"""

from datetime import datetime, timedelta
from pathlib import Path
import random
import tempfile
import unittest

import adaptive_difficulty
import canonical_text
import daily_review
import learning
import parent_insights
import school_scope
import test_learning
from words import INVERSE_STORIES, STORIES, guidance, make_word_problem, word_pool


class WordExpansionTests(unittest.TestCase):
    def test_existing_six_ids_text_and_tags_are_unchanged(self):
        snapshots = {
            "increase": ("addition", "result", 3, 2, "りんごが 3こ あります。2こ もらいました。いま なんこ ありますか。"),
            "decrease": ("subtraction", "result", 8, 2, "りんごが 8こ あります。2こ たべました。のこりは なんこ ですか。"),
            "combine": ("addition", "result", 3, 2, "あかい つみきが 3こ、あおい つみきが 2こ あります。あわせて なんこ ですか。"),
            "separate": ("subtraction", "result", 8, 2, "いぬと ねこが ぜんぶで 8ひき います。いぬは 2ひき です。ねこは なんびき ですか。"),
            "compare": ("subtraction", "difference", 8, 2, "りんごが 8こ、みかんが 2こ あります。りんごは みかんより なんこ おおいですか。"),
            "difference": ("subtraction", "difference", 8, 2, "こどもが 8にん います。いすは 2こ あります。ひとりに いすが 1こ ひつようです。いすは あと なんこ いりますか。"),
        }
        for story, (operation, unknown, left, right, text) in snapshots.items():
            problem = make_word_problem(story, 10, left, right)
            self.assertEqual(problem["question_text"], text)
            self.assertEqual(problem["problem_id"], f"word_v1_{story}_10_{left}_{right}")
            self.assertEqual((problem["operation"], problem["unknown_type"]), (operation, unknown))

    def test_inverse_unknowns_use_solving_operands_not_story_order(self):
        examples = {
            "increase_start": (13, 8, "subtraction", "start", 5, "はじめに"),
            "increase_change": (13, 8, "subtraction", "change", 5, "なんこ もらいましたか"),
            "decrease_start": (5, 8, "addition", "start", 13, "はじめに"),
            "decrease_change": (13, 8, "subtraction", "change", 5, "なんこ たべましたか"),
        }
        for story, (left, right, operation, unknown, answer, prompt) in examples.items():
            problem = make_word_problem(story, 20, left, right)
            self.assertEqual(problem["correct_answer"], answer)
            self.assertEqual((problem["operation"], problem["unknown_type"]), (operation, unknown))
            self.assertEqual(problem["problem_id"], f"word_v2_{story}_20_{left}_{right}")
            self.assertIn(prompt, problem["question_text"])
            record = learning.make_attempt(problem, "user_001", story, 1, "normal", answer, 2, 1,
                                           selected_operation=operation, equation_left=left, equation_right=right)
            self.assertTrue(record["is_correct"])
            self.assertTrue(record["equation_correct"])
            # 増える文章でも足し算を選ぶと、計算自体が合っていても総合は誤答。
            wrong_op = "addition" if operation == "subtraction" else "subtraction"
            wrong = learning.make_attempt(problem, "user_001", story + "bad", 1, "normal",
                                          left + right if wrong_op == "addition" else abs(left - right), 2, 1,
                                          selected_operation=wrong_op, equation_left=left, equation_right=right)
            self.assertFalse(wrong["operation_selection_correct"])
            self.assertFalse(wrong["is_correct"])
            if operation == "subtraction":
                reverse = learning.make_attempt(problem, "user_001", story + "reverse", 1, "normal", 0, 2, 1,
                                                selected_operation=operation, equation_left=right, equation_right=left)
                self.assertFalse(reverse["equation_correct"])

    def test_all_pools_preserve_range_carry_and_unique_story_text(self):
        self.assertEqual(len(STORIES), 10)
        for limit in (10, 20):
            for operation in ("addition", "subtraction"):
                for special in ("auto", "none", "with"):
                    pool = word_pool(operation, limit, special)
                    self.assertEqual(len(pool), len({q["problem_id"] for q in pool}))
                    self.assertEqual(len(pool), len({q["question_text"] for q in pool}))
                    for q in pool:
                        self.assertLessEqual(max(q["left_operand"], q["right_operand"], q["correct_answer"]), limit)
                        self.assertEqual(q["operation"], operation)
                        flag = q["carry"] if operation == "addition" else q["borrowing"]
                        if special != "auto":
                            self.assertEqual(flag, special == "with")
                    if pool:
                        self.assertTrue(set(q["story_type"] for q in pool) & INVERSE_STORIES)
        for story in INVERSE_STORIES - {"decrease_start"}:
            with self.assertRaises(ValueError):
                make_word_problem(story, 10, 4, 4)
        with self.assertRaises(ValueError):
            make_word_problem("decrease_start", 10, 6, 5)

    def test_inverse_hints_reveal_only_after_answer_and_remain_canonical(self):
        for story in sorted(INVERSE_STORIES):
            q = make_word_problem(story, 20, 5 if story == "decrease_start" else 13, 8)
            steps = parent_insights.math_hint_steps(q)
            self.assertEqual(steps[0], guidance(q))
            self.assertTrue(all("=" not in hint and str(q["correct_answer"]) not in hint for hint in steps))
            self.assertIn("たす" if q["operation"] == "addition" else "ひく", steps[-1])
            symbol = "+" if q["operation"] == "addition" else "−"
            self.assertIn(f"{q['left_operand']} {symbol} {q['right_operand']} = {q['correct_answer']}", guidance(q, True))
            fields = canonical_text.canonical_fields("math", q)
            self.assertIn("question", fields)
            self.assertIn("hint_text", fields)
            self.assertIn("explanation_text", fields)
            changed = dict(q, question_text=q["question_text"] + "改訂")
            self.assertEqual({}, canonical_text.canonical_fields("math", changed))

    def test_school_adaptive_and_review_keep_new_canonical_ids(self):
        now = datetime(2026, 10, 8, 12, tzinfo=daily_review.JST)
        q = make_word_problem("increase_start", 20, 13, 8)
        row = learning.make_attempt(q, "user_001", "due", 1, "normal", 0, 2, 1,
                                    selected_operation="subtraction", equation_left=13, equation_right=8)
        row["datetime"] = (now - timedelta(days=2)).isoformat()
        rows = [row]
        plan = daily_review.plan_math(rows, "user_001", limit=20, now=now)
        self.assertEqual(plan["items"][0]["problem_id"], q["problem_id"])
        scope = school_scope.validate("user_001", "addition_10", "current")
        pool = school_scope.review_pool(rows, "user_001", scope, "math", now)
        self.assertIn(q["problem_id"], {p["problem_id"] for p in pool})
        self.assertNotIn(q["problem_id"], {p["problem_id"] for p in school_scope.review_pool(rows, "user_002", school_scope.validate("user_002", "addition_10", "current"), "math", now)})
        automatic = school_scope.plan_math([], "user_001", school_scope.validate("user_001", "subtraction_20_with", "current"),
                                           problem_format="word_problem", now=now, rng=random.Random(2))
        self.assertTrue(all(p["operation"] == "subtraction" and p["number_range"] == 20 and p["borrowing"] for p in automatic["items"]))
        self.assertTrue(any(p["story_type"] in INVERSE_STORIES for p in automatic["items"]))

    def test_new_answer_persistence_is_idempotent_and_initial_review_stay_separate(self):
        from assessment import assess
        q = make_word_problem("decrease_start", 20, 5, 8)
        normal = learning.make_attempt(q, "user_001", "normal", 1, "normal", 13, 2, 1,
                                       selected_operation="addition", equation_left=8, equation_right=5)
        review = learning.make_attempt(q, "user_001", "review", 1, "review", 0, 2, 1,
                                       selected_operation="addition", equation_left=5, equation_right=8)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "math.sqlite3"
            learning.init_db(path)
            for row in (normal, normal, review, review):
                learning.save_attempt(row, path)
            rows, has_more = learning.read_attempts("user_001", path=path)
        self.assertFalse(has_more)
        self.assertEqual(len(rows), 2)
        self.assertTrue(next(r for r in rows if r["selection_type"] == "normal")["is_correct"])
        report = assess(rows)
        self.assertEqual(report["word_normal"]["count"], 1)
        self.assertEqual(report["word_review"]["count"], 1)


class WordExpansionUITests(unittest.TestCase):
    # 既存の隔離DB・イベント境界をそのまま使う。既存テスト自体は継承しない。
    setUp = test_learning.AppFlowTests.setUp
    click_label = test_learning.AppFlowTests.click_label
    start_words = test_learning.AppFlowTests.start_words
    event = test_learning.AppFlowTests.event
    rows = test_learning.AppFlowTests.rows

    def test_inverse_set_choose_equation_answer_result_and_retry(self):
        self.start_words()
        cases = [make_word_problem(story, 20, 5 if story == "decrease_start" else 13, 8)
                 for story in sorted(INVERSE_STORIES)]
        cases.append(make_word_problem("increase", 20, 5, 8))
        self.app.session_state.round["problems"] = cases
        self.app.run()
        for index, q in enumerate(cases):
            self.event("choose_operation", selected_operation=q["operation"])
            self.event("submit_equation", selected_operation=q["operation"],
                       equation_left=q["left_operand"], equation_right=q["right_operand"])
            self.event("answer", 0 if index == 1 else q["correct_answer"])
            self.event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(self.app.metric[1].value, "80%")
        self.assertEqual(len(self.rows()), 5)
        self.click_label("まちがえた もんだいを もういちど")
        self.assertEqual(self.app.session_state.round["problems"][0]["problem_id"], cases[1]["problem_id"])
        q = cases[1]
        self.event("choose_operation", selected_operation=q["operation"])
        self.event("submit_equation", selected_operation=q["operation"],
                   equation_left=q["left_operand"], equation_right=q["right_operand"])
        self.event("answer", q["correct_answer"])
        self.event("next")
        self.assertEqual(self.app.metric[1].value, "100%")
        self.assertEqual(self.rows()[-1]["selection_type"], "retry")
        self.assertEqual(self.rows()[-1]["problem_id"], q["problem_id"])


if __name__ == "__main__":
    unittest.main()
