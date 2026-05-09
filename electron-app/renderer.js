const state = {
  videoPath: '',
  coverPath: '',
  outputDir: '',
  nvencAvailable: false,
  outputPath: '',
  rendering: false,
  selects: {},
};

const $ = (id) => document.getElementById(id);

const videoDrop = $('videoDrop');
const coverDrop = $('coverDrop');
const videoMeta = $('videoMeta');
const coverMeta = $('coverMeta');
const outputDir = $('outputDir');
const filenamePreview = $('filenamePreview');
const encoderHint = $('encoderHint');
const encoderStrip = $('encoderStrip');
const logEl = $('log');
const progressBar = $('progressBar');
const progressShell = document.querySelector('.progress-shell');
const successSweep = $('successSweep');
const successOverlay = $('successOverlay');
const doneFile = $('doneFile');
const doneBubble = $('doneBubble');

function fileName(value) {
  if (!value) return '';
  return value.split(/[\\/]/).pop();
}

function dirName(value) {
  if (!value) return '';
  const normalized = value.replace(/[\\/]+$/, '');
  const index = Math.max(normalized.lastIndexOf('\\'), normalized.lastIndexOf('/'));
  return index > 0 ? normalized.slice(0, index) : '';
}

function cleanName(value) {
  return String(value || '').trim().replace(/[\\/:*?"<>|]/g, '_').replace(/[. ]+$/g, '');
}

function versionValue(value) {
  const text = cleanName(value);
  if (!text) return 'V1';
  if (/^\d+$/.test(text)) return `V${text}`;
  if (/^v\d+$/i.test(text)) return `V${text.slice(1)}`;
  return text;
}

function selectValue(id) {
  return state.selects[id]?.value || '';
}

function restartPop(element) {
  element.classList.remove('liquid-pop');
  void element.offsetWidth;
  element.classList.add('liquid-pop');
}

function closeSelects(except = null) {
  Object.values(state.selects).forEach((select) => {
    if (select.root !== except) {
      select.root.classList.remove('open');
      select.menu.classList.remove('open');
    }
  });
}

function positionSelectMenu(select) {
  if (!select || !select.root.classList.contains('open')) return;
  const rect = select.button.getBoundingClientRect();
  const gap = 8;
  const pagePad = 12;
  const below = window.innerHeight - rect.bottom - gap - pagePad;
  const above = rect.top - gap - pagePad;
  const naturalHeight = Math.min(select.menu.scrollHeight || 258, 258);
  const openUp = below < Math.min(170, naturalHeight) && above > below;
  const maxHeight = Math.max(120, Math.min(258, openUp ? above : below));
  const top = openUp ? Math.max(pagePad, rect.top - gap - Math.min(naturalHeight, maxHeight)) : rect.bottom + gap;

  select.menu.style.left = `${Math.round(rect.left)}px`;
  select.menu.style.top = `${Math.round(top)}px`;
  select.menu.style.width = `${Math.round(rect.width)}px`;
  select.menu.style.maxHeight = `${Math.round(maxHeight)}px`;
}

function positionOpenSelect() {
  Object.values(state.selects).forEach(positionSelectMenu);
}

function setSelectValue(id, value, label = value, options = {}) {
  const select = state.selects[id];
  if (!select) return;
  select.value = value;
  select.label = label;
  select.buttonText.textContent = label;
  select.root.dataset.value = value;
  select.menu.querySelectorAll('.select-option').forEach((option) => {
    option.classList.toggle('selected', option.dataset.value === value);
  });
  if (!options.silent) {
    restartPop(select.root);
    select.root.dispatchEvent(new CustomEvent('liquid-change', { bubbles: true }));
  }
}

function createLiquidSelect(id, options, config = {}) {
  const root = $(id);
  const initial = root.dataset.value || options[0].value;
  root.innerHTML = `
    <button class="select-button lit" type="button">
      <span class="select-text"></span>
      <span class="select-chevron">⌄</span>
    </button>
  `;

  const button = root.querySelector('.select-button');
  const buttonText = root.querySelector('.select-text');
  const menu = document.createElement('div');
  menu.className = 'select-menu';
  menu.dataset.owner = id;
  menu.addEventListener('click', (event) => event.stopPropagation());
  document.body.appendChild(menu);
  state.selects[id] = { root, button, buttonText, menu, value: initial, label: initial };

  options.forEach((item) => {
    const option = document.createElement('button');
    option.type = 'button';
    option.className = 'select-option';
    option.dataset.value = item.value;
    option.textContent = item.label;
    option.addEventListener('click', (event) => {
      event.stopPropagation();
      setSelectValue(id, item.value, item.label);
      root.classList.remove('open');
      menu.classList.remove('open');
    });
    menu.appendChild(option);
  });

  if (config.allowCustom) {
    const custom = document.createElement('input');
    custom.className = 'select-custom-input';
    custom.placeholder = config.placeholder || '输入自定义值';
    custom.addEventListener('click', (event) => event.stopPropagation());
    custom.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        const value = versionValue(custom.value);
        setSelectValue(id, value, value);
        root.classList.remove('open');
        menu.classList.remove('open');
      }
    });
    custom.addEventListener('input', () => {
      if (custom.value.trim()) {
        const value = versionValue(custom.value);
        setSelectValue(id, value, value);
      }
    });
    menu.appendChild(custom);
  }

  button.addEventListener('click', (event) => {
    event.stopPropagation();
    const willOpen = !root.classList.contains('open');
    closeSelects(root);
    root.classList.toggle('open', willOpen);
    menu.classList.toggle('open', willOpen);
    if (willOpen) {
      positionSelectMenu(state.selects[id]);
      restartPop(root);
      requestAnimationFrame(() => positionSelectMenu(state.selects[id]));
    }
  });

  const selected = options.find((item) => item.value === initial) || options[0];
  setSelectValue(id, selected.value, selected.label, { silent: true });
}

