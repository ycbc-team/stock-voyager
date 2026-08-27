# Agent.md — stocktrend 模块

个股走势分析页面生成模块。这里保留两类信息：

1. 原需求文档里的关键业务口径，避免删文档后丢约束。
2. 当前仓库这版重构后的实际代码结构，方便后续继续清理遗留文件。

## 一、模块职责

- 每个交易日生成静态个股走势页面。
- 当前主入口由仓库根目录 `main.py` 统一调度，会同时生成：
  - `fundflow`
  - `stocktrend`
- `stocktrend` 目前支持两套页面：
  - `build/data/stocktrend_ashare.json` + `build/site/stocktrend_ashare.html`
  - `build/data/stocktrend_hk.json` + `build/site/stocktrend_hk.html`

## 二、原需求里的关键业务信息

### 1. A 股页面目标

- 面向 **32 只核心 A 股** 做每日收盘后的静态分析页。
- 报告口径以 **收盘快照** 为准，不取盘中实时值，不编造缺失数据。
- 页面应支持历史回看，核心字段围绕行情、资金面、估值、分红、财务质量展开。

### 2. 原需求中的核心口径

- 行情/估值：按交易日 **收盘口径** 获取。
- 主力净流入：按当日收盘口径获取。
- 两融：允许使用 **T-1 真实值**，但必须如实标注。
- 北向持股：**T-1 属正常口径**，不算异常缺失。
- 10Y 国债收益率：若当日未发布，可沿用上一交易日真实值，并注明口径。
- 缺失处理原则：宁可展示 `—`，也不要补造数字。
- A 股配色：**涨红跌绿**。

### 3. A 股标的范围

原需求固定跟踪 32 只核心 A 股，覆盖消费、医药、制造、科技、金融、资源等方向，包含：

- 贵州茅台、伊利股份、恒瑞医药、美的集团、海澜之家、公牛集团、中国中免、锦江酒店、珀莱雅
- 中国神华、中国海油、万华化学、中信特钢、紫金矿业、宁德时代、海螺水泥、中国建筑
- 海康威视、比亚迪、同花顺、中国移动、分众传媒、中航沈飞、三一重工、招商银行、中国平安
- 保利发展、长江电力、伟明环保、京沪高铁、云南白药、中国船舶

代码格式约束仍然重要：

- westock：`sh600519`
- 妙想：`600519`
- Wind：`600519.SH`

不同数据源代码格式不能混用。

### 4. 原需求里的详情页模块重点

- 行情快照
- 估值与位置
- 资金面动态
- 财务与分红
- 区间走势
- 风险提示
- 一句话总结

原文档还强调：

- 页面顶部要明确声明“静态收盘快照”。
- 财务历史与分红历史可以是低频维护数据，但必须和实时行情口径区分开。
- 风险提示与总结允许人工维护，不要求伪装成实时数据。

## 三、当前代码结构

```text
stocktrend/
├── stocktrend_data_fetcher.py   # 拉取数据并产出 JSON 中间结果
├── stocktrend_ui_renderer.py    # 基于 JSON 渲染静态 HTML
├── stocktrend_static_data.py    # 港股基础静态数据
├── stocktrend_style.css         # 独立 CSS 模板
└── Agent.md
```

## 四、当前重构约束

- 每日变化的数据统一拆到 `build/cache/`，页面 JSON 输出到 `build/data/`，HTML 输出到 `build/site/`。
- 长期稳定缓存统一放到 `common/cache/`，默认不按时间过期，而是按业务规则刷新。
- `stocktrend` 会优先复用 `build/cache/` 中已有请求产物，避免和 `fundflow` 重复拉取。
- 请求脚本只产出 JSON，不再输出 CSV。

典型共享产物包括：

- `build/cache/stock_fundflow_today_full_<date>.json`
- `build/cache/stocktrend_ashare_spot_<date>.json`
- `build/cache/stocktrend_hk_spot_<date>.json`
- `build/cache/stocktrend_hist_<market>_<date>.json`

## 五、当前代码现状说明

这版重构已经把公共请求和缓存目录拆到 `common/`，`stocktrend` 当前主流程已经完成两处关键切换：

1. 港股基础静态数据已从旧 `data.json` 切到 `stocktrend_static_data.py`。
2. 页面样式已从旧 `build.py` 内嵌 CSS 切到 `stocktrend_style.css`。

因此 `data.json` 与 `build.py` 已不再是运行依赖，可以删除。

## 六、运行方式

统一走仓库根目录：

```bash
python3 main.py
```

可选参数：

```bash
python3 main.py --date 2026-08-25
python3 main.py --stocktrend-market ashare
python3 main.py --stocktrend-market hk
```

## 七、Agent 操作红线

- 不要把盘中实时值当成收盘值写入页面。
- 不要对缺失字段做 alias、猜测或补造。
- 需要复用的数据优先读 `build/cache/`，长期稳定映射才进 `common/cache/`。
- 后续继续清理 `stocktrend` 遗留文件时，优先保留当前主流程依赖的 `stocktrend_static_data.py` 与 `stocktrend_style.css`。
