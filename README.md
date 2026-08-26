# stock-voyager

静态股票分析页面生成项目。当前主流程会统一生成 4 个页面：

- `build/index.html`：站点导航首页
- `build/fundflow.html`：A 股资金流日报
- `build/stocktrend_ashare.html`：A 股个股走势
- `build/stocktrend_hk.html`：港股个股走势

> 全部为零 JS 静态 HTML，适合 GitHub Pages 等静态部署。

## 当前目录角色

| 路径 | 作用 |
|------|------|
| `main.py` | 仓库主入口。统一生成首页、`fundflow`、`stocktrend` 页面。 |
| `common/` | 公共模块。包括请求逻辑、JSON 读写、站点导航、缓存目录等。 |
| `fundflow/` | A 股资金流页面模块。 |
| `stocktrend/` | A 股 / 港股个股走势页面模块。 |
| `build/` | 运行后生成的 JSON / HTML 产物目录。 |
| `common/cache/` | 长期稳定缓存目录。 |

## 页面组织方式

当前站点不是把 3 张内容页硬塞到单个 HTML 里，而是采用：

1. 一个导航首页 `build/index.html`
2. 三个独立内容页
3. 每个内容页底部带静态 tab 导航

这样做的好处是：

- 静态部署最兼容
- 每页都能单独打开和分享
- 页面内容互不耦合，后续继续扩展更轻

## stocktrend 当前结构

`stocktrend` 已经完成从旧模板链路到新主流程的切换：

| 文件 | 作用 |
|------|------|
| `stocktrend_data_fetcher.py` | 生成 `stocktrend` 的 JSON 中间产物。 |
| `stocktrend_ui_renderer.py` | 读取 JSON 并渲染 HTML。 |
| `stocktrend_static_data.py` | 港股基础静态数据。 |
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

## `fundflow/` —— A股收盘资金流抓取模块

独立追踪 A 股每日收盘后的资金流动数据（与上面的页面模板解耦）。

| 文件 | 作用 |
|------|------|
| `main.py` | **仓库主入口**。统一生成 `fundflow` 与 `stocktrend` 的 JSON / HTML 页面。 |
| `common/` | **共享模块**。统一放置请求逻辑、JSON 读写、`common/cache/` 等公共能力。 |
| `fundflow_main.py` | `fundflow` 页面总控。先生成 JSON，再渲染 HTML。 |
| `fundflow_data_fetcher.py` | `fundflow` 数据抓取层。每个请求模块单独产出到 `build/`，再汇总成 `build/fundflow.json`。 |
| `fundflow_ui_renderer.py` | **UI 渲染层**。读取 JSON 中间产物并生成纯静态 HTML。 |
| `report.css` | 网页报告样式源（深色金融终端风、涨红跌绿），生成 HTML 时**内联**进产物，保证 HTML 单文件自包含。 |

**输出**（默认写入项目根 `build/`，已 gitignore；文件名固定无日期，每天运行覆盖前一天）：

| 产物 | 说明 |
|------|------|
| `build/index.html` | 站点导航首页，统一链接到三张业务页面。 |
| `build/fundflow.html` | **默认输出**。纯静态网页报告（数据内联、零 JS），移动端 Safari 可直接打开；打开/刷新即见最新。 |
| `build/stocktrend_ashare.html` | A 股个股走势页。 |
| `build/stocktrend_hk.html` | 港股个股走势页。 |
| `build/fundflow.json` | `fundflow` 汇总 JSON。 |
| `build/fundflow_*.json` / `build/stocktrend_*.json` | 各请求模块拆分后的 JSON 产物，供跨页面复用。 |

**日常用法**：每天跑一次主脚本，打开 `build/index.html` 进入站点首页。

```bash
./.venv/bin/python main.py
./.venv/bin/python main.py --date 2026-08-25
./.venv/bin/python fundflow/fundflow_main.py
./.venv/bin/python stocktrend/stocktrend_data_fetcher.py --market all
```

> 注：
> 1. 长期稳定数据统一放在 `common/cache/`；每天变化的数据统一放在项目根 `build/`。
> 2. `fundflow` 与 `stocktrend` 共用 `common/market_data.py` 中的请求逻辑。
> 3. `stocktrend` 会优先读取 `build/stock_fundflow_today_full_<date>.json`，直接复用 `fundflow` 已请求过的资金流结果。

## 自动部署（GitHub Actions + Pages）

`.github/workflows/ashare-report.yml` 会在**每个交易日 15:45（北京时间）收盘后**自动运行脚本并把 HTML 部署到 GitHub Pages：

- 触发：`push`（推 main 即跑）+ `schedule`（周一至五 07:45 UTC）+ `workflow_dispatch`（可手动触发）
- 流程：`python3 main.py`（统一产出首页 + `fundflow` + `stocktrend` JSON / HTML）→ 把 `build/index.html` 作为站点根首页上传，并附带三个业务页面 → `deploy-pages`
- 一次性配置：仓库 **Settings → Pages → Source 选「GitHub Actions」**，之后每次运行自动更新站点
- 手动触发：仓库 **Actions → 选中该工作流 → Run workflow**
- 站点地址：`https://<owner>.github.io/<repo>/`（根路径即导航首页）
