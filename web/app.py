"""
FastAPI web server for the freqtrade_scoring benchmark dashboard.

Usage:
    python web/app.py [--port 8080] [--db results/benchmark.db]
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from web.db import DB

STATIC_DIR = Path(__file__).parent / "static"

# DB instance — initialised at startup
_db: DB | None = None


def get_db() -> DB:
    global _db
    if _db is None:
        # Lazy init with default path (covers uvicorn --reload and direct imports)
        _db = DB(ROOT / "results" / "benchmark.db")
    return _db


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _db
    if _db is None:
        db_path = ROOT / "results" / "benchmark.db"
        _db = DB(db_path)
        csv_path = ROOT / "results" / "benchmark.csv"
        total, _ = _db.list_benchmarks(limit=1)
        if total == 0 and csv_path.exists():
            n = _db.import_from_csv(csv_path)
            print(f"Auto-imported {n} records from benchmark.csv")
    yield


app = FastAPI(title="freqtrade Benchmark Dashboard", version="1.0.0", lifespan=lifespan)


# ── Static files ──────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/api/benchmarks")
async def list_benchmarks(
    strategy: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    min_win_rate: Optional[float] = Query(None, ge=0, le=1),
    max_drawdown: Optional[float] = Query(None),
    sort_by: str = Query("run_at"),
    order: str = Query("desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    total, items = get_db().list_benchmarks(
        strategy=strategy,
        tag=tag,
        min_win_rate=min_win_rate,
        max_drawdown=max_drawdown,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "items": items}


@app.get("/api/benchmarks/{run_id}")
async def get_benchmark(run_id: str) -> dict[str, Any]:
    row = get_db().get_benchmark(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@app.delete("/api/benchmarks/{run_id}")
async def delete_benchmark(run_id: str) -> dict[str, str]:
    deleted = get_db().delete_benchmark(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": "deleted", "run_id": run_id}


@app.post("/api/benchmarks/import")
async def import_csv() -> dict[str, Any]:
    csv_path = ROOT / "results" / "benchmark.csv"
    count = get_db().import_from_csv(csv_path)
    return {"imported": count, "source": str(csv_path)}


@app.get("/api/trades/{run_id}")
async def get_trades(run_id: str) -> dict[str, Any]:
    """Return per-trade records from the result directory."""
    trades_path = ROOT / "results" / run_id / "trades.csv"
    if not trades_path.exists():
        raise HTTPException(status_code=404, detail="Trades file not found")
    import pandas as pd
    df = pd.read_csv(trades_path)
    return {"run_id": run_id, "trades": df.to_dict(orient="records")}


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Benchmark Dashboard")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db", default=str(ROOT / "results" / "benchmark.db"))
    args = parser.parse_args()

    global _db
    db_path = Path(args.db)
    _db = DB(db_path)

    # Auto-import CSV if DB is empty
    csv_path = ROOT / "results" / "benchmark.csv"
    total, _ = _db.list_benchmarks(limit=1)
    if total == 0 and csv_path.exists():
        n = _db.import_from_csv(csv_path)
        print(f"Auto-imported {n} records from benchmark.csv")

    print(f"\nDashboard running at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
