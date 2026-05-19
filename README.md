# Video Previewer

基于 FFmpeg 的视频预览片段生成工具，支持命令行和图形界面两种使用方式。

## 功能特性

- 从任意 MP4 视频中均匀抽取片段，自动拼接为预览视频
- 支持设置预览总时长、片段数量、跳过片头/片尾
- 使用 stream copy 模式，不重新编码，速度极快
- 图形界面支持拖拽导入视频，实时显示进度

## 依赖

- Python 3.7+
- [FFmpeg](https://ffmpeg.org/)（需加入系统 PATH，或在界面中手动指定路径）
- 图形界面额外依赖：`tkinterdnd2`

```bash
pip install tkinterdnd2
```

## 使用方法

### 图形界面

```bash
python video_preview_ui.py
```

- 将 MP4 视频拖入界面，或点击选择文件
- 调整参数后点击「生成预览视频」

### 命令行

```bash
python video_preview.py <输入文件> [选项]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `input` | 必填 | 源 MP4 文件路径 |
| `-d`, `--duration` | `30` | 预览视频总时长（秒） |
| `-s`, `--segments` | `5` | 片段数量 |
| `-o`, `--output` | 自动生成 | 输出文件路径 |
| `--start-offset` | `0` | 跳过片头秒数 |
| `--end-offset` | `0` | 跳过片尾秒数 |
| `--ffmpeg-path` | `ffmpeg` | FFmpeg 可执行文件路径 |

**示例：**

```bash
# 生成 30 秒、5 段的预览，输出到同目录
python video_preview.py myvideo.mp4

# 60 秒预览，10 段，跳过片头 30 秒和片尾 60 秒
python video_preview.py myvideo.mp4 -d 60 -s 10 --start-offset 30 --end-offset 60
```

## 打包为 exe

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name "VideoPreview" \
  --add-data "<tkinterdnd2路径>/tkdnd/win-x86;tkinterdnd2/tkdnd/win-x86" \
  video_preview_ui.py
```

打包完成后 exe 位于 `dist/VideoPreview.exe`，双击即可运行，无需安装 Python。

## 注意事项

由于使用 stream copy 不重新编码，实际生成的预览时长可能略长于设定值（误差取决于视频关键帧间隔）。如需精确时长，需改用重新编码模式。
