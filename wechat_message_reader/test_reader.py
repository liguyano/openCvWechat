import unittest
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from wechat_message_reader import reader


class MessageDetectionTests(unittest.TestCase):
    def scene(self):
        image = np.full((600, 1000, 3), 250, dtype=np.uint8)
        cv2.rectangle(image, (310, 450), (985, 590), (225, 225, 225), 1)
        return image

    def bubble(self, image, y, x=370, width=110, color=(240, 238, 238)):
        cv2.rectangle(image, (x, y), (x + width, y + 36), color, -1)
        cv2.putText(image, 'text', (x + 8, y + 24), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (35, 35, 35), 1)

    def test_last_incoming_excludes_outgoing_and_editor(self):
        image = self.scene()
        self.bubble(image, 110)
        self.bubble(image, 390)
        self.bubble(image, 410, x=830, color=(150, 240, 150))
        self.bubble(image, 500)
        result = reader.detect_latest_incoming(image, chat_left=300)
        self.assertIsNotNone(result)
        self.assertTrue(result.y <= 408 < result.y + result.h)
        self.assertTrue(result.x <= 420 < result.x + result.w)

    def test_empty_scene_does_not_select_input_box(self):
        self.assertIsNone(reader.detect_latest_incoming(self.scene(), chat_left=300))

    def test_menu_requires_copy_label_and_confidence(self):
        items = [dict(text='Delete', score=0.99, position=[[0, 0], [20, 0], [20, 20], [0, 20]]),
                 dict(text='Copy', score=0.9, position=[[30, 30], [70, 30], [70, 50], [30, 50]])]
        self.assertEqual(reader.find_copy_item(items), (50, 40))
        self.assertIsNone(reader.find_copy_item(items[:1]))
        items[1]['score'] = 0.1
        self.assertIsNone(reader.find_copy_item(items))

    def test_ocr_process_timeout_returns_instead_of_hanging(self):
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            reader.run_ocr_command([sys.executable, '-c', 'import time; time.sleep(30)'], .2)
        self.assertLess(time.monotonic() - started, 5)

    def test_ocr_process_failure_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, 'OCR process failed'):
            reader.run_ocr_command([sys.executable, '-c', 'raise SystemExit(3)'], 5)

    def test_waits_after_reply_and_accepts_same_text_on_next_turn(self):
        tracker = reader.TurnTracker()
        self.assertTrue(tracker.is_new('hello', True))
        tracker.mark_replied('hello')
        self.assertFalse(tracker.is_new('hello', True))
        self.assertFalse(tracker.is_new('hello', False))
        self.assertTrue(tracker.is_new('hello', True))

    def test_changed_message_is_new_without_outgoing_observation(self):
        tracker = reader.TurnTracker()
        tracker.mark_replied('old')
        self.assertFalse(tracker.is_new('old', True))
        self.assertTrue(tracker.is_new('new', True))

    def test_old_incoming_above_outgoing_is_not_new(self):
        tracker = reader.TurnTracker()
        self.assertFalse(tracker.is_new('old', False))

    def test_outgoing_detection_prevents_replying_to_an_old_message(self):
        image = self.scene()
        self.bubble(image, 110)
        self.bubble(image, 300, x=830, color=(150, 240, 150))
        outgoing = reader.detect_latest_outgoing(image, 300, 450)
        self.assertIsNotNone(outgoing)
        self.assertGreater(outgoing.y, reader.detect_latest_incoming(image, 300).y)

    def test_watch_exits_when_window_disappears(self):
        args = SimpleNamespace(poll_interval=2, input_top=450)
        recognizer = SimpleNamespace(refresh=lambda: None)
        image = self.scene()
        region = dict(left=1920, top=0, width=1000, height=600)
        with patch.object(reader.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'window not found'):
                reader.watch_conversation(args, recognizer, image, region, 300,
                                          Path(__file__).parent / 'output', {})

    def test_fingerprint_survives_message_moving_up_after_send(self):
        a, b = self.scene(), self.scene()
        self.bubble(a, 390)
        self.bubble(b, 200)
        first = reader.detect_latest_incoming(a, 300)
        second = reader.detect_latest_incoming(b, 300)
        self.assertEqual(reader.bubble_fingerprint(a, first), reader.bubble_fingerprint(b, second))


if __name__ == '__main__':
    unittest.main()
