# stock-voyager

静态股票分析页面生成项目。当前主流程会统一生成 5 个页面：

- `build/site/index.html`：站点导航首页
- `build/site/fundflow.html`：A 股资金流日报
- `build/site/fundflow_hk.html`：港股资金流日报
- `build/site/stocktrend_ashare.html`：A 股个股走势
- `build/site/stocktrend_hk.html`：港股个股走势

> 全部为零 JS 静态 HTML，适合 GitHub Pages 等静态部署。

## 当前目录角色

| 路径 | 作用 |
|------|------|
| `main.py` | 仓库主入口。统一生成首页、资金流（A 股 + 港股）、个股走势（A 股 + 港股）页面。 |
| `make_snapshot.py` | 数据快照抓取：统一拉取各模块真实数据存盘，供本地预览复用。 |
| `preview_from_snapshot.py` | 读快照渲染 `preview/` 下预览页，零网络请求。 |
| `common/` | 公共模块。包括请求逻辑、JSON 读写、站点导航、缓存目录等。 |
| `fundflow/` | A 股 / 港股资金流页面模块。 |
| `stocktrend/` | A 股 / 港股个股走势页面模块。 |
| `build/site/` | 最终静态站点 HTML。 |
| `build/data/` | 页面级 JSON 中间产物。 |
| `build/cache/` | 按天缓存的请求级数据。 |
| `common/cache/` | 长期稳定缓存目录。默认不按时间过期，按业务规则决定是否刷新。 |

## 页面组织方式

当前站点不是把 4 张内容页硬塞到单个 HTML 里，而是采用：

1. 一个导航首页 `build/site/index.html`
2. 四个独立内容页（A 股资金流 / 港股资金流 / A 股个股走势 / 港股个股走势）
3. 每个内容页底部带静态 tab 导航

这样做的好处是：

- 静态部署最兼容
- 每页都能单独打开和分享
- 页面内容互不耦合，后续继续扩展更轻

## stocktrend 当前结构

`stocktrend` 已经完成从旧模板链路到新主流程的切换：

| 文件 | 作用 |
|------|------|
| `stocktrend_data_fetcher.py` | 生成 `stocktrend` 的 JSON 中间产物（含 A 股 / 港股）。 |
| `stocktrend_processor.py` | 行情数据加工层：聚合、排名、定调等纯计算，零外部请求。 |
| `stocktrend_ui_renderer.py` | 读取 JSON 并渲染 HTML。 |
| `stocktrend_static_data.py` | 港股基础静态数据（行业 / 板块 / 名单）。 |
| `stocktrend_style.css` | `stocktrend` 页面样式。 |

旧的 `data.json`、`build.py`、`stocktrend/index.html` 已经移除，不再参与当前流程。

## 运行方式

推荐直接从仓库根目录运行：

```bash
./.venv/bin/python main.py
./.venv/bin/python main.py --date 2026-08-25
```

也可以只跑单个模块：

```bash
./.venv/bin/python fundflow/fundflow_main.py
./.venv/bin/python stocktrend/stocktrend_data_fetcher.py --market all
./.venv/bin/python stocktrend/stocktrend_ui_renderer.py
```

## 开发预览（快照机制）

改页面布局 / 样式时无需反复请求接口，也不必写 mock：

```bash
./.venv/bin/python make_snapshot.py          # 抓真实数据存盘到 build/data/snapshot.json
./.venv/bin/python preview_from_snapshot.py  # 读快照渲染 preview/*.html 供本地核对
```

- `make_snapshot.py`：统一抓取资金流（A 股 / 港股）+ 个股走势（A 股 / 港股）的真实数据，落盘为单一快照，供预览复用。
- `preview_from_snapshot.py`：读取快照渲染各预览页到 `preview/`，不发起任何网络请求。
- `preview/` 与 `build/` 均为 gitignore，仅本地使用。

## `fundflow/` —— A股 / 港股收盘资金流抓取模块

独立追踪 A 股、港股每日收盘后的资金流动数据（与上面的页面模板解耦）。

