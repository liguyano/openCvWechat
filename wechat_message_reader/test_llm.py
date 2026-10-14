import json
import unittest
from unittest.mock import patch
from io import BytesIO
from urllib.error import HTTPError

from wechat_message_reader import llm


class ReplyTests(unittest.TestCase):
    config = dict(api_base='https://example.test/v1', api_key='test-secret',
                  model='qwen3.8-max', timeout=5)

    def test_request_and_reply_use_chat_completions(self):
        seen = {}
        def open_request(request, timeout):
            seen['url'] = request.full_url
            seen['body'] = json.loads(request.data)
            return BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
                              'message': {'content': ' Hello! ', 'reasoning_content': 'private'}}]}).encode())
        with patch('wechat_message_reader.llm.open_request', side_effect=open_request):
            reply = llm.generate_reply('incoming message', self.config)
        self.assertEqual(reply, 'Hello!')
        self.assertEqual(seen['url'], 'https://example.test/v1/chat/completions')
        self.assertEqual(seen['body']['model'], 'qwen3.8-max')
        self.assertEqual(seen['body']['messages'][-1], {'role': 'user', 'content': 'incoming message'})

    def test_empty_or_truncated_reply_fails(self):
        for content, reason in [('', 'stop'), (None, 'stop'), ('partial', 'length')]:
            result = {'choices': [{'finish_reason': reason, 'message': {'content': content}}]}
            with patch('wechat_message_reader.llm.open_request',
                       return_value=BytesIO(json.dumps(result).encode())):
                with self.assertRaises(RuntimeError):
                    llm.generate_reply('hi', self.config)

    def test_previous_turns_are_sent_in_order_without_modification(self):
        previous = [{'role': 'user', 'content': 'My name is Alice'},
                    {'role': 'assistant', 'content': 'Hello Alice'}]
        bodies = []
        def respond(request, timeout):
            bodies.append(json.loads(request.data))
            return BytesIO(json.dumps({'choices': [{'message': {'content': 'Alice'}}]}).encode())
        with patch('wechat_message_reader.llm.open_request', side_effect=respond):
            self.assertEqual(llm.generate_reply('My name?', self.config, previous), 'Alice')
        self.assertEqual(bodies[0]['messages'][1:], previous + [{'role': 'user', 'content': 'My name?'}])
        self.assertEqual(len(previous), 2)

    def test_http_failure_does_not_expose_key(self):
        error = HTTPError('https://example.test', 401, 'test-secret', {}, None)
        with patch('wechat_message_reader.llm.open_request', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                llm.generate_reply('hi', self.config)
        self.assertNotIn('test-secret', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
