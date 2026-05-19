#!/usr/bin/env python3
"""GUI for video_preview — drag-and-drop video file and configure parameters."""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from tkinterdnd2 import DND_FILES, TkinterDnD

from video_preview import PreviewError, build_output_path, generate_preview


# ── helpers ───────────────────────────────────────────────────────────────────

def clean_dnd_path(raw: str) -> str:
    path = raw.strip()
    if path.startswith("{") and path.endswith("}"):
        path = path[1:-1]
    return path.strip('"').strip("'")


# ── main window ───────────────────────────────────────────────────────────────

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Video Preview Generator")
        self.resizable(True, True)
        self.minsize(520, 480)
        self._build_ui()
        self._log_queue: queue.Queue = queue.Queue()
        self._poll_log()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Drop zone ─────────────────────────────────────────────────────────
        drop_frame = tk.Frame(self, bd=2, relief="groove", bg="#f0f4f8",
                              width=480, height=100)
        drop_frame.pack(fill="x", padx=16, pady=(16, 4))
        drop_frame.pack_propagate(False)

        self._drop_label = tk.Label(
            drop_frame,
            text="拖拽 MP4 视频到这里\n或点击选择文件",
            bg="#f0f4f8", fg="#555", font=("Segoe UI", 11),
            cursor="hand2",
        )
        self._drop_label.place(relx=0.5, rely=0.5, anchor="center")
        self._drop_label.bind("<Button-1>", self._browse_input)
        drop_frame.bind("<Button-1>", self._browse_input)

        for widget in (drop_frame, self._drop_label):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

        # ── Parameters ────────────────────────────────────────────────────────
        param_frame = tk.LabelFrame(self, text="参数设置", padx=10, pady=8,
                                    font=("Segoe UI", 9))
        param_frame.pack(fill="x", padx=16, pady=4)

        self._var_duration     = tk.StringVar(value="30")
        self._var_segments     = tk.StringVar(value="5")
        self._var_start_offset = tk.StringVar(value="0")
        self._var_end_offset   = tk.StringVar(value="0")

        rows = [
            ("预览总时长", self._var_duration,     "秒"),
            ("片段数量",   self._var_segments,     "段"),
            ("跳过片头",   self._var_start_offset, "秒"),
            ("跳过片尾",   self._var_end_offset,   "秒"),
        ]
        for i, (label, var, unit) in enumerate(rows):
            tk.Label(param_frame, text=label, anchor="w",
                     font=("Segoe UI", 9)).grid(row=i, column=0, sticky="w", pady=3)
            tk.Entry(param_frame, textvariable=var, width=10,
                     font=("Segoe UI", 9)).grid(row=i, column=1, sticky="w", padx=(6, 0))
            tk.Label(param_frame, text=unit, fg="#888",
                     font=("Segoe UI", 8)).grid(row=i, column=2, sticky="w", padx=(3, 0))

        # ── Output path ───────────────────────────────────────────────────────
        out_frame = tk.Frame(self)
        out_frame.pack(fill="x", padx=16, pady=4)
        tk.Label(out_frame, text="输出路径", font=("Segoe UI", 9)).pack(side="left")
        self._var_output = tk.StringVar()
        tk.Entry(out_frame, textvariable=self._var_output, width=40,
                 font=("Segoe UI", 9)).pack(side="left", padx=(6, 4))
        tk.Button(out_frame, text="浏览…", command=self._browse_output,
                  font=("Segoe UI", 9)).pack(side="left")

        # ── FFmpeg path ───────────────────────────────────────────────────────
        ff_frame = tk.Frame(self)
        ff_frame.pack(fill="x", padx=16, pady=2)
        tk.Label(ff_frame, text="ffmpeg 路径", font=("Segoe UI", 9)).pack(side="left")
        self._var_ffmpeg = tk.StringVar(value="ffmpeg")
        tk.Entry(ff_frame, textvariable=self._var_ffmpeg, width=38,
                 font=("Segoe UI", 9)).pack(side="left", padx=(6, 4))
        tk.Button(ff_frame, text="浏览…", command=self._browse_ffmpeg,
                  font=("Segoe UI", 9)).pack(side="left")

        # ── Generate button ───────────────────────────────────────────────────
        self._btn_generate = tk.Button(
            self, text="生成预览视频", command=self._generate,
            font=("Segoe UI", 11, "bold"), bg="#2563eb", fg="white",
            activebackground="#1d4ed8", activeforeground="white",
            relief="flat", padx=20, pady=6, cursor="hand2",
        )
        self._btn_generate.pack(pady=(10, 4))

        # ── Progress bar ──────────────────────────────────────────────────────
        self._progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self._progress.pack(fill="x", padx=16, pady=(0, 4))

        # ── Log ───────────────────────────────────────────────────────────────
        log_frame = tk.Frame(self)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self._log = tk.Text(log_frame, height=8, state="disabled",
                            font=("Consolas", 8), bg="#1e1e1e", fg="#d4d4d4",
                            relief="flat", wrap="word")
        scroll = tk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scroll.set)
        self._log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._input_path: str = ""

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_drop(self, event):
        self._set_input(clean_dnd_path(event.data))

    def _browse_input(self, _event=None):
        path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")],
        )
        if path:
            self._set_input(path)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="选择输出路径",
            defaultextension=".mp4",
            filetypes=[("MP4 files", "*.mp4")],
        )
        if path:
            self._var_output.set(path)

    def _browse_ffmpeg(self):
        path = filedialog.askopenfilename(
            title="选择 ffmpeg 可执行文件",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self._var_ffmpeg.set(path)

    def _set_input(self, path: str):
        self._input_path = path
        self._drop_label.config(
            text=f"已选择：{os.path.basename(path)}",
            fg="#1d4ed8", font=("Segoe UI", 10, "bold"),
        )
        if not self._var_output.get():
            self._var_output.set(build_output_path(path, None))

    # ── generation ────────────────────────────────────────────────────────────

    def _generate(self):
        if not self._input_path:
            self._log_write("请先选择或拖入一个视频文件。\n", "warn")
            return
        try:
            duration     = float(self._var_duration.get())
            segments     = int(self._var_segments.get())
            start_offset = float(self._var_start_offset.get())
            end_offset   = float(self._var_end_offset.get())
        except ValueError:
            self._log_write("参数格式错误，请检查输入（必须为数字）。\n", "warn")
            return

        output   = self._var_output.get().strip() or None
        ffmpeg   = self._var_ffmpeg.get().strip() or "ffmpeg"

        self._btn_generate.config(state="disabled")
        self._progress["value"] = 0
        self._log_write("开始生成...\n\n")

        threading.Thread(
            target=self._run_generate,
            args=(self._input_path, duration, segments, output,
                  start_offset, end_offset, ffmpeg),
            daemon=True,
        ).start()

    def _run_generate(self, input_path, duration, segments, output,
                      start_offset, end_offset, ffmpeg):
        def log(msg):
            self._log_queue.put(("info", msg + "\n"))

        def on_progress(pct):
            self._log_queue.put(("progress", pct))

        try:
            generate_preview(
                input_path=input_path,
                duration=duration,
                segments=segments,
                output=output,
                start_offset=start_offset,
                end_offset=end_offset,
                ffmpeg_path=ffmpeg,
                log=log,
                on_progress=on_progress,
            )
            self._log_queue.put(("ok", ""))
        except PreviewError as e:
            self._log_queue.put(("warn", f"错误：{e}\n"))
        except Exception as e:
            self._log_queue.put(("warn", f"未知错误：{e}\n"))
        finally:
            self._log_queue.put(("done", ""))

    # ── log helpers ───────────────────────────────────────────────────────────

    def _poll_log(self):
        try:
            while True:
                kind, text = self._log_queue.get_nowait()
                if kind == "progress":
                    self._progress["value"] = text
                elif kind == "done":
                    self._btn_generate.config(state="normal")
                elif kind == "ok":
                    self._log_write("完成！\n", "ok")
                else:
                    self._log_write(text, kind)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _log_write(self, text: str, kind: str = "info"):
        colors = {"info": "#d4d4d4", "warn": "#f97316", "ok": "#4ade80"}
        self._log.config(state="normal")
        self._log.tag_config(kind, foreground=colors.get(kind, "#d4d4d4"))
        self._log.insert("end", text, kind)
        self._log.see("end")
        self._log.config(state="disabled")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    App().mainloop()
