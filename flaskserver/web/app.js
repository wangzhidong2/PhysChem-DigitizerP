/* ============================================================
   PhysChem 实验仪表盘 —— 桌面式前端
   零依赖（仅本地 echarts.min.js）：模块图标 / 窗口 / 任务栏 / 密钥提交
   数据源统一封装在 api() 一处，将来换 SSE 只改这里。
   ============================================================ */
'use strict';

const POLL_DETAIL_MS = 1000;   // 单窗口数据轮询间隔
const POLL_OVERVIEW_MS = 3000; // 服务状态 + 模块列表轮询间隔
const SERIES_LIMIT = 2000;     // 序列降采样点数
const TOKEN_KEY = 'pcd_token';

const $ = (id) => document.getElementById(id);
const desktopEl = $('desktop');
const iconsEl = $('desktop-icons');
const windowsEl = $('windows');
const taskbarAppsEl = $('taskbar-apps');
const panelEl = $('panel');
const panelModulesEl = $('panel-modules');
const startBtn = $('start-btn');
const authBtn = $('auth-btn');
const tokenInput = $('token');
const tokenSubmitBtn = $('token-submit');
const tokenHintEl = $('token-hint');
const healthDot = $('health-dot');
const healthText = $('health-text');
const authDot = $('auth-dot');
const authText = $('auth-text');
const serviceInfoEl = $('service-info');
const hintEl = $('desktop-hint');
const toastEl = $('toast');

/* ---------- 状态 ---------- */
let modules = [];                 // /api/modules 的返回
const moduleMap = new Map();      // key -> 模块摘要
const windows = new Map();        // key -> 窗口对象
let zCounter = 10;
let urlTokenApplied = false;
let authState = 'unknown';       // 'ok' | 'err' | 'unknown'：最近一次请求的密钥校验结果

/* ---------- 通用工具 ---------- */
const ICON_ALIAS = [
  [/ph/i, 'pH'], [/位移/, 'cm'], [/速度/, 'v'],
  [/电压/, 'V'], [/电流/, 'A'], [/力/, '力'], [/温度/, '℃'],
];
function iconText(name, key) {
  const s = String(name || key || '?');
  for (const [re, txt] of ICON_ALIAS) {
    if (re.test(s)) return txt;
  }
  const m = /^[A-Za-z0-9]{1,3}/.exec(s);
  if (m && /[A-Za-z]/.test(m[0])) return m[0];
  return s.slice(0, 1);
}

function fmt(v) {
  v = Number(v);
  if (!isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1000) return v.toFixed(0);
  if (a >= 1) return v.toFixed(2);
  return v.toPrecision(2);
}

function dotClass(m) {
  if (!m) return 'dot';
  if (m.collecting) return 'dot collecting';
  if (m.connected) return 'dot on';
  return 'dot';
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

let toastTimer = null;
let toastHideTimer = null;
function toast(msg, ms) {
  toastEl.textContent = msg;
  toastEl.classList.remove('hidden');
  // 强制重排，保证连续提示也能重放动画
  void toastEl.offsetWidth;
  toastEl.classList.add('show');
  clearTimeout(toastTimer);
  clearTimeout(toastHideTimer);   // 否则旧提示的延迟隐藏会把新提示一起藏掉
  toastTimer = setTimeout(() => {
    toastEl.classList.remove('show');
    toastHideTimer = setTimeout(() => toastEl.classList.add('hidden'), 300);
  }, ms || 2600);
}

/* ---------- 启动：?token=xxx 自动登录 ---------- */
// 应用内「打开仪表盘」会在链接上带 ?token=xxx：打开即存入 localStorage。
// 地址栏保留 token（用户要求：登录后地址带上密钥，刷新/分享链接可直接进入）。
(function () {
  try {
    const p = new URLSearchParams(location.search);
    const t = p.get('token');
    if (!t) return;
    localStorage.setItem(TOKEN_KEY, t);
    urlTokenApplied = true;
  } catch (e) { /* 忽略：不因 URL 解析失败影响使用 */ }
})();

/* ---------- 访问密钥 ---------- */
function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
}

function maskToken(t) {
  if (!t) return '';
  return t.length <= 4 ? '••••' : '••••' + t.slice(-4);
}

