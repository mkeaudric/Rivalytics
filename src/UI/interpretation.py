"""
interpretation.py — Interpretasi signal (umum + relatif) + Explain via Groq.
"""
import os
from typing import Optional


# =========================
# INTERPRETASI UMUM (vs peer)
# =========================
def interpret_general(symbol: str, signal: dict, companies: list, signals: list) -> str:
    """
    Bandingin signal perusahaan ini dengan peer di subsector yang sama.
    """
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
def interpret_relative(symbol: str, signal: dict, user_symbol: Optional[str], signals: list) -> str:
    """
    Bandingin signal perusahaan ini dengan perusahaan user.
    """
    if not user_symbol:
        return "User belum pilih perusahaan pembanding."

    # Cari signal user yang sama (period sama)
    user_signal = next(
        (s for s in signals
         if s["symbol"] == user_symbol
         and s["signal_type"] == signal["signal_type"]
         and s["period_label"] == signal["period_label"]),
        None,
    )

    if not user_signal:
        return (
            f"{symbol}: **{signal['delta_pct']:+.1f}%** YoY. "
            f"Kamu ({user_symbol}) tidak punya signal yang sama di periode ini. "
            f"Kamu mungkin lebih stabil."
        )

    user_delta = user_signal["delta_pct"]
    diff = signal["delta_pct"] - user_delta

    if signal["signal_type"] in ("revenue_deterioration", "profit_deterioration", "cash_flow_weakness"):
        if diff < -10:
            verdict = f"{symbol} **jauh lebih buruk** dari kamu. Ini **peluang** ambil market share."
        elif diff > 10:
            verdict = f"{symbol} **lebih baik** dari kamu. Waspada, mereka mungkin lagi growth."
        else:
            verdict = f"{symbol} sejalan dengan kamu."
    else:
        verdict = f"{symbol} berbeda dari kamu."

    return (
        f"{symbol}: **{signal['delta_pct']:+.1f}%** YoY. "
        f"Kamu ({user_symbol}): **{user_delta:+.1f}%** YoY. "
        f"→ {verdict}"
    )


# =========================
# EXPLAIN VIA GROQ
# =========================
def explain_with_groq(
    symbol: str,
    signal: dict,
    interpretation_general: str,
    interpretation_relative: str,
    user_name: str = "perusahaan kamu",
) -> str:
    """
    Panggil Groq API untuk penjelasan natural language.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return (
            "⚠ **GROQ_API_KEY belum diset.**\n\n"
            "Cara set:\n"
            "```\n$env:GROQ_API_KEY='gsk_xxxxx'\n```\n"
            "Atau bikin file `.env` di root project."
        )

    try:
        from groq import Groq
    except ImportError:
        return "⚠ Package `groq` belum diinstall. Jalankan: `pip install groq`"

    client = Groq(api_key=api_key)

    # Bersihin markdown dari interpretasi
    gen_clean = interpretation_general.replace("**", "")
    rel_clean = interpretation_relative.replace("**", "")

    prompt = f"""Kamu adalah analis bisnis. Jelaskan signal berikut secara singkat, jelas, dan actionable.

PERUSAHAAN: {symbol}
SIGNAL: {signal['signal_type']}
PERIODE: {signal['period_label']}
DELTA: {signal['delta_pct']:+.1f}%
SEVERITY: {signal['severity']}

INTERPRETASI UMUM (vs peer):
{gen_clean}

INTERPRETASI RELATIF (vs {user_name}):
{rel_clean}

Tulis penjelasan 3-4 kalimat yang:
1. Menjelaskan apa arti signal ini
2. Kenapa penting
3. Apa yang harus dilakukan user

Langsung paragraf, tanpa bullet points."""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Kamu adalah analis bisnis profesional."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=300,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠ Gagal panggil Groq: {e}"