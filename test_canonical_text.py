"""教材表記の文脈・文字学習保護・保存原文の不変性。"""

from copy import deepcopy
from itertools import permutations
import re
import unittest
from unittest.mock import patch

import canonical_text as canonical
from japanese_questions import QUESTIONS
from learning import make_problem
from words import STORIES, guidance, make_word_problem


class CanonicalTextTests(unittest.TestCase):
    def question(self, identifier):
        return deepcopy(next(q for q in QUESTIONS if q["question_id"] == identifier))

    def test_readings_reconstruct_every_approved_original(self):
        pattern = re.compile("|".join(re.escape(term) for term in
                                     sorted(canonical.TERMS, key=len, reverse=True)))
        items = [("japanese", q) for q in QUESTIONS]
        items.extend(("math", make_word_problem(story, 10, 4, 2)) for story in STORIES)
        for subject, item in items:
            for field, mapping in canonical.canonical_fields(subject, item).items():
                for original, written in mapping.items():
                    with self.subTest(subject=subject, field=field, original=original):
                        spoken = pattern.sub(lambda m: canonical.TERMS[m.group()], written)
                        self.assertEqual(original, spoken)

    def test_approved_japanese_catalog_is_complete(self):
        expected = {q["question_id"] for q in QUESTIONS if q["category"] != "words"}
        self.assertEqual(expected, set(canonical._japanese_catalog()))

    def test_word_character_questions_protect_all_display_fields(self):
        for q in QUESTIONS:
            if q["category"] == "words":
                with self.subTest(question=q["question_id"]):
                    self.assertEqual(canonical.DISPLAY_FIELDS,
                                     canonical.protected_fields("japanese", q))
                    self.assertFalse(canonical.get_terms("japanese", q))
                    self.assertTrue(all(not mapping for mapping in
                                        canonical.canonical_fields("japanese", q).values()))

    def test_particle_letters_and_quoted_particles_stay_unchanged(self):
        for q in QUESTIONS:
            if q["category"] != "particles":
                continue
            with self.subTest(question=q["question_id"]):
                fields = canonical.canonical_fields("japanese", q)
                self.assertEqual({"choices", "selected", "correct_answer"},
                                 canonical.protected_fields("japanese", q))
                for field in canonical.protected_fields("japanese", q):
                    self.assertEqual({}, fields[field])
                explanation = fields["explanation"].get(q["explanation"], q["explanation"])
                self.assertIn(f"「{q['target_particle']}」", explanation)
                self.assertNotIn("歯", explanation)

    def test_school_place_is_converted_without_answer_changes(self):
        q = self.question("jp_particles_015")
        before = deepcopy(q)
        fields = canonical.canonical_fields("japanese", q)
        self.assertEqual("わたしは 学校（　）いきます。", fields["text"][q["text"]])
        self.assertEqual({}, fields["choices"])
        self.assertEqual(before, q)

    def test_ordering_partial_and_full_answers_use_original_choice_order(self):
        q = self.question("jp_sequence_002")
        fields = canonical.canonical_fields("japanese", q)
        for count in range(1, len(q["choices"]) + 1):
            for ordering in permutations(q["choices"], count):
                original = " → ".join(ordering)
                self.assertIn(original, fields["selected"])
                self.assertEqual(original.count(" → "), fields["selected"][original].count(" → "))

    def test_word_boundaries_preserve_existing_verbs_and_particle_quotes(self):
        q = self.question("jp_sequence_008")
        written = canonical.canonical_fields("japanese", q)["text"][q["text"]]
        self.assertIn("本を かえしました", written)
        self.assertNotIn("か絵", written)
        q = self.question("jp_sentence_004")
        self.assertEqual({}, canonical.canonical_fields("japanese", q)["hint"])

    def test_unknown_or_modified_questions_do_not_guess_homophones(self):
        for field in ("text", "choices", "hint", "explanation", "question"):
            q = self.question("jp_passage_010")
            q[field] = ["はし", "あつい", "はな"] if field == "choices" else "はなは はしに あたった。"
            with self.subTest(field=field):
                self.assertEqual({}, canonical.canonical_fields("japanese", q))
        q = self.question("jp_passage_010")
        q["question_id"] = "jp_passage_new"
        self.assertEqual({}, canonical.canonical_fields("japanese", q))

    def test_catalog_revision_requires_new_context_review(self):
        q = self.question("jp_passage_010")
        q["text"] = "はなを かみました。"  # 花でなく鼻の文脈。
        with patch.object(canonical, "_japanese_catalog", return_value={q["question_id"]: q}):
            self.assertEqual({}, canonical.canonical_fields("japanese", q))

    def test_no_dictionary_return_changes_problem_or_choices(self):
        before = deepcopy(QUESTIONS)
        for q in QUESTIONS:
            mappings = canonical.canonical_fields("japanese", q)
            for mapping in mappings.values():
                mapping.clear()
        self.assertEqual(before, QUESTIONS)

    def test_all_six_math_story_guidance_has_reviewed_terms(self):
        for story in STORIES:
            problem = make_word_problem(story, 10, 4, 2)
            before = deepcopy(problem)
            fields = canonical.canonical_fields("math", problem)
            with self.subTest(story=story):
                self.assertIn(guidance(problem), fields["hint_text"])
                self.assertIn(guidance(problem, reveal=True), fields["explanation_text"])
                self.assertEqual(before, problem)

    def test_math_known_question_rejects_changed_or_ambiguous_text(self):
        problem = make_word_problem("difference", 10, 4, 2)
        problem["question_text"] = "はしが 4こ あります。"
        self.assertEqual({}, canonical.canonical_fields("math", problem))
        problem = make_word_problem("difference", 10, 4, 2)
        problem["correct_answer"] = 100
        self.assertEqual({}, canonical.canonical_fields("math", problem))

    def test_math_guidance_revision_is_not_blindly_converted(self):
        problem = make_word_problem("difference", 10, 4, 2)
        with patch("words.guidance", return_value="はなに あわせて かんがえよう。"):
            fields = canonical.canonical_fields("math", problem)
        self.assertNotIn("hint_text", fields)
        self.assertNotIn("explanation_text", fields)
        self.assertIn("question", fields)  # 承認済み本文だけを表示変換する。

    def test_approved_unchanged_field_and_unreviewed_field_are_distinct(self):
        problem = make_word_problem("increase", 10, 4, 2)
        fields = canonical.canonical_fields("math", problem)
        self.assertIn("question", fields)
        self.assertEqual({}, fields["question"])
        original_hint = guidance(problem)
        with patch("words.guidance", side_effect=lambda p, reveal=False:
                   original_hint if not reveal else "学校は はなの かたちだよ。"):
            fields = canonical.canonical_fields("math", problem)
        self.assertIn("hint_text", fields)
        self.assertNotIn("explanation_text", fields)

    def test_calculation_guidance_preserves_arithmetic_and_ids(self):
        for operation, left, right in (("addition", 8, 5), ("subtraction", 13, 5)):
            problem = make_problem(operation, 20, left, right)
            before = deepcopy(problem)
            fields = canonical.canonical_fields("math", problem)
            self.assertEqual({}, fields["question"])
            self.assertIn(guidance(problem, reveal=True), fields["explanation_text"])
            self.assertEqual(before, problem)

    def test_exact_field_lookup_does_not_convert_an_unapproved_string(self):
        q = self.question("jp_passage_002")
        mapping = canonical.get_terms("japanese", q, "choices")
        self.assertEqual("学校", mapping["がっこう"])
        self.assertEqual("がっこうへ はしで いく", mapping.get("がっこうへ はしで いく",
                                                           "がっこうへ はしで いく"))

    def test_unknown_subject_and_invalid_items_leave_display_unchanged(self):
        for subject, item in (("other", {}), ("math", None), ("math", {}), ("japanese", {})):
            self.assertEqual({}, canonical.canonical_fields(subject, item))
            self.assertEqual({}, canonical.get_terms(subject, item))


if __name__ == "__main__":
    unittest.main()