function setTokenHint(text, kind) {
  tokenHintEl.textContent = text;
  tokenHintEl.className = 'panel-hint' + (kind ? ' ' + kind : '');
}

function updateAuthUI() {
  const t = getToken();
  authDot.className = 'dot ' + (t ? 'ok' : 'warn');
  authText.textContent = t ? '密钥 ' + maskToken(t) : '密钥未设置';
  authBtn.title = t ? '已保存访问密钥 ' + maskToken(t) + '，点击修改' : '点击设置访问密钥';
}

function onAuthError(isFirst) {
  authBtn.classList.add('attention');
  setTimeout(() => authBtn.classList.remove('attention'), 3200);
  setTokenHint('密钥缺失或错误：请提交正确的访问密钥后再操作', 'err');
  // 只在首次失败时弹面板并聚焦，避免每轮轮询都抢走输入焦点
  if (!isFirst) return;
  openPanel();
  if (document.activeElement !== tokenInput) {
    tokenInput.focus();
    tokenInput.select();
  }
}

/** 提交密钥：立即保存并生效（重新拉取全部数据） */
async function submitToken() {
  const v = tokenInput.value.trim();
  setToken(v);
  authState = 'unknown';
  if (v) {
    toast('密钥已保存，正在重新校验…');
    setTokenHint('已提交密钥 ' + maskToken(v) + '，正在校验…');
  } else {
    toast('已清除保存的密钥');
    setTokenHint('已清除密钥：写操作将无法通过校验');
  }
  await refreshOverview();
  refreshAllWindows();
  if (!v) return;                       // 清除密钥：保留上方提示
  if (authState === 'err') return;      // 校验失败：保留 onAuthError 写入的错误提示
  setTokenHint('已保存密钥 ' + maskToken(v) + '，写操作（开始/停止采集等）已可用', 'ok');
}

function setToken(t) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (e) { /* localStorage 不可用时仅本次会话有效 */ }
  tokenInput.value = t || '';
  updateAuthUI();
}

/* ---------- 数据源（唯一出口） ---------- */
async function api(path, opts) {
  // 注意：必须与调用方传入的 headers 合并，不能整体覆盖，
  // 否则 POST 的 Content-Type 会把 X-Auth-Token 顶掉（写操作报 401）
  const init = Object.assign({}, opts || {});
  init.headers = Object.assign({ 'X-Auth-Token': getToken() }, (opts && opts.headers) || {});
  let resp;
  try {
    resp = await fetch(path, init);
  } catch (e) {
    throw new Error('无法连接数据接口');
  }
  if (resp.status === 401) {
    const first = authState !== 'err';
    authState = 'err';
    onAuthError(first);
    throw new Error('访问密钥缺失或错误（点任务栏「密钥」提交）');
  }
  if (!resp.ok) {
    let msg = 'HTTP ' + resp.status;
    try { msg = (await resp.json()).message || msg; } catch (e) { /* 保留默认 */ }
    throw new Error(msg);
  }
  authState = 'ok';
  return resp.json();
}

/* ---------- 服务状态与模块列表 ---------- */
async function refreshOverview() {
  await Promise.allSettled([refreshHealth(), refreshModules()]);
}

async function refreshHealth() {
  try {
    const d = await api('/api/health');
    healthDot.className = 'dot ok';
    healthText.textContent = '服务正常';
    serviceInfoEl.textContent =
      `运行 ${Math.round(d.uptime_s || 0)} 秒 · 模块 ${d.modules_n} 个 · 局域网访问${d.lan_access ? '开启' : '关闭'}`;
  } catch (e) {
    healthDot.className = 'dot err';
    healthText.textContent = '未连接';
    serviceInfoEl.textContent = '无法连接数据接口：' + e.message;
  }
}

async function refreshModules() {
  try {
    const d = await api('/api/modules');
    modules = d.modules || [];
    moduleMap.clear();
    modules.forEach((m) => moduleMap.set(m.key, m));
    syncIcons();
    syncPanelList();
    syncWindowStates();
    hintEl.querySelector('.hint-sub').textContent =
      '点击左侧图标打开模块窗口，实时查看曲线与控制采集';
  } catch (e) {
    hintEl.querySelector('.hint-sub').textContent = '模块列表读取失败：' + e.message;
    setPanelModulesHint('读取失败：' + e.message);
  }
}

