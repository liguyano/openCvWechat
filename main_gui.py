#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
main_gui_calendar.py

Tkinter GUI for main.py, with calendar date picker and time dropdowns.

Put these files in the same folder:
    main_gui_calendar.py
    main.py
    wechat_search_box_recognizer_click.py
    send_button.py

Optional dependency for a real calendar popup:
    pip install tkcalendar

If tkcalendar is not installed, this GUI will fall back to a normal YYYY-MM-DD date input box.
"""

import datetime as dt
import queue
import threading
import traceback
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

try:
    from tkcalendar import DateEntry
    HAS_TKCALENDAR = True
except Exception:
    DateEntry = None
    HAS_TKCALENDAR = False

# IMPORTANT:
# Use an alias. Do not write `import main` and then define `def main()`,
# otherwise the function name may shadow the imported module.
import main as sender_module


class ScheduledJob:
    def __init__(self, job_id: int, run_at: dt.datetime, config: dict):
        self.job_id = job_id
        self.run_at = run_at
        self.config = config
        self.after_id = None


class MainGuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("WeChat Message Sender")
        self.root.geometry("900x720")

        self.is_sending = False
        self.jobs: dict[int, ScheduledJob] = {}
        self.next_job_id = 1
        self.log_queue: queue.Queue[str] = queue.Queue()

        self.date_widget = None

        self._build_vars()
        self._build_ui()
        self._poll_log_queue()

    def _build_vars(self):
        now_plus_1 = dt.datetime.now() + dt.timedelta(minutes=1)

        self.friend_keyword_var = tk.StringVar(value="ウィーエト")
        self.message_var = tk.StringVar(value="こんにちは")

        self.monitor_var = tk.IntVar(value=2)
        self.title_keyword_var = tk.StringVar(value="")
        self.result_offset_x_var = tk.IntVar(value=0)
        self.result_offset_y_var = tk.IntVar(value=78)
        self.wait_after_search_paste_var = tk.DoubleVar(value=0.8)
        self.debug_search_var = tk.BooleanVar(value=False)
        self.debug_send_var = tk.BooleanVar(value=True)

        # Date and time picker values
        self.date_var = tk.StringVar(value=now_plus_1.strftime("%Y-%m-%d"))
        self.hour_var = tk.StringVar(value=now_plus_1.strftime("%H"))
        self.minute_var = tk.StringVar(value=now_plus_1.strftime("%M"))
        self.second_var = tk.StringVar(value=now_plus_1.strftime("%S"))

        self.status_var = tk.StringVar(value="Ready")

    def _build_ui(self):
        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.pack(fill=tk.BOTH, expand=True)

        # Send settings
        send_frame = ttk.LabelFrame(root_frame, text="Send settings", padding=10)
        send_frame.pack(fill=tk.X)

        ttk.Label(send_frame, text="Friend keyword:").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(send_frame, textvariable=self.friend_keyword_var, width=42).grid(
            row=0, column=1, sticky=tk.W + tk.E, pady=4
        )

        ttk.Label(send_frame, text="Message:").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(send_frame, textvariable=self.message_var, width=68).grid(
            row=1, column=1, columnspan=5, sticky=tk.W + tk.E, pady=4
        )

        # Date picker + time dropdowns
        ttk.Label(send_frame, text="Schedule date:").grid(row=2, column=0, sticky=tk.W, pady=4)

        if HAS_TKCALENDAR:
            self.date_widget = DateEntry(
                send_frame,
                width=14,
                textvariable=self.date_var,
                date_pattern="yyyy-mm-dd",
                locale="en_US",
            )
            self.date_widget.grid(row=2, column=1, sticky=tk.W, pady=4)
        else:
            self.date_widget = ttk.Entry(send_frame, textvariable=self.date_var, width=16)
            self.date_widget.grid(row=2, column=1, sticky=tk.W, pady=4)
            ttk.Label(
                send_frame,
                text="Install `pip install tkcalendar` for calendar popup",
                foreground="#a06000",
            ).grid(row=2, column=2, columnspan=4, sticky=tk.W, padx=8)

        ttk.Label(send_frame, text="Time:").grid(row=3, column=0, sticky=tk.W, pady=4)

        hour_values = [f"{i:02d}" for i in range(24)]
        minute_values = [f"{i:02d}" for i in range(60)]
        second_values = [f"{i:02d}" for i in range(60)]

        self.hour_combo = ttk.Combobox(
            send_frame,
            textvariable=self.hour_var,
            values=hour_values,
            width=5,
            state="readonly",
        )
        self.hour_combo.grid(row=3, column=1, sticky=tk.W, pady=4)

        ttk.Label(send_frame, text="时").grid(row=3, column=2, sticky=tk.W, padx=(2, 8))

        self.minute_combo = ttk.Combobox(
            send_frame,
            textvariable=self.minute_var,
            values=minute_values,
            width=5,
            state="readonly",
        )
        self.minute_combo.grid(row=3, column=3, sticky=tk.W, pady=4)

        ttk.Label(send_frame, text="分").grid(row=3, column=4, sticky=tk.W, padx=(2, 8))

        self.second_combo = ttk.Combobox(
            send_frame,
            textvariable=self.second_var,
            values=second_values,
            width=5,
            state="readonly",
        )
        self.second_combo.grid(row=3, column=5, sticky=tk.W, pady=4)

        ttk.Label(send_frame, text="秒").grid(row=3, column=6, sticky=tk.W, padx=(2, 8))

        ttk.Label(
            send_frame,
            text="Pick a date, then choose hour/minute/second from dropdowns.",
            foreground="#666666",
        ).grid(row=4, column=1, columnspan=6, sticky=tk.W, pady=(0, 4))

        send_frame.columnconfigure(1, weight=1)

        # Advanced parameters
        params = ttk.LabelFrame(root_frame, text="Parameters", padding=10)
        params.pack(fill=tk.X, pady=10)

        ttk.Label(params, text="monitor:").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(params, from_=0, to=9, textvariable=self.monitor_var, width=10).grid(
            row=0, column=1, sticky=tk.W, pady=4
        )

        ttk.Label(params, text="title_keyword:").grid(row=0, column=2, sticky=tk.W, padx=(20, 0), pady=4)
        ttk.Entry(params, textvariable=self.title_keyword_var, width=22).grid(
            row=0, column=3, sticky=tk.W, pady=4
        )

        ttk.Label(params, text="result_offset_x:").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(
            params,
            from_=-300,
            to=300,
            textvariable=self.result_offset_x_var,
            width=10,
        ).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(params, text="result_offset_y:").grid(row=1, column=2, sticky=tk.W, padx=(20, 0), pady=4)
        ttk.Spinbox(
            params,
            from_=0,
            to=300,
            textvariable=self.result_offset_y_var,
            width=10,
        ).grid(row=1, column=3, sticky=tk.W, pady=4)

        ttk.Label(params, text="wait_after_search_paste:").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(
            params,
            from_=0.1,
            to=10.0,
            increment=0.1,
            textvariable=self.wait_after_search_paste_var,
            width=10,
        ).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Checkbutton(params, text="debug_search", variable=self.debug_search_var).grid(
            row=2, column=2, sticky=tk.W, padx=(20, 0), pady=4
        )
        ttk.Checkbutton(params, text="debug_send", variable=self.debug_send_var).grid(
            row=2, column=3, sticky=tk.W, pady=4
        )

        # Buttons
        button_frame = ttk.Frame(root_frame)
        button_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(button_frame, text="Send now", command=self.send_now).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Add scheduled job", command=self.add_scheduled_job).pack(side=tk.LEFT, padx=8)
        ttk.Button(button_frame, text="Cancel selected job", command=self.cancel_selected_job).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Cancel all jobs", command=self.cancel_all_jobs).pack(side=tk.LEFT, padx=8)
        ttk.Button(button_frame, text="Clear log", command=self.clear_log).pack(side=tk.RIGHT)

        # Status
        status_frame = ttk.Frame(root_frame)
        status_frame.pack(fill=tk.X)

        ttk.Label(status_frame, text="Status:").pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var, foreground="#0066cc").pack(side=tk.LEFT)

        # Scheduled jobs table
        jobs_frame = ttk.LabelFrame(root_frame, text="Scheduled jobs", padding=8)
        jobs_frame.pack(fill=tk.X, pady=(10, 0))

        self.jobs_tree = ttk.Treeview(
            jobs_frame,
            columns=("time", "friend", "message"),
            show="headings",
            height=6,
        )
        self.jobs_tree.heading("time", text="Run at")
        self.jobs_tree.heading("friend", text="Friend keyword")
        self.jobs_tree.heading("message", text="Message")

        self.jobs_tree.column("time", width=180, anchor=tk.W)
        self.jobs_tree.column("friend", width=180, anchor=tk.W)
        self.jobs_tree.column("message", width=460, anchor=tk.W)

        self.jobs_tree.pack(fill=tk.X)

        # Log
        log_frame = ttk.LabelFrame(root_frame, text="Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.log_box = scrolledtext.ScrolledText(log_frame, height=16)
        self.log_box.pack(fill=tk.BOTH, expand=True)

        self.log("GUI started.")
        self.log("Keep WeChat visible on the target monitor before sending or scheduled sending.")
        if HAS_TKCALENDAR:
            self.log("Calendar date picker is enabled by tkcalendar.")
        else:
            self.log("tkcalendar is not installed. Falling back to YYYY-MM-DD date entry.")

    # -----------------------------
    # Config and time parsing
    # -----------------------------
    def get_config(self) -> dict:
        friend_keyword = self.friend_keyword_var.get().strip()
        message = self.message_var.get()

        if not friend_keyword:
            raise ValueError("Friend keyword cannot be empty.")

        if not message:
            raise ValueError("Message cannot be empty.")

        title_keyword = self.title_keyword_var.get().strip() or None

        return {
            "friend_keyword": friend_keyword,
            "text": message,
            "monitor_index": int(self.monitor_var.get()),
            "debug_search": bool(self.debug_search_var.get()),
            "debug_send": bool(self.debug_send_var.get()),
            "title_keyword": title_keyword,
            "result_offset_x": int(self.result_offset_x_var.get()),
            "result_offset_y": int(self.result_offset_y_var.get()),
            "wait_after_search_paste": float(self.wait_after_search_paste_var.get()),
        }

    def get_selected_date(self) -> dt.date:
        if HAS_TKCALENDAR and hasattr(self.date_widget, "get_date"):
            return self.date_widget.get_date()

        raw_date = self.date_var.get().strip()
        try:
            return dt.datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError as e:
            raise ValueError("Date must be in YYYY-MM-DD format.") from e

    def parse_schedule_time(self) -> dt.datetime:
        selected_date = self.get_selected_date()

        try:
            hour = int(self.hour_var.get())
            minute = int(self.minute_var.get())
            second = int(self.second_var.get())
        except ValueError as e:
            raise ValueError("Hour, minute, and second must be valid numbers.") from e

        target = dt.datetime.combine(
            selected_date,
            dt.time(hour=hour, minute=minute, second=second),
        )

        if target <= dt.datetime.now():
            raise ValueError("Schedule time must be later than current time.")

        return target

    # -----------------------------
    # Send actions
    # -----------------------------
    def send_now(self):
        try:
            config = self.get_config()
        except Exception as e:
            messagebox.showerror("Invalid parameters", str(e))
            return

        self.start_send_thread(config, source="Send now")

    def add_scheduled_job(self):
        try:
            config = self.get_config()
            run_at = self.parse_schedule_time()
        except Exception as e:
            messagebox.showerror("Invalid parameters", str(e))
            return

        delay_ms = int((run_at - dt.datetime.now()).total_seconds() * 1000)

        if delay_ms <= 0:
            messagebox.showerror("Invalid parameters", "Schedule time must be later than current time.")
            return

        job_id = self.next_job_id
        self.next_job_id += 1

        job = ScheduledJob(job_id=job_id, run_at=run_at, config=config)
        after_id = self.root.after(delay_ms, lambda jid=job_id: self.run_scheduled_job(jid))
        job.after_id = after_id

        self.jobs[job_id] = job

        self.jobs_tree.insert(
            "",
            tk.END,
            iid=str(job_id),
            values=(
                run_at.strftime("%Y-%m-%d %H:%M:%S"),
                config["friend_keyword"],
                config["text"],
            ),
        )

        self.status_var.set(f"Scheduled job #{job_id}")
        self.log(
            f"Added scheduled job #{job_id}: "
            f"time={run_at.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"friend={config['friend_keyword']}, message={config['text']}"
        )

    def run_scheduled_job(self, job_id: int):
        job = self.jobs.pop(job_id, None)

        if job is None:
            return

        try:
            self.jobs_tree.delete(str(job_id))
        except Exception:
            pass

        self.start_send_thread(job.config, source=f"Scheduled job #{job_id}")

    def start_send_thread(self, config: dict, source: str):
        if self.is_sending:
            messagebox.showwarning("Busy", "A sending task is already running. Please wait.")
            self.log(f"{source} not started because another send task is running.")
            return

        self.is_sending = True
        self.status_var.set(f"{source} running...")
        self.log(f"{source} started: friend={config['friend_keyword']}, message={config['text']}")

        thread = threading.Thread(
            target=self.send_worker,
            args=(config, source),
            daemon=True,
        )
        thread.start()

    def send_worker(self, config: dict, source: str):
        try:
            if not hasattr(sender_module, "send_message_to_fixed_friend"):
                raise AttributeError(
                    "main.py does not have function `send_message_to_fixed_friend`. "
                    "Check that main_gui_calendar.py is in the same folder as the correct main.py."
                )

            ok = sender_module.send_message_to_fixed_friend(**config)

            if ok:
                self.log_queue.put(f"{source} finished successfully.")
                self.root.after(0, lambda: self.finish_send(True, f"{source} finished successfully."))
            else:
                self.log_queue.put(f"{source} failed: send_message_to_fixed_friend returned False.")
                self.root.after(0, lambda: self.finish_send(False, f"{source} failed."))

        except Exception:
            err = traceback.format_exc()
            self.log_queue.put(f"{source} exception:\n{err}")
            self.root.after(0, lambda: self.finish_send(False, f"{source} exception. Check the log."))

    def finish_send(self, ok: bool, message: str):
        self.is_sending = False
        self.status_var.set("Send finished" if ok else "Send failed")

        if ok:
            messagebox.showinfo("Done", message)
        else:
            messagebox.showerror("Failed", message)

    # -----------------------------
    # Job cancellation
    # -----------------------------
    def cancel_selected_job(self):
        selected = self.jobs_tree.selection()

        if not selected:
            self.log("No scheduled job selected.")
            return

        for item_id in selected:
            try:
                job_id = int(item_id)
            except ValueError:
                continue

            job = self.jobs.pop(job_id, None)
            if job is not None and job.after_id is not None:
                try:
                    self.root.after_cancel(job.after_id)
                except Exception:
                    pass

            try:
                self.jobs_tree.delete(item_id)
            except Exception:
                pass

            self.log(f"Cancelled scheduled job #{job_id}.")

        self.status_var.set("Selected scheduled job cancelled")

    def cancel_all_jobs(self):
        if not self.jobs:
            self.log("No scheduled jobs to cancel.")
            return

        for job_id, job in list(self.jobs.items()):
            if job.after_id is not None:
                try:
                    self.root.after_cancel(job.after_id)
                except Exception:
                    pass

        self.jobs.clear()

        for item_id in self.jobs_tree.get_children():
            self.jobs_tree.delete(item_id)

        self.status_var.set("All scheduled jobs cancelled")
        self.log("Cancelled all scheduled jobs.")

    # -----------------------------
    # Log helpers
    # -----------------------------
    def log(self, text: str):
        ts = dt.datetime.now().strftime("%H:%M:%S")
        self.log_box.insert(tk.END, f"[{ts}] {text}\n")
        self.log_box.see(tk.END)

    def _poll_log_queue(self):
        try:
            while True:
                self.log(self.log_queue.get_nowait())
        except queue.Empty:
            pass

        self.root.after(200, self._poll_log_queue)

    def clear_log(self):
        self.log_box.delete("1.0", tk.END)


def run_gui():
    root = tk.Tk()
    MainGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
