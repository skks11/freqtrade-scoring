# freqtrade_scoring 产品需求文档（PRD）

## 1. 项目概述

### 1.1 背景与目标

构建一套基于 freqtrade 的量化策略回测工具，支持多策略管理、信号驱动回测、灵活止盈止损配置，以及结构化的结果管理与比较能力。

核心目标：
- 将不同策略的交易信号与回测执行解耦，策略信号以 CSV 格式独立维护
- 统一 freqtrade 配置管理，减少重复配置，只维护各策略的 diff
- 提供标准化的回测结果存储与跨策略对比能力
- 支持灵活的 TP（多档位分批止盈）、SL、Trailing Stop、Minimal ROI 配置

### 1.2 技术栈

- **回测引擎**: freqtrade（需本地安装，版本 >= 2023.x）
- **语言**: Python 3.10+
- **数据格式**: JSON（配置）、CSV（信号、benchmark）
- **运行方式**: CLI 脚本 + Python API

### 1.3 核心约束

- 所有回测基于同一 `base_config.json`，各策略只维护 diff 部分
- 策略代码不包含信号生成逻辑，信号完全由外部 CSV 驱动
- custom_exit 必须开启，用于实现多档 TP 和策略专属退出逻辑

---

## 2. 目录结构

```
freqtrade_scoring/
│
├── configs/
│   ├── base_config.json              # 公共基础配置（exchange、stake、timeframe 等）
│   └── strategies/
│       ├── StrategyA.json            # 策略 A 的 diff 配置（仅包含覆盖字段）
│       └── StrategyB.json            # 策略 B 的 diff 配置
│
├── signals/
│   └── {StrategyName}/
│       └── {PAIR}_{timeframe}.csv    # 策略信号文件，例: BTC_USDT_1h.csv
│
├── results/
│   ├── benchmark.csv                 # 全局 benchmark，仅保留核心指标
│   └── {StrategyName}_{YYYYMMDD_HHMMSS}/
│       ├── config_merged.json        # 本次回测实际使用的完整配置（调试用）
│       ├── backtest_results.json     # freqtrade 原始回测输出
│       └── trades.csv                # 逐笔交易记录（从 backtest_results 提取）
│
├── strategies/
│   └── CsvSignalStrategy.py          # 回测模板策略基类
│
├── scripts/
│   ├── download_data.py              # 数据下载脚本
│   ├── run_backtest.py               # 回测执行脚本
│   └── compare_results.py            # 结果比较脚本
│
├── user_data/                        # freqtrade 标准目录（数据、日志等）
│   └── data/
│
└── prd.md
```

---

## 3. 模块功能规格

### 3.1 配置管理模块

#### base_config.json 结构（示例）

```json
{
  "max_open_trades": 3,
  "stake_currency": "USDT",
  "stake_amount": 100,
  "tradable_balance_ratio": 0.99,
  "fiat_display_currency": "USD",
  "timeframe": "1h",
  "dry_run": true,
  "exchange": {
    "name": "binance",
    "key": "",
    "secret": "",
    "ccxt_config": {},
    "pair_whitelist": ["BTC/USDT", "ETH/USDT"]
  },
  "dataformat_ohlcv": "json",
  "dataformat_trades": "jsongz",
  "stoploss": -0.05,
  "trailing_stop": false,
  "minimal_roi": {
    "0": 0.10,
    "30": 0.05,
    "60": 0.02,
    "120": 0.01
  }
}
```

#### 策略 diff 配置（configs/strategies/StrategyA.json）

只写需要覆盖的字段，不写则继承 base_config：

```json
{
  "stoploss": -0.03,
  "trailing_stop": true,
  "trailing_stop_positive": 0.01,
  "trailing_stop_positive_offset": 0.02,
  "trailing_only_offset_is_reached": true,
  "minimal_roi": {
    "0": 0.05,
    "60": 0.02
  },
  "tp_config": {
    "enabled": true,
    "levels": [
      {"ratio": 0.33, "target": 0.01},
      {"ratio": 0.33, "target": 0.02},
      {"ratio": 0.34, "target": 0.03}
    ]
  }
}
```