function outputFilename() {
  const mode = $('namingSegment').dataset.value || 'template';
  if (mode === 'template') {
    const type = selectValue('projectTypeSelect') || '商单';
    const project = cleanName($('projectName').value);
    const version = cleanName(versionValue(selectValue('versionSelect') || 'V1'));
    return `【竖版】${type}_${project}${version}.mp4`;
  }
  const custom = cleanName($('customName').value);
  return custom ? `${custom.replace(/\.mp4$/i, '')}.mp4` : '';
}

function updatePreview() {
  filenamePreview.textContent = outputFilename() || '请输入输出文件名';
}

function updateEncoderHint() {
  const encoder = selectValue('encoderSelect') || 'auto';
  let text;
  if (encoder === 'auto') {
    text = state.nvencAvailable ? '自动预计使用 GPU / NVENC' : '自动预计使用 CPU x264';
  } else if (encoder === 'nvenc') {
    text = '已选择 GPU / NVENC';
  } else {
    text = '已选择 CPU x264';
  }
  encoderHint.textContent = text;
  encoderStrip.textContent = text;
}

function setDropSelected(kind, path) {
  if (kind === 'video') {
    state.videoPath = path;
    videoMeta.textContent = fileName(path);
    videoDrop.classList.add('selected');
    videoDrop.querySelector('.drop-action').textContent = '已选择';
    const videoDir = dirName(path);
    if (videoDir) {
      state.outputDir = videoDir;
      outputDir.value = videoDir;
    }
  } else {
    state.coverPath = path;
    coverMeta.textContent = fileName(path);
    coverDrop.classList.add('selected');
    coverDrop.querySelector('.drop-action').textContent = '已选择';
  }
}

function appendLog(text) {
  logEl.textContent += text;
  logEl.scrollTop = logEl.scrollHeight;
}

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach((button) => button.classList.toggle('active', button.dataset.tab === tab));
  document.querySelector('.tabs').dataset.active = tab;
  $('workPage').classList.toggle('active', tab === 'work');
  $('logPage').classList.toggle('active', tab === 'log');
}

function outputPath() {
  if (!state.outputDir) return '';
  return `${state.outputDir}\\${outputFilename()}`;
}

function setupDrop(card, kind) {
  card.addEventListener('dragover', (event) => {
    event.preventDefault();
    card.classList.add('dragover');
  });
  card.addEventListener('dragleave', () => card.classList.remove('dragover'));
  card.addEventListener('drop', (event) => {
    event.preventDefault();
    card.classList.remove('dragover');
    const file = event.dataTransfer.files[0];
    if (!file) return;
    const path = window.bridge.getPathForFile(file);
    if (path) setDropSelected(kind, path);
  });
}

function setupHoverLights() {
  document.querySelectorAll('.lit').forEach((element) => {
    element.addEventListener('pointermove', (event) => {
      const rect = element.getBoundingClientRect();
      element.style.setProperty('--mx', `${event.clientX - rect.left}px`);
      element.style.setProperty('--my', `${event.clientY - rect.top}px`);
    });
  });
}

function showSuccess(outputPathValue) {
  state.outputPath = outputPathValue;
  doneBubble.textContent = completionBubbleText();
  doneFile.textContent = fileName(outputPathValue);
  successSweep.classList.remove('run');
  void successSweep.offsetWidth;
  successSweep.classList.add('run');
  window.setTimeout(() => {
    successOverlay.classList.add('show');
  }, 430);
}

function completionBubbleText(date = new Date()) {
  const minutes = date.getHours() * 60 + date.getMinutes();
  const workStart = 9 * 60;
  const workEnd = 20 * 60;
  if (minutes >= workStart && minutes <= workEnd) {
    return '项目结束，今天你又是Be Different的一天。';
  }
  return '加班辛苦了！今天的你Committed爆了！';
}

function hideSuccess() {
  successOverlay.classList.remove('show');
}

function setRendering(rendering) {
  state.rendering = rendering;
  $('startBtn').disabled = rendering;
  $('startBtn').textContent = rendering ? '生成中...' : '开始生成';
  progressShell.classList.toggle('active', rendering);
}