| 文件 | 作用 |
|------|------|
| `main.py` | **仓库主入口**。统一生成 `fundflow`（A 股 + 港股）与 `stocktrend` 的 JSON / HTML 页面。 |
| `common/` | **共享模块**。统一放置请求逻辑、JSON 读写、`common/cache/` 等公共能力。 |
| `fundflow_main.py` | `fundflow` 页面总控。先生成 JSON，再渲染 HTML；`market="hk"` 时产出港股资金流页。 |
| `fundflow_data_fetcher.py` | `fundflow` 数据抓取层。请求级缓存写到 `build/cache/`，页面 JSON 写到 `build/data/fundflow.json` / `fundflow_hk.json`。 |
| `fundflow_processor.py` | 加工层：按申万行业聚合、热点 / 异动识别、盘面定调，零外部请求。 |
| `fundflow_ui_renderer.py` | **UI 渲染层**。读取 JSON 中间产物并生成纯静态 HTML。 |
| `report.css` | 网页报告样式源（深色金融终端风、涨红跌绿），生成 HTML 时**内联**进产物，保证 HTML 单文件自包含。 |

**输出**（默认写入项目根 `build/`，已 gitignore）：

| 产物 | 说明 |
|------|------|
| `build/site/index.html` | 站点导航首页，统一链接到四张业务页面。 |
| `build/site/fundflow.html` | A 股资金流日报（数据内联、零 JS），移动端 Safari 可直接打开。 |
| `build/site/fundflow_hk.html` | 港股资金流日报。 |
| `build/site/stocktrend_ashare.html` | A 股个股走势页。 |
| `build/site/stocktrend_hk.html` | 港股个股走势页。 |
| `build/data/fundflow.json` / `fundflow_hk.json` | `fundflow` 汇总 JSON（A 股 / 港股）。 |
| `build/data/stocktrend_ashare.json` / `build/data/stocktrend_hk.json` | `stocktrend` 页面 JSON。 |
| `build/cache/*.json` | 每日请求级缓存，供跨页面复用。 |

**日常用法**：每天跑一次主脚本，打开 `build/site/index.html` 进入站点首页。

```bash
./.venv/bin/python main.py
./.venv/bin/python main.py --date 2026-08-25
./.venv/bin/python fundflow/fundflow_main.py
./.venv/bin/python stocktrend/stocktrend_data_fetcher.py --market all
```

> 注：
> 1. 长期稳定数据统一放在 `common/cache/`；每天变化的数据拆分到 `build/cache/`，页面 JSON 进入 `build/data/`，最终 HTML 进入 `build/site/`。
> 2. `common/cache/` 默认不靠 TTL 驱动失效；像申万行业常量这类参考数据会长期保留。
> 3. 对“长期稳定但可能增量变化”的缓存，采用“命中即复用，发现缺失再刷新”的策略。例如 `sw_stock_map.json` 会在发现当日资金流股票里有未映射代码时自动重拉申万成分股并补齐新股。
> 4. `fundflow` 与 `stocktrend` 共用 `common/market_data.py` 中的请求逻辑。
> 5. `stocktrend` 会优先读取 `build/cache/stock_fundflow_today_full_<date>.json`，直接复用 `fundflow` 已请求过的资金流结果。

## 自动部署（GitHub Actions + Pages）

站点由单一工作流**每日全量**构建并部署：

| 工作流 | 频率 | 说明 |
|--------|------|------|
| `.github/workflows/fundflow-daily.yml` | 每个交易日 16:00（北京时间 = 08:00 UTC，周一至五） | 收盘后全量重建 资金流日报（A 股 + 港股）+ 个股走势（A 股 + 港股）+ 导航首页，一并部署。不再按模块拆分频率（历史曾为「资金流每日 + 个股走势每周五」）。 |

- 触发：`push`（推 main 即运行，可当作手动刷新）+ `schedule`（见上表 cron）+ `workflow_dispatch`（可手动触发）
- 流程：`python main.py` 全量生成 → 上传完整 `build/site/` → `deploy-pages`
- 一次性配置：仓库 **Settings → Pages → Source 选「GitHub Actions」**，之后每次运行自动更新站点
- 手动触发：仓库 **Actions → 股票日报-每日 → Run workflow**
- 站点地址：`https://<owner>.github.io/<repo>/`（根路径即导航首页）

> 注：GitHub Actions 的 `schedule` 只在默认分支（main）上运行；本地修改需合并/推送到 main 后才会按新频率生效。
