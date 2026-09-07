"""
Guarda cada operación y cada snapshot de equity en SQLite. No es solo un
log: es la fuente de datos que algún día leerá el backend de la app de
iPhone para pintar la gráfica de evolución y el histórico de compra/venta.

En Railway, DB_PATH debe apuntar a un Volume montado (si no, se pierde
el histórico en cada redeploy).
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import config


@contextmanager
def _conn():
    conn = sqlite3.connect(config.db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                price REAL NOT NULL,
                mode TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                equity REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS optimizer_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                old_params TEXT,
                new_params TEXT,
                profit_factor REAL
            )
        """)


def record_trade(symbol: str, side: str, qty: float, price: float, mode: str):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO trades (timestamp, symbol, side, qty, price, mode) VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), symbol, side, qty, price, mode),
        )


def record_equity(equity: float):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO equity_snapshots (timestamp, equity) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), equity),
        )


def record_optimizer_run(old_params: str, new_params: str, profit_factor: float):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO optimizer_runs (timestamp, old_params, new_params, profit_factor) VALUES (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), old_params, new_params, profit_factor),
        )