async function init() {
  const info = await window.bridge.appInfo();
  $('appTitle').textContent = `${info.name} v${info.version}`;
  window.setTimeout(async () => {
    const encoder = await window.bridge.checkEncoder();
    state.nvencAvailable = encoder.nvencAvailable;
    updateEncoderHint();
  }, 120);
}

createLiquidSelect('projectTypeSelect', [
  { value: '商单', label: '商单' },
  { value: '基地', label: '基地' },
]);
createLiquidSelect(
  'versionSelect',
  Array.from({ length: 20 }, (_, index) => {
    const value = `V${index + 1}`;
    return { value, label: value };
  }),
  { allowCustom: true, placeholder: '输入版本，例如 V21' },
);
createLiquidSelect('qualitySelect', [
  { value: '15M', label: '最佳 - 15 Mbps' },
  { value: '8M', label: '高 - 8 Mbps' },
  { value: '6M', label: '普通 - 6 Mbps' },
]);
createLiquidSelect('encoderSelect', [
  { value: 'auto', label: '自动' },
  { value: 'nvenc', label: 'NVIDIA NVENC' },
  { value: 'x264', label: 'CPU x264' },
]);

document.addEventListener('click', () => closeSelects());
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    closeSelects();
    hideSuccess();
  }
});
window.addEventListener('resize', positionOpenSelect);
window.addEventListener('scroll', positionOpenSelect, true);

document.querySelectorAll('.tab').forEach((button) => {
  button.addEventListener('click', () => {
    switchTab(button.dataset.tab);
    restartPop(document.querySelector('.tabs'));
  });
});

videoDrop.addEventListener('click', async () => {
  const path = await window.bridge.selectVideo();
  if (path) setDropSelected('video', path);
});

coverDrop.addEventListener('click', async () => {
  const path = await window.bridge.selectCover();
  if (path) setDropSelected('cover', path);
});

$('chooseOutput').addEventListener('click', async () => {
  const path = await window.bridge.selectOutputDir();
  if (path) {
    state.outputDir = path;
    outputDir.value = path;
  }
});

function setupSegment() {
  const segment = $('namingSegment');
  segment.addEventListener('click', (event) => {
    const button = event.target.closest('.segment-button');
    if (!button) return;
    const value = button.dataset.value;
    segment.dataset.value = value;
    segment.querySelectorAll('.segment-button').forEach((item) => item.classList.toggle('active', item === button));
    restartPop(segment);
    const custom = value === 'custom';
    $('customName').disabled = !custom;
    $('projectName').disabled = custom;
    state.selects.projectTypeSelect.root.classList.toggle('disabled', custom);
    state.selects.versionSelect.root.classList.toggle('disabled', custom);
    updatePreview();
  });
}

['projectName', 'customName'].forEach((id) => $(id).addEventListener('input', updatePreview));
['projectTypeSelect', 'versionSelect'].forEach((id) => $(id).addEventListener('liquid-change', updatePreview));
$('encoderSelect').addEventListener('liquid-change', updateEncoderHint);

$('startBtn').addEventListener('click', async () => {
  if (state.rendering) return;
  const out = outputPath();
  if (!state.videoPath || !state.coverPath || !state.outputDir || !out) {
    alert('请先选择视频、封套、输出目录，并填写文件名。');
    return;
  }
  progressBar.style.width = '0%';
  logEl.textContent = '';
  setRendering(true);
  const result = await window.bridge.startRender({
    videoPath: state.videoPath,
    coverPath: state.coverPath,
    outputPath: out,
    bitrate: selectValue('qualitySelect') || '15M',
    encoder: selectValue('encoderSelect') || 'auto',
    videoTopY: Number($('videoTopY').value || 422),
    cq: Number($('cq').value || 18),
    preset: $('preset').value || 'p5',
  });
  setRendering(false);
  if (result.ok) {
    progressBar.style.width = '100%';
    showSuccess(result.outputPath);
  } else {
    alert(result.message || '输出失败，请查看日志。');
  }
});

$('openLocation').addEventListener('click', () => {
  if (state.outputPath) window.bridge.showItem(state.outputPath);
});
$('closeDialog').addEventListener('click', hideSuccess);
successOverlay.addEventListener('click', (event) => {
  if (event.target === successOverlay) hideSuccess();
});

setupDrop(videoDrop, 'video');
setupDrop(coverDrop, 'cover');
setupHoverLights();
setupSegment();
document.querySelectorAll('[data-window]').forEach((button) => {
  button.addEventListener('click', () => window.bridge.windowControl(button.dataset.window));
});
updatePreview();
init();

window.bridge.onLog(appendLog);
window.bridge.onProgress((value) => {
  progressBar.style.width = `${Math.max(0, Math.min(100, value))}%`;
});
window.bridge.onEncoderDetected((value) => {
  state.nvencAvailable = value.nvencAvailable;
  updateEncoderHint();
});
