"""音声イベントはモックし、保存とカード進行を一時 SQLite で検証。"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import learning
import japanese
from test_learning import test_environment


class FlashcardUIAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'math.sqlite3'
        self.jp_path = Path(self.temp.name) / 'jp.sqlite3'
        self.writer = learning.save_attempt
        self.reader = learning.read_attempts
        self.init = learning.init_db
        self.jp_init = japanese.init_db
        self.init(self.path)
        self.jp_init(self.jp_path)
        self.lost = False
        self.saved_calls = []
        patches = [patch.dict('os.environ', test_environment(), clear=True), patch('streamlit.secrets', {}),
                   patch('learning.init_db', side_effect=lambda: self.init(self.path)),
                   patch('japanese.init_db', side_effect=lambda: self.jp_init(self.jp_path)),
                   patch('learning.save_attempt', side_effect=self.save),
                   patch('learning.read_attempts', side_effect=lambda user, **kw: self.reader(user, path=self.path, **kw)),
                   patch('flashcards_ui.keyboard', return_value=None)]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.keyboard = self.mocks[-1]
        self.app = AppTest.from_file('app.py', default_timeout=15).run()
        self.click('select_user_001')
        self.click('flashcard_open')
        self.app.select_slider(key='fc_count').set_value(5).run()
        self.click('fc_start')

    def save(self, record):
        self.saved_calls.append(deepcopy(record))
        self.writer(record, self.path)
        if self.lost:
            self.lost = False
            raise OSError('保存後応答だけ失敗')

    def rows(self):
        return self.reader('user_001', page_size=100, path=self.path)[0]

    def click(self, key):
        self.app.button(key=key).click().run()
        self.assertFalse(self.app.exception)

    def event(self, action, **data):
        state = self.app.session_state.fc_round
        token = f"{state['session_id']}:{state['index']}:{state['phase']}:{state['revision']}"
        event = {'token': token, 'action': action, 'response_time_sec': 2.5, **data}
        self.keyboard.return_value = event
        self.app.run()
        self.assertFalse(self.app.exception)
        self.keyboard.return_value = None
        return event

    def answer(self, correct=True, method='keyboard'):
        state = self.app.session_state.fc_round
        value = state['cards'][state['index']]['correct_answer'] if correct else 0
        return self.event('answer', input_method=method, answer=value)

    def test_unknown_and_wrong_speech_confirmation_manual_fallback_metadata(self):
        self.event('recognition_failed', recognized_text='わからない')
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.app.session_state.fc_round['voice_failures'], 1)
        # 13 の答えを期待していても認識した 3 を正解へ補正しない。
        state = self.app.session_state.fc_round
        state['cards'][0] = learning.make_problem('addition', 20, 9, 4)
        self.event('answer', input_method='voice', recognized_text='3', answer=13)
        self.assertEqual(state['phase'], 'confirm')
        self.assertEqual(state['candidate']['answer'], 3)
        self.assertEqual(self.rows(), [])
        self.event('correct_voice')
        self.assertEqual(self.rows(), [])
        self.answer(method='keypad')
        row = self.rows()[0]
        self.assertEqual((row['input_method'], row['user_answer'], row['recognition_retry_count']), ('keypad', 13, 2))
        self.assertIsNone(row['parsed_answer'])
        self.assertIsNone(row['recognized_text'])
        self.assertIsNone(row['recognition_success'])
        self.assertEqual(row['response_time_sec'], 2.5)
        self.assertEqual(row['session_elapsed_sec'], 2.5)
        self.assertEqual(row['total_recognition_retry_count'], 2)

    def test_confirm_wrong_voice_and_retry_are_independent_records(self):
        self.event('answer', input_method='voice', recognized_text='3')
        self.event('confirm_voice', response_time_sec=4)
        first = self.rows()[0]
        self.assertFalse(first['is_correct'])
        self.assertEqual(first['recognized_text'], '3')
        self.assertTrue(first['recognition_success'])
        self.event('next')
        for _ in range(4):
            self.answer()
            self.event('next')
        self.assertEqual(self.app.session_state.screen, 'flashcard_results')
        self.click('fc_retry')
        self.answer()
        self.event('next')
        rows = self.rows()
        matching = [r for r in rows if r['problem_id'] == first['problem_id']]
        self.assertEqual(len(rows), 6)
        self.assertEqual(len(matching), 2)
        retry = next(r for r in matching if r['selection_type'] == 'retry')
        self.assertNotEqual(first['attempt_id'], retry['attempt_id'])
        self.assertEqual(retry['attempt_count'], 2)
        self.assertFalse(retry['first_attempt_correct'])
        self.assertTrue(retry['is_correct'])

    def test_lost_save_response_and_stale_events_cannot_duplicate_or_overwrite(self):
        self.lost = True
        old = self.answer()
        state = self.app.session_state.fc_round
        pending = deepcopy(state['pending'])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(state['answers'], [])
        self.assertEqual(state['index'], 0)
        self.click('fc_retry_save')
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(state['answers'][0]['attempt_id'], pending['attempt_id'])
        self.keyboard.return_value = old
        self.app.run()
        self.keyboard.return_value = None
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(state['answers']), 1)
        self.event('next')
        self.keyboard.return_value = old
        self.app.run()
        self.keyboard.return_value = None
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(state['index'], 1)

    def test_test_round_never_invokes_writer_even_if_global_mode_is_removed(self):
        self.app.session_state.parent_test_mode = True
        self.app.session_state.screen = 'flashcard_settings'
        self.app.run()
        self.click('fc_start')
        self.app.session_state.parent_test_mode = False
        self.answer()
        self.assertEqual(self.saved_calls, [])
        self.assertEqual(self.rows(), [])
        self.assertEqual(len(self.app.session_state.fc_round['answers']), 1)

    def test_invalid_events_and_changed_user_cannot_save(self):
        for data in ({'answer': True}, {'answer': 100}, {'answer': 13, 'response_time_sec': float('nan')},
                     {'answer': 13, 'response_time_sec': -1}):
            self.event('answer', input_method='keyboard', **data)
        self.assertEqual(self.rows(), [])
        self.app.session_state.user_id = 'user_002'
        self.answer()
        self.assertEqual(self.app.session_state.screen, 'flashcard_settings')
        self.assertEqual(self.rows(), [])

    def test_voice_round_setting_survives_next_and_stop_does_not_assess(self):
        state = self.app.session_state.fc_round
        number = state['cards'][0]['correct_answer']
        self.event('answer', input_method='voice', recognized_text=str(number), voice_enabled=True)
        row = self.rows()[0]
        self.assertTrue(row['is_correct'])
        self.assertEqual(row['parsed_answer'], number)
        self.assertEqual(row['recognized_text'], str(number))
        self.assertEqual(state['index'], 1)  # 保存後の中間画面・next往復を省く。
        self.assertEqual(state['phase'], 'question')
        self.assertTrue(self.keyboard.call_args.kwargs['previous_correct'])
        self.assertTrue(state['voice_enabled'])
        self.assertTrue(self.keyboard.call_args.kwargs['voice_enabled'])
        self.event('voice_off', voice_enabled=False)
        self.assertFalse(state['voice_enabled'])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(state['index'], 1)

    def test_fast_voice_save_retry_advances_once_with_same_id_and_ignores_old_event(self):
        state = self.app.session_state.fc_round
        self.lost = True
        old = self.event('answer', input_method='voice', voice_enabled=True,
                         recognized_text=str(state['cards'][0]['correct_answer']))
        pending = deepcopy(state['pending'])
        self.assertEqual(state['index'], 0)
        self.assertEqual(len(state['answers']), 0)
        self.assertTrue(state['advance_after_save'])
        self.click('fc_retry_save')
        self.assertEqual(state['index'], 1)
        self.assertEqual(len(state['answers']), 1)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['attempt_id'], pending['attempt_id'])
        self.keyboard.return_value = old
        self.app.run()
        self.keyboard.return_value = None
        self.assertEqual(state['index'], 1)
        self.assertEqual(len(self.rows()), 1)

    def test_fast_voice_round_finishes_and_keeps_test_answers_out_of_history(self):
        self.app.session_state.parent_test_mode = True
        self.app.session_state.screen = 'flashcard_settings'
        self.app.run()
        self.app.select_slider(key='fc_count').set_value(5).run()
        self.click('fc_start')
        # セット開始時のおためしを固定し、途中の設定変更でも本番へ書かない。
        self.app.session_state.parent_test_mode = False
        state = self.app.session_state.fc_round
        self.assertEqual(len(state['cards']), 5)
        for index in range(5):
            self.assertEqual(state['index'], index)
            self.event('answer', input_method='voice', voice_enabled=True,
                       recognized_text=str(state['cards'][index]['correct_answer']))
        self.assertEqual(self.app.session_state.screen, 'flashcard_results')
        self.assertEqual(len(state['answers']), 5)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.saved_calls, [])

    def test_wrong_continuous_voice_requires_confirmation_and_keeps_saved_feedback(self):
        state = self.app.session_state.fc_round
        self.event('answer', input_method='voice', voice_enabled=True, recognized_text='0')
        self.assertEqual(state['phase'], 'confirm')
        self.assertEqual(state['index'], 0)
        self.assertEqual(self.rows(), [])
        self.event('confirm_voice', voice_enabled=True)
        self.assertEqual(state['phase'], 'saved')
        self.assertEqual(state['index'], 0)
        self.assertFalse(self.rows()[0]['is_correct'])
        self.event('next')
        self.assertEqual(state['index'], 1)

    def test_fast_voice_normal_round_saves_all_five_answers_and_finishes(self):
        state = self.app.session_state.fc_round
        for index in range(5):
            self.assertEqual(state['index'], index)
            self.assertEqual(state['phase'], 'question')
            self.event('answer', input_method='voice', voice_enabled=True,
                       recognized_text=str(state['cards'][index]['correct_answer']))
        rows = self.rows()
        self.assertEqual(self.app.session_state.screen, 'flashcard_results')
        self.assertEqual(len(rows), 5)
        self.assertEqual(len({row['attempt_id'] for row in rows}), 5)
        self.assertEqual(sorted(row['question_order'] for row in rows), [1, 2, 3, 4, 5])
        self.assertEqual(sum(row['round_completed'] for row in rows), 1)
        self.assertTrue(all(row['is_correct'] and row['input_method'] == 'voice' for row in rows))

    def test_narrow_range_repeats_preserve_initial_false_and_report_groups(self):
        self.app.session_state.screen = 'flashcard_settings'
        self.app.run()
        self.app.number_input(key='fc_min').set_value(18).run()
        self.app.number_input(key='fc_max').set_value(18).run()
        self.app.select_slider(key='fc_count').set_value(5).run()
        self.click('fc_start')
        self.answer(correct=False)
        self.event('next')
        for _ in range(4):
            self.answer()
            self.event('next')
        rows = sorted(self.rows(), key=lambda row: row['question_order'])
        self.assertEqual(len(rows), 5)
        self.assertEqual(len({row['problem_id'] for row in rows}), 1)
        self.assertEqual([row['attempt_count'] for row in rows], [1, 2, 3, 4, 5])
        self.assertTrue(all(not row['first_attempt_correct'] for row in rows))
        self.assertEqual(sum(row['is_correct'] for row in rows), 4)
        self.assertTrue(rows[-1]['round_completed'])
        self.click('fc_report_results')
        self.assertIn('セッションごとの成績', [e.label for e in self.app.expander])
        text = ' '.join(markdown.value for markdown in self.app.markdown)
        self.assertIn('同カードの初回', text)
        self.assertIn('同カードの2回目以降', text)
        self.click('fc_report_back')
        self.click('fc_retry')
        self.answer()
        self.event('next')
        retry = next(row for row in self.rows() if row['selection_type'] == 'retry')
        self.assertEqual(retry['attempt_count'], 6)
        self.assertFalse(retry['first_attempt_correct'])

    def test_three_unknown_recognitions_stop_continuous_voice_without_answer(self):
        for _ in range(3):
            self.event('recognition_failed', recognized_text='', voice_enabled=True)
        state = self.app.session_state.fc_round
        self.assertFalse(state['voice_enabled'])
        self.assertEqual(state['voice_failures'], 3)
        self.assertEqual(self.rows(), [])


if __name__ == '__main__':
    unittest.main()
