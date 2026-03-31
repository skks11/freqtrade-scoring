"""
Generates mock signal CSV files for StrategyA and StrategyB to support testing
without a live data feed or freqtrade installation.

Signals are synthetic but follow realistic patterns:
- Entry signals cluster (not every candle)
- Exits come after realistic hold durations (2h–96h)
- entry_tag and exit_tag are varied to exercise TP/SL logic
"""
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
SIGNALS_DIR = ROOT / "signals"

# Fixed seed for reproducibility
random.seed(0)

ENTRY_TAGS_A = ["breakout_long", "momentum_long", "trend_follow", "mean_revert"]
EXIT_TAGS_A = ["tp1_hit", "tp2_hit", "tp3_hit", "sl_hit", "manual_exit", "trailing_stop"]

ENTRY_TAGS_B = ["swing_long", "news_impulse", "liquidity_grab"]
EXIT_TAGS_B = ["tp1_hit", "tp2_hit", "tp3_hit", "sl_hit", "reversal_signal", "timeout_exit"]


def _generate_signals(
    pair: str,
    start: datetime,
    end: datetime,
    timeframe_h: int,
    entry_tags: list[str],
    exit_tags: list[str],
    avg_trades_per_week: float = 3.0,
) -> pd.DataFrame:
    """Generate a realistic signal sequence for one pair."""
    rows = []
    current = start
    candle_delta = timedelta(hours=timeframe_h)

    in_trade = False
    entry_time = None
    min_hold_h = max(timeframe_h, 2)

    while current < end:
        ts_ms = int(current.timestamp() * 1000)

        if not in_trade:
            # Probability of entry each candle (Poisson-like)
            candles_per_week = 7 * 24 / timeframe_h
            p_entry = avg_trades_per_week / candles_per_week
            if random.random() < p_entry:
                rows.append({
                    "timestamp": ts_ms,
                    "pair": pair,
                    "signal": 1,
                    "entry_tag": random.choice(entry_tags),
                    "exit_tag": "",
                })
                in_trade = True
                entry_time = current
            else:
                rows.append({"timestamp": ts_ms, "pair": pair, "signal": 0,
                              "entry_tag": "", "exit_tag": ""})
        else:
            hold_so_far = (current - entry_time).total_seconds() / 3600
            # Exit probability increases with hold time; min hold = min_hold_h
            if hold_so_far < min_hold_h:
                p_exit = 0.0
            else:
                # Sigmoid-like: ramps up from min_hold to ~72h
                p_exit = min(0.35, (hold_so_far - min_hold_h) / 80.0 + 0.05)

            if random.random() < p_exit:
                rows.append({
                    "timestamp": ts_ms,
                    "pair": pair,
                    "signal": -1,
                    "entry_tag": "",
                    "exit_tag": random.choice(exit_tags),
                })
                in_trade = False
            else:
                rows.append({"timestamp": ts_ms, "pair": pair, "signal": 0,
                              "entry_tag": "", "exit_tag": ""})

        current += candle_delta

    # Close any open trade at end
    if in_trade and rows:
        rows[-1]["signal"] = -1
        rows[-1]["exit_tag"] = "end_of_period"

    return pd.DataFrame(rows)


def generate_all(start_date: str = "20230101", end_date: str = "20240101"):
    start = datetime.strptime(start_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(end_date, "%Y%m%d").replace(tzinfo=timezone.utc)

    strategies = {
        "StrategyA": {
            "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
            "timeframe_h": 1,
            "entry_tags": ENTRY_TAGS_A,
            "exit_tags": EXIT_TAGS_A,
            "avg_trades_per_week": 4,
        },
        "StrategyB": {
            "pairs": ["BTC/USDT", "ETH/USDT"],
            "timeframe_h": 4,
            "entry_tags": ENTRY_TAGS_B,
            "exit_tags": EXIT_TAGS_B,
            "avg_trades_per_week": 2,
        },
    }

    generated = []
    for strategy_name, cfg in strategies.items():
        out_dir = SIGNALS_DIR / strategy_name
        out_dir.mkdir(parents=True, exist_ok=True)

        for pair in cfg["pairs"]:
            pair_file = pair.replace("/", "_")
            timeframe_str = f"{cfg['timeframe_h']}h"
            csv_path = out_dir / f"{pair_file}_{timeframe_str}.csv"

            df = _generate_signals(
                pair=pair,
                start=start,
                end=end,
                timeframe_h=cfg["timeframe_h"],
                entry_tags=cfg["entry_tags"],
                exit_tags=cfg["exit_tags"],
                avg_trades_per_week=cfg["avg_trades_per_week"],
            )
            df.to_csv(csv_path, index=False)
            n_trades = (df["signal"] == 1).sum()
            print(f"  Generated {csv_path.relative_to(ROOT)}  ({n_trades} entry signals)")
            generated.append(csv_path)

    return generated


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default="20240101")
    args = parser.parse_args()

    print(f"Generating mock signals {args.start} → {args.end} ...")
    files = generate_all(args.start, args.end)
    print(f"Done. {len(files)} signal files created.")
