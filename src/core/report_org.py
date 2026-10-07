"""
report_org.py — Report dari perspektif organization.

Signal yang sama, tapi interpretasi beda per relationship,
dan makin tajam kalau user udah upload data finansial mereka.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import get_conn, get_relationships, get_organization
from core.context_interpreter import interpret
from core.csv_import import get_org_snapshots


def _load_user_context(conn, org_id: int):
    """Ambil snapshot user terbaru (kalau ada)."""
    snapshots = get_org_snapshots(conn, org_id, limit=12)
    has_data = len(snapshots) > 0
    latest = snapshots[0] if has_data else None
    return snapshots, latest


def _load_target_snapshot(conn, symbol: str):
    """Snapshot terbaru dari monitored company."""
    row = conn.execute("""
        SELECT * FROM financial_snapshots
        WHERE symbol = ?
        ORDER BY report_date DESC LIMIT 1
    """, [symbol]).fetchone()
    return dict(row) if row else None


def _load_signals(conn, symbol: str, limit: int = 3):
    """Signal attention/watch terbaru."""
    rows = conn.execute("""
        SELECT * FROM signals
        WHERE symbol = ? AND severity IN ('attention', 'watch')
        ORDER BY period_label DESC, severity
        LIMIT ?
    """, [symbol, limit]).fetchall()
    return [dict(r) for r in rows]


def org_dashboard(org_id: int):
    conn = get_conn()
    org = get_organization(conn, org_id)
    if not org:
        print(f"  ✗ Org id={org_id} tidak ditemukan")
        conn.close()
        return

    rels = get_relationships(conn, org_id)

    # Header
    print("\n" + "=" * 72)
    print(f"  {org['name']}")
    print(f"  {org['sector_slug']} / {org['subsector_slug']} | Tier: {org['size_tier']}")
    print("=" * 72)

    if not rels:
        print("  (belum ada monitored company)")
        conn.close()
        return

    # User context
    user_snapshots, user_latest = _load_user_context(conn, org_id)
    has_user = user_latest is not None
    user_revenue = user_latest["revenue"] if has_user else None

    print(f"\n  User financial data: ", end="")
    if has_user:
        print(f"✓ {len(user_snapshots)} kuartal (latest revenue: {user_revenue:,})")
    else:
        print("✗ belum di-upload (interpretasi generik)")

    # Signal stats
    symbols = [r["company_symbol"] for r in rels]
    placeholders = ",".join("?" * len(symbols))
    stats = conn.execute(f"""
        SELECT severity, COUNT(*) as n
        FROM signals WHERE symbol IN ({placeholders})
        GROUP BY severity
    """, symbols).fetchall()
    counts = {r["severity"]: r["n"] for r in stats}

    print(f"\n  🔴 {counts.get('attention', 0):>3} Attention    "
          f"🟡 {counts.get('watch', 0):>3} Watch")

    # Group by relationship type
    by_type = {}
    for r in rels:
        by_type.setdefault(r["relationship_type"], []).append(r)

    for rel_type in ["competitor", "supplier", "customer",
                     "distributor", "partner", "other"]:
        if rel_type not in by_type:
            continue

        items = by_type[rel_type]
        print(f"\n  ── {rel_type.upper()} ({len(items)}) "
              + "─" * (60 - len(rel_type)))

        for rel in items:
            sym = rel["company_symbol"]
            sigs = _load_signals(conn, sym, limit=3)
            target_snap = _load_target_snapshot(conn, sym)

            prio_icon = {
                "high": "🔴", "medium": "🟡", "low": "🟢"
            }.get(rel["priority"], "⚪")

            print(f"\n  {prio_icon} {sym} — {rel['company_name'][:40]}")

            if not sigs:
                print(f"      ✓ Tidak ada signal")
                continue

            for s in sigs:
                result = interpret(
                    signal=s,
                    relationship=rel,
                    user_snapshot=user_latest,
                    target_snapshot=target_snap,
                )

                delta_str = (
                    f"{s['delta_pct']:+.1f}%" if s["delta_pct"] is not None else "n/a"
                )
                conf_icon = {"high": "●", "medium": "◐", "low": "○"}.get(
                    result["confidence"], "·"
                )

                print(f"      {conf_icon} {s['period_label']} | "
                      f"{result['headline']} ({delta_str})")
                if result.get("relevance"):
                    print(f"        → {result['relevance']}")

    # Legend
    print(f"\n  Legend: ● high confidence  ◐ medium  ○ low (no user data)")
    conn.close()
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python report_org.py <org_id> [--explain SYMBOL]")
        sys.exit(1)

    org_id = int(sys.argv[1])
    
    if len(sys.argv) >= 4 and sys.argv[2] == "--explain":
        symbol = sys.argv[3].upper()
        # Show report + AI explanation untuk symbol itu
        from core.ai_explain import explain
        org_dashboard(org_id)
        print(f"\n{'=' * 72}")
        print(f"  AI DEEP DIVE: {symbol}")
        print("=" * 72)
        print(explain(symbol, relationship_type="supplier"))
    else:
        org_dashboard(org_id)