from pydantic import BaseModel, Field


class ValuationConfig(BaseModel):
    """P/E valuation (menus 5 and 6)."""

    scenario_spread: float = Field(default=0.2, gt=0, lt=1)
    """The conservative and optimistic target P/E are the user's target × (1 ∓ spread)."""

    max_scan_explanations: int = Field(default=3, ge=1, le=20)
    """The undervalued scan asks the AI to explain at most this many top stocks (one paid call each)."""