#### 配置合并规则

- 使用递归 `deep_merge(base, diff)`：diff 中存在的 key 覆盖 base，不存在的 key 保留 base
- 合并结果写入 `results/{run_id}/config_merged.json` 供调试
- `tp_config` 是自定义扩展字段，freqtrade 原生不识别，由策略模板类读取

#### 默认值

如果策略 diff 中未配置以下字段，使用以下默认值：

| 字段 | 默认值 |
|------|--------|
| stoploss | -0.05 |
| trailing_stop | false |
| minimal_roi | {"0": 0.10, "60": 0.02} |
| tp_config.enabled | false |
| tp_config.levels | [{ratio:0.33, target:0.01}, {ratio:0.33, target:0.02}, {ratio:0.34, target:0.03}] |

---

### 3.2 信号 CSV 格式

#### 文件命名

`signals/{StrategyName}/{PAIR}_{timeframe}.csv`

例：`signals/StrategyA/BTC_USDT_1h.csv`（pair 中的 `/` 替换为 `_`）

#### 列定义

| 列名 | 类型 | 必填 | 说明 |
|------|------|------|------|
| timestamp | int64 | 是 | Unix 时间戳（毫秒），对应 K 线 open 时间 |
| pair | string | 是 | 交易对，例: `BTC/USDT` |
| signal | int | 是 | 1=做多入场, -1=平仓退出, 0=无信号 |
| entry_tag | string | 否 | 入场信号标签，signal=1 时有效，用于区分入场类型 |
| exit_tag | string | 否 | 出场信号标签，signal=-1 时有效，驱动 custom_exit 逻辑 |

#### 示例数据

```csv
timestamp,pair,signal,entry_tag,exit_tag
1704067200000,BTC/USDT,1,breakout_long,
1704153600000,BTC/USDT,0,,
1704240000000,BTC/USDT,-1,,manual_exit
1704326400000,ETH/USDT,1,momentum_long,
1704412800000,ETH/USDT,-1,,tp3_hit
```

#### 约束

- 同一 pair 在持仓期间（signal=1 之后、signal=-1 之前），中间行的 signal 应为 0
- exit_tag 中的特殊前缀：
  - `tp1_` / `tp2_` / `tp3_`：触发对应 TP 档位的分批出场
  - 其他任意字符串：视为策略专属退出信号，传入 custom_exit 处理

---

### 3.3 策略模板类 `CsvSignalStrategy`

文件路径：`strategies/CsvSignalStrategy.py`

#### 类结构

```python
class CsvSignalStrategy(IStrategy):
    """
    基于外部 CSV 信号的回测模板策略。
    子策略继承此类，通过设置 strategy_name 指定信号文件目录。
    """

    # freqtrade 必须配置
    INTERFACE_VERSION = 3
    can_short = False
    use_custom_stoploss = True       # 启用自定义止损（trailing 扩展用）
    process_only_new_candles = True

    # 子类可覆盖
    strategy_name: str = "default"   # 对应 signals/{strategy_name}/ 目录

    # 内部状态：记录每个 trade 已执行的 TP 档位
    _tp_filled: dict = {}            # {trade_id: set of tp level indices filled}
```

#### 方法规格

**`populate_entry_trend(dataframe, metadata)`**
- 读取 `signals/{strategy_name}/{pair}_{timeframe}.csv`
- 将 signal==1 的 timestamp 行标记 `enter_long=1`，并写入 `enter_tag`
- CSV 按 pair 缓存，避免重复 IO

**`populate_exit_trend(dataframe, metadata)`**
- 将 signal==-1 的 timestamp 行标记 `exit_long=1`，并写入 `exit_tag`
- 此处仅处理无 TP 配置的硬性退出；TP 退出在 custom_exit 中处理

