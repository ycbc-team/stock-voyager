# Agent.md — fundflow 模块

A 股收盘资金流数据抓取 + 静态网页报告生成模块。独立于仓库根目录的港股页面模板（build.py / data.json / index.html），只关注资金流动跟踪。

## 一、项目简介

- **职责**：每日收盘后抓取 A 股核心行情与资金流数据，并生成一份**纯静态**（零 JS）HTML 网页报告。
- **覆盖数据**：
  1. 主要指数收盘点位（上证/深证/创业板/科创50/沪深300/上证50/中证500/中证1000/中证2000/北证50）
  2. 申万一级 31 行业涨跌幅 + 主力资金净流入
  3. 北向资金：**仅**成交额与成交占比（净买入自 2024-08-19 起不再披露，一律不取/不编造）
  4. 风格指数（国证规模×价值/成长）+ 主题代理（由申万行业聚合：金融防御/医药景气/科技成长/周期资源）
  5. 个股资金流 TOP（净流入/净流出）+ 行业热点/异动
- **数据源**：东方财富 push2 公开接口（与证券时报·数据宝同源）为主；腾讯财经 gtimg 为指数回退源。
- **不使用 MCP**：脚本是纯公开 HTTP，日常零 MCP 依赖。已连的「东方财富妙想 MCP」是需用户鉴权的 MCP 服务（端点 `mxapi.eastmoney.com/mxds/v2/mcp`，无令牌直接 401），仅供 Agent 会话内使用，脚本无法也不应直连。申万一级的公开源即 push2 的 90. 行业指数接口（正常日可用）。
- **降级链（重要，2026-08-25 实测）**：EM 会对高频探测的 IP 做 WAF 限流（push2 全端点空应答 http=000，页面可达）。此时脚本自动降级：
  - 指数/个股/两市成交额 → `push2delay.eastmoney.com`（延迟行情主机，对本机 IP 宽容）
  - 北向成交额 → `datacenter-web.eastmoney.com` 的 RPT_MUTUAL_DEAL_HISTORY（type 001/002/005，DEAL_AMT 单位百万元）
  - 申万一级（90. 指数）与 kamt 仅 push2 主主机提供 → 被限流时降级为「数据暂缺」，可用 `--merge` 用 MCP 数据补全（见下）

## 二、目录结构

```
fundflow/
├── ashare_close_fetcher.py   # 抓取 + 报告生成脚本（零第三方依赖，仅标准库）
├── report.css                # HTML 报告样式源（深色金融终端风、涨红跌绿），生成时内联进 HTML
└── Agent.md                  # 本文件
```

产物**不在此目录**，统一输出到项目根 `build/`（已 gitignore，不入库）：

```
build/
├── ashare_close.html          # 默认输出：静态网页报告（数据内联、无 <script>）
├── ashare_close.json          # 机器可读（--fmt json）
├── ashare_close.md            # Markdown（--fmt md）
└── ashare_close_industry.csv  # 申万行业表（--fmt csv）
```

## 三、构建 / 运行命令

```bash
cd fundflow

# 1) 日常构建（默认）：取最近交易日，仅生成 HTML
python3 ashare_close_fetcher.py
# → 产物：build/ashare_close.html（覆盖前一天）

# 2) 指定数据日期
python3 ashare_close_fetcher.py --date 2026-08-25

# 3) 多格式输出（逗号组合：json / md / csv / html）
python3 ashare_close_fetcher.py --fmt json,md,html

# 4) 自定义输出目录
python3 ashare_close_fetcher.py --fmt csv --out /tmp/x

# 5) 个股资金流 TOP 数量（默认 10）
python3 ashare_close_fetcher.py --topn 20

# 6) EM 被限流时，用外部/MCP 数据补全缺失模块（申万/个股TOP等）
python3 ashare_close_fetcher.py --merge /tmp/merge.json
# merge.json 结构见文末
```

