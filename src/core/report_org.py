"""
report_org.py — Report dari perspektif organization.
Signal yang sama, tapi interpretasi beda per relationship.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import get_conn, get_relationships, get_organization


# Interpretasi signal per relationship type
INTERPRETATION = {
    "competitor": {
        "revenue_deterioration": ("Competitor revenue declining", "Potensi peluang ambil market share"),
        "profit_deterioration":  ("Competitor profitability dropping", "Peluang kompetitif, tapi cek apakah sektor-wide"),
        "leverage_increase":     ("Competitor mengambil lebih banyak utang", "Bisa ekspansi agresif atau distress"),
        "cash_flow_weakness":    ("Competitor cash flow melemah", "Kemungkinan kesulitan operasional"),
        "loss_making":           ("Competitor rugi kuartal ini", "Peluang, tapi hati-hati ada perang harga"),
    },
    "supplier": {
        "revenue_deterioration": ("Supplier revenue turun", "⚠ Risiko supply chain"),
        "profit_deterioration":  ("Supplier profitability turun", "⚠ Risiko keberlanjutan supplier"),
        "leverage_increase":     ("Supplier tambah utang", "⚠ Risiko finansial supplier"),
        "cash_flow_weakness":    ("Supplier cash flow melemah", "⚠ Risiko gagal bayar / delivery"),
        "loss_making":           ("Supplier rugi", "🚨 Risiko tinggi — cek kontrak"),
    },
    "customer": {
        "revenue_deterioration": ("Customer revenue turun", "⚠ Potensi penurunan demand"),
        "profit_deterioration":  ("Customer profitability turun", "⚠ Customer mungkin kurangi order"),
        "leverage_increase":     ("Customer tambah utang", "Cek kemampuan bayar"),
        "cash_flow_weakness":    ("Customer cash flow melemah", "⚠ Risiko pembayaran"),
        "loss_making":           ("Customer rugi", "🚨 Risiko kredit"),
    },
    "distributor": {
        "revenue_deterioration": ("Distributor revenue turun", "⚠ Risiko channel"),
        "profit_deterioration":  ("Distributor profitability turun", "Cek komitmen distributor"),
        "leverage_increase":     ("Distributor tambah utang", "Risiko operasional"),
        "cash_flow_weakness":    ("Distributor cash flow melemah", "⚠ Risiko channel"),
        "loss_making":           ("Distributor rugi", "🚨 Risiko channel disruption"),
    },
    "partner": {
        "revenue_deterioration": ("Partner revenue turun", "Cek dampak ke kolaborasi"),
        "profit_deterioration":  ("Partner profitability turun", "Evaluasi partnership"),
        "leverage_increase":     ("Partner tambah utang", "Cek exposure"),
        "cash_flow_weakness":    ("Partner cash flow melemah", "Evaluasi partnership"),
        "loss_making":           ("Partner rugi", "Tinjau ulang partnership"),
    },
    "other": {
        # default
        "revenue_deterioration": ("Revenue turun", ""),
        "profit_deterioration":  ("Profitability turun", ""),
        "leverage_increase":     ("Leverage naik", ""),
        "cash_flow_weakness":    ("Cash flow melemah", ""),
        "loss_making":           ("Rugi", ""),
    },
}


def _interpret(rel_type: str, signal_type: str):
    """Return (headline, relevance) tuple."""
    mapping = INTERPRETATION.get(rel_type, INTERPRETATION["other"])
    return mapping.get(signal_type, ("Signal terdeteksi", ""))


def org_dashboard(org_id: int):
    conn = get_conn()
    org = get_organization(conn, org_id)
    if not org:
        print(f"  ✗ Org id={org_id} tidak ditemukan")
        conn.close()
        return

    rels = get_relationships(conn, org_id)

    print("\n" + "=" * 72)
    print(f"  {org['name']}")
    print(f"  {org['sector_slug']} / {org['subsector_slug']} | Tier: {org['size_tier']}")
    print("=" * 72)

    if not rels:
        print("  (belum ada monitored company)")
        conn.close()
        return

    # Stats
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

    # Per relationship type
    by_type = {}
    for r in rels:
        by_type.setdefault(r["relationship_type"], []).append(r)

    for rel_type in ["competitor", "supplier", "customer", "distributor", "partner", "other"]:
        if rel_type not in by_type:
            continue

        items = by_type[rel_type]
        print(f"\n  ── {rel_type.upper()} ({len(items)}) " + "─" * (60 - len(rel_type)))

        for rel in items:
            sym = rel["company_symbol"]
            # Ambil signal attention terbaru
            sigs = conn.execute("""
                SELECT period_label, signal_type, severity, delta_pct
                FROM signals
                WHERE symbol = ? AND severity IN ('attention', 'watch')
                ORDER BY period_label DESC, severity
                LIMIT 3
            """, [sym]).fetchall()

            prio_icon = "🔴" if rel["priority"] == "high" else (
                "🟡" if rel["priority"] == "medium" else "🟢"
            )
            print(f"\n  {prio_icon} {sym} — {rel['company_name'][:40]}")

            if not sigs:
                print(f"      ✓ Tidak ada signal")
                continue

            for s in sigs:
                headline, relevance = _interpret(rel_type, s["signal_type"])
                delta_str = f"{s['delta_pct']:+.1f}%" if s["delta_pct"] else "n/a"
                print(f"      · {s['period_label']} | {headline} ({delta_str})")
                if relevance:
                    print(f"        → {relevance}")

    conn.close()
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python report_org.py <org_id>")
        sys.exit(1)
    org_dashboard(int(sys.argv[1]))