"""CLI: python -m wechat_message_reader.reader --friend NAME --monitor 2."""

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
import time
import uuid

import cv2
import numpy as np


@dataclass(frozen=True)
class Bubble:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2


class TurnTracker:
    """Avoid resending a reply until new content or an observed new turn."""
    def __init__(self):
        self.last_replied = None
        self.saw_outgoing = False

    def is_new(self, fingerprint, incoming_is_last):
        if not incoming_is_last:
            if self.last_replied is not None:
                self.saw_outgoing = True
            return False
        return self.saw_outgoing or fingerprint != self.last_replied

    def mark_replied(self, fingerprint):
        self.last_replied = fingerprint
        self.saw_outgoing = False


def detect_latest_outgoing(image, chat_left, input_top):
    h, w = image.shape[:2]
    top = max(60, int(h * .12))
    roi = image[top:input_top, chat_left:w]
    if roi.size == 0:
        return None
    mask = cv2.inRange(cv2.cvtColor(roi, cv2.COLOR_BGR2HSV),
                       np.array([35, 45, 80]), np.array([95, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if x > (w - chat_left) * .35 and bw >= 30 and bh >= 22 and bh < h * .4:
            boxes.append(Bubble(x + chat_left, y + top, bw, bh))
    return max(boxes, key=lambda b: b.y + b.h) if boxes else None


def bubble_fingerprint(image, bubble):
    patch = image[bubble.y:bubble.y + bubble.h, bubble.x:bubble.x + bubble.w]
    # Quantize text pixels, not screen coordinates; sending may move old bubbles.
    dark = (cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) < 180).astype(np.uint8)
    return hashlib.sha256(str(dark.shape).encode() + dark.tobytes()).hexdigest()


def detect_input_top(image, chat_left):
    """Find a long editor boundary below the middle of the chat window."""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image[:, chat_left:], cv2.COLOR_BGR2GRAY)
    lines = cv2.HoughLinesP(cv2.Canny(gray, 20, 70), 1, np.pi / 180,
                            60, minLineLength=int((w - chat_left) * .85), maxLineGap=15)
    ys = []
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            if abs(int(y1) - int(y2)) <= 3 and h * .55 < y1 < h * .90:
                ys.append(int(min(y1, y2)))
    return min(ys) if ys else int(h * .75)


def detect_latest_incoming(image, chat_left=None, input_top=None):
    """Return the lowest visible gray bubble anchored near the incoming column."""
    h, w = image.shape[:2]
    chat_left = int(w * .30) if chat_left is None else int(chat_left)
    if not 0 <= chat_left < w - 50:
        raise ValueError('Chat boundary is outside the image.')
    input_top = detect_input_top(image, chat_left) if input_top is None else int(input_top)
    top = max(60, int(h * .12))
    if input_top <= top:
        return None
    roi = image[top:input_top, chat_left:w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 215]), np.array([180, 25, 245]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        # Avatars occupy the first ~20..60 pixels; incoming bubbles follow them.
        if not 45 <= x <= 150:
            continue
        if bw < 30 or bh < 22 or bw > (w - chat_left) * .75 or bh > h * .40:
            continue
        if cv2.contourArea(contour) / (bw * bh) < .60:
            continue
        patch = roi[y:y + bh, x:x + bw]
        # Require dark content instead of accepting an empty gray panel.
        if np.count_nonzero(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) < 180) < 5:
            continue
        candidates.append(Bubble(chat_left + x, top + y, bw, bh))
    return max(candidates, key=lambda b: (b.y + b.h, b.y)) if candidates else None


def find_copy_item(items):
    """Choose an exact Copy label, never a guessed menu row."""
    for item in items:
        text = ''.join(str(item.get('text', '')).split()).lower()
        if text not in {'copy', '\u590d\u5236', '\u8907\u88fd', '\u30b3\u30d4\u30fc'}:
            continue
        if float(item.get('score', 0)) < .5:
            continue
        points = np.asarray(item.get('position', []))
        if points.ndim == 2 and points.shape[1] == 2 and len(points) >= 2:
            return tuple(np.mean(points, axis=0).astype(int))
    return None


