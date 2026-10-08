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
import base64
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


# ilangin tombol 'deploy' (https://discuss.streamlit.io/t/how-to-hide-or-remove-the-deploy-button-that-appears-at-the-top-right-corner-of-the-streamlit-app/55325)
st.markdown(
    r"""
    <style>
    /* Untuk Streamlit versi baru (v1.40+) */
    .stAppDeployButton {
        display: none;
    }
    /* Sebagai fallback untuk versi lama */
    .stDeployButton {
        display: none;
    }
    </style>
    """, unsafe_allow_html=True
)

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
from core.context_interpreter import interpret_general, interpret_relative
from monitoring.weekly import (
    check_updates,
    ingest_selected,
    get_pending_summary,
    get_monitored_symbols,
    should_check_now,
)

# ============================================================
# PAGE CONFIG + STYLE
# ============================================================
st.set_page_config(
    page_title="Rivalytics",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    #MainMenu, footer {visibility: hidden;}
    header[data-testid="stHeader"] {background: transparent;}
    .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1500px;}
    [data-testid="stSidebar"] [data-testid="stImage"] {
        margin: 0 !important;
        padding: 0 !important;
    }

    [data-testid="stSidebar"] img {
        display: block;
        margin: 0 !important;
        padding: 0 !important;
    }
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
def load_logo_base64(path: Path) -> str:
    """Load logo sebagai base64 string untuk embed di HTML."""
    if not path.exists():
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

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

def _fmt_rupiah(v):
    """Format angka ringkas: 4.4 T, 450 M, dll."""
    if v is None:
        return "-"
    try:
        v = float(v)
    except (ValueError, TypeError):
        return "-"
    if abs(v) >= 1_000_000_000_000:
        return f"Rp {v/1_000_000_000_000:.2f} T"
    if abs(v) >= 1_000_000_000:
        return f"Rp {v/1_000_000_000:.2f} M"
    if abs(v) >= 1_000_000:
        return f"Rp {v/1_000_000:.2f} jt"
    return f"Rp {v:,.0f}"

def _fmt_string(v, max_len=25):
    """Potong string panjang dengan ellipsis di tengah."""
    if not v:
        return "-"
    v = str(v)
    if len(v) <= max_len:
        return v
    return v[:max_len-1] + "…"

