# WeChat Latest Incoming Message Reader

An independent tool inside this repository that reuses `main.search_friend_and_click_first_result()` to activate WeChat when necessary and open a friend's conversation. It finds the latest **currently visible incoming gray message bubble**, opens its context menu, recognizes the Copy item with CnOCR, and reads the clipboard.

By default it only copies a message. With `--reply`, it calls the configured model and reuses `main.send_text_from_monitor()` to paste and send one reply. It does not scroll to the end of the conversation, verify the searched friend's identity, transcribe voice messages, or extract text from pictures. Friend selection retains the existing sender's fixed-offset behavior.

## Generate and send a model reply

`config.local.json` holds the local API base, key, model, and timeout. This file is ignored by Git. The shareable `config.example.json` contains no key. Environment variables `WECHAT_LLM_BASE_URL`, `WECHAT_LLM_API_KEY`, and `WECHAT_LLM_MODEL` can override configuration; `--model` takes precedence for the model ID. The default is `qwen3.8-max`.

Generate and send one reply in the currently open conversation:

```powershell
python -m wechat_message_reader.reader --current-chat --monitor 2 --ocr-timeout 120 --reply
```

Search a friend, copy the latest visible incoming bubble, and reply once:

```powershell
python -m wechat_message_reader.reader --friend "Your friend name" --monitor 2 --ocr-timeout 120 --reply
```

Generate a reply without pasting or sending:

```powershell
python -m wechat_message_reader.reader --current-chat --monitor 2 --ocr-timeout 120 --reply --preview-reply
```

The copied message is sent to the configured model API when `--reply` is enabled. The current message, all saved conversation turns, and the configured system prompt are sent; screenshots are not uploaded. The reply is saved to `output/model_reply.txt`. No tools are offered to the model, and its reply is used only as text. Empty, truncated, malformed, or failed responses stop the workflow. Keep the target conversation open throughout the call. A window/header check runs before sending, but this is a screenshot-based guard, not identity verification or delivery confirmation. Each normal run handles one message. Use --watch to wait for subsequent replies.

