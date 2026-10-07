"""
app.py — Rivalytics UI (Streamlit).

Letak: src/UI/app.py
ROOT = src/ (parent dari UI/)

Perbaikan:
- Notif toast saat nambah relasi
- Hapus symbol di Profile Report (useless)
- Settings page buat API keys (Sectors, Groq, OpenAI)
- Interpretation bandingin vs user sendiri (butuh CSV)
"""
import sys
import io
import os
import re
from pathlib import Path
from contextlib import redirect_stdout

# UI/ → parent = src/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load environment variables dari .env (di root project)
ENV_PATH = ROOT.parent / ".env"
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    pass

import streamlit as st
import pandas as pd

# ============================================================
# CORE IMPORTS
# ============================================================
from core.db import (
    get_conn,
    get_organization,
    get_relationships,
    add_relationship,
    remove_relationship,
)
from discovery.profile import (
    CompanyProfile,
    SizeTier,
    save_profile,
    get_profile,
    list_profiles,
    delete_profile,
)
from core.csv_import import import_csv, get_org_snapshots
from core.ai_explain import explain
from interpretation import (
    interpret_general,
    interpret_relative,
)


# ============================================================
# PAGE CONFIG + STYLE
# ============================================================
st.set_page_config(
    page_title="Rivalytics",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    #MainMenu, footer {visibility: hidden;}
    header[data-testid="stHeader"] {background: transparent;}
    .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1500px;}
    [data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.18);}
    .brand {font-size: 1.55rem; font-weight: 800; letter-spacing: -.03em; margin-bottom: .15rem;}
    .brand-sub {color: #8a8f98; font-size: .82rem; margin-bottom: 1.3rem;}
    .hero {
        padding: 1.55rem 1.7rem;
        border: 1px solid rgba(128,128,128,.18);
        border-radius: 18px;
        background: linear-gradient(135deg, rgba(80,100,180,.10), rgba(80,100,180,.025));
        margin-bottom: 1.2rem;
    }
    .hero h1 { margin: 0 0 .35rem 0; font-size: 2rem; }
    .hero p { margin: 0; color: #8a8f98; }
    .section-title {font-size: 1.08rem; font-weight: 750; margin: .7rem 0 .65rem 0;}
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
""", unsafe_allow_html=True)


# ============================================================
# HELPERS
# ============================================================
def run_and_capture(func, *args, **kwargs) -> str:
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            func(*args, **kwargs)
    except Exception as e:
        return f"⚠ Error: {e}"
    return buf.getvalue()


def load_all():
    conn = get_conn()
    try:
        companies = [dict(r) for r in conn.execute("SELECT * FROM companies").fetchall()]
        signals = [dict(r) for r in conn.execute("SELECT * FROM signals").fetchall()]
        orgs = [dict(r) for r in conn.execute("SELECT * FROM organizations").fetchall()]
        rels = [dict(r) for r in conn.execute("SELECT * FROM relationships").fetchall()]
    finally:
        conn.close()
    return companies, signals, orgs, rels


def signal_label(v):
    return str(v).replace("_", " ").title()


def severity_icon(v):
    return {"attention": "🔴", "watch": "🟡", "info": "🔵"}.get(v, "⚪")


def format_delta(v):
    return "n/a" if v is None else f"{v:+.1f}%"


def get_relationship_type(org_id: int, symbol: str):
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT relationship_type FROM relationships
            WHERE organization_id = ? AND company_symbol = ?
        """, [org_id, symbol]).fetchone()
        return row["relationship_type"] if row else None
    finally:
        conn.close()


def get_org_snapshots_for(org_id: int):
    """Ambil org_snapshots untuk 1 profile."""
    conn = get_conn()
    try:
        return get_org_snapshots(conn, org_id, limit=12)
    finally:
        conn.close()


def compute_user_delta(user_snapshots, metric, period_label):
    """Hitung YoY delta user's metric untuk period tertentu."""
    m = re.match(r"Q(\d)-(\d{4})", period_label)
    if not m:
        return None
    q, year = int(m.group(1)), int(m.group(2))
    prev_label = f"Q{q}-{year - 1}"

    current = next((s for s in user_snapshots if s["period_label"] == period_label), None)
    previous = next((s for s in user_snapshots if s["period_label"] == prev_label), None)

    if not current or not previous:
        return None

    cur_val = current.get(metric)
    prev_val = previous.get(metric)

    if cur_val is None or prev_val is None or prev_val == 0:
        return None
    if prev_val < 0:
        return None

    delta = (cur_val - prev_val) / abs(prev_val) * 100
    return round(delta, 2)


def save_env_var(key: str, value: str):
    """Simpen/update key di .env file & os.environ."""
    lines = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    lines = [l for l in lines if not l.startswith(f"{key}=")]
    if value:
        lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
    if value:
        os.environ[key] = value
    elif key in os.environ:
        del os.environ[key]


def get_env_var(key: str) -> str:
    return os.environ.get(key, "")


# ============================================================
# LOAD DATA
# ============================================================
companies, signals, orgs, relationships = load_all()
company_by_symbol = {c["symbol"]: c for c in companies}


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown('<div class="brand">◈ Rivalytics</div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">Competitive intelligence</div>', unsafe_allow_html=True)

    page = st.radio("Navigation", [
        "🏠 Dashboard",
        "🏢 Companies",
        "🔔 Signals",
        "🔗 Relationships",
        "📥 Ingest Data",
        "📄 CSV Import",
        "📊 Reports & AI",
        "🧠 Interpretation",
        "⚙️ Settings",
    ], label_visibility="collapsed")

    st.divider()
    st.caption(f"{len(companies)} companies · {len(signals)} signals · {len(orgs)} profiles")


# ============================================================
# 🏠 DASHBOARD
# ============================================================
if page == "🏠 Dashboard":
    st.markdown(
        '<div class="hero"><h1>Competitive Intelligence</h1>'
        '<p>Pantau perubahan, sinyal risiko, dan posisi relatif.</p></div>',
        unsafe_allow_html=True,
    )

    att = sum(1 for s in signals if s["severity"] == "attention")
    watch = sum(1 for s in signals if s["severity"] == "watch")
    info = sum(1 for s in signals if s["severity"] == "info")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Companies", len(companies))
    c2.metric("Total Signals", len(signals))
    c3.metric("Attention", att)
    c4.metric("Watch", watch)

    st.markdown('<div class="section-title">Signal overview</div>', unsafe_allow_html=True)

    left, right = st.columns([1.15, 1])
    with left:
        df = pd.DataFrame({
            "Severity": ["Attention", "Watch", "Info"],
            "Count": [att, watch, info],
        })
        st.bar_chart(df.set_index("Severity"))
    with right:
        if signals:
            types = pd.Series([signal_label(s["signal_type"]) for s in signals])
            type_counts = types.value_counts().rename_axis("Signal").reset_index(name="Count")
            st.dataframe(type_counts, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title">Companies requiring attention</div>', unsafe_allow_html=True)
    rows = []
    for c in companies:
        cs = [s for s in signals if s["symbol"] == c["symbol"]]
        rows.append({
            "Symbol": c["symbol"],
            "Company": c["name"],
            "Sector": c.get("sector", "-"),
            "Attention": sum(1 for s in cs if s["severity"] == "attention"),
            "Watch": sum(1 for s in cs if s["severity"] == "watch"),
            "Signals": len(cs),
        })
    if rows:
        top = pd.DataFrame(rows).sort_values(["Attention", "Watch", "Signals"], ascending=False)
        st.dataframe(top, use_container_width=True, hide_index=True)
    else:
        st.markdown('<div class="empty-state">Belum ada data.</div>', unsafe_allow_html=True)


# ============================================================
# 🏢 COMPANIES
# ============================================================
elif page == "🏢 Companies":
    st.markdown('<div class="hero"><h1>Companies & Profiles</h1><p>Kelola data perusahaan & profil user.</p></div>', unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs([
        "📋 List Companies",
        "🔍 Discovery",
        "👤 Profile Perusahaan",
    ])

    # ---------- TAB 1: LIST COMPANIES ----------
    with tab1:
        search = st.text_input("Search", placeholder="Nama atau symbol...")
        df = pd.DataFrame(companies) if companies else pd.DataFrame()
        if not df.empty:
            if search:
                q = search.lower()
                df = df[df["symbol"].str.lower().str.contains(q) | df["name"].str.lower().str.contains(q)]
            st.caption(f"{len(df)} dari {len(companies)} perusahaan")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption("💡 Mau lihat laporan detail perusahaan? Buka tab **📊 Reports & AI → Company Report**.")
        else:
            st.info("Belum ada perusahaan. Ingest data dulu di tab **Ingest Data**.")

    # ---------- TAB 2: DISCOVERY ----------
    with tab2:
        st.markdown("**Discovery** — cari kompetitor/supplier kandidat")
        try:
            from discovery.discovery import discover_competitors
            from core.taxonomy import load_or_fetch_taxonomy
            from core.sectors_client import SectorsClient

            c1, c2, c3 = st.columns(3)
            with c1:
                sub_slug = st.text_input("Subsector slug", value="food-beverage")
            with c2:
                tier = st.selectbox("Size tier", ["micro", "small", "medium", "large"], index=2)
            with c3:
                limit = st.number_input("Limit", min_value=1, max_value=50, value=8)

            if st.button("🔍 Discover Competitors", type="primary"):
                with st.spinner("Mencari..."):
                    try:
                        client = SectorsClient()
                        taxonomy = load_or_fetch_taxonomy(client)
                        profile = CompanyProfile(
                            name="User",
                            sector_slug="consumer-non-cyclicals",
                            subsector_slug=sub_slug,
                            size_tier=SizeTier(tier),
                        )
                        comps = discover_competitors(profile, client, taxonomy, limit=limit)
                        st.success(f"Ditemukan {len(comps)} kandidat")
                        if comps:
                            st.dataframe(pd.DataFrame(comps), use_container_width=True, hide_index=True)
                    except Exception as e:
                        st.error(f"Error: {e}")
        except ImportError as e:
            st.warning(f"Module belum ada: {e}")

    # ---------- TAB 3: PROFILE PERUSAHAAN ----------
    with tab3:
        st.markdown("**Profile Perusahaan** — kelola profil user")
        st.caption("Ini representasi perusahaan kamu — dipakai buat monitoring & report.")

        st.markdown("### 📋 Daftar Profile")
        if orgs:
            profile_df = pd.DataFrame(orgs)
            cols = ["id", "name", "sector_slug", "subsector_slug", "size_tier", "description"]
            cols = [c for c in cols if c in profile_df.columns]
            st.dataframe(
                profile_df[cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": "ID",
                    "name": "Nama",
                    "sector_slug": "Sector",
                    "subsector_slug": "Subsector",
                    "size_tier": "Tier",
                    "description": "Deskripsi",
                },
            )
        else:
            st.info("Belum ada profile. Bikin di bawah.")

        st.divider()

        st.markdown("### ➕ Bikin Profile Baru")

        with st.form("create_profile_form"):
            name = st.text_input("Nama perusahaan", placeholder="PT Contoh Pangan")
            c1, c2 = st.columns(2)
            with c1:
                sector = st.text_input("Sector slug", value="consumer-non-cyclicals")
                size = st.selectbox("Size tier", ["micro", "small", "medium", "large"], index=2)
            with c2:
                subsector = st.text_input("Subsector slug", value="food-beverage")
                ticker = st.text_input("Ticker (opsional)", placeholder="ICBP")

            desc = st.text_area(
                "Deskripsi (opsional)",
                height=80,
                placeholder="Perusahaan makanan ringan yang fokus pada...",
            )

            if st.form_submit_button("💾 Simpan Profile", type="primary"):
                if not name:
                    st.error("Nama wajib diisi")
                else:
                    profile = CompanyProfile(
                        name=name,
                        sector_slug=sector,
                        subsector_slug=subsector,
                        size_tier=SizeTier(size),
                        business_description=desc,
                        ticker=ticker or None,
                    )
                    conn = get_conn()
                    org_id = save_profile(conn, profile)
                    conn.close()
                    st.success(f"✓ Profile disimpan (id={org_id})")
                    st.rerun()

        if orgs:
            st.divider()
            st.markdown("### ✏️ Edit / Hapus Profile")

            org_options = {f"{o['name']} (id={o['id']})": o["id"] for o in orgs}
            selected = st.selectbox("Pilih profile", list(org_options.keys()), key="edit_profile_select")
            org_id = org_options[selected]

            conn = get_conn()
            profile = get_profile(conn, org_id)
            conn.close()

            if profile:
                with st.form("edit_profile_form"):
                    e_name = st.text_input("Nama", value=profile.name)
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        e_sector = st.text_input("Sector", value=profile.sector_slug)
                        tier_list = ["micro", "small", "medium", "large"]
                        e_size = st.selectbox(
                            "Size tier",
                            tier_list,
                            index=tier_list.index(profile.size_tier.value),
                        )
                    with ec2:
                        e_subsector = st.text_input("Subsector", value=profile.subsector_slug)
                        e_ticker = st.text_input("Ticker", value=profile.ticker or "")

                    e_desc = st.text_area("Deskripsi", value=profile.business_description, height=80)

                    col_a, col_b = st.columns([1, 1])

                    if col_a.form_submit_button("💾 Update", type="primary"):
                        updated = CompanyProfile(
                            id=org_id,
                            name=e_name,
                            sector_slug=e_sector,
                            subsector_slug=e_subsector,
                            size_tier=SizeTier(e_size),
                            business_description=e_desc,
                            ticker=e_ticker or None,
                        )
                        conn = get_conn()
                        save_profile(conn, updated)
                        conn.close()
                        st.success("✓ Profile diupdate")
                        st.rerun()

                    if col_b.form_submit_button("🗑️ Hapus"):
                        conn = get_conn()
                        ok = delete_profile(conn, org_id)
                        conn.close()
                        if ok:
                            st.success(f"✓ Profile {org_id} dihapus")
                            st.rerun()


# ============================================================
# 🔔 SIGNALS
# ============================================================
elif page == "🔔 Signals":
    st.markdown('<div class="hero"><h1>Signals</h1><p>Perubahan yang butuh perhatian.</p></div>', unsafe_allow_html=True)

    if not signals:
        st.markdown('<div class="empty-state">Belum ada signal.</div>', unsafe_allow_html=True)
    else:
        df = pd.DataFrame(signals)
        all_sev = ["attention", "watch", "info"]
        all_types = sorted(df["signal_type"].dropna().unique())

        f1, f2 = st.columns(2)
        sev = f1.multiselect("Severity", all_sev, default=all_sev)
        types = f2.multiselect("Signal type", all_types, default=all_types, format_func=signal_label)

        filtered = df[df["severity"].isin(sev) & df["signal_type"].isin(types)].copy()
        filtered["Signal"] = filtered["signal_type"].map(signal_label)
        filtered["Delta"] = filtered["delta_pct"].map(format_delta)
        filtered["Severity"] = filtered["severity"].map(lambda x: f"{severity_icon(x)} {x.title()}")

        st.caption(f"{len(filtered)} signal")
        st.dataframe(
            filtered[["symbol", "period_label", "Signal", "Severity", "Delta"]],
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# 🔗 RELATIONSHIPS
# ============================================================
elif page == "🔗 Relationships":
    st.markdown('<div class="hero"><h1>Relationships</h1><p>Kelola hubungan dengan monitored companies.</p></div>', unsafe_allow_html=True)

    if not orgs:
        st.warning("Belum ada profile perusahaan. Bikin dulu di **Companies → Profile Perusahaan**.")
    else:
        org_options = {f"{o['name']} (id={o['id']})": o["id"] for o in orgs}
        selected = st.selectbox("Pilih profile", list(org_options.keys()))
        org_id = org_options[selected]

        tab1, tab2, tab3 = st.tabs(["📋 Show", "➕ Add", "🗑️ Remove"])

        with tab1:
            conn = get_conn()
            rels = get_relationships(conn, org_id)
            conn.close()
            if rels:
                st.dataframe(pd.DataFrame(rels), use_container_width=True, hide_index=True)
            else:
                st.info("Belum ada relationship.")

        with tab2:
            with st.form("add_rel_form"):
                c1, c2, c3 = st.columns(3)
                symbol = c1.text_input("Symbol", placeholder="ICBP").upper()
                rel_type = c2.selectbox(
                    "Type",
                    ["competitor", "supplier", "customer", "distributor", "partner", "other"],
                )
                priority = c3.selectbox("Priority", ["high", "medium", "low"], index=1)

                if st.form_submit_button("Tambah", type="primary"):
                    if not symbol:
                        st.error("Symbol wajib diisi")
                    else:
                        conn = get_conn()
                        added = add_relationship(conn, org_id, symbol, rel_type, priority)
                        conn.close()
                        if added:
                            st.toast(f"✓ {symbol} → {rel_type} [{priority}] berhasil ditambahkan!", icon="✅")
                            st.success(f"✓ {symbol} → {rel_type} [{priority}]")
                            st.rerun()
                        else:
                            st.toast(f"⚠ {symbol} sudah ada", icon="⚠️")
                            st.warning(f"⚠ {symbol} sudah ada (skip)")

        with tab3:
            conn = get_conn()
            rels = get_relationships(conn, org_id)
            conn.close()
            if rels:
                to_remove = st.selectbox("Pilih yang dihapus", [r["company_symbol"] for r in rels])
                if st.button("🗑️ Hapus", type="primary"):
                    conn = get_conn()
                    ok = remove_relationship(conn, org_id, to_remove)
                    conn.close()
                    if ok:
                        st.toast(f"✓ {to_remove} dihapus", icon="🗑️")
                        st.success(f"✓ {to_remove} dihapus")
                        st.rerun()
            else:
                st.info("Belum ada relationship.")


# ============================================================
# 📥 INGEST DATA
# ============================================================
elif page == "📥 Ingest Data":
    st.markdown('<div class="hero"><h1>Ingest Data</h1><p>Ambil data dari Sectors API.</p></div>', unsafe_allow_html=True)

    # Cek Sectors API key
    if not get_env_var("SECTORS_API_KEY"):
        st.warning("⚠ SECTORS_API_KEY belum diset. Buka **⚙️ Settings** dulu.")

    try:
        from monitoring.ingest import Ingestor

        c1, c2 = st.columns([2, 1])
        with c1:
            symbols_input = st.text_area(
                "Symbols (1 per baris atau dipisah koma)",
                placeholder="BBCA\nBBRI\nADRO",
                height=120,
            )
        with c2:
            n_quarters = st.number_input("Jumlah kuartal", min_value=1, max_value=12, value=8)

        if st.button("🚀 Ingest", type="primary"):
            symbols = [s.strip().upper() for s in symbols_input.replace(",", "\n").split("\n") if s.strip()]
            if not symbols:
                st.error("Masukin minimal 1 symbol")
            else:
                progress = st.progress(0)
                results = []
                try:
                    ing = Ingestor()
                    for i, sym in enumerate(symbols):
                        try:
                            result = ing.ingest_smart(sym)
                            results.append({"symbol": sym, "status": "✓", "detail": str(result)})
                        except Exception as e:
                            results.append({"symbol": sym, "status": "✗", "detail": str(e)})
                        progress.progress((i + 1) / len(symbols))
                    st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(f"Error: {e}")
    except ImportError as e:
        st.warning(f"Module `ingest` belum tersedia: {e}")


# ============================================================
# 📄 CSV IMPORT
# ============================================================
elif page == "📄 CSV Import":
    st.markdown('<div class="hero"><h1>CSV Import</h1><p>Upload data finansial user (per profile).</p></div>', unsafe_allow_html=True)

    if not orgs:
        st.warning("Belum ada profile perusahaan. Bikin dulu di **Companies → Profile Perusahaan**.")
    else:
        org_options = {f"{o['name']} (id={o['id']})": o["id"] for o in orgs}
        selected = st.selectbox("Profile", list(org_options.keys()))
        org_id = org_options[selected]

        st.markdown("**Format CSV:** `period,revenue,earnings,total_debt,operating_cash_flow`")
        st.code(
            "period,revenue,earnings,total_debt,operating_cash_flow\n"
            "Q1-2025,50000000000,5000000000,10000000000,3000000000",
            language="csv",
        )

        uploaded = st.file_uploader("Upload CSV", type=["csv"])
        if uploaded is not None:
            tmp = Path("temp_upload.csv")
            tmp.write_bytes(uploaded.getvalue())

            if st.button("📥 Import", type="primary"):
                try:
                    result = import_csv(org_id, str(tmp))
                    st.toast(f"✓ {result['inserted']} inserted, {result['updated']} updated", icon="✅")
                    st.success(f"✓ {result['inserted']} inserted, {result['updated']} updated")
                    if result["errors"]:
                        st.warning(f"⚠ {len(result['errors'])} error(s)")
                        for e in result["errors"][:10]:
                            st.text(e)
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    tmp.unlink(missing_ok=True)


# ============================================================
# 📊 REPORTS & AI
# ============================================================
elif page == "📊 Reports & AI":
    st.markdown(
        '<div class="hero"><h1>Reports & AI</h1>'
        '<p>Ringkasan, laporan detail, dan narasi AI dalam satu tempat.</p></div>',
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Summary",
        "🏢 Company Report",
        "👤 Profile Report",
        "🤖 AI Explain",
    ])

    # ---------- TAB 1: SUMMARY ----------
    with tab1:
        st.markdown("**Ringkasan umum** — overview semua perusahaan yang dimonitor")
        if st.button("📈 Load Summary", type="primary", key="btn_summary"):
            from core.report import summary
            st.code(run_and_capture(summary), language="text")

    # ---------- TAB 2: COMPANY REPORT ----------
    with tab2:
        st.markdown("**Company Report** — detail 1 perusahaan")
        if not companies:
            st.info("Belum ada perusahaan.")
        else:
            symbol = st.selectbox(
                "Company",
                [c["symbol"] for c in companies],
                key="report_sym",
                format_func=lambda x: f"{x} — {company_by_symbol.get(x, {}).get('name', '')}",
            )
            if st.button("📊 Load Company Report", type="primary", key="btn_company"):
                from core.report import company_detail
                st.code(run_and_capture(company_detail, symbol), language="text")

    # ---------- TAB 3: PROFILE REPORT ----------
    with tab3:
        st.markdown("**Profile Report** — laporan per profil")
        if not orgs:
            st.info("Belum ada profile perusahaan.")
        else:
            org_options = {f"{o['name']} (id={o['id']})": o["id"] for o in orgs}
            selected = st.selectbox("Profile", list(org_options.keys()), key="report_org")
            org_id = org_options[selected]

            if st.button("👤 Load Profile Report", type="primary", key="btn_org"):
                from core.report_org import org_dashboard
                st.code(run_and_capture(org_dashboard, org_id), language="text")

    # ---------- TAB 4: AI EXPLAIN ----------
    with tab4:
        st.markdown("**AI Explain** — generate narasi via LLM")
        st.caption("Relationship diambil otomatis dari database. Buat kelola relationship, buka tab **🔗 Relationships**.")

        # Cek Groq API key
        if not get_env_var("GROQ_API_KEY") and not get_env_var("OPENAI_API_KEY"):
            st.warning("⚠ API key belum diset. Buka **⚙️ Settings** dulu.")

        if not companies:
            st.info("Belum ada perusahaan.")
        elif not orgs:
            st.info("Belum ada profile perusahaan.")
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                org_options = {f"{o['name']} (id={o['id']})": o["id"] for o in orgs}
                selected_org = st.selectbox("Profile", list(org_options.keys()), key="ai_org")
                org_id = org_options[selected_org]
            with c2:
                symbol = st.selectbox(
                    "Company",
                    [c["symbol"] for c in companies],
                    key="ai_sym",
                    format_func=lambda x: f"{x} — {company_by_symbol.get(x, {}).get('name', '')}",
                )
            with c3:
                provider = st.selectbox("Provider", ["groq", "openai"], key="ai_provider")

            rel_type = get_relationship_type(org_id, symbol)
            if rel_type:
                st.info(f"🔗 Relationship: **{rel_type}**")
            else:
                st.warning(f"⚠ {symbol} belum ada di relationship untuk profile ini. Pakai default: **other**")
                rel_type = "other"

            if st.button("🤖 Generate Explanation", type="primary", key="btn_ai"):
                with st.spinner("Menghubungi LLM..."):
                    try:
                        result = explain(symbol, relationship_type=rel_type, provider=provider)
                        st.markdown("### Hasil")
                        st.markdown(result)
                    except Exception as e:
                        st.error(f"Error: {e}")


# ============================================================
# 🧠 INTERPRETATION
# ============================================================
elif page == "🧠 Interpretation":
    st.markdown('<div class="hero"><h1>Interpretation</h1><p>Bandingkan signal target vs peer & vs perusahaan kamu.</p></div>', unsafe_allow_html=True)

    if not signals:
        st.info("Belum ada signal.")
    elif not orgs:
        st.warning("Belum ada profile perusahaan. Bikin dulu di **Companies → Profile Perusahaan**.")
    else:
        # Step 1: pilih profile (user)
        st.markdown("### 1️⃣ Pilih Profile (Perusahaan Kamu)")
        org_options = {f"{o['name']} (id={o['id']})": o["id"] for o in orgs}
        selected_org = st.selectbox("Profile", list(org_options.keys()), key="interp_org")
        org_id = org_options[selected_org]

        # Cek apakah user punya CSV data
        user_snapshots = get_org_snapshots_for(org_id)
        has_csv = len(user_snapshots) > 0

        if not has_csv:
            st.error("⚠ **Belum ada data CSV** untuk profile ini. Upload dulu di tab **📄 CSV Import** biar bisa bandingin.")
            st.stop()
        else:
            st.success(f"✓ Data CSV tersedia: **{len(user_snapshots)} kuartal**")

        st.divider()

        # Step 2: pilih target company + signal
        st.markdown("### 2️⃣ Pilih Target Company")
        all_symbols = sorted({s["symbol"] for s in signals})

        c1, c2 = st.columns(2)
        with c1:
            symbol = st.selectbox(
                "Company",
                all_symbols,
                key="interp_sym",
                format_func=lambda x: f"{x} — {company_by_symbol.get(x, {}).get('name', '')}",
            )
        with c2:
            company_signals = [s for s in signals if s["symbol"] == symbol]
            periods = sorted({s["period_label"] for s in company_signals}, reverse=True)
            period = st.selectbox("Period", periods, key="interp_period")

        period_signals = [s for s in company_signals if s["period_label"] == period]
        types = sorted({s["signal_type"] for s in period_signals})
        sig_type = st.selectbox("Signal type", types, format_func=signal_label, key="interp_sig")
        signal = next(s for s in period_signals if s["signal_type"] == sig_type)

        st.divider()

        # Info signal
        company = company_by_symbol.get(symbol, {})
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Company", symbol)
        m2.metric("Period", signal["period_label"])
        m3.metric("YoY Delta", format_delta(signal.get("delta_pct")))
        m4.metric("Severity", f"{severity_icon(signal['severity'])} {signal['severity'].title()}")

        st.markdown(f"**{company.get('name', symbol)}** · {company.get('sector', 'n/a')} · {signal_label(sig_type)}")

        st.divider()

        # Interpretasi
        st.markdown("### 3️⃣ Hasil Interpretasi")

        # General — vs peer
        general = interpret_general(symbol, signal, companies, signals)

        # Relative — vs user's OWN data (dari CSV)
        user_delta = compute_user_delta(user_snapshots, signal["metric"], signal["period_label"])

        if user_delta is None:
            relative = (
                f"⚠ **Data kamu tidak cukup** untuk dibandingkan.\n\n"
                f"Signal: **{signal['signal_type']}** ({format_delta(signal['delta_pct'])}) "
                f"di periode **{signal['period_label']}**.\n\n"
                f"Kamu perlu data kuartal **{signal['period_label']}** dan "
                f"**{signal['period_label'].split('-')[0]}{int(signal['period_label'].split('-')[1]) - 1}** "
                f"untuk perbandingan YoY."
            )
        else:
            diff = signal["delta_pct"] - user_delta
            if signal["signal_type"] in ("revenue_deterioration", "profit_deterioration", "cash_flow_weakness"):
                if diff < -10:
                    verdict = f"{symbol} **jauh lebih buruk** dari kamu. Ini **peluang** ambil market share."
                elif diff > 10:
                    verdict = f"{symbol} **lebih baik** dari kamu. Waspada."
                else:
                    verdict = f"{symbol} sejalan dengan kamu."
            else:
                verdict = f"{symbol} berbeda dari kamu."

            relative = (
                f"**{symbol}**: **{signal['delta_pct']:+.1f}%** YoY ({signal['metric']})\n\n"
                f"**Kamu** ({selected_org}): **{user_delta:+.1f}%** YoY (metric yang sama)\n\n"
                f"→ {verdict}"
            )

        a, b = st.columns(2)
        with a:
            st.markdown("### 🌐 vs Peer")
            st.caption("Bandingin dengan rata-rata peer di subsector yang sama")
            st.info(general)
        with b:
            st.markdown("### 🎯 vs Kamu")
            st.caption("Bandingin dengan data finansial kamu sendiri (dari CSV)")
            st.info(relative)


# ============================================================
# ⚙️ SETTINGS
# ============================================================
elif page == "⚙️ Settings":
    st.markdown('<div class="hero"><h1>Settings</h1><p>Atur API keys untuk Sectors & LLM provider.</p></div>', unsafe_allow_html=True)

    st.info(f"📍 Settings disimpan di: `{ENV_PATH}`")

    # Sectors
    st.markdown("### 🌐 Sectors API")
    st.caption("Dibutuhin buat ingest data perusahaan & discovery.")

    sectors_current = get_env_var("SECTORS_API_KEY")
    sectors_status = "✅ Ada" if sectors_current else "❌ Belum diset"
    st.markdown(f"**Status:** {sectors_status}")

    with st.form("sectors_form"):
        sectors_key = st.text_input(
            "Sectors API Key",
            value=sectors_current,
            type="password",
            placeholder="240d3ca6...",
        )
        col_a, col_b = st.columns([1, 1])
        if col_a.form_submit_button("💾 Simpan Sectors Key", type="primary"):
            save_env_var("SECTORS_API_KEY", sectors_key.strip())
            st.toast("✓ Sectors API Key disimpan", icon="✅")
            st.success("✓ Sectors API Key disimpan")
            st.rerun()
        if col_b.form_submit_button("🗑️ Hapus"):
            save_env_var("SECTORS_API_KEY", "")
            st.toast("✓ Sectors API Key dihapus", icon="🗑️")
            st.success("✓ Sectors API Key dihapus")
            st.rerun()

    st.divider()

    # Groq
    st.markdown("### 🤖 Groq API")
    st.caption("Dibutuhin buat AI explanation (gratis, cepat).")
    st.markdown("🔗 Daftar: [console.groq.com](https://console.groq.com/keys)")

    groq_current = get_env_var("GROQ_API_KEY")
    groq_status = "✅ Ada" if groq_current else "❌ Belum diset"
    st.markdown(f"**Status:** {groq_status}")

    with st.form("groq_form"):
        groq_key = st.text_input(
            "Groq API Key",
            value=groq_current,
            type="password",
            placeholder="gsk_...",
        )
        col_a, col_b = st.columns([1, 1])
        if col_a.form_submit_button("💾 Simpan Groq Key", type="primary"):
            save_env_var("GROQ_API_KEY", groq_key.strip())
            st.toast("✓ Groq API Key disimpan", icon="✅")
            st.success("✓ Groq API Key disimpan")
            st.rerun()
        if col_b.form_submit_button("🗑️ Hapus"):
            save_env_var("GROQ_API_KEY", "")
            st.toast("✓ Groq API Key dihapus", icon="🗑️")
            st.success("✓ Groq API Key dihapus")
            st.rerun()

    st.divider()

    # OpenAI
    st.markdown("### 🧠 OpenAI API (Opsional)")
    st.caption("Alternatif Groq. Bisa dipakai buat AI explanation.")
    st.markdown("🔗 Daftar: [platform.openai.com](https://platform.openai.com/api-keys)")

    openai_current = get_env_var("OPENAI_API_KEY")
    openai_status = "✅ Ada" if openai_current else "❌ Belum diset"
    st.markdown(f"**Status:** {openai_status}")

    with st.form("openai_form"):
        openai_key = st.text_input(
            "OpenAI API Key",
            value=openai_current,
            type="password",
            placeholder="sk-...",
        )
        col_a, col_b = st.columns([1, 1])
        if col_a.form_submit_button("💾 Simpan OpenAI Key", type="primary"):
            save_env_var("OPENAI_API_KEY", openai_key.strip())
            st.toast("✓ OpenAI API Key disimpan", icon="✅")
            st.success("✓ OpenAI API Key disimpan")
            st.rerun()
        if col_b.form_submit_button("🗑️ Hapus"):
            save_env_var("OPENAI_API_KEY", "")
            st.toast("✓ OpenAI API Key dihapus", icon="🗑️")
            st.success("✓ OpenAI API Key dihapus")
            st.rerun()

    st.divider()
    st.markdown("### 📋 Status Semua Keys")
    status_df = pd.DataFrame([
        {"Key": "SECTORS_API_KEY", "Status": "✅ Ada" if get_env_var("SECTORS_API_KEY") else "❌ Belum"},
        {"Key": "GROQ_API_KEY", "Status": "✅ Ada" if get_env_var("GROQ_API_KEY") else "❌ Belum"},
        {"Key": "OPENAI_API_KEY", "Status": "✅ Ada" if get_env_var("OPENAI_API_KEY") else "❌ Belum"},
    ])
    st.dataframe(status_df, use_container_width=True, hide_index=True)