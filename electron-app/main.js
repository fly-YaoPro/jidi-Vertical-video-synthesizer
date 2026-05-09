const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const path = require('path');
const { spawn, execFile } = require('child_process');
const fs = require('fs');

const APP_NAME = '基地边缘竖版视频合成器Pro';
const APP_VERSION = '1.5';
const CANVAS_WIDTH = 1080;
const CANVAS_HEIGHT = 1260;
const OUTPUT_FPS = 25;

let mainWindow;
let nvencAvailable = false;
let nvencChecked = false;
let nvencDetectionPromise = null;

function toolPath(name) {
  const exe = process.platform === 'win32' ? `${name}.exe` : name;
  const packaged = path.join(process.resourcesPath || '', exe);
  if (app.isPackaged && fs.existsSync(packaged)) return packaged;
  const dev = path.join(__dirname, '..', exe);
  if (fs.existsSync(dev)) return dev;
  return exe;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 620,
    height: 760,
    minWidth: 540,
    minHeight: 600,
    title: `${APP_NAME} v${APP_VERSION}`,
    backgroundColor: '#edf5ff',
    transparent: false,
    hasShadow: true,
    roundedCorners: true,
    autoHideMenuBar: true,
    frame: false,
    titleBarStyle: 'hidden',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'index.html'));
}

function sendLog(text) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('render-log', text);
  }
}

function sendProgress(value) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('render-progress', value);
  }
}

function runCapture(command, args) {
  return new Promise((resolve) => {
    execFile(command, args, { windowsHide: true, encoding: 'utf8' }, (error, stdout, stderr) => {
      resolve({
        ok: !error,
        output: `${stdout || ''}${stderr || ''}`,
      });
    });
  });
}

async function detectNvenc() {
  if (nvencChecked) return { nvencAvailable, ffmpeg: toolPath('ffmpeg') };
  if (nvencDetectionPromise) return nvencDetectionPromise;

  const ffmpeg = toolPath('ffmpeg');
  nvencDetectionPromise = runCapture(ffmpeg, ['-hide_banner', '-encoders'])
    .then((result) => {
      nvencAvailable = result.ok && result.output.includes('h264_nvenc');
      nvencChecked = true;
      return { nvencAvailable, ffmpeg };
    })
    .finally(() => {
      nvencDetectionPromise = null;
    });
  return nvencDetectionPromise;
}

async function probeDuration(videoPath) {
  const ffprobe = toolPath('ffprobe');
  const result = await runCapture(ffprobe, [
    '-v',
    'error',
    '-show_entries',
    'format=duration',
    '-of',
    'default=noprint_wrappers=1:nokey=1',
    videoPath,
  ]);
  const value = Number.parseFloat(result.output.trim());
  return Number.isFinite(value) && value > 0 ? value : null;
}

function secondsFromTime(value) {
  const match = value.match(/(\d+):(\d+):(\d+(?:\.\d+)?)/);
  if (!match) return null;
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
}

function bitrateBuffer(bitrate) {
  const match = bitrate.match(/^(\d+)M$/);
  return match ? `${Number(match[1]) * 2}M` : bitrate;
}

function buildFfmpegArgs(job, useNvenc) {
  const bitrate = job.bitrate || '8M';
  const videoTopY = Number.isFinite(Number(job.videoTopY)) ? Number(job.videoTopY) : 422;
  const filter = `[0:v]scale=${CANVAS_WIDTH}:${CANVAS_HEIGHT}:force_original_aspect_ratio=increase,crop=${CANVAS_WIDTH}:${CANVAS_HEIGHT},setsar=1[bg];[1:v]scale=${CANVAS_WIDTH}:-2,setsar=1[v];[bg][v]overlay=0:${videoTopY}:shortest=1,format=yuv420p[outv]`;
  const args = [
    '-y',
    '-hide_banner',
    '-loop',
    '1',
    '-i',
    job.coverPath,
    '-i',
    job.videoPath,
    '-filter_complex',
    filter,
    '-map',
    '[outv]',
    '-map',
    '1:a?',
    '-r',
    String(OUTPUT_FPS),
  ];

  if (useNvenc) {
    args.push(
      '-c:v',
      'h264_nvenc',
      '-preset',
      job.preset || 'p5',
      '-rc',
      'vbr',
      '-cq',
      String(job.cq || 18),
      '-b:v',
      bitrate,
      '-maxrate',
      bitrate,
      '-bufsize',
      bitrateBuffer(bitrate),
    );
  } else {
    args.push(
      '-c:v',
      'libx264',
      '-b:v',
      bitrate,
      '-maxrate',
      bitrate,
      '-bufsize',
      bitrateBuffer(bitrate),
      '-preset',
      job.cpuPreset || 'medium',
    );
  }

  args.push('-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-shortest', job.outputPath);
  return args;
}

