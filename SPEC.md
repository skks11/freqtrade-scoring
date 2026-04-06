# freqtrade_scoring 接口与配置规范

> 本文档是开发和集成的唯一权威参考。所有配置字段、信号格式、Python API、REST API、数据库结构均以此为准。

---

## 目录

1. [信号 CSV 格式](#1-信号-csv-格式)
2. [配置系统](#2-配置系统)
3. [Python API](#3-python-api)
4. [策略接口](#4-策略接口)
5. [REST API](#5-rest-api)
6. [数据库 Schema](#6-数据库-schema)
7. [数据结构定义](#7-数据结构定义)
8. [文件路径约定](#8-文件路径约定)
9. [错误处理](#9-错误处理)

---

## 1. 信号 CSV 格式

### 1.1 文件路径

```
signals/{StrategyName}/{BASE}_{QUOTE}_{timeframe}.csv
```

- `StrategyName` — 必须与策略类的 `strategy_name` 属性完全一致
- `BASE_QUOTE` — 交易对斜杠替换为下划线（`BTC/USDT` → `BTC_USDT`）
- `timeframe` — 必须与该策略 config 中的 `timeframe` 字段一致（如 `1h`、`4h`、`15m`）
- 每个策略每个交易对一个文件

### 1.2 列定义

| 列名 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `timestamp` | int64 | ✅ | K 线 **open** 时间，Unix 毫秒（UTC） |
| `pair` | string | ✅ | 交易对，斜杠格式，如 `BTC/USDT` |
| `signal` | int | ✅ | 见下方信号值表 |
| `entry_tag` | string | — | 入场原因标签；仅在 `signal=1` 或 `signal=2` 时有效 |
| `exit_tag` | string | — | 出场原因标签；仅在 `signal=-1` 或 `signal=-2` 时有效 |

### 1.3 信号值

| 值 | 方向 | 含义 |
|---:|------|------|
| `1` | Long | 开多 — 开启多头仓位 |
| `-1` | Long | 平多 — 关闭当前多头仓位 |
| `2` | Short | 开空 — 开启空头仓位 |
| `-2` | Short | 平空 — 关闭当前空头仓位 |
| `0` | — | 无操作（保持当前状态） |

**设计原则：** 正数 = 开仓，负数 = 平仓；绝对值 1 = 多头，2 = 空头。

### 1.4 信号语义

- `signal=1` 在已有多头仓位时被忽略；`signal=2` 在已有空头仓位时被忽略
- `signal=-1` 在无多头仓位时被忽略；`signal=-2` 在无空头仓位时被忽略
- 多头与空头仓位**独立追踪**，同一 pair 可同时存在多空（hedge mode）
- 引擎将每个开仓信号与其后最近的对应平仓信号配对，构成一笔交易
- 文件末尾未关闭的仓位会被静默丢弃

### 1.5 exit_tag 保留前缀

| 前缀 | 含义 |
|------|------|
| `tp1` | TP1 止盈信号（mock 引擎据此模拟 TP1 档位收益） |
| `tp2` | TP2 止盈信号 |
| `tp3` | TP3 止盈信号 |
| `sl` / `stop` | 止损信号（mock 引擎据此模拟亏损） |
| 其他字符串 | 策略专属信号，直接传入 `custom_exit` 处理 |

> 注意：在真实 freqtrade 模式下，TP 触发由 `custom_exit` 根据 `current_profit` 阈值自动判断，exit_tag 前缀仅影响 mock 引擎的盈亏模拟。

### 1.6 格式约束

- 编码：**UTF-8**，不含 BOM
- 必须包含 header 行，列名与上表完全一致
- 按 `timestamp` **升序**排列
- 同一 pair 在同一时间戳不允许出现重复行
- `entry_tag` 与 `exit_tag` 可为空字符串或 NaN，统一处理为 `""`
- `pair` 列使用 `/` 分隔（如 `BTC/USDT`），不是 `_`

### 1.7 示例

```csv
timestamp,pair,signal,entry_tag,exit_tag
1672531200000,BTC/USDT,1,breakout_long,
1672617600000,BTC/USDT,0,,
1672790400000,BTC/USDT,-1,,tp2_hit
1672876800000,BTC/USDT,2,resistance_reject,
1673049600000,BTC/USDT,-2,,tp1_hit
1673136000000,ETH/USDT,1,oversold_bounce,
1673222400000,ETH/USDT,-1,,reversal_signal
```

---

## 2. 配置系统

### 2.1 文件位置

```
configs/
├── base_config.json          # 公共基础配置（所有策略共享）
└── strategies/
    └── {StrategyName}.json   # 策略 diff（仅包含需要覆盖的字段）
```

### 2.2 合并规则

```python
merged_config = deep_merge(base_config, strategy_diff)
```

- 使用**递归深合并**：diff 中存在的 key 覆盖 base，不存在的 key 保留 base
- 嵌套 dict 递归合并，不做整体替换
- 若策略无 diff 文件，直接使用 `base_config.json`

### 2.3 base_config.json 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_open_trades` | int | `3` | 最大同时持仓数 |
| `stake_currency` | string | `"USDT"` | 计价货币 |
| `stake_amount` | int/float | `100` | 每笔交易金额 |
| `tradable_balance_ratio` | float | `0.99` | 可用余额比例 |
| `timeframe` | string | `"1h"` | K 线周期 |
| `dry_run` | bool | `true` | 是否模拟模式 |
| `exchange.name` | string | `"binance"` | 交易所名称 |
| `exchange.pair_whitelist` | list[string] | `["BTC/USDT",...]` | 默认交易对列表 |
| `stoploss` | float | `-0.05` | 止损比例（负数） |
| `trailing_stop` | bool | `false` | 是否启用追踪止损 |
| `trailing_stop_positive` | float\|null | `null` | 追踪止损正向距离 |
| `trailing_stop_positive_offset` | float\|null | `null` | 启用正向追踪的收益阈值 |
| `trailing_only_offset_is_reached` | bool | `false` | 仅达到 offset 后才追踪 |
| `minimal_roi` | dict[str, float] | 见下 | 最小 ROI 梯度 |
| `tp_config` | dict | 见下 | 自定义分批止盈配置 |

**minimal_roi 格式：** key 为持仓分钟数（字符串），value 为该时间后触发的最低收益率：

```json
{
  "0":   0.10,
  "60":  0.05,
  "120": 0.02,
  "240": 0.01
}
```

### 2.4 tp_config 字段说明

> `tp_config` 是本框架扩展字段，freqtrade 原生不识别，由 `CsvSignalStrategy` 读取。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `false` | 是否启用分批止盈 |
| `levels` | list[TPLevel] | 见下 | 止盈档位列表（顺序执行） |

**TPLevel 对象：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `ratio` | float | 该档出场的仓位比例（所有档位之和必须等于 1.0） |
| `target` | float | 触发该档的最低收益率（相对入场价，如 `0.01` = 1%） |

**默认 tp_config：**

```json
{
  "enabled": false,
  "levels": [
    {"ratio": 0.33, "target": 0.01},
    {"ratio": 0.33, "target": 0.02},
    {"ratio": 0.34, "target": 0.03}
  ]
}
```

### 2.5 退出优先级

当多个退出条件同时满足时，优先级从高到低：

1. 止损（stoploss）
2. 追踪止损（trailing_stop，若启用）
3. 策略专属 exit_tag（非 tp 前缀，custom_exit 返回）
4. TP1 → TP2 → TP3（按档位顺序，custom_exit 返回）
5. Minimal ROI
6. CSV 中的 signal=-1 / signal=-2

---

## 3. Python API

### 3.1 `scripts/config_manager.py`

```python
def deep_merge(base: dict, override: dict) -> dict
```
递归合并，override 键覆盖 base。返回新 dict，不修改原值。

---

```python
def load_config(strategy_name: str) -> dict
```
加载 `base_config.json` 并与 `configs/strategies/{strategy_name}.json`（若存在）深合并。

| 参数 | 类型 | 说明 |
|------|------|------|
| `strategy_name` | str | 策略名称，对应 diff 文件名 |

返回：完整合并后的 config dict  
异常：`FileNotFoundError` — base_config.json 不存在

---

```python
def get_tp_config(config: dict) -> dict
```
从 config 中提取 tp_config，若缺失字段则补全默认值。返回结构见 [2.4](#24-tp_config-字段说明)。

---

### 3.2 `scripts/run_backtest.py`

```python
def run_backtest(
    strategy: str,
    timerange: str,
    pairs: list[str] | None = None,
    mock: bool = False,
    tag: str = "",
    config_path: Path | None = None,
) -> dict
```

执行回测（mock 模式或真实 freqtrade 模式），保存结果，更新 benchmark。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `strategy` | str | — | 策略名称（必填） |
| `timerange` | str | — | 回测时间范围，格式 `YYYYMMDD-YYYYMMDD`（必填） |
| `pairs` | list[str]\|None | `None` | 指定交易对列表；为 None 时自动发现 signals 目录下所有 CSV |
| `mock` | bool | `False` | `True` = 使用 mock 引擎（无需 freqtrade）；`False` = 调用真实 freqtrade |
| `tag` | str | `""` | 人工标注标签，写入 benchmark |
| `config_path` | Path\|None | `None` | 覆盖默认 base_config 路径（预留，暂未生效） |

返回：
```python
{
    "run_id":            str,     # 唯一标识，格式见下
    "result_dir":        str,     # 结果目录绝对路径
    "strategy":          str,
    "timerange":         str,
    "pairs":             str,     # 逗号分隔
    "total_trades":      int,
    "win_rate":          float,   # 0–1
    "profit_factor":     float,
    "total_profit_pct":  float,
    "max_drawdown":      float,   # 负数
    "avg_duration_mins": int,
    "sharpe":            float,
    "calmar":            float,
}
```

返回 `{}` 时表示回测无结果（零信号或 freqtrade 失败）。

**run_id 格式：** `{StrategyName}_{YYYYmmdd_HHMMSS_ffffff}`（含微秒，确保唯一）

---

### 3.3 `scripts/mock_engine.py`

```python
def run_mock_backtest(
    strategy_name: str,
    config: dict,
    timerange: str,
    pairs: list[str] | None = None,
) -> dict[str, Any]
```

从 CSV 信号模拟回测，不依赖 freqtrade。

| 参数 | 类型 | 说明 |
|------|------|------|
| `strategy_name` | str | 对应 `signals/{strategy_name}/` 目录 |
| `config` | dict | 已合并的完整 config（使用 `stoploss`、`timeframe`、`tp_config`） |
| `timerange` | str | `YYYYMMDD-YYYYMMDD` |
| `pairs` | list[str]\|None | 为 None 时自动扫描 signals 目录下匹配 timeframe 的所有 CSV |

返回：统计 dict，结构见 [7.2 BacktestStats](#72-backteststats)  
随机种子：`random.seed(42)` + `np.random.seed(42)`（保证可复现）  
异常：`FileNotFoundError` — signals 目录不存在

---

### 3.4 `scripts/generate_mock_data.py`

```python
def generate_all(
    start_date: str = "20230101",
    end_date: str = "20240101",
) -> list[Path]
```

为 StrategyA（仅多）、StrategyB（仅多）、StrategyC（多空混合）生成合成信号 CSV。

| 参数 | 格式 | 说明 |
|------|------|------|
| `start_date` | `YYYYMMDD` | 信号起始日期 |
| `end_date` | `YYYYMMDD` | 信号结束日期（不含） |

返回：所有生成的 CSV 文件路径列表

---

## 4. 策略接口

### 4.1 `CsvSignalStrategy` 基类

```python
class CsvSignalStrategy(IStrategy):
    strategy_name: str = "default"  # fallback；优先读 self.config["strategy_name"]
```

**通常不需要子类文件。** `run_backtest.py` 会自动把 `strategy_name` 写入 config，`CsvSignalStrategy` 据此定位 signals 目录：

```
# 只需信号文件 + 可选的 diff config，直接运行：
python scripts/run_backtest.py --strategy MyStrategy --timerange ... --mock
```

**仅当需要自定义退出逻辑时才创建子类：**

```python
from strategies.CsvSignalStrategy import CsvSignalStrategy

class MyStrategy(CsvSignalStrategy):
    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        result = super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)
        if result:
            return result
        # 策略专属逻辑
        return None
```

### 4.2 freqtrade 钩子方法

以下方法由框架自动调用，**不需要在子类中重写**（除非有专属逻辑）：

```python
def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame
```
- 读取 CSV 中 `signal=1` 的行 → 设置 `enter_long=1` + `enter_tag`
- 读取 CSV 中 `signal=2` 的行 → 设置 `enter_short=1` + `enter_tag`

```python
def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame
```
- 读取 CSV 中 `signal=-1` 的行 → 设置 `exit_long=1` + `exit_tag`（tp_config.enabled=True 时跳过，由 custom_exit 处理）
- 读取 CSV 中 `signal=-2` 的行 → 设置 `exit_short=1` + `exit_tag`

```python
def custom_exit(
    self,
    pair: str,
    trade: Trade,
    current_time: pd.Timestamp,
    current_rate: float,
    current_profit: float,
    **kwargs,
) -> str | None
```

执行顺序：
1. 读取当前 K 线时间戳对应的 CSV `exit_tag`
2. 若 exit_tag 非空且不以 `tp1`/`tp2`/`tp3` 开头 → 直接返回该 tag（触发策略专属退出）
3. 若 `tp_config.enabled=True`：遍历 levels，找到首个 `current_profit >= target` 且未触发的档位 → 返回 `"tp1"` / `"tp2"` / `"tp3"`
4. 无匹配 → 返回 `None`（继续持仓）

```python
def custom_stoploss(
    self,
    pair: str,
    trade: Trade,
    current_time: pd.Timestamp,
    current_rate: float,
    current_profit: float,
    **kwargs,
) -> float
```
返回 `self.stoploss`（freqtrade 的 trailing 逻辑在此基础上叠加）。

### 4.3 私有工具方法

| 方法 | 说明 |
|------|------|
| `_load_signals(pair: str) -> pd.DataFrame` | 按 pair 加载并缓存 CSV，pair 格式自动转换 |
| `_get_tp_config() -> dict` | 从 `self.config` 读取 tp_config，补全默认值 |
| `_get_csv_exit_tag(pair: str, current_time: pd.Timestamp) -> str` | 查询指定时间戳的 exit_tag，未找到返回 `""` |

---

## 5. REST API

**Base URL：** `http://{host}:{port}`（默认 `http://127.0.0.1:8080`）

### GET `/api/benchmarks`

查询 benchmark 列表。

**Query 参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `strategy` | string | — | 策略名模糊匹配（LIKE %x%） |
| `tag` | string | — | tag 精确匹配 |
| `min_win_rate` | float [0,1] | — | 胜率下限（≥） |
| `max_drawdown` | float | — | 最大回撤下限（如 `-0.15` 表示回撤不超过 15%） |
| `sort_by` | string | `"run_at"` | 排序字段，可选值见下 |
| `order` | `"asc"` \| `"desc"` | `"desc"` | 排序方向 |
| `limit` | int [1,200] | `50` | 每页条数 |
| `offset` | int ≥0 | `0` | 分页偏移 |

`sort_by` 可选值：`run_at` `win_rate` `profit_factor` `total_profit_pct` `max_drawdown` `sharpe` `calmar` `total_trades` `strategy`

**响应：**

```json
{
  "total": 42,
  "items": [ <BenchmarkRecord>, ... ]
}
```

---

### GET `/api/benchmarks/{run_id}`

查询单条 benchmark 详情。

**响应：** `<BenchmarkRecord>`  
**404：** `{"detail": "Run not found"}`

---

### DELETE `/api/benchmarks/{run_id}`

删除 benchmark 记录（仅删除数据库行，不删除 results/ 目录文件）。

**响应：** `{"status": "deleted", "run_id": "<run_id>"}`  
**404：** `{"detail": "Run not found"}`

---

### POST `/api/benchmarks/import`

从 `results/benchmark.csv` 重新导入数据到数据库（幂等，用于手动同步）。

**响应：** `{"imported": 12, "source": "/path/to/benchmark.csv"}`

---

### GET `/api/trades/{run_id}`

获取某次回测的逐笔交易记录。

**响应：**

```json
{
  "run_id": "StrategyA_20240101_120000_000000",
  "trades": [ <TradeRecord>, ... ]
}
```

**404：** `{"detail": "Trades file not found"}`

---

### GET `/api/health`

健康检查。

**响应：** `{"status": "ok"}`

---

## 6. 数据库 Schema

**文件位置：** `results/benchmark.db`（SQLite）

```sql
CREATE TABLE IF NOT EXISTS benchmark (
    id                INTEGER  PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT     NOT NULL UNIQUE,
    strategy          TEXT     NOT NULL,
    tag               TEXT     DEFAULT '',
    timerange         TEXT     DEFAULT '',
    pairs             TEXT     DEFAULT '',        -- 逗号分隔，如 "BTC/USDT,ETH/USDT"
    total_trades      INTEGER  DEFAULT 0,
    win_rate          REAL     DEFAULT 0,         -- 0–1
    profit_factor     REAL     DEFAULT 0,
    total_profit_pct  REAL     DEFAULT 0,         -- 绝对值，如 0.42 = 42%
    max_drawdown      REAL     DEFAULT 0,         -- 负数，如 -0.12 = -12%
    avg_duration_mins INTEGER  DEFAULT 0,
    sharpe            REAL     DEFAULT 0,
    calmar            REAL     DEFAULT 0,
    run_at            TEXT     DEFAULT ''         -- ISO 8601，如 2024-01-01T12:00:00+00:00
);
```

**索引：** `run_id` 列有 UNIQUE 约束，自动建索引。  
**写入策略：** `INSERT ... ON CONFLICT(run_id) DO UPDATE`（upsert）。

---

## 7. 数据结构定义

### 7.1 BenchmarkRecord

API 返回和数据库行的统一结构：

```typescript
interface BenchmarkRecord {
  id:                number     // 自增主键
  run_id:            string     // 唯一标识，格式: {StrategyName}_{YYYYmmdd_HHMMSS_ffffff}
  strategy:          string     // 策略名称
  tag:               string     // 人工标注标签（可为空）
  timerange:         string     // 回测时间范围，格式: YYYYMMDD-YYYYMMDD
  pairs:             string     // 逗号分隔的交易对列表
  total_trades:      number     // 总交易笔数
  win_rate:          number     // 胜率 [0, 1]
  profit_factor:     number     // 盈亏比 = 总盈利 / |总亏损|
  total_profit_pct:  number     // 总收益率（各笔之和）
  max_drawdown:      number     // 最大回撤，负数
  avg_duration_mins: number     // 平均持仓时长（分钟）
  sharpe:            number     // 年化 Sharpe Ratio
  calmar:            number     // Calmar Ratio = 总收益 / |最大回撤|
  run_at:            string     // 回测执行时间，ISO 8601
}
```

### 7.2 BacktestStats

`run_backtest` 和 `run_mock_backtest` 返回值（不含 `id`，含 `trades`）：

```typescript
interface BacktestStats {
  strategy:          string
  timerange:         string
  pairs:             string
  total_trades:      number
  win_rate:          number     // 精度：4位小数
  profit_factor:     number     // 精度：4位小数
  total_profit_pct:  number     // 精度：4位小数
  max_drawdown:      number     // 精度：4位小数
  avg_duration_mins: number
  sharpe:            number     // 精度：4位小数
  calmar:            number     // 精度：4位小数
  trades:            TradeRecord[]
}
```

### 7.3 TradeRecord

`trades.csv` 中每一行，以及 `GET /api/trades/{run_id}` 响应中每个元素：

```typescript
interface TradeRecord {
  pair:          string    // 交易对，如 "BTC/USDT"
  side:          "long" | "short"
  entry_time:    string    // ISO 8601
  exit_time:     string    // ISO 8601
  duration_mins: number    // 持仓时长（分钟）
  profit_pct:    number    // 本笔收益率，精度：6位小数；正数=盈利，负数=亏损
  entry_tag:     string
  exit_tag:      string
  is_win:        boolean   // profit_pct > 0
}
```

### 7.4 TPConfig

```typescript
interface TPConfig {
  enabled: boolean
  levels:  TPLevel[]  // 按 target 升序排列，所有 ratio 之和必须等于 1.0
}

interface TPLevel {
  ratio:  number  // 出场仓位比例，如 0.33
  target: number  // 触发收益率阈值，如 0.01 (= 1%)
}
```

---

## 8. 文件路径约定

| 路径 | 说明 |
|------|------|
| `configs/base_config.json` | 公共 freqtrade 配置（唯一） |
| `configs/strategies/{Name}.json` | 策略 diff 配置（可选） |
| `signals/{Name}/{PAIR}_{tf}.csv` | 策略信号文件 |
| `results/benchmark.csv` | 所有回测核心指标汇总（仅追加） |
| `results/benchmark.db` | SQLite 数据库（Web 数据源） |
| `results/{run_id}/backtest_results.json` | 单次回测统计 JSON |
| `results/{run_id}/trades.csv` | 单次回测逐笔交易 CSV |
| `results/{run_id}/config_merged.json` | 本次回测实际使用的完整配置（调试用） |
| `strategies/{Name}.py` | freqtrade 策略文件（继承 CsvSignalStrategy） |

---

## 9. 错误处理

| 场景 | 异常类型 | 说明 |
|------|----------|------|
| base_config.json 不存在 | `FileNotFoundError` | 提示文件路径 |
| 策略 diff JSON 格式错误 | `json.JSONDecodeError` | 提示文件路径 |
| 信号 CSV 不存在 | `FileNotFoundError` | 提示完整路径 |
| 信号 CSV 缺少必填列 | `ValueError` | 提示缺失的列名 |
| signals 目录不存在 | `FileNotFoundError` | mock 引擎抛出 |
| freqtrade 进程非零退出 | `RuntimeError` | 保留临时 config 文件供调试，打印 stderr |
| benchmark.csv/DB 写入失败 | 打印 WARNING | 不阻断主流程，结果文件仍保存 |
| API 资源不存在 | HTTP 404 | `{"detail": "<message>"}` |
