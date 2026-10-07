"""
csv_import.py — Import user financial data dari CSV.

Format CSV yang diharapkan:
    period,revenue,earnings,total_debt,operating_cash_flow
    Q1-2025,50000000000,5000000000,10000000000,3000000000
    ...

Usage:
    python src/core/csv_import.py <org_id> <path_to_csv>
"""
import csv
import re
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import get_conn, get_organization


PERIOD_RE = re.compile(r"^Q([1-4])-(\d{4})$", re.IGNORECASE)


def _parse_period(period_str: str) -> tuple[int, int, str]:
    """
    'Q2-2026' → (2, 2026, '2026-06-30')
    """
    m = PERIOD_RE.match(period_str.strip())
    if not m:
        raise ValueError(
            f"Format period salah: '{period_str}'. Harus 'Q1-YYYY' s/d 'Q4-YYYY'"
        )
    quarter = int(m.group(1))
    year = int(m.group(2))
    month_end = {1: 3, 2: 6, 3: 9, 4: 12}[quarter]
    last_day = {3: 31, 6: 30, 9: 30, 12: 31}[month_end]
    report_date = f"{year}-{month_end:02d}-{last_day:02d}"
    return quarter, year, report_date


def _parse_number(s: str):
    """Handle '', 'NULL', '1.000.000', '1,000,000', '1000000'."""
    if s is None:
        return None
    s = str(s).strip()
    if s == "" or s.upper() in ("NULL", "N/A", "-", "NA"):
        return None
    # Hapus pemisah ribuan
    s = s.replace(".", "").replace(",", "")
    try:
        return int(float(s))
    except ValueError:
        return None


REQUIRED_COLS = {"period"}
KNOWN_COLS = {
    "period", "revenue", "earnings", "total_assets", "total_liabilities",
    "total_debt", "operating_cash_flow",
}


def import_csv(org_id: int, csv_path: str) -> dict:
    """
    Return dict: {inserted, updated, skipped, errors}
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV tidak ditemukan: {csv_path}")

    conn = get_conn()
    try:
        org = get_organization(conn, org_id)
        if not org:
            raise ValueError(f"Org id={org_id} tidak ditemukan")

        inserted = 0
        updated = 0
        errors = []

        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            # Validasi header
            if not reader.fieldnames:
                raise ValueError("CSV kosong atau gak ada header")

            cols = {c.strip().lower() for c in reader.fieldnames}
            missing = REQUIRED_COLS - cols
            if missing:
                raise ValueError(f"Kolom wajib hilang: {missing}")

            unknown = cols - KNOWN_COLS
            if unknown:
                print(f"  ⚠ Kolom tidak dikenal diabaikan: {unknown}")

            for i, row in enumerate(reader, start=2):  # row 2 = baris data pertama
                try:
                    period = row.get("period", "").strip()
                    if not period:
                        continue

                    quarter, year, report_date = _parse_period(period)

                    values = {
                        "organization_id": org_id,
                        "period_label": f"Q{quarter}-{year}",
                        "report_date": report_date,
                        "quarter": quarter,
                        "year": year,
                        "revenue": _parse_number(row.get("revenue")),
                        "earnings": _parse_number(row.get("earnings")),
                        "total_assets": _parse_number(row.get("total_assets")),
                        "total_liabilities": _parse_number(row.get("total_liabilities")),
                        "total_debt": _parse_number(row.get("total_debt")),
                        "operating_cash_flow": _parse_number(row.get("operating_cash_flow")),
                        "source": "csv",
                    }

                    # Cek duplikat
                    existing = conn.execute("""
                        SELECT id FROM org_snapshots
                        WHERE organization_id = ? AND period_label = ?
                    """, [org_id, values["period_label"]]).fetchone()

                    if existing:
                        conn.execute("""
                            UPDATE org_snapshots SET
                                revenue = ?, earnings = ?, total_assets = ?,
                                total_liabilities = ?, total_debt = ?,
                                operating_cash_flow = ?
                            WHERE id = ?
                        """, [
                            values["revenue"], values["earnings"],
                            values["total_assets"], values["total_liabilities"],
                            values["total_debt"], values["operating_cash_flow"],
                            existing["id"],
                        ])
                        updated += 1
                    else:
                        conn.execute("""
                            INSERT INTO org_snapshots (
                                organization_id, period_label, report_date,
                                quarter, year, revenue, earnings,
                                total_assets, total_liabilities, total_debt,
                                operating_cash_flow, source
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, [
                            values["organization_id"], values["period_label"],
                            values["report_date"], values["quarter"], values["year"],
                            values["revenue"], values["earnings"],
                            values["total_assets"], values["total_liabilities"],
                            values["total_debt"], values["operating_cash_flow"],
                            values["source"],
                        ])
                        inserted += 1

                except Exception as e:
                    errors.append(f"Baris {i}: {e}")

        conn.commit()

        return {
            "organization": org["name"],
            "inserted": inserted,
            "updated": updated,
            "errors": errors,
        }
    finally:
        conn.close()


def get_org_snapshots(conn, org_id: int, limit: int = 12):
    rows = conn.execute("""
        SELECT * FROM org_snapshots
        WHERE organization_id = ?
        ORDER BY report_date DESC
        LIMIT ?
    """, [org_id, limit]).fetchall()
    return [dict(r) for r in rows]


# ---- CLI ----

def main():
    if len(sys.argv) < 3:
        print("Usage: python csv_import.py <org_id> <path_to_csv>")
        sys.exit(1)

    org_id = int(sys.argv[1])
    csv_path = sys.argv[2]

    print(f"\n[import] org_id={org_id}, csv={csv_path}")
    result = import_csv(org_id, csv_path)

    print(f"\n  Organization: {result['organization']}")
    print(f"  Inserted:     {result['inserted']} baris")
    print(f"  Updated:      {result['updated']} baris")

    if result["errors"]:
        print(f"\n  Errors ({len(result['errors'])}):")
        for e in result["errors"]:
            print(f"    - {e}")
    else:
        print(f"  Errors:       0")

    print()


if __name__ == "__main__":
    main()