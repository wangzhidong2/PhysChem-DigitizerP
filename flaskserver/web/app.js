/* PhysChem 实验仪表盘 —— 原生 JS + Canvas，零依赖零 CDN
 * 数据源封装在 fetchSeries() 一处，将来换 SSE 只改这里。
 */
'use strict';

const POLL_MS = 1000;          // 轮询间隔
const SERIES_LIMIT = 2000;     // 序列降采样点数

const $ = (id) => document.getElementById(id);
const listEl = $('module-list');
const nameEl = $('detail-name');
const controlsEl = $('controls');
const chartEl = $('chart');
const paramsEl = $('params');

let modules = [];
let currentKey = null;
let pollTimer = null;

/* ---------- 数据源（唯一出口，将来换 SSE 只改这一处） ---------- */
async function api(path, opts) {
  const token = localStorage.getItem('pcd_token') || '';
  const headers = Object.assign({'X-Auth-Token': token}, (opts && opts.headers) || {});
  const resp = await fetch(path, Object.assign({headers}, opts));
  if (resp.status === 401) throw new Error('需要访问密钥（右上角输入后重试）');
  if (!resp.ok) {
    let msg = 'HTTP ' + resp.status;
    try { msg = (await resp.json()).message || msg; } catch (e) {}
    throw new Error(msg);
  }
  return resp.json();
}

async function fetchSeries(key, limit) {
  const d = await api(`/api/modules/${key}/series?limit=${limit}`);
  return d.points || [];
}

/* ---------- 模块列表 ---------- */
async function refreshModules() {
  try {
    const d = await api('/api/modules');
    modules = d.modules || [];
    renderList();
    if (!currentKey && modules.length) selectModule(modules[0].key);
    if (currentKey) pollDetail();
  } catch (e) {
    listEl.innerHTML = `<div class="msg">无法连接：${e.message}</div>`;
  }
}

function renderList() {
  listEl.innerHTML = '';
  modules.forEach((m) => {
    const item = document.createElement('div');
    item.className = 'module-item' + (m.key === currentKey ? ' active' : '');
    const dotCls = 'dot' + (m.collecting ? ' on' : '');
    item.innerHTML =
      `<div class="name"><span class="${dotCls}"></span>${m.name}</div>` +
      `<div class="sub">${m.connected ? '已连接' : '未连接'} · ${m.total_points} 点</div>`;
    item.onclick = () => selectModule(m.key);
    listEl.appendChild(item);
  });
}

/* ---------- 模块详情 ---------- */
function selectModule(key) {
  currentKey = key;
  renderList();
  pollDetail();
}

async function pollDetail() {
  if (!currentKey) return;
  try {
    const [snap, points] = await Promise.all([
      api(`/api/modules/${currentKey}?points=1`),
      fetchSeries(currentKey, SERIES_LIMIT),
    ]);
    nameEl.textContent = snap.name || currentKey;
    paramsEl.textContent = typeof snap.params === 'string'
      ? snap.params : JSON.stringify(snap.params, null, 1);
    renderControls(snap.actions || []);
    drawChart(points, snap.x_label, snap.y_label);
    // 列表里的点数/状态也顺带更新
    const m = modules.find((x) => x.key === currentKey);
    if (m) { m.total_points = snap.total_points; m.collecting = snap.collecting; renderList(); }
  } catch (e) {
    paramsEl.textContent = '读取失败：' + e.message;
  }
}

function renderControls(actions) {
  controlsEl.innerHTML = '';
  const label = {start: '开始采集', stop: '停止采集', toggle: '开始/停止',
                 clear: '清空数据', tare: '去皮', calibrate: '校准',
                 zero_cal: '零点校准'};
  actions.forEach((a) => {
    const btn = document.createElement('button');
    btn.textContent = label[a] || a;
    btn.onclick = () => sendAction(a);
    controlsEl.appendChild(btn);
  });
}

async function sendAction(action) {
  const isGeneric = ['start', 'stop', 'toggle'].includes(action);
  const url = isGeneric
    ? `/api/modules/${currentKey}/collect`
    : `/api/modules/${currentKey}/command`;
  try {
    const d = await api(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action}),
    });
    paramsEl.textContent = d.message || '已执行';
    pollDetail();
  } catch (e) {
    paramsEl.textContent = '命令失败：' + e.message;
  }
}

/* ---------- Canvas 曲线（滚动窗口，自适应大小与暗色） ---------- */
function drawChart(points, xLabel, yLabel) {
  const ctx = chartEl.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = chartEl.clientWidth, h = chartEl.clientHeight;
  if (chartEl.width !== w * dpr) { chartEl.width = w * dpr; chartEl.height = h * dpr; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const axis = dark ? '#9aa0a8' : '#666';
  const line = '#0078d4';
  const pad = {l: 56, r: 14, t: 14, b: 30};
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;

  if (!points || points.length < 2) {
    ctx.fillStyle = axis;
    ctx.font = '13px sans-serif';
    ctx.fillText('暂无数据（开始采集后这里会出现曲线）', pad.l, h / 2);
    return;
  }

  const xs = points.map((p) => p[0]), ys = points.map((p) => Number(p[1]));
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (x1 - x0 === 0) { x1 = x0 + 1; }
  if (y1 - y0 === 0) { y1 = y0 + 1; }
  const yPad = (y1 - y0) * 0.08;
  y0 -= yPad; y1 += yPad;

  const px = (t) => pad.l + ((t - x0) / (x1 - x0)) * iw;
  const py = (v) => pad.t + (1 - (v - y0) / (y1 - y0)) * ih;

  // 坐标轴与刻度
  ctx.strokeStyle = axis; ctx.fillStyle = axis;
  ctx.lineWidth = 1; ctx.font = '11px sans-serif';
  ctx.strokeRect(pad.l, pad.t, iw, ih);
  for (let i = 0; i <= 4; i++) {
    const vy = y0 + ((y1 - y0) * i) / 4;
    const yy = py(vy);
    ctx.fillText(fmt(vy), 4, yy + 4);
    const vx = x0 + ((x1 - x0) * i) / 4;
    ctx.fillText(fmt(vx), px(vx) - 12, h - 10);
  }
  // 轴标题
  ctx.fillText(yLabel || '', 4, pad.t - 2);
  ctx.fillText(xLabel || '', w - pad.r - 60, h - 10);

  // 曲线
  ctx.strokeStyle = line; ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((p, i) => {
    const X = px(p[0]), Y = py(Number(p[1]));
    i === 0 ? ctx.moveTo(X, Y) : ctx.lineTo(X, Y);
  });
  ctx.stroke();
}

function fmt(v) {
  if (!isFinite(v)) return '-';
  const a = Math.abs(v);
  if (a >= 1000) return v.toFixed(0);
  if (a >= 1) return v.toFixed(2);
  return v.toPrecision(2);
}

/* ---------- 启动 ---------- */
window.addEventListener('resize', () => { if (currentKey) pollDetail(); });
refreshModules();
setInterval(refreshModules, 3000);
