"""教科共通の学年表示と、採点・保存データからの独立性。"""

from copy import deepcopy
from datetime import datetime
import unittest
from unittest.mock import patch

from activity import JST
from canonical_text import TERMS, canonical_fields
from japanese_questions import QUESTIONS
from learning_profiles import default_profile
from text_display import READINGS_FOR_DISPLAY, component_display, parts_for, plain_label
from words import STORIES, make_word_problem


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=JST)


class TextDisplayTests(unittest.TestCase):
    def profile(self, grade=1, mode="all", tap=True, unlearned=()):
        profile = default_profile("user_001", NOW)
        profile.update(grade=grade, furigana_mode=mode, reading_tap=tap,
                       unlearned=list(unlearned))
        return profile

    def surface(self, text, profile):
        return "".join(part["text"] for part in parts_for(text, profile, NOW))

    def question(self, identifier):
        return deepcopy(next(q for q in QUESTIONS if q["question_id"] == identifier))

    def render(self, subject, item, profile):
        with patch("text_display.session_profile", return_value=profile):
            return component_display(subject, item, profile["user_id"])

    def test_six_grade_boundaries_keep_whole_words_and_correct_readings(self):
        examples = (("学校", "がっこう", 1), ("公園", "こうえん", 2),
                    ("学習", "がくしゅう", 3), ("積み木", "つみき", 4),
                    ("増える", "ふえる", 5), ("取り除いて", "とりのぞいて", 6))
        for grade in range(1, 7):
            profile = self.profile(grade, "none", False)
            for written, reading, required in examples:
                with self.subTest(grade=grade, word=written):
                    self.assertEqual(written if grade >= required else reading,
                                     self.surface(written, profile))

    def test_all_ruby_only_for_available_kanji(self):
        parts = parts_for("学校・公園", self.profile(1, "all", False), NOW)
        self.assertEqual("学校・こうえん", "".join(p["text"] for p in parts))
        self.assertEqual(["がっこう"], [p["reading"] for p in parts if p["reading"]])
        self.assertFalse(any(p["help_reading"] for p in parts))

    def test_current_ruby_applies_to_any_current_grade_character_in_a_word(self):
        profile = self.profile(3, "current", False)
        parts = parts_for("学校・公園・学習", profile, NOW)
        self.assertEqual("学校・公園・学習", "".join(p["text"] for p in parts))
        self.assertEqual(["がくしゅう"], [p["reading"] for p in parts if p["reading"]])
        # 学は小1、習は小3。語の最高学年だけでなく今年の字を含むことが条件。
        self.assertEqual("がくしゅう", next(p for p in parts if p["reading"])["reading"])

    def test_none_ruby_does_not_enable_tap_when_tap_is_off(self):
        parts = parts_for("学校・公園", self.profile(6, "none", False), NOW)
        self.assertFalse(any(p["reading"] or p["help_reading"] for p in parts))
        self.assertEqual("学校・公園", "".join(p["text"] for p in parts))

    def test_tap_reading_is_independent_of_ruby_and_keeps_surface(self):
        for mode, expected_ruby, expected_help in (
                ("all", "がっこう", ""), ("current", "", "がっこう"),
                ("none", "", "がっこう")):
            with self.subTest(mode=mode):
                parts = parts_for("学校", self.profile(2, mode, True), NOW)
                self.assertEqual([{"text": "学校", "reading": expected_ruby,
                                   "help_reading": expected_help}], parts)
        parts = parts_for("公園", self.profile(2, "current", True), NOW)
        self.assertEqual("こうえん", parts[0]["reading"])
        self.assertEqual("", parts[0]["help_reading"])

    def test_unlearned_override_returns_whole_word_to_hiragana(self):
        parts = parts_for("学校・公園", self.profile(6, "all", True, ("学",)), NOW)
        self.assertEqual("がっこう・公園", "".join(p["text"] for p in parts))
        self.assertEqual(["こうえん"], [p["reading"] for p in parts if p["reading"]])
        self.assertFalse(any(p["help_reading"] for p in parts))

    def test_outside_curriculum_known_word_stays_hiragana_at_every_grade(self):
        # 履は小学校の配当表外。歴を知っていても語全体を読みで表示する。
        for grade in range(1, 7):
            with self.subTest(grade=grade):
                parts = parts_for("履歴", self.profile(grade, "all", True), NOW)
                self.assertEqual([{"text": "りれき", "reading": "", "help_reading": ""}], parts)

    def test_auto_advance_updates_word_surface_at_april_first(self):
        profile = self.profile(1, "none", False)
        profile.update(auto_advance=True, base_school_year=2025)
        before = datetime(2026, 3, 31, 23, 59, tzinfo=JST)
        after = datetime(2026, 4, 1, 0, 0, tzinfo=JST)
        self.assertEqual("こうえん", "".join(p["text"] for p in parts_for("公園", profile, before)))
        self.assertEqual("公園", "".join(p["text"] for p in parts_for("公園", profile, after)))

    def test_original_hiragana_is_not_guessed_or_automatically_converted(self):
        text = "はし・あつい・はな・え・がっこう"
        self.assertEqual(text, self.surface(text, self.profile(6)))

    def test_both_subjects_use_same_per_child_grade(self):
        japanese = self.question("jp_particles_013")
        math = make_word_problem("combine", 10, 4, 2)
        for grade in (1, 2, 6):
            profile = self.profile(grade, "none", False)
            jp = self.render("japanese", japanese, profile)["display_fields"]
            ma = self.render("math", math, profile)["display_fields"]
            jp_surface = "".join(p["text"] for p in jp["text"][japanese["text"]]["parts"])
            ma_surface = "".join(p["text"] for p in ma["question"][math["question_text"]]["parts"])
            with self.subTest(grade=grade):
                self.assertIn("公園" if grade >= 2 else "こうえん", jp_surface)
                self.assertIn("積み木" if grade >= 4 else "つみき", ma_surface)

    def test_words_character_tasks_keep_all_fields_original(self):
        for q in QUESTIONS:
            if q["category"] == "words":
                result = self.render("japanese", q, self.profile(6))
                self.assertTrue(all(not mapping for mapping in result["display_fields"].values()))

    def test_particle_choices_and_answers_remain_learning_letters(self):
        for q in QUESTIONS:
            if q["category"] == "particles":
                fields = self.render("japanese", q, self.profile(6))["display_fields"]
                for field in ("choices", "selected", "correct_answer"):
                    with self.subTest(question=q["question_id"], field=field):
                        self.assertEqual({}, fields[field])
                explanation = fields["explanation"][q["explanation"]]["parts"]
                self.assertIn(f"「{q['target_particle']}」", "".join(p["text"] for p in explanation))

    def test_rendering_keeps_original_ids_answers_hint_and_profile_state(self):
        items = [("japanese", self.question("jp_sequence_002")),
                 ("japanese", self.question("jp_particles_015")),
                 ("math", make_word_problem("difference", 10, 4, 2))]
        profile = self.profile(6, "none", True)
        before_profile = deepcopy(profile)
        for subject, item in items:
            item["hint_used"] = False
            before_item = deepcopy(item)
            self.render(subject, item, profile)
            self.assertEqual(before_item, item)
            self.assertEqual(before_profile, profile)

    def test_unknown_or_changed_catalogs_supply_no_replacement_fields(self):
        unknown = self.question("jp_passage_010")
        unknown["question_id"] = "not_reviewed"
        changed = self.question("jp_passage_010")
        changed["text"] = "はなを かみました。"
        for item in (unknown, changed):
            fields = self.render("japanese", item, self.profile(6))["display_fields"]
            self.assertTrue(all(not mapping for mapping in fields.values()))

    def test_unreviewed_math_guidance_keeps_original_display(self):
        problem = make_word_problem("difference", 10, 4, 2)
        before = deepcopy(problem)
        changed = "学校は はなの かたちだよ。"
        with patch("words.guidance", return_value=changed):
            fields = self.render("math", problem, self.profile(1))["display_fields"]
        # 原文に既知語の学校を含んでも、未承認フィールドの変換は渡さない。
        self.assertEqual({}, fields["hint_text"])
        self.assertEqual({}, fields["explanation_text"])
        self.assertTrue(fields["question"])
        self.assertEqual(before, problem)

    def test_every_generated_canonical_kanji_is_managed_by_a_declared_reading(self):
        items = [("japanese", q) for q in QUESTIONS]
        items.extend(("math", make_word_problem(story, 10, 4, 2)) for story in STORIES)
        profile = self.profile(6, "all", False)
        for subject, item in items:
            for field, mapping in canonical_fields(subject, item).items():
                for original, written in mapping.items():
                    for part in parts_for(written, profile, NOW):
                        with self.subTest(subject=subject, field=field, original=original):
                            if any("\u3400" <= char <= "\u9fff" for char in part["text"]):
                                self.assertIn(part["text"], TERMS)
                                self.assertEqual(TERMS[part["text"]], part["reading"])

    def test_existing_known_kanji_hints_have_managed_readings(self):
        for q in QUESTIONS:
            fields = self.render("japanese", q, self.profile(1, "all", False))["display_fields"]
            for value in fields["hint"].values():
                for part in value["parts"]:
                    if any("\u3400" <= char <= "\u9fff" for char in part["text"]):
                        self.assertTrue(part["reading"], q["question_id"])

    def test_native_control_labels_follow_grade_without_touching_keys(self):
        with patch("text_display.session_profile", return_value=self.profile(1)):
            self.assertEqual("がくしゅうりれき", plain_label("学習履歴", "user_001"))
        with patch("text_display.session_profile", return_value=self.profile(6)):
            self.assertEqual("学習りれき", plain_label("学習履歴", "user_001"))
        self.assertEqual("りれき", READINGS_FOR_DISPLAY["履歴"])


if __name__ == "__main__":
    unittest.main()
