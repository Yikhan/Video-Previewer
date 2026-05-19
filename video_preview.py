#!/usr/bin/env python3
"""Generate a preview video by extracting evenly-distributed segments from an mp4 file."""

import argparse
import os
import subprocess
import sys
import tempfile


class PreviewError(RuntimeError):
    """Raised on any user-facing error so callers can handle it without sys.exit."""


def _run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise PreviewError(
            f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result


def get_video_duration(input_path, ffprobe_bin):
    # Use csv output to avoid JSON backslash-escaping issues with Windows paths.
    cmd = [ffprobe_bin, "-v", "quiet",
           "-show_entries", "format=duration",
           "-of", "csv=p=0",
           input_path]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise PreviewError(
            f"ffprobe failed on '{input_path}':\n{result.stderr.strip()}"
        )
    raw = result.stdout.strip()
    if not raw:
        raise PreviewError(
            f"ffprobe returned no duration for '{input_path}'. "
            "Is it a valid video file?"
        )
    return float(raw)


def validate_ffmpeg(ffmpeg_bin, ffprobe_bin):
    for name, path in [("ffmpeg", ffmpeg_bin), ("ffprobe", ffprobe_bin)]:
        result = subprocess.run([path, "-version"], capture_output=True)
        if result.returncode != 0:
            raise PreviewError(
                f"'{path}' not found or not executable. "
                f"Make sure {name} is installed and in PATH, "
                f"or specify its location with --ffmpeg-path."
            )


def build_output_path(input_path, output_arg):
    if output_arg:
        return output_arg
    base, ext = os.path.splitext(input_path)
    return f"{base}_preview{ext}"


def extract_segment(ffmpeg_bin, input_path, start, duration, output_path):
    _run_cmd([
        ffmpeg_bin, "-y",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ])


def concat_segments(ffmpeg_bin, segment_paths, output_path):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                     delete=False, encoding="utf-8") as f:
        list_file = f.name
        for path in segment_paths:
            f.write(f"file '{path}'\n")
    try:
        _run_cmd([
            ffmpeg_bin, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path,
        ])
    finally:
        os.unlink(list_file)


def generate_preview(
    input_path,
    duration=30.0,
    segments=5,
    output=None,
    start_offset=0.0,
    end_offset=0.0,
    ffmpeg_path="ffmpeg",
    log=None,
    on_progress=None,
):
    """
    Core logic — importable by the GUI.
    `log` is an optional callable(str) for progress messages.
    `on_progress` is an optional callable(float) receiving 0.0–100.0.
    Raises PreviewError on any user-facing problem.
    """
    if log is None:
        log = print
    if on_progress is None:
        on_progress = lambda _: None

    ffmpeg_bin = ffmpeg_path
    ffprobe_bin = (
        os.path.join(os.path.dirname(ffmpeg_bin), "ffprobe")
        if os.path.dirname(ffmpeg_bin)
        else "ffprobe"
    )

    validate_ffmpeg(ffmpeg_bin, ffprobe_bin)

    if not os.path.isfile(input_path):
        raise PreviewError(f"Input file not found: '{input_path}'")
    if segments < 1:
        raise PreviewError("--segments must be at least 1.")
    if duration <= 0:
        raise PreviewError("--duration must be greater than 0.")
    if start_offset < 0 or end_offset < 0:
        raise PreviewError("--start-offset and --end-offset must be non-negative.")

    total_duration = get_video_duration(input_path, ffprobe_bin)
    usable_start = start_offset
    usable_end = total_duration - end_offset
    usable_duration = usable_end - usable_start
    segment_duration = duration / segments

    if usable_duration <= 0:
        raise PreviewError(
            f"Usable video duration is {usable_duration:.2f}s after applying offsets "
            f"(start-offset={start_offset}s, end-offset={end_offset}s, "
            f"video length={total_duration:.2f}s). Adjust offsets and try again."
        )
    if usable_duration < duration:
        raise PreviewError(
            f"Usable video duration ({usable_duration:.2f}s) is shorter than "
            f"the requested preview duration ({duration}s). "
            f"Reduce --duration or adjust offsets and try again."
        )
    if segment_duration > usable_duration / segments:
        raise PreviewError(
            f"Segment duration ({segment_duration:.2f}s) is too long for the available range. "
            f"Reduce --duration or --segments and try again."
        )

    partition = usable_duration / segments
    segment_starts = [
        usable_start + i * partition + (partition - segment_duration) / 2
        for i in range(segments)
    ]

    output_path = build_output_path(input_path, output)

    log(f"Source video   : {input_path} ({total_duration:.2f}s)")
    log(f"Usable range   : {usable_start:.2f}s – {usable_end:.2f}s ({usable_duration:.2f}s)")
    log(f"Segments       : {segments} x {segment_duration:.2f}s = {duration:.2f}s preview")
    log(f"Output         : {output_path}")
    log("")

    # Progress: segments each take 90/n %, concat takes final 10 %
    seg_step = 90.0 / segments

    tmpdir = tempfile.mkdtemp()
    segment_files = []
    try:
        for i, start in enumerate(segment_starts):
            seg_path = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
            log(f"  Extracting segment {i + 1}/{segments} at {start:.2f}s ...")
            extract_segment(ffmpeg_bin, input_path, start, segment_duration, seg_path)
            segment_files.append(seg_path)
            on_progress((i + 1) * seg_step)

        log("\n  Concatenating segments ...")
        concat_segments(ffmpeg_bin, segment_files, output_path)
        on_progress(100.0)
    finally:
        for f in segment_files:
            if os.path.exists(f):
                os.unlink(f)
        if os.path.exists(tmpdir):
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass

    log(f"\nDone. Preview saved to: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Extract evenly-distributed segments from an mp4 to create a preview video."
    )
    parser.add_argument("input", help="Path to the source mp4 file")
    parser.add_argument("-d", "--duration", type=float, default=30.0,
                        help="Total duration of the preview in seconds (default: 30)")
    parser.add_argument("-s", "--segments", type=int, default=5,
                        help="Number of segments to extract (default: 5)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output file path (default: <input>_preview.mp4)")
    parser.add_argument("--start-offset", type=float, default=0.0,
                        help="Skip this many seconds at the start of the source video (default: 0)")
    parser.add_argument("--end-offset", type=float, default=0.0,
                        help="Skip this many seconds at the end of the source video (default: 0)")
    parser.add_argument("--ffmpeg-path", default="ffmpeg",
                        help="Path to ffmpeg executable (default: ffmpeg from PATH)")
    args = parser.parse_args()

    try:
        generate_preview(
            input_path=args.input,
            duration=args.duration,
            segments=args.segments,
            output=args.output,
            start_offset=args.start_offset,
            end_offset=args.end_offset,
            ffmpeg_path=args.ffmpeg_path,
        )
    except PreviewError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
