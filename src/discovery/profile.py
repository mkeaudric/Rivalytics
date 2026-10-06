from dataclasses import dataclass
from enum import Enum


class SizeTier(str, Enum):
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


SIZE_TIER_RANGES = {
    SizeTier.MICRO:  (0,                 50_000_000_000),
    SizeTier.SMALL:  (50_000_000_000,    500_000_000_000),
    SizeTier.MEDIUM: (500_000_000_000,   5_000_000_000_000),
    SizeTier.LARGE:  (5_000_000_000_000, float("inf")),
}


@dataclass
class CompanyProfile:
    name: str
    sector_slug: str
    subsector_slug: str
    size_tier: SizeTier
    business_description: str = ""
    ticker: str | None = None

    @property
    def market_cap_range(self) -> tuple[float, float]:
        return SIZE_TIER_RANGES[self.size_tier]