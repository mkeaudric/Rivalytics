"""
context_interpreter.py — Interpretasi signal dengan konteks user.

Input:
  - signal (dari tabel signals)
  - relationship (competitor/supplier/dll)
  - user snapshot (kalau ada)
  - target company snapshot

Output:
  - (headline, relevance, confidence)
  - confidence = 'high' (user data ada) | 'medium' (user data ada tapi beda periode) | 'low' (no user data)
"""
import re
from typing import Optional


def _size_bucket(user_val: Optional[int], target_val: Optional[int]) -> str:
    """
    Return: 'much_smaller' | 'smaller' | 'similar' | 'larger' | 'much_larger' | 'unknown'
    Berdasarkan rasio revenue.
    """
    if not user_val or not target_val or user_val <= 0:
        return "unknown"

    ratio = target_val / user_val
    if ratio >= 5:
        return "much_larger"
    if ratio >= 1.5:
        return "larger"
    if ratio >= 0.67:
        return "similar"
    if ratio >= 0.2:
        return "smaller"
    return "much_smaller"


# ============================================================
# Interpretation tables
# ============================================================

COMPETITOR_REVENUE_DOWN = {
    "much_larger": (
        "Kompetitor {name} yang {ratio}x lebih besar dari Anda sedang kontraksi",
        "Dampak ke competitive position Anda terbatas kecuali mereka exit lini produk tertentu. Perlu cek segmentasi bisnis mereka.",
    ),
    "larger": (
        "Kompetitor {name} ({ratio}x ukuran Anda) revenue turun",
        "Momentum mereka melemah. Berpotensi buka ruang share jika Anda bisa maintain margin — cek apakah mereka akan re-price.",
    ),
    "similar": (
        "Kompetitor head-to-head Anda {name} revenue turun",
        "Kompetitor langsung sedang melemah. Ini peluang taktis untuk agresif di segmen yang overlap.",
    ),
    "smaller": (
        "Kompetitor lebih kecil {name} revenue turun",
        "Dampak ke Anda minimal. Mungkin cek apakah mereka akan jadi acquisition target atau exit pasar.",
    ),
    "much_smaller": (
        "Kompetitor kecil {name} revenue turun",
        "Signal ini tidak relevan untuk competitive position Anda. Bisa diabaikan.",
    ),
    "unknown": (
        "Kompetitor {name} revenue turun",
        "Perlu data revenue Anda untuk interpretasi yang tajam. Tanpa itu, ini cuma indikator umum.",
    ),
}

COMPETITOR_PROFIT_DOWN = {
    "much_larger": (
        "Kompetitor {name} profit turun signifikan",
        "Profitabilitas mereka melemah tapi ukuran masih jauh di atas Anda. Fokus pada segmen niche yang bisa Anda menangkan.",
    ),
    "larger": (
        "Kompetitor utama {name} profit turun",
        "Profitabilitas kompetitor turun — bisa jadi akibat perang harga atau cost pressure. Cek apakah ini sektor-wide.",
    ),
    "similar": (
        "Kompetitor head-to-head {name} profit turun",
        "Peluang langsung: mereka mungkin kurangi marketing spend atau R&D. Agresif di area itu.",
    ),
    "smaller": (
        "Kompetitor kecil {name} profit turun",
        "Bukan ancaman langsung. Monitor apakah mereka masuk price war.",
    ),
    "much_smaller": (
        "Kompetitor kecil {name} profit turun",
        "Tidak relevan untuk strategic Anda.",
    ),
    "unknown": (
        "Kompetitor {name} profit turun",
        "Interpretasi butuh konteks ukuran relatif.",
    ),
}

SUPPLIER_CASHFLOW_DOWN = {
    "high": (
        "🚨 Supplier prioritas tinggi {name} cash flow melemah",
        "Risiko supply chain nyata. Segera cek kontrak delivery & cari alternatif.",
    ),
    "medium": (
        "Supplier {name} cash flow melemah",
        "Monitor ketat. Siapkan backup supplier jika kondisi memburuk kuartal depan.",
    ),
    "low": (
        "Supplier {name} cash flow melemah",
        "Exposure Anda rendah. Catat di watchlist, review 1-2 kuartal lagi.",
    ),
}

# ... dst untuk signal_type lain


# ============================================================
# Main function
# ============================================================

