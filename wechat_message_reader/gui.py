"""Tkinter controls: python -m wechat_message_reader.gui."""
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

from .llm import DEFAULT_BASE, DEFAULT_MODEL, DEFAULT_PROMPT

FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parent
CONFIG = FOLDER / 'config.local.json'
MODE_LABELS = {'持续回复': 'watch', '回复一次': 'once', '只生成回复': 'preview', '仅识别消息': 'detect'}


def build_command(values):
    command = [sys.executable, '-u', '-m', 'wechat_message_reader.reader']
    mode = values['mode']
    if mode not in {'watch', 'once', 'preview', 'detect'}:
        raise ValueError('无效的运行模式')
    if values['current_chat']:
        command.append('--current-chat')
    elif str(values['friend']).strip():
        command += ['--friend', str(values['friend']).strip()]
    else:
        raise ValueError('请输入好友关键词，或勾选使用当前聊天')
    for field in ('monitor', 'taskbar_monitor', 'result_offset_x', 'result_offset_y'):
        value = int(values[field])
        if field in ('monitor', 'taskbar_monitor') and value < 0:
            raise ValueError('屏幕编号不能为负数')
        command += ['--' + field.replace('_', '-'), str(value)]
    for field in ('poll_interval', 'ocr_timeout', 'wait'):
        value = float(values[field])
        if not math.isfinite(value) or value <= 0:
            raise ValueError('检查间隔和等待/超时时间必须是大于零的数')
        command += ['--' + field.replace('_', '-'), str(value)]
    if values.get('title_keyword', '').strip():
        command += ['--title-keyword', values['title_keyword'].strip()]
    if values.get('model', '').strip():
        command += ['--model', values['model'].strip()]
    if values.get('debug'):
        command.append('--debug')
    command += {'watch': ['--watch'], 'once': ['--reply'],
                'preview': ['--reply', '--preview-reply'], 'detect': ['--detect-only']}[mode]
    return command


