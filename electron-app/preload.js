const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('bridge', {
  appInfo: () => ipcRenderer.invoke('app-info'),
  checkEncoder: () => ipcRenderer.invoke('check-encoder'),
  selectVideo: () => ipcRenderer.invoke('select-video'),
  selectCover: () => ipcRenderer.invoke('select-cover'),
  selectOutputDir: () => ipcRenderer.invoke('select-output-dir'),
  getPathForFile: (file) => {
    if (webUtils && webUtils.getPathForFile) return webUtils.getPathForFile(file);
    return file.path || '';
  },
  startRender: (job) => ipcRenderer.invoke('start-render', job),
  showItem: (filePath) => ipcRenderer.invoke('show-item', filePath),
  windowControl: (action) => ipcRenderer.invoke('window-control', action),
  onLog: (callback) => ipcRenderer.on('render-log', (_event, text) => callback(text)),
  onProgress: (callback) => ipcRenderer.on('render-progress', (_event, value) => callback(value)),
  onEncoderDetected: (callback) => ipcRenderer.on('encoder-detected', (_event, value) => callback(value)),
});