def interpret(signal: dict, relationship: dict,
              user_snapshot: Optional[dict] = None,
              target_snapshot: Optional[dict] = None) -> dict:
    """
    Return dict:
        {
          'headline': str,
          'relevance': str,
          'confidence': 'high'|'medium'|'low',
        }
    """
    rel_type = relationship["relationship_type"]
    priority = relationship.get("priority", "medium")
    company_name = relationship.get("company_name", relationship["company_symbol"])
    signal_type = signal["signal_type"]

    # Hitung ukuran relatif
    size = "unknown"
    ratio_str = ""
    if user_snapshot and target_snapshot:
        user_rev = user_snapshot.get("revenue")
        target_rev = target_snapshot.get("revenue")
        size = _size_bucket(user_rev, target_rev)
        if user_rev and target_rev and user_rev > 0:
            ratio = target_rev / user_rev
            ratio_str = f"{ratio:.1f}"

    # Confidence level
    if size != "unknown":
        confidence = "high"
    elif user_snapshot:
        confidence = "medium"
    else:
        confidence = "low"

    # Pilih interpretation
    headline = None
    relevance = None

    if rel_type == "competitor":
        if signal_type in ("revenue_deterioration", "loss_making"):
            tmpl = COMPETITOR_REVENUE_DOWN.get(size) or COMPETITOR_REVENUE_DOWN["unknown"]
            headline = tmpl[0].format(name=company_name, ratio=ratio_str)
            relevance = tmpl[1]
        elif signal_type == "profit_deterioration":
            tmpl = COMPETITOR_PROFIT_DOWN.get(size) or COMPETITOR_PROFIT_DOWN["unknown"]
            headline = tmpl[0].format(name=company_name, ratio=ratio_str)
            relevance = tmpl[1]
        else:
            # leverage_increase, cash_flow_weakness → generic + size context
            headline = f"Kompetitor {company_name} {signal_type.replace('_', ' ')}"
            if size in ("much_larger", "larger"):
                relevance = f"Meskipun lebih besar dari Anda, perhatikan apakah ini tanda tekanan sektor."
            elif size == "similar":
                relevance = "Head-to-head competitor. Perhatikan implikasi kompetitif."
            else:
                relevance = "Signal umum, butuh konteks lebih."

    elif rel_type == "supplier":
        if signal_type in ("cash_flow_weakness", "loss_making"):
            tmpl = SUPPLIER_CASHFLOW_DOWN.get(priority) or SUPPLIER_CASHFLOW_DOWN["medium"]
            headline = tmpl[0].format(name=company_name)
            relevance = tmpl[1]
        elif signal_type == "leverage_increase":
            headline = f"Supplier {company_name} tambah utang"
            if priority == "high":
                relevance = "⚠ Supplier prioritas tinggi menambah leverage. Cek likuiditas & komitmen delivery."
            else:
                relevance = "Monitor. Cek apakah untuk ekspansi atau untuk survive."
        elif signal_type == "revenue_deterioration":
            headline = f"Supplier {company_name} revenue turun"
            relevance = "⚠ Potensi supply disruption. Cek kapasitas mereka untuk fulfill kontrak."
        else:
            headline = f"Supplier {company_name} {signal_type.replace('_', ' ')}"
            relevance = "Signal untuk dipantau."

    elif rel_type == "customer":
        if signal_type in ("revenue_deterioration", "profit_deterioration", "loss_making"):
            headline = f"Customer {company_name} mengalami tekanan finansial"
            relevance = "⚠ Risiko penurunan order atau keterlambatan pembayaran. Cek exposure Anda."
        elif signal_type == "cash_flow_weakness":
            headline = f"Customer {company_name} cash flow melemah"
            relevance = "⚠ Tingkatkan monitoring pembayaran. Cek aging receivable."
        else:
            headline = f"Customer {company_name} {signal_type.replace('_', ' ')}"
            relevance = "Signal untuk dipantau dari sisi demand."

    else:
        # Generic fallback
        headline = f"{company_name}: {signal_type.replace('_', ' ')}"
        relevance = "Perlu konteks relationship untuk interpretasi."

    return {
        "headline": headline,
        "relevance": relevance,
        "confidence": confidence,
        "size_context": size,
    }

