# kode untuk fetch dan cache slug

import json
from pathlib import Path
from sectors_client import SectorsClient

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)


def load_or_fetch_taxonomy(client: SectorsClient) -> dict:
    cache_file = CACHE_DIR / "taxonomy.json"

    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)

    subsectors = client._get("/subsectors/")     # [{sector, subsector}, ...]
    industries = client._get("/industries/")     # [{subsector, industry}, ...]
    subindustries = client._get("/subindustries/")

    taxonomy = {
        "sector_to_subsectors": {},
        "subsector_to_sector": {},
        "subsector_to_industry": {},
        "industry_to_subindustries": {},
    }

    for row in subsectors:
        taxonomy["sector_to_subsectors"].setdefault(row["sector"], []).append(row["subsector"])
        taxonomy["subsector_to_sector"][row["subsector"]] = row["sector"]

    for row in industries:
        taxonomy["subsector_to_industry"][row["subsector"]] = row["industry"]

    for row in subindustries:
        taxonomy["industry_to_subindustries"].setdefault(row["industry"], []).append(row["sub_industry"])

    with open(cache_file, "w") as f:
        json.dump(taxonomy, f, indent=2)

    return taxonomy