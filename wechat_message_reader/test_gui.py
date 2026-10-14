import unittest
from wechat_message_reader import gui


class CommandTests(unittest.TestCase):
    def values(self):
        return dict(mode='watch', current_chat=True, friend='', monitor='2',
                    taskbar_monitor='1', poll_interval='2', ocr_timeout='120',
                    wait='.8', result_offset_x='0', result_offset_y='78',
                    model='qwen3.8-max', title_keyword='', debug=False)

    def test_continuous_current_chat_command(self):
        command = gui.build_command(self.values())
        self.assertIn('--watch', command)
        self.assertIn('--current-chat', command)
        self.assertNotIn('--friend', command)

    def test_preview_searches_friend_without_watch(self):
        values = self.values()
        values.update(mode='preview', current_chat=False, friend='A friend')
        command = gui.build_command(values)
        self.assertIn('--preview-reply', command)
        self.assertIn('--reply', command)
        self.assertNotIn('--watch', command)
        self.assertEqual(command[command.index('--friend') + 1], 'A friend')

    def test_invalid_interval_or_missing_friend_rejected(self):
        for changes in (dict(poll_interval='0'), dict(current_chat=False, friend=''),
                        dict(ocr_timeout='nan'), dict(monitor='-1')):
            values = self.values()
            values.update(changes)
            with self.assertRaises(ValueError):
                gui.build_command(values)