# =========================
# INTERPRETASI UMUM (vs peer)
# =========================
def interpret_general(symbol: str, signal: dict, companies: list, signals: list) -> str:
    """
    Bandingin signal perusahaan ini dengan peer di subsector yang sama.
    """
    if signal.get("delta_pct") is None:
        return (
            f"{symbol} tidak punya delta YoY untuk signal "
            f"{signal['signal_type']} (loss making — basis pembanding negatif). "
            f"Interpretasi manual diperlukan."
        )

    # Cari company info
    company = next((c for c in companies if c["symbol"] == symbol), None)
    if not company:
        return "Data perusahaan tidak ditemukan."

    subsector = company["sub_sector"]

    # Cari peer yang punya signal sama di period sama
    peers = [
        s for s in signals
        if s["signal_type"] == signal["signal_type"]
        and s["period_label"] == signal["period_label"]
        and s["symbol"] != symbol
        and next((c for c in companies if c["symbol"] == s["symbol"] and c["sub_sector"] == subsector), None)
    ]

    if not peers:
        return (
            f"Tidak ada peer di subsector '{subsector}' dengan signal sama. "
            f"Signal ini unik untuk {symbol}."
        )

    deltas = [p["delta_pct"] for p in peers if p["delta_pct"] is not None]
    if not deltas:
        return "Peer ada tapi tidak ada data delta."

    avg = sum(deltas) / len(deltas)
    diff = signal["delta_pct"] - avg

    if signal["signal_type"] in ("revenue_deterioration", "profit_deterioration", "cash_flow_weakness"):
        if diff < -10:
            verdict = "**lebih buruk** dari rata-rata peer"
        elif diff > 10:
            verdict = "**lebih baik** dari rata-rata peer"
        else:
            verdict = "sejalan dengan peer"
    else:
        verdict = "berbeda dari peer"

    return (
        f"{symbol} mengalami **{signal['signal_type']}** dengan delta "
        f"**{signal['delta_pct']:+.1f}%**. "
        f"Rata-rata peer di {subsector}: **{avg:+.1f}%** ({len(peers)} peer). "
        f"→ {symbol} {verdict}."
    )

# =========================
# INTERPRETASI RELATIF (vs user)
# =========================
def interpret_relative(symbol: str, signal: dict, user_snapshots: list, user_name: str = "kamu") -> str:
    """
    Bandingin signal perusahaan dengan data CSV user (dari org_snapshots).
    """
    if signal.get("delta_pct") is None:
        return (
            f"{symbol}: signal `{signal['signal_type']}` tidak punya delta YoY. "
            f"Perbandingan relative tidak tersedia."
        )

    period_label = signal["period_label"]
    m = re.match(r"Q(\d)-(\d{4})", period_label)
    if not m:
        return "Format period tidak dikenali."
    q, year = int(m.group(1)), int(m.group(2))
    prev_label = f"Q{q}-{year - 1}"

    current = next((s for s in user_snapshots if s["period_label"] == period_label), None)
    previous = next((s for s in user_snapshots if s["period_label"] == prev_label), None)

    if not current or not previous:
        return (
            f"⚠ **Data kamu tidak cukup** untuk dibandingkan.\n\n"
            f"Butuh kuartal **{period_label}** dan **{prev_label}**. "
            f"Upload CSV di tab **📄 CSV Import**."
        )

    metric = signal.get("metric", "revenue")
    cur_val = current.get(metric)
    prev_val = previous.get(metric)

    if cur_val is None or prev_val is None or prev_val == 0 or prev_val < 0:
        return f"⚠ Data `{metric}` kamu tidak valid untuk perbandingan."

    user_delta = round((cur_val - prev_val) / abs(prev_val) * 100, 2)
    diff = signal["delta_pct"] - user_delta

    if signal["signal_type"] in ("revenue_deterioration", "profit_deterioration", "cash_flow_weakness"):
        if diff < -10:
            verdict = f"{symbol} **jauh lebih buruk** dari kamu. Peluang ambil market share."
        elif diff > 10:
            verdict = f"{symbol} **lebih baik** dari kamu. Waspada."
        else:
            verdict = f"{symbol} sejalan dengan kamu."
    else:
        verdict = f"{symbol} berbeda dari kamu."

    return (
        f"**{symbol}**: **{signal['delta_pct']:+.1f}%** YoY ({metric})\n\n"
        f"**{user_name}**: **{user_delta:+.1f}%** YoY (metric sama)\n\n"
        f"→ {verdict}"
    )