/** 面板模块区显示一条提示（清掉已有的模块条目） */
function setPanelModulesHint(text) {
  panelModulesEl.querySelectorAll('.panel-module').forEach((n) => n.remove());
  let hint = panelModulesEl.querySelector('.panel-hint');
  if (!hint) {
    hint = el('div', 'panel-hint');
    panelModulesEl.appendChild(hint);
  }
  hint.textContent = text;
}

/* ---------- 桌面图标 ---------- */
function syncIcons() {
  const seen = new Set();
  modules.forEach((m) => {
    seen.add(m.key);
    let node = iconsEl.querySelector(`.desktop-icon[data-key="${cssEscape(m.key)}"]`);
    if (!node) {
      node = el('div', 'desktop-icon');
      node.dataset.key = m.key;
      const img = el('div', 'icon-img');
      img.appendChild(el('span', null, iconText(m.name, m.key)));
      img.appendChild(el('span', 'icon-dot'));
      node.appendChild(img);
      node.appendChild(el('div', 'icon-name', m.name));
      node.title = m.name + '（点击打开或聚焦窗口）';
      node.addEventListener('click', () => openModule(m.key));
      iconsEl.appendChild(node);
    }
    node.querySelector('.icon-name').textContent = m.name;
    node.querySelector('.icon-dot').className = 'icon-dot' + dotClass(m).replace('dot', '');
  });
  iconsEl.querySelectorAll('.desktop-icon').forEach((n) => {
    if (!seen.has(n.dataset.key)) n.remove();
  });
}

