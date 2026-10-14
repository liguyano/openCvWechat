# Latest Incoming Message Reader

Read the latest incoming message currently visible in a WeChat conversation. Reuse the repository's existing taskbar activation and friend-search function. This tool does not send messages or automatically scroll history.

Detect neutral gray incoming bubbles in the chat panel, exclude outgoing green bubbles and the editor, and choose the lowest candidate. Right-click that candidate and use CnOCR to locate the Copy menu item. Read the resulting clipboard text; report failure when copying is unavailable. Support offline image inspection and a live detection-only mode. Leave existing sender files unchanged.

Implementation plan: add a pure image detector and regression tests; add menu OCR and clipboard verification; add a command-line entry point and English usage guide; verify against synthetic cases and the supplied screenshot without sending or clicking during verification.