def save_preview(image, bubble, output):
    output.mkdir(parents=True, exist_ok=True)
    preview = image.copy()
    if bubble:
        cv2.rectangle(preview, (bubble.x, bubble.y),
                      (bubble.x + bubble.w, bubble.y + bubble.h), (0, 0, 255), 2)
    cv2.imencode('.png', preview)[1].tofile(str(output / 'latest_incoming.png'))


def run_ocr_command(command, timeout):
    """Bound heavy imports, model downloads, and inference in one child process."""
    if timeout <= 0:
        raise ValueError('OCR timeout must be greater than zero.')
    try:
        subprocess.run(command, check=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f'OCR timed out after {timeout:g}s. Check model downloads/network; '
            'retry with --ocr-timeout 120 if the first model load needs more time.'
        ) from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f'OCR process failed (exit {error.returncode}); see the error above.') from error


def copy_bubble(bubble, region, output, ocr_timeout=45):
    """Right-click and OCR Copy; require a fresh clipboard value."""
    import pyautogui
    import pyperclip
    from mss import MSS

    print('Checking OCR dependencies...', flush=True)
    for dependency in ('cnocr', 'onnxruntime'):
        if importlib.util.find_spec(dependency) is None:
            raise RuntimeError(
                f'Missing OCR dependency: {dependency}. Install using: '
                f'"{sys.executable}" -m pip install {dependency}'
            )
    previous = pyperclip.paste()
    sentinel = 'wechat-reader-' + uuid.uuid4().hex
    x, y = bubble.center
    abs_x, abs_y = region['left'] + x, region['top'] + y
    copied = False
    pyperclip.copy(sentinel)
    try:
        print('Opening the message context menu...', flush=True)
        pyautogui.click(abs_x, abs_y, button='right')
        time.sleep(.5)
        # Capture around the pointer, clipped to the same window. Menus can
        # open above or below the pointer, depending on available space.
        left, top = max(0, x - 260), max(0, y - 380)
        right, bottom = min(region['width'], x + 340), min(region['height'], y + 380)
        menu_region = dict(left=region['left'] + left, top=region['top'] + top,
                           width=right - left, height=bottom - top)
        with MSS() as sct:
            image = cv2.cvtColor(np.array(sct.grab(menu_region)), cv2.COLOR_BGRA2BGR)
        menu_path = output / 'copy_menu.png'
        result_path = output / 'copy_menu_ocr.json'
        cv2.imencode('.png', image)[1].tofile(str(menu_path))
        result_path.unlink(missing_ok=True)
        print(f'Recognizing Copy menu (timeout {ocr_timeout:g}s)...', flush=True)
        run_ocr_command([sys.executable, '-u', '-m', 'wechat_message_reader.ocr_worker',
                         str(menu_path), str(result_path)], ocr_timeout)
        point = find_copy_item(json.loads(result_path.read_text(encoding='utf-8')))
        if point is None:
            raise RuntimeError('Copy menu item not found. The message may not be copyable text; inspect copy_menu.png.')
        print('Copy menu found; clicking and waiting for clipboard text...', flush=True)
        pyautogui.click(menu_region['left'] + int(point[0]), menu_region['top'] + int(point[1]))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            text = pyperclip.paste()
            if text and text != sentinel:
                copied = True
                return text
            time.sleep(.1)
        raise RuntimeError('Copy did not produce fresh clipboard text.')
    finally:
        if not copied:
            pyautogui.press('esc')
            # Preserve another application's clipboard update if one occurred.
            if pyperclip.paste() == sentinel:
                pyperclip.copy(previous)


