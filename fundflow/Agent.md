# Agent.md — fundflow 模块

A 股收盘资金流数据抓取 + 静态网页报告生成模块。独立于仓库根目录的港股页面模板（build.py / data.json / index.html），只关注资金流动跟踪。

## 一、项目简介

- **职责**：每日收盘后抓取 A 股核心行情与资金流数据，并生成一份**纯静态**（零 JS）HTML 网页报告。
- **覆盖数据**：
  1. 主要指数收盘点位（上证/深证/创业板/科创50/沪深300/上证50/中证500/中证1000/中证2000/北证50）
  2. 申万一级 31 行业涨跌幅 + 按申万成分股聚合的主力资金净流入
  3. 北向资金：**仅**成交额与成交占比（净买入自 2024-08-19 起不再披露，一律不取/不编造）
  4. 风格指数（国证规模×价值/成长）+ 主题代理（由申万行业聚合：金融防御/医药景气/科技成长/周期资源）
  5. 个股资金流 TOP（净流入/净流出）+ 行业热点/异动
- **数据源**：
  - 抓取层：`AKShare`
  - 申万一级涨跌幅：`AKShare.index_realtime_sw(symbol="一级行业")`
  - 申万成分股：`AKShare.index_component_sw(symbol=行业代码)`，结果缓存到 `fundflow/.cache/sw_stock_map.json`
  - 个股资金流排行：`AKShare.stock_individual_fund_flow_rank(indicator="今日")`
  - 主要指数 / 国证风格 / 两市成交额 / 北向成交额：东方财富公开接口，指数回退腾讯 gtimg
- **缓存策略**：申万一级静态映射与成分股映射属于低变更数据，默认缓存 7 天。只有行情类和资金流排行按日实时抓。
- **请求策略**：所有外部调用前统一遵守 `REQ_DELAY` 节流；优先复用单次全市场排行结果，不额外重复请求个股 TOP。

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
python3 -m venv .venv
. .venv/bin/activate
pip install -r ../requirements.txt

# 1) 日常构建（默认）：取最近交易日，仅生成 HTML
python ashare_close_fetcher.py
# → 产物：build/ashare_close.html（覆盖前一天）

# 2) 指定数据日期
python ashare_close_fetcher.py --date 2026-08-25

# 3) 多格式输出（逗号组合：json / md / csv / html）
python ashare_close_fetcher.py --fmt json,md,html

# 4) 自定义输出目录
python ashare_close_fetcher.py --fmt csv --out /tmp/x

# 5) 个股资金流 TOP 数量（默认 10）
python ashare_close_fetcher.py --topn 20

# 6) EM 被限流时，用外部/MCP 数据补全缺失模块（申万/个股TOP等）
python ashare_close_fetcher.py --merge /tmp/merge.json
# merge.json 结构见文末
```

**限速与请求量**：
- 每次 HTTP 请求前主动延迟 `REQ_DELAY` 秒（默认 0.35，`REQ_DELAY=0` 关闭、`REQ_DELAY=0.8` 更保守），避免短时间密集请求触发数据源限流。
- 长期不变数据（申万映射、成分股映射）优先走本地缓存；缓存命中时不会再请求远端。
- 个股资金流 TOP 直接复用全市场资金流排行结果，不再为 TOP 单独发请求。

**关键点**：
- 文件名**固定无日期**，每天运行覆盖前一天；打开/刷新 `build/ashare_close.html` 即见最新报告。
- 默认 `--fmt html`；`--fmt` 未传任何有效值时不输出任何文件（会提示）。
- 偶发接口超时调优：`EM_TIMEOUT=8 EM_RETRIES=2 python3 ashare_close_fetcher.py`
- `report.css` 必须与脚本同目录（脚本按自身位置加载并内联），移动时两者一起搬。

## 四、口径与约束（Agent 必须遵守）

1. **北向净买入不编造**：2024-08 起不再实时披露，报告只展示公开的成交额/成交占比；即便接口返回净买额字段也统一置 None。
2. **移动端约束**：WorkBuddy 移动端 Safari 打开本地 HTML 不执行 `<script>`。因此报告**必须保持纯静态**——数据内联进 HTML 标签，生成器内**禁止引入任何 JS**（改样式只改 `report.css`，改结构改 `write_html()`，都不要引入脚本）。
3. **A 股配色惯例**：涨=红（`#f6465d`）、跌=绿（`#0ecb81`）。
4. **口径约束**：报告中的“申万一级主力净流入”是按个股资金流聚合得到，不等同于任何单一网页原始字段；页面文案不要再写成“东财行业资金流”。
5. 所有输出显式标注**数据日期**与**数据来源**。
6. `fundflow/.cache/` 是长期缓存目录，不要加回 `.gitignore`；静态映射应随仓库提交，避免 CI 每次全量回源。
7. 个股资金流优先复用缓存的申万成分股映射，按 `secid` 批量请求延迟行情主机；只有这条路径失败时才回退到更重的全市场排行。

## 五、每日例行（给 Agent / 自动化）

1. 判断当日是否为交易日（脚本 `detect_trade_date()` 已处理，也可直接 `--date` 指定）。
2. 运行 `python3 ashare_close_fetcher.py`（收盘 15:00 后）。
3. 校验输出：`build/ashare_close.html` 生成成功、头部数据日期正确、无「数据暂缺」大面积出现（本机网络正常时）。
4. 若 AKShare 相关接口暂不可用，优先检查 `.venv` / `requirements.txt` / 外网访问与 `fundflow/.cache/` 是否有效，再考虑 `--merge` 补全。
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
