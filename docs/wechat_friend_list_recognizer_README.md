# WeChat Friend List Recognizer

`wechat_friend_list_recognizer.py` is a Windows-oriented Python utility for locating a visible WeChat desktop window, detecting the conversation list rows, cropping each nickname area, running OCR, and returning the row positions as Python objects.

The main public interface is the `WeChatFriendListRecognizer` class. After calling `refresh()`, the latest recognition output can be read from the `results` property.

## Features

- Finds a visible WeChat desktop window on a selected monitor.
- Detects conversation/friend rows from the left-side conversation list.
- Crops the nickname area of each row and runs OCR.
- Returns each row as a `FriendPosition` object.
- Keeps row positions even when OCR confidence is low.
- Stores the latest recognition results in `recognizer.results`.
- Supports debug image output for troubleshooting.

## Requirements

This script is designed for Windows because it uses Windows API calls to enumerate visible windows.

Install the Python dependencies:

```bash
pip install opencv-python numpy mss cnocr
```

The script currently initializes OCR through `CnOCR`. Some environments may also install OCR-related dependencies such as `onnxruntime` automatically.

## Basic Usage

```python
from wechat_friend_list_recognizer import WeChatFriendListRecognizer

recognizer = WeChatFriendListRecognizer(
    monitor_index=2,
    debug=False,
    row_height=72,
)

recognizer.refresh()

friends = recognizer.results

for friend in friends:
    print(friend.index)
    print(friend.name)
    print(friend.click_x, friend.click_y)
    print(friend.raw_name)
    print(friend.raw_texts)
```

## Public Class API

### `WeChatFriendListRecognizer`

```python
recognizer = WeChatFriendListRecognizer(
    monitor_index=2,
    debug=False,
    row_height=72,
    title_keyword=None,
    score_threshold=0.20,
    keep_all_rows=True,
    debug_dir=None,
)
```

#### Parameters

| Parameter | Type | Default | Description |
|---|---:|---:|---|
| `monitor_index` | `int` | `2` | Monitor index used for WeChat window detection. `0` usually means all monitors, `1` is the primary monitor, and `2` is the secondary monitor. |
| `debug` | `bool` | `False` | If `True`, saves debug screenshots and OCR input images. |
| `row_height` | `int` | `72` | Estimated height of each WeChat conversation row. |
| `title_keyword` | `str | None` | Optional keyword used to filter window titles, such as `微信`. |
| `score_threshold` | `float` | `0.20` | Minimum OCR confidence required for text to be accepted as `name`. |
| `keep_all_rows` | `bool` | `True` | If `True`, row positions are kept even when the nickname OCR result is invalid or low-confidence. |
| `debug_dir` | `str | None` | Optional custom directory for debug output files. |

## Main Methods and Properties

### `refresh()`

Runs the full recognition process again:

1. Enables DPI awareness.
2. Finds the WeChat window.
3. Detects conversation row positions.
4. Crops each nickname region.
5. Runs OCR.
6. Updates `recognizer.results`.

```python
friends = recognizer.refresh()
```

It returns the same list stored in:

```python
recognizer.results
```

### `results`

A property containing the latest recognition result list.

```python
friends = recognizer.results
```

Each item is a `FriendPosition` object.

### `get_result_by_name(name, exact=True)`

Finds one result from the latest `results` list.

```python
friend = recognizer.get_result_by_name("张三")

if friend:
    print(friend.click_x, friend.click_y)
```

For partial matching:

```python
friend = recognizer.get_result_by_name("张", exact=False)
```

### `last_window_img`

The latest captured WeChat window image.

```python
img = recognizer.last_window_img
```

### `last_window_region`

The latest detected WeChat window region in screen coordinates.

```python
region = recognizer.last_window_region
```

Example value:

```python
{
    "left": 2264,
    "top": 231,
    "width": 1093,
    "height": 650,
}
```

### `last_rows`

The latest detected conversation row boxes in WeChat-window-relative coordinates.

```python
rows = recognizer.last_rows
```

Each row is:

```python
(x, y, w, h)
```

## Result Object: `FriendPosition`

Each recognized row is stored as a `FriendPosition` object.

```python
@dataclass
class FriendPosition:
    index: int
    name: str
    x: int
    y: int
    w: int
    h: int
    click_x: int
    click_y: int
    raw_texts: List[Tuple[str, float]]
    raw_name: str
    best_score: float
    is_valid_name: bool
```

### Fields

| Field | Description |
|---|---|
| `index` | Original row index in the detected conversation list. |
| `name` | Cleaned OCR result that passed the confidence threshold. May be empty if OCR confidence is low. |
| `x`, `y`, `w`, `h` | Row box in WeChat-window-relative coordinates. |
| `click_x`, `click_y` | Absolute screen coordinates for clicking the row center. |
| `raw_texts` | Raw OCR text and score pairs. |
| `raw_name` | Cleaned OCR text before confidence filtering. Useful when `name` is empty. |
| `best_score` | Highest OCR confidence score for that row. |
| `is_valid_name` | Whether the final `name` passed validation. |

