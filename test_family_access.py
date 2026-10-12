"""家族専用リンクの入口と、通常URLの保護を実データに触れず検証。"""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from family_access import valid_family_link, family_link_key
from test_learning import test_environment

KEY = 'a' * 43  # テスト専用。本番ではランダム生成する。


class FamilyLinkTests(unittest.TestCase):
    def test_derived_key_is_stable_separate_and_overridable(self):
        settings = {'SUPABASE_SECRET_KEY': 'server-secret-for-testing-' + 'x'*32}
        key = family_link_key(lambda name: settings.get(name, ''))
        self.assertTrue(valid_family_link([key], key))
        self.assertNotEqual(key, settings['SUPABASE_SECRET_KEY'])
        self.assertEqual(key, family_link_key(lambda name: settings.get(name, '')))
        settings['SUPABASE_SECRET_KEY'] += 'changed'
        self.assertNotEqual(key, family_link_key(lambda name: settings.get(name, '')))
        settings['MATH_FAMILY_LINK_KEY'] = KEY
        self.assertEqual(family_link_key(lambda name: settings.get(name, '')), KEY)
        settings['MATH_FAMILY_LINK_KEY'] = 'invalid'
        self.assertEqual(family_link_key(lambda name: settings.get(name, '')), '')
        self.assertEqual(family_link_key(lambda name: ''), '')

    def test_single_matching_key_only(self):
        self.assertTrue(valid_family_link([KEY], KEY))
        for values in ([], [KEY, KEY], ['b'*43], [''], [None], [1], KEY,
                       [KEY+'!'], ['短い鍵'], ['a'*129]):
            with self.subTest(values=values):
                self.assertFalse(valid_family_link(values, KEY))

    def test_missing_or_invalid_configuration_fails_closed(self):
        for key in ('', None, True, 'short', 'a'*129, 'a'*42+'!'):
            with self.subTest(key=key):
                self.assertFalse(valid_family_link([KEY], key))


class FamilyLinkAppTests(unittest.TestCase):
    def setUp(self):
        patches = [patch.dict(os.environ, test_environment(), clear=True),
                   patch('streamlit.secrets', {}), patch('learning.init_db')]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        os.environ.update(MATH_REQUIRE_PASSWORD='true', MATH_APP_PASSWORD='test-password',
                          MATH_FAMILY_LINK_KEY=KEY)

    def app(self, token=None):
        app = AppTest.from_file(str(Path(__file__).with_name('app.py')), default_timeout=10)
        if token is not None:
            app.query_params['family'] = token
        return app.run()

    def assert_names(self, app):
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.text_input), 0)
        self.assertTrue({'select_user_001', 'select_user_002'}.issubset({b.key for b in app.button}))

    def assert_locked(self, app):
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.text_input), 1)
        self.assertFalse(any(b.key == 'select_user_001' for b in app.button))

    def test_valid_link_skips_form_on_first_visit_and_fresh_reload(self):
        self.assert_names(self.app(KEY))
        self.assert_names(self.app(KEY))
        self.mocks[-1].assert_called()

    def test_plain_url_wrong_and_duplicate_keys_do_not_touch_storage(self):
        for token in (None, 'b'*43, '', [KEY, KEY]):
            self.mocks[-1].reset_mock()
            self.assert_locked(self.app(token))
            self.mocks[-1].assert_not_called()

    def test_rotation_revokes_even_existing_link_session(self):
        app = self.app(KEY)
        self.assert_names(app)
        self.assertNotIn('access_granted', app.session_state)
        os.environ['MATH_FAMILY_LINK_KEY'] = 'b'*43
        self.mocks[-1].reset_mock()
        self.assert_locked(app.run())
        self.mocks[-1].assert_not_called()
        app.query_params['family'] = 'b'*43
        self.assert_names(app.run())
        os.environ.pop('MATH_FAMILY_LINK_KEY')
        self.assert_locked(app.run())

    def test_parent_test_mode_and_query_key_are_preserved(self):
        app = self.app(KEY)
        app.button(key='parent_test_start').click().run()
        self.assert_names(app)
        self.assertTrue(app.session_state.parent_test_mode)
        app.button(key='parent_test_end').click().run()
        self.assert_names(app)
        self.assertFalse(app.session_state.parent_test_mode)
        self.assertEqual(app.query_params['family'], KEY)

    def test_secret_setting_can_enable_link_without_environment_key(self):
        os.environ.pop('MATH_FAMILY_LINK_KEY')
        with patch('streamlit.secrets', {'MATH_FAMILY_LINK_KEY': KEY}):
            self.assert_names(self.app(KEY))

    def test_existing_server_secret_enables_link_without_new_setting(self):
        os.environ.pop('MATH_FAMILY_LINK_KEY')
        settings = {'SUPABASE_SECRET_KEY': 'server-secret-for-testing-' + 'x'*32}
        key = family_link_key(lambda name: settings.get(name, ''))
        with patch('streamlit.secrets', settings):
            self.assert_names(self.app(key))
            app = self.app()
            self.assert_locked(app)
            app.text_input(key='family_password').input('test-password')
            app.button[0].click().run()
            self.assert_names(app)
            self.assertTrue(any(e.label == '保護者向け：子ども用リンク' for e in app.expander))


if __name__ == '__main__':
    unittest.main()
