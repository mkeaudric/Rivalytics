"""
ai_explain.py — AI explanation layer.

Ambil signal + metrics dari DB, kirim ke LLM, dapat narasi.
Bukan agent. Bukan MCP. Just a single-shot prompt → response.
"""
import json
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import get_conn, get_snapshots


# ---- Provider abstraction ----

class LLMProvider:
    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class GroqProvider(LLMProvider):
    def __init__(self, model: str = "openai/gpt-oss-120b"):
        try:
            from groq import Groq
        except ImportError:
            raise RuntimeError("Install dulu: pip install groq")
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("Set GROQ_API_KEY environment variable")
        self.client = Groq(api_key=key)
        self.model = model

    def complete(self, system: str, user: str) -> str:
        r = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return r.choices[0].message.content


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str = "gpt-4o-mini"):
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("Install dulu: pip install openai")
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("Set OPENAI_API_KEY environment variable")
        self.client = OpenAI(api_key=key)
        self.model = model

    def complete(self, system: str, user: str) -> str:
        r = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return r.choices[0].message.content


def get_provider(name: str = "groq") -> LLMProvider:
    if name == "groq":
        return GroqProvider()
    elif name == "openai":
        return OpenAIProvider()
    raise ValueError(f"Provider tidak dikenal: {name}")


# ---- Context builder ----

def _build_context(symbol: str, relationship_type: str = "other",
                   organization_name: str = "perusahaan kami") -> dict:
    """
    Bangun konteks dari DB untuk symbol tertentu.
    Return dict yang siap di-serialize ke prompt.
    """
    conn = get_conn()
    try:
        company = conn.execute(
            "SELECT * FROM companies WHERE symbol = ?", [symbol]
        ).fetchone()
        if not company:
            return None

        signals = conn.execute("""
            SELECT period_label, signal_type, severity, metric,
                   current_value, previous_value, delta_pct
            FROM signals WHERE symbol = ?
            ORDER BY period_label DESC, severity
            LIMIT 10
        """, [symbol]).fetchall()

        snapshots = get_snapshots(conn, symbol, limit=8)

        return {
            "company": {
                "symbol": company["symbol"],
                "name": company["name"],
                "sector": company["sector"],
                "sub_sector": company["sub_sector"],
                "market_cap": company["market_cap"],
            },
            "relationship": relationship_type,
            "organization": organization_name,
            "signals": [dict(s) for s in signals],
            "snapshots": [
                {
                    "period": f"Q{s['quarter']}-{s['year']}",
                    "revenue": s["revenue"],
                    "earnings": s["earnings"],
                    "total_debt": s["total_debt"],
                    "operating_cash_flow": s["operating_cash_flow"],
                }
                for s in snapshots
            ],
        }
    finally:
        conn.close()


def _format_context_for_prompt(ctx: dict) -> str:
    """Ubah context jadi string yang enak dibaca LLM."""
    c = ctx["company"]
    lines = [
        f"Company: {c['name']} ({c['symbol']})",
        f"Sector: {c['sector']} / {c['sub_sector']}",
        f"Market cap: IDR {c['market_cap']:,}" if c["market_cap"] else "",
        f"Relationship ke {ctx['organization']}: {ctx['relationship']}",
        "",
        "Recent financial snapshots (kuartal terbaru dulu):",
    ]
    for s in ctx["snapshots"][:6]:
        lines.append(
            f"  {s['period']}: revenue={s['revenue']:,} "
            f"earnings={s['earnings']:,} "
            f"debt={s['total_debt']:,}"
            if s["revenue"] else f"  {s['period']}: (data tidak lengkap)"
        )

    lines.append("")
    lines.append("Detected signals:")
    for s in ctx["signals"]:
        delta = f"{s['delta_pct']:+.1f}%" if s["delta_pct"] is not None else "n/a"
        lines.append(
            f"  [{s['severity']}] {s['period_label']} {s['signal_type']} ({delta})"
        )

    return "\n".join(l for l in lines if l is not None)


# ---- Prompt templates ----

SYSTEM_PROMPT = """You are a financial analyst assistant for a company intelligence platform.

Your job: explain financial signals in plain language for a business executive (CEO/CFO level).

Rules:
- Be concise. 3-4 sentences max for summary, then bullet points if needed.
- Focus on WHAT changed and WHY it matters given the relationship (competitor/supplier/customer).
- Use numbers when relevant (e.g. "revenue turun 18% YoY").
- DO NOT hallucinate numbers not in the data.
- DO NOT predict the future. Use phrases like "indicating", "suggests", "potential".
- If relationship is "supplier", emphasize supply-chain risk.
- If relationship is "competitor", emphasize competitive dynamics.
- If relationship is "customer", emphasize demand/credit risk.
- Write in Indonesian, mix with English financial terms naturally.
"""


def explain(symbol: str, relationship_type: str = "other",
            organization_name: str = "perusahaan kami",
            provider: str = "groq") -> str:
    """
    Return narasi natural-language tentang signal perusahaan ini.
    """
    ctx = _build_context(symbol, relationship_type, organization_name)
    if ctx is None:
        return f"  ✗ {symbol} tidak ada di DB"

    user_prompt = f"""Berikut data tentang {symbol}:

{_format_context_for_prompt(ctx)}

Buat penjelasan singkat (3-4 kalimat) yang menjawab:
1. Apa yang berubah secara finansial?
2. Kenapa ini penting untuk kami sebagai {relationship_type}?
3. Apakah ada pola yang mengkhawatirkan?

Jangan ulangi semua angka. Fokus pada insight.
"""

    llm = get_provider(provider)
    return llm.complete(SYSTEM_PROMPT, user_prompt)

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
    """..."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "⚠ **GROQ_API_KEY belum diset.**"

    try:
        from groq import Groq
    except ImportError:
        return "⚠ Package `groq` belum diinstall. Jalankan: `pip install groq`"

    client = Groq(api_key=api_key)

    gen_clean = (interpretation_general or "").replace("**", "")
    rel_clean = (interpretation_relative or "").replace("**", "")

    # Handle delta_pct None
    if signal.get("delta_pct") is None:
        delta_str = "n/a (basis negatif)"
    else:
        delta_str = f"{signal['delta_pct']:+.1f}%"

    prompt = f"""Kamu adalah analis bisnis. Jelaskan signal berikut secara singkat, jelas, dan actionable.
        PERUSAHAAN: {symbol}
        SIGNAL: {signal['signal_type']}
        PERIODE: {signal['period_label']}
        DELTA: {delta_str}
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
            model="openai/gpt-oss-120b",
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

# ---- CLI ----

def main():
    if len(sys.argv) < 2:
        print("Usage: python ai_explain.py <SYMBOL> [relationship] [provider]")
        print("  relationship: competitor | supplier | customer | other")
        print("  provider:     groq | openai")
        sys.exit(1)

    symbol = sys.argv[1].upper()
    relationship = sys.argv[2] if len(sys.argv) > 2 else "other"
    provider = sys.argv[3] if len(sys.argv) > 3 else "groq"

    print(f"\n{'=' * 70}")
    print(f"  AI EXPLANATION: {symbol} (as {relationship})")
    print(f"{'=' * 70}\n")

    try:
        result = explain(symbol, relationship, provider=provider)
        print(result)
    except Exception as e:
        print(f"  ✗ Error: {e}")

    print()


if __name__ == "__main__":
    main()