"""追加読解教材の本文根拠・既存教材不変・既存学習経路を検証する。"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import random
import re
import unittest

import adaptive_difficulty
import canonical_text
import daily_review
import japanese as jp
import test_japanese as existing_tests
from japanese_questions import QUESTIONS, TAG_LABELS
from parent_insights import japanese_hint_steps
from reading_materials import QUESTIONS as READING_QUESTIONS, build_questions

NOW = datetime(2026, 10, 8, 12, tzinfo=jp.JST)


def record(question, day=7, selection="normal", answer=None, chain="reading"):
    row = jp.make_record(question, "user_001", "reading", 1, selection,
                         question["answer"] if answer is None else answer, 3, 1, chain)
    row["datetime"] = NOW.replace(day=day).isoformat()
    return row


class ReadingMaterialsTests(unittest.TestCase):
    def test_original_120_questions_are_byte_for_byte_unchanged(self):
        original = json.dumps(QUESTIONS[:120], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(sha256(original.encode()).hexdigest(),
                         "abf58a94f357343be8483fab8116cfe104894435b3913b4e0420cbe1625d9c70")
        self.assertEqual(QUESTIONS[120:], READING_QUESTIONS)

    def test_balanced_kinds_levels_and_distinct_valid_choices(self):
        self.assertEqual(len(READING_QUESTIONS), 16)
        self.assertEqual(len({q["question_id"] for q in QUESTIONS}), len(QUESTIONS))
        self.assertEqual(Counter(q["question_word"] for q in READING_QUESTIONS), {"why": 8, "how": 8})
        self.assertEqual(Counter(q["difficulty"] for q in READING_QUESTIONS), {1: 4, 2: 8, 3: 4})
        self.assertEqual(Counter(q["answer"] for q in READING_QUESTIONS), {0: 6, 1: 5, 2: 5})
        for q in READING_QUESTIONS:
            with self.subTest(question=q["question_id"]):
                self.assertEqual(q["category"], "passage")
                self.assertEqual(len(set(q["choices"])), 3)
                self.assertTrue(jp.validate_answer(q, q["answer"]))
                self.assertTrue(set(q["skill_tags"]).issubset(TAG_LABELS))
                self.assertNotIn(q["choices"][q["answer"]], q["hint"])
                for wrong in range(3):
                    if wrong != q["answer"]:
                        self.assertTrue(q["error_tags"][str(wrong)])

    def test_every_explanation_quotes_the_exact_numbered_sentence(self):
        for q in READING_QUESTIONS:
            with self.subTest(question=q["question_id"]):
                evidence = re.match(r"てがかりは ([12])ぶんめの『([^』]+)』", q["explanation"])
                self.assertIsNotNone(evidence)
                self.assertEqual(evidence[2], q["text"].split("\n")[int(evidence[1]) - 1])
                self.assertIn(q["choices"][q["answer"]], q["explanation"])
                self.assertEqual(len(japanese_hint_steps(q)), 3)
                self.assertNotIn(evidence[2], japanese_hint_steps(q))
        rebuilt = build_questions()
        rebuilt[0]["choices"].clear()
        self.assertEqual(len(READING_QUESTIONS[0]["choices"]), 3)

    def test_new_texts_are_reviewed_but_modified_copy_is_not_approved(self):
        for q in READING_QUESTIONS:
            with self.subTest(question=q["question_id"]):
                self.assertIn(q["question_id"], canonical_text._japanese_catalog())
                self.assertIn("explanation", canonical_text.canonical_fields("japanese", q))
                changed = deepcopy(q)
                changed["explanation"] += "これは かいへんです。"
                self.assertEqual(canonical_text.canonical_fields("japanese", changed), {})

    def test_manual_selection_and_adaptive_level_three_use_same_catalog(self):
        pool = [q for q in QUESTIONS if q["category"] == "passage"]
        with patch("japanese.random.sample", side_effect=lambda candidates, size: candidates[-size:]):
            chosen = jp.choose_questions("passage", 10)
        self.assertTrue(all(q in READING_QUESTIONS for q in chosen))
        first = [q for q in pool if q["difficulty"] == 1][:5]
        second = [q for q in pool if q["difficulty"] == 2][:5]
        rows = [record(q, day=1, chain=f"first{i}") for i, q in enumerate(first)]
        rows += [record(q, day=4, chain=f"second{i}") for i, q in enumerate(second)]
        plan = adaptive_difficulty.plan_japanese(rows, "user_001", "passage", 5, now=NOW, rng=random.Random(1))
        self.assertEqual(plan["decisions"]["passage"]["level"], 3)
        self.assertEqual(sum(q["difficulty"] == 3 for q in plan["items"]), 4)
        self.assertEqual(len({q["question_id"] for q in plan["items"]}), 5)

    def test_new_problem_review_and_tag_analysis_keep_initial_record_meaning(self):
        q = READING_QUESTIONS[9]
        wrong = record(q, answer=(q["answer"] + 1) % 3)
        plan = daily_review.plan_japanese([wrong], "user_001", now=NOW)
        self.assertEqual(plan["items"][0]["question_id"], q["question_id"])
        other = daily_review.plan_japanese([wrong], "user_002", now=NOW)
        self.assertNotIn(q["question_id"], other["reasons"])
        fixed = record(q, day=8, selection="review", chain="new_review_chain")
        before, after = jp.analyze([wrong], NOW), jp.analyze([wrong, fixed], NOW)
        self.assertEqual(before["summary"], after["summary"])
        self.assertEqual(next(g for g in after["tags"] if g["key"] == "emotion")["label"], "気持ちを読む")
        self.assertEqual(after["review"]["count"], 1)
        state = daily_review.schedule([wrong, fixed], "user_001", "japanese", NOW)[q["question_id"]]
        self.assertTrue(state["latest"]["correct"])
        self.assertEqual(state["due_date"], NOW.date() + timedelta(days=3))

    def test_persistence_and_idempotent_retry_preserve_evidence_and_chain(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "reading.sqlite3"
            jp.init_db(path)
            for i, q in enumerate(READING_QUESTIONS):
                row = record(q, chain=f"chain{i}")
                jp.save_record(row, path)
                jp.save_record(row, path)
            rows = jp.read_all("user_001", path)
            self.assertEqual(len(rows), 16)
            self.assertEqual(jp.read_all("user_002", path), [])
            for row in rows:
                source = next(q for q in READING_QUESTIONS if q["question_id"] == row["question_id"])
                self.assertEqual(row["explanation"], source["explanation"])
                self.assertEqual(row["text"], source["text"])
                self.assertEqual(existing_tests.record(source)["category"], row["category"])
            jp.save_record(record(READING_QUESTIONS[0]), Path(folder) / "never-created.sqlite3", test_mode=True)
            self.assertFalse((Path(folder) / "never-created.sqlite3").exists())


class ReadingExpansionUI(unittest.TestCase):
    setUp = existing_tests.JapaneseAppTests.setUp
    event = existing_tests.JapaneseAppTests.event

    def test_evidence_only_after_answer_and_result_retry_reuse_original_chain(self):
        with patch("japanese.choose_questions", return_value=deepcopy(READING_QUESTIONS[:5])):
            self.app.radio(key="jp_category").set_value("passage")
            self.app.radio(key="jp_count").set_value(5)
            self.app.button(key="jp_start").click().run()
        for index in range(5):
            question = self.app.session_state.jp_round["questions"][index]
            args = json.loads(self.app.get("component_instance")[0].proto.json_args)
            self.assertIsNone(args["explanation"])
            self.assertIsNone(args["correct_answer"])
            answer = (question["answer"] + 1) % 3 if index == 0 else question["answer"]
            self.event(answer, hint=index == 0)
            args = json.loads(self.app.get("component_instance")[0].proto.json_args)
            self.assertEqual(args["explanation"], question["explanation"])
            self.assertIn("てがかりは", args["explanation"])
            self.event(next=True)
        self.assertEqual(self.app.metric[1].value, "80%")
        wrong = next(row for row in jp.read_all("user_001") if not row["correct"])
        self.app.button(key="jp_retry").click().run()
        self.event(self.app.session_state.jp_round["questions"][0]["answer"])
        self.event(next=True)
        latest = jp.read_all("user_001")[0]
        self.assertEqual(latest["chain_id"], wrong["chain_id"])
        self.assertEqual(latest["attempt_count"], 2)
        self.assertEqual(latest["explanation"], wrong["explanation"])


if __name__ == "__main__":
    unittest.main()
