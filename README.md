# 基地边缘竖版视频合成器Pro

当前版本：`1.3`

一个轻量 Windows 桌面工具：选择横屏视频、封套 PNG、输出目录后，自动生成 `1080x1260` 的竖版封套视频。

## 运行

```powershell
python app.py
```

需要本机可用 `ffmpeg.exe` 和 `ffprobe.exe`。可以放在本程序同目录，也可以加入系统 `PATH`。

## 拖拽支持

已支持把文件拖到对应输入框：

- 视频拖到“横屏视频”
- PNG 拖到“封套 PNG”
- 文件夹拖到“输出目录”

拖拽依赖为 `tkinterdnd2`。若换到新机器，可安装：

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7897"
$env:HTTPS_PROXY="http://127.0.0.1:7897"
python -m pip install -r requirements.txt
```

## 输出命名

命名方式有两种：

- 模板：`【竖版】` + `商单/基地` + `_项目名称` + `版本号`
- 自定义：直接输入完整文件名；不写 `.mp4` 时会自动补上

模板示例：

```text
【竖版】商单_鸿蒙技术V4.mp4
```

版本号下拉提供 `V1` 到 `V20`，也可以手动输入。

## 输出规格

- 分辨率：`1080x1260`
- 帧率：`25fps`
- 视频：优先 `h264_nvenc`，不可用时自动回退 `libx264`
- 导出质量：最佳 `15Mbps`、高 `8Mbps`、普通 `6Mbps`
- 音频：`AAC 192k`
- 像素格式：`yuv420p`
- 位置：横屏视频顶部边缘放在画布 `y=422` 的位置，可在高级参数里修改“视频顶部 Y”

## 打包 exe

安装 PyInstaller：

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7897"
$env:HTTPS_PROXY="http://127.0.0.1:7897"
python -m pip install pyinstaller
```

打包：

```powershell
pyinstaller --noconsole --onefile --name VerticalWrapperGenerator --collect-all tkinterdnd2 app.py
```

打包后可把 `ffmpeg.exe` 和 `ffprobe.exe` 放到 exe 同目录，或者继续使用系统 `PATH` 中的 FFmpeg。
