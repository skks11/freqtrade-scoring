"""
CsvSignalStrategy - base strategy class for freqtrade that drives entry/exit
decisions entirely from external CSV signal files.

Subclass this, set `strategy_name`, and optionally override `custom_exit`.

Signal CSV format:
    timestamp (ms), pair, signal (1/-1/0), entry_tag, exit_tag

Custom exits handled here:
  - Multi-level TP (tp_config in merged config)
  - Arbitrary exit_tag passthrough for subclass overrides
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
SIGNALS_DIR = ROOT / "signals"

try:
    from freqtrade.strategy import IStrategy, IntParameter
    from freqtrade.persistence import Trade
    _FT_AVAILABLE = True
except ImportError:
    # Allow import in non-freqtrade environments (e.g. unit tests)
    _FT_AVAILABLE = False
    IStrategy = object
    Trade = object


class CsvSignalStrategy(IStrategy):  # type: ignore[misc]
    """
    Base strategy: loads signals from CSV, delegates all TP/SL/exit logic
    to config-driven rules and subclass overrides.
    """

    # Signal convention:
    #   1  = enter long      -1  = exit long
    #   2  = enter short     -2  = exit short
    #   0  = no action

    INTERFACE_VERSION = 3
    can_short = True   # required for short signals to work in freqtrade
    use_custom_stoploss = True
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Subclass must set this to match the signals/{strategy_name}/ directory.
    strategy_name: str = "default"

    # TP state per trade: {trade_id: set of level indices already triggered}
    _tp_filled: dict[int, set[int]] = {}

    # Signal cache: {pair_timeframe: DataFrame}
    _signal_cache: dict[str, pd.DataFrame] = {}

    # ── Signal loading ────────────────────────────────────────────────────────

    def _effective_strategy_name(self) -> str:
        """Strategy name from config takes priority over class attribute."""
        return self.config.get("strategy_name", self.strategy_name)

    def _load_signals(self, pair: str) -> pd.DataFrame:
        timeframe = self.config.get("timeframe", "1h")
        cache_key = f"{self._effective_strategy_name()}_{pair}_{timeframe}"
        if cache_key in self._signal_cache:
            return self._signal_cache[cache_key]

        pair_file = pair.replace("/", "_")
        path = SIGNALS_DIR / self._effective_strategy_name() / f"{pair_file}_{timeframe}.csv"
        if not path.exists():
            log.warning("Signal file not found: %s", path)
            df = pd.DataFrame(columns=["timestamp", "pair", "signal", "entry_tag", "exit_tag"])
            self._signal_cache[cache_key] = df
            return df

        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for col in ("entry_tag", "exit_tag"):
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].fillna("")
        self._signal_cache[cache_key] = df
        return df

    def _get_tp_config(self) -> dict:
        default = {
            "enabled": False,
            "levels": [
                {"ratio": 0.33, "target": 0.01},
                {"ratio": 0.33, "target": 0.02},
                {"ratio": 0.34, "target": 0.03},
            ],
        }
        tp = self.config.get("tp_config", {})
        if not tp:
            return default
        merged = dict(default)
        merged.update(tp)
        return merged

    def _get_csv_exit_tag(self, pair: str, current_time: pd.Timestamp) -> str:
        signals = self._load_signals(pair)  # uses _effective_strategy_name internally
        if signals.empty:
            return ""
        row = signals[signals["timestamp"] == current_time]
        if row.empty:
            return ""
        return str(row.iloc[0].get("exit_tag", ""))

    # ── freqtrade hooks ───────────────────────────────────────────────────────

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata["pair"]
        signals = self._load_signals(pair)

        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""

        if signals.empty:
            return dataframe

        long_map  = signals[signals["signal"] == 1].set_index("timestamp")
        short_map = signals[signals["signal"] == 2].set_index("timestamp")

        for idx, row in dataframe.iterrows():
            ts = row["date"]
            if ts in long_map.index:
                dataframe.at[idx, "enter_long"] = 1
                dataframe.at[idx, "enter_tag"] = long_map.at[ts, "entry_tag"]
            elif ts in short_map.index:
                dataframe.at[idx, "enter_short"] = 1
                dataframe.at[idx, "enter_tag"] = short_map.at[ts, "entry_tag"]

        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata["pair"]
        signals = self._load_signals(pair)

        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        dataframe["exit_tag"] = ""

        if signals.empty:
            return dataframe

        tp_enabled = self._get_tp_config().get("enabled", False)

        long_exit_map  = signals[signals["signal"] == -1].set_index("timestamp")
        short_exit_map = signals[signals["signal"] == -2].set_index("timestamp")

        for idx, row in dataframe.iterrows():
            ts = row["date"]
            if ts in long_exit_map.index:
                if not tp_enabled:
                    dataframe.at[idx, "exit_long"] = 1
                dataframe.at[idx, "exit_tag"] = long_exit_map.at[ts, "exit_tag"]
            elif ts in short_exit_map.index:
                if not tp_enabled:
                    dataframe.at[idx, "exit_short"] = 1
                dataframe.at[idx, "exit_tag"] = short_exit_map.at[ts, "exit_tag"]

        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade: "Trade",
        current_time: pd.Timestamp,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        tp_cfg = self._get_tp_config()

        # 1. Strategy-specific exit tag from CSV (non-TP)
        exit_tag = self._get_csv_exit_tag(pair, current_time)
        if exit_tag and not any(exit_tag.startswith(p) for p in ("tp1", "tp2", "tp3")):
            return exit_tag

        # 2. Multi-level TP
        if tp_cfg.get("enabled") and hasattr(trade, "id"):
            filled = self._tp_filled.setdefault(trade.id, set())
            levels = tp_cfg.get("levels", [])
            for i, level in enumerate(levels):
                if i not in filled and current_profit >= level["target"]:
                    filled.add(i)
                    return f"tp{i+1}"

        return None

    def custom_stoploss(
        self,
        pair: str,
        trade: "Trade",
        current_time: pd.Timestamp,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float:
        # Return the configured stoploss (freqtrade trailing logic handles the rest)
        return self.stoploss

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # No indicators needed — pure signal-driven strategy
        return dataframe
