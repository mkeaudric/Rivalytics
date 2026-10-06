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

    def ingest(self, symbol: str, n_quarters: int = 8) -> dict:
        """
        Fetch + store 1 company. Return summary.
        """
        symbol = _clean_symbol(symbol)
        print(f"\n[ingest] {symbol}")

        conn = get_conn()
        try:
            # --- Overview ---
            print(f"  → fetching overview...")
            report = self.fetch_overview(symbol)
            ov = report.get("overview", {})
            upsert_company(conn, symbol, report.get("company_name", symbol), ov)
            print(f"    ✓ {report.get('company_name')} | MC: {ov.get('market_cap', 0):,}")

            # --- Quarterly ---
            print(f"  → fetching quarterly (n={n_quarters})...")
            snapshots = self.fetch_quarterly(symbol, n_quarters)

            for q in snapshots:
                upsert_snapshot(conn, symbol, q)

            conn.commit()
            print(f"    ✓ {len(snapshots)} snapshots stored")

            return {
                "symbol": symbol,
                "name": report.get("company_name"),
                "snapshots_stored": len(snapshots),
            }
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