**限速与请求量**：
- 每次 HTTP 请求前主动延迟 `REQ_DELAY` 秒（默认 0.35，`REQ_DELAY=0` 关闭、`REQ_DELAY=0.8` 更保守），避免短时间密集请求触发数据源限流。
- 已合并请求：主要指数 + 国证风格 + 两市成交额 = **1 次** ulist；个股净流入/净流出 = 沪深合并 **2 次** clist。正常日全流程仅 **5 次** 请求（指数快照 1 + 申万 1 + 北向 1 + 个股 2）；被限流时因多主机/重试会上升（脚本会打印实际请求数）。

**关键点**：
- 文件名**固定无日期**，每天运行覆盖前一天；打开/刷新 `build/ashare_close.html` 即见最新报告。
- 默认 `--fmt html`；`--fmt` 未传任何有效值时不输出任何文件（会提示）。
- 偶发接口超时调优：`EM_TIMEOUT=8 EM_RETRIES=2 python3 ashare_close_fetcher.py`
- `report.css` 必须与脚本同目录（脚本按自身位置加载并内联），移动时两者一起搬。

## 四、口径与约束（Agent 必须遵守）

1. **北向净买入不编造**：2024-08 起不再实时披露，报告只展示公开的成交额/成交占比；即便接口返回净买额字段也统一置 None。
2. **移动端约束**：WorkBuddy 移动端 Safari 打开本地 HTML 不执行 `<script>`。因此报告**必须保持纯静态**——数据内联进 HTML 标签，生成器内**禁止引入任何 JS**（改样式只改 `report.css`，改结构改 `write_html()`，都不要引入脚本）。
3. **A 股配色惯例**：涨=红（`#f6465d`）、跌=绿（`#0ecb81`）。
4. **沙箱限制**：WorkBuddy 沙箱出口代理会拦截东方财富**板块类**接口（`90.`/`m:90` secid、kamt），此时只有指数走腾讯 gtimg 回退、申万/北向/资金流模块显示「数据暂缺」——属预期降级，不是 bug。**本机 Mac 直接运行可完整取数**。
5. 所有输出显式标注**数据日期**与**数据来源**。

## 五、每日例行（给 Agent / 自动化）

1. 判断当日是否为交易日（脚本 `detect_trade_date()` 已处理，也可直接 `--date` 指定）。
2. 运行 `python3 ashare_close_fetcher.py`（收盘 15:00 后）。
3. 校验输出：`build/ashare_close.html` 生成成功、头部数据日期正确、无「数据暂缺」大面积出现（本机网络正常时）。
4. 若申万/北向等显示「数据暂缺」且确认是 EM 限流（而非网络故障），用已连的 MCP（东方财富妙想 `mx_index_block_finance_data` / 腾讯自选股）取数后以 `--merge` 补全重跑。
5. 如需对外分享，直接给 `build/ashare_close.html` 文件本身（单文件自包含）。

## 六、自动部署（GitHub Actions + Pages）

`.github/workflows/ashare-report.yml`：每个交易日 15:45（北京时间）自动运行脚本并部署 GitHub Pages。

- 触发：`schedule`（周一至五 07:45 UTC）+ `workflow_dispatch`（手动）
- 流程：`python3 fundflow/ashare_close_fetcher.py`（默认仅 HTML）→ `build/ashare_close.html` 复制为站点根 `index.html` → upload-pages-artifact → deploy-pages
- 一次性配置：仓库 **Settings → Pages → Source 选「GitHub Actions」**
- 站点：`https://<owner>.github.io/<repo>/`（根路径即最新报告）

## 七、--merge 补全 JSON 结构```json
{
  "sw_industry": [{"code": "801010", "name": "农林牧渔", "pct": 2.23, "main_net_in": 924900000, "source": "..."}],
  "sw_industry_source": "数据来源说明",
  "stock_top_in":  [{"code": "688835", "name": "N高凯", "pct": 282.99, "main_net_in": 2137000000}],
  "stock_top_out": [{"code": "300308", "name": "中际旭创", "pct": -2.78, "main_net_in": -2445000000}],
  "stock_source": "数据来源说明"
}
```
`main_net_in` 单位为元（亿 × 1e8）；`style_proxy`/`hotspots` 会由脚本依据补全后的申万数据自动重算，无需手工提供。
