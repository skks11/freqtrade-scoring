"""
StrategyA - breakout + momentum signals with trailing stop and 3-level TP.
Inherits all CSV-driven logic from CsvSignalStrategy.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.CsvSignalStrategy import CsvSignalStrategy

try:
    import pandas as pd
    from freqtrade.persistence import Trade
except ImportError:
    pass


class StrategyA(CsvSignalStrategy):
    strategy_name = "StrategyA"

    # These are used by freqtrade when real backtesting; mock engine reads from config.
    stoploss = -0.03
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True
    minimal_roi = {"0": 0.06, "60": 0.03, "120": 0.01}
    timeframe = "1h"

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        # Parent handles TP levels and CSV exit tags
        result = super().custom_exit(pair, trade, current_time, current_rate,
                                     current_profit, **kwargs)
        if result:
            return result

        # StrategyA-specific: force exit after 72h if in loss
        if hasattr(trade, "open_date_utc"):
            hours_held = (current_time - trade.open_date_utc).total_seconds() / 3600
            if current_profit < -0.015 and hours_held > 72:
                return "timeout_loss_exit"

        return None
