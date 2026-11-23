# -*- coding: utf-8 -*-
"""
mcp_report.py — 实验报告生成（Markdown + 自包含 HTML）

只做排版：统计量、SVG 曲线、结论段落都由这里生成，不依赖任何第三方库。
报告里的"结论/目的/步骤"由 AI 通过工具参数写入，本模块负责把它们和数据
放在一起，产出可直接交给老师/存档的文件。

输出目录：环境变量 PCD_REPORT_DIR，缺省 ~/PhysChemReports
"""

import html
import math
import os
import time
from pathlib import Path

#: 单条曲线最多画多少个点（再多也看不出差别，只会把文件撑大）
MAX_PLOT_POINTS = 900

_CN_NUM = '一二三四五六七八九十'


def _sections(items):
    """按"有内容才出章"的规则生成连续编号的章节。

    items: [(标题, 正文), ...]。正文为空则跳过该章，且编号顺延——
    否则只填结论时会出现"一、实验目的"缺失、直接跳到"四、结论"的跳号。
    """
    out, idx = [], 0
    for title, body in items:
        if body is None:
            continue
        text = body if isinstance(body, str) else str(body)
        if not text.strip():
            continue
        out.append(('%s、%s' % (_CN_NUM[idx] if idx < len(_CN_NUM) else idx + 1, title),
                    text))
        idx += 1
    return out


def report_root():
    return Path(os.environ.get('PCD_REPORT_DIR')
                or (Path.home() / 'PhysChemReports'))


def _num(value, digits=4):
    """数值格式化：去掉浮点尾巴，None 显示为 —。"""
    if value is None:
        return '—'
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(v) or math.isinf(v):
        return '—'
    if v != 0 and (abs(v) < 1e-3 or abs(v) >= 1e5):
        return '%.*g' % (digits, v)
    text = ('%.*f' % (digits, v)).rstrip('0').rstrip('.')
    return text if text not in ('', '-0') else '0'


def compute_stats(channels):
    """按通道计算统计量。返回 [{id,name,n,mean,std,min,max,drift,rel_std}]。"""
    out = []
    for ch in channels or []:
        pts = ch.get('points') or []
        ys = [p[1] for p in pts if isinstance(p, (list, tuple)) and len(p) > 1
              and isinstance(p[1], (int, float))]
        if not ys:
            out.append({'id': ch.get('id'), 'name': ch.get('name'), 'n': 0})
            continue
        n = len(ys)
        mean = sum(ys) / n
        var = sum((y - mean) ** 2 for y in ys) / (n - 1) if n > 1 else 0.0
        std = math.sqrt(max(0.0, var))
        half = n // 2
        drift = 0.0
        if half >= 2:
            first = sum(ys[:half]) / half
            second = sum(ys[half:]) / (n - half)
            drift = second - first
        rel = (std / abs(mean)) if mean else 0.0
        out.append({
            'id': ch.get('id'), 'name': ch.get('name'), 'n': n,
            'mean': mean, 'std': std, 'min': min(ys), 'max': max(ys),
            'drift': drift, 'rel_std': rel,
        })
    return out


def quality_notes(stats):
    """给 AI 的数据质量提示（只描述事实，不下结论）。"""
    notes = []
    for s in stats:
        if s.get('n', 0) == 0:
            notes.append('%s：没有数据点。' % (s.get('name') or '通道'))
            continue
        if s['n'] < 10:
            notes.append('%s：仅 %d 点，统计意义有限。' % (s.get('name'), s['n']))
        if s.get('rel_std', 0) > 0.05:
            notes.append('%s：相对波动 %.1f%%，读数不稳定或存在干扰。'
                         % (s.get('name'), s['rel_std'] * 100))
        if s.get('std') and abs(s.get('drift', 0)) > 2 * s['std']:
            notes.append('%s：前后半段均值相差 %.4g，存在系统性漂移，可能尚未达到平衡。'
                         % (s.get('name'), s['drift']))
    return notes


