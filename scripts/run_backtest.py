"""
Backtest runner: supports real freqtrade mode and --mock mode for testing.

Usage (mock):
    python scripts/run_backtest.py --strategy StrategyA --timerange 20230101-20231231 --mock

Usage (real freqtrade):
    python scripts/run_backtest.py --strategy StrategyA --timerange 20230101-20231231
"""
import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.config_manager import get_tp_config, load_config, write_temp_config
from scripts.mock_engine import run_mock_backtest
from web.db import DB

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

RESULTS_DIR = ROOT / "results"


def _make_run_id(strategy_name: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:22]  # include microseconds
    return f"{strategy_name}_{ts}"


def _save_results(run_id: str, stats: dict, config: dict) -> Path:
    result_dir = RESULTS_DIR / run_id
    result_dir.mkdir(parents=True, exist_ok=True)

    # Save merged config
    config_out = {k: v for k, v in config.items()}  # shallow copy
    with open(result_dir / "config_merged.json", "w", encoding="utf-8") as f:
        json.dump(config_out, f, indent=2)

    # Save trades CSV
    trades = stats.pop("trades", [])
    if trades:
        import pandas as pd
        pd.DataFrame(trades).to_csv(result_dir / "trades.csv", index=False)

    # Save backtest summary
    with open(result_dir / "backtest_results.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    return result_dir


def _update_benchmark_csv(run_id: str, stats: dict, tag: str) -> None:
    import pandas as pd
    benchmark_path = RESULTS_DIR / "benchmark.csv"

    row = {
        "run_id": run_id,
        "strategy": stats.get("strategy", ""),
        "tag": tag,
        "timerange": stats.get("timerange", ""),
        "pairs": stats.get("pairs", ""),
        "total_trades": stats.get("total_trades", 0),
        "win_rate": stats.get("win_rate", 0),
        "profit_factor": stats.get("profit_factor", 0),
        "total_profit_pct": stats.get("total_profit_pct", 0),
        "max_drawdown": stats.get("max_drawdown", 0),
        "avg_duration_mins": stats.get("avg_duration_mins", 0),
        "sharpe": stats.get("sharpe", 0),
        "calmar": stats.get("calmar", 0),
        "run_at": datetime.now(timezone.utc).isoformat(),
    }

    if benchmark_path.exists():
        df = pd.read_csv(benchmark_path)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])

    df.to_csv(benchmark_path, index=False)


def _update_db(run_id: str, stats: dict, tag: str) -> None:
    db = DB(ROOT / "results" / "benchmark.db")
    db.upsert_benchmark(
        run_id=run_id,
        strategy=stats.get("strategy", ""),
        tag=tag,
        timerange=stats.get("timerange", ""),
        pairs=stats.get("pairs", ""),
        total_trades=stats.get("total_trades", 0),
        win_rate=stats.get("win_rate", 0),
        profit_factor=stats.get("profit_factor", 0),
        total_profit_pct=stats.get("total_profit_pct", 0),
        max_drawdown=stats.get("max_drawdown", 0),
        avg_duration_mins=stats.get("avg_duration_mins", 0),
        sharpe=stats.get("sharpe", 0),
        calmar=stats.get("calmar", 0),
        run_at=datetime.now(timezone.utc).isoformat(),
    )


def run_backtest(
    strategy: str,
    timerange: str,
    pairs: list[str] | None = None,
    mock: bool = False,
    tag: str = "",
    config_path: Path | None = None,
) -> dict:
    config = load_config(strategy)
    config["tp_config"] = get_tp_config(config)
    # Inject strategy_name so CsvSignalStrategy can locate signals without a subclass file
    config["strategy_name"] = strategy

    run_id = _make_run_id(strategy)
    log.info("Starting backtest run_id=%s strategy=%s timerange=%s mock=%s",
             run_id, strategy, timerange, mock)

    if mock:
        stats = run_mock_backtest(strategy, config, timerange, pairs)
    else:
        stats = _run_freqtrade(strategy, config, timerange, pairs)

    if not stats:
        log.error("Backtest produced no results.")
        return {}

    result_dir = _save_results(run_id, dict(stats), config)
    log.info("Results saved to %s", result_dir)

    try:
        _update_benchmark_csv(run_id, dict(stats), tag)
        _update_db(run_id, dict(stats), tag)
        log.info("Benchmark updated (CSV + DB)")
    except Exception as exc:
        log.warning("Failed to update benchmark: %s", exc)

    return {"run_id": run_id, "result_dir": str(result_dir), **stats}


def _run_freqtrade(strategy: str, config: dict, timerange: str,
                   pairs: list[str] | None) -> dict:
    """Run actual freqtrade backtesting. Requires freqtrade to be installed."""
    tmp_config = write_temp_config(config)
    try:
        cmd = [
            "freqtrade", "backtesting",
            "--config", str(tmp_config),
            "--strategy", "CsvSignalStrategy",  # single class handles all strategies via config
            "--timerange", timerange,
            "--export", "trades",
        ]
        if pairs:
            cmd += ["--pairs"] + pairs

        log.info("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        if result.returncode != 0:
            log.error("freqtrade failed:\n%s", result.stderr)
            raise RuntimeError(f"freqtrade backtesting failed (rc={result.returncode})")
        return _parse_freqtrade_output(result.stdout)
    finally:
        tmp_config.unlink(missing_ok=True)


def _parse_freqtrade_output(stdout: str) -> dict:
    """Minimal parser for freqtrade backtest output — extend as needed."""
    log.warning("Real freqtrade output parsing is a stub. Returning empty dict.")
    return {}


def main():
    parser = argparse.ArgumentParser(description="Run freqtrade backtest")
    parser.add_argument("--strategy", required=True, help="Strategy class name")
    parser.add_argument("--timerange", required=True, help="YYYYMMDD-YYYYMMDD")
    parser.add_argument("--pairs", nargs="+", help="Pairs to backtest")
    parser.add_argument("--tag", default="", help="Optional label for this run")
    parser.add_argument("--mock", action="store_true", help="Use mock engine (no freqtrade needed)")
    parser.add_argument("--config", default=None, help="Override base config path")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    result = run_backtest(
        strategy=args.strategy,
        timerange=args.timerange,
        pairs=args.pairs,
        mock=args.mock,
        tag=args.tag,
    )
    if result:
        print(f"\nBacktest complete!")
        print(f"  run_id      : {result['run_id']}")
        print(f"  result_dir  : {result['result_dir']}")
        print(f"  total_trades: {result.get('total_trades', 0)}")
        print(f"  win_rate    : {result.get('win_rate', 0):.2%}")
        print(f"  total_profit: {result.get('total_profit_pct', 0):.2%}")
        print(f"  max_drawdown: {result.get('max_drawdown', 0):.2%}")
        print(f"  sharpe      : {result.get('sharpe', 0):.3f}")


if __name__ == "__main__":
    main()
