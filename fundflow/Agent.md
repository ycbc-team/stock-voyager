# Agent.md — fundflow 模块

A 股收盘资金流数据抓取 + 静态网页报告生成模块。当前采用“数据生产 / UI 渲染 / 主脚本编排”三段式结构，只关注资金流动跟踪。

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
  - 申万成分股：`AKShare.index_component_sw(symbol=行业代码)`，结果缓存到 `common/cache/sw_stock_map.json`
  - 个股资金流排行：`AKShare.stock_individual_fund_flow_rank(indicator="今日")`
  - 主要指数 / 国证风格 / 两市成交额 / 北向成交额：东方财富公开接口，指数回退腾讯 gtimg
- **缓存策略**：长期稳定数据统一放在 `common/cache/`；每天会变的数据拆到 `build/cache/`，页面 JSON 进入 `build/data/`，最终 HTML 进入 `build/site/`。
- **长期缓存语义**：
  - `sw_mapping.json` 属于参考常量，默认不按时间过期。
  - `sw_stock_map.json` 属于长期稳定但可能增量变化的数据，默认也不按时间过期；当发现当日股票列表里存在未映射代码时，自动重新抓取申万成分股并补齐新股。
- **请求策略**：所有外部调用前统一遵守 `REQ_DELAY` 节流；优先复用单次全市场排行结果，不额外重复请求个股 TOP。

## 二、目录结构

```
common/
├── market_data.py           # fundflow / stocktrend 共享请求逻辑
├── storage.py               # build 与 common/cache 的统一读写
└── cache/                   # 仅长期稳定数据

fundflow/
├── fundflow_data_fetcher.py # 数据抓取 / 聚合 / JSON 产出
├── fundflow_ui_renderer.py  # 基于 JSON 中间产物渲染纯静态 HTML
├── fundflow_main.py         # 页面总控：先生产数据，再渲染 HTML
├── report.css
└── Agent.md
```

产物**不在此目录**，统一输出到项目根 `build/`（已 gitignore，不入库）：

```
build/
├── site/
│   └── fundflow.html
├── data/
│   └── fundflow.json
└── cache/
    ├── fundflow_market_snapshot_<date>.json
    ├── fundflow_sw_index_spot_<date>.json
    ├── fundflow_northbound_<date>.json
    └── stock_fundflow_today_full_<date>.json
```

## 三、构建 / 运行命令

```bash
cd fundflow
../.venv/bin/python -m pip install -r ../requirements.txt

# 1) 日常构建（默认）：主脚本先产出 JSON，再渲染 HTML
../.venv/bin/python fundflow_main.py
# → 产物：build/data/fundflow.json + build/site/fundflow.html

# 2) 指定数据日期
../.venv/bin/python fundflow_main.py --date 2026-08-25

# 3) 个股资金流 TOP 数量（默认 10）
../.venv/bin/python fundflow_main.py --topn 20

# 4) 仅跑数据生产层
../.venv/bin/python fundflow_data_fetcher.py

# 5) 基于已生成 JSON 单独做 HTML 渲染
../.venv/bin/python fundflow_ui_renderer.py --input ../build/data/fundflow.json --output ../build/site/fundflow.html
```

**限速与请求量**：
- 每次 HTTP 请求前主动延迟 `REQ_DELAY` 秒（默认 0.35，`REQ_DELAY=0` 关闭、`REQ_DELAY=0.8` 更保守），避免短时间密集请求触发数据源限流。
- 长期不变数据（申万映射、成分股映射）优先走本地缓存；缓存命中时不会再请求远端。
- 个股资金流 TOP 直接复用全市场资金流排行结果，不再为 TOP 单独发请求。

**关键点**：
- 页面级文件名固定无日期；打开/刷新 `build/site/fundflow.html` 即见最新报告。
- 主脚本固定产出 `build/data/fundflow.json` + `build/site/fundflow.html`，不再输出 CSV。
- 偶发接口超时调优：`EM_TIMEOUT=8 EM_RETRIES=2 ../.venv/bin/python fundflow_main.py`
- `report.css` 必须与脚本同目录（脚本按自身位置加载并内联），移动时两者一起搬。

## 四、口径与约束（Agent 必须遵守）

1. **北向净买入不编造**：2024-08 起不再实时披露，报告只展示公开的成交额/成交占比；即便接口返回净买额字段也统一置 None。
2. **移动端约束**：WorkBuddy 移动端 Safari 打开本地 HTML 不执行 `<script>`。因此报告**必须保持纯静态**——数据内联进 HTML 标签，生成器内**禁止引入任何 JS**（改样式只改 `report.css`，改结构改 `write_html()`，都不要引入脚本）。
3. **A 股配色惯例**：涨=红（`#f6465d`）、跌=绿（`#0ecb81`）。
4. **口径约束**：报告中的“申万一级主力净流入”是按个股资金流聚合得到，不等同于任何单一网页原始字段；页面文案不要再写成“东财行业资金流”。
5. 所有输出显式标注**数据日期**与**数据来源**。
6. 长期缓存统一放在 `common/cache/`；不要再把模块私有 `.cache/` 当成正式缓存目录。
7. 个股资金流优先复用缓存的申万成分股映射，按 `secid` 批量请求延迟行情主机；只有这条路径失败时才回退到更重的全市场排行。

## 五、每日例行（给 Agent / 自动化）

1. 判断当日是否为交易日（脚本 `detect_trade_date()` 已处理，也可直接 `--date` 指定）。
2. 运行 `../.venv/bin/python fundflow_main.py`（收盘 15:00 后）。
3. 校验输出：`build/data/fundflow.json` 与 `build/site/fundflow.html` 生成成功、头部数据日期正确、无「数据暂缺」大面积出现（本机网络正常时）。
4. 若 AKShare 相关接口暂不可用，优先检查 `.venv` / `requirements.txt` / 外网访问与 `common/cache/` 中静态映射是否有效。
5. 如需对外分享，直接给 `build/site/fundflow.html` 文件本身（单文件自包含）。

