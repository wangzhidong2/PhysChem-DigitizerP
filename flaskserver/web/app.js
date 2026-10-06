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

/* ---------- 启动：支持 ?token=xxx 自动鉴权 ---------- */
// 书签形如 http://host:port/?token=xxx —— 打开即把密钥存入 localStorage
// 并从地址栏抹掉（避免密钥留在历史记录/分享链接里），然后正常初始化。
(function () {
  const p = new URLSearchParams(location.search);
  const t = p.get('token');
  if (t) {
    localStorage.setItem('pcd_token', t);
    p.delete('token');
    const qs = p.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
  }
})();

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

/* ---------- ECharts 曲线（滚动窗口，自适应大小与暗色） ---------- */
let chart = null;

function themeDark() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function getChart() {
  if (!chart) {
    if (typeof echarts === 'undefined') {
      // echarts.min.js 加载失败（旧缓存 HTML / 文件缺失）时给出可见提示而非静默空白
      chartEl.innerHTML = '<div class="msg">图表库加载失败：请按 Ctrl+F5 强制刷新页面</div>';
      throw new Error('echarts 未加载');
    }
    chart = echarts.init(chartEl, null, {renderer: 'canvas'});
    // #chart 是 flex 布局，容器尺寸变化不触发 window.resize，
    // 必须监听容器本身，否则 canvas 被 CSS 拉伸（文字巨大且模糊）
    new ResizeObserver(() => chart && chart.resize()).observe(chartEl);
  }
  return chart;
}

function drawChart(points, xLabel, yLabel) {
  if (typeof echarts === 'undefined') return; // 库未加载时不重复刷错误提示
  // 容器尚无尺寸（display:none / 布局未完成）时初始化会得到 0 尺寸画布，
  // 等 ResizeObserver 触发后再绘制
  if (chartEl.clientWidth === 0 || chartEl.clientHeight === 0) return;
  const dark = themeDark();
  const axis = dark ? '#9aa0a8' : '#666';
  const split = dark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.08)';
  const c = getChart();

  const hasData = points && points.length >= 2;
  const option = {
    backgroundColor: 'transparent',
    animation: false,
    grid: {left: 64, right: 20, top: 28, bottom: 36},
    title: hasData ? undefined : {
      text: '暂无数据（开始采集后这里会出现曲线）',
      left: 'center', top: 'middle',
      textStyle: {color: axis, fontSize: 13, fontWeight: 'normal'},
    },
    xAxis: {
      type: 'value',
      name: xLabel || '',
      nameLocation: 'end',
      nameTextStyle: {color: axis, fontSize: 11},
      min: hasData ? (v) => v.min : 0,
      max: hasData ? (v) => (v.max === v.min ? v.min + 1 : v.max) : 1,
      axisLabel: {color: axis, fontSize: 11, formatter: fmt},
      axisLine: {lineStyle: {color: axis}},
      splitLine: {show: false},
    },
    yAxis: {
      type: 'value',
      name: yLabel || '',
      nameTextStyle: {color: axis, fontSize: 11, align: 'left'},
      scale: true,
      axisLabel: {color: axis, fontSize: 11, formatter: fmt},
      axisLine: {lineStyle: {color: axis}},
      splitLine: {lineStyle: {color: split}},
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      valueFormatter: (v) => fmt(Number(v)),
    },
    series: [{
      type: 'line',
      showSymbol: false,
      lineStyle: {color: '#0078d4', width: 2},
      itemStyle: {color: '#0078d4'},
      data: hasData ? points.map((p) => [p[0], Number(p[1])]) : [],
    }],
  };
  c.setOption(option, true);
}

window.addEventListener('resize', () => {
  if (chart) chart.resize();
  if (currentKey) pollDetail();
});

function fmt(v) {
  if (!isFinite(v)) return '-';
  const a = Math.abs(v);
  if (a >= 1000) return v.toFixed(0);
  if (a >= 1) return v.toFixed(2);
  return v.toPrecision(2);
}

/* ---------- 启动 ---------- */
refreshModules();
setInterval(refreshModules, 3000);
