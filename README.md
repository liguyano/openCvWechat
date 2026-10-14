# openCvWechat

Windows desktop WeChat automation with OpenCV, CnOCR, and an OpenAI-compatible language-model API.

## Features

- A graphical interface with Start, Stop, parameter controls, and live logs.
- Copy the latest visible incoming text message from WeChat.
- Generate one reply or continuously wait for and reply to new messages.
- Save complete conversation context across restarts, with a Clear chat history button.
- Preview model replies without sending them.
- Inspect all text detected in an image, including confidence and bounding boxes.
- Additional tools for scheduled sending, conversation-list OCR, taskbar recognition, and article image extraction.

## Installation

Use Windows with desktop WeChat installed. Run from the repository root:

```powershell
git clone https://github.com/liguyano/openCvWechat.git
cd openCvWechat
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

OCR currently runs on CPU. First use may download models. RapidOCR is pinned to 3.9.1 for compatibility with CnOCR/CnSTD.

## Start the graphical interface

```powershell
.\.venv\Scripts\python.exe -m wechat_message_reader.gui
```

Or double-click [start_gui.cmd](wechat_message_reader/start_gui.cmd).

1. Choose continuous replies, one reply, model preview, or detection only.
2. Use the currently open chat, or enter a friend-search keyword.
3. Configure the WeChat monitor, taskbar monitor, timing, and search-result offsets.
4. Enter your API URL, API key, model ID, timeout, and reply prompt.
5. Click Start. Click Stop to end the reader and its OCR child process.

Monitor 0 is the combined desktop; 1 is the primary monitor; 2 is the next monitor when available. Defaults assume WeChat on monitor 2 and the taskbar on monitor 1. Keep the target chat visible and at the latest messages.

Continuous mode checks every two seconds by default. It waits when the latest recognized message is outgoing, and calls the model after a new incoming turn. It stops if the window disappears, the conversation changes, or copying, the API, or sending fails.

## API configuration

GUI settings are saved to the Git-ignored `wechat_message_reader/config.local.json`. For command-line setup:

```powershell
Copy-Item wechat_message_reader/config.example.json wechat_message_reader/config.local.json
```

Edit `api_base`, `api_key`, `model`, and `timeout` for your account. The URL must use HTTPS. The default model is `qwen3.8-max`; availability depends on your provider/account. `system_prompt` is optional.

Environment variables `WECHAT_LLM_BASE_URL`, `WECHAT_LLM_API_KEY`, and `WECHAT_LLM_MODEL` override file settings. `--model` overrides the model ID.

API requests contain the current copied message, all saved conversation turns, and the system prompt. Screenshots are not uploaded to the model API.

## Conversation context

Successful send attempts save incoming text and model replies in `wechat_message_reader/output/chat_history.json`. All saved turns are included in the next request, including after restarting. Preview-only replies do not update history. No truncation or summarization is applied; if the provider context limit is reached, clear history.

This version uses one shared history file. **Clear history before switching friends.** Old WeChat messages are not automatically imported.

Click Clear chat history to reset model context. A running worker is stopped first; history is then cleared and the worker remains stopped. This does not delete WeChat messages.

## Command-line examples

Copy from the current chat:

```powershell
.\.venv\Scripts\python.exe -m wechat_message_reader.reader --current-chat --monitor 2 --ocr-timeout 120
```

Generate a reply without sending:

```powershell
.\.venv\Scripts\python.exe -m wechat_message_reader.reader --current-chat --monitor 2 --ocr-timeout 120 --reply --preview-reply
```

Continuously reply:

```powershell
.\.venv\Scripts\python.exe -m wechat_message_reader.reader --current-chat --monitor 2 --ocr-timeout 120 --watch
```

Use `--friend "Your friend name"` instead of `--current-chat` to search once at startup. Press Ctrl+C to stop. Add `--detect-only` for message detection without copying or replying. See `--help` for all options.

## OCR inspection

Place an image at `ocr_accuracy_test/a.png`, then run:

```powershell
.\.venv\Scripts\python.exe ocr_accuracy_test/check_ocr.py
```

The input image is local and not bundled in the repository. Outputs in `ocr_accuracy_test/output/`:

- `recognized.txt`: all recognized text.
- `results.json`: text, confidence, and positions.
- `annotated.png`: detected text regions.
- `report.json`: summary and optional reference comparison.

Provide `--expected path/to/reference.txt` to measure character error rate against a correct transcription. Model confidence is not measured accuracy. The bundled `expected.txt` belongs to an earlier Send-label example; replace it for another image. The default recognizer primarily targets Chinese and English.

## Project layout

| Path | Purpose |
| --- | --- |
| `wechat_message_reader/` | GUI, message copying, model replies, monitoring, and context |
| `ocr_accuracy_test/` | Image OCR inspection |
| `main.py` | Friend navigation, input recognition, and sending |
| `mai_gui.py`, `main_gui.py` | Original manual and scheduled sender interfaces |
| `wechat_search_box_recognizer_click.py` | Window and search-box recognition |
| `send_button.py` | Green send-button recognition |
| `friend_list_ocr.py` | Conversation rows and nickname OCR |
| `taskbar_wechat_clicker.py`, `taskbar_icon_match_clicker.py` | Taskbar recognition |
| `wechatArtical/` | Article capture and image extraction |
| `docs/` | Recognition documentation |

## Tests and limitations

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s wechat_message_reader -p "test_*.py"
```

Tests cover detection, turn tracking, OCR process timeouts, API responses, history persistence, and GUI command construction. They do not prove live WeChat delivery.

Recognition depends on the visible light-theme layout and display scaling. Friend selection clicks a fixed search-result offset rather than verifying identity. The reader handles the latest visible supported gray text bubble; media and rapid bursts may be missed. Identical new messages may be indistinguishable if an outgoing turn was not observed. Duplicate-tracking state resets when the reader restarts.

A successful send-button click does not confirm delivery. Stop cannot undo a sent message, and forced interruption while copying can leave a clipboard marker. Credentials, conversation history, and generated outputs are excluded from Git by the tool directories' ignore rules.

## Documentation

- [Message reader and GUI guide](wechat_message_reader/README.md)
- [OCR inspection guide](ocr_accuracy_test/README.md)
- [Recognition methods](docs/recognition_methods.md)
