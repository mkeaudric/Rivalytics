"""
db.py — SQLite schema untuk Rivalytics.

Design decisions:
- Cuma simpan field yang kita pakai untuk signal detection
- Field lain bisa di-fetch on-demand kalau perlu (report detail)
- Parsing date → quarter & year disimpan biar query gampang
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "rivalytics.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    symbol              TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    sector              TEXT,
    sub_sector          TEXT,
    industry            TEXT,
    market_cap          INTEGER,
    market_cap_rank     INTEGER,
    last_close_price    INTEGER,
    updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS financial_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    report_date         TEXT NOT NULL,       -- '2026-06-30'
    quarter             INTEGER NOT NULL,    -- 1..4
    year                INTEGER NOT NULL,    -- 2026
    period_label        TEXT NOT NULL,       -- 'Q2-2026'

    -- Income statement
    revenue             INTEGER,
    cost_of_revenue     INTEGER,
    gross_profit        INTEGER,
    operating_expense   INTEGER,
    operating_pnl       INTEGER,
    ebit                INTEGER,
    ebitda              INTEGER,
    earnings_before_tax INTEGER,
    tax                 INTEGER,
    earnings            INTEGER,             -- net income

    -- Balance sheet
    total_assets        INTEGER,
    total_liabilities   INTEGER,
    total_equity        INTEGER,
    total_debt          INTEGER,
    cash_only           INTEGER,
    current_liabilities INTEGER,

    -- Cash flow
    operating_cash_flow INTEGER,
    investing_cash_flow INTEGER,
    financing_cash_flow INTEGER,
    free_cash_flow      INTEGER,

    fetched_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, report_date),
    FOREIGN KEY (symbol) REFERENCES companies(symbol)
);

CREATE TABLE IF NOT EXISTS signals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    period_label        TEXT NOT NULL,       -- 'Q2-2026' (kapan terjadi)
    signal_type         TEXT NOT NULL,       -- 'revenue_deterioration', dst
    severity            TEXT NOT NULL,       -- 'info' | 'watch' | 'attention'
    metric              TEXT NOT NULL,       -- 'revenue'
    current_value       REAL,
    previous_value      REAL,
    delta_pct           REAL,
    context             TEXT,                -- JSON: {yoy, qoq, sector_avg...}
    detected_at         TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (symbol) REFERENCES companies(symbol)
);

CREATE INDEX IF NOT EXISTS idx_snap_symbol_date
    ON financial_snapshots(symbol, report_date DESC);
CREATE INDEX IF NOT EXISTS idx_signals_symbol
    ON signals(symbol, detected_at DESC);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"[db] initialized: {DB_PATH}")


# ---------- helpers ----------

def upsert_company(conn, symbol, name, overview: dict):
    conn.execute("""
        INSERT INTO companies (symbol, name, sector, sub_sector, industry,
                               market_cap, market_cap_rank, last_close_price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            name = excluded.name,
            sector = excluded.sector,
            sub_sector = excluded.sub_sector,
            industry = excluded.industry,
            market_cap = excluded.market_cap,
            market_cap_rank = excluded.market_cap_rank,
            last_close_price = excluded.last_close_price,
            updated_at = CURRENT_TIMESTAMP
    """, [
        symbol, name,
        overview.get("sector"),
        overview.get("sub_sector"),
        overview.get("industry"),
        overview.get("market_cap"),
        overview.get("market_cap_rank"),
        overview.get("last_close_price"),
    ])


def upsert_snapshot(conn, symbol, q: dict):
    """q = satu item dari list /financials/quarterly/."""
    date_str = q["date"]  # '2026-06-30'
    year = int(date_str[:4])
    month = int(date_str[5:7])
    quarter = (month - 1) // 3 + 1
    period_label = f"Q{quarter}-{year}"

    conn.execute("""
        INSERT INTO financial_snapshots (
            symbol, report_date, quarter, year, period_label,
            revenue, cost_of_revenue, gross_profit, operating_expense,
            operating_pnl, ebit, ebitda, earnings_before_tax, tax, earnings,
            total_assets, total_liabilities, total_equity, total_debt,
            cash_only, current_liabilities,
            operating_cash_flow, investing_cash_flow, financing_cash_flow,
            free_cash_flow
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, report_date) DO UPDATE SET
            revenue = excluded.revenue,
            earnings = excluded.earnings,
            total_assets = excluded.total_assets,
            total_liabilities = excluded.total_liabilities,
            total_equity = excluded.total_equity,
            total_debt = excluded.total_debt,
            operating_cash_flow = excluded.operating_cash_flow,
            free_cash_flow = excluded.free_cash_flow,
            fetched_at = CURRENT_TIMESTAMP
    """, [
        symbol, date_str, quarter, year, period_label,
        q.get("revenue"), q.get("cost_of_revenue"), q.get("gross_profit"),
        q.get("operating_expense"), q.get("operating_pnl"),
        q.get("ebit"), q.get("ebitda"), q.get("earnings_before_tax"),
        q.get("tax"), q.get("earnings"),
        q.get("total_assets"), q.get("total_liabilities"),
        q.get("total_equity"), q.get("total_debt"),
        q.get("cash_only"), q.get("current_liabilities"),
        q.get("operating_cash_flow"), q.get("investing_cash_flow"),
        q.get("financing_cash_flow"), q.get("free_cash_flow"),
    ])


def insert_signal(conn, signal: dict):
    """Idempotent: skip kalau signal dengan symbol+period+type sama sudah ada."""
    existing = conn.execute("""
        SELECT id FROM signals
        WHERE symbol = ? AND period_label = ? AND signal_type = ?
    """, [signal["symbol"], signal["period_label"], signal["signal_type"]]).fetchone()

    if existing:
        return False

    conn.execute("""
        INSERT INTO signals
        (symbol, period_label, signal_type, severity, metric,
         current_value, previous_value, delta_pct, context)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        signal["symbol"], signal["period_label"], signal["signal_type"],
        signal["severity"], signal["metric"],
        signal["current_value"], signal["previous_value"],
        signal["delta_pct"], signal.get("context"),
    ])
    return True


def get_snapshots(conn, symbol, limit=12):
    """Return list snapshot descending by date."""
    rows = conn.execute("""
        SELECT * FROM financial_snapshots
        WHERE symbol = ?
        ORDER BY report_date DESC
        LIMIT ?
    """, [symbol, limit]).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()