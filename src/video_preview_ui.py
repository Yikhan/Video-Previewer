#!/usr/bin/env python3
"""GUI for video_preview — drag-and-drop video file and configure parameters."""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from tkinterdnd2 import DND_FILES, TkinterDnD

from ts_convert import ConvertError, convert_ts
from video_preview import PreviewError, build_output_path, find_ffmpeg, generate_preview


# ── helpers ───────────────────────────────────────────────────────────────────

def parse_dnd_paths(raw: str) -> list:
    """Parse one or more file paths from a tkinterdnd2 drop event string."""
    paths = []
    raw = raw.strip()
    i = 0
    while i < len(raw):
        if raw[i] == "{":
            end = raw.index("}", i)
            paths.append(raw[i + 1 : end])
            i = end + 1
        elif raw[i] == " ":
            i += 1
        else:
            end = i
            while end < len(raw) and raw[end] not in (" ", "{"):
                end += 1
            paths.append(raw[i:end])
            i = end
    return [p.strip('"\'') for p in paths if p.strip()]


# ── main window ───────────────────────────────────────────────────────────────

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Video Preview Generator")
        self.resizable(True, True)
        self.minsize(520, 480)
        self.geometry("1040x960")
        self._stop_event = threading.Event()
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
            text="拖拽视频文件到这里（支持多个）\n或点击选择文件",
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
        self._var_ffmpeg = tk.StringVar(value=find_ffmpeg())
        tk.Entry(ff_frame, textvariable=self._var_ffmpeg, width=38,
                 font=("Segoe UI", 9)).pack(side="left", padx=(6, 4))
        tk.Button(ff_frame, text="浏览…", command=self._browse_ffmpeg,
                  font=("Segoe UI", 9)).pack(side="left")

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=(10, 4))

        self._btn_generate = tk.Button(
            btn_frame, text="生成预览视频", command=self._generate,
            font=("Segoe UI", 11, "bold"), bg="#2563eb", fg="white",
            activebackground="#1d4ed8", activeforeground="white",
            relief="flat", padx=20, pady=6, cursor="hand2",
        )
        self._btn_generate.pack(side="left", padx=(0, 8))

        self._btn_ts_convert = tk.Button(
            btn_frame, text="转换ts视频", command=self._convert_ts,
            font=("Segoe UI", 11, "bold"), bg="#059669", fg="white",
            activebackground="#047857", activeforeground="white",
            relief="flat", padx=20, pady=6, cursor="hand2",
        )
        self._btn_ts_convert.pack(side="left", padx=(0, 8))

        self._btn_stop = tk.Button(
            btn_frame, text="停止", command=self._stop,
            font=("Segoe UI", 11, "bold"), bg="#dc2626", fg="white",
            activebackground="#b91c1c", activeforeground="white",
            relief="flat", padx=20, pady=6, cursor="hand2",
            state="disabled",
        )
        self._btn_stop.pack(side="left")

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

        self._input_paths: list = []

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_drop(self, event):
        self._set_inputs(parse_dnd_paths(event.data))

    def _browse_input(self, _event=None):
        paths = filedialog.askopenfilenames(
            title="选择视频文件",
            filetypes=[("Video files", "*.mp4 *.ts *.tsv"), ("All files", "*.*")],
        )
        if paths:
            self._set_inputs(list(paths))

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

    def _set_inputs(self, paths: list):
        self._input_paths = paths
        if len(paths) == 1:
            label = f"已选择：{os.path.basename(paths[0])}"
            out = build_output_path(paths[0], None)
        else:
            label = f"已选择 {len(paths)} 个文件"
            out = os.path.dirname(os.path.abspath(paths[-1]))
        self._drop_label.config(text=label, fg="#1d4ed8", font=("Segoe UI", 10, "bold"))
        if paths:
            self._var_output.set(out)

    # ── busy / stop state ─────────────────────────────────────────────────────

    def _set_busy(self, busy: bool):
        run_state  = "disabled" if busy else "normal"
        stop_state = "normal"  if busy else "disabled"
        self._btn_generate.config(state=run_state)
        self._btn_ts_convert.config(state=run_state)
        self._btn_stop.config(state=stop_state)
        if not busy:
            self._stop_event.clear()

    def _stop(self):
        self._stop_event.set()
        self._btn_stop.config(state="disabled")
        self._log_write("正在停止...\n", "warn")

    # ── preview generation ────────────────────────────────────────────────────

    def _generate(self):
        if not self._input_paths:
            self._log_write("请先选择或拖入视频文件。\n", "warn")
            return
        try:
            duration     = float(self._var_duration.get())
            segments     = int(self._var_segments.get())
            start_offset = float(self._var_start_offset.get())
            end_offset   = float(self._var_end_offset.get())
        except ValueError:
            self._log_write("参数格式错误，请检查输入（必须为数字）。\n", "warn")
            return

        # Single file: respect the output path field; multiple files: auto-name each
        output_single = self._var_output.get().strip() if len(self._input_paths) == 1 else None
        ffmpeg = self._var_ffmpeg.get().strip() or find_ffmpeg()

        self._set_busy(True)
        self._progress["value"] = 0
        self._log_write("开始生成...\n\n")

        threading.Thread(
            target=self._run_generate,
            args=(list(self._input_paths), duration, segments, output_single,
                  start_offset, end_offset, ffmpeg),
            daemon=True,
        ).start()

    def _run_generate(self, input_paths, duration, segments, output_single,
                      start_offset, end_offset, ffmpeg):
        def log(msg):
            self._log_queue.put(("info", msg + "\n"))

        total_files = len(input_paths)

        def on_progress(pct, file_idx):
            overall = (file_idx * 100.0 + pct) / total_files
            self._log_queue.put(("progress", overall))

        try:
            for idx, input_path in enumerate(input_paths):
                if self._stop_event.is_set():
                    break
                if total_files > 1:
                    log(f"\n── 文件 {idx + 1}/{total_files}: {os.path.basename(input_path)} ──")
                    output = build_output_path(input_path, None)
                else:
                    output = output_single or None
                generate_preview(
                    input_path=input_path,
                    duration=duration,
                    segments=segments,
                    output=output,
                    start_offset=start_offset,
                    end_offset=end_offset,
                    ffmpeg_path=ffmpeg,
                    log=log,
                    on_progress=lambda pct, i=idx: on_progress(pct, i),
                    stop_event=self._stop_event,
                )

            if self._stop_event.is_set():
                self._log_queue.put(("warn", "已停止。\n"))
            else:
                self._log_queue.put(("ok", ""))
        except PreviewError as e:
            if self._stop_event.is_set():
                self._log_queue.put(("warn", "已停止。\n"))
            else:
                self._log_queue.put(("warn", f"错误：{e}\n"))
        except Exception as e:
            self._log_queue.put(("warn", f"未知错误：{e}\n"))
        finally:
            self._log_queue.put(("done", ""))

    # ── TS conversion ─────────────────────────────────────────────────────────

    def _convert_ts(self):
        ts_input_files = [p for p in self._input_paths
                          if p.lower().endswith((".ts", ".tsv"))]

        if ts_input_files:
            input_files = ts_input_files
            ref_dir = os.path.dirname(os.path.abspath(input_files[0]))
        elif self._input_paths:
            ref_dir = os.path.dirname(os.path.abspath(self._input_paths[0]))
            found = [f for f in os.listdir(ref_dir)
                     if f.lower().endswith((".ts", ".tsv"))]
            if not found:
                self._log_write(f"在 {ref_dir} 中未找到 .ts 或 .tsv 文件。\n", "warn")
                return
            input_files = [os.path.join(ref_dir, f) for f in found]
        else:
            src = filedialog.askdirectory(title="选择包含 .ts/.tsv 文件的文件夹")
            if not src:
                return
            found = [f for f in os.listdir(src)
                     if f.lower().endswith((".ts", ".tsv"))]
            if not found:
                self._log_write(f"在 {src} 中未找到 .ts 或 .tsv 文件。\n", "warn")
                return
            input_files = [os.path.join(src, f) for f in found]
            ref_dir = src

        output_path = self._var_output.get().strip()
        if output_path:
            abs_out = os.path.abspath(output_path)
            # Directory path (no extension) → use directly; file path → use its parent
            out_base = abs_out if not os.path.splitext(abs_out)[1] else os.path.dirname(abs_out)
        else:
            out_base = ref_dir
        output_dir = os.path.join(out_base, "mp4_output")

        ffmpeg = self._var_ffmpeg.get().strip() or find_ffmpeg()

        self._set_busy(True)
        self._progress["value"] = 0
        self._log_write(f"开始转换 {len(input_files)} 个文件...\n\n")

        threading.Thread(
            target=self._run_convert_ts,
            args=(input_files, output_dir, ffmpeg),
            daemon=True,
        ).start()

    def _run_convert_ts(self, input_files, output_dir, ffmpeg):
        def log(msg):
            self._log_queue.put(("info", msg + "\n"))

        def on_progress(pct):
            self._log_queue.put(("progress", pct))

        try:
            convert_ts(
                input_files=input_files,
                output_dir=output_dir,
                ffmpeg_path=ffmpeg,
                log=log,
                on_progress=on_progress,
                stop_event=self._stop_event,
            )
            if self._stop_event.is_set():
                self._log_queue.put(("warn", "已停止。\n"))
            else:
                self._log_queue.put(("ok", ""))
        except ConvertError as e:
            if self._stop_event.is_set():
                self._log_queue.put(("warn", "已停止。\n"))
            else:
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
                    self._set_busy(False)
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
