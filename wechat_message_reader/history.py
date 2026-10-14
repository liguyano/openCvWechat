"""Persistent, untruncated conversation context for the simple reply tool."""
import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / 'output' / 'chat_history.json'


class ChatHistory:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.messages = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            except (ValueError, OSError) as error:
                raise ValueError('Cannot load chat history. Clear history or fix the history file.') from error
            if not isinstance(data, list) or any(
                not isinstance(m, dict) or m.get('role') not in {'user', 'assistant'}
                or not isinstance(m.get('content'), str) for m in data
            ):
                raise ValueError('Invalid chat history format.')
            self.messages = data

    def write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.messages, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.path)

    def append_turn(self, incoming, reply):
        self.messages.extend([{'role': 'user', 'content': incoming},
                              {'role': 'assistant', 'content': reply}])
        self.write()

    def clear(self):
        self.messages = []
        self.write()


def clear_history(path=DEFAULT_PATH):
    # Allow the UI to clear even a damaged history file without loading it.
    store = ChatHistory.__new__(ChatHistory)
    store.path, store.messages = Path(path), []
    store.write()
