#!/usr/bin/env python3
"""Batch remux .ts / .tsv files to .mp4 using ffmpeg stream-copy."""

import os
import subprocess
import sys
import threading
import time


class ConvertError(RuntimeError):
    """Raised on any user-facing error during TS conversion."""


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def convert_ts(
    input_files,
    output_dir,
    ffmpeg_path="ffmpeg",
    log=None,
    on_progress=None,
    stop_event=None,
):
    """
    Remux each file in *input_files* to MP4 (stream-copy, no re-encode).

    Parameters
    ----------
    input_files  : list of absolute file paths (.ts / .tsv)
    output_dir   : directory where the resulting .mp4 files are written
    ffmpeg_path  : path to the ffmpeg executable
    log          : optional callable(str) for progress messages
    on_progress  : optional callable(float) receiving 0–100
    stop_event   : optional threading.Event; set it to request cancellation
    """
    if log is None:
        log = print
    if on_progress is None:
        on_progress = lambda _: None

    os.makedirs(output_dir, exist_ok=True)
    log(f"输出文件夹：{output_dir}")

    total = len(input_files)
    for i, input_file in enumerate(input_files, 1):
        if stop_event and stop_event.is_set():
            raise ConvertError("已停止")

        fname = os.path.basename(input_file)
        stem  = os.path.splitext(fname)[0]
        output_file = os.path.join(output_dir, stem + ".mp4")
        log(f"[{i}/{total}] 正在转换：{fname}")

        proc = subprocess.Popen(
            [ffmpeg_path, "-i", input_file, "-c", "copy", output_file, "-y"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=_NO_WINDOW,
        )

        # Drain stderr in a thread so the pipe buffer never fills up and blocks ffmpeg
        stderr_chunks: list = []
        drain = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True)
        drain.start()

        while proc.poll() is None:
            if stop_event and stop_event.is_set():
                proc.kill()
                proc.wait()
                drain.join(timeout=2)
                raise ConvertError("已停止")
            time.sleep(0.1)

        drain.join()
        stderr_out = (stderr_chunks[0] if stderr_chunks else b"").decode("utf-8", errors="replace")

        if proc.returncode != 0:
            tail = stderr_out.strip()[-400:] if stderr_out.strip() else "(无输出)"
            log(f"  ⚠ 转换失败 (exit {proc.returncode}):\n  {tail}")
        else:
            log(f"  完成：{stem}.mp4")

        on_progress(int(i / total * 100))