HTTP requests use the standard library, so no additional API client dependency is required. Model IDs and API format are documented in [Qwen3.8-Max](https://www.alibabacloud.com/help/en/model-studio/qwen3-8-max) and [Model Studio Chat Completions](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions).

## Run from the repository root

### Graphical controls

Double-click `wechat_message_reader/start_gui.cmd`, or run:

```powershell
python -m wechat_message_reader.gui
```

Choose continuous reply, one reply, model preview, or detection only. Configure the friend/current chat, monitor, taskbar monitor, polling interval, OCR timeout, search delay, result offsets, model, API address/key/timeout, and reply prompt. Click Start to launch the existing reader and see its live output. Parameters are locked while running. Stop ends the reader and its OCR subprocess; closing the window also stops the running job. It cannot undo a message already sent, and forced stopping during a clipboard operation can leave the temporary clipboard marker behind.

The API key is masked and saved only in the Git-ignored `config.local.json`. It is passed to the child through its environment rather than command-line arguments. Conversation controls currently reset to their defaults when the GUI is reopened; model API settings and the prompt are saved when starting.

Use the existing virtual environment and dependencies from the root `requirements.txt`:

```powershell
cd E:\code\opencvTest
.\.venv\Scripts\python.exe -m wechat_message_reader.reader --friend "Your friend name" --monitor 2
```

The copied text stays in the clipboard and is saved as UTF-8 to `wechat_message_reader/output/latest_message.txt`. The preview `latest_incoming.png` marks the selected bubble; `copy_menu.png` shows the region inspected for Copy. A failed attempt does not overwrite the previous text file, so an old file is not evidence that the new attempt succeeded.

To use the conversation that is already open:

```powershell
.\.venv\Scripts\python.exe -m wechat_message_reader.reader --current-chat --monitor 2
```

To check detection before attempting Copy:

```powershell
.\.venv\Scripts\python.exe -m wechat_message_reader.reader --current-chat --monitor 2 --detect-only
```

`--detect-only` prevents message/menu clicks and clipboard access after locating the conversation. When combined with `--friend`, the existing search workflow still clicks and pastes the friend keyword. Use `--current-chat` with it to skip that workflow.

## Offline screenshot inspection

```powershell
.\.venv\Scripts\python.exe -m wechat_message_reader.reader --image "C:\path\to\screenshot.png"
```

Offline mode never clicks or accesses the clipboard. For a full desktop screenshot or a different layout, supply the chat panel's left boundary and editor's top boundary in screenshot pixels:

```powershell
.\.venv\Scripts\python.exe -m wechat_message_reader.reader --image "C:\path\to\screenshot.png" --chat-left 319 --input-top 483
```

## Configuration

| Option | Default | Meaning |
| --- | --- | --- |
| `--monitor` | `2` | Monitor containing WeChat |
| `--taskbar-monitor` | `1` | Monitor searched for the WeChat taskbar icon |
| `--friend` | None | Friend search keyword; required unless using current-chat or offline mode |
| `--result-offset-x` / `--result-offset-y` | `0` / `78` | First search result offset from the search-box center |
| `--wait` | `0.8` | Seconds to wait after pasting the search keyword |
| `--title-keyword` | None | Optional window-title filter |
| `--chat-left` | Automatic | Chat panel boundary relative to the screenshot/window |
| `--input-top` | Automatic | Editor boundary relative to the screenshot/window |
| `--output` | Tool's `output` directory | Preview and copied-text output directory |
| `--debug` | Off | Enable existing window/search debug output |

Keep WeChat visible and avoid moving the mouse or changing the clipboard while a copy attempt runs. The tool checks `cnocr` and `onnxruntime` before opening the menu. CnOCR runs in a separate process with progress messages and a default 45-second deadline, covering imports, model downloads, and inference. First use may require a model download. Use `--ocr-timeout 120` to allow more time. On timeout, the worker is stopped and the copy attempt reports failure.

If `onnxruntime` is missing, install it in the same environment:

```powershell
.\.venv\Scripts\python.exe -m pip install onnxruntime "rapidocr==3.9.1"
```

The repository pins RapidOCR 3.9.1 because CnOCR 2.3.3 / CnSTD 1.2.8 import `resolve_model_key`, an API absent from the installed RapidOCR 3.10.0. Model downloading and recognition still need validation on the live installation after these dependencies are installed.

## Recognition and failure behavior

The message detector searches low-saturation light-gray regions near the incoming-message column, checks geometry and dark content, and selects the lowest bubble above the editor. It estimates the editor boundary from long horizontal lines, with a proportional fallback. Default geometry targets the light WeChat layout shown in the reference screenshot; dark themes and different scaling may require tuning.

The Copy label is recognized exactly in Chinese (simplified/traditional), English, or Japanese. Other labels are not clicked. This is an initial screenshot-based implementation: unusual gray media bubbles can be selected, and an unavailable Copy item is reported as a failure. It cannot skip an unsupported latest message and silently claim an earlier one is the latest.

A unique clipboard marker distinguishes fresh Copy results from stale clipboard text, even if the copied message equals the previous clipboard text. If copying fails and the marker is still present, the prior text is restored. Clipboard formats other than plain text are not preserved. Successful clipboard copying proves text was obtained, not that friend selection or message interpretation was semantically correct.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s wechat_message_reader -p "test_*.py"
```

The tests cover incoming/outgoing selection, editor exclusion, an empty scene, and menu label/confidence filtering. Live context-menu copying must be checked on the actual WeChat installation; offline tests do not prove the menu's behavior there.


## Continuous replies

```powershell
python -m wechat_message_reader.reader --current-chat --monitor 2 --ocr-timeout 120 --watch
```

Or use `--friend "Your friend name"` instead of `--current-chat` to search once at startup. `--watch` enables model replies automatically. Change polling with `--poll-interval 2` (default: two seconds). Stop with Ctrl+C. Losing the visible WeChat window, changing conversations, or a copy/API/send failure stops the loop. Preview and offline modes cannot be combined with watch.

At startup, the tool replies if the latest visible recognized text bubble is incoming; otherwise it waits. It compares incoming and outgoing bubble positions and remembers the last replied bubble's text-pixel fingerprint, independent of vertical position. Repeated unchanged frames do not trigger model calls. After observing our outgoing turn, the same incoming text can trigger a reply on a later turn. A stable second screenshot is required before copying.

This is screenshot-based monitoring, not a WeChat message-ID subscription. Keep the chat at the latest messages without manual scrolling. Rapid identical messages arriving before an outgoing turn is observed may be indistinguishable; unsupported media or several messages between checks can be missed. Only the latest visible supported incoming bubble is processed. State is kept only while the process runs; restarting can reply to a still-visible incoming message again. Each model call receives the incoming message, system prompt, and all saved conversation turns. No actual continuous conversation was sent during automated verification.


## Conversation context

Successful send attempts append the copied incoming text as `user` and the model reply as `assistant` to `output/chat_history.json`. Each following API call includes the entire saved history in order. The file is loaded on startup, so context survives stopping and reopening the app. No truncation or summarization is applied; API context limits can eventually cause a request to fail, at which point clear the history. Preview-only replies do not update the conversation history.

The first version uses one shared history file. Clear it when switching friends to avoid mixing conversations. It records exchanges handled by this tool from now on; it does not import old WeChat messages or reconstruct previous tool runs. The file is inside the Git-ignored output directory.

The GUI's **Clear chat history** button writes an empty history. If a job is running, it stops that job first, clears the history after exit, and leaves it stopped. Click Start to begin again. This clears model context, not WeChat's own chat messages, log output, screenshots, or the latest reply text file.
