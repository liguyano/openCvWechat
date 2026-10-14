import json
from pathlib import Path
import tempfile
import unittest

from wechat_message_reader import history


class HistoryTests(unittest.TestCase):
    def location(self):
        folder = Path(__file__).parent / 'output'
        folder.mkdir(exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(dir=folder))
        return self.folder / 'history.json'

    def test_turns_survive_reload_and_clear(self):
        path = self.location()
        store = history.ChatHistory(path)
        store.append_turn('My name is Alice', 'Hello Alice')
        store.append_turn('What is my name?', 'Alice')
        loaded = history.ChatHistory(path)
        self.assertEqual(loaded.messages, [
            {'role': 'user', 'content': 'My name is Alice'},
            {'role': 'assistant', 'content': 'Hello Alice'},
            {'role': 'user', 'content': 'What is my name?'},
            {'role': 'assistant', 'content': 'Alice'}])
        loaded.clear()
        self.assertEqual(history.ChatHistory(path).messages, [])

    def test_invalid_history_does_not_silently_disappear(self):
        path = self.location()
        path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            history.ChatHistory(path)