# ============================================================
# LOAD DATA
# ============================================================
companies, signals, orgs, relationships = load_all()
company_by_symbol = {c["symbol"]: c for c in companies}


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    LOGO_PATH = ROOT.parent / "assets" / "logo-white.png"

    logo_b64 = load_logo_base64(LOGO_PATH)

    if logo_b64:
        st.markdown(
            f'''
            <div style="margin-bottom: 1.3rem;">
                <img src="data:image/png;base64,{logo_b64}"
                     style="width: 160px; height: auto;" alt="Rivalytics">
                <div class="brand-sub" style="margin-top: .5rem;">
                    Competitive intelligence
                </div>
            </div>
            ''',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="brand">Rivalytics</div>', unsafe_allow_html=True)
        st.markdown('<div class="brand-sub">Competitive intelligence</div>', unsafe_allow_html=True)

    page = st.radio("Navigation", [
        "🏠 Dashboard",
        "🏢 Companies",
        "🔔 Signals",
        "🔗 Relationships",
        "📄 CSV Import",
        "📅 Weekly Update",
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
        "📋 Monitored Companies",
        "🔍 Discovery",
        "👤 Profile Perusahaan",
    ])

    # ---------- TAB 1: MONITORED COMPANIES ----------
    with tab1:
        st.markdown("**Monitored Companies** — perusahaan yang sudah punya relasi dengan profile Anda")
        st.caption("Hanya perusahaan yang punya relationship yang muncul di sini.")

        if not orgs:
            st.info("Belum ada profile. Bikin dulu di tab **👤 Profile Perusahaan**.")
        else:
            org_options = {f"{o['name']} (id={o['id']})": o["id"] for o in orgs}
            selected_org = st.selectbox("Profile", list(org_options.keys()), key="monitored_org")
            org_id = org_options[selected_org]

            conn = get_conn()
            rels = get_relationships(conn, org_id)
            conn.close()

            if not rels:
                st.info("Belum ada monitored company. Tambah dari tab **🔍 Discovery** atau **🔗 Relationships**.")
            else:
                rows = []
                for rel in rels:
                    sym = rel["company_symbol"]
                    sym_sigs = [s for s in signals if s["symbol"] == sym]
                    att = sum(1 for s in sym_sigs if s["severity"] == "attention")
                    watch = sum(1 for s in sym_sigs if s["severity"] == "watch")
                    mc = rel.get("market_cap") or 0
                    rows.append({
                        "Symbol": sym,
                        "Company": rel.get("company_name", "-"),
                        "Sector": rel.get("sector", "-"),
                        "Relationship": (rel["relationship_type"] or "—").title() if rel["relationship_type"] else "—",
                        "Priority": rel["priority"].title(),
                        "Market Cap": f"Rp {mc/1e12:.2f} T" if mc else "-",
                        "Attention": att,
                        "Watch": watch,
                        "Signals": len(sym_sigs),
                    })
                df = pd.DataFrame(rows).sort_values(
                    ["Attention", "Watch", "Signals"], ascending=False
                )
                st.caption(f"{len(df)} monitored companies")
                st.dataframe(df, use_container_width=True, hide_index=True)

    # ---------- TAB 2: DISCOVERY ----------
    with tab2:
        st.markdown("**Discovery** — cari kompetitor/supplier kandidat")
        st.caption("Discovery menggunakan ~1 credit untuk screener + ~1 credit per kandidat yang di-preview.")

        try:
            from discovery.discovery import discover_competitors, discover_suppliers
            from core.taxonomy import load_or_fetch_taxonomy
            from core.sectors_client import SectorsClient

            st.markdown("#### 🔍 Filter Pencarian")
            c1, c2 = st.columns(2)
            with c1:
                mode = st.radio("Mode", ["Competitor", "Supplier"], horizontal=True)
                sub_slug = st.text_input("Subsector slug", value="food-beverage",
                                        help="Contoh: food-beverage, banks, coal")
            with c2:
                tier = st.selectbox("Size tier (market cap)",
                                    ["micro", "small", "medium", "large"], index=2)
                limit = st.number_input("Jumlah kandidat", min_value=1, max_value=100, value=20)

            c1, c2 = st.columns(2)
            with c1:
                only_growing = st.checkbox("Hanya yang revenue-nya tumbuh", value=False)
            with c2:
                sort_by = st.selectbox("Sort by", ["-market_cap", "market_cap", "symbol"])

            if st.button("🔍 Discover Sekarang", type="primary"):
                with st.spinner("Cari kandidat..."):
                    try:
                        client = SectorsClient()
                        taxonomy = load_or_fetch_taxonomy(client)

                        profile = CompanyProfile(
                            name="User",
                            sector_slug="consumer-non-cyclicals",
                            subsector_slug=sub_slug,
                            size_tier=SizeTier(tier),
                        )

                        if mode == "Competitor":
                            comps = discover_competitors(
                                profile, client, taxonomy,
                                limit=limit, only_growing=only_growing
                            )
                        else:
                            comps = discover_suppliers(
                                profile, client, taxonomy,
                                upstream_subsectors=[sub_slug],
                                limit=limit
                            )

                        st.session_state["discovery_results"] = {
                            "data": comps,
                            "mode": mode,
                            "sub_slug": sub_slug,
                        }
                        st.toast(f"✓ {len(comps)} kandidat ditemukan", icon="✅")
                    except Exception as e:
                        st.error(f"Error: {e}")

            if "discovery_results" in st.session_state:
                info = st.session_state["discovery_results"]
                comps = info["data"]

                st.divider()
                st.markdown(f"### 📋 Hasil: {len(comps)} kandidat")

                if not comps:
                    st.warning("Nggak ada kandidat. Coba ubah filter.")
                else:
                    df = pd.DataFrame(comps)
                    display_cols = [c for c in ["symbol_clean", "company_name", "sector", "sub_sector", "market_cap"] if c in df.columns]
                    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

                    # Preview
                    st.divider()
                    st.markdown("### 👁️ Preview Detail Kandidat")
                    st.caption("Pilih kandidat untuk melihat detail sebelum menambahkan ke monitoring.")

                    candidate_map = {
                        (c.get("symbol_clean") or c.get("symbol", "").replace(".JK", "")): c
                        for c in comps
                    }
                    preview_symbol = st.selectbox(
                        "Pilih kandidat untuk preview",
                        list(candidate_map.keys()),
                        key="preview_candidate",
                    )

                    cache_key = f"detail_cache_{preview_symbol}"
                    if cache_key not in st.session_state:
                        with st.spinner(f"Fetching detail {preview_symbol}..."):
                            try:
                                client = SectorsClient()
                                report = client.get_company_report(
                                    preview_symbol, sections="overview"
                                )
                                st.session_state[cache_key] = report
                            except Exception as e:
                                st.session_state[cache_key] = {"_error": str(e)}

                    detail = st.session_state[cache_key]

                    if "_error" in detail:
                        st.error(f"Gagal fetch detail: {detail['_error']}")
                    else:
                        ov = detail.get("overview", {})
                        name = detail.get("company_name", preview_symbol)

                        st.markdown(f"#### {name} · `{preview_symbol}`")

                        d1, d2 = st.columns(2)
                        d1.metric("Market Cap", _fmt_rupiah(ov.get("market_cap")))
                        d2.metric("Last Close", _fmt_rupiah(ov.get("last_close_price")))

                        s1, s2 = st.columns(2)
                        with s1:
                            st.markdown(
                                f"<div style='color: #8a8f98; font-size: 0.75rem; "
                                f"text-transform: uppercase; letter-spacing: 0.05em;'>Sector</div>"
                                f"<div style='font-size: 1.05rem; font-weight: 600; "
                                f"margin-top: 0.15rem;'>{ov.get('sector', '-')}</div>",
                                unsafe_allow_html=True,
                            )
                        with s2:
                            st.markdown(
                                f"<div style='color: #8a8f98; font-size: 0.75rem; "
                                f"text-transform: uppercase; letter-spacing: 0.05em;'>Sub-sector</div>"
                                f"<div style='font-size: 1.05rem; font-weight: 600; "
                                f"margin-top: 0.15rem;'>{ov.get('sub_sector', '-')}</div>",
                                unsafe_allow_html=True,
                            )

                        indices = ov.get("indices") or []
                        tags = ov.get("tags") or []
                        listing_date = ov.get("listing_date", "-")
                        employee_num = ov.get("employee_num", "-")

                        info_col1, info_col2 = st.columns(2)
                        with info_col1:
                            st.markdown(f"**Industry**: {ov.get('industry', '-')}")
                            st.markdown(f"**Listing date**: {listing_date}")
                            st.markdown(f"**Employees**: {employee_num}")
                        with info_col2:
                            st.markdown(f"**Indices**: {', '.join(indices) if indices else '-'}")
                            st.markdown(f"**Tags**: {', '.join(tags[:5]) if tags else '-'}")

                        already_monitored = any(
                            (r.get("company_symbol") == preview_symbol)
                            for r in relationships
                        )
                        if already_monitored:
                            st.info(f"ℹ️ `{preview_symbol}` sudah ada di monitoring.")

                    # ---------- Add to Monitoring ----------
                    st.divider()
                    st.markdown("### ➕ Tambah ke Monitoring")
                    st.caption("Perusahaan yang belum ada di database akan otomatis di-ingest. Relationship bisa di-set nanti di tab 🔗 Relationships.")

                    if not orgs:
                        st.warning("Bikin profile dulu di **Companies → Profile Perusahaan**.")
                    else:
                        org_options = {f"{o['name']} (id={o['id']})": o["id"] for o in orgs}
                        selected_org = st.selectbox("Profile", list(org_options.keys()), key="disc_org")
                        org_id = org_options[selected_org]

                        symbols = [c.get("symbol_clean") or c.get("symbol", "").replace(".JK", "") for c in comps]
                        selected_symbols = st.multiselect(
                            "Pilih perusahaan buat ditambah ke monitoring",
                            symbols,
                            default=symbols[:5],
                        )

                        if st.button(f"➕ Tambah {len(selected_symbols)} ke Monitoring", type="primary"):
                            from monitoring.ingest import Ingestor
                            ing = Ingestor()

                            ingested = 0
                            ingest_failed = []
                            for sym in selected_symbols:
                                ck = get_conn()
                                exists = ck.execute(
                                    "SELECT symbol FROM companies WHERE symbol = ?", [sym]
                                ).fetchone()
                                ck.close()
                                if not exists:
                                    try:
                                        with st.spinner(f"Ingest {sym}..."):
                                            ing.ingest_smart(sym)
                                        ingested += 1
                                    except Exception as e:
                                        ingest_failed.append(f"{sym}: {e}")

                            conn = get_conn()
                            added = 0
                            skipped = 0
                            for sym in selected_symbols:
                                if add_relationship(conn, org_id, sym):  # ← tanpa type
                                    added += 1
                                else:
                                    skipped += 1
                            conn.close()

                            msg = f"✓ {added} ditambah ke monitoring"
                            if ingested:
                                msg += f", {ingested} di-ingest"
                            if skipped:
                                msg += f", {skipped} skip (udah ada)"
                            st.toast(msg, icon="✅")
                            st.success(msg + ". Set relationship di tab 🔗 Relationships.")
                            if ingest_failed:
                                st.warning("Gagal ingest: " + "; ".join(ingest_failed))
                            st.rerun()

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
            # Section 1: Set relationship untuk yang belum di-set
            conn = get_conn()
            unset = conn.execute("""
                SELECT r.company_symbol, c.name as company_name
                FROM relationships r
                JOIN companies c ON c.symbol = r.company_symbol
                WHERE r.organization_id = ? AND r.relationship_type IS NULL
            """, [org_id]).fetchall()
            conn.close()

            if unset:
                st.markdown("### 🎯 Set Relationship untuk Monitored Companies")
                st.caption("Perusahaan ini sudah di-monitoring tapi belum punya relationship.")
                for row in unset:
                    sym = row["company_symbol"]
                    with st.expander(f"**{sym}** — {row['company_name']}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            rtype = st.selectbox(
                                "Type",
                                ["competitor", "supplier", "customer",
                                 "distributor", "partner", "other"],
                                key=f"rtype_{sym}",
                            )
                        with c2:
                            prio = st.selectbox(
                                "Priority",
                                ["high", "medium", "low"],
                                index=1,
                                key=f"prio_{sym}",
                            )
                        if st.button("💾 Set", key=f"set_{sym}", type="primary"):
                            from core.db import set_relationship_type
                            ck = get_conn()
                            set_relationship_type(ck, org_id, sym, rtype, prio)
                            ck.close()
                            st.toast(f"✓ {sym} → {rtype} [{prio}]", icon="✅")
                            st.rerun()
                st.divider()

            # Section 2: Add manual (existing)
            st.markdown("### ➕ Add Manual (dengan relationship langsung)")
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
                        ck = get_conn()
                        exists = ck.execute(
                            "SELECT symbol FROM companies WHERE symbol = ?", [symbol]
                        ).fetchone()
                        ck.close()

                        if not exists:
                            try:
                                from monitoring.ingest import Ingestor
                                with st.spinner(f"Ingest {symbol}..."):
                                    Ingestor().ingest_smart(symbol)
                            except Exception as e:
                                st.error(f"Gagal ingest {symbol}: {e}")
                                st.stop()

                        conn = get_conn()
                        added = add_relationship(conn, org_id, symbol, rel_type, priority)
                        conn.close()
                        if added:
                            st.toast(f"✓ {symbol} → {rel_type} [{priority}]", icon="✅")
                            st.rerun()
                        else:
                            st.warning(f"⚠ {symbol} sudah ada")

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
# 📅 WEEKLY UPDATE
# ============================================================
elif page == "📅 Weekly Update":
    st.markdown(
        '<div class="hero"><h1>Weekly Intelligence</h1>'
        '<p>Cek update data baru tanpa boros API — user konfirmasi dulu.</p></div>',
        unsafe_allow_html=True,
    )

    # Status
    summary = get_pending_summary()

    c1, c2, c3 = st.columns(3)
    c1.metric("Monitored", summary["total_monitored"])
    c2.metric("Pending Updates", summary["pending_updates"])
    last_check_str = summary["last_check"][:16] if summary["last_check"] else "Belum pernah"
    c3.metric("Last Check", last_check_str)

    if summary["should_check"]:
        st.warning("⏰ Udah lebih dari 7 hari sejak cek terakhir. Waktunya cek update!")
    else:
        st.info("✅ Cek terakhir masih dalam 7 hari terakhir.")

    st.divider()

    # Cek Update
    st.markdown("### 🔍 Step 1: Cek Update")
    st.caption("Cek metadata. Ini tidak fetch data finansial, hanya mengecek apakah ada kuartal baru.")

    if not orgs:
        st.warning("Belum ada profile. Bikin dulu di Companies → Profile Perusahaan.")
    else:
        org_options = {"Semua profile": None}
        org_options.update({f"{o['name']} (id={o['id']})": o["id"] for o in orgs})
        selected_org = st.selectbox("Profile", list(org_options.keys()), key="weekly_org")
        selected_org_id = org_options[selected_org]

        if st.button("🔍 Cek Update Sekarang", type="primary"):
            with st.spinner("Cek metadata..."):
                try:
                    results = check_updates(org_id=selected_org_id)
                    st.session_state["weekly_results"] = results
                    st.toast(f"✓ Cek selesai untuk {len(results)} perusahaan", icon="✅")
                except Exception as e:
                    st.error(f"Error: {e}")

    st.divider()

    # Hasil cek
    if "weekly_results" in st.session_state:
        results = st.session_state["weekly_results"]

        if not results:
            st.info("Belum ada monitored company. Tambah relasi dulu di tab 🔗 Relationships.")
        else:
            st.markdown("### 📋 Step 2: Review Hasil")

            # Split
            with_update = [r for r in results if r.get("has_update")]
            no_update = [r for r in results if not r.get("has_update") and not r.get("error")]
            errors = [r for r in results if r.get("error")]

            if with_update:
                st.success(f"🎯 **{len(with_update)} perusahaan** punya data baru — siap di-ingest!")

                st.markdown("**Pilih yang mau di-ingest** (2 credits per perusahaan):")

                selected_symbols = []
                for r in with_update:
                    col1, col2, col3, col4 = st.columns([0.5, 2, 2, 2])
                    with col1:
                        checked = st.checkbox("", key=f"chk_{r['symbol']}", label_visibility="collapsed")
                    with col2:
                        st.markdown(f"**{r['symbol']}**")
                    with col3:
                        st.caption(f"DB: {r['latest_in_db']}")
                    with col4:
                        st.caption(f"API: {r['latest_available']}")
                    if checked:
                        selected_symbols.append(r["symbol"])

                if selected_symbols:
                    total_credits = len(selected_symbols) * 2
                    st.warning(f"⚠️ **Estimasi biaya: {total_credits} credits** untuk {len(selected_symbols)} perusahaan")

                    if st.button(f"🚀 Ingest {len(selected_symbols)} yang Dipilih", type="primary"):
                        with st.spinner(f"Ingest {len(selected_symbols)} perusahaan..."):
                            try:
                                result = ingest_selected(selected_symbols)
                                st.toast(
                                    f"✓ {len(result['success'])} sukses, {len(result['failed'])} gagal",
                                    icon="✅"
                                )
                                st.success(f"✓ Sukses: {len(result['success'])} perusahaan")
                                if result["failed"]:
                                    st.error(f"✗ Gagal: {len(result['failed'])} perusahaan")
                                    for f in result["failed"]:
                                        st.text(f"  {f['symbol']}: {f['error']}")
                                st.info(f"Credits terpakai: **{result['total_credits_used']}**")
                                st.session_state.pop("weekly_results", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                else:
                    st.caption("Centang perusahaan di atas buat di-ingest.")

            else:
                st.info("✓ Nggak ada update baru. Semua data udah up-to-date.")

            if no_update:
                with st.expander(f"✅ {len(no_update)} perusahaan up-to-date"):
                    for r in no_update:
                        st.text(f"  {r['symbol']}: {r['latest_in_db']}")

            if errors:
                with st.expander(f"⚠️ {len(errors)} error"):
                    for r in errors:
                        st.text(f"  {r['symbol']}: {r['error']}")

    st.divider()
    st.caption("💡 **Tips:** Cek update ini CHEAP (cuma metadata). Ingest baru bayar 2 credits per perusahaan.")

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
        relative = interpret_relative(symbol, signal, user_snapshots, user_name=selected_org)

        a, b = st.columns(2)
        with a:
            st.markdown("### 🌐 vs Peer")
            st.caption("Bandingin dengan rata-rata peer di subsector yang sama")
            st.info(general)
        with b:
            st.markdown("### 🎯 vs Kamu")
            st.caption("Bandingin dengan data finansial kamu sendiri (dari CSV)")
            st.info(relative)

        st.divider()
        st.markdown("### 🤖 AI Deep Dive")
        st.caption("Generate narasi lengkap dari interpretasi di atas menggunakan LLM.")

        if not get_env_var("GROQ_API_KEY") and not get_env_var("OPENAI_API_KEY"):
            st.warning("⚠ API key belum diset. Buka **⚙️ Settings** dulu.")
        else:
            provider = st.selectbox("Provider", ["groq", "openai"], key="interp_provider")

            if st.button("🤖 Generate AI Explanation", type="primary", key="btn_interp_ai"):
                with st.spinner("Menghubungi LLM..."):
                    try:
                        from core.ai_explain import explain_with_groq
                        result = explain_with_groq(
                            symbol=symbol,
                            signal=signal,
                            interpretation_general=general,
                            interpretation_relative=relative,
                            user_name=selected_org,
                        )
                        st.markdown("#### Hasil")
                        st.markdown(result)
                    except Exception as e:
                        st.error(f"Error: {e}")


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