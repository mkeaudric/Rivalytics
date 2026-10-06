"""
ingest.py — Fetch data dan simpan ke DB.
Biaya: 2 credits per company (1 report overview, 1 quarterly).
"""
import os
import requests
from typing import Optional

from core.db import get_conn, upsert_company, upsert_snapshot


BASE_URL = "https://api.sectors.app/v2"


def _clean_symbol(s: str) -> str:
    return s.replace(".JK", "").replace(".jk", "").upper()


class Ingestor:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SECTORS_API_KEY")
        if not self.api_key:
            raise ValueError("SECTORS_API_KEY tidak diset")
        self.headers = {"Authorization": self.api_key}

    def _get(self, path, params=None):
        r = requests.get(f"{BASE_URL}{path}", headers=self.headers,
                         params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def fetch_overview(self, symbol: str) -> dict:
        """Return {'symbol': ..., 'company_name': ..., 'overview': {...}}."""
        return self._get(f"/company/report/{symbol}/",
                         params={"sections": "overview"})

    def fetch_quarterly(self, symbol: str, n_quarters: int = 8) -> list:
        """Return list of quarterly snapshots, descending by date."""
        return self._get(f"/financials/quarterly/{symbol}/",
                         params={"n_quarters": n_quarters})

    def ingest_smart(self, symbol: str):
        """
        Incremental ingest:
        - Company baru: fetch 5 kuartal (5 credits)
        - Company lama: cek quarter baru, fetch seperlunya (1-2 credits)
        """
        symbol = _clean_symbol(symbol)
        conn = get_conn()

        try:
            # Cek: sudah punya snapshot?
            existing = conn.execute("""
                SELECT MAX(report_date) as latest FROM financial_snapshots
                WHERE symbol = ?
            """, [symbol]).fetchone()
            latest_in_db = existing["latest"] if existing else None

            if latest_in_db is None:
                # === INITIAL LOAD ===
                print(f"  [{symbol}] initial load (5 kuartal, ~5 credits)")
                report = self.fetch_overview(symbol)
                ov = report.get("overview", {})
                upsert_company(conn, symbol, report.get("company_name", symbol), ov)

                snapshots = self.fetch_quarterly(symbol, n_quarters=5)
                for q in snapshots:
                    upsert_snapshot(conn, symbol, q)
                conn.commit()
                return {"symbol": symbol, "mode": "initial", "n": len(snapshots)}

            else:
                # === INCREMENTAL ===
                # Cek dates yang tersedia di API
                dates = self._get(f"/company/get_quarterly_financial_dates/{symbol}/")
                # dates = {"2026": [["2026-03-31", "q1"], ["2026-06-30", "q2"]], ...}

                # Flatten
                all_dates = []
                for year, rows in dates.items():
                    for report_date, quarter in rows:
                        all_dates.append(report_date)

                # Filter yang belum ada di DB
                existing_dates = {
                    r["report_date"] for r in conn.execute(
                        "SELECT report_date FROM financial_snapshots WHERE symbol = ?",
                        [symbol]
                    ).fetchall()
                }
                new_dates = sorted(set(all_dates) - existing_dates)

                if not new_dates:
                    print(f"  [{symbol}] up-to-date (0 credits for data)")
                    return {"symbol": symbol, "mode": "noop", "n": 0}

                # Fetch n_quarters = jumlah quarter baru (dari terbaru)
                n_new = len(new_dates)
                print(f"  [{symbol}] {n_new} kuartal baru ditemukan, fetching...")
                snapshots = self.fetch_quarterly(symbol, n_quarters=n_new)
                for q in snapshots:
                    upsert_snapshot(conn, symbol, q)
                conn.commit()
                return {"symbol": symbol, "mode": "incremental", "n": n_new}

        finally:
            conn.close()


def ingest_many(symbols: list, n_quarters: int = 8):
    """Batch ingest. Return summary."""
    ing = Ingestor()
    results = []
    for sym in symbols:
        try:
            results.append(ing.ingest(sym, n_quarters))
        except Exception as e:
            print(f"  ✗ {sym}: {e}")
            results.append({"symbol": sym, "error": str(e)})
    return results