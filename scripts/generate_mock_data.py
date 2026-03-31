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

# Signal convention:
#   1  = enter long      -1  = exit long
#   2  = enter short     -2  = exit short
#   0  = no action

ENTRY_TAGS_A = ["breakout_long", "momentum_long", "trend_follow", "mean_revert"]
EXIT_TAGS_A = ["tp1_hit", "tp2_hit", "tp3_hit", "sl_hit", "manual_exit", "trailing_stop"]

ENTRY_TAGS_B = ["swing_long", "news_impulse", "liquidity_grab"]
EXIT_TAGS_B = ["tp1_hit", "tp2_hit", "tp3_hit", "sl_hit", "reversal_signal", "timeout_exit"]

ENTRY_TAGS_C_LONG  = ["breakout_long", "oversold_bounce", "support_hold"]
ENTRY_TAGS_C_SHORT = ["breakout_short", "overbought_fade", "resistance_reject"]
EXIT_TAGS_C = ["tp1_hit", "tp2_hit", "tp3_hit", "sl_hit", "reversal_exit"]


def _generate_signals(
    pair: str,
    start: datetime,
    end: datetime,
    timeframe_h: int,
    entry_tags: list[str],
    exit_tags: list[str],
    avg_trades_per_week: float = 3.0,
    allow_short: bool = False,
    short_ratio: float = 0.4,
) -> pd.DataFrame:
    """
    Generate a realistic signal sequence for one pair.

    If allow_short=True, roughly short_ratio fraction of entries will be short
    trades (signal=2 / signal=-2); the rest are longs (signal=1 / signal=-1).
    Long and short positions are never open simultaneously.
    """
    rows = []
    current = start
    candle_delta = timedelta(hours=timeframe_h)

    long_entry_time: datetime | None = None
    short_entry_time: datetime | None = None
    min_hold_h = max(timeframe_h, 2)

    short_entry_tags = ENTRY_TAGS_C_SHORT if allow_short else []

    while current < end:
        ts_ms = int(current.timestamp() * 1000)
        in_long  = long_entry_time is not None
        in_short = short_entry_time is not None

        if not in_long and not in_short:
            candles_per_week = 7 * 24 / timeframe_h
            p_entry = avg_trades_per_week / candles_per_week
            if random.random() < p_entry:
                go_short = allow_short and random.random() < short_ratio
                if go_short:
                    rows.append({
                        "timestamp": ts_ms, "pair": pair, "signal": 2,
                        "entry_tag": random.choice(short_entry_tags), "exit_tag": "",
                    })
                    short_entry_time = current
                else:
                    rows.append({
                        "timestamp": ts_ms, "pair": pair, "signal": 1,
                        "entry_tag": random.choice(entry_tags), "exit_tag": "",
                    })
                    long_entry_time = current
            else:
                rows.append({"timestamp": ts_ms, "pair": pair, "signal": 0,
                              "entry_tag": "", "exit_tag": ""})

        elif in_long:
            hold_h = (current - long_entry_time).total_seconds() / 3600
            p_exit = 0.0 if hold_h < min_hold_h else min(0.35, (hold_h - min_hold_h) / 80.0 + 0.05)
            if random.random() < p_exit:
                rows.append({
                    "timestamp": ts_ms, "pair": pair, "signal": -1,
                    "entry_tag": "", "exit_tag": random.choice(exit_tags),
                })
                long_entry_time = None
            else:
                rows.append({"timestamp": ts_ms, "pair": pair, "signal": 0,
                              "entry_tag": "", "exit_tag": ""})

        else:  # in_short
            hold_h = (current - short_entry_time).total_seconds() / 3600
            p_exit = 0.0 if hold_h < min_hold_h else min(0.35, (hold_h - min_hold_h) / 80.0 + 0.05)
            if random.random() < p_exit:
                rows.append({
                    "timestamp": ts_ms, "pair": pair, "signal": -2,
                    "entry_tag": "", "exit_tag": random.choice(exit_tags),
                })
                short_entry_time = None
            else:
                rows.append({"timestamp": ts_ms, "pair": pair, "signal": 0,
                              "entry_tag": "", "exit_tag": ""})

        current += candle_delta

    # Close any open position at end
    if long_entry_time is not None and rows:
        rows[-1]["signal"] = -1
        rows[-1]["exit_tag"] = "end_of_period"
    elif short_entry_time is not None and rows:
        rows[-1]["signal"] = -2
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
            "allow_short": False,
        },
        "StrategyB": {
            "pairs": ["BTC/USDT", "ETH/USDT"],
            "timeframe_h": 4,
            "entry_tags": ENTRY_TAGS_B,
            "exit_tags": EXIT_TAGS_B,
            "avg_trades_per_week": 2,
            "allow_short": False,
        },
        "StrategyC": {
            "pairs": ["BTC/USDT", "ETH/USDT"],
            "timeframe_h": 1,
            "entry_tags": ENTRY_TAGS_C_LONG,
            "exit_tags": EXIT_TAGS_C,
            "avg_trades_per_week": 5,
            "allow_short": True,
            "short_ratio": 0.4,
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
                allow_short=cfg.get("allow_short", False),
                short_ratio=cfg.get("short_ratio", 0.4),
            )
            df.to_csv(csv_path, index=False)
            n_long  = (df["signal"] == 1).sum()
            n_short = (df["signal"] == 2).sum()
            short_note = f", {n_short} short" if n_short > 0 else ""
            print(f"  Generated {csv_path.relative_to(ROOT)}  ({n_long} long{short_note})")
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