def _svg(channels, x_label='时间 (s)', y_label='', width=860, height=340):
    """手写 SVG 多通道折线图（不依赖 matplotlib，报告单文件可离线打开）。"""
    pad_l, pad_r, pad_t, pad_b = 58, 18, 34, 42
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    series = []
    for ch in channels or []:
        pts = [p for p in (ch.get('points') or [])
               if isinstance(p, (list, tuple)) and len(p) > 1
               and isinstance(p[0], (int, float)) and isinstance(p[1], (int, float))]
        if not pts:
            continue
        if len(pts) > MAX_PLOT_POINTS:
            step = len(pts) / float(MAX_PLOT_POINTS)
            pts = [pts[int(i * step)] for i in range(MAX_PLOT_POINTS)]
        series.append({'name': ch.get('name') or '通道',
                       'color': ch.get('color') or '#0078d4', 'points': pts})

    if not series:
        return ('<svg viewBox="0 0 %d %d" width="100%%" xmlns="http://www.w3.org/2000/svg">'
                '<text x="%d" y="%d" text-anchor="middle" fill="#8a8a8a" '
                'font-size="14">无数据</text></svg>'
                % (width, height, width // 2, height // 2))

    xs = [p[0] for s in series for p in s['points']]
    ys = [p[1] for s in series for p in s['points']]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x1 - x0 < 1e-9:
        x1 = x0 + 1.0
    if y1 - y0 < 1e-9:
        pad = max(abs(y1) * 0.05, 0.5)
        y0, y1 = y0 - pad, y1 + pad
    else:
        pad = (y1 - y0) * 0.08
        y0, y1 = y0 - pad, y1 + pad

    def tick(v, span):
        digits = 0 if span >= 20 else 1 if span >= 2 else 2 if span >= 0.2 else 3
        return '%.*f' % (digits, v)

    def sx(x):
        return pad_l + (x - x0) / (x1 - x0) * plot_w

    def sy(y):
        return pad_t + plot_h - (y - y0) / (y1 - y0) * plot_h

    parts = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" '
             'xmlns="http://www.w3.org/2000/svg">' % (width, height),
             '<rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/>' % (width, height)]

    # 横向网格 + y 轴刻度
    for i in range(5):
        yv = y0 + (y1 - y0) * i / 4.0
        yy = sy(yv)
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#e8e8e8" '
                     'stroke-width="1"/>' % (pad_l, yy, pad_l + plot_w, yy))
        parts.append('<text x="%d" y="%.1f" text-anchor="end" font-size="11" '
                     'fill="#666">%s</text>' % (pad_l - 8, yy + 4, tick(yv, y1 - y0)))

    # 纵向网格 + x 轴刻度
    for i in range(6):
        xv = x0 + (x1 - x0) * i / 5.0
        xx = sx(xv)
        parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#f0f0f0" '
                     'stroke-width="1"/>' % (xx, pad_t, xx, pad_t + plot_h))
        parts.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="11" '
                     'fill="#666">%s</text>' % (xx, pad_t + plot_h + 16, tick(xv, x1 - x0)))

    parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#bbb" stroke-width="1"/>'
                 % (pad_l, pad_t + plot_h, pad_l + plot_w, pad_t + plot_h))

    # 曲线
    for s in series:
        d = ' '.join(('M' if i == 0 else 'L') + '%.1f,%.1f' % (sx(x), sy(y))
                     for i, (x, y) in enumerate(s['points']))
        parts.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.8" '
                     'stroke-linejoin="round" stroke-linecap="round"/>'
                     % (d, s['color']))

    # 图例
    lx = pad_l
    for s in series:
        parts.append('<line x1="%d" y1="18" x2="%d" y2="18" stroke="%s" stroke-width="3"/>'
                     % (lx, lx + 18, s['color']))
        parts.append('<text x="%d" y="22" font-size="12" fill="#444">%s</text>'
                     % (lx + 24, html.escape(s['name'])))
        lx += 24 + 12 * len(s['name']) + 24

    # 轴标题
    parts.append('<text x="%d" y="%d" text-anchor="middle" font-size="12" '
                 'fill="#555">%s</text>'
                 % (pad_l + plot_w // 2, height - 6, html.escape(x_label)))
    if y_label:
        parts.append('<text x="14" y="%d" text-anchor="middle" font-size="12" '
                     'fill="#555" transform="rotate(-90 14 %d)">%s</text>'
                     % (pad_t + plot_h // 2, pad_t + plot_h // 2, html.escape(y_label)))
    parts.append('</svg>')
    return ''.join(parts)


def _meta_rows(ctx):
    st = ctx.get('status') or {}
    state = st.get('state') or {}
    conn = st.get('connection') or {}
    rows = [
        ('模块', '%s（%s）' % (st.get('name') or ctx.get('module'),
                              ctx.get('module'))),
        ('数据后端', ctx.get('backend') or '—'),
        ('生成时间', ctx.get('generated_at') or ''),
        ('数据点数', str(state.get('points_n', 0))),
        ('连接方式', ('%s %s' % (conn.get('mode') or '—',
                              conn.get('port') or '')).strip()),
        ('通道数', str(len(state.get('channels') or []))),
    ]
    return rows


def _stats_table(stats):
    head = ('| 通道 | 点数 | 均值 | 标准差 | 最小 | 最大 | 前后漂移 |\n'
            '|---|---:|---:|---:|---:|---:|---:|\n')
    lines = []
    for s in stats:
        if not s.get('n'):
            lines.append('| %s | 0 | — | — | — | — | — |' % (s.get('name') or '—'))
            continue
        lines.append('| %s | %d | %s | %s | %s | %s | %s |' % (
            s.get('name') or '—', s['n'], _num(s['mean']), _num(s['std']),
            _num(s['min']), _num(s['max']), _num(s['drift'])))
    return head + '\n'.join(lines) + '\n'


def _preview_table(channels, limit=12):
    ch = next((c for c in channels or [] if c.get('points')), None)
    if not ch:
        return '_（无数据）_\n'
    pts = ch['points'][:limit]
    out = ['| # | 时间 (s) | 数值 |', '|---:|---:|---:|']
    for i, p in enumerate(pts, 1):
        out.append('| %d | %s | %s |' % (i, _num(p[0], 3), _num(p[1], 4)))
    return '\n'.join(out) + '\n'


def build_markdown(ctx):
    stats = ctx.get('stats') or []
    notes = quality_notes(stats)
    channels = (ctx.get('series') or {}).get('channels')
    blocks = _sections([
        ('实验目的', ctx.get('objective')),
        ('实验步骤', ctx.get('procedure')),
        ('数据统计', _stats_table(stats) if stats else ''),
        ('数据预览', _preview_table(channels) if channels else ''),
        ('结论', ctx.get('conclusion') or '（待补充）'),
        ('备注', ctx.get('notes')),
    ])
    lines = ['# %s' % (ctx.get('title') or '实验报告'), '']
    for k, v in _meta_rows(ctx):
        lines.append('- **%s**：%s' % (k, v))
    lines.append('')
    for title, body in blocks:
        lines += ['## %s' % title, '', body.strip(), '']
        if title.endswith('数据统计') and notes:
            lines += ['> **数据质量提示**', '>']
            lines += ['> - %s' % n for n in notes]
            lines.append('')
    lines += ['---', '',
              '由 PhysChem-Digitizer 的 MCP 接口生成；数据文件：%s'
              % (ctx.get('csv_path') or '未导出'), '']
    return '\n'.join(lines)


def build_html(ctx):
    st = ctx.get('status') or {}
    stats = ctx.get('stats') or []
    notes = quality_notes(stats)
    channels = ctx.get('series', {}).get('channels') or []

    def esc(v):
        return html.escape('' if v is None else str(v))

    cards = []
    for s in stats:
        if not s.get('n'):
            continue
        cards.append(
            '<div class="card"><div class="card-name">%s</div>'
            '<div class="card-main">%s</div>'
            '<div class="card-sub">σ = %s · n = %d · 漂移 %s</div></div>'
            % (esc(s.get('name')), esc(_num(s['mean'])), esc(_num(s['std'])),
               s['n'], esc(_num(s['drift']))))

    rows = ''.join('<tr><th>%s</th><td>%s</td></tr>' % (esc(k), esc(v))
                   for k, v in _meta_rows(ctx))
    note_html = ''
    if notes:
        note_html = ('<div class="notes"><strong>数据质量提示</strong><ul>%s</ul></div>'
                     % ''.join('<li>%s</li>' % esc(n) for n in notes))

    def prose(body):
        """正文段落：.prose 已是 pre-wrap，不要再把 \\n 换成 <br>（会变成双倍行距）。"""
        if not body or not str(body).strip():
            return ''
        return '<div class="prose">%s</div>' % esc(body).strip()

    stats_block = ''
    if cards:
        stats_block += '<div class="cards">%s</div>' % ''.join(cards)
    if note_html:
        stats_block += note_html
    has_points = any((c.get('points') for c in channels))
    chart_block = ('<div class="chart">%s</div>' % _svg(
        channels, st.get('x_label') or '时间 (s)', st.get('y_label') or '')
        if has_points else '')

    # 只保留有内容的章节，编号顺延（与 Markdown 一致）
    body_parts, idx = [], 0
    for title, block in (('实验目的', prose(ctx.get('objective'))),
                         ('实验步骤', prose(ctx.get('procedure'))),
                         ('数据统计', stats_block),
                         ('数据曲线', chart_block),
                         ('结论', prose(ctx.get('conclusion'))),
                         ('备注', prose(ctx.get('notes')))):
        if not block:
            continue
        no = _CN_NUM[idx] if idx < len(_CN_NUM) else str(idx + 1)
        body_parts.append('<section><h2>%s、%s</h2>%s</section>'
                          % (no, esc(title), block))
        idx += 1
    sections = '\n'.join(body_parts)

    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --fg:#1f2328; --muted:#6b7280; --line:#e6e8eb; --accent:#0078d4; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:32px 24px 64px; background:#f6f7f9; color:var(--fg);
  font-family:"HarmonyOS Sans SC","Microsoft YaHei",system-ui,-apple-system,sans-serif;
  line-height:1.7; }}
.page {{ max-width:940px; margin:0 auto; background:#fff; border:1px solid var(--line);
  border-radius:14px; padding:40px 44px 48px; box-shadow:0 2px 16px rgba(0,0,0,.04); }}
h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:.3px; }}
.sub {{ color:var(--muted); font-size:13px; margin-bottom:26px; }}
h2 {{ font-size:17px; margin:32px 0 12px; padding-left:10px;
  border-left:3px solid var(--accent); }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }}
