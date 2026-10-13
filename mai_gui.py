#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
mai_gui.py

Tkinter 图形界面版：

功能：
    1. 手动发送：选择好友关键词、消息内容，点击“立即发送”；
    2. 定时发送：设置几点发送给谁、发送什么消息；
    3. 可调 main.py 里的主要参数：
        - monitor
        - title_keyword
        - result_offset_x
        - result_offset_y
        - wait_after_search_paste
        - debug_search
        - debug_send

使用前提：
    这个文件要和 main.py、wechat_search_box_recognizer_click.py、send_button.py 放在同一个目录。
"""

import datetime as _dt
import contextlib
import io
import threading
import traceback
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import main as sender_module


class MaiGuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("WeChat Scheduled Sender")
        self.root.geometry("760x620")

        self.scheduled_after_id = None
        self.scheduled_time = None
        self.is_sending = False

        self._build_vars()
        self._build_ui()

    def _build_vars(self):
        now_plus_1 = _dt.datetime.now() + _dt.timedelta(minutes=1)

        self.friend_keyword_var = tk.StringVar(value="ウィーエト")
        self.message_var = tk.StringVar(value="こんにちは")

        self.monitor_var = tk.IntVar(value=2)
        self.title_keyword_var = tk.StringVar(value="")
        self.result_offset_x_var = tk.IntVar(value=0)
        self.result_offset_y_var = tk.IntVar(value=78)
        self.wait_after_search_paste_var = tk.DoubleVar(value=0.8)

        self.debug_search_var = tk.BooleanVar(value=False)
        self.debug_send_var = tk.BooleanVar(value=True)

        # 支持两种格式：
        #   HH:MM
        #   YYYY-MM-DD HH:MM
        self.schedule_time_var = tk.StringVar(value=now_plus_1.strftime("%H:%M"))

        self.status_var = tk.StringVar(value="就绪")

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # 基础发送设置
        basic = ttk.LabelFrame(main, text="发送设置", padding=10)
        basic.pack(fill=tk.X)

        ttk.Label(basic, text="好友关键词：").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(basic, textvariable=self.friend_keyword_var, width=40).grid(
            row=0, column=1, sticky=tk.W + tk.E, pady=4
        )

        ttk.Label(basic, text="消息内容：").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(basic, textvariable=self.message_var, width=55).grid(
            row=1, column=1, columnspan=3, sticky=tk.W + tk.E, pady=4
        )

        ttk.Label(basic, text="定时时间：").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Entry(basic, textvariable=self.schedule_time_var, width=22).grid(
            row=2, column=1, sticky=tk.W, pady=4
        )
        ttk.Label(
            basic,
            text="支持 HH:MM / HH:MM:SS / YYYY-MM-DD HH:MM / YYYY-MM-DD HH:MM:SS",
            foreground="#666666",
        ).grid(row=2, column=2, columnspan=2, sticky=tk.W, padx=8)

        basic.columnconfigure(1, weight=1)

        # 参数设置
        params = ttk.LabelFrame(main, text="参数设置", padding=10)
        params.pack(fill=tk.X, pady=10)

        ttk.Label(params, text="monitor：").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(params, from_=0, to=9, textvariable=self.monitor_var, width=10).grid(
            row=0, column=1, sticky=tk.W, pady=4
        )

        ttk.Label(params, text="title_keyword：").grid(row=0, column=2, sticky=tk.W, padx=(20, 0), pady=4)
        ttk.Entry(params, textvariable=self.title_keyword_var, width=20).grid(
            row=0, column=3, sticky=tk.W, pady=4
        )

        ttk.Label(params, text="result_offset_x：").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(
            params,
            from_=-300,
            to=300,
            textvariable=self.result_offset_x_var,
            width=10,
        ).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(params, text="result_offset_y：").grid(row=1, column=2, sticky=tk.W, padx=(20, 0), pady=4)
        ttk.Spinbox(
            params,
            from_=0,
            to=300,
            textvariable=self.result_offset_y_var,
            width=10,
        ).grid(row=1, column=3, sticky=tk.W, pady=4)

        ttk.Label(params, text="搜索后等待秒数：").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(
            params,
            from_=0.1,
            to=10.0,
            increment=0.1,
            textvariable=self.wait_after_search_paste_var,
            width=10,
        ).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Checkbutton(
            params,
            text="debug_search",
            variable=self.debug_search_var,
        ).grid(row=2, column=2, sticky=tk.W, padx=(20, 0), pady=4)

        ttk.Checkbutton(
            params,
            text="debug_send",
            variable=self.debug_send_var,
        ).grid(row=2, column=3, sticky=tk.W, pady=4)

        # 按钮区
        buttons = ttk.Frame(main)
        buttons.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(buttons, text="立即发送", command=self.send_now).pack(side=tk.LEFT)
        ttk.Button(buttons, text="设置定时发送", command=self.schedule_send).pack(side=tk.LEFT, padx=8)
        ttk.Button(buttons, text="取消定时", command=self.cancel_schedule).pack(side=tk.LEFT)
        ttk.Button(buttons, text="清空日志", command=self.clear_log).pack(side=tk.RIGHT)

        # 状态
        status_frame = ttk.Frame(main)
        status_frame.pack(fill=tk.X)

        ttk.Label(status_frame, text="状态：").pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var, foreground="#0066cc").pack(side=tk.LEFT)

        # 日志
        log_frame = ttk.LabelFrame(main, text="日志", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.log_box = scrolledtext.ScrolledText(log_frame, height=18)
        self.log_box.pack(fill=tk.BOTH, expand=True)

        self.log("程序已启动。")
        self.log("提醒：定时发送前，请保持微信窗口在目标屏幕上可见，不能被遮挡。")

    def get_config(self):
        friend_keyword = self.friend_keyword_var.get().strip()
        message = self.message_var.get()

        if not friend_keyword:
            raise ValueError("好友关键词不能为空")

        if not message:
            raise ValueError("消息内容不能为空")

        title_keyword = self.title_keyword_var.get().strip() or None

        return {
            "friend_keyword": friend_keyword,
            "text": message,
            "monitor_index": int(self.monitor_var.get()),
            "title_keyword": title_keyword,
            "debug_search": bool(self.debug_search_var.get()),
            "debug_send": bool(self.debug_send_var.get()),
            "result_offset_x": int(self.result_offset_x_var.get()),
            "result_offset_y": int(self.result_offset_y_var.get()),
            "wait_after_search_paste": float(self.wait_after_search_paste_var.get()),
        }

    def parse_schedule_time(self) -> _dt.datetime:
        raw = self.schedule_time_var.get().strip()

        if not raw:
            raise ValueError("定时时间不能为空")

        now = _dt.datetime.now()

        formats = [
            "%H:%M",
            "%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
        ]

        last_error = None

        for fmt in formats:
            try:
                parsed = _dt.datetime.strptime(raw, fmt)

                if fmt in {"%H:%M", "%H:%M:%S"}:
                    target = now.replace(
                        hour=parsed.hour,
                        minute=parsed.minute,
                        second=parsed.second,
                        microsecond=0,
                    )

                    # 如果今天这个时间已经过了，就默认排到明天
                    if target <= now:
                        target += _dt.timedelta(days=1)

                    return target

                if parsed <= now:
                    raise ValueError("定时时间必须晚于当前时间")

                return parsed

            except ValueError as e:
                last_error = e

        raise ValueError(
            "时间格式不正确。请使用 HH:MM、HH:MM:SS、YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS"
        ) from last_error

    def send_now(self):
        try:
            config = self.get_config()
        except Exception as e:
            messagebox.showerror("参数错误", str(e))
            return

        self._start_send_thread(config=config, source="立即发送")

    def schedule_send(self):
        try:
            config = self.get_config()
            target = self.parse_schedule_time()
        except Exception as e:
            messagebox.showerror("参数错误", str(e))
            return

        self.cancel_schedule(silent=True)

        delay_ms = int((target - _dt.datetime.now()).total_seconds() * 1000)

        if delay_ms <= 0:
            messagebox.showerror("参数错误", "定时时间必须晚于当前时间")
            return

        self.scheduled_time = target
        self.scheduled_after_id = self.root.after(
            delay_ms,
            lambda: self._start_send_thread(config=config, source="定时发送"),
        )

        self.status_var.set(f"已定时：{target.strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(
            f"已设置定时发送：{target.strftime('%Y-%m-%d %H:%M:%S')}，"
            f"好友={config['friend_keyword']}，消息={config['text']}"
        )

    def cancel_schedule(self, silent=False):
        if self.scheduled_after_id is not None:
            try:
                self.root.after_cancel(self.scheduled_after_id)
            except Exception:
                pass

            self.scheduled_after_id = None
            self.scheduled_time = None
            self.status_var.set("已取消定时")
            self.log("已取消定时发送。")
        elif not silent:
            self.log("当前没有待执行的定时任务。")

    def _start_send_thread(self, config: dict, source: str):
        if self.is_sending:
            messagebox.showwarning("正在发送", "当前已经有发送任务在执行，请稍后再试。")
            return

        self.is_sending = True
        self.status_var.set(f"{source}执行中...")
        self.log(f"{source}开始：好友={config['friend_keyword']}，消息={config['text']}")

        thread = threading.Thread(
            target=self._send_worker,
            args=(config, source),
            daemon=True,
        )
        thread.start()

    def _send_worker(self, config: dict, source: str):
        try:
            class GuiLogWriter(io.TextIOBase):
                def write(inner, text):
                    text = text.rstrip("\n")
                    if text:
                        self.root.after(0, lambda value=text: self.log(value))
                    return len(text)

                def flush(inner):
                    return None

            with contextlib.redirect_stdout(GuiLogWriter()), contextlib.redirect_stderr(GuiLogWriter()):
                ok = sender_module.send_message_to_fixed_friend(**config)

            if ok:
                self.root.after(0, lambda: self._send_finished(True, f"{source}完成。"))
            else:
                self.root.after(0, lambda: self._send_finished(False, f"{source}失败：send_message_to_fixed_friend 返回 False。"))

        except Exception:
            err = traceback.format_exc()
            self.root.after(0, lambda: self._send_finished(False, f"{source}异常：\n{err}"))

    def _send_finished(self, ok: bool, message: str):
        self.is_sending = False
        self.status_var.set("发送完成" if ok else "发送失败")
        self.log(message)

        if ok:
            messagebox.showinfo("完成", "发送任务已完成")
        else:
            messagebox.showerror("失败", message)

    def log(self, text: str):
        ts = _dt.datetime.now().strftime("%H:%M:%S")
        self.log_box.insert(tk.END, f"[{ts}] {text}\n")
        self.log_box.see(tk.END)

    def clear_log(self):
        self.log_box.delete("1.0", tk.END)


def main():
    root = tk.Tk()
    app = MaiGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
