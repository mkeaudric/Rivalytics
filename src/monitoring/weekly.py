"""
weekly.py — Weekly intelligence report.

Cek apakah ada update data baru untuk monitored companies.
Ini CHEAP (cuma cek metadata), tapi user harus konfirmasi sebelum
ingest detail (yang mahal).

Flow:
1. check_updates() → cek metadata (cheap)
2. User review hasil
3. ingest_selected() → fetch detail (expensive) — dipanggil dari UI
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import get_conn


def _parse_date_to_quarter(report_date: str) -> str:
    """'2026-06-30' → 'Q2-2026'"""
    y = int(report_date[:4])
    m = int(report_date[5:7])
    q = (m - 1) // 3 + 1
    return f"Q{q}-{y}"


def get_monitored_symbols(org_id=None):
    """Ambil semua symbol yang dimonitor (dari relationships)."""
    conn = get_conn()
    try:
        if org_id:
            rows = conn.execute("""
                SELECT DISTINCT company_symbol FROM relationships
                WHERE organization_id = ?
                ORDER BY company_symbol
            """, [org_id]).fetchall()
        else:
            rows = conn.execute("""
                SELECT DISTINCT company_symbol FROM relationships
                ORDER BY company_symbol
            """).fetchall()
        return [r["company_symbol"] for r in rows]
    finally:
        conn.close()


def get_latest_in_db(symbol: str):
    """Kuartal terbaru yang udah ada di DB."""
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT period_label FROM financial_snapshots
            WHERE symbol = ?
            ORDER BY report_date DESC LIMIT 1
        """, [symbol]).fetchone()
        return row["period_label"] if row else None
    finally:
        conn.close()


def last_check_time():
    """Kapan terakhir cek mingguan."""
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT MAX(last_check_at) as last FROM ingest_tracker
        """).fetchone()
        return row["last"] if row and row["last"] else None
    finally:
        conn.close()


def should_check_now(days: int = 7) -> bool:
    """Apakah udah waktunya cek (default: 7 hari)."""
    last = last_check_time()
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return datetime.now() - last_dt >= timedelta(days=days)
    except Exception:
        return True


def check_updates(org_id=None, symbols=None) -> list:
    """
    Cek kalau ada data baru untuk monitored companies.
    
    Ini CHEAP — cuma panggil endpoint metadata, bukan financials detail.
    
    Return: list of {
        symbol, latest_in_db, latest_available, has_update, error?
    }
    """
    from core.sectors_client import SectorsClient

    if symbols is None:
        symbols = get_monitored_symbols(org_id)

    if not symbols:
        return []

    try:
        client = SectorsClient()
    except Exception as e:
        return [{"symbol": "ALL", "error": str(e), "has_update": False}]

    results = []

    for sym in symbols:
        try:
            latest_db = get_latest_in_db(sym)

            # Endpoint cheap: cuma daftar tanggal
            dates = client._get(f"/company/get_quarterly_financial_dates/{sym}/")

            all_dates = []
            for year, rows in dates.items():
                for report_date, quarter in rows:
                    all_dates.append(report_date)

            if all_dates:
                latest_api_date = sorted(all_dates, reverse=True)[0]
                latest_api = _parse_date_to_quarter(latest_api_date)
            else:
                latest_api = None

            has_update = (
                latest_api is not None
                and (latest_db is None or latest_api != latest_db)
            )

            results.append({
                "symbol": sym,
                "latest_in_db": latest_db or "-",
                "latest_available": latest_api or "-",
                "has_update": has_update,
                "error": None,
            })

        except Exception as e:
            results.append({
                "symbol": sym,
                "latest_in_db": get_latest_in_db(sym) or "-",
                "latest_available": "?",
                "has_update": False,
                "error": str(e),
            })

    # Update last_check_at
    now = datetime.now().isoformat()
    conn = get_conn()
    try:
        for r in results:
            if r.get("error"):
                continue
            conn.execute("""
                INSERT INTO ingest_tracker
                (symbol, last_check_at, latest_in_db, latest_available, pending_update)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    last_check_at = excluded.last_check_at,
                    latest_in_db = excluded.latest_in_db,
                    latest_available = excluded.latest_available,
                    pending_update = excluded.pending_update
            """, [
                r["symbol"], now,
                r["latest_in_db"], r["latest_available"],
                1 if r["has_update"] else 0,
            ])
        conn.commit()
    finally:
        conn.close()

    return results


def ingest_selected(symbols: list) -> dict:
    """
    Ingest yang dipilih user (EXPENSIVE — 2 credits per symbol).
    
    Return: {success: [...], failed: [...], total_credits_used: int}
    """
    from monitoring.ingest import Ingestor

    if not symbols:
        return {"success": [], "failed": [], "total_credits_used": 0}

    ing = Ingestor()
    success = []
    failed = []

    for sym in symbols:
        try:
            result = ing.ingest_smart(sym)
            success.append({"symbol": sym, "result": result})
        except Exception as e:
            failed.append({"symbol": sym, "error": str(e)})

    # Update tracker: catat last_ingest_at
    now = datetime.now().isoformat()
    conn = get_conn()
    try:
        for item in success:
            sym = item["symbol"]
            latest = get_latest_in_db(sym)
            conn.execute("""
                INSERT INTO ingest_tracker
                (symbol, last_ingest_at, latest_in_db, pending_update)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(symbol) DO UPDATE SET
                    last_ingest_at = excluded.last_ingest_at,
                    latest_in_db = excluded.latest_in_db,
                    pending_update = 0
            """, [sym, now, latest])
        conn.commit()
    finally:
        conn.close()

    return {
        "success": success,
        "failed": failed,
        "total_credits_used": len(success) * 2,
    }


def get_pending_summary(org_id=None) -> dict:
    """Ringkasan status pending update."""
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(pending_update) as pending
            FROM ingest_tracker
        """).fetchone()

        return {
            "total_monitored": row["total"] or 0,
            "pending_updates": row["pending"] or 0,
            "last_check": last_check_time(),
            "should_check": should_check_now(),
        }
    finally:
        conn.close()