function cssEscape(s) {
  return String(s).replace(/["\\]/g, '\\$&');
}

/* ---------- 窗口 ---------- */
function defaultRect() {
  const b = desktopEl.getBoundingClientRect();
  const narrow = b.width < 760;
  const W = narrow ? Math.max(320, b.width - 16) : Math.min(640, b.width - 160);
  const H = narrow ? Math.max(240, b.height - 16) : Math.min(540, b.height - 80);
  const i = windows.size % 6;
  if (narrow) return { x: 8, y: 8, w: W, h: H };
  const x = Math.max(120, Math.min(160 + i * 28, b.width - W - 8));
  const y = Math.max(12, Math.min(24 + i * 28, b.height - H - 8));
  return { x, y, w: W, h: H };
}

function createWindow(key) {
  const m = moduleMap.get(key) || { key, name: key };
  const r = defaultRect();
  const node = el('div', 'window opening');
  node.dataset.key = key;
  node.style.left = r.x + 'px';
  node.style.top = r.y + 'px';
  node.style.width = r.w + 'px';
  node.style.height = r.h + 'px';
  setTimeout(() => node.classList.remove('opening'), 250);

  // 标题栏
  const bar = el('div', 'window-titlebar');
  const icon = el('div', 'window-icon');
  icon.textContent = iconText(m.name, key);
  bar.appendChild(icon);
  const title = el('div', 'window-title');
  title.appendChild(document.createTextNode(m.name + ' '));
  title.appendChild(el('span', 'win-state', '读取中…'));
  bar.appendChild(title);
  const controls = el('div', 'window-controls');
  const btnMin = el('button', 'window-control min', '─');
  const btnMax = el('button', 'window-control max', '▢');
  const btnClose = el('button', 'window-control close', '✕');
  btnMin.title = '最小化';
  btnMax.title = '最大化 / 还原';
  btnClose.title = '关闭';
  [btnMin, btnMax, btnClose].forEach((b) => { b.type = 'button'; controls.appendChild(b); });
  bar.appendChild(controls);
  node.appendChild(bar);

  // 内容
  const content = el('div', 'window-content');
  const stats = el('div', 'win-stats');
  const statsMap = {};
  [['latest', '最新值'], ['state', '状态'], ['points', '数据点'], ['ylabel', 'Y 轴']].forEach(([f, label]) => {
    const box = el('div', 'win-stat');
    box.appendChild(el('span', 'stat-label', label));
    const v = el('span', 'stat-value', '—');
    box.appendChild(v);
    statsMap[f] = v;
    stats.appendChild(box);
  });
  content.appendChild(stats);
  const toolbar = el('div', 'win-toolbar');
  content.appendChild(toolbar);
  const chartEl = el('div', 'win-chart');
  content.appendChild(chartEl);
  const params = el('pre', 'win-params', '读取中…');
  content.appendChild(params);
  node.appendChild(content);
  windowsEl.appendChild(node);

  const w = {
    key, el: node, chart: null, busy: false, busyCmd: false,
    state: { minimized: false, maximized: false },
    els: { title, state: title.querySelector('.win-state'), stats: statsMap, toolbar, chart: chartEl, params },
  };

  // 交互
  btnMin.addEventListener('click', () => minimizeWindow(w));
  btnMax.addEventListener('click', () => toggleMaximize(w));
  btnClose.addEventListener('click', () => closeWindow(w));
  node.addEventListener('pointerdown', () => focusWindow(w), true);
  makeDraggable(w, bar);
  return w;
}

function openModule(key) {
  let w = windows.get(key);
  if (!w) {
    w = createWindow(key);
    windows.set(key, w);
  }
  if (w.state.minimized) {
    w.state.minimized = false;
    w.el.classList.remove('minimized');
  }
  focusWindow(w);
  updateTaskbar();
  updateHint();
  closePanel();
  refreshWindow(w);
}

function closeWindow(w) {
  if (w.chart) {
    try { w.chart.dispose(); } catch (e) { /* 忽略 */ }
    w.chart = null;
  }
  w.el.remove();
  windows.delete(w.key);
  updateTaskbar();
  updateHint();
}

function minimizeWindow(w) {
  w.state.minimized = true;
  w.el.classList.add('minimized');
  updateTaskbar();
}

function toggleMaximize(w) {
  w.state.maximized = !w.state.maximized;
  w.el.classList.toggle('maximized', w.state.maximized);
  if (w.chart) setTimeout(() => w.chart && w.chart.resize(), 260);
}

function focusWindow(w) {
  windows.forEach((o) => o.el.classList.toggle('active', o === w));
  w.el.style.zIndex = ++zCounter;
  updateTaskbar();
}

function updateHint() {
  hintEl.classList.toggle('hidden', windows.size > 0);
}

/* 拖动：标题栏按下后跟随指针，限制在桌面范围内 */
function makeDraggable(w, handle) {
  let dx = 0, dy = 0, dragging = false, b = null;
  handle.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.window-control')) return;
    if (w.state.maximized) return;
    if (e.button !== undefined && e.button !== 0) return;
    dragging = true;
    b = desktopEl.getBoundingClientRect();
    const r = w.el.getBoundingClientRect();
    dx = e.clientX - r.left;
    dy = e.clientY - r.top;
    w.el.classList.add('dragging');
    // 指针捕获失败（合成事件 / 极少数浏览器）不影响拖动本身
    try { handle.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
    e.preventDefault();
  });
  handle.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const r = w.el.getBoundingClientRect();
    let x = e.clientX - dx - b.left;
    let y = e.clientY - dy - b.top;
    // 至少保留 80px 标题栏在可视区，避免窗口被拖出屏幕
    x = Math.min(Math.max(x, -r.width + 80), b.width - 80);
    y = Math.min(Math.max(y, 0), Math.max(0, b.height - 32));
    w.el.style.left = x + 'px';
    w.el.style.top = y + 'px';
  });
  const stop = (e) => {
    if (!dragging) return;
    dragging = false;
    w.el.classList.remove('dragging');
    try {
      if (handle.hasPointerCapture && handle.hasPointerCapture(e.pointerId)) {
        handle.releasePointerCapture(e.pointerId);
      }
    } catch (err) { /* 忽略 */ }
  };
  handle.addEventListener('pointerup', stop);
  handle.addEventListener('pointercancel', stop);
}

