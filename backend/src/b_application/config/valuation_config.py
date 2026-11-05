from pydantic import BaseModel, Field


class ValuationConfig(BaseModel):
    """P/E valuation (menus 5 and 6)."""

    scenario_spread: float = Field(default=0.2, gt=0, lt=1)
    """The conservative and optimistic target P/E are the user's target × (1 ∓ spread)."""

    max_scan_explanations: int = Field(default=3, ge=1, le=20)
    """The undervalued scan asks the AI to explain at most this many top stocks (one paid call each)."""

    not_investment_advice: str
    """The last section of every valuation report."""

    low_pe_caveat: str
    """Under the undervalued scan's table, and among the risks of a stock that looks undervalued."""

    ai_not_provided: str
    """Stands in for an explanation section the AI left empty."""

    undervaluation_formula: str
    """Under a report's gap lines and above the undervalued scan's counts."""

    no_fair_price_prompt_rule: str
    """The explanation prompt's rule for a stock with no fair price. `{reason}` is why the P/E does not apply."""

    keep_scenarios_prompt_rule: str
    """The explanation prompt's rule for a stock with three scenarios."""

    low_pe_prompt_rule: str
    """The explanation prompt's extra rule for a stock that looks undervalued."""