**`custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)`**
- 优先级顺序：
  1. 检查 CSV 中是否有对应时间戳的 exit_tag，若有且不是 tp* 前缀，触发策略专属退出
  2. 若 tp_config.enabled=True，检查当前收益是否达到各 TP 目标：
     - TP1：current_profit >= levels[0].target，且 TP1 尚未执行 → 返回 `"tp1"`，出场 33%
     - TP2：current_profit >= levels[1].target，且 TP2 尚未执行 → 返回 `"tp2"`，出场 33%
     - TP3：current_profit >= levels[2].target，且 TP3 尚未执行 → 返回 `"tp3"`，出场剩余 34%
  3. 无触发 → 返回 None（继续持仓）

> 注意：freqtrade 的 custom_exit 返回非 None 字符串即触发退出，分批出场依赖 `custom_exit_profit_only=True` 和 stake 管理，详见实现细节。

**`custom_stoploss(pair, trade, current_time, current_rate, current_profit, **kwargs)`**
- 若 trailing_stop 配置生效，从合并后的 config 读取 trailing 参数
- 默认透传 freqtrade 内置 trailing 逻辑（返回 `self.stoploss`）
- 子类可覆盖此方法实现动态止损

**`_load_signals(pair: str) -> pd.DataFrame`**
- 私有方法，按 pair 缓存 CSV，返回该 pair 的全部信号 DataFrame
- pair 格式转换：`BTC/USDT` → `BTC_USDT`

**`_get_tp_config() -> dict`**
- 从 `self.config` 中读取 `tp_config`，若不存在返回默认配置

#### 子策略示例

```python
# strategies/StrategyA.py
from CsvSignalStrategy import CsvSignalStrategy

class StrategyA(CsvSignalStrategy):
    strategy_name = "StrategyA"

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        # 可在父类逻辑基础上增加专属逻辑
        exit_reason = super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)
        if exit_reason:
            return exit_reason
        # 策略 A 专属：如果持仓超过 48 小时且亏损超过 2%，强制退出
        hours_held = (current_time - trade.open_date_utc).total_seconds() / 3600
        if current_profit < -0.02 and hours_held > 48:
            return "timeout_exit"
        return None
```

---

### 3.4 数据下载模块

文件：`scripts/download_data.py`

#### CLI 接口

```bash
python scripts/download_data.py \
  --pairs BTC/USDT ETH/USDT \
  --timeframes 1h 4h \
  --days 365 \
  [--exchange binance] \
  [--config configs/base_config.json]
```

#### Python API

```python
from scripts.download_data import download_data

download_data(
    pairs=["BTC/USDT", "ETH/USDT"],
    timeframes=["1h"],
    days=365,
    config_path="configs/base_config.json"
)
```

#### 实现逻辑

1. 加载 base_config.json
2. 调用 freqtrade CLI：`freqtrade download-data --config {tmp_config} --pairs {pairs} --timeframes {timeframes} --days {days}`
3. 数据保存至 `user_data/data/{exchange}/`

---

### 3.5 回测执行模块

文件：`scripts/run_backtest.py`

#### CLI 接口

```bash
python scripts/run_backtest.py \
  --strategy StrategyA \
  --timerange 20230101-20231231 \
  [--pairs BTC/USDT ETH/USDT] \
  [--config configs/base_config.json] \
  [--tag "v1_experiment"]
```

#### Python API

```python
from scripts.run_backtest import run_backtest

result = run_backtest(
    strategy="StrategyA",
    timerange="20230101-20231231",
    pairs=["BTC/USDT"],
    tag="v1_experiment"
)
# result: {"run_id": "StrategyA_20240101_120000", "result_dir": "results/StrategyA_20240101_120000/"}
```

#### 执行流程