function runFfmpeg(job, useNvenc, duration) {
  return new Promise((resolve) => {
    const ffmpeg = toolPath('ffmpeg');
    const args = buildFfmpegArgs(job, useNvenc);
    sendLog(`编码方式：${useNvenc ? 'GPU / NVENC' : 'CPU x264'}\n`);
    sendLog(`输出文件：${job.outputPath}\n`);
    sendLog(`FFmpeg：${ffmpeg}\n${args.join(' ')}\n\n`);

    const child = spawn(ffmpeg, args, { windowsHide: true });
    child.stdout.on('data', (data) => sendLog(data.toString()));
    child.stderr.on('data', (data) => {
      const text = data.toString();
      sendLog(text);
      if (duration) {
        const match = text.match(/time=(\d+:\d+:\d+(?:\.\d+)?)/);
        if (match) {
          const current = secondsFromTime(match[1]);
          if (current !== null) sendProgress(Math.min(100, (current / duration) * 100));
        }
      }
    });
    child.on('close', (code) => {
      if (code === 0 && fs.existsSync(job.outputPath)) sendProgress(100);
      resolve(code === 0 && fs.existsSync(job.outputPath));
    });
    child.on('error', (error) => {
      sendLog(`启动 FFmpeg 失败：${error.message}\n`);
      resolve(false);
    });
  });
}

ipcMain.handle('app-info', async () => ({ name: APP_NAME, version: APP_VERSION }));
ipcMain.handle('check-encoder', async () => detectNvenc());

ipcMain.handle('select-video', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择横屏视频',
    properties: ['openFile'],
    filters: [{ name: 'Video', extensions: ['mp4', 'mov', 'mkv', 'avi', 'm4v'] }],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('select-cover', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择封套 PNG',
    properties: ['openFile'],
    filters: [{ name: 'PNG', extensions: ['png'] }],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('select-output-dir', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择输出目录',
    properties: ['openDirectory'],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('start-render', async (_event, job) => {
  if (!job.videoPath || !job.coverPath || !job.outputPath) {
    return { ok: false, message: '请先选择视频、封套 PNG 和输出路径。' };
  }
  if (!fs.existsSync(job.videoPath)) return { ok: false, message: '输入视频不存在。' };
  if (!fs.existsSync(job.coverPath)) return { ok: false, message: '封套 PNG 不存在。' };

  try {
    fs.mkdirSync(path.dirname(job.outputPath), { recursive: true });
  } catch (error) {
    return { ok: false, message: `输出目录不可写：${error.message}` };
  }

  const duration = await probeDuration(job.videoPath);
  if (!duration) sendLog('未能读取视频时长，进度条将按未知时长显示。\n');

  const selected = job.encoder || 'auto';
  await detectNvenc();
  if (selected === 'nvenc' && !nvencAvailable) {
    return { ok: false, message: '当前 FFmpeg 不支持 NVENC，请选择自动或 CPU x264。' };
  }

  let useNvenc = selected === 'nvenc' || (selected === 'auto' && nvencAvailable);
  if (selected === 'auto' && !nvencAvailable) {
    sendLog('当前 FFmpeg 不支持 NVENC，已自动使用 CPU x264。\n');
  }

  let ok = await runFfmpeg(job, useNvenc, duration);
  if (!ok && selected === 'auto' && useNvenc) {
    sendLog('\nNVENC 输出失败，正在自动回退 CPU x264。\n');
    useNvenc = false;
    ok = await runFfmpeg(job, useNvenc, duration);
  }
  return { ok, outputPath: job.outputPath, message: ok ? '完成' : '输出失败，请查看日志。' };
});

ipcMain.handle('show-item', async (_event, filePath) => {
  shell.showItemInFolder(filePath);
});

ipcMain.handle('window-control', async (_event, action) => {
  if (!mainWindow) return;
  if (action === 'minimize') mainWindow.minimize();
  if (action === 'maximize') {
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
  }
  if (action === 'close') mainWindow.close();
});

app.whenReady().then(async () => {
  createWindow();
  mainWindow.webContents.once('did-finish-load', () => {
    detectNvenc().then((result) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('encoder-detected', { nvencAvailable: result.nvencAvailable });
      }
    });
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
