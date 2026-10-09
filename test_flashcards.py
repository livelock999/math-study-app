"""計算カードの生成と、音声を推測で採点しない境界を検証します。"""
import unittest
import json
import sqlite3
import random
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

import flashcards
import learning


def card_record(method='voice'):
    record = learning.make_attempt(learning.make_problem('addition', 20, 9, 4),
                                   'user_001', 'flashcard-test', 1, 'normal', 13, 3.25, 1, round_size=1)
    record.update(learning_mode='flashcard', answer_range_min=11, answer_range_max=18,
                  input_method=method, recognized_text='じゅうさん' if method == 'voice' else None,
                  parsed_answer=13 if method == 'voice' else None,
                  recognition_success=True if method == 'voice' else None,
                  recognition_retry_count=2, first_attempt_correct=True,
                  session_elapsed_sec=3.25, total_recognition_retry_count=2)
    return record


class FlashcardTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(random.setstate, random.getstate())

    def test_subtraction_cards_cover_zero_borrowing_and_never_negative(self):
        for lower, upper in ((0, 0), (0, 9), (10, 19), (19, 19)):
            cards = flashcards.generate_cards(lower, upper, 50, 'ordered', mode='subtraction')
            self.assertEqual(len(cards), 50)
            for card in cards:
                self.assertEqual(card['operation'], 'subtraction')
                self.assertTrue(1 <= card['left_operand'] <= 20)
                self.assertTrue(1 <= card['right_operand'] <= 9)
                self.assertTrue(lower <= card['correct_answer'] <= upper)
                self.assertEqual(card['correct_answer'], card['left_operand'] - card['right_operand'])
                self.assertIsNone(card['carry'])
                self.assertEqual(card['borrowing'], card['left_operand'] % 10 < card['right_operand'])
        pool = flashcards.generate_cards(0, 19, 100, 'ordered', mode='subtraction')
        self.assertTrue(any(card['borrowing'] for card in pool))
        self.assertTrue(any(not card['borrowing'] for card in pool))
        self.assertTrue(any(card['correct_answer'] == 0 for card in pool))

    def test_mixed_decks_balanced_unique_when_possible_and_seeded_shuffle(self):
        odd_majorities = set()
        sequences = set()
        for seed in range(10):
            for count in (5, 20, 50):
                random.seed(seed)
                cards = flashcards.generate_cards(0, 18, count, 'ordered', mode='mixed')
                operations = [card['operation'] for card in cards]
                addition = operations.count('addition')
                subtraction = operations.count('subtraction')
                self.assertLessEqual(abs(addition - subtraction), 1)
                self.assertGreater(min(addition, subtraction), 0)
                self.assertEqual(len({card['problem_id'] for card in cards}), count)
                if count == 5:
                    odd_majorities.add('addition' if addition > subtraction else 'subtraction')
                    sequences.add(tuple(card['problem_id'] for card in cards))
        self.assertEqual(odd_majorities, {'addition', 'subtraction'})
        self.assertGreater(len(sequences), 1)
        random.seed(34)
        a = flashcards.generate_cards(0, 18, 20, 'ordered', mode='mixed')
        random.seed(34)
        b = flashcards.generate_cards(0, 18, 20, 'ordered', mode='mixed')
        self.assertEqual(a, b)

    def test_mixed_small_pool_repeats_and_invalid_ranges_fail_before_generation(self):
        cards = flashcards.generate_cards(2, 2, 20, mode='mixed')
        self.assertEqual(sum(card['operation'] == 'addition' for card in cards), 10)
        self.assertTrue(all(card['correct_answer'] == 2 for card in cards))
        for kwargs in ({'answer_min': 0, 'answer_max': 1, 'mode': 'mixed'},
                       {'answer_min': 19, 'answer_max': 19, 'mode': 'mixed'},
                       {'answer_min': 0, 'answer_max': 18, 'count': 1, 'mode': 'mixed'},
                       {'answer_min': 20, 'answer_max': 20, 'mode': 'subtraction'},
                       {'mode': 'mix'}, {'mode': None}, {'mode': True}):
            with self.subTest(kwargs=kwargs):
                values = dict(answer_min=11, answer_max=18, count=20, order='shuffle', mode='addition')
                values.update(kwargs)
                self.assertIsNotNone(flashcards.selection_error(**values))
                with self.assertRaises(ValueError):
                    flashcards.generate_cards(**values)

    def test_operation_and_structure_tables_distinguish_borrowing_from_carry(self):
        rows = []
        for operation, left, right in (('addition', 9, 4), ('subtraction', 13, 4), ('subtraction', 9, 4)):
            problem = learning.make_problem(operation, 20, left, right)
            row = learning.make_attempt(problem, 'user_001', 'structure', 1, 'normal',
                                        problem['correct_answer'], 2, 1)
            row.update(learning_mode='flashcard', input_method='keyboard', answer_range_min=0, answer_range_max=18)
            rows.append(row)
        tables = flashcards.report_tables(rows)
        self.assertEqual(len(tables['operations']), 2)
        self.assertEqual(len(tables['structures']), 3)
        structures = ' '.join(row['分類'] for row in tables['structures'])
        self.assertIn('繰り上がりあり', structures)
        self.assertIn('繰り下がりあり', structures)
        self.assertIn('繰り下がりなし', structures)
        for group in tables['structures']:
            if '繰り下がり' in group['分類']:
                self.assertNotIn('同じ数', group['分類'])
            else:
                self.assertIn('同じ数', group['分類'])

    def session_rows(self, size=3):
        rows = []
        for index, seconds in enumerate((1, 5, 3), 1):
            row = card_record()
            row.update(attempt_id=f'session_{index}', question_order=index, round_size=size,
                       round_completed=index == size, response_time_sec=seconds,
                       session_elapsed_sec=(2, 8, 12)[index - 1],
                       total_recognition_retry_count=index - 1,
                       datetime=f'2026-10-07T15:0{index}:00+00:00',
                       question_text=f'question {index}', is_correct=index != 2)
            rows.append(row)
        return rows

    def test_completed_session_retains_cumulative_time_failures_and_longest_problem(self):
        row = flashcards.session_table(self.session_rows())[0]
        self.assertEqual(row['状態'], '完了')
        self.assertEqual((row['保存済み問題数'], row['設定問題数'], row['正答数']), (3, 3, 2))
        self.assertEqual(row['同カード初回正答率'], '67%')
        self.assertEqual((row['平均（秒）'], row['最速（秒）'], row['最長（秒）']), (3, 1, 5))
        self.assertEqual(row['最長の問題'], 'question 2')
        self.assertEqual((row['認識やりなおし（累積）'], row['最終回答まで（秒）']), (2, 12))
        self.assertEqual(row['日時（日本時間）'], '2026/10/08 00:03')

    def test_incomplete_session_stays_incomplete_and_retry_initial_rate_unknown(self):
        rows = self.session_rows(size=5)[:2]
        for row in rows:
            row.update(selection_type='retry', attempt_count=2)
        actual = flashcards.session_table(rows)[0]
        self.assertEqual((actual['状態'], actual['練習']), ('途中', '再練習'))
        self.assertEqual((actual['保存済み問題数'], actual['設定問題数']), (2, 5))
        self.assertEqual(actual['同カード初回正答率'], '—')
        self.assertEqual(actual['最終回答まで（秒）'], 8)

    def test_completed_session_truncated_by_report_range_labels_partial_statistics(self):
        rows = self.session_rows()[-1:]
        actual = flashcards.session_table(rows)[0]
        self.assertEqual(actual['状態'], '完了（集計範囲は一部）')
        self.assertEqual((actual['保存済み問題数'], actual['設定問題数']), (1, 3))
        self.assertEqual((actual['認識やりなおし（累積）'], actual['最終回答まで（秒）']), (2, 12))
        self.assertEqual(actual['平均（秒）'], 3)

    def test_default_cards_use_single_digit_operands_and_answers_11_to_18(self):
        cards = flashcards.generate_cards()
        self.assertEqual(len(cards), 20)
        self.assertEqual(len({p['problem_id'] for p in cards}), 20)
        for card in cards:
            self.assertEqual(card['operation'], 'addition')
            self.assertTrue(1 <= card['left_operand'] <= 9)
            self.assertTrue(1 <= card['right_operand'] <= 9)
            self.assertEqual(card['correct_answer'], card['left_operand'] + card['right_operand'])
            self.assertTrue(11 <= card['correct_answer'] <= 18)

    def test_ordered_cards_and_invalid_or_insufficient_ranges(self):
        cards = flashcards.generate_cards(11, 18, 20, order='ordered')
        self.assertEqual(cards, flashcards.generate_cards(11, 18, 20, order='ordered'))
        for kwargs in ({'answer_min': 1}, {'answer_max': 19}, {'answer_min': 18, 'answer_max': 11},
                       {'count': True}, {'count': 0}, {'order': 'unknown'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                flashcards.generate_cards(**kwargs)
        narrow = flashcards.generate_cards(18, 18, 20)
        self.assertEqual(len(narrow), 20)
        self.assertTrue(all(p['correct_answer'] == 18 for p in narrow))

    def test_speech_numbers_are_parsed_without_using_expected_answer(self):
        for phrase, expected in [('13', 13), ('１３', 13), ('十三', 13), ('じゅうさん', 13),
                                 ('ジュウサン', 13), ('3', 3), ('さん', 3), ('零', 0), ('99', 99)]:
            with self.subTest(phrase=phrase):
                self.assertEqual(flashcards.parse_spoken_number(phrase), expected)
        for phrase in ('', '13か3', '13 3', 'わからない', 'たぶん13', '-3', '1.3', '100'):
            with self.subTest(phrase=phrase):
                self.assertIsNone(flashcards.parse_spoken_number(phrase))

    def test_speed_summary_and_jst_daily_table(self):
        rows = [card_record() for _ in range(3)]
        for row, seconds, correct in zip(rows, (1, 3, 8), (True, False, True)):
            row.update(response_time_sec=seconds, is_correct=correct, datetime='2026-10-07T15:00:00+00:00')
        summary = flashcards.summarize(rows)
        self.assertEqual((summary['count'], summary['correct'], summary['median_seconds']), (3, 2, 3))
        self.assertEqual(summary['average_seconds'], 4)
        self.assertEqual((summary['fastest_seconds'], summary['slowest_seconds']), (1, 8))
        self.assertEqual(len(summary['mistakes']), 1)
        self.assertEqual(flashcards.report_tables(rows)['days'][0]['分類'], '2026/10/08')
        self.assertIsNone(flashcards.summarize([])['median_seconds'])

    def test_initial_accuracy_excludes_repeated_normal_cards_and_retry(self):
        first = card_record()
        first.update(is_correct=False, first_attempt_correct=False)
        repeat = {**first, 'attempt_id': 'repeat', 'attempt_count': 2, 'is_correct': True}
        retry = {**repeat, 'attempt_id': 'retry', 'selection_type': 'retry', 'attempt_count': 3}
        summary = flashcards.summarize([first, repeat, retry])
        self.assertEqual((summary['count'], summary['correct'], summary['first_count'], summary['first_rate']),
                         (3, 2, 1, 0))
        self.assertIsNone(flashcards.summarize([repeat, retry])['first_rate'])
        from cross_subject import build_report
        now = datetime.now(timezone.utc)
        report = build_report([first, repeat, retry], [], 'user_001', now=now)
        cards = next(g for g in report['groups'] if g['label'] == '算数：計算カード')
        self.assertEqual((cards['count'], cards['rate']), (1, 0))

    def test_new_metadata_migrates_nullable_and_roundtrips_sqlite_idempotently(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'old.sqlite3'
            old = learning.make_attempt(learning.make_problem('addition', 10, 2, 3),
                                        'user_001', 'old', 1, 'normal', 999, 1, 1)
            columns = {k: v for k, v in learning.COLUMNS.items() if k not in learning.FLASHCARD_COLUMNS}
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE attempts (' + ', '.join(f'"{k}" {v}' for k, v in columns.items()) + ')')
                db.execute('INSERT INTO attempts (' + ', '.join(columns) + ') VALUES (' +
                           ', '.join('?' for _ in columns) + ')', [old[k] for k in columns])
            learning.init_db(path)
            record = card_record()
            learning.save_attempt(record, path)
            learning.save_attempt(record, path)
            rows, _ = learning.read_attempts('user_001', path=path)
            self.assertEqual(len(rows), 2)
            old_saved = next(r for r in rows if r['session_id'] == 'old')
            self.assertEqual(old_saved['user_answer'], 999)
            self.assertTrue(all(old_saved[k] is None for k in learning.FLASHCARD_COLUMNS))
            saved = next(r for r in rows if r['attempt_id'] == record['attempt_id'])
            for key in learning.FLASHCARD_COLUMNS:
                self.assertEqual(saved[key], record[key])

    def test_cloud_payload_retains_all_card_metadata_and_duplicate_resolution(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 201
        response.getcode.return_value = 201
        record = card_record()
        with patch('learning.get_supabase_config', return_value=('https://example.supabase.co', 'sb_secret_fake')), \
                patch('learning.supabase_urlopen', return_value=response) as post:
            learning.save_attempt(record)
        request = post.call_args.args[0]
        payload = json.loads(request.data)
        if isinstance(payload, list):
            payload = payload[0]
        for key in learning.FLASHCARD_COLUMNS:
            self.assertEqual(payload[key], record[key])
        self.assertIn('resolution=ignore-duplicates', request.get_header('Prefer'))

    def test_backup_roundtrip_retains_voice_and_manual_failures(self):
        import history_backup
        records = [card_record(), card_record('keyboard')]
        records[1]['attempt_id'] += '_manual'
        data = history_backup.export_backup('user_001', records, [])
        restored = history_backup.parse_backup(data, 'user_001')['math']
        self.assertEqual(restored, records)

    def test_card_speed_does_not_change_ordinary_assessment_or_review_weakness(self):
        from assessment import assess
        from cross_subject import build_report
        from daily_review import schedule
        slow, fast = card_record(), card_record()
        slow.update(attempt_id='slow', response_time_sec=100, datetime='2026-10-07T00:00:00+09:00')
        fast.update(attempt_id='fast', response_time_sec=0.01, datetime=slow['datetime'])
        self.assertEqual(assess([slow], 'user_001')['overall']['count'], 0)
        now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        a = schedule([slow], 'user_001', 'math', now)
        b = schedule([fast], 'user_001', 'math', now)
        self.assertEqual(a[slow['problem_id']]['interval_days'], b[fast['problem_id']]['interval_days'])
        report = build_report([slow], [], 'user_001', now=now)
        self.assertEqual(report['groups'][0]['count'], 0)
        self.assertEqual(next(g for g in report['groups'] if g['label'] == '算数：計算カード')['count'], 1)


if __name__ == '__main__':
    unittest.main()
