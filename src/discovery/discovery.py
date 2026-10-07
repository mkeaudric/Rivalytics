from typing import Optional
from core.sectors_client import SectorsClient, clean_symbol
from core.taxonomy import load_or_fetch_taxonomy
from profile import CompanyProfile, SizeTier


def _market_cap_filter(user: CompanyProfile) -> str:
    u_min, u_max = user.market_cap_range
    if u_max == float("inf"):
        return f"market_cap >= {int(u_min)}"
    return f"market_cap >= {int(u_min)} and market_cap <= {int(u_max)}"


def discover_competitors(
    user: CompanyProfile,
    client: SectorsClient,
    taxonomy: dict,
    limit: int = 15,
    only_growing: bool = False,
) -> list[dict]:
    # Cari competitor kandidat:
    # - subsector sama
    # - market cap dalam range size tier user (dilonggarkan 2x)
    # - (opsional) revenue Q terbaru > revenue Q yang sama tahun lalu
    
    if user.subsector_slug not in taxonomy["subsector_to_sector"]:
        raise ValueError(f"Slug subsector tidak valid: {user.subsector_slug}")

    u_min, u_max = user.market_cap_range
    min_mc = int(u_min * 0.5)
    where = f"sub_sector = '{user.subsector_slug}' and market_cap >= {min_mc}"
    if u_max != float("inf"):
        where += f" and market_cap <= {int(u_max * 2)}"

    if only_growing:
        # Screening pertumbuhan di sisi server aja
        # Pakai kuartal terbaru (misal Q2-2024 vs Q2-2023)
        # TODO: hardcode tahun dulu untuk MVP; nanti bikin dinamis
        where += " and revenue_q[Q2-2024] > revenue_q[Q2-2023] * 1.1"

    results = client.screen_all(
        where=where,
        order_by="-market_cap",
        max_results=limit * 3,
    )

    # Normalisasi symbol
    for r in results:
        r["symbol_clean"] = clean_symbol(r["symbol"])

    return results[:limit]


def discover_suppliers(
    user: CompanyProfile,
    client: SectorsClient,
    taxonomy: dict,
    upstream_subsectors: list[str],
    limit: int = 15,
) -> list[dict]:
    # Supplier discovery: cari perusahaan di subsector upstream, BUKAN yang mirip user.
    results = []
    for sub in upstream_subsectors:
        if sub not in taxonomy["subsector_to_sector"]:
            print(f"  [skip] slug tidak valid: {sub}")
            continue

        try:
            companies = client.screen_all(
                where=f"sub_sector = '{sub}'",
                order_by="-market_cap",
                max_results=limit,
            )
            for c in companies:
                c["symbol_clean"] = clean_symbol(c["symbol"])
                c["_upstream_subsector"] = sub
                results.append(c)
        except Exception as e:
            print(f"  [warn] gagal fetch {sub}: {e}")

    return results[:limit]