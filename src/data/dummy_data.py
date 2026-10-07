"""
dummy_data.py — Data dummy buat test UI tanpa database.
"""

# =========================
# COMPANIES
# =========================
DUMMY_COMPANIES = [
    {"symbol": "BBCA", "name": "Bank Central Asia",     "sector": "Financials", "sub_sector": "banks", "market_cap": 1_200_000_000_000_000},
    {"symbol": "BBRI", "name": "Bank Rakyat Indonesia", "sector": "Financials", "sub_sector": "banks", "market_cap": 700_000_000_000_000},
    {"symbol": "BMRI", "name": "Bank Mandiri",          "sector": "Financials", "sub_sector": "banks", "market_cap": 600_000_000_000_000},
    {"symbol": "INDF", "name": "Indofood Sukses Makmur","sector": "Consumer Non-Cyclicals", "sub_sector": "food-beverage", "market_cap": 60_000_000_000_000},
    {"symbol": "ICBP", "name": "Indofood CBP",          "sector": "Consumer Non-Cyclicals", "sub_sector": "food-beverage", "market_cap": 130_000_000_000_000},
    {"symbol": "ADRO", "name": "Adaro Energy",          "sector": "Energy", "sub_sector": "coal", "market_cap": 80_000_000_000_000},
    {"symbol": "PTBA", "name": "Bukit Asam",            "sector": "Energy", "sub_sector": "coal", "market_cap": 30_000_000_000_000},
    {"symbol": "UNVR", "name": "Unilever Indonesia",    "sector": "Consumer Non-Cyclicals", "sub_sector": "household-products", "market_cap": 130_000_000_000_000},
    {"symbol": "MYOR", "name": "Mayora Indah",          "sector": "Consumer Non-Cyclicals", "sub_sector": "food-beverage", "market_cap": 50_000_000_000_000},
    {"symbol": "GOTO", "name": "GoTo Gojek Tokopedia",  "sector": "Technology", "sub_sector": "internet", "market_cap": 80_000_000_000_000},
]


# =========================
# SIGNALS
# =========================
DUMMY_SIGNALS = [
    {"symbol": "ADRO", "period_label": "Q2-2026", "signal_type": "revenue_deterioration", "severity": "attention", "delta_pct": -25.3},
    {"symbol": "ADRO", "period_label": "Q2-2026", "signal_type": "cash_flow_weakness", "severity": "attention", "delta_pct": -204.5},
    {"symbol": "ADRO", "period_label": "Q2-2026", "signal_type": "profit_deterioration", "severity": "attention", "delta_pct": -55.0},
    {"symbol": "PTBA", "period_label": "Q2-2026", "signal_type": "revenue_deterioration", "severity": "watch", "delta_pct": -18.2},
    {"symbol": "PTBA", "period_label": "Q2-2026", "signal_type": "cash_flow_weakness", "severity": "watch", "delta_pct": -40.0},
    {"symbol": "INDF", "period_label": "Q2-2026", "signal_type": "revenue_deterioration", "severity": "watch", "delta_pct": -20.0},
    {"symbol": "ICBP", "period_label": "Q2-2026", "signal_type": "revenue_deterioration", "severity": "info", "delta_pct": -3.0},
    {"symbol": "UNVR", "period_label": "Q2-2026", "signal_type": "profit_deterioration", "severity": "attention", "delta_pct": -50.0},
    {"symbol": "GOTO", "period_label": "Q2-2026", "signal_type": "loss_making", "severity": "attention", "delta_pct": None},
    {"symbol": "MYOR", "period_label": "Q2-2026", "signal_type": "leverage_increase", "severity": "watch", "delta_pct": 35.0},
    {"symbol": "BBCA", "period_label": "Q2-2026", "signal_type": "revenue_deterioration", "severity": "info", "delta_pct": -2.0},
    {"symbol": "BBRI", "period_label": "Q2-2026", "signal_type": "revenue_deterioration", "severity": "watch", "delta_pct": -8.0},
]


# =========================
# ORGANIZATIONS
# =========================
DUMMY_ORGS = [
    {"id": 1, "name": "PT Contoh Pangan", "sector_slug": "consumer-non-cyclicals", "subsector_slug": "food-beverage", "size_tier": "medium", "description": "Perusahaan makanan ringan"},
    {"id": 2, "name": "PT Contoh Energi", "sector_slug": "energy", "subsector_slug": "coal", "size_tier": "large", "description": "Perusahaan tambang batu bara"},
]


# =========================
# RELATIONSHIPS
# =========================
DUMMY_RELATIONSHIPS = [
    {"id": 1, "organization_id": 1, "company_symbol": "ICBP", "relationship_type": "competitor", "priority": "high", "company_name": "Indofood CBP"},
    {"id": 2, "organization_id": 1, "company_symbol": "INDF", "relationship_type": "competitor", "priority": "high", "company_name": "Indofood Sukses Makmur"},
    {"id": 3, "organization_id": 1, "company_symbol": "MYOR", "relationship_type": "competitor", "priority": "medium", "company_name": "Mayora Indah"},
    {"id": 4, "organization_id": 1, "company_symbol": "BBCA", "relationship_type": "supplier", "priority": "low", "company_name": "Bank Central Asia"},
    {"id": 5, "organization_id": 2, "company_symbol": "PTBA", "relationship_type": "competitor", "priority": "high", "company_name": "Bukit Asam"},
    {"id": 6, "organization_id": 2, "company_symbol": "ADRO", "relationship_type": "competitor", "priority": "high", "company_name": "Adaro Energy"},
]