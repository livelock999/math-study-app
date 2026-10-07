"""公式配当表の総数・改訂箇所と、学年境界での共通表示判定を検証。"""

import unittest

from grade_kanji import (
    KANJI_BY_GRADE, KANJI_GRADE, available_at_grade, grade_for,
    kanji_through_grade, _GRADE_CHARACTERS,
)


class GradeKanjiTests(unittest.TestCase):
    def test_current_table_has_all_1026_characters_without_duplicates(self):
        for grade, characters in _GRADE_CHARACTERS.items():
            with self.subTest(grade=grade):
                self.assertEqual(len(characters), len(set(characters)))
        self.assertEqual(
            {grade: len(chars) for grade, chars in KANJI_BY_GRADE.items()},
            {1: 80, 2: 160, 3: 200, 4: 202, 5: 193, 6: 191},
        )
        characters = [c for chars in KANJI_BY_GRADE.values() for c in chars]
        self.assertEqual(len(characters), 1026)
        self.assertEqual(len(set(characters)), 1026)
        self.assertEqual(len(KANJI_GRADE), 1026)
        self.assertTrue(all("\u4e00" <= c <= "\u9fff" for c in characters))

    def test_2017_added_prefecture_kanji_are_in_grade_four(self):
        # 文科省「国語編」冊子18頁: 新規20字 + 旧小5から4字 + 旧小6から1字。
        for character in "茨媛岡潟岐熊香佐埼崎滋鹿縄井沖栃奈梨阪阜賀群徳富城":
            with self.subTest(character=character):
                self.assertEqual(grade_for(character), 4)
                self.assertFalse(available_at_grade(character, 3))
                self.assertTrue(available_at_grade(character, 4))

    def test_2017_reassigned_kanji_are_not_left_in_the_old_grade(self):
        for character in "囲紀喜救型航告殺士史象賞貯停堂得毒費粉脈歴":
            with self.subTest(character=character):
                self.assertEqual(grade_for(character), 5)
                self.assertFalse(available_at_grade(character, 4))
        for character in "胃腸恩券承舌銭退敵俵預":
            with self.subTest(character=character):
                self.assertEqual(grade_for(character), 6)
                self.assertFalse(available_at_grade(character, 5))

    def test_display_vocabulary_uses_the_required_grade_boundary(self):
        expected = {"学": 1, "校": 1, "算": 2, "語": 2, "習": 3,
                    "問": 3, "題": 3, "解": 5, "履": None, "歴": 5}
        for character, assigned in expected.items():
            with self.subTest(character=character):
                self.assertEqual(grade_for(character), assigned)
                for grade in range(1, 7):
                    self.assertEqual(
                        available_at_grade(character, grade),
                        assigned is not None and assigned <= grade,
                    )

    def test_unknown_and_non_single_character_inputs_do_not_get_a_grade(self):
        for value in ("あ", "ア", "1", "。", "龍", "𠮷", "", "学校", None, 1):
            with self.subTest(value=value):
                self.assertIsNone(grade_for(value))
                self.assertFalse(available_at_grade(value, 6))

    def test_cumulative_sets_expand_through_every_grade(self):
        expected_counts = {1: 80, 2: 240, 3: 440, 4: 642, 5: 835, 6: 1026}
        previous = frozenset()
        for grade, count in expected_counts.items():
            current = kanji_through_grade(grade)
            self.assertIsInstance(current, frozenset)
            self.assertEqual(len(current), count)
            self.assertTrue(previous < current)
            self.assertTrue(KANJI_BY_GRADE[grade] <= current)
            previous = current

    def test_invalid_grade_does_not_silently_enable_all_kanji(self):
        for grade in (0, 7, -1, 2.0, True, False, "2", None):
            with self.subTest(grade=grade):
                with self.assertRaises(ValueError):
                    available_at_grade("学", grade)
                with self.assertRaises(ValueError):
                    kanji_through_grade(grade)

    def test_shared_table_cannot_be_modified_by_a_consumer(self):
        with self.assertRaises(TypeError):
            KANJI_GRADE["学"] = 6
        with self.assertRaises(TypeError):
            KANJI_BY_GRADE[1] = frozenset()


if __name__ == "__main__":
    unittest.main()
