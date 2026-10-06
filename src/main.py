from profile import CompanyProfile, SizeTier
from sectors_client import SectorsClient
from taxonomy import load_or_fetch_taxonomy
from discovery import discover_competitors, discover_suppliers


def main():
    client = SectorsClient()

    print("Loading taxonomy...")
    taxonomy = load_or_fetch_taxonomy(client)
    print(f"  {len(taxonomy['subsector_to_sector'])} subsector, "
          f"{len(taxonomy['subsector_to_industry'])} industry")

    user = CompanyProfile(
        name="PT Contoh Pangan",
        sector_slug="consumer-non-cyclicals",
        subsector_slug="food-beverage",
        size_tier=SizeTier.MEDIUM,
    )

    print(f"\n=== COMPETITOR KANDIDAT (subsector: {user.subsector_slug}) ===\n")
    competitors = discover_competitors(user, client, taxonomy, limit=8)
    for c in competitors:
        mc = c.get("market_cap", 0)
        print(f"  {c['symbol_clean']:6} {c['company_name'][:35]:35} MC: {mc:>18,}")

    print(f"\n=== SUPPLIER KANDIDAT (upstream) ===\n")
    suppliers = discover_suppliers(
        user, client, taxonomy,
        upstream_subsectors=["packaging", "chemicals", "agricultural-products"],
        limit=6,
    )
    for s in suppliers:
        mc = s.get("market_cap", 0)
        print(f"  {s['symbol_clean']:6} {s['company_name'][:35]:35} "
              f"({s['_upstream_subsector']}) MC: {mc:>15,}")


if __name__ == "__main__":
    main()