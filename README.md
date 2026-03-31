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

## Signal CSV Format

Place signal files at `signals/{StrategyName}/{PAIR}_{timeframe}.csv`:

```csv
timestamp,pair,signal,entry_tag,exit_tag
1704067200000,BTC/USDT,1,breakout_long,
1704153600000,BTC/USDT,0,,
1704240000000,BTC/USDT,-1,,tp2_hit
```

| Column | Values | Description |
|--------|--------|-------------|
| `timestamp` | int (ms) | K-line open time |
| `signal` | `1` / `-1` / `0` | Enter / Exit / Hold |
| `entry_tag` | string | Label for entry type |
| `exit_tag` | string | Drives `custom_exit`; `tp1_`/`tp2_`/`tp3_` prefix triggers TP levels |

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