```
1. 加载 base_config.json
2. 若存在 configs/strategies/{StrategyName}.json，deep_merge 得到完整 config
3. 写入 /tmp/freqtrade_run_{uuid}.json（临时 config）
4. 创建结果目录: results/{StrategyName}_{YYYYMMDD_HHMMSS}/
5. 保存 config_merged.json 到结果目录
6. 执行: freqtrade backtesting --config {tmp_config} --strategy {StrategyName} --timerange {timerange} --export trades
7. 将 freqtrade 输出的 backtest_results.json 和 trades.csv 移入结果目录
8. 解析 backtest_results.json，提取核心指标，追加到 results/benchmark.csv
9. 清理临时 config 文件（失败时保留）
```

---

### 3.6 结果管理与比较模块

文件：`scripts/compare_results.py`

#### CLI 接口

```bash
# 列出所有回测记录
python scripts/compare_results.py list

# 对比指定策略的多次回测
python scripts/compare_results.py compare --strategies StrategyA StrategyB

# 显示某次回测详情
python scripts/compare_results.py show --run-id StrategyA_20240101_120000
```

#### benchmark.csv 格式

```csv
run_id,strategy,tag,timerange,pairs,total_trades,win_rate,profit_factor,total_profit_pct,max_drawdown,avg_duration_mins,sharpe,calmar,run_at
StrategyA_20240101_120000,StrategyA,,20230101-20231231,"BTC/USDT,ETH/USDT",245,0.58,1.32,0.42,-0.12,187,1.45,2.10,2024-01-01T12:00:00
StrategyB_20240102_083000,StrategyB,v1_experiment,20230101-20231231,BTC/USDT,312,0.61,1.48,0.55,-0.09,143,1.72,2.85,2024-01-02T08:30:00
```

#### 核心指标说明

| 字段 | 说明 |
|------|------|
| run_id | 唯一标识，格式: `{StrategyName}_{YYYYMMDD_HHMMSS}` |
| strategy | 策略名称 |
| tag | 可选的人工标注标签 |
| timerange | 回测时间范围 |
| pairs | 回测交易对（逗号分隔） |
| total_trades | 总交易次数 |
| win_rate | 胜率（0~1） |
| profit_factor | 盈亏比 |
| total_profit_pct | 总收益率（百分比形式，如 0.42 表示 42%） |
| max_drawdown | 最大回撤（负数，如 -0.12 表示 -12%） |
| avg_duration_mins | 平均持仓时长（分钟） |
| sharpe | Sharpe Ratio |
| calmar | Calmar Ratio |
| run_at | 回测执行时间（ISO 8601） |

---

## 4. TP/SL 完整配置规格

### 4.1 SL（止损）

```json
{
  "stoploss": -0.03
}
```

### 4.2 Trailing Stop

```json
{
  "trailing_stop": true,
  "trailing_stop_positive": 0.01,
  "trailing_stop_positive_offset": 0.02,
  "trailing_only_offset_is_reached": true
}
```

- `trailing_stop_positive`：收益达到 offset 后启动的追踪止损距离
- `trailing_only_offset_is_reached`：只有收益超过 offset 才启动 trailing

### 4.3 Minimal ROI

```json
{
  "minimal_roi": {
    "0": 0.10,
    "30": 0.05,
    "60": 0.02,
    "120": 0.01,
    "240": 0
  }
}
```

键为持仓分钟数，值为该时间点之后满足即退出的最低收益率。

### 4.4 多档 TP（tp_config）

```json
{
  "tp_config": {
    "enabled": true,
    "levels": [
      {"ratio": 0.33, "target": 0.01},
      {"ratio": 0.33, "target": 0.02},
      {"ratio": 0.34, "target": 0.03}
    ]
  }
}
```

- `ratio`：该档位出场的仓位比例（三档合计必须等于 1.0）
- `target`：触发该档位出场的最低收益率（相对入场价）
- 默认 3 档，比例默认 33%/33%/34%
- TP 档位数量和比例可在 diff 配置中自定义

### 4.5 退出优先级

当多个退出条件同时满足时，优先级从高到低：

1. SL（止损）
2. Trailing Stop（如启用）
3. 策略专属 exit_tag（custom_exit 中处理）
4. TP1 / TP2 / TP3（按档位顺序）
5. Minimal ROI
6. CSV 中的 signal=-1

