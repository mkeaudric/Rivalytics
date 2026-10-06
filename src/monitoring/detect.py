"""
detect.py — Rule-based signal detection.

Setiap signal yang terdeteksi dimasukkan ke DB dengan:
- severity: info | watch | attention
- metric: revenue, earnings, total_debt, operating_cash_flow, dll
- context: JSON string dengan detail (YoY, QoQ)
"""
import json
from core.db import get_conn, get_snapshots, insert_signal


# Thresholds (dalam persen)
THRESHOLDS = {
    "revenue_deterioration":  -15.0,   # YoY revenue turun > 15%
    "profit_deterioration":   -30.0,   # YoY earnings turun > 30%
    "leverage_increase":       25.0,   # YoY total_debt naik > 25%
    "cash_flow_weakness":     -30.0,   # YoY operating_cf turun > 30%
}


def _yoy(snapshots: list, idx: int, field: str):
    """
    snapshots[idx] = kuartal sekarang
    Cari snapshot dengan period_label setahun lalu (idx+4 jika descending).
    Return (current, previous, delta_pct).
    """
    current = snapshots[idx]
    current_period = f"Q{current['quarter']}-{current['year']}"
    prev_period = f"Q{current['quarter']}-{current['year'] - 1}"

    # Cari di list
    previous = None
    for s in snapshots:
        if f"Q{s['quarter']}-{s['year']}" == prev_period:
            previous = s
            break

    cur_val = current.get(field)
    prev_val = previous.get(field) if previous else None

    if cur_val is None or prev_val is None or prev_val == 0:
        return cur_val, prev_val, None

    delta = (cur_val - prev_val) / abs(prev_val) * 100
    return cur_val, prev_val, round(delta, 2)


def detect_for_symbol(symbol: str) -> list:
    """
    Deteksi semua signal untuk 1 symbol, berdasarkan snapshot terbaru.
    Return list of signals (juga disimpan ke DB).
    """
    conn = get_conn()
    try:
        snapshots = get_snapshots(conn, symbol, limit=12)
        if len(snapshots) < 5:
            print(f"  [!] {symbol}: snapshot kurang ({len(snapshots)}), skip")
            return []

        # Snapshots descending by date, jadi [0] = terbaru
        latest = snapshots[0]
        period = f"Q{latest['quarter']}-{latest['year']}"
        signals_found = []

        # --- Rule 1: Revenue deterioration ---
        cur, prev, delta = _yoy(snapshots, 0, "revenue")
        if delta is not None and delta < THRESHOLDS["revenue_deterioration"]:
            sev = "attention" if delta < -25 else "watch"
            sig = {
                "symbol": symbol,
                "period_label": period,
                "signal_type": "revenue_deterioration",
                "severity": sev,
                "metric": "revenue",
                "current_value": float(cur),
                "previous_value": float(prev),
                "delta_pct": delta,
                "context": json.dumps({"yoy_pct": delta}),
            }
            signals_found.append(sig)

        # --- Rule 2: Profit deterioration ---
        cur, prev, delta = _yoy(snapshots, 0, "earnings")
        if delta is not None and delta < THRESHOLDS["profit_deterioration"]:
            sev = "attention" if delta < -50 else "watch"
            sig = {
                "symbol": symbol,
                "period_label": period,
                "signal_type": "profit_deterioration",
                "severity": sev,
                "metric": "earnings",
                "current_value": float(cur),
                "previous_value": float(prev),
                "delta_pct": delta,
                "context": json.dumps({"yoy_pct": delta}),
            }
            signals_found.append(sig)

        # --- Rule 3: Leverage increase ---
        cur, prev, delta = _yoy(snapshots, 0, "total_debt")
        if delta is not None and delta > THRESHOLDS["leverage_increase"]:
            sev = "watch" if delta < 50 else "attention"
            sig = {
                "symbol": symbol,
                "period_label": period,
                "signal_type": "leverage_increase",
                "severity": sev,
                "metric": "total_debt",
                "current_value": float(cur),
                "previous_value": float(prev),
                "delta_pct": delta,
                "context": json.dumps({"yoy_pct": delta}),
            }
            signals_found.append(sig)

        # --- Rule 4: Operating cash flow weakness ---
        cur, prev, delta = _yoy(snapshots, 0, "operating_cash_flow")
        if delta is not None and delta < THRESHOLDS["cash_flow_weakness"]:
            sev = "attention" if delta < -50 else "watch"
            sig = {
                "symbol": symbol,
                "period_label": period,
                "signal_type": "cash_flow_weakness",
                "severity": sev,
                "metric": "operating_cash_flow",
                "current_value": float(cur),
                "previous_value": float(prev),
                "delta_pct": delta,
                "context": json.dumps({"yoy_pct": delta}),
            }
            signals_found.append(sig)

        # --- Rule 5: Loss making ---
        if latest.get("earnings") is not None and latest["earnings"] < 0:
            sig = {
                "symbol": symbol,
                "period_label": period,
                "signal_type": "loss_making",
                "severity": "attention",
                "metric": "earnings",
                "current_value": float(latest["earnings"]),
                "previous_value": None,
                "delta_pct": None,
                "context": json.dumps({"note": "negative earnings"}),
            }
            signals_found.append(sig)

        # --- Store ---
        for sig in signals_found:
            if insert_signal(conn, sig):
                print(f"  🔔 [{sig['severity']}] {symbol} {period} "
                      f"{sig['signal_type']} (delta={sig['delta_pct']}%)")

        conn.commit()
        return signals_found
    finally:
        conn.close()


def detect_all():
    """Detect untuk semua company yang ada di DB."""
    conn = get_conn()
    symbols = [r["symbol"] for r in conn.execute(
        "SELECT DISTINCT symbol FROM financial_snapshots"
    ).fetchall()]
    conn.close()

    print(f"\n[detect] scanning {len(symbols)} symbols...")
    total = 0
    for s in symbols:
        total += len(detect_for_symbol(s))
    print(f"\n[detect] done. {total} signal baru ditemukan.")
    return total