## 六、自动部署（GitHub Actions + Pages）

`.github/workflows/ashare-report.yml`：每个交易日 16:01（北京时间）自动运行脚本并部署 GitHub Pages。

- 触发：`push`（推 main 即刷新）+ `schedule`（周一至五 08:01 UTC）+ `workflow_dispatch`（手动触发）
- 流程：`python3 main.py`（统一生成导航首页 + `fundflow` + `stocktrend` 页面）→ 上传 `build/site/` → deploy-pages
- 一次性配置：仓库 **Settings → Pages → Source 选「GitHub Actions」**
- 站点：`https://<owner>.github.io/<repo>/`（根路径即导航首页）

## 七、补充说明

- `stocktrend` 若发现 `build/cache/stock_fundflow_today_full_<date>.json` 已存在，会直接复用，不会重复请求同一批资金流数据。
- `fundflow_data_fetcher.py` 与 `stocktrend_data_fetcher.py` 都只输出 JSON，不再带 `fmt/csv` 参数。

## 八、港股资金流（与 A 股共用 4 文件，按 `--market hk` 切换）

港股资金流**不再单独建文件**，而是与 A 股共用 `fundflow/` 下同一套 4 文件 + `report.css`，通过 `--market hk` 分支输出独立的 `fundflow_hk.html`（UI 模板约 95% 与 A 股一致，仅按 `market` 切换标题/口径/行业文案，并非「仅换标签」，申万 31 行业 vs 港股二级业务类别（约 32 类）、北向 vs 南向等是真实分支）。模式对齐 `stocktrend/`（一套代码出 A 股 / 港股 / 美股三个独立网页）。

- `fundflow_data_fetcher.py`：文末追加港股抓取函数（`load_or_fetch_hk_index_snapshot` / `load_or_fetch_hk_stock_fundflow` / `load_or_fetch_southbound` / `fetch_hk_market_breadth`）
- `fundflow_processor.py`：文末追加港股装配函数（`collect_report_data_hk` / `build_hk_sector` / `compute_hk_hotspots` / `generate_hk_verdict`），`write_report_json(..., market=...)` 按 market 选 `fundflow_hk.json` / `fundflow.json`；`build_hk_sector()` 按恒生二级业务类别（l2，约 32 类）聚合港股主力净流入
- `fundflow_ui_renderer.py`：`write_html(path, result, market="ashare")` 单一模板，靠 `is_hk = market=="hk"` 分支标题/核心 KPI（恒生+恒科+国企 / 南向占比 / 港股行业净流入 / 港股涨跌家数）/ 行业面板标签 / 南北向跟踪整块 / 页脚口径
- `fundflow_main.py`：`build_fundflow_report(..., market=...)` + `--market {ashare,hk}`

首页 `index.html` 已增加「港股资金流日报」入口卡片；站点底部导航 `site_navigation.SITE_TABS` 已增加「港股资金流」tab（`fundflow_hk.html`）。`main.py` 在 `--only fundflow`（及 `all`）时同步产出 A 股 + 港股两份资金流页面并重建首页。

**数据展示模块**（与 A 股资金流日报一一对应）：盘面定调 / 主要指数 / 核心市场总览 / 港股行业主力净流入 / 个股资金流排行 / 南向资金跟踪 / 热点与异动板块。

**数据源**：
- 主要指数：腾讯 gtimg（`hkHSI` 恒生 / `hkHSTECH` 恒科 / `hkHSCEI` 国企 / `hkHSCCI` 红筹）
- 个股主力净流入：东方财富 `push2delay` 全港股资金流排行（`fs=m:128+t:1..4`，按 f62 排序，净流入/流出各 TOP100 合并去重；单页封顶 100 条，故分两页取）
- 港股行业分类：复用 `stocktrend/stocktrend_static_data.HK_BASE_DATA`（按 `l2` 聚合约 32 个恒生二级业务类别，顺序见 `_hk_l2_order()`，自然按 l1 分组排布）
- 南向（港股通）：东方财富数据中心 `RPT_MUTUAL_DEAL_HISTORY`（003/004/006 → 沪/深/合计成交额 + 净买入；**南向净买入公开披露，与北向不同**）
- 港股全市场涨跌家数 / 总成交额：AKShare `stock_hk_spot_em`（与 A 股 `stock_zh_a_spot_em` 同款；港股无涨跌停板，故不取涨停/跌停池）

**注意（数据范围）**：
- 「港股二级行业主力净流入」面板按恒生二级业务类别（l2，约 32 类）展示，不再收敛为 4 大板块 / 12 个一级行业；`HK_BASE_DATA["stocks"]` 现已补齐到 40 只、覆盖全部约 32 个二级类别，故各二级行业均有标的、无「—」空板块。若需更全覆盖，可继续扩充 `HK_BASE_DATA` 或接入恒生综合行业全量映射。
- 「个股资金流排行」已是**全港股市场** TOP（非仅 11 只），与 A 股全市场口径一致。
- 本沙箱代理可能拦截 AKShare `stock_hk_spot_em`，届时「港股涨跌家数」显示「暂不可用」；A 股个股资金流 AKShare 失败会自动回退东方财富。

构建命令：
```bash
../.venv/bin/python -m fundflow.fundflow_main --market hk        # 生成 fundflow_hk.json + fundflow_hk.html
../.venv/bin/python -m main --only fundflow                       # A股+港股资金流 + 首页 一起产出
```

