"""
Mock backtest engine: simulates trade outcomes from CSV signals without requiring
a live freqtrade installation. Produces realistic statistics for testing the pipeline.
"""
import random
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
SIGNALS_DIR = ROOT / "signals"


"""
Signal convention:
    1  = enter long
   -1  = exit long  (close long position)
    2  = enter short
   -2  = exit short (close short position)
    0  = no action
"""


def _load_signals(strategy_name: str, pair: str, timeframe: str) -> pd.DataFrame:
    pair_file = pair.replace("/", "_")
    path = SIGNALS_DIR / strategy_name / f"{pair_file}_{timeframe}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Signal file not found: {path}")
    df = pd.read_csv(path)
    required = {"timestamp", "pair", "signal"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Signal CSV missing columns: {missing} in {path}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("entry_tag", "exit_tag"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("")
    return df


def _simulate_trade_profit(exit_tag: str, sl_pct: float, tp_config: dict) -> float:
    """Generate a realistic profit percentage for a single trade."""
    tag = (exit_tag or "").lower()
    levels = tp_config.get("levels", [])

    if "tp3" in tag and len(levels) >= 3:
        return random.uniform(levels[2]["target"] * 0.9, levels[2]["target"] * 1.4)
    if "tp2" in tag and len(levels) >= 2:
        return random.uniform(levels[1]["target"] * 0.9, levels[1]["target"] * 1.3)
    if "tp1" in tag and len(levels) >= 1:
        return random.uniform(levels[0]["target"] * 0.8, levels[0]["target"] * 1.2)
    if "sl" in tag or "stop" in tag:
        return sl_pct * random.uniform(0.7, 1.05)

    # Generic: ~58% win rate
    if random.random() < 0.58:
        mu = (levels[0]["target"] if levels else 0.015)
        profit = random.gauss(mu, mu * 0.8)
        return max(0.001, profit)
    else:
        loss = random.gauss(sl_pct * 0.65, abs(sl_pct) * 0.25)
        return min(-0.001, loss)


def _build_trade(entry_row: pd.Series, exit_row: pd.Series, sl_pct: float,
                 tp_config: dict, pair: str, side: str = "long") -> dict[str, Any]:
    entry_ts = entry_row["timestamp"]
    exit_ts = exit_row["timestamp"]
    if exit_ts <= entry_ts:
        # Safety: ensure positive duration
        exit_ts = entry_ts + pd.Timedelta(hours=random.randint(1, 48))

    duration_mins = int((exit_ts - entry_ts).total_seconds() / 60)
    profit_pct = _simulate_trade_profit(exit_row["exit_tag"], sl_pct, tp_config)

    # Apply TP scaling: if TP enabled, partial exits lower average profit slightly
    if tp_config.get("enabled") and profit_pct > 0:
        # Weighted average across TP levels vs remaining position
        profit_pct *= random.uniform(0.75, 1.0)

    # For shorts, price moving down is profit — invert sign to reflect that
    if side == "short":
        profit_pct = -profit_pct  # raw sim gives long-style profit; flip for short

    return {
        "pair": pair,
        "side": side,
        "entry_time": entry_ts.isoformat(),
        "exit_time": exit_ts.isoformat(),
        "duration_mins": duration_mins,
        "profit_pct": round(profit_pct, 6),
        "entry_tag": str(entry_row["entry_tag"]),
        "exit_tag": str(exit_row["exit_tag"]),
        "is_win": profit_pct > 0,
    }


def _compute_stats(trades: list[dict], strategy_name: str, timerange: str,
                   pairs: list[str]) -> dict[str, Any]:
    if not trades:
        return {}

    profits = np.array([t["profit_pct"] for t in trades])
    wins = profits[profits > 0]
    losses = profits[profits <= 0]

    win_rate = float(len(wins) / len(profits))
    profit_factor = (float(wins.sum() / abs(losses.sum()))
                     if len(losses) > 0 and losses.sum() != 0 else 999.0)
    total_profit_pct = float(profits.sum())

    # Sharpe (simplified daily)
    std = float(profits.std()) if len(profits) > 1 else 0.0
    sharpe = float(profits.mean() / std * np.sqrt(252)) if std > 0 else 0.0

    # Max drawdown via cumulative equity curve
    cumulative = np.cumsum(profits)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = cumulative - running_max
    max_drawdown = float(drawdowns.min()) if len(drawdowns) > 0 else 0.0

    calmar = (total_profit_pct / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    avg_duration = int(np.mean([t["duration_mins"] for t in trades]))

    return {
        "strategy": strategy_name,
        "timerange": timerange,
        "pairs": ",".join(sorted(set(pairs))),
        "total_trades": len(trades),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "total_profit_pct": round(total_profit_pct, 4),
        "max_drawdown": round(max_drawdown, 4),
        "avg_duration_mins": avg_duration,
        "sharpe": round(sharpe, 4),
        "calmar": round(calmar, 4),
        "trades": trades,
    }


def run_mock_backtest(
    strategy_name: str,
    config: dict,
    timerange: str,
    pairs: list[str] | None = None,
) -> dict[str, Any]:
    """
    Simulate a backtest from CSV signals.

    Args:
        strategy_name: Name of the strategy (matches signals/{strategy_name}/ dir).
        config: Merged config dict.
        timerange: "YYYYMMDD-YYYYMMDD"
        pairs: Optional list of pairs to backtest. Defaults to all CSVs found.

    Returns:
        Dict with aggregate stats and per-trade records.
    """
    random.seed(42)  # Reproducible mock results
    np.random.seed(42)

    sl_pct = config.get("stoploss", -0.05)
    timeframe = config.get("timeframe", "1h")
    tp_config = config.get("tp_config", {"enabled": False, "levels": []})

    start_str, end_str = timerange.split("-")
    start_dt = pd.Timestamp(datetime.strptime(start_str, "%Y%m%d")).tz_localize("UTC")
    end_dt = pd.Timestamp(datetime.strptime(end_str, "%Y%m%d")).tz_localize("UTC")

    strategy_signals_dir = SIGNALS_DIR / strategy_name
    if not strategy_signals_dir.exists():
        raise FileNotFoundError(f"Signals directory not found: {strategy_signals_dir}")

    if pairs is None:
        csv_files = list(strategy_signals_dir.glob(f"*_{timeframe}.csv"))
        pairs = [f.stem.replace(f"_{timeframe}", "").replace("_", "/", 1) for f in csv_files]

    all_trades: list[dict] = []
    used_pairs: list[str] = []

    for pair in pairs:
        try:
            df = _load_signals(strategy_name, pair, timeframe)
        except FileNotFoundError:
            continue

        df = df[(df["timestamp"] >= start_dt) & (df["timestamp"] <= end_dt)].copy()
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Track long and short positions independently
        long_entry: pd.Series | None = None
        short_entry: pd.Series | None = None

        for _, row in df.iterrows():
            sig = int(row["signal"])

            if sig == 1 and long_entry is None:          # enter long
                long_entry = row
            elif sig == -1 and long_entry is not None:    # exit long
                trade = _build_trade(long_entry, row, sl_pct, tp_config, pair, side="long")
                all_trades.append(trade)
                long_entry = None

            elif sig == 2 and short_entry is None:        # enter short
                short_entry = row
            elif sig == -2 and short_entry is not None:   # exit short
                trade = _build_trade(short_entry, row, sl_pct, tp_config, pair, side="short")
                all_trades.append(trade)
                short_entry = None

        used_pairs.append(pair)

    return _compute_stats(all_trades, strategy_name, timerange, used_pairs)
