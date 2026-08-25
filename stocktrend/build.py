# -*- coding: utf-8 -*-
"""
可复用模板：暗色金融终端风单文件 HTML 生成器（零 JS，移动端 Safari 可用）。

用法：
  1. 编辑同目录 data.json（数据源：个股/组合/板块/文案）。
  2. 运行 `python build.py` 生成 index.html。

布局（CSS + 8 模块弹窗 + 卡片 + 达标名单 + 组合）固定在本文件；
数据（行情/财务/文案/板块/组合）全部来自 data.json，改数据即可换市场，无需改布局。
"""

import json, os

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system,'PingFang SC','Helvetica Neue',sans-serif; background:#0d1117; color:#c9d1d9; line-height:1.6; }
.container { max-width: 860px; margin: 0 auto; padding: 16px; }
.header { background:linear-gradient(135deg,#161b22,#1a1a3e); border:1px solid #30363d; border-radius:16px; padding:26px 22px; margin-bottom:14px; text-align:center; }
.header .tag { display:inline-block; font-size:11px; color:#58a6ff; background:rgba(88,166,255,.1); border:1px solid rgba(88,166,255,.3); padding:3px 12px; border-radius:20px; margin-bottom:10px; }
.header h1 { font-size:23px; color:#f0c040; margin-bottom:6px; }
.header .subtitle { font-size:13px; color:#8b949e; }
.header .date { font-size:11px; color:#6e7681; margin-top:8px; }
.sector { border-radius:12px; padding:14px; margin-bottom:12px; }
.sector h2 { font-size:15px; margin-bottom:10px; }
.sector-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:8px; }
.sector-consumer { background:linear-gradient(135deg,#1c1a0e,#1a1a2e); border:1px solid #3d3520; }
.sector-consumer h2 { color:#f0c040; }
.sector-cycle { background:linear-gradient(135deg,#1c1410,#1a1414); border:1px solid #3d2820; }
.sector-cycle h2 { color:#ff8c42; }
.sector-tech { background:linear-gradient(135deg,#0e1c14,#0e1a1c); border:1px solid #1a3d2e; }
.sector-tech h2 { color:#3fb950; }
.sector-finance { background:linear-gradient(135deg,#0e141c,#0e141a); border:1px solid #1a2d3d; }
.sector-finance h2 { color:#58a6ff; }
.sub-group { grid-column:span 2; }
.sub-group .sub-h { font-size:12px; color:#8b949e; margin:8px 0 6px; padding-left:6px; border-left:2px solid #30363d; }
.stock-card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px 12px; transition:transform .15s,box-shadow .15s; cursor:pointer; display:block; min-width:0; }
.stock-card:hover { transform:translateY(-2px); box-shadow:0 4px 16px rgba(88,166,255,.15); border-color:#58a6ff; }
.stock-card .industry { font-size:10px; color:#6e7681; }
.stock-card .name { font-size:13px; font-weight:bold; color:#e6edf3; margin:3px 0; }
.stock-card .data { font-size:10px; }
.stock-card .data .good { color:#3fb950; }
.stock-card .data .up { color:#f85149; }
.stock-card .data .down { color:#3fb950; }
.stock-card .yt { font-size:10px; font-weight:bold; margin-top:3px; }
.stock-card .scoremark { font-size:10px; color:#f0c040; margin-top:3px; }
.border-yellow { border-left:3px solid #e8b923; }
.border-blue { border-left:3px solid #2196f3; }
.border-orange { border-left:3px solid #ff9800; }
.border-green { border-left:3px solid #00c853; }
.border-purple { border-left:3px solid #9c27b0; }
.border-red { border-left:3px solid #f44336; }
.border-brown { border-left:3px solid #795548; }
.border-gray { border-left:3px solid #6e7681; }
.databadge { background:#1c1408; border:1px solid #3d2810; color:#d29922; font-size:11px; padding:8px 12px; border-radius:8px; line-height:1.6; margin-bottom:14px; }
.databadge b { color:#f0c040; }
.disclaimer { background:#1c1408; border:1px solid #3d2810; border-radius:12px; padding:14px; margin:14px 0 18px; }
.disclaimer p { color:#d29922; font-size:11px; line-height:1.7; }
.footer { text-align:center; padding:16px; color:#6e7681; font-size:11px; }
.stock-item { position:relative; }
.modal-toggle { position:absolute; width:0; height:0; opacity:0; pointer-events:none; }
.modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,.78); display:none; overflow-y:auto; -webkit-overflow-scrolling:touch; padding:24px; z-index:9999; }
.modal-toggle:checked ~ .modal-overlay { display:block; }
.modal-backdrop { position:fixed; inset:0; cursor:default; z-index:1; }
.modal { position:relative; z-index:2; max-width:820px; margin:0 auto 24px; background:#0d1117; border:1px solid #30363d; border-radius:16px; box-shadow:0 20px 60px rgba(0,0,0,.5); }
.modal-x { position:sticky; top:0; display:flex; justify-content:flex-end; align-items:center; gap:10px; padding:10px 14px; background:linear-gradient(#0d1117 75%, rgba(13,17,23,0)); z-index:3; }
.modal-close { background:rgba(255,255,255,.08); border:1px solid #30363d; color:#c9d1d9; font-size:13px; padding:6px 14px; border-radius:8px; cursor:pointer; }
.modal-close:hover { background:rgba(248,81,73,.15); border-color:#f85149; color:#f85149; }
.modal-x .hint { font-size:11px; color:#6e7681; }
.modal-body { padding:0 18px 20px; }
.stock-head { background:linear-gradient(135deg,#161b22,#1a1a3e); border:1px solid #30363d; border-radius:16px; padding:20px; margin-bottom:14px; }
.stock-head .code { font-size:12px; color:#8b949e; }
.stock-head h1 { font-size:22px; color:#f0c040; margin:4px 0; }
.stock-head .en { font-size:13px; color:#8b949e; margin-bottom:4px; }
.stock-head .ind { font-size:13px; color:#58a6ff; }
.scorepill { display:inline-block; margin-top:10px; background:#238636; color:#fff; font-weight:bold; padding:4px 12px; border-radius:20px; font-size:14px; }
.module { background:#161b22; border:1px solid #30363d; border-radius:12px; padding:16px; margin-bottom:12px; }
.module h2 { font-size:15px; color:#58a6ff; margin-bottom:10px; display:flex; align-items:center; gap:6px; }
.module h2 .num { background:#21262d; color:#58a6ff; width:22px; height:22px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:12px; }
.kv { display:grid; grid-template-columns:1fr 1fr; gap:8px 16px; font-size:13px; }
.kv .k { color:#8b949e; }
.kv .v { color:#e6edf3; }
.kv .v.good { color:#3fb950; }
.kv .v.warn { color:#d29922; }
.kv .v.bad { color:#f85149; }
.kv .v.up { color:#f85149; }
.kv .v.down { color:#3fb950; }
.kv .v.flat { color:#8b949e; }
.conclusion-bar { display:flex; flex-wrap:wrap; align-items:center; gap:10px; padding:12px 14px; border-radius:10px; margin-bottom:8px; }
.conclusion-bar.ok { background:rgba(35,134,54,.15); border:1px solid #238636; }
.conclusion-bar.mid { background:rgba(210,153,34,.12); border:1px solid #3d3520; }
.conclusion-bar.wait { background:rgba(248,81,73,.12); border:1px solid #3d2820; }
.conclusion-bar .cb-tag { font-size:15px; font-weight:bold; padding:3px 12px; border-radius:20px; color:#fff; }
.conclusion-bar.ok .cb-tag { background:#238636; }
.conclusion-bar.mid .cb-tag { background:#d29922; }
.conclusion-bar.wait .cb-tag { background:#f85149; }
.conclusion-bar .cb-reason { font-size:13px; color:#c9d1d9; flex:1; min-width:200px; }
.note { font-size:12px; color:#8b949e; background:#0d1117; border-left:3px solid #30363d; padding:8px 12px; border-radius:0 8px 8px 0; margin-top:10px; }
.risk { font-size:13px; color:#f85149; padding:6px 0; border-bottom:1px dashed #30363d; }
.risk:last-child { border-bottom:none; }
.summary { font-size:13px; color:#c9d1d9; line-height:1.9; }
/* 参考站对齐：买卖决策子模块 */
.sub-h { font-size:14px; color:#c9d1d9; margin:16px 0 8px; padding-left:10px; border-left:3px solid #388bfd; font-weight:600; }
.sub-h:first-of-type { margin-top:4px; }
.verdict { font-size:17px; font-weight:bold; padding:11px 14px; border-radius:10px; margin-bottom:8px; }
.verdict.ok { background:rgba(35,134,54,0.15); color:#3fb950; border:1px solid #238636; }
.verdict.mid { background:rgba(210,153,34,0.12); color:#d29922; border:1px solid #3d3520; }
.verdict.wait { background:rgba(248,81,73,0.12); color:#f85149; border:1px solid #3d2820; }
.reason { font-size:13px; color:#8b949e; line-height:1.7; }
.tag-row { margin-top:10px; }
.tag { display:inline-block; background:#21262d; color:#8b949e; font-size:11px; padding:2px 10px; border-radius:10px; margin:2px 4px 2px 0; }
.tier-table { width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }
.tier-table th, .tier-table td { padding:8px 6px; text-align:center; border-bottom:1px solid #30363d; }
.tier-table th { color:#8b949e; font-weight:normal; background:#0d1117; }
.tier-table td:first-child { text-align:left; color:#8b949e; }
.metric-cards { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:14px; }
.metric-card { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:12px 10px; text-align:center; }
.metric-card .mc-k { font-size:11px; color:#8b949e; }
.metric-card .mc-v { font-size:20px; font-weight:bold; color:#e6edf3; margin:4px 0 2px; white-space:nowrap; }
.metric-card .mc-v .mc-u { font-size:11px; font-weight:normal; color:#8b949e; margin-left:2px; }
.metric-card .mc-v.good { color:#3fb950; }
.metric-card .mc-s { font-size:11px; color:#8b949e; }
.metric-card .mc-s.up { color:#f85149; }
.metric-card .mc-s.down { color:#3fb950; }
.metric-card .mc-v.bad { color:#f85149; }
.hist-table { width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }
.hist-table th, .hist-table td { padding:8px 6px; text-align:center; border-bottom:1px solid #30363d; }
.hist-table th { color:#8b949e; font-weight:normal; background:#0d1117; }
.hist-table td:first-child, .hist-table th:first-child { text-align:left; color:#8b949e; }
.hist-table tr:last-child td { border-bottom:none; }
.hist-table .v.good { color:#3fb950; font-weight:bold; }
.hist-table .v.warn { color:#d29922; }
.hist-table .v.bad { color:#f85149; }
.mine-box { font-size:16px; font-weight:bold; padding:10px 14px; border-radius:10px; margin-bottom:8px; }
.mine-box.pass { background:rgba(35,134,54,.15); color:#3fb950; border:1px solid #238636; }
.mine-box.warn { background:rgba(210,153,34,.12); color:#d29922; border:1px solid #3d3520; }
.mine-box.fail { background:rgba(248,81,73,.12); color:#f85149; border:1px solid #3d2820; }
.mine-reasons { list-style:none; font-size:12px; color:#c9d1d9; line-height:1.9; margin:0; padding-left:0; }
.mine-reasons li { padding-left:16px; position:relative; }
.mine-reasons li:before { content:"•"; color:#58a6ff; position:absolute; left:2px; }
.cover-box { display:flex; align-items:center; gap:14px; background:#0d1f0d; border:1px solid #1a3d2e; border-radius:10px; padding:12px 14px; margin-top:12px; }
.cover-box .cover-num { font-size:22px; font-weight:bold; color:#3fb950; white-space:nowrap; }
.cover-box .cover-txt { font-size:12px; color:#c9d1d9; line-height:1.6; }
.sustain-score { display:flex; align-items:center; gap:14px; background:#0d1f0d; border:1px solid #1a3d2e; border-radius:10px; padding:12px 14px; margin-bottom:10px; }
.sustain-score.mid { background:#1c1a0e; border-color:#3d3520; }
.sustain-score.bad { background:#1c1408; border-color:#3d2810; }
.sustain-score .ss-num { font-size:28px; font-weight:bold; color:#3fb950; }
.sustain-score.mid .ss-num { color:#d29922; }
.sustain-score.bad .ss-num { color:#f85149; }
.sustain-score .ss-den { font-size:14px; color:#8b949e; font-weight:normal; }
.sustain-score .ss-star { font-size:18px; color:#f0c040; letter-spacing:2px; }
.ss-reasons { list-style:none; font-size:12px; color:#c9d1d9; line-height:1.9; margin:4px 0 0; padding-left:0; }
.ss-reasons li { padding-left:16px; position:relative; }
.ss-reasons li:before { content:"•"; color:#3fb950; position:absolute; left:2px; }
.income-box { display:flex; align-items:center; gap:14px; background:#0d1f0d; border:1px solid #1a3d2e; border-radius:10px; padding:12px 14px; }
.income-box .ib-num { font-size:24px; font-weight:bold; color:#3fb950; white-space:nowrap; }
.income-box .ib-num .ib-u { font-size:12px; color:#8b949e; font-weight:normal; }
.income-box .ib-txt { font-size:12px; color:#c9d1d9; line-height:1.6; }
.yield-vs { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:8px; }
.yield-vs .yv-item { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:12px 8px; text-align:center; }
.yield-vs .yv-k { font-size:11px; color:#8b949e; }
.yield-vs .yv-v { font-size:20px; font-weight:bold; color:#e6edf3; margin-top:4px; }
.yield-vs .yv-v.good { color:#3fb950; }
.yield-vs .yv-v.bad { color:#f85149; }
.gauge { background:#21262d; border-radius:20px; height:20px; overflow:hidden; margin:6px 0 14px; }
.gauge > div { height:100%; background:linear-gradient(90deg,#238636,#3fb950); border-radius:20px; }
.factor { margin-bottom:10px; }
.factor .fl { display:flex; justify-content:space-between; font-size:12px; color:#8b949e; margin-bottom:3px; }
.factor .fl b { color:#e6edf3; }
.factor .bar { background:#21262d; border-radius:10px; height:10px; overflow:hidden; }
.factor .bar > div { height:100%; background:#58a6ff; }
.databadge { background:#1c1408; border:1px solid #3d2810; color:#d29922; font-size:11px; padding:8px 12px; border-radius:8px; line-height:1.6; margin-bottom:14px; }
.databadge b { color:#f0c040; }
@media (max-width:640px){
  .modal-overlay { padding:8px; }
  .modal { max-width:none; margin:0; border-radius:0; border-left:none; border-right:none; border-top:none; min-height:100%; }
  .modal-body { padding:0 14px 18px; }
  .stock-head { padding:16px; }
  .module { padding:14px; }
  .metric-cards { grid-template-columns:repeat(2,1fr); }
  .kv { grid-template-columns:1fr 1fr; gap:8px 12px; }
  .conclusion-bar { flex-direction:column; align-items:flex-start; }
  .conclusion-bar .cb-tag { align-self:flex-start; }
  .roe-section, .combo-section { padding:14px; }
  .yield-vs { grid-template-columns:1fr; }
  .hist-table { font-size:12px; }
}
@media (max-width:460px){ .container { padding:10px; } .stock-card { padding:8px 10px; } .metric-cards { grid-template-columns:repeat(2,1fr); } }
/* 达标名单（ROE 分层） */
.roe-section { background:linear-gradient(135deg,#0d1f0d 0%,#0d2818 100%); border:1px solid #1a3d2e; border-radius:16px; padding:18px; margin-bottom:14px; }
.roe-section h2 { font-size:15px; margin-bottom:12px; color:#3fb950; }
.roe-tier { display:flex; align-items:baseline; gap:10px; font-size:12px; padding:6px 0; border-bottom:1px dashed #1a3d2e; }
.roe-tier:last-child { border-bottom:none; }
.roe-label { font-weight:bold; min-width:96px; white-space:nowrap; }
.roe-names { color:#c9d1d9; line-height:1.7; }
/* 组合 */
.combo-section { background:linear-gradient(135deg,#161b22 0%,#0d1117 100%); border:1px solid #30363d; border-radius:16px; padding:18px; margin-bottom:14px; }
.combo-section h2 { color:#f0c040; font-size:15px; margin-bottom:12px; text-align:center; }
.combo-card { background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08); border-radius:10px; padding:12px 14px; margin-bottom:10px; }
.combo-card .combo-title { font-size:13px; font-weight:bold; }
.combo-card .combo-stable { color:#3fb950; }
.combo-card .combo-growth { color:#58a6ff; }
.combo-card .combo-aggressive { color:#bc8cff; }
.combo-card .combo-desc { font-size:12px; color:#8b949e; margin-top:6px; line-height:1.7; }
.combo-card .combo-desc b { color:#f0c040; }
.combo-stocks { margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; }
.combo-stock { display:inline-block; font-size:12px; color:#e6edf3; background:rgba(88,166,255,.08); border:1px solid rgba(88,166,255,.25); padding:3px 10px; border-radius:8px; cursor:pointer; transition:background .15s; }
.combo-stock:hover { background:rgba(88,166,255,.22); }
"""

SIGNAL_TEXT = ["可分批关注", "持有观察", "谨慎观望"]
SIGNAL_EMOJI = ["🟢", "🟡", "🔴"]
SIGNAL_COLOR = ["#3fb950", "#d29922", "#f85149"]
CONCL_CLASS = ["ok", "mid", "wait"]

def fmt_chg(c):
    cls = "up" if c > 0 else ("down" if c < 0 else "flat")
    sign = "+" if c > 0 else ""
    return f'<span class="{cls}">{sign}{c:.2f}%</span>'

def fmt_div(d):
    if d == 0:
        return "—"
    return f'<span class="good">{d:.2f}%</span>'

def fmt_pe(p):
    if p < 0:
        return f'<span style="color:#f85149">亏损</span>'
    return f'<b>{p:.2f}</b>'


def render_card(s):
    sid = f"m-hk{s['code']}"
    return f'''<div class="stock-item">
  <input type="checkbox" id="{sid}" class="modal-toggle">
  <label class="stock-card border-{s['border']}" for="{sid}">
    <div class="industry">{s['l2_code']} {s['l2']}</div>
    <div class="name">{s['zh']} {s['code']}</div>
    <div class="data">涨跌 {fmt_chg(s['chg'])} | PE {fmt_pe(s['pe'])} | {fmt_div(s['div'])}</div>
    <div class="yt" style="color:{SIGNAL_COLOR[s['signal']]}">{SIGNAL_EMOJI[s['signal']]} {SIGNAL_TEXT[s['signal']]}</div>
    <div class="scoremark">市值 {s['mkt']} · 52w位 {s['pos']}%</div>
  </label>
  {render_modal(s, sid)}
</div>'''


def render_modal(s, sid):
    pe_disp = f"{s['pe']:.2f}" if s['pe'] > 0 else "亏损"
    div_disp = f"{s['div']:.2f}%" if s['div'] > 0 else "—"
    div_v_cls = "good" if s['div'] >= 4 else ("bad" if s['div'] == 0 else "")

    chg_s_cls = "up" if s['chg'] > 0 else ("down" if s['chg'] < 0 else "")
    chg_arrow = "▲" if s['chg'] > 0 else ("▼" if s['chg'] < 0 else "—")
    chg_text = f"{chg_arrow} {abs(s['chg']):.2f}%"

    pe_v_cls = "good" if 0 < s['pe'] < 12 else ("bad" if s['pe'] > 30 else "")

    # ===== 真实基本面（2025年报披露）=====
    real_roe = s.get('roe') or 0.0
    margin = s.get('margin')
    liab = s.get('liab') or 0.0
    south = s.get('south') or 0.0
    div5 = s.get('div5') or []
    has_div = any(d is not None for d in div5)

    # ---- 模块6「巴菲特模型评分」：真实 ROE 驱动（满分 100）----
    f_roe = round(min(real_roe / 25.0, 1.0) * 30) if real_roe > 0 else 0
    f_val = round(max(min((35 - s['pe']) / 35.0, 1.0), 0.0) * 25) if s['pe'] > 0 else 0
    f_div = round(min(s['div'] / 6.0, 1.0) * 15)
    f_sol = round(max(min((4 - s['pb']) / 4.0, 1.0), 0.0) * 15) if s['pb'] > 0 else 0
    mc_num = float(''.join(ch for ch in s['mkt'] if ch.isdigit() or ch == '.'))
    f_moat = 15 if mc_num >= 1.0 else (12 if mc_num >= 0.3 else (9 if mc_num >= 0.1 else 6))
    bw_total = f_roe + f_val + f_div + f_sol + f_moat
    if bw_total >= 70:
        bw_color, bw_label = "#3fb950", "良好，可纳入观察池"
    elif bw_total >= 50:
        bw_color, bw_label = "#d29922", "中等，需结合估值位置"
    else:
        bw_color, bw_label = "#f85149", "偏弱，谨慎对待"
    factors = [
        ("ROE盈利能力(2025年报)", f_roe, 30, f"ROE {real_roe:.1f}%"),
        ("估值合理性(PE)", f_val, 25, f"PE {pe_disp}"),
        ("分红回报", f_div, 15, f"股息率 {div_disp}"),
        ("财务稳健/资产质量", f_sol, 15, f"PB {s['pb']:.2f}"),
        ("护城河/现金流(规模代理)", f_moat, 15, f"市值 {s['mkt']}"),
    ]
    factor_html = "\n".join(
        f'        <div class="factor">\n'
        f'          <div class="fl"><span>{lab}</span><b>{sc}/{mx}</b></div>\n'
        f'          <div class="bar"><div style="width:{sc/mx*100:.0f}%"></div></div>\n'
        f'          <div class="fl" style="color:#6e7681"><span>{sub}</span><span></span></div>\n'
        f'        </div>'
        for lab, sc, mx, sub in factors
    )

    # ---- 模块5「分红回报全景」：真实近5年每股股息 ----
    if has_div:
        years = [2021, 2022, 2023, 2024, 2025]
        div_rows = "".join(
            f"<tr><td>{y}</td><td class=\"v {'good' if (d is not None and d > 0) else ''}\">{('%.3f' % d) if d is not None else '—'}</td></tr>"
            for y, d in zip(years, div5)
        )
        last_div = next((d for d in reversed(div5) if d is not None), 0) or 0
        dy_last = last_div / s['price'] * 100.0 if s['price'] > 0 else 0.0
        income = dy_last / 100.0 * 100000.0 if dy_last > 0 else 0
        shares = 100000.0 / s['price'] if s['price'] > 0 else 0
        spread = dy_last - 4.30
        ss_total = round(min(dy_last / 6.0 * 100.0, 95.0))
        ss_stars = '★' * max(1, ss_total // 20) + '☆' * (5 - max(1, ss_total // 20))
        ss_cls = '' if ss_total >= 70 else ('mid' if ss_total >= 45 else 'bad')
        module5_html = f'''          <h3 class="sub-h">近 5 年每股股息（年报+中期，含税，HKD）</h3>
          <table class="hist-table">
            <thead><tr><th>年度</th><th>每股股息(HKD)</th></tr></thead>
            <tbody>{div_rows}</tbody>
          </table>
          <div class="note">数据来自东方财富妙想分红明细（年报年度分配+中期，含税，已折算港币）；"—" 表示当年未披露/未分红。近年分红为真实披露值。</div>
          <h3 class="sub-h">股息率 vs 无风险利率</h3>
          <div class="yield-vs">
            <div class="yv-item"><div class="yv-k">最新年度股息率</div><div class="yv-v good">{dy_last:.2f}%</div></div>
            <div class="yv-item"><div class="yv-k">无风险利率(参考)</div><div class="yv-v">4.30%</div></div>
            <div class="yv-item"><div class="yv-k">利差(性价比)</div><div class="yv-v {'good' if spread>0 else 'bad'}">{spread:+.2f}pct</div></div>
          </div>
          <h3 class="sub-h">分红可持续性评分（基于最新年度股息率）</h3>
          <div class="sustain-score {ss_cls}">
            <div class="ss-num">{ss_total}<span class="ss-den">/100</span></div>
            <div class="ss-star">{ss_stars}</div>
          </div>
          <ul class="ss-reasons"><li>最新年度股息率 {dy_last:.2f}%，{'处高位、收息属性强' if dy_last>=5 else ('中等、基本可持续' if dy_last>=2 else '偏低')}</li><li>派息连续性/覆盖率以年报披露为准（真实披露值）。</li></ul>
          <h3 class="sub-h">10万元分红收益测算</h3>
          <div class="income-box">
            <div class="ib-num">≈ {income:,.0f} 港元<span class="ib-u">/年（税前）</span></div>
            <div class="ib-txt">以现价 {s['price']:.2f} 港元买入 10 万港元，约得 {shares:,.0f} 股，按最新年度每股股息 {last_div:.3f} 港元 测算，年化税前分红约 {income:,.0f} 港元。</div>
          </div>
          <div class="note">测算按最新年度每股股息（真实披露）与现价推算；实际派息以公司公告为准。</div>'''
    else:
        module5_html = '          <div class="reason">当前不分红（成长/亏损阶段或近年未派息），分红回报不适用；关注点转向估值修复与盈利兑现。</div>'

    r2 = s['risks'][1] if len(s['risks']) > 1 else s['risks'][0]
    mine_box_cls = "pass" if bw_total >= 72 else "warn"
    mine_box_txt = "质地较优" if bw_total >= 72 else "排雷关注"

    # ---- 模块2「买卖决策与建仓」：估值位置判断 + 建仓三档 ----
    if s['pos'] <= 20:
        vcls, vicon, vtxt = "ok", "✅", "处于历史低位区，安全边际较足"
        vreason = "估值低于近年中枢，下行空间相对有限，可积极关注。"
    elif s['pos'] <= 50:
        vcls, vicon, vtxt = "mid", "⚠️", "估值中等，可逢低分批"
        vreason = "处于近年中枢附近，等回调或企稳信号再分批加仓。"
    else:
        vcls, vicon, vtxt = "wait", "⚠️", "估值偏高，等待回调"
        vreason = "高于近年中枢，安全边际不足，耐心等待击球区。"

    dist_low = (s['price'] - s['w52l']) / s['w52l'] * 100 if s['w52l'] > 0 else 0

    if s['div'] > 0:
        dps = s['price'] * s['div'] / 100.0
        y1 = max(s['div'], 3.0)
        y2 = s['div'] + 1.5
        y3 = s['div'] + 3.0
        p1 = dps / y1 * 100
        p2 = dps / y2 * 100
        p3 = dps / y3 * 100
        tier_intro = f"以现价 {s['price']:.2f} 港元、TTM 每股分红约 {dps:.2f} 港元（股息率 {s['div']:.2f}%）测算，按目标股息率反推三档建仓价："
        target_reason = (f"按目标股息率 {y3:.1f}%（重仓档）反推，对应建仓价约 <b>{p3:.2f}</b> 港元，"
                         f"较现价 {s['price']:.2f} 还需下探约 <b>{(s['price']-p3)/s['price']*100:.0f}%</b>。建议在该价位附近再建仓。")
        tier_rows = "".join(
            f"<tr><td>{n}</td><td class=\"v good\">{p:.2f} 港元</td><td>股息率 {y:.1f}%</td></tr>"
            for n, p, y in [("试探仓", p1, y1), ("加仓", p2, y2), ("重仓", p3, y3)]
        )
    else:
        p3 = s['w52l'] * 1.05
        p2 = (s['price'] + s['w52l']) / 2
        p1 = s['price'] * 0.92
        tier_intro = f"{s['zh']} 当前不分红，按现价折让 + 52周低位（{s['w52l']:.2f}）锚定三档建仓价："
        target_reason = (f"以 52 周低位 {s['w52l']:.2f} 港元附近为底部建仓位，对应重仓价约 <b>{p3:.2f}</b> 港元，"
                         f"较现价 {s['price']:.2f} 还需下探约 <b>{(s['price']-p3)/s['price']*100:.0f}%</b>。")
        tier_rows = "".join(
            f"<tr><td>{n}</td><td class=\"v good\">{p:.2f} 港元</td><td>{d}</td></tr>"
            for n, p, d in [("试探仓", p1, "现价约 92% 折让"), ("加仓", p2, "现价与52周低之间"), ("重仓", p3, "接近52周低位")]
        )

    risks_html = "\n".join(f'<div class="risk">{r}</div>' for r in s['risks'])

    margin_disp = ('%.1f%%' % margin) if margin is not None else '不适用'
    margin_cls = "" if margin is not None else "warn"
    liab_cls = "bad" if liab > 70 else ("warn" if liab > 50 else "good")

    return f'''<div class="modal-overlay">
    <label class="modal-backdrop" for="{sid}"></label>
    <div class="modal">
      <div class="modal-x">
        <span class="hint">点击空白处或 ✕ 关闭</span>
        <label class="modal-close" for="{sid}">✕ 关闭</label>
      </div>
      <div class="modal-body">
        <div class="databadge">
          {MODAL_DATABADGE}
        </div>
        <div class="stock-head">
          <div class="code">{s['code']}.HK</div>
          <h1>{s['zh']}</h1>
          <div class="en">{s['en']}</div>
          <div class="ind">📌 {s['l1']} · {s['l2']}</div>
          <div class="scorepill" style="background:{bw_color}">巴菲特模型评分 {bw_total} / 100</div>
        </div>
        <div class="module">
          <h2><span class="num">1</span>行情快照（{SNAP_ISO} 收盘后）</h2>
          <div class="metric-cards">
            <div class="metric-card"><div class="mc-k">最新价</div><div class="mc-v">{s['price']:.2f}<span class="mc-u">港元</span></div><div class="mc-s {chg_s_cls}">{chg_text}</div></div>
            <div class="metric-card"><div class="mc-k">股息率(TTM)</div><div class="mc-v {div_v_cls}">{div_disp.replace("%", "<span class=\"mc-u\">%</span>") if s['div']>0 else "—"}</div><div class="mc-s">{"高息" if s['div']>=5 else ("中等分红" if s['div']>=2 else "低息/不分红")}</div></div>
            <div class="metric-card"><div class="mc-k">总市值</div><div class="mc-v">{s['mkt']}</div><div class="mc-s">PB {s['pb']:.2f}</div></div>
            <div class="metric-card"><div class="mc-k">PE(TTM)</div><div class="mc-v {pe_v_cls}">{pe_disp}{'<span class="mc-u">倍</span>' if s['pe']>0 else ''}</div><div class="mc-s">52w位 {s['pos']}%</div></div>
          </div>
          <div class="kv">
            <div><span class="k">今开 / 昨收</span><br><span class="v">{s['open']:.2f} / {s['prev']:.2f}</span></div>
            <div><span class="k">成交额</span><br><span class="v">{s['amount']}港元</span></div>
            <div><span class="k">换手率</span><br><span class="v">{s['turn']:.2f}%</span></div>
            <div><span class="k">52周区间</span><br><span class="v">{s['w52l']:.2f} – {s['w52h']:.2f}</span></div>
          </div>
          <div class="note">数据口径：{SNAP_ISO} 收盘快照（收盘口径，非盘中实时），行情/估值来自腾讯自选股。</div>
        </div>
        <div class="module">
          <h2><span class="num">2</span>买卖决策与建仓</h2>
          <h3 class="sub-h">是否推荐入手</h3>
          <div class="conclusion-bar {CONCL_CLASS[s['signal']]}"><span class="cb-tag">{SIGNAL_EMOJI[s['signal']]} {SIGNAL_TEXT[s['signal']]}</span><span class="cb-reason">{s['suggest'][2:].strip()}</span></div>
          <div class="reason">综合 {s['zh']} 当前估值位置（52周分位 {s['pos']}%）与基本面判断。</div>
          <h3 class="sub-h">是否处于低点（估值视角）</h3>
          <div class="verdict {vcls}">{vicon} {vtxt}</div>
          <div class="reason">{vreason} 当前 52 周分位 {s['pos']}%，PE {pe_disp}，PB {s['pb']:.2f}。</div>
          <div class="kv" style="margin-top:10px">
            <div><span class="k">当前 PE</span><br><span class="v">{pe_disp}</span></div>
            <div><span class="k">当前 PB</span><br><span class="v">{s['pb']:.2f}</span></div>
            <div><span class="k">52周分位</span><br><span class="v">{s['pos']}%</span></div>
            <div><span class="k">距52周低点</span><br><span class="v">+{dist_low:.0f}%</span></div>
          </div>
          <h3 class="sub-h">估值目标价（建仓视角）</h3>
          <div class="reason">{target_reason}</div>
          <h3 class="sub-h">建议买入价位（三档建仓）</h3>
          <div class="reason">{tier_intro}</div>
          <table class="tier-table">
            <thead><tr><th>档位</th><th>对应价</th><th>说明</th></tr></thead>
            <tbody>{tier_rows}</tbody>
          </table>
        </div>
        <div class="module">
          <h2><span class="num">3</span>资金面动态</h2>
          <div class="summary">{s['capital']}；近期价量表现与南向(港股通)持仓如下。</div>
          <div class="kv">
            <div><span class="k">52周分位</span><br><span class="v">{s['pos']}%</span></div>
            <div><span class="k">南向(港股通)持股</span><br><span class="v {'good' if south>=10 else ''}">{south:.2f}%</span></div>
            <div><span class="k">近5日 / 近20日</span><br><span class="v {'up' if s['chg5']>0 else 'down'}">{s['chg5']:+.2f}% / {s['chg20']:+.2f}%</span></div>
            <div><span class="k">近60日 / YTD</span><br><span class="v {'up' if s['chg60']>0 else 'down'}">{s['chg60']:+.2f}% / {s['ytd']:+.2f}%</span></div>
            <div><span class="k">换手率(当日)</span><br><span class="v">{s['turn']:.2f}%</span></div>
            <div><span class="k">成交额(当日)</span><br><span class="v">{s['amount']}港元</span></div>
          </div>
          <div class="tag-row">
            <span class="tag">现价 {s['price']:.2f} 港元</span>
            <span class="tag">52周 {s['w52l']:.2f}–{s['w52h']:.2f}</span>
            <span class="tag">南向持股 {south:.2f}%</span>
          </div>
          <div class="note">港股无 A 股「北向/融资融券」口径；南向(港股通)持股比例为最新交易日真实披露值（来源 Wind），反映内资通过港股通的持仓占比。</div>
        </div>
        <div class="module">
          <h2><span class="num">4</span>盈利质量与排雷</h2>
          <h3 class="sub-h">真实盈利质量指标（2025年报披露）</h3>
          <table class="hist-table">
            <thead><tr><th>指标</th><th>2025年报</th></tr></thead>
            <tbody>
              <tr><td>ROE 净资产收益率</td><td class="v {'good' if real_roe>=15 else 'warn' if real_roe>=10 else 'bad'}">{real_roe:.1f}%</td></tr>
              <tr><td>销售毛利率</td><td class="{margin_cls}">{margin_disp}</td></tr>
              <tr><td>资产负债率</td><td class="v {liab_cls}">{liab:.1f}%</td></tr>
              <tr><td>股息率(TTM)</td><td class="v {div_v_cls}">{div_disp}</td></tr>
              <tr><td>52周分位</td><td>{s['pos']}%</td></tr>
            </tbody>
          </table>
          <div class="note">ROE / 毛利率 / 资产负债率来自 2025 年报披露（Wind/东方财富），为会计口径真实值。</div>
          <h3 class="sub-h">排雷结论</h3>
          <div class="mine-box {mine_box_cls}">{mine_box_txt}</div>
          <ul class="mine-reasons">
            <li>{s['risks'][0]}</li>
            <li>{r2}</li>
            <li>资产负债率 {liab:.1f}%（{'偏高、需关注杠杆' if liab>70 else ('中等、可控' if liab>50 else '较低、财务稳健')}）</li>
            <li>{'连续分红、收息属性清晰' if s['div']>=2 else ('高 ROE 但低分红/不分红' if real_roe>=15 else '市值规模大、流动性好' if mc_num>=0.3 else '小市值、波动与流动性需留意')}</li>
          </ul>
        </div>
        <div class="module">
          <h2><span class="num">5</span>分红回报全景</h2>
{module5_html}
        </div>
        <div class="module">
          <h2><span class="num">6</span>巴菲特模型评分</h2>
          <div class="gauge"><div style="width:{bw_total}%;background:{bw_color}"></div></div>
          <div class="reason">综合评分 <b style="color:{bw_color}">{bw_total} / 100</b>（{bw_label}）。</div>
{factor_html}
          <div class="note">评分逻辑：ROE盈利能力(30) + 估值合理性(25) + 分红回报(15) + 财务稳健/资产质量(15) + 护城河/现金流(15)。<b>ROE 采用 2025 年报披露真实值</b>；估值/分红/稳健/护城河仍为模型口径。</div>
        </div>
        <div class="module">
          <h2><span class="num">7</span>风险提示（重点3条）</h2>
          {risks_html}
        </div>
        <div class="module">
          <h2><span class="num">8</span>进一步分析 · 一句话总结</h2>
          <div class="summary">{s['summary']}</div>
          <div class="note">单只标的建议不超过组合的 15%-20%，并严格分散行业与风格。</div>
        </div>
      </div>
    </div>
  </div>'''


# ===== 数据驱动层（由 data.json 渲染，布局固定） =====

def render_roster(stocks, meta):
    tiers = [
        ("超神 (>25%)", "#3fb950", []),
        ("优秀 (15-25%)", "#58a6ff", []),
        ("接近 (10-15%)", "#d29922", []),
        ("偏弱 (<10% / 亏损)", "#8b949e", []),
    ]
    for s in stocks:
        roe = s.get('roe') or 0.0
        name = f"{s['zh']} {s['code']}"
        if roe > 25:
            tiers[0][2].append(name)
        elif roe >= 15:
            tiers[1][2].append(name)
        elif roe >= 10:
            tiers[2][2].append(name)
        else:
            tiers[3][2].append(name)
    rows = []
    for label, color, names in tiers:
        rows.append(f'<div class="roe-tier"><span class="roe-label" style="color:{color}">{label}</span>'
                    f'<span class="roe-names">{" · ".join(names)}</span></div>')
    return f'''<div class="roe-section">
    <h2>{meta['roster_title']}</h2>
    {''.join(rows)}
    <div class="note" style="margin-top:10px">{meta['roster_note']}</div>
  </div>'''


def render_combos(combos, stocks, meta):
    cards = []
    for c in combos:
        cls, title, codes, desc = c['cls'], c['title'], c['codes'], c['desc']
        labels = []
        for code in codes:
            s = next(x for x in stocks if x['code'] == code)
            labels.append(f'<label class="combo-stock" for="m-hk{code}">{s["zh"]} {code}</label>')
        cards.append(f'''    <div class="combo-card">
      <div class="combo-title {cls}">{title}</div>
      <div class="combo-stocks">{" ".join(labels)}</div>
      <div class="combo-desc">{desc}</div>
    </div>''')
    return f'''  <div class="combo-section">
    <h2>{meta['combo_section_title']}</h2>
    {''.join(cards)}
    <div class="note" style="margin-top:6px">{meta['combo_note']}</div>
  </div>'''


def render_page(data):
    meta = data['meta']
    stocks = data['stocks']
    out = []
    out.append(f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>{meta["title"]}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<div class="container">\n')
    out.append(f'''<div class="header">
  <div class="tag">{meta['tag']}</div>
  <h1>{meta['title']}</h1>
  <div class="subtitle">{meta['subtitle']}</div>
  <div class="date">{meta['date']}</div>
</div>
<div class="databadge">
  {meta['databadge']}
</div>
''')
    for sec in data['sectors']:
        sec_key = sec['key']
        sec_title = sec['title']
        sec_stocks = [s for s in stocks if s['sector'] == sec_key]
        out.append(f'<div class="sector sector-{sec_key}">\n<h2>{sec_title}</h2>\n<div class="sector-grid">\n')
        seen_l1 = []
        for s in sec_stocks:
            if s['l1'] not in seen_l1:
                seen_l1.append(s['l1'])
                out.append(f'<div class="sub-group"><div class="sub-h">▍{s["l1"]}</div></div>\n')
            out.append(render_card(s))
        out.append('</div>\n</div>\n')
    out.append(render_roster(stocks, meta))
    out.append(render_combos(data['combos'], stocks, meta))
    out.append(f'''<div class="disclaimer">
  <p>{meta['disclaimer']}</p>
</div>
<div class="footer">{meta['footer']}</div>
</div>
</body>
</html>
''')
    return "".join(out)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "data.json"), encoding="utf-8") as f:
        data = json.load(f)
    SNAP_ISO = data["meta"]["snap_iso"]
    MODAL_DATABADGE = data["meta"]["modal_databadge"]
    html = render_page(data)
    out_path = os.path.join(here, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已生成：{out_path}（{len(data['stocks'])} 只个股 · {len(html)} 字节）")
