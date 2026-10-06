import os
import requests
from typing import Optional

SECTORS_BASE = "https://api.sectors.app/v2"


def clean_symbol(symbol: str) -> str:
    """'BBCA.JK' -> 'BBCA'"""
    return symbol.replace(".JK", "").replace(".jk", "").upper()


class SectorsClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SECTORS_API_KEY")
        if not self.api_key:
            raise ValueError("SECTORS_API_KEY tidak ditemukan")
        self.headers = {"Authorization": self.api_key}

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{SECTORS_BASE}{path}"
        r = requests.get(url, headers=self.headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # ---------- SCREENER ----------
    def screen(
        self,
        where: str,
        order_by: str = "symbol",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        return self._get("/companies/", params={
            "where": where,
            "order_by": order_by,
            "limit": limit,
            "offset": offset,
        })

    def screen_all(
        self,
        where: str,
        order_by: str = "symbol",
        max_results: int = 200,
    ) -> list[dict]:
        results = []
        offset = 0
        page_size = min(200, max_results)

        while len(results) < max_results:
            resp = self.screen(where, order_by, page_size, offset)
            results.extend(resp.get("results", []))
            if not resp["pagination"]["has_next"]:
                break
            offset = resp["pagination"]["next_offset"]

        return results[:max_results]

    # ---------- COMPANY REPORT ----------
    def get_company_report(self, symbol: str, sections: str = "overview") -> dict:
        return self._get(f"/company/report/{symbol}/", params={"sections": sections})

    # ---------- FINANCIALS ----------
    def get_quarterly_financials(self, symbol: str, n_quarters: int = 4) -> dict:
        return self._get(f"/financials/quarterly/{symbol}/", params={"n_quarters": n_quarters})

    # ---------- CORPORATE ACTIONS ----------
    def get_corporate_actions(self, symbol: str) -> dict:
        return self._get(f"/company/corporate-actions/{symbol}/")

    # ---------- UNIVERSE POLLING ----------
    def poll_recent_quarterly_dates(self, since: str, limit: int = 30) -> dict:
        return self._get("/companies/quarterly-financial-dates/", params={
            "since": since,
            "limit": limit,
        })