### Convenience Properties

```python
friend.center
```

Returns:

```python
(click_x, click_y)
```

```python
friend.box
```

Returns:

```python
(x, y, w, h)
```

### Convert to Dictionary

The script does not automatically save JSON anymore. If you need a serializable dictionary, call:

```python
data = friend.to_dict()
```

Example:

```python
friends_as_dicts = [friend.to_dict() for friend in recognizer.results]
```

## Simple Function Interface

A helper function is also available:

```python
from wechat_friend_list_recognizer import get_friend_positions

friends = get_friend_positions(
    monitor_index=2,
    debug=False,
    row_height=72,
    title_keyword=None,
    keep_all_rows=True,
)

for friend in friends:
    print(friend.name, friend.click_x, friend.click_y)
```

This function creates a `WeChatFriendListRecognizer`, calls `refresh()`, and returns `recognizer.results`.

## Command-Line Usage

Run directly:

```bash
python wechat_friend_list_recognizer.py
```

With options:

```bash
python wechat_friend_list_recognizer.py --monitor 2 --debug --row-height 72
```

Filter by window title keyword:

```bash
python wechat_friend_list_recognizer.py --monitor 2 --title-keyword 微信
```

Change OCR confidence threshold:

```bash
python wechat_friend_list_recognizer.py --score-threshold 0.10
```

Drop low-confidence rows instead of keeping all row positions:

```bash
python wechat_friend_list_recognizer.py --drop-invalid
```

## Debug Output

When `debug=True` or `--debug` is used, the script saves intermediate images and text files under the debug directory.

Common debug files include:

| File | Purpose |
|---|---|
| `debug_wechat_window_screenshot.png` | Captured WeChat window screenshot. |
| `debug_friend_rows.png` | Detected conversation rows. |
| `ocr_name_raw_XX.png` | Raw cropped nickname image for row `XX`. |
| `ocr_name_input_XX.png` | Enlarged OCR input image for row `XX`. |
| `ocr_name_result_XX.txt` | Raw OCR output and parsed text for row `XX`. |
| `debug_friend_ocr_result.png` | Final result image with detected rows marked. |

## Important Notes

OCR accuracy may be unstable for WeChat UI screenshots because nickname text is small and may appear on different backgrounds. Selected rows may use white text on a green background, and timestamps may sometimes be included in the crop.

For automation that mainly needs click positions, keep `keep_all_rows=True`. This ensures that all detected row positions are returned even when OCR confidence is low.

When `name` is empty, check these fields:

```python
friend.raw_name
friend.raw_texts
friend.best_score
```

These fields can help you decide whether to trust the OCR output manually or tune `score_threshold`.

## Example: Click a Recognized Friend

This script only returns coordinates. It does not click automatically. You can combine it with another library such as `pyautogui`:

```python
import pyautogui
from wechat_friend_list_recognizer import WeChatFriendListRecognizer

recognizer = WeChatFriendListRecognizer(monitor_index=2)
recognizer.refresh()

friend = recognizer.get_result_by_name("张三")

if friend:
    pyautogui.click(friend.click_x, friend.click_y)
else:
    print("Friend not found")
```

Install `pyautogui` only if you need automatic clicking:

```bash
pip install pyautogui
```

## Example: Use Low-Confidence Raw Results

```python
recognizer = WeChatFriendListRecognizer(
    monitor_index=2,
    score_threshold=0.20,
    keep_all_rows=True,
)

recognizer.refresh()

for friend in recognizer.results:
    if friend.name:
        display_name = friend.name
    else:
        display_name = f"LOW_CONFIDENCE: {friend.raw_name}"

    print(display_name, friend.center, friend.best_score)
```

## Troubleshooting

### Only a few results are returned

Set `keep_all_rows=True`. This is already the default in the class version.

```python
recognizer = WeChatFriendListRecognizer(keep_all_rows=True)
```

If you use the command line, avoid `--drop-invalid` unless you really want to remove low-confidence rows.

### The WeChat window is not found

Check that:

- WeChat is visible and not minimized.
- The correct monitor index is used.
- The window is not completely covered by another window.
- On Windows display scaling, DPI awareness is enabled automatically by the script.

Try:

```bash
python wechat_friend_list_recognizer.py --monitor 1 --debug
python wechat_friend_list_recognizer.py --monitor 2 --debug
```

### OCR result contains timestamp digits

The nickname crop may include part of the timestamp. You can tune the crop area inside `ocr_name_from_row()` or use `raw_name` as a low-confidence hint rather than a final name.
