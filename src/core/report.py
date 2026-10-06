"""
report.py — Tampilkan ringkasan dari DB.
Bukan dashboard web, cuma CLI — cukup untuk demo video.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import get_conn


SEVERITY_ICON = {
    "attention": "🔴",
    "watch":     "🟡",
    "info":      "🔵",
}

SEVERITY_RANK = {"attention": 0, "watch": 1, "info": 2}


def summary():
    """Ringkasan portofolio yang dimonitor."""
    conn = get_conn()

    # Total per severity
    print("\n" + "=" * 70)
    print("  RIVALYTICS — COMPANY INTELLIGENCE SUMMARY")
    print("=" * 70)

    rows = conn.execute("""
        SELECT severity, COUNT(*) as n
        FROM signals GROUP BY severity
    """).fetchall()
    counts = {r["severity"]: r["n"] for r in rows}

    print(f"\n  🔴 {counts.get('attention', 0):>3} Attention   "
          f"🟡 {counts.get('watch', 0):>3} Watch   "
          f"🔵 {counts.get('info', 0):>3} Info")

    # Company-level summary
    print("\n" + "-" * 70)
    print("  MONITORED COMPANIES")
    print("-" * 70)

    companies = conn.execute("""
        SELECT c.symbol, c.name, c.sector, c.market_cap,
               COUNT(s.id) as n_signals,
               SUM(CASE WHEN s.severity = 'attention' THEN 1 ELSE 0 END) as n_attention
        FROM companies c
        LEFT JOIN signals s ON s.symbol = c.symbol
        GROUP BY c.symbol
        ORDER BY n_attention DESC, n_signals DESC
    """).fetchall()

    print(f"\n  {'Symbol':6} {'Company':38} {'Attn':>5} {'Total':>6}")
    print(f"  {'-'*6} {'-'*38} {'-'*5} {'-'*6}")

    for c in companies:
        icon = "🔴" if c["n_attention"] >= 3 else ("🟡" if c["n_attention"] >= 1 else "🟢")
        name = (c["name"] or "")[:36]
        print(f"  {icon} {c['symbol']:5} {name:38} {c['n_attention'] or 0:>5} {c['n_signals']:>6}")

    conn.close()
    print()


def company_detail(symbol: str):
    """Detail 1 company."""
    conn = get_conn()

    company = conn.execute(
        "SELECT * FROM companies WHERE symbol = ?", [symbol]
    ).fetchone()
    if not company:
        print(f"  ✗ {symbol} tidak ditemukan")
        return

    print("\n" + "=" * 70)
    print(f"  {company['symbol']} — {company['name']}")
    print("=" * 70)
    print(f"  Sector:      {company['sector']}")
    print(f"  Sub-sector:  {company['sub_sector']}")
    print(f"  Market cap:  {company['market_cap']:,}")

    # Snapshot terbaru
    latest = conn.execute("""
        SELECT * FROM financial_snapshots
        WHERE symbol = ?
        ORDER BY report_date DESC LIMIT 1
    """, [symbol]).fetchone()

    if latest:
        print(f"\n  Latest quarter: {latest['period_label']}")
        print(f"  Revenue:        {latest['revenue']:>22,}" if latest['revenue'] else "")
        print(f"  Earnings:       {latest['earnings']:>22,}" if latest['earnings'] else "")
        print(f"  Total debt:     {latest['total_debt']:>22,}" if latest['total_debt'] else "")

    # Signals
    signals = conn.execute("""
        SELECT * FROM signals
        WHERE symbol = ?
        ORDER BY period_label DESC, severity
    """, [symbol]).fetchall()

    if signals:
        print(f"\n  SIGNALS ({len(signals)}):")
        for s in signals:
            icon = SEVERITY_ICON.get(s["severity"], "?")
            delta_str = f"{s['delta_pct']:+.2f}%" if s["delta_pct"] else "n/a"
            print(f"    {icon} {s['period_label']:8} {s['signal_type']:25} {delta_str}")
    else:
        print(f"\n  ✓ Tidak ada signal.")

    conn.close()
    print()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        company_detail(sys.argv[1].upper())
    else:
        summary()