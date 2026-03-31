# freqtrade_scoring

A backtesting framework built on top of [freqtrade](https://github.com/freqtrade/freqtrade) that decouples strategy signals from execution logic, enabling rapid multi-strategy comparison with a built-in web dashboard.

## Features

- **Signal-driven backtesting** — strategies are defined entirely by external CSV signal files; no indicator code required
- **Config diff system** — a single `base_config.json` shared across all strategies; each strategy only stores its overrides
- **Multi-level TP** — configurable 3-point take-profit (TP1/TP2/TP3) with custom position ratios, driven by `custom_exit`
- **Flexible SL/Trailing/ROI** — full freqtrade SL, trailing stop, and minimal ROI support per strategy
- **Structured result storage** — every backtest run gets its own directory with `backtest_results.json`, `trades.csv`, and the merged config used
- **Benchmark tracking** — a rolling `benchmark.csv` + SQLite DB that accumulates key metrics across all runs
- **Web dashboard** — FastAPI + vanilla JS UI with filtering, sorting, pagination, and delete

## Project Structure

```
freqtrade_scoring/
├── configs/
│   ├── base_config.json          # Shared freqtrade config
│   └── strategies/
│       ├── StrategyA.json        # Per-strategy config diff (only overrides)
│       └── StrategyB.json
├── signals/
│   └── {StrategyName}/
│       └── {PAIR}_{timeframe}.csv  # Signal files
├── results/
│   ├── benchmark.csv             # Aggregated metrics (all runs)
│   ├── benchmark.db              # SQLite — source for web dashboard
│   └── {StrategyName}_{timestamp}/
│       ├── backtest_results.json
│       ├── trades.csv
│       └── config_merged.json
├── strategies/
│   ├── CsvSignalStrategy.py      # Base strategy class
│   ├── StrategyA.py
│   └── StrategyB.py
├── scripts/
│   ├── config_manager.py         # Config load + deep merge
│   ├── mock_engine.py            # Backtest simulator (no freqtrade needed)
│   ├── run_backtest.py           # Main backtest runner
│   ├── download_data.py          # Data download wrapper
│   ├── generate_mock_data.py     # Mock signal generator
│   └── compare_results.py        # CLI result comparison
├── web/
│   ├── app.py                    # FastAPI server
│   ├── db.py                     # SQLite CRUD
│   └── static/index.html         # Single-page dashboard
└── demo.py                       # End-to-end demo (mock data → backtests → web UI)
```

## Quick Start

### 1. Install dependencies

```bash
pip install fastapi uvicorn pandas numpy aiofiles
# For real freqtrade backtesting (optional):
pip install freqtrade
```

### 2. Run the full demo (no freqtrade needed)

```bash
python demo.py
```

This will:
1. Generate synthetic signal CSVs for `StrategyA` (1h, 3 pairs) and `StrategyB` (4h, 2 pairs)
2. Run 5 mock backtests across different timeranges and pair subsets
3. Save results to `results/` and populate `benchmark.db`
4. Launch the web dashboard at **http://127.0.0.1:8080**

### 3. Run a single backtest (mock mode)

```bash
python scripts/run_backtest.py \
  --strategy StrategyA \
  --timerange 20230101-20231231 \
  --mock \
  --tag "v1_experiment"
```

### 4. Run a real freqtrade backtest

```bash
python scripts/run_backtest.py \
  --strategy StrategyA \
  --timerange 20230101-20231231 \
  --pairs BTC/USDT ETH/USDT
```

### 5. Start the web dashboard (standalone)

```bash
python web/app.py --port 8080
```

## Signal CSV Format Specification

### File Naming

```
signals/{StrategyName}/{BASE}_{QUOTE}_{timeframe}.csv
```

- `{StrategyName}` — must match the `strategy_name` attribute in the strategy class
- `{BASE}_{QUOTE}` — trading pair with `/` replaced by `_` (e.g. `BTC/USDT` → `BTC_USDT`)
- `{timeframe}` — must match the `timeframe` field in the strategy config (e.g. `1h`, `4h`, `15m`)
- One file per pair per strategy; multi-pair strategies need multiple files

**Examples:**
```
signals/StrategyA/BTC_USDT_1h.csv
signals/StrategyA/ETH_USDT_1h.csv
signals/StrategyB/BTC_USDT_4h.csv
```

---

### Columns

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `timestamp` | int64 | **yes** | K-line **open** time in Unix milliseconds (UTC) |
| `pair` | string | **yes** | Trading pair with slash — e.g. `BTC/USDT` |
| `signal` | int | **yes** | `1` = enter long · `-1` = exit long · `0` = no action |
| `entry_tag` | string | no | Label for the entry reason (only read when `signal=1`) |
| `exit_tag` | string | no | Label for the exit reason (only read when `signal=-1`); drives `custom_exit` logic |

---

### Signal Semantics

- **`signal=1`** — open a long position at this candle's open time. Ignored if already in a trade.
- **`signal=-1`** — close the current long position. Ignored if not in a trade.
- **`signal=0`** — no action; row is still required to maintain a complete candle timeline.
- The engine pairs each `1` with the next subsequent `-1` to form a trade.
- An unclosed position at the end of the file is silently dropped.
- Rows must be **sorted ascending by `timestamp`**; duplicate timestamps for the same pair are undefined behaviour.

---

### entry_tag Convention

Used to label why a trade was entered. Stored in freqtrade's `enter_tag` field and visible in trade logs. No reserved prefixes — any string is valid.

```
breakout_long
momentum_long
mean_revert_dip
news_impulse
```

---

### exit_tag Convention

Controls `custom_exit` routing. The following prefixes have special meaning:

| Prefix | Effect |
|--------|--------|
| `tp1` | Hint to mock engine that this exit is a TP1 hit (profit near TP1 target) |
| `tp2` | Hint to mock engine that this exit is a TP2 hit |
| `tp3` | Hint to mock engine that this exit is a TP3 hit |
| `sl` or `stop` | Hint to mock engine that this exit is a stop-loss hit |
| anything else | Passed directly to `custom_exit` as a strategy-specific signal |

> **Note:** In real freqtrade mode, TP levels are triggered automatically by `custom_exit` based on `current_profit` thresholds — the `exit_tag` prefix is only a hint for the mock engine's P&L simulation. For non-TP exits (e.g. `reversal_signal`, `news_exit`), the strategy's `custom_exit` receives the tag and can act on it.

---

### Complete Example

```csv
timestamp,pair,signal,entry_tag,exit_tag
1672531200000,BTC/USDT,1,breakout_long,
1672617600000,BTC/USDT,0,,
1672704000000,BTC/USDT,0,,
1672790400000,BTC/USDT,-1,,tp2_hit
1672876800000,BTC/USDT,1,momentum_long,
1672963200000,BTC/USDT,-1,,sl_hit
1673049600000,ETH/USDT,1,trend_follow,
1673136000000,ETH/USDT,-1,,manual_exit
```

- Rows 1–4: one BTC trade, entered on breakout, exited at TP2
- Rows 5–6: second BTC trade, entered on momentum, hit stop loss
- Rows 7–8: one ETH trade with a custom strategy-specific exit tag

---

### Encoding & Format Rules

- **Encoding:** UTF-8, no BOM
- **Line endings:** LF or CRLF (both accepted)
- **Header row:** required, exactly the column names shown above
- **Empty values:** `entry_tag` and `exit_tag` may be empty or omitted (treated as `""`)
- **`pair` column:** must use `/` separator (`BTC/USDT`), not `_`
- **`timestamp` column:** milliseconds since Unix epoch (divide by 1000 to get seconds); must align to actual K-line open times for real freqtrade mode to match candles correctly

## Strategy Config Diff

Only write fields that differ from `base_config.json`:

```json
// configs/strategies/StrategyA.json
{
  "stoploss": -0.03,
  "trailing_stop": true,
  "tp_config": {
    "enabled": true,
    "levels": [
      {"ratio": 0.33, "target": 0.01},
      {"ratio": 0.33, "target": 0.025},
      {"ratio": 0.34, "target": 0.04}
    ]
  }
}
```

## Adding a New Strategy

1. Drop signal CSVs into `signals/NewStrategy/`
2. Optionally create `configs/strategies/NewStrategy.json` for overrides
3. Create `strategies/NewStrategy.py`:

```python
from strategies.CsvSignalStrategy import CsvSignalStrategy

class NewStrategy(CsvSignalStrategy):
    strategy_name = "NewStrategy"
    timeframe = "1h"
```

4. Run: `python scripts/run_backtest.py --strategy NewStrategy --timerange ... --mock`

## Web Dashboard

The dashboard reads from `results/benchmark.db` and supports:

- **Filter** by strategy name (fuzzy), tag, min win rate, max drawdown
- **Sort** by any metric column (click header)
- **Paginate** (20 records per page)
- **Detail view** per run (trades JSON linked)
- **Delete** records with confirmation

## Benchmark Metrics

| Metric | Description |
|--------|-------------|
| `win_rate` | Fraction of profitable trades |
| `profit_factor` | Gross profit / gross loss |
| `total_profit_pct` | Sum of all trade returns |
| `max_drawdown` | Largest peak-to-trough equity drop |
| `sharpe` | Annualised Sharpe ratio |
| `calmar` | Total return / max drawdown |
| `avg_duration_mins` | Average trade hold time |
