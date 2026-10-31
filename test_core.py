import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from core import BEIJING, PREFIX, Store, ask
from features import daily_status, summary_window


class ReplyTests(unittest.TestCase):
    def response(self, content):
        response = Mock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': content}}]}
        return response

    def test_rejects_blank_and_non_text_model_replies(self):
        for content in ('   \n\t', None, ['not text'], {'text': 'not a string'}):
            with self.subTest(content=content), patch('core.requests.post', return_value=self.response(content)):
                with self.assertRaisesRegex(RuntimeError, '正文'):
                    ask({'model': 'test', 'api_key': 'synthetic-key'}, 'question', [])

    def test_valid_reply_is_trimmed_and_prefixed(self):
        with patch('core.requests.post', return_value=self.response('  answer  ')):
            self.assertEqual(ask({'model': 'test', 'api_key': 'synthetic-key'}, 'question', []), (PREFIX+'answer', 0))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.addCleanup(self.store.db.close)

    def test_context_does_not_cross_account_or_room(self):
        for account, room, key in [('a', 'one', 'ok'), ('a', 'two', 'other-room'), ('b', 'one', 'other-account')]:
            self.store.add(account, room, {'key': key, 'seq': 1, 'ts': 100, 'text': key, 'sender': 'member'})
        self.assertEqual([m['key'] for m in self.store.recent('a', 'one')], ['ok'])

    def test_daily_status_uses_the_same_default_as_scheduler(self):
        for hour in (8, 10):
            now = datetime(2026, 10, 31, hour, tzinfo=BEIJING).timestamp()
            self.assertIn('09:00', daily_status(self.store, 'a', 'one', {'daily_enabled': True}, now))
        self.store.claim('a', 'one', 'daily:2026-10-31')
        self.assertIn('09:00', daily_status(self.store, 'a', 'one', {'daily_enabled': True}, now))

    def test_summary_before_daily_boundary_selects_last_complete_day(self):
        now = datetime(2026, 10, 31, 8, tzinfo=BEIJING).timestamp()
        start, end = summary_window(now)
        self.assertEqual(start, datetime(2026, 10, 29, 9, tzinfo=BEIJING))
        self.assertEqual(end, datetime(2026, 10, 30, 9, tzinfo=BEIJING))


if __name__ == '__main__':
    unittest.main()
