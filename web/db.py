"""
SQLite persistence layer for benchmark records.
"""
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
DEFAULT_DB_PATH = ROOT / "results" / "benchmark.db"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS benchmark (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL UNIQUE,
    strategy          TEXT NOT NULL,
    tag               TEXT DEFAULT '',
    timerange         TEXT DEFAULT '',
    pairs             TEXT DEFAULT '',
    total_trades      INTEGER DEFAULT 0,
    win_rate          REAL DEFAULT 0,
    profit_factor     REAL DEFAULT 0,
    total_profit_pct  REAL DEFAULT 0,
    max_drawdown      REAL DEFAULT 0,
    avg_duration_mins INTEGER DEFAULT 0,
    sharpe            REAL DEFAULT 0,
    calmar            REAL DEFAULT 0,
    run_at            TEXT DEFAULT ''
);
"""

COLUMNS = [
    "id", "run_id", "strategy", "tag", "timerange", "pairs",
    "total_trades", "win_rate", "profit_factor", "total_profit_pct",
    "max_drawdown", "avg_duration_mins", "sharpe", "calmar", "run_at",
]


class DB:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._connect() as conn:
            conn.execute(CREATE_TABLE_SQL)
            conn.commit()

    def upsert_benchmark(self, **kwargs) -> None:
        fields = [k for k in kwargs if k in COLUMNS[1:]]  # skip id
        placeholders = ", ".join(["?"] * len(fields))
        cols = ", ".join(fields)
        updates = ", ".join(f"{f}=excluded.{f}" for f in fields if f != "run_id")
        sql = (
            f"INSERT INTO benchmark ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(run_id) DO UPDATE SET {updates}"
        )
        values = [kwargs[f] for f in fields]
        with self._connect() as conn:
            conn.execute(sql, values)
            conn.commit()

    def list_benchmarks(
        self,
        strategy: str | None = None,
        tag: str | None = None,
        min_win_rate: float | None = None,
        max_drawdown: float | None = None,
        sort_by: str = "run_at",
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[dict[str, Any]]]:
        allowed_sort = {
            "run_at", "win_rate", "profit_factor", "total_profit_pct",
            "max_drawdown", "sharpe", "calmar", "total_trades", "strategy",
        }
        if sort_by not in allowed_sort:
            sort_by = "run_at"
        order = "DESC" if order.lower() == "desc" else "ASC"

        conditions = []
        params: list[Any] = []

        if strategy:
            conditions.append("strategy LIKE ?")
            params.append(f"%{strategy}%")
        if tag:
            conditions.append("tag = ?")
            params.append(tag)
        if min_win_rate is not None:
            conditions.append("win_rate >= ?")
            params.append(min_win_rate)
        if max_drawdown is not None:
            conditions.append("max_drawdown >= ?")
            params.append(max_drawdown)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with self._connect() as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) FROM benchmark {where}", params
            ).fetchone()
            total = count_row[0]

            rows = conn.execute(
                f"SELECT * FROM benchmark {where} ORDER BY {sort_by} {order} "
                f"LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

        return total, [dict(r) for r in rows]

    def get_benchmark(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM benchmark WHERE run_id = ?", [run_id]
            ).fetchone()
        return dict(row) if row else None

    def delete_benchmark(self, run_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM benchmark WHERE run_id = ?", [run_id]
            )
            conn.commit()
        return cursor.rowcount > 0

    def import_from_csv(self, csv_path: Path) -> int:
        import pandas as pd
        if not csv_path.exists():
            return 0
        df = pd.read_csv(csv_path).fillna("")
        count = 0
        for _, row in df.iterrows():
            try:
                self.upsert_benchmark(**{
                    k: row[k] for k in COLUMNS[1:] if k in df.columns
                })
                count += 1
            except Exception:
                pass
        return count