/* ---------- 任务栏窗口按钮 ---------- */
function updateTaskbar() {
  const seen = new Set();
  windows.forEach((w, key) => {
    seen.add(key);
    let btn = taskbarAppsEl.querySelector(`.taskbar-app[data-key="${cssEscape(key)}"]`);
    if (!btn) {
      btn = el('button', 'taskbar-app');
      btn.type = 'button';
      btn.dataset.key = key;
      btn.appendChild(el('span', 'app-dot'));
      btn.appendChild(el('span', 'app-label', (moduleMap.get(key) || {}).name || key));
      btn.addEventListener('click', () => {
        const win = windows.get(key);
        if (!win) return;
        if (win.state.minimized) {
          win.state.minimized = false;
          win.el.classList.remove('minimized');
          focusWindow(win);
          refreshWindow(win);
        } else if (win.el.classList.contains('active')) {
          minimizeWindow(win);
        } else {
          focusWindow(win);
        }
      });
      taskbarAppsEl.appendChild(btn);
    }
    const m = moduleMap.get(key);
    btn.querySelector('.app-label').textContent = (m && m.name) || key;
    btn.querySelector('.app-dot').className = 'app-dot' + dotClass(m).replace('dot', '');
    btn.classList.toggle('active', !w.state.minimized && w.el.classList.contains('active'));
    btn.classList.toggle('minimized', w.state.minimized);
    btn.title = ((m && m.name) || key) + (w.state.minimized ? '（已最小化）' : '');
  });
  taskbarAppsEl.querySelectorAll('.taskbar-app').forEach((n) => {
    if (!seen.has(n.dataset.key)) n.remove();
  });
}

/* ---------- 侧面板（模块列表 + 密钥 + 服务信息） ---------- */
function syncPanelList() {
  const seen = new Set();
  if (!modules.length) {
    setPanelModulesHint('未读取到模块');
    return;
  }
  const empty = panelModulesEl.querySelector('.panel-hint');
  if (empty) empty.remove();
  modules.forEach((m) => {
    seen.add(m.key);
    let node = panelModulesEl.querySelector(`.panel-module[data-key="${cssEscape(m.key)}"]`);
    if (!node) {
      node = el('button', 'panel-module');
      node.type = 'button';
      node.dataset.key = m.key;
      const icon = el('span', 'pm-icon');
      icon.textContent = iconText(m.name, m.key);
      node.appendChild(icon);
      node.appendChild(el('span', 'pm-name', m.name));
      node.appendChild(el('span', 'pm-sub'));
      node.addEventListener('click', () => openModule(m.key));
      panelModulesEl.appendChild(node);
    }
    node.querySelector('.pm-name').textContent = m.name;
    node.querySelector('.pm-sub').textContent =
      (m.collecting ? '采集中' : (m.connected ? '已连接' : '未连接')) + ' · ' + (m.total_points || 0) + ' 点';
  });
  panelModulesEl.querySelectorAll('.panel-module').forEach((n) => {
    if (!seen.has(n.dataset.key)) n.remove();
  });
}

function openPanel() {
  panelEl.classList.remove('hidden');
  startBtn.classList.add('active');
  startBtn.setAttribute('aria-expanded', 'true');
}

function closePanel() {
  panelEl.classList.add('hidden');
  startBtn.classList.remove('active');
  startBtn.setAttribute('aria-expanded', 'false');
}

function togglePanel() {
  if (panelEl.classList.contains('hidden')) openPanel();
  else closePanel();
}

/* ---------- 窗口数据刷新 ---------- */
function refreshAllWindows() {
  windows.forEach((w) => refreshWindow(w));
}