th {{ color:var(--muted); font-weight:500; width:132px; }}
.cards {{ display:flex; gap:14px; flex-wrap:wrap; margin:14px 0 6px; }}
.card {{ flex:1 1 180px; border:1px solid var(--line); border-radius:10px;
  padding:14px 16px; background:#fafbfc; }}
.card-name {{ font-size:12px; color:var(--muted); }}
.card-main {{ font-size:26px; font-weight:600; font-variant-numeric:tabular-nums; }}
.card-sub {{ font-size:12px; color:var(--muted); margin-top:2px; }}
.chart {{ border:1px solid var(--line); border-radius:10px; padding:10px; margin-top:8px; }}
.prose {{ white-space:pre-wrap; }}
.notes {{ background:#fff8e6; border:1px solid #f0d9a8; border-radius:10px;
  padding:12px 16px; font-size:13px; margin:16px 0; }}
.notes ul {{ margin:6px 0 0 18px; padding:0; }}
footer {{ margin-top:36px; padding-top:14px; border-top:1px solid var(--line);
  color:var(--muted); font-size:12px; }}
@media print {{ body {{ background:#fff; padding:0; }} .page {{ border:0; box-shadow:none; }} }}
</style></head><body><div class="page">
<h1>{title}</h1>
<div class="sub">{name} · {module} · {generated_at}</div>
<table>{rows}</table>
{sections}
<footer>由 PhysChem-Digitizer MCP 接口生成 · 数据后端 {backend} · 数据文件 {csv}</footer>
</div></body></html>""".format(
        title=esc(ctx.get('title') or '实验报告'),
        name=esc(st.get('name') or ''),
        module=esc(ctx.get('module') or ''),
        generated_at=esc(ctx.get('generated_at') or ''),
        rows=rows,
        sections=sections,
        backend=esc(ctx.get('backend') or ''),
        csv=esc(ctx.get('csv_path') or '未导出'),
    )


def write_report(ctx, out_dir=None, stem=None):
    """写 Markdown + HTML 两个文件，返回路径信息。"""
    root = Path(out_dir) if out_dir else report_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    base = stem or '%s_%s' % (ctx.get('module') or 'report', stamp)
    md_path = root / (base + '.md')
    html_path = root / (base + '.html')
    md_path.write_text(build_markdown(ctx), encoding='utf-8')
    html_path.write_text(build_html(ctx), encoding='utf-8')

    data_dir = root / 'data'
    if ctx.get('csv_path'):
        data_dir.mkdir(exist_ok=True)

    return {
        'markdown': str(md_path),
        'html': str(html_path),
        'dir': str(root),
        'bytes': {'markdown': md_path.stat().st_size, 'html': html_path.stat().st_size},
    }