---

## 5. 错误处理规范

| 错误场景 | 处理方式 |
|----------|----------|
| 信号 CSV 文件不存在 | 抛出 `FileNotFoundError`，明确提示路径 |
| CSV 列缺失或格式错误 | 抛出 `ValueError`，提示行号和列名 |
| 策略 diff JSON 格式错误 | 抛出 `json.JSONDecodeError`，提示文件路径 |
| freqtrade 回测失败 | 保留临时 config 文件，打印 freqtrade 错误输出，抛出 `RuntimeError` |
| benchmark.csv 写入失败 | 打印警告，不阻断主流程，回测结果仍保存 |
| pair 数据不存在 | 打印警告，跳过该 pair 继续处理其他 pair |

---

## 6. 扩展性设计

### 6.1 新增策略

1. 在 `signals/{NewStrategy}/` 下放置信号 CSV 文件
2. 可选：在 `configs/strategies/NewStrategy.json` 中添加 diff 配置
3. 创建 `strategies/NewStrategy.py`，继承 `CsvSignalStrategy`，设置 `strategy_name = "NewStrategy"`
4. 无需修改任何公共模块

### 6.2 自定义 exit_tag 处理

通过解析 entry_tag / exit_tag 实现策略专属逻辑：

```python
def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
    exit_tag = self._get_csv_exit_tag(pair, current_time)

    # 通用 TP 处理（父类）
    tp_result = self._check_tp_levels(trade, current_profit)
    if tp_result:
        return tp_result

    # 策略专属标签处理
    if exit_tag == "reversal_signal":
        return "reversal_exit"
    if exit_tag == "news_event":
        return "news_forced_exit"

    return None
```

### 6.3 多时间框架信号

CSV 文件按 timeframe 独立存储，策略类在初始化时根据 `self.timeframe` 自动选择对应文件。

---

## 7. 非功能性需求

| 项目 | 要求 |
|------|------|
| Python 版本 | 3.10+ |
| freqtrade 版本 | >= 2023.10 |
| CSV 信号文件大小 | 单文件支持 100 万行以上（使用 pandas 分块读取） |
| 结果目录 | 每次回测独立目录，不覆盖历史结果 |
| 配置文件编码 | UTF-8 |
| 日志 | 所有脚本使用 Python logging，支持 --verbose 参数 |
| 可测试性 | 核心逻辑（config merge、CSV 加载、TP 计算）提供单元测试 |

---

## 8. Benchmark Web 可视化

### 8.1 概述

提供一个轻量级 Web UI，用于浏览、筛选、排序和管理回测 benchmark 记录，替代直接查看 CSV 文件的方式。

### 8.2 技术选型

| 层 | 技术 |
|----|------|
| 后端 | Python + FastAPI |
| 数据库 | SQLite（单文件，无需部署，路径：`results/benchmark.db`） |
| 前端 | 原生 HTML + JavaScript（无框架依赖，单页面） |
| 数据迁移 | 首次启动时自动将 `benchmark.csv` 导入 SQLite |

选择 SQLite 的原因：部署零成本，文件可随结果目录一同备份，支持 SQL 查询满足排序/筛选需求。

### 8.3 目录结构补充

```
freqtrade_scoring/
├── web/
│   ├── app.py               # FastAPI 应用入口
│   ├── db.py                # SQLite 数据库操作（建表、CRUD）
│   └── static/
│       └── index.html       # 单页前端
└── results/
    └── benchmark.db         # SQLite 数据库文件
```

### 8.4 数据库 Schema

```sql
CREATE TABLE benchmark (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL UNIQUE,
    strategy    TEXT NOT NULL,
    tag         TEXT,
    timerange   TEXT,
    pairs       TEXT,                   -- 逗号分隔
    total_trades INTEGER,
    win_rate    REAL,
    profit_factor REAL,
    total_profit_pct REAL,
    max_drawdown REAL,
    avg_duration_mins INTEGER,
    sharpe      REAL,
    calmar      REAL,
    run_at      TEXT                    -- ISO 8601
);
```