async function refreshWindow(w) {
  if (w.busy || w.state.minimized) return;
  w.busy = true;
  try {
    const [snap, series] = await Promise.all([
      api(`/api/modules/${encodeURIComponent(w.key)}`),
      api(`/api/modules/${encodeURIComponent(w.key)}/series?limit=${SERIES_LIMIT}`),
    ]);
    const m = moduleMap.get(w.key);
    if (m) {
      m.connected = snap.connected;
      m.collecting = snap.collecting;
      m.total_points = snap.total_points;
      m.name = snap.name || m.name;
    }
    w.els.state.textContent =
      (snap.collecting ? '采集中' : (snap.connected ? '已连接' : '未连接'));
    const yLabel = snap.y_label || '';
    const um = /\(([^()]*)\)\s*$/.exec(yLabel);
    const unit = um ? ' ' + um[1] : '';
    const latest = snap.latest && snap.latest.y !== undefined ? fmt(snap.latest.y) + unit : '—';
    w.els.stats.latest.textContent = latest;
    w.els.stats.state.textContent =
      (snap.collecting ? '采集中' : '已停止') + (snap.connected ? '' : ' · 未连接');
    w.els.stats.points.textContent = String(snap.total_points || 0);
    w.els.stats.ylabel.textContent = yLabel || '—';
    renderControls(w, snap.actions || []);
    w.els.params.textContent = typeof snap.params === 'string'
      ? snap.params
      : JSON.stringify(snap.params || {}, null, 1);
    drawChart(w, series.points || [], snap.x_label, yLabel);
    syncWindowStates();
  } catch (e) {
    w.els.params.textContent = '读取失败：' + e.message;
  } finally {
    w.busy = false;
  }
}

function syncWindowStates() {
  windows.forEach((w, key) => {
    const m = moduleMap.get(key);
    if (!m) return;
    w.els.state.textContent = m.collecting ? '采集中' : (m.connected ? '已连接' : '未连接');
  });
  updateTaskbar();
}

const ACTION_LABEL = {
  start: '开始采集', stop: '停止采集', toggle: '开始/停止',
  clear: '清空数据', tare: '去皮', calibrate: '校准',
  zero_cal: '零点校准', cancel_zero_cal: '取消零点校准',
};

function renderControls(w, actions) {
  const key = actions.join(',');
  if (w.els.toolbar.dataset.actions === key) return;
  w.els.toolbar.dataset.actions = key;
  w.els.toolbar.innerHTML = '';
  if (!actions.length) {
    w.els.toolbar.appendChild(el('span', 'panel-hint', '该模块无可用控制动作'));
    return;
  }
  actions.forEach((a) => {
    const btn = el('button', 'ctrl-btn', ACTION_LABEL[a] || a);
    btn.type = 'button';
    btn.addEventListener('click', () => sendAction(w, a, btn));
    w.els.toolbar.appendChild(btn);
  });
}

async function sendAction(w, action, btn) {
  if (w.busyCmd) return;
  w.busyCmd = true;
  if (btn) btn.disabled = true;
  const generic = ['start', 'stop', 'toggle'].includes(action);
  const url = generic
    ? `/api/modules/${encodeURIComponent(w.key)}/collect`
    : `/api/modules/${encodeURIComponent(w.key)}/command`;
  try {
    const d = await api(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    toast(d.message || '已执行：' + (ACTION_LABEL[action] || action));
    await refreshWindow(w);
  } catch (e) {
    toast('命令失败：' + e.message);
  } finally {
    w.busyCmd = false;
    if (btn) btn.disabled = false;
  }
}

/* ---------- ECharts 曲线（滚动窗口，自适应大小与暗色） ---------- */
function themeDark() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function getChart(w) {
  if (!w.chart) {
    if (typeof echarts === 'undefined') {
      w.els.chart.innerHTML = '<div class="win-msg">图表库加载失败：请按 Ctrl+F5 强制刷新页面</div>';
      throw new Error('echarts 未加载');
    }
    w.chart = echarts.init(w.els.chart, null, { renderer: 'canvas' });
    // 容器是 flex 布局，尺寸变化不触发 window.resize，须监听容器本身
    new ResizeObserver(() => w.chart && w.chart.resize()).observe(w.els.chart);
  }
  return w.chart;
}

function drawChart(w, points, xLabel, yLabel) {
  if (typeof echarts === 'undefined') return; // 库未加载时不重复刷错误提示
  // 容器尚无尺寸（最小化 / 布局未完成）时初始化会得到 0 尺寸画布
  if (w.els.chart.clientWidth === 0 || w.els.chart.clientHeight === 0) {
    if (w.chart) w.chart.resize();
    return;
  }
  const dark = themeDark();
  const axis = dark ? '#9aa0a8' : '#666';
  const split = dark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.08)';
  const c = getChart(w);
  w._lastDraw = { points, xLabel, yLabel };   // 系统主题切换时据此重绘

  const hasData = points && points.length >= 2;
  const option = {
    backgroundColor: 'transparent',
    animation: false,
    grid: { left: 52, right: 16, top: 26, bottom: 32 },
    title: hasData ? undefined : {
      text: '暂无数据（开始采集后这里会出现曲线）',
      left: 'center', top: 'middle',
      textStyle: { color: axis, fontSize: 12, fontWeight: 'normal' },
    },
    xAxis: {
      type: 'value',
      name: xLabel || '',
      nameLocation: 'end',
      nameTextStyle: { color: axis, fontSize: 11 },
      min: hasData ? (v) => v.min : 0,
      max: hasData ? (v) => (v.max === v.min ? v.min + 1 : v.max) : 1,
      axisLabel: { color: axis, fontSize: 11, formatter: fmt },
      axisLine: { lineStyle: { color: axis } },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: yLabel || '',
      nameTextStyle: { color: axis, fontSize: 11, align: 'left' },
      scale: true,
      axisLabel: { color: axis, fontSize: 11, formatter: fmt },
      axisLine: { lineStyle: { color: axis } },
      splitLine: { lineStyle: { color: split } },
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      valueFormatter: (v) => fmt(Number(v)),
    },
    series: [{
      type: 'line',
      showSymbol: false,
      lineStyle: { color: '#187aff', width: 2 },
      itemStyle: { color: '#187aff' },
      data: hasData ? points.map((p) => [p[0], Number(p[1])]) : [],
    }],
  };
  c.setOption(option, true);
}

