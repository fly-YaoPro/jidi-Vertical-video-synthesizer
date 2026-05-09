# 基地边缘竖版视频合成器Pro

当前版本：`v1.5`

一个轻量 Windows 桌面工具，用于把横屏视频自动合成为固定规格的竖版封套视频。用户选择横屏视频、封套 PNG 和输出命名后，即可生成 `1080x1260` 的竖版 MP4，不需要进入 DaVinci Resolve 手动包装。

## 功能亮点

- 横屏视频与封套 PNG 支持点击选择和拖拽导入
- 输出画布固定为 `1080x1260`
- 横屏视频保持比例缩放到宽度 `1080`，视频顶部默认落在 `y=422`
- 输出帧率固定 `25fps`
- 支持自动 / NVIDIA NVENC / CPU x264 编码
- 自动检测 NVENC，自动模式下优先使用 GPU，不支持时回退 CPU
- 导出质量三档：最佳 `15 Mbps`、高 `8 Mbps`、普通 `6 Mbps`
- 支持模板命名和自定义命名
- 选择横屏视频后，默认输出目录自动设置为视频所在目录
- 生成完成后可打开文件所在位置
- Liquid Glass 风格界面，包含玻璃质感、动效、高光扫过和完成反馈

## 下载使用

请到 GitHub Releases 下载最新的单文件 exe：

```text
基地边缘竖版视频合成器Pro_LiquidGlass_v1.5.exe
```

双击打开后使用：

1. 拖入或选择横屏视频
2. 拖入或选择封套 PNG
3. 设置输出命名和导出质量
4. 点击“开始生成”

## 输出规格

- 分辨率：`1080x1260`
- 帧率：`25fps`
- 视频编码：`h264_nvenc` 或 `libx264`
- 音频编码：`AAC 192k`
- 像素格式：`yuv420p`
- 封装格式：`MP4`
- 默认视频顶部位置：`y=422`

## 开发运行

源码在 `electron-app/` 目录。

```powershell
cd electron-app
npm install
npm start
```

如果需要通过代理安装依赖：

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7897"
$env:HTTPS_PROXY="http://127.0.0.1:7897"
npm install
```

## 打包

```powershell
cd electron-app
$env:CSC_IDENTITY_AUTO_DISCOVERY="false"
npm run dist
```

打包产物位于：

```text
electron-app/dist/基地边缘竖版视频合成器Pro_LiquidGlass_v1.5.exe
```

## FFmpeg

发布包内已随应用携带 `ffmpeg.exe` 和 `ffprobe.exe`。开发环境中需要将它们放在项目根目录，或加入系统 `PATH`。