### 8.5 API 接口

**`GET /api/benchmarks`**

查询 benchmark 列表，支持以下 query 参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| strategy | string | 按策略名过滤（模糊匹配） |
| tag | string | 按 tag 过滤（精确匹配） |
| min_win_rate | float | 胜率下限 |
| max_drawdown | float | 最大回撤上限（如 -0.1 表示回撤不超过 10%） |
| sort_by | string | 排序字段，默认 `run_at` |
| order | string | `asc` 或 `desc`，默认 `desc` |
| limit | int | 返回条数，默认 50 |
| offset | int | 分页偏移，默认 0 |

响应示例：
```json
{
  "total": 42,
  "items": [
    {
      "run_id": "StrategyA_20240101_120000",
      "strategy": "StrategyA",
      "win_rate": 0.58,
      "total_profit_pct": 0.42,
      "max_drawdown": -0.12,
      "sharpe": 1.45,
      "run_at": "2024-01-01T12:00:00"
    }
  ]
}
```

**`DELETE /api/benchmarks/{run_id}`**

删除指定回测记录（仅删除数据库记录，不删除 results/ 目录下的文件）。

**`GET /api/benchmarks/{run_id}`**

获取单条记录详情，包含全部字段。

**`POST /api/benchmarks/import`**

从 `benchmark.csv` 重新导入数据（用于手动同步）。

### 8.6 前端功能

**页面布局**

```
┌─────────────────────────────────────────────┐
│  freqtrade Benchmark Dashboard              │
├──────────────┬──────────────────────────────┤
│  筛选面板     │  结果表格                     │
│              │                              │
│  Strategy:   │  run_id | strategy | WR |    │
│  [input]     │  profit | drawdown | sharpe  │
│              │  [排序箭头]  [删除按钮]        │
│  Min WR:     │                              │
│  [0~1 slider]│  分页控制                    │
│              │                              │
│  Max DD:     │                              │
│  [input]     │                              │
│              │                              │
│  Sort by:    │                              │
│  [dropdown]  │                              │
│              │                              │
│  [Apply]     │                              │
└──────────────┴──────────────────────────────┘
```

**交互功能**

| 功能 | 说明 |
|------|------|
| 筛选 | 按策略名（模糊）、tag、胜率下限、最大回撤上限筛选 |
| 排序 | 点击表头切换升序/降序，支持所有数值字段 |
| 删除 | 每行右侧有删除按钮，二次确认后调用 DELETE API |
| 分页 | 每页 20 条，显示总条数和当前页码 |
| 刷新 | 顶部刷新按钮重新拉取数据 |
| 高亮 | sharpe > 1.5 绿色高亮，max_drawdown < -0.2 红色高亮 |

### 8.7 启动方式

```bash
# 启动 Web 服务（默认端口 8080）
python web/app.py [--port 8080] [--db results/benchmark.db]
```

首次启动时若 `benchmark.db` 不存在，自动建表并从 `benchmark.csv` 导入数据。

### 8.8 回测写入 DB

`run_backtest.py` 完成回测后，除追加 `benchmark.csv` 外，同时将记录 INSERT 到 `benchmark.db`（若 DB 文件存在）。

---

## 9. 开发优先级

| 优先级 | 模块 |
|--------|------|
| P0 | 配置管理（base_config + diff merge） |
| P0 | CsvSignalStrategy 模板类（entry/exit/custom_exit） |
| P0 | 回测执行脚本（run_backtest.py） |
| P1 | 数据下载脚本（download_data.py） |
| P1 | Benchmark DB 写入（SQLite） |
| P1 | Web 可视化（FastAPI + 单页前端） |
| P2 | 结果比较脚本（compare_results.py） |
| P2 | 多档 TP 分批出场（freqtrade 限制需验证可行性） |