/* ---------- 时钟 ---------- */
function updateClock() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  $('clock-time').textContent = p(d.getHours()) + ':' + p(d.getMinutes());
  $('clock-date').textContent =
    `${d.getMonth() + 1}月${d.getDate()}日 周${'日一二三四五六'[d.getDay()]}`;
}

/* ---------- 登录页（鉴权开启时拦截，参考路由器管理登录） ---------- */
const loginEl = $('login');
const loginInput = $('login-token');
const loginSubmitBtn = $('login-submit');
const loginHintEl = $('login-hint');

let pollingStarted = false;

function setLoginHint(text, kind) {
  loginHintEl.textContent = text;
  loginHintEl.className = 'login-hint' + (kind ? ' ' + kind : '');
}

function showLogin(errText) {
  loginEl.classList.remove('hidden');
  loginInput.value = '';
  loginInput.classList.remove('login-err');
  setLoginHint(errText || '密钥可在上位机「数据接口」设置页查看或重新生成',
               errText ? 'err' : '');
  setTimeout(() => loginInput.focus(), 60);
}

function closeLogin() {
  loginEl.classList.add('hidden');
}

/** 登录成功后把密钥写进地址栏：刷新 / 分享链接可直接进入 */
function putTokenInUrl(t) {
  try {
    const p = new URLSearchParams(location.search);
    p.set('token', t);
    history.replaceState(null, '', location.pathname + '?' + p.toString() + location.hash);
  } catch (e) { /* 忽略 */ }
}

/** 探测鉴权状态与已存密钥是否有效（独立 fetch，不触发 onAuthError 弹面板） */
async function probeAuth() {
  let resp;
  try {
    resp = await fetch('/api/auth/check', { headers: { 'X-Auth-Token': getToken() } });
  } catch (e) {
    throw new Error('无法连接数据接口');
  }
  if (resp.status === 401) return { ok: false, auth_enabled: true };
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  return resp.json();
}

/** 登录提交：校验通过才放行，并把密钥带进地址栏 */
async function doLogin() {
  const v = loginInput.value.trim();
  if (!v) {
    setLoginHint('请输入访问密钥', 'err');
    loginInput.focus();
    return;
  }
  loginSubmitBtn.disabled = true;
  try {
    const resp = await fetch('/api/auth/check', { headers: { 'X-Auth-Token': v } });
    if (resp.status === 401) throw new Error('密钥不正确，请重新输入');
    if (!resp.ok) throw new Error('服务异常（HTTP ' + resp.status + '）');
    setToken(v);
    putTokenInUrl(v);
    authState = 'ok';
    closeLogin();
    enterDashboard();
    toast('登录成功：地址已带上密钥，刷新或分享链接可直接进入');
  } catch (e) {
    setLoginHint(e.message, 'err');
    loginInput.classList.add('login-err');
    loginEl.classList.remove('shake');
    void loginEl.offsetWidth;   // 强制重排以重放抖动动画
    loginEl.classList.add('shake');
    loginInput.focus();
    loginInput.select();
  } finally {
    loginSubmitBtn.disabled = false;
  }
}

