import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import importlib.util
import streamlit as st
import pandas as pd

from interpretation import interpret_general, interpret_relative, explain_with_groq


# DATA LOADER
USE_DUMMY = True


def _load_dummy_data():
    """Load dummy_data.py without requiring a rename of the original file."""
    path = ROOT / "dummy_data.py"
    spec = importlib.util.spec_from_file_location("dummy_data", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Tidak dapat membaca {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_data():
    if USE_DUMMY:
        dummy = _load_dummy_data()
        return {
            "companies": dummy.DUMMY_COMPANIES,
            "signals": dummy.DUMMY_SIGNALS,
            "orgs": dummy.DUMMY_ORGS,
            "relationships": dummy.DUMMY_RELATIONSHIPS,
        }

    from core.db import get_conn

    conn = get_conn()
    try:
        return {
            "companies": [dict(r) for r in conn.execute("SELECT * FROM companies").fetchall()],
            "signals": [dict(r) for r in conn.execute("SELECT * FROM signals").fetchall()],
            "orgs": [dict(r) for r in conn.execute("SELECT * FROM organizations").fetchall()],
            "relationships": [dict(r) for r in conn.execute("SELECT * FROM relationships").fetchall()],
        }
    finally:
        conn.close()

# PAGE 
st.set_page_config(
    page_title="Rivalytics",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        #MainMenu, footer {visibility: hidden;}
        header {visibility: hidden;}

        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1500px;
        }

        [data-testid="stSidebar"] {
            border-right: 1px solid rgba(128,128,128,.18);
        }

        .brand {
            font-size: 1.55rem;
            font-weight: 800;
            letter-spacing: -.03em;
            margin-bottom: .15rem;
        }
        .brand-sub {
            color: #8a8f98;
            font-size: .82rem;
            margin-bottom: 1.3rem;
        }

        .hero {
            padding: 1.55rem 1.7rem;
            border: 1px solid rgba(128,128,128,.18);
            border-radius: 18px;
            background: linear-gradient(135deg, rgba(80,100,180,.10), rgba(80,100,180,.025));
            margin-bottom: 1.2rem;
        }
        .hero h1 { margin: 0 0 .35rem 0; font-size: 2rem; }
        .hero p { margin: 0; color: #8a8f98; }

        .section-title {
            font-size: 1.08rem;
            font-weight: 750;
            margin: .7rem 0 .65rem 0;
        }

        .signal-card {
            padding: 1rem 1.05rem;
            border: 1px solid rgba(128,128,128,.17);
            border-radius: 14px;
            margin-bottom: .7rem;
            background: rgba(128,128,128,.035);
        }
        .signal-name { font-weight: 700; }
        .signal-meta { color: #8a8f98; font-size: .82rem; }

        .small-muted { color: #8a8f98; font-size: .82rem; }

        div[data-testid="stMetric"] {
            border: 1px solid rgba(128,128,128,.17);
            padding: .85rem 1rem;
            border-radius: 14px;
            background: rgba(128,128,128,.035);
        }

        .empty-state {
            padding: 2rem;
            text-align: center;
            border: 1px dashed rgba(128,128,128,.3);
            border-radius: 14px;
            color: #8a8f98;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


data = load_data()
companies = data["companies"]
signals = data["signals"]
orgs = data["orgs"]
relationships = data["relationships"]

company_by_symbol = {c["symbol"]: c for c in companies}


def signal_label(value):
    return str(value).replace("_", " ").title()


def severity_icon(value):
    return {"attention": "🔴", "watch": "🟡", "info": "🔵"}.get(value, "⚪")


def format_delta(value):
    return "n/a" if value is None else f"{value:+.1f}%"


# SIDEBAR NAVIGATION
with st.sidebar:
    st.markdown('<div class="brand">◈ Rivalytics</div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">Competitive intelligence dashboard</div>', unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        ["Dashboard", "Companies", "Signals", "Organizations", "Interpretation"],
        label_visibility="collapsed",
    )

    st.divider()
    st.caption("DATA STATUS")
    if USE_DUMMY:
        st.warning("Dummy data aktif")
    else:
        st.success("Database aktif")

    st.caption(f"{len(companies)} companies · {len(signals)} signals · {len(orgs)} organizations")

# DASHBOARD
if page == "Dashboard":
    st.markdown(
        '<div class="hero"><h1>Competitive Intelligence</h1>'
        '<p>Pantau perubahan perusahaan, sinyal risiko, dan posisi relatif terhadap kompetitor.</p></div>',
        unsafe_allow_html=True,
    )

    attention = sum(s.get("severity") == "attention" for s in signals)
    watch = sum(s.get("severity") == "watch" for s in signals)
    info = sum(s.get("severity") == "info" for s in signals)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Companies", len(companies))
    c2.metric("Total Signals", len(signals))
    c3.metric("Attention", attention)
    c4.metric("Watch", watch)

    st.markdown('<div class="section-title">Signal overview</div>', unsafe_allow_html=True)
    left, right = st.columns([1.15, 1])

    with left:
        severity_df = pd.DataFrame({
            "Severity": ["Attention", "Watch", "Info"],
            "Count": [attention, watch, info],
        })
        st.bar_chart(severity_df.set_index("Severity"))

    with right:
        type_counts = (
            pd.Series([signal_label(s["signal_type"]) for s in signals])
            .value_counts()
            .rename_axis("Signal")
            .reset_index(name="Count")
        )
        st.dataframe(type_counts, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title">Companies requiring attention</div>', unsafe_allow_html=True)
    rows = []
    for c in companies:
        company_signals = [s for s in signals if s["symbol"] == c["symbol"]]
        att = sum(s["severity"] == "attention" for s in company_signals)
        watch_count = sum(s["severity"] == "watch" for s in company_signals)
        rows.append({
            "Symbol": c["symbol"],
            "Company": c["name"],
            "Sector": c["sector"],
            "Attention": att,
            "Watch": watch_count,
            "Signals": len(company_signals),
        })

    top_df = pd.DataFrame(rows).sort_values(
        ["Attention", "Watch", "Signals"], ascending=False
    )
    st.dataframe(top_df, use_container_width=True, hide_index=True)


# COMPANIES
elif page == "Companies":
    st.markdown('<div class="hero"><h1>Companies</h1><p>Daftar perusahaan yang tersedia di Rivalytics.</p></div>', unsafe_allow_html=True)

    search = st.text_input("Search company", placeholder="Cari nama atau symbol...")
    sector_options = ["All"] + sorted({c["sector"] for c in companies})
    sector = st.selectbox("Sector", sector_options)

    df = pd.DataFrame(companies)
    if search:
        q = search.lower()
        df = df[df["symbol"].str.lower().str.contains(q) | df["name"].str.lower().str.contains(q)]
    if sector != "All":
        df = df[df["sector"] == sector]

    st.caption(f"Menampilkan {len(df)} dari {len(companies)} perusahaan")
    st.dataframe(df, use_container_width=True, hide_index=True)


# SIGNALS
elif page == "Signals":
    st.markdown('<div class="hero"><h1>Signals</h1><p>Temukan perubahan yang membutuhkan perhatian lebih lanjut.</p></div>', unsafe_allow_html=True)

    df = pd.DataFrame(signals)
    all_severity = ["attention", "watch", "info"]
    all_types = sorted(df["signal_type"].dropna().unique())
    all_periods = sorted(df["period_label"].dropna().unique(), reverse=True)

    f1, f2, f3 = st.columns(3)
    severity = f1.multiselect("Severity", all_severity, default=all_severity)
    types = f2.multiselect("Signal type", all_types, default=all_types, format_func=signal_label)
    periods = f3.multiselect("Period", all_periods, default=all_periods)

    filtered = df[
        df["severity"].isin(severity)
        & df["signal_type"].isin(types)
        & df["period_label"].isin(periods)
    ].copy()

    filtered["Signal"] = filtered["signal_type"].map(signal_label)
    filtered["Delta"] = filtered["delta_pct"].map(format_delta)
    filtered["Severity"] = filtered["severity"].map(lambda x: f"{severity_icon(x)} {x.title()}")

    st.caption(f"{len(filtered)} signal ditemukan")
    st.dataframe(
        filtered[["symbol", "period_label", "Signal", "Severity", "Delta"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "symbol": "Symbol",
            "period_label": "Period",
            "Signal": "Signal Type",
            "Severity": "Severity",
            "Delta": "YoY Delta",
        },
    )

# ORGANIZATIONS
elif page == "Organizations":
    st.markdown('<div class="hero"><h1>Organizations</h1><p>Perusahaan pengguna dan hubungan kompetitifnya.</p></div>', unsafe_allow_html=True)

    if not orgs:
        st.markdown('<div class="empty-state">Belum ada organization.</div>', unsafe_allow_html=True)
    else:
        org_names = [o["name"] for o in orgs]
        selected_name = st.selectbox("Organization", org_names)
        org = next(o for o in orgs if o["name"] == selected_name)

        c1, c2, c3 = st.columns(3)
        c1.metric("Size tier", org.get("size_tier", "n/a").title())
        c2.metric("Sector", org.get("sector_slug", "n/a"))
        c3.metric("Subsector", org.get("subsector_slug", "n/a"))

        st.info(org.get("description", "Tidak ada deskripsi."))

        org_rel = [r for r in relationships if r["organization_id"] == org["id"]]
        st.markdown('<div class="section-title">Relationships</div>', unsafe_allow_html=True)
        if org_rel:
            rel_df = pd.DataFrame(org_rel)
            st.dataframe(
                rel_df[["company_symbol", "company_name", "relationship_type", "priority"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "company_symbol": "Symbol",
                    "company_name": "Company",
                    "relationship_type": "Relationship",
                    "priority": "Priority",
                },
            )
        else:
            st.markdown('<div class="empty-state">Belum ada relationship.</div>', unsafe_allow_html=True)


# INTERPRETATION
elif page == "Interpretation":
    st.markdown('<div class="hero"><h1>Signal Interpretation</h1><p>Bandingkan sebuah signal terhadap peer dan perusahaan kamu.</p></div>', unsafe_allow_html=True)

    if not signals:
        st.markdown('<div class="empty-state">Belum ada signal untuk diinterpretasikan.</div>', unsafe_allow_html=True)
        st.stop()

    all_symbols = sorted({s["symbol"] for s in signals})
    symbol = st.selectbox(
        "Company",
        all_symbols,
        format_func=lambda x: f"{x} — {company_by_symbol.get(x, {}).get('name', '')}",
    )

    company_signals = [s for s in signals if s["symbol"] == symbol]
    periods = sorted({s["period_label"] for s in company_signals}, reverse=True)
    period = st.selectbox("Period", periods)

    period_signals = [s for s in company_signals if s["period_label"] == period]
    types = sorted({s["signal_type"] for s in period_signals})
    sig_type = st.selectbox("Signal type", types, format_func=signal_label)
    signal = next(s for s in period_signals if s["signal_type"] == sig_type)

    st.divider()

    company = company_by_symbol.get(symbol, {})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Company", symbol)
    m2.metric("Period", signal["period_label"])
    m3.metric("YoY Delta", format_delta(signal.get("delta_pct")))
    m4.metric("Severity", f"{severity_icon(signal['severity'])} {signal['severity'].title()}")

    st.markdown(
        f"**{company.get('name', symbol)}** · {company.get('sector', 'n/a')} · "
        f"{company.get('sub_sector', 'n/a')} · **{signal_label(sig_type)}**"
    )

    st.divider()

    user_options = ["Tidak dibandingkan"] + [
        s for s in all_symbols if s != symbol
    ]
    user_symbol = st.selectbox(
        "Perusahaan pembanding kamu",
        user_options,
        format_func=lambda x: x if x == "Tidak dibandingkan" else f"{x} — {company_by_symbol.get(x, {}).get('name', '')}",
    )
    user_symbol = None if user_symbol == "Tidak dibandingkan" else user_symbol

    general = interpret_general(symbol, signal, companies, signals)
    relative = interpret_relative(symbol, signal, user_symbol, signals)

    st.divider()
    a, b = st.columns(2)
    with a:
        st.markdown("### 🌐 General interpretation")
        st.caption("Perbandingan dengan peer dalam subsector yang sama")
        st.info(general)
    with b:
        st.markdown("### 🎯 Relative interpretation")
        st.caption("Perbandingan dengan perusahaan pilihan kamu")
        st.info(relative)

    st.divider()
    st.markdown("### 🔍 AI explanation")
    st.caption("Penjelasan tambahan menggunakan Groq jika API key tersedia.")

    if st.button("Explain signal", type="primary"):
        with st.spinner("Menganalisis signal..."):
            explanation = explain_with_groq(
                symbol,
                signal,
                general,
                relative,
                user_name=user_symbol or "perusahaan kamu",
            )
        st.markdown("#### Hasil analisis")
        st.write(explanation)
