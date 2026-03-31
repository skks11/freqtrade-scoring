"""
StrategyB - swing trading with wider targets and larger TP ratios.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.CsvSignalStrategy import CsvSignalStrategy


class StrategyB(CsvSignalStrategy):
    strategy_name = "StrategyB"

    stoploss = -0.07
    trailing_stop = False
    minimal_roi = {"0": 0.15, "120": 0.05, "360": 0.02}
    timeframe = "4h"
