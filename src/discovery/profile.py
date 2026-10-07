"""
profile.py — Company profile (representasi perusahaan user).

CompanyProfile = SATU-SATUNYA representasi perusahaan:
- Kalau `id` = None → belum disimpen ke DB (cuma buat discovery)
- Kalau `id` = ada → udah disimpen di tabel `organizations`
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SizeTier(str, Enum):
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


SIZE_TIER_RANGES = {
    SizeTier.MICRO:  (0,                  50_000_000_000),
    SizeTier.SMALL:  (50_000_000_000,     500_000_000_000),
    SizeTier.MEDIUM: (500_000_000_000,    5_000_000_000_000),
    SizeTier.LARGE:  (5_000_000_000_000,  float("inf")),
}


@dataclass
class CompanyProfile:
    name: str
    sector_slug: str
    subsector_slug: str
    size_tier: SizeTier
    business_description: str = ""
    ticker: Optional[str] = None
    id: Optional[int] = None

    @property
    def market_cap_range(self) -> tuple:
        return SIZE_TIER_RANGES[self.size_tier]

    @property
    def is_saved(self) -> bool:
        return self.id is not None

    def to_db_dict(self) -> dict:
        return {
            "name": self.name,
            "sector_slug": self.sector_slug,
            "subsector_slug": self.subsector_slug,
            "size_tier": self.size_tier.value,
            "description": self.business_description,
        }

    @classmethod
    def from_db(cls, row: dict) -> "CompanyProfile":
        return cls(
            id=row["id"],
            name=row["name"],
            sector_slug=row["sector_slug"] or "",
            subsector_slug=row["subsector_slug"] or "",
            size_tier=SizeTier(row["size_tier"]) if row["size_tier"] else SizeTier.MEDIUM,
            business_description=row.get("description") or "",
        )


# =========================
# DB HELPERS
# =========================

def save_profile(conn, profile: CompanyProfile) -> int:
    """Simpen CompanyProfile ke tabel organizations. Return org_id."""
    if profile.id:
        conn.execute("""
            UPDATE organizations SET
                name = ?, sector_slug = ?, subsector_slug = ?,
                size_tier = ?, description = ?
            WHERE id = ?
        """, [
            profile.name, profile.sector_slug, profile.subsector_slug,
            profile.size_tier.value, profile.business_description,
            profile.id,
        ])
        conn.commit()
        return profile.id
    else:
        cur = conn.execute("""
            INSERT INTO organizations
            (name, sector_slug, subsector_slug, size_tier, description)
            VALUES (?, ?, ?, ?, ?)
        """, [
            profile.name, profile.sector_slug, profile.subsector_slug,
            profile.size_tier.value, profile.business_description,
        ])
        conn.commit()
        org_id = cur.lastrowid
        profile.id = org_id
        return org_id


def get_profile(conn, org_id: int) -> Optional[CompanyProfile]:
    row = conn.execute(
        "SELECT * FROM organizations WHERE id = ?", [org_id]
    ).fetchone()
    if not row:
        return None
    return CompanyProfile.from_db(dict(row))


def list_profiles(conn) -> list:
    rows = conn.execute("SELECT * FROM organizations ORDER BY id").fetchall()
    return [CompanyProfile.from_db(dict(r)) for r in rows]


def delete_profile(conn, org_id: int) -> bool:
    cur = conn.execute("DELETE FROM organizations WHERE id = ?", [org_id])
    conn.commit()
    return cur.rowcount > 0