class App:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.events = queue.Queue()
        self.closing = False
        self.clear_pending = False
        root.title('微信自动回复')
        root.geometry('860x760')
        config = {}
        if CONFIG.exists():
            try:
                config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
            except (ValueError, OSError):
                pass
        self.config = config
        defaults = dict(friend='', monitor='2', taskbar_monitor='1', poll_interval='2',
                        ocr_timeout='120', wait='0.8', result_offset_x='0', result_offset_y='78',
                        model=config.get('model', DEFAULT_MODEL), title_keyword='',
                        api_base=config.get('api_base', DEFAULT_BASE),
                        api_key=os.environ.get('WECHAT_LLM_API_KEY', config.get('api_key', '')),
                        api_timeout=str(config.get('timeout', 60)))
        self.vars = {k: tk.StringVar(value=v) for k, v in defaults.items()}
        self.current_chat = tk.BooleanVar(value=True)
        self.debug = tk.BooleanVar(value=False)
        self.mode = tk.StringVar(value='持续回复')
        self.status = tk.StringVar(value='已停止')
        frame = ttk.Frame(root, padding=12)
        frame.pack(fill='both', expand=True)
        settings = ttk.LabelFrame(frame, text='运行设置', padding=10)
        settings.pack(fill='x')
        ttk.Label(settings, text='运行模式').grid(row=0, column=0, sticky='w')
        self.mode_box = ttk.Combobox(settings, textvariable=self.mode,
                                     values=list(MODE_LABELS), state='readonly', width=18)
        self.mode_box.grid(row=0, column=1, sticky='ew', padx=6, pady=4)
        self.current_box = ttk.Checkbutton(settings, text='使用当前聊天（跳过搜索好友）', variable=self.current_chat)
        self.current_box.grid(row=0, column=2, columnspan=2, sticky='w')
        fields = [('好友关键词', 'friend'), ('微信所在屏幕', 'monitor'),
                  ('任务栏所在屏幕', 'taskbar_monitor'), ('检查间隔（秒）', 'poll_interval'),
                  ('OCR 超时（秒）', 'ocr_timeout'), ('搜索等待（秒）', 'wait'),
                  ('结果横向偏移', 'result_offset_x'), ('结果纵向偏移', 'result_offset_y'),
                  ('模型名称', 'model'), ('窗口标题关键词', 'title_keyword')]
        self.inputs = []
        for i, (label, name) in enumerate(fields):
            row, col = i // 2 + 1, (i % 2) * 2
            ttk.Label(settings, text=label).grid(row=row, column=col, sticky='w', pady=4)
            widget = ttk.Entry(settings, textvariable=self.vars[name], width=24)
            widget.grid(row=row, column=col + 1, sticky='ew', padx=6, pady=4)
            self.inputs.append(widget)
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)
        api = ttk.LabelFrame(frame, text='模型接口（保存在本地，不提交 Git）', padding=10)
        api.pack(fill='x', pady=8)
        for row, (label, name) in enumerate([('接口地址', 'api_base'), ('API Key', 'api_key'), ('API 超时（秒）', 'api_timeout')]):
            ttk.Label(api, text=label).grid(row=row, column=0, sticky='w', pady=3)
            entry = ttk.Entry(api, textvariable=self.vars[name], show='*' if name == 'api_key' else '')
            entry.grid(row=row, column=1, sticky='ew', padx=6)
            self.inputs.append(entry)
        api.columnconfigure(1, weight=1)
        ttk.Label(api, text='回复提示词').grid(row=3, column=0, sticky='nw', pady=3)
        self.prompt = scrolledtext.ScrolledText(api, height=3, wrap='word')
        self.prompt.insert('1.0', config.get('system_prompt', DEFAULT_PROMPT))
        self.prompt.grid(row=3, column=1, sticky='ew', padx=6)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=4)
        self.start_button = ttk.Button(buttons, text='启动', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='停止', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        self.clear_button = ttk.Button(buttons, text='清除聊天记录', command=self.clear_chat_history)
        self.clear_button.pack(side='left', padx=8)
        ttk.Label(buttons, textvariable=self.status).pack(side='left', padx=8)
        ttk.Checkbutton(buttons, text='保存识别调试图', variable=self.debug).pack(side='right')
        ttk.Label(frame, text='保持目标聊天可见。持续回复会自动发送；“只生成回复”可用于先检查模型结果。').pack(anchor='w', pady=4)
        self.log = scrolledtext.ScrolledText(frame, height=12, wrap='word', state='disabled')
        self.log.pack(fill='both', expand=True)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def write(self, text):
        # Never display the configured key even if a dependency prints it.
        key = self.vars['api_key'].get()
        if key:
            text = text.replace(key, '[API KEY]')
        self.log.configure(state='normal')
        self.log.insert('end', text.rstrip() + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def busy(self, running):
        self.start_button.configure(state='disabled' if running else 'normal')
        self.stop_button.configure(state='normal' if running else 'disabled')
        for widget in self.inputs:
            widget.configure(state='disabled' if running else 'normal')
        self.mode_box.configure(state='disabled' if running else 'readonly')
        self.current_box.configure(state='disabled' if running else 'normal')
        self.prompt.configure(state='disabled' if running else 'normal')

    def start(self):
        if self.process is not None:
            return
        try:
            values = {k: var.get() for k, var in self.vars.items()}
            values.update(mode=MODE_LABELS[self.mode.get()], current_chat=self.current_chat.get(), debug=self.debug.get())
            command = build_command(values)
            timeout = float(values['api_timeout'])
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError('API 超时必须大于零')
            from urllib.parse import urlparse
            if urlparse(values['api_base']).scheme != 'https':
                raise ValueError('接口地址必须以 https:// 开头')
            if values['mode'] != 'detect' and not values['api_key'].strip():
                raise ValueError('请输入 API Key')
            config = dict(self.config, api_base=values['api_base'].strip(), api_key=values['api_key'].strip(),
                          model=values['model'].strip(), timeout=timeout,
                          system_prompt=self.prompt.get('1.0', 'end').strip() or DEFAULT_PROMPT)
            CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
            self.config = config
            env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
            env.update(WECHAT_LLM_API_KEY=config['api_key'], WECHAT_LLM_BASE_URL=config['api_base'], WECHAT_LLM_MODEL=config['model'])
            self.process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.busy(True)
            self.status.set('运行中')
            self.write('已启动：' + self.mode.get())
            threading.Thread(target=self.read_output, args=(self.process,), daemon=True).start()
        except (ValueError, OSError) as error:
            messagebox.showerror('启动失败', str(error))

    def read_output(self, process):
        try:
            for line in process.stdout:
                self.events.put(('log', line))
        finally:
            process.stdout.close()
            self.events.put(('exit', process.wait()))

    def stop(self):
        if self.process is None:
            return
        self.stop_button.configure(state='disabled')
        self.status.set('正在停止')
        threading.Thread(target=self.terminate, args=(self.process,), daemon=True).start()

    def clear_chat_history(self):
        if self.process is not None:
            self.clear_pending = True
            self.clear_button.configure(state='disabled')
            self.write('先停止回复，再清除全部上下文。清除后可重新启动。')
            self.stop()
            return
        try:
            from .history import clear_history
            clear_history()
            self.write('聊天记录已清除，下一次调用将不携带之前的对话。')
        except OSError as error:
            messagebox.showerror('清除失败', str(error))

    def terminate(self, process):
        if process.poll() is not None:
            return
        try:
            if os.name == 'nt':
                # Stop this reader and its OCR child, not unrelated Python jobs.
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            else:
                process.terminate()
            if process.poll() is None:
                process.kill()
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.kill()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'log':
                    self.write(value)
                else:
                    self.process = None
                    self.busy(False)
                    self.status.set('已停止' if value == 0 else '已停止（见日志）')
                    self.write(f'程序已结束，退出码：{value}')
                    if self.clear_pending:
                        self.clear_pending = False
                        self.clear_button.configure(state='normal')
                        self.clear_chat_history()
                    if self.closing:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        if self.process is None:
            self.root.destroy()
        elif not self.closing:
            self.closing = True
            self.stop()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