def run(args):
    output = Path(args.output).resolve()
    config = None
    if args.reply:
        if args.image or args.detect_only:
            raise ValueError('--reply cannot be combined with --image or --detect-only.')
        from .llm import load_config
        config = load_config(args.config, args.model)
        from .history import ChatHistory
        config['_history'] = ChatHistory()
        print(f'Loaded {len(config["_history"].messages) // 2} previous conversation turns.', flush=True)
    if args.image:
        image = cv2.imdecode(np.fromfile(args.image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Cannot read the supplied image.')
        region = None
        chat_left = args.chat_left
    else:
        from main import search_friend_and_click_first_result
        from wechat_search_box_recognizer_click import WeChatSearchBoxRecognizer
        if not args.current_chat:
            if not args.friend:
                raise ValueError('Provide --friend NAME or use --current-chat.')
            ok = search_friend_and_click_first_result(
                friend_keyword=args.friend, monitor_index=args.monitor,
                title_keyword=args.title_keyword, debug_search=args.debug,
                result_offset_x=args.result_offset_x, result_offset_y=args.result_offset_y,
                wait_after_paste=args.wait, taskbar_monitor_index=args.taskbar_monitor)
            if not ok:
                raise RuntimeError('Could not open the requested conversation.')
        recognizer = WeChatSearchBoxRecognizer(args.monitor, args.debug, args.title_keyword)
        result = recognizer.refresh()
        if result is None:
            raise RuntimeError('Could not identify the visible WeChat window.')
        image, region = recognizer.window_image, recognizer.window_region
        chat_left = args.chat_left
        if chat_left is None:
            chat_left = result.plus_x - region['left'] + 26
    if args.watch:
        watch_conversation(args, recognizer, image, region, chat_left, output, config)
        return
    bubble = detect_latest_incoming(image, chat_left, args.input_top)
    save_preview(image, bubble, output)
    if bubble is None:
        raise RuntimeError('No visible incoming gray message bubble found. Inspect latest_incoming.png.')
    print(f'Latest visible incoming bubble: {bubble}')
    print(f'Preview: {output / "latest_incoming.png"}')
    if args.image or args.detect_only:
        return
    reply_to_bubble(args, image, region, chat_left, bubble, output, config,
                    recognizer if region is not None else None)


def reply_to_bubble(args, image, region, chat_left, bubble, output, config, recognizer):
    text = copy_bubble(bubble, region, output, args.ocr_timeout)
    (output / 'latest_message.txt').write_text(text, encoding='utf-8')
    print('Copied text:\n' + text)
    print(f'Saved: {output / "latest_message.txt"}')
    if config is not None:
        from .llm import generate_reply
        print(f'Generating reply with {config["model"]}...', flush=True)
        history = config['_history']
        reply = generate_reply(text, config, history.messages)
        (output / 'model_reply.txt').write_text(reply, encoding='utf-8')
        print('Model reply:\n' + reply, flush=True)
        if args.preview_reply:
            print('Preview complete; reply was not pasted or sent.')
            return
        # A slow API call gives the user time to switch chats. Recheck the
        # conversation title area before reusing the sender on this monitor.
        old_region = dict(region)
        if recognizer.refresh() is None or recognizer.window_region != old_region:
            raise RuntimeError('WeChat window changed while generating the reply; stopped before sending.')
        fresh = recognizer.window_image
        x1, x2 = chat_left + 8, min(image.shape[1], chat_left + 320)
        a, b = image[35:80, x1:x2], fresh[35:80, x1:x2]
        if a.shape != b.shape or a.size == 0 or np.mean(np.max(cv2.absdiff(a, b), axis=2) > 20) > .001:
            raise RuntimeError('Conversation header changed while generating the reply; stopped before sending.')
        from main import send_text_from_monitor
        print('Pasting and sending the model reply...', flush=True)
        if not send_text_from_monitor(text=reply, monitor_index=args.monitor, debug_send=args.debug):
            raise RuntimeError('Reply generation succeeded but input/send recognition failed; inspect model_reply.txt.')
        history.append_turn(text, reply)
        print(f'Context saved: {len(history.messages) // 2} turns.', flush=True)
        print('Reply pasted and send button clicked.')


def watch_conversation(args, recognizer, initial_image, initial_region, chat_left, output, config):
    tracker = TurnTracker()
    output.mkdir(parents=True, exist_ok=True)
    image = initial_image
    region = dict(initial_region)
    x1, x2 = chat_left + 8, min(image.shape[1], chat_left + 320)
    header = image[35:80, x1:x2].copy()
    print(f'Continuous replies enabled. Poll interval: {args.poll_interval:g}s. Ctrl+C to stop.', flush=True)
    while True:
        fresh_header = image[35:80, x1:x2]
        if (region != initial_region or header.shape != fresh_header.shape or header.size == 0
                or np.mean(np.max(cv2.absdiff(header, fresh_header), axis=2) > 20) > .001):
            raise RuntimeError('Conversation/window changed; continuous replies stopped.')
        input_top = args.input_top if args.input_top is not None else detect_input_top(image, chat_left)
        incoming = detect_latest_incoming(image, chat_left, input_top)
        outgoing = detect_latest_outgoing(image, chat_left, input_top)
        if incoming is not None:
            is_last = outgoing is None or incoming.y + incoming.h > outgoing.y + outgoing.h
            fingerprint = bubble_fingerprint(image, incoming)
            if tracker.is_new(fingerprint, is_last):
                # Require a stable second observation to avoid clicking a bubble
                # while new messages or automatic scrolling are still moving it.
                time.sleep(.3)
                if recognizer.refresh() is None:
                    raise RuntimeError('WeChat window not found; continuous replies stopped.')
                stable = recognizer.window_image
                candidate = detect_latest_incoming(stable, chat_left, args.input_top)
                if (recognizer.window_region == region and candidate is not None
                        and bubble_fingerprint(stable, candidate) == fingerprint):
                    latest_out = detect_latest_outgoing(stable, chat_left,
                        args.input_top if args.input_top is not None else detect_input_top(stable, chat_left))
                    stable_header = stable[35:80, x1:x2]
                    if (stable_header.shape != header.shape or
                            np.mean(np.max(cv2.absdiff(header, stable_header), axis=2) > 20) > .001):
                        raise RuntimeError('Conversation changed; continuous replies stopped.')
                    if latest_out is None or candidate.y + candidate.h > latest_out.y + latest_out.h:
                        save_preview(stable, candidate, output)
                        reply_to_bubble(args, stable, region, chat_left, candidate, output, config, recognizer)
                        tracker.mark_replied(fingerprint)
                        print('Waiting for the next incoming message...', flush=True)
        time.sleep(args.poll_interval)
        if recognizer.refresh() is None:
            raise RuntimeError('WeChat window not found; continuous replies stopped.')
        image, region = recognizer.window_image, dict(recognizer.window_region)


def cli():
    parser = argparse.ArgumentParser(description='Copy the latest visible incoming WeChat message.')
    parser.add_argument('--friend', help='Friend search keyword')
    parser.add_argument('--monitor', type=int, default=2)
    parser.add_argument('--taskbar-monitor', type=int, default=1)
    parser.add_argument('--title-keyword')
    parser.add_argument('--result-offset-x', type=int, default=0)
    parser.add_argument('--result-offset-y', type=int, default=78)
    parser.add_argument('--wait', type=float, default=.8)
    parser.add_argument('--current-chat', action='store_true', help='Skip friend search')
    parser.add_argument('--detect-only', action='store_true', help='Locate the bubble without copying')
    parser.add_argument('--image', help='Offline screenshot; never clicks or accesses the clipboard')
    parser.add_argument('--chat-left', type=int, help='Chat panel left boundary in screenshot pixels')
    parser.add_argument('--input-top', type=int, help='Editor top boundary in screenshot pixels')
    parser.add_argument('--output', default=str(Path(__file__).parent / 'output'))
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--reply', action='store_true', help='Generate a model reply and send it once')
    parser.add_argument('--watch', action='store_true', help='Reply to new incoming messages until Ctrl+C or window loss')
    parser.add_argument('--poll-interval', type=float, default=2, help='Seconds between checks in watch mode')
    parser.add_argument('--preview-reply', action='store_true', help='With --reply, generate without pasting/sending')
    parser.add_argument('--config', default=str(Path(__file__).parent / 'config.local.json'))
    parser.add_argument('--model', help='Override configured model ID')
    parser.add_argument('--ocr-timeout', type=float, default=45,
                        help='Maximum seconds for OCR imports, model loading, and recognition')
    try:
        args = parser.parse_args()
        if args.watch:
            args.reply = True
            if args.preview_reply:
                raise ValueError('--watch cannot be combined with --preview-reply.')
        if args.poll_interval <= 0:
            raise ValueError('Poll interval must be greater than zero.')
        if args.ocr_timeout <= 0:
            raise ValueError('OCR timeout must be greater than zero.')
        if args.preview_reply and not args.reply:
            raise ValueError('--preview-reply requires --reply.')
        run(args)
    except (RuntimeError, ValueError) as error:
        parser.exit(1, f'Error: {error}\n')
    except KeyboardInterrupt:
        print('\nStopped by Ctrl+C.', flush=True)


if __name__ == '__main__':
    cli()
