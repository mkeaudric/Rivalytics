"""
detect.py — Rule-based signal detection.

Scan SEMUA kuartal historis untuk menemukan anomali.
Sector-aware: skip cash flow weakness untuk bank.
Delta guard: buang signal dengan |delta| > 500% (artefak basis kecil).
"""
import json
from core.db import get_conn, get_snapshots, insert_signal


THRESHOLDS = {
    "revenue_deterioration":  -15.0,
    "profit_deterioration":   -30.0,
    "leverage_increase":       25.0,
    "cash_flow_weakness":     -30.0,
}

# Delta di atas ini dianggap artefak matematika (basis mendekati nol)
DELTA_CAP = 500.0


def _find_snapshot_by_period(snapshots: list, quarter: int, year: int):
    target = f"Q{quarter}-{year}"
    for s in snapshots:
        if f"Q{s['quarter']}-{s['year']}" == target:
            return s
    return None


def _yoy(snapshots: list, idx: int, field: str):
    current = snapshots[idx]
    previous = _find_snapshot_by_period(
        snapshots, current["quarter"], current["year"] - 1
    )
    cur_val = current.get(field)
    prev_val = previous.get(field) if previous else None

    if cur_val is None or prev_val is None or prev_val == 0:
        return cur_val, prev_val, None

    # Basis negatif → delta % tidak bermakna
    if prev_val < 0:
        return cur_val, prev_val, None

    delta = (cur_val - prev_val) / abs(prev_val) * 100
    return cur_val, prev_val, round(delta, 2)


def _build_signal(symbol, period, signal_type, severity, metric,
                  cur, prev, delta, context_extra=None):
    """
    Return dict signal, atau None kalau delta ekstrem (artefak basis).
    """
    if delta is not None and abs(delta) > DELTA_CAP:
        return None

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
    conn = get_conn()
    try:
        snapshots = get_snapshots(conn, symbol, limit=24)
        if len(snapshots) < 5:
            print(f"  [!] {symbol}: snapshot kurang ({len(snapshots)}), skip")
            return []

        # Ambil sector untuk sector-aware rules
        sector_row = conn.execute(
            "SELECT sector FROM companies WHERE symbol = ?", [symbol]
        ).fetchone()
        sector = (sector_row["sector"] or "") if sector_row else ""
        is_financial = "Financial" in sector

        signals_found = []

        for i, snap in enumerate(snapshots):
            period = f"Q{snap['quarter']}-{snap['year']}"

            # --- Rule 1: Revenue deterioration (YoY) ---
            cur, prev, delta = _yoy(snapshots, i, "revenue")
            if delta is not None and delta < THRESHOLDS["revenue_deterioration"]:
                sev = "attention" if delta < -25 else "watch"
                sig = _build_signal(
                    symbol, period, "revenue_deterioration", sev,
                    "revenue", cur, prev, delta,
                )
                if sig:
                    signals_found.append(sig)

            # --- Rule 2: Profit deterioration (YoY) ---
            cur, prev, delta = _yoy(snapshots, i, "earnings")
            if delta is not None and delta < THRESHOLDS["profit_deterioration"]:
                sev = "attention" if delta < -50 else "watch"
                sig = _build_signal(
                    symbol, period, "profit_deterioration", sev,
                    "earnings", cur, prev, delta,
                )
                if sig:
                    signals_found.append(sig)

            # --- Rule 3: Leverage increase (YoY) ---
            cur, prev, delta = _yoy(snapshots, i, "total_debt")
            if delta is not None and delta > THRESHOLDS["leverage_increase"]:
                sev = "watch" if delta < 50 else "attention"
                sig = _build_signal(
                    symbol, period, "leverage_increase", sev,
                    "total_debt", cur, prev, delta,
                )
                if sig:
                    signals_found.append(sig)

            # --- Rule 4: Cash flow weakness (YoY) — SKIP untuk bank ---
            if not is_financial:
                cur, prev, delta = _yoy(snapshots, i, "operating_cash_flow")
                if delta is not None and delta < THRESHOLDS["cash_flow_weakness"]:
                    sev = "attention" if delta < -50 else "watch"
                    sig = _build_signal(
                        symbol, period, "cash_flow_weakness", sev,
                        "operating_cash_flow", cur, prev, delta,
                    )
                    if sig:
                        signals_found.append(sig)

            # --- Rule 5: Loss making ---
            if snap.get("earnings") is not None and snap["earnings"] < 0:
                sig = _build_signal(
                    symbol, period, "loss_making", "attention",
                    "earnings",
                    snap["earnings"], None, None,
                    context_extra={"note": "negative quarterly earnings"},
                )
                if sig:
                    signals_found.append(sig)

        # Store
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