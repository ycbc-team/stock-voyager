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
| `ashare_close_fetcher.py` | **抓取 + 出报告脚本**（零第三方依赖，仅标准库）。覆盖主要指数、申万一级 31 行业涨跌幅+主力净流入、北向资金（仅成交额+占比，净买入不编造）、风格指数、个股资金流 TOP 与热点异动。主源东方财富 push2（与数据宝同源），指数回退腾讯 gtimg。 |
| `report.css` | 网页报告样式源（深色金融终端风、涨红跌绿），生成 HTML 时**内联**进产物，保证 HTML 单文件自包含。 |

**输出**（默认写入项目根 `build/`，已 gitignore；文件名固定无日期，每天运行覆盖前一天）：

| 产物 | 说明 |
|------|------|
| `build/ashare_close.html` | **默认输出**。纯静态网页报告（数据内联、零 JS），移动端 Safari 可直接打开；打开/刷新即见最新。 |
| `build/ashare_close.json` / `.md` / `_industry.csv` | 可选输出，由 `--fmt` 控制。 |

**日常用法**：每天跑一次 py 更新数据，打开 `build/ashare_close.html` 即见最新报告。

```bash
cd fundflow
python3 ashare_close_fetcher.py                            # 默认仅输出 HTML
python3 ashare_close_fetcher.py --fmt json,md,html         # 同时输出 JSON + Markdown + HTML
python3 ashare_close_fetcher.py --fmt csv --out /tmp/x     # 仅申万行业 CSV，自定义目录
# 省略 --date 自动取最近交易日；偶发超时调优：EM_TIMEOUT=8 EM_RETRIES=2 python3 ashare_close_fetcher.py
```

> 注：在 WorkBuddy 沙箱内东方财富板块类接口会被出口代理拦截，只有指数走腾讯回退、其余模块显示「数据暂缺」；在本机 Mac 直接运行即可完整取数并生成全量报告。

## 自动部署（GitHub Actions + Pages）

`.github/workflows/ashare-report.yml` 会在**每个交易日 15:45（北京时间）收盘后**自动运行脚本并把 HTML 部署到 GitHub Pages：

- 触发：`schedule`（周一至五 07:45 UTC）+ `workflow_dispatch`（可手动触发）
- 流程：`python3 fundflow/ashare_close_fetcher.py`（默认仅 HTML，请求间隔 REQ_DELAY=0.4s）→ 把 `build/ashare_close.html` 作为站点根 `index.html` 上传 → `deploy-pages`
- 一次性配置：仓库 **Settings → Pages → Source 选「GitHub Actions」**，之后每次运行自动更新站点
- 手动触发：仓库 **Actions → 选中该工作流 → Run workflow**
- 站点地址：`https://<owner>.github.io/<repo>/`（根路径即最新报告）

