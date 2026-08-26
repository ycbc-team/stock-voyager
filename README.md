# 股票分析页 · 可复用布局模板

把已上线港股分析页的**视觉布局**落地为可复用文件。布局（暗色金融终端风、卡片 + 8 模块纯 CSS 弹窗、ROE 达标名单、推荐组合）固定不变；所有**数据/文案**集中在 `data.json`，换市场只改数据，不改布局。

> 零 JS、纯静态输出，移动端 Safari 可直接打开（已规避手机端不执行 `<script>` 的坑）。

## 文件说明

| 文件 | 作用 |
|------|------|
| `data.json` | **数据源**（唯一需要改的文件）。含页面文案、板块、组合、每只个股的行情与真实财务。当前示例 = 40 只港股真实数据。 |
| `build.py`  | **布局引擎**（固定）。含 CSS + 渲染函数，读取 `data.json` 生成静态 `index.html`。一般无需改动。 |
| `index.html`| 每次运行 `build.py` 重新生成的最终页面（可直接部署/分享）。 |

## 复用步骤（换一种市场分析）

1. **改数据源**：编辑 `data.json`。
   - `meta`：标题、标签、副标题、页脚、各项免责/口径说明（含 `modal_databadge` 弹窗内口径说明）、`snap_iso` 快照日期。
   - `sectors`：板块分组（key 需与个股 `sector` 字段对应，title/label/color 自定义）。
   - `combos`：推荐组合（cls 决定配色，codes 引用个股 code，desc 说明）。
   - `stocks`：个股数组，字段见下方 schema。
2. **生成页面**：在 `stock-template/` 目录运行
   ```
   python build.py
   ```
   得到同目录 `index.html`。
3. **发布**（可选）：用 CloudStudio 部署 `stock-template/` 目录，得到可分享链接。

## data.json 字段 schema（stocks 数组每个对象）

| 字段 | 含义 | 示例 |
|------|------|------|
| `code` | 股票代码 | `"00700"` |
| `zh` / `en` | 中文名 / 英文名 | `"腾讯控股"` |
| `l1` / `l2` / `l2_code` | 一级/二级类别名 + 二级代码 | `"资讯科技业"` |
| `sector` | 所属板块 key（对应 sectors.key） | `"tech"` |
| `signal` | 推荐信号索引：0=🟢可分批 / 1=🟡持有 / 2=🔴谨慎 | `0` |
| `border` | 卡片左边框配色 class | `"yellow"` |
| `price` `chg` `pe` `pb` `div` `mkt` `pos` | 现价/涨跌%/PE/PB/股息率%/市值/52周分位 | `512.0` |
| `w52l` `w52h` `open` `prev` `turn` `amount` | 52周低/高/今开/昨收/换手率/成交额 | `198.6` |
| `chg5` `chg20` `chg60` `ytd` | 近5/20/60日、年初至今涨跌% | `3.2` |
| `capital` | 资金面描述文本 | `"南向持续净流入…"` |
| `risks` | 风险提示列表（3 条） | `["…","…","…"]` |
| `roe` `margin` `liab` `south` | 真实 ROE% / 毛利率% / 资产负债率% / 南向(港股通)持股% | `21.13` |
| `div5` | 近5年每股股息(HKD)，无/未分红用 `null` | `[null,null,3.40,4.50,5.30]` |
| `suggest` `summary` `trend` | 建仓建议/一句话总结/走势（可选扩展字段） | `"…"` |

> `margin` 为 `null` 时渲染"不适用"（金融/资源业不适用毛利率）。

## 需要微调布局时（少数情况）

以下属于**布局层**，若切换到 A 股/美股等需相应改名，直接在 `build.py` 中改即可：
- 模块标题与标签（如 M3「南向(港股通)持股」→ A股可改「北向持股」；M4 注释口径说明）。
- 配色、卡片网格、弹窗宽度等 CSS。

常规换市场**不必动 `build.py`**，只改 `data.json`。

## `fundflow/` —— A股收盘资金流抓取模块

独立追踪 A 股每日收盘后的资金流动数据（与上面的页面模板解耦）。

| 文件 | 作用 |
|------|------|
| `fundflow_main.py` | **主脚本**。先调用数据生产层，再基于 JSON 中间产物生成 HTML。 |
| `funflow_data_fetcher.py` | **数据抓取层**。覆盖主要指数、申万一级 31 行业涨跌幅 + 按申万成分股聚合的主力净流入、北向资金（仅成交额+占比，净买入不编造）、风格指数、个股资金流 TOP 与热点异动。抓取层使用 `AKShare`，指数回退腾讯 gtimg；个股资金流优先按申万成分股 `secid` 分批请求，行业聚合与个股 TOP 共用同一批数据。 |
| `funflow_ui_renderer.py` | **UI 渲染层**。读取 JSON 中间产物并生成纯静态 HTML。 |
| `report.css` | 网页报告样式源（深色金融终端风、涨红跌绿），生成 HTML 时**内联**进产物，保证 HTML 单文件自包含。 |

**输出**（默认写入项目根 `build/`，已 gitignore；文件名固定无日期，每天运行覆盖前一天）：

| 产物 | 说明 |
|------|------|
| `build/funflow.html` | **默认输出**。纯静态网页报告（数据内联、零 JS），移动端 Safari 可直接打开；打开/刷新即见最新。 |
| `build/funflow.json` / `_industry.csv` | 中间数据与可选行业表，由主脚本或数据层脚本产出。 |

**日常用法**：每天跑一次 py 更新数据，打开 `build/funflow.html` 即见最新报告。

```bash
cd fundflow
../.venv/bin/python -m pip install -r ../requirements.txt
../.venv/bin/python fundflow_main.py                       # 默认输出 build/funflow.json + build/funflow.html
../.venv/bin/python fundflow_main.py --fmt json,csv,html   # 同时输出 JSON + CSV + HTML
../.venv/bin/python fundflow_main.py --fmt csv --out /tmp/x  # 仅申万行业 CSV，自定义目录
# 省略 --date 自动取最近交易日；偶发超时调优：
# EM_TIMEOUT=8 EM_RETRIES=2 FUND_FLOW_BATCH_SIZE=400 ../.venv/bin/python fundflow_main.py
```

> 注：
> 1. `fundflow/.cache/` 需要随仓库提交，避免 GitHub Actions 每次都是全量回源。
> 2. 申万一级映射和申万成分股映射属于长周期静态数据，默认缓存 180 天；可用 `FUND_STATIC_CACHE_TTL_HOURS` 调整。
> 3. 个股资金流默认按 `FUND_FLOW_BATCH_SIZE=400` 分批请求 `push2delay`，比全市场分页排行请求数更低。

## 自动部署（GitHub Actions + Pages）

`.github/workflows/ashare-report.yml` 会在**每个交易日 15:45（北京时间）收盘后**自动运行脚本并把 HTML 部署到 GitHub Pages：

- 触发：`push`（推 main 即跑）+ `schedule`（周一至五 07:45 UTC）+ `workflow_dispatch`（可手动触发）
- 流程：`python3 fundflow/fundflow_main.py`（默认产出 JSON 中间产物 + HTML，请求间隔 REQ_DELAY=0.4s）→ 把 `build/funflow.html` 作为站点根 `index.html` 上传 → `deploy-pages`
- 一次性配置：仓库 **Settings → Pages → Source 选「GitHub Actions」**，之后每次运行自动更新站点
- 手动触发：仓库 **Actions → 选中该工作流 → Run workflow**
- 站点地址：`https://<owner>.github.io/<repo>/`（根路径即最新报告）