/** 登录放行后：同步密钥 UI 并启动数据轮询 */
function enterDashboard() {
  tokenInput.value = getToken();
  updateAuthUI();
  setTokenHint('已保存密钥 ' + maskToken(getToken()) + '，写操作（开始/停止采集等）已可用', 'ok');
  startPolling();
  refreshOverview();
}

function startPolling() {
  if (pollingStarted) return;
  pollingStarted = true;
  refreshOverview();
  setInterval(refreshOverview, POLL_OVERVIEW_MS);
  setInterval(() => {
    if (document.hidden) return;
    refreshAllWindows();
  }, POLL_DETAIL_MS);
}

function bindEvents() {
  startBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePanel(); });
  $('panel-close').addEventListener('click', closePanel);
  authBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    openPanel();
    tokenInput.focus();
    tokenInput.select();
  });
  tokenSubmitBtn.addEventListener('click', submitToken);
  tokenInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); submitToken(); }
  });
  // 登录页
  loginSubmitBtn.addEventListener('click', doLogin);
  loginInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); doLogin(); }
  });
  loginInput.addEventListener('input', () => {
    loginInput.classList.remove('login-err');
    if (loginHintEl.classList.contains('err')) {
      setLoginHint('密钥可在上位机「数据接口」设置页查看或重新生成');
    }
  });
  document.addEventListener('pointerdown', (e) => {
    if (panelEl.classList.contains('hidden')) return;
    if (panelEl.contains(e.target) || startBtn.contains(e.target) || authBtn.contains(e.target)) return;
    closePanel();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePanel();
  });
  // 系统主题切换时重绘曲线
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  const onTheme = () => windows.forEach((w) => {
    if (w.chart && w._lastDraw) {
      drawChart(w, w._lastDraw.points, w._lastDraw.xLabel, w._lastDraw.yLabel);
    }
  });
  if (mq.addEventListener) mq.addEventListener('change', onTheme);
  window.addEventListener('resize', () => {
    windows.forEach((w) => {
      if (w.chart) w.chart.resize();
      // 窗口变大出界时拉回可视区
      const b = desktopEl.getBoundingClientRect();
      const r = w.el.getBoundingClientRect();
      if (r.left > b.width - 80) w.el.style.left = Math.max(0, b.width - r.width) + 'px';
      if (r.top > b.height - 32) w.el.style.top = Math.max(0, b.height - 32) + 'px';
    });
  });
}

/** 启动门卫：先探测鉴权，再决定进桌面还是拦在登录页 */
async function startup() {
  updateClock();
  setInterval(updateClock, 1000);
  bindEvents();
  updateAuthUI();
  tokenInput.value = getToken();
  updateHint();
  let auth;
  try {
    auth = await probeAuth();
  } catch (e) {
    // 页面由同一服务托管，走到这里通常是代理/网络异常
    showLogin('无法连接数据接口：' + e.message);
    return;
  }
  if (!auth.auth_enabled) {        // 鉴权关闭：免登录直接进
    closeLogin();
    authDot.className = 'dot ok';
    authText.textContent = '鉴权已关闭';
    authBtn.title = '服务未开启访问鉴权，所有操作无需密钥';
    setTokenHint('服务未开启访问鉴权：读、写操作均无需密钥');
    startPolling();
    return;
  }
  if (auth.ok) {                   // 已带正确密钥（URL / 上次保存）
    closeLogin();
    enterDashboard();
    if (urlTokenApplied) {
      setTimeout(() => toast('已通过链接自动登录，可直接控制实验'), 400);
    }
    return;
  }
  showLogin();                     // 鉴权开启且无有效密钥 → 登录页
}

startup();