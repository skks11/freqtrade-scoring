"""
End-to-end demo: generate mock signals → run backtests → start web dashboard.

Usage:
    python demo.py
"""
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

PORT = 8080
HOST = "127.0.0.1"
URL  = f"http://{HOST}:{PORT}"


def check_deps():
    missing = []
    for pkg in ("fastapi", "uvicorn", "pandas", "numpy"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[demo] Missing packages: {', '.join(missing)}")
        print(f"[demo] Run: pip install {' '.join(missing)}")
        sys.exit(1)


def step(msg: str):
    print(f"\n{'─'*60}")
    print(f"  {msg}")
    print(f"{'─'*60}")


def main():
    check_deps()

    # ── Step 1: Generate mock signal data ─────────────────────────────────────
    step("Step 1/3 · Generating mock signal data")
    from scripts.generate_mock_data import generate_all
    files = generate_all(start_date="20230101", end_date="20240101")
    print(f"\n  {len(files)} signal files generated under signals/")

    # ── Step 2: Run mock backtests ────────────────────────────────────────────
    step("Step 2/3 · Running mock backtests")
    from scripts.run_backtest import run_backtest

    runs = [
        # (strategy, timerange, tag, pairs)
        ("StrategyA", "20230101-20231231", "baseline",    None),
        ("StrategyA", "20230101-20231231", "q1_only",     None),
        ("StrategyA", "20230601-20231231", "h2_test",     ["BTC/USDT"]),
        ("StrategyB", "20230101-20231231", "baseline",    None),
        ("StrategyB", "20230101-20231231", "btc_only",    ["BTC/USDT"]),
    ]

    report_dirs = []
    for strategy, timerange, tag, pairs in runs:
        print(f"\n  → {strategy} [{timerange}] tag={tag!r} pairs={pairs or 'all'}")
        result = run_backtest(
            strategy=strategy,
            timerange=timerange,
            pairs=pairs,
            mock=True,
            tag=tag,
        )
        if result:
            report_dirs.append(result["result_dir"])
            print(f"     trades={result.get('total_trades',0):>4}  "
                  f"wr={result.get('win_rate',0):.1%}  "
                  f"profit={result.get('total_profit_pct',0):+.1%}  "
                  f"sharpe={result.get('sharpe',0):.2f}")

    # ── Step 3: Launch web dashboard ──────────────────────────────────────────
    step("Step 3/3 · Launching web dashboard")
    print(f"\n  Starting server on {URL} ...")

    # Launch uvicorn as a subprocess so we can print the summary first
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web.app:app",
         "--host", HOST, "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT),
    )

    time.sleep(1.5)  # Wait for server to bind

    if proc.poll() is not None:
        print("  [ERROR] Server failed to start.")
        sys.exit(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "═"*60)
    print("  DEMO READY")
    print("═"*60)
    print(f"\n  🌐  Web Dashboard   →  {URL}")
    print(f"\n  📂  Backtest Reports:")
    for d in report_dirs:
        rel = Path(d).relative_to(ROOT)
        print(f"       {rel}/")
        print(f"         ├── backtest_results.json")
        print(f"         ├── trades.csv")
        print(f"         └── config_merged.json")
    print(f"\n  📊  Benchmark CSV   →  results/benchmark.csv")
    print(f"  🗄️   Benchmark DB    →  results/benchmark.db")
    print("\n  Press Ctrl+C to stop the server.\n")

    try:
        webbrowser.open(URL)
    except Exception:
        pass

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
