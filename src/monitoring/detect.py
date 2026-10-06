"""
detect.py — Rule-based signal detection.

Scan SEMUA kuartal historis (bukan cuma terbaru) untuk menemukan
anomali yang mungkin sudah lewat tapi penting untuk konteks.

Setiap signal dimasukkan ke DB dengan:
- severity: info | watch | attention
- metric: revenue, earnings, total_debt, operating_cash_flow
- context: JSON string dengan detail (YoY, QoQ, dsb)
"""
import json
from core.db import get_conn, get_snapshots, insert_signal


# Thresholds (dalam persen)
THRESHOLDS = {
    "revenue_deterioration":  -15.0,
    "profit_deterioration":   -30.0,
    "leverage_increase":       25.0,
    "cash_flow_weakness":     -30.0,
}


def _find_snapshot_by_period(snapshots: list, quarter: int, year: int):
    """Cari snapshot dengan quarter & year tertentu."""
    target = f"Q{quarter}-{year}"
    for s in snapshots:
        if f"Q{s['quarter']}-{s['year']}" == target:
            return s
    return None


def _yoy(snapshots, idx, field):
    current = snapshots[idx]
    previous = _find_snapshot_by_period(
        snapshots, current["quarter"], current["year"] - 1
    )

    cur_val = current.get(field)
    prev_val = previous.get(field) if previous else None

    if cur_val is None or prev_val is None or prev_val == 0:
        return cur_val, prev_val, None

    # Edge case: basis negatif → delta % gak bermakna
    if prev_val < 0:
        # Kalau dua-duanya negatif, kasih delta=None biar rule gak trigger
        # (loss_making yang handle kasus ini)
        if cur_val < 0:
            return cur_val, prev_val, None
        # Kalau basis negatif tapi sekarang positif → "recovery"
        # juga skip, karena maknanya ambigu

    delta = (cur_val - prev_val) / abs(prev_val) * 100
    return cur_val, prev_val, round(delta, 2)


def _qoq(snapshots: list, idx: int, field: str):
    """
    QoQ comparison: kuartal sekarang vs kuartal sebelumnya.
    Handle wrap Q1 → Q4 tahun sebelumnya.
    """
    current = snapshots[idx]

    # Cari kuartal sebelumnya
    if current["quarter"] == 1:
        prev_q, prev_y = 4, current["year"] - 1
    else:
        prev_q, prev_y = current["quarter"] - 1, current["year"]

    previous = _find_snapshot_by_period(snapshots, prev_q, prev_y)

    cur_val = current.get(field)
    prev_val = previous.get(field) if previous else None

    if cur_val is None or prev_val is None or prev_val == 0:
        return cur_val, prev_val, None

    delta = (cur_val - prev_val) / abs(prev_val) * 100
    return cur_val, prev_val, round(delta, 2)


def _build_signal(symbol, period, signal_type, severity, metric,
                  cur, prev, delta, context_extra=None):
    ctx = {"yoy_pct": delta} if context_extra is None else context_extra
    return {
        "symbol": symbol,
        "period_label": period,
        "signal_type": signal_type,
        "severity": severity,
        "metric": metric,
        "current_value": float(cur) if cur is not None else None,
        "previous_value": float(prev) if prev is not None else None,
        "delta_pct": delta,
        "context": json.dumps(ctx),
    }


def detect_for_symbol(symbol: str) -> list:
    """
    Scan SEMUA kuartal untuk 1 symbol.
    Return list signal yang baru dibuat (tidak termasuk yang sudah ada di DB).
    """
    conn = get_conn()
    try:
        # Ambil lebih banyak snapshot untuk cakupan historis
        snapshots = get_snapshots(conn, symbol, limit=24)
        if len(snapshots) < 5:
            print(f"  [!] {symbol}: snapshot kurang ({len(snapshots)}), skip")
            return []

        signals_found = []

        # Loop semua kuartal (mulai dari yang terbaru)
        for i, snap in enumerate(snapshots):
            period = f"Q{snap['quarter']}-{snap['year']}"

            # --- Rule 1: Revenue deterioration (YoY) ---
            cur, prev, delta = _yoy(snapshots, i, "revenue")
            if delta is not None and delta < THRESHOLDS["revenue_deterioration"]:
                sev = "attention" if delta < -25 else "watch"
                signals_found.append(_build_signal(
                    symbol, period, "revenue_deterioration", sev,
                    "revenue", cur, prev, delta,
                ))

            # --- Rule 2: Profit deterioration (YoY) ---
            cur, prev, delta = _yoy(snapshots, i, "earnings")
            if delta is not None and delta < THRESHOLDS["profit_deterioration"]:
                sev = "attention" if delta < -50 else "watch"
                signals_found.append(_build_signal(
                    symbol, period, "profit_deterioration", sev,
                    "earnings", cur, prev, delta,
                ))

            # --- Rule 3: Leverage increase (YoY) ---
            cur, prev, delta = _yoy(snapshots, i, "total_debt")
            if delta is not None and delta > THRESHOLDS["leverage_increase"]:
                sev = "watch" if delta < 50 else "attention"
                signals_found.append(_build_signal(
                    symbol, period, "leverage_increase", sev,
                    "total_debt", cur, prev, delta,
                ))

            # --- Rule 4: Operating cash flow weakness (YoY) ---
            cur, prev, delta = _yoy(snapshots, i, "operating_cash_flow")
            if delta is not None and delta < THRESHOLDS["cash_flow_weakness"]:
                sev = "attention" if delta < -50 else "watch"
                signals_found.append(_build_signal(
                    symbol, period, "cash_flow_weakness", sev,
                    "operating_cash_flow", cur, prev, delta,
                ))

            # --- Rule 5: Loss making (per kuartal) ---
            if snap.get("earnings") is not None and snap["earnings"] < 0:
                signals_found.append(_build_signal(
                    symbol, period, "loss_making", "attention",
                    "earnings",
                    snap["earnings"], None, None,
                    context_extra={"note": "negative quarterly earnings"},
                ))

        # --- Store (idempotent: insert_signal skip kalau sudah ada) ---
        new_count = 0
        for sig in signals_found:
            if insert_signal(conn, sig):
                new_count += 1
                print(f"  🔔 [{sig['severity']:9}] {symbol} {sig['period_label']:8} "
                      f"{sig['signal_type']:22} "
                      f"delta={sig['delta_pct'] if sig['delta_pct'] is not None else 'n/a'}%")

        conn.commit()

        if new_count == 0 and signals_found:
            print(f"  [{symbol}] {len(signals_found)} signal lama (sudah ada di DB)")
        elif new_count == 0:
            print(f"  [{symbol}] tidak ada signal")

        return signals_found
    finally:
        conn.close()


def detect_all():
    """Detect untuk semua company di DB."""
    conn = get_conn()
    symbols = [r["symbol"] for r in conn.execute(
        "SELECT DISTINCT symbol FROM financial_snapshots"
    ).fetchall()]
    conn.close()

    print(f"\n[detect] scanning {len(symbols)} symbols...")
    total = 0
    for s in symbols:
        total += len(detect_for_symbol(s))
    print(f"\n[detect] done. {total} signal total (termasuk yang sudah ada).")
    return total