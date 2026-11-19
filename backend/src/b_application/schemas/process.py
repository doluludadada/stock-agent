from dataclasses import dataclass

from a_domain.model.analysis.stock_brief import BriefSource, StockBrief
from a_domain.model.market.company_profile import CompanyProfile
from a_domain.rules.technical.strategy import TechnicalStrategy
from b_application.schemas.pipeline_status import PipelineStatus


@dataclass(frozen=True)
class HeldBriefs:
    """What the site holds of one of its AI texts for a stock, a company or the world, as BriefLookup answers it."""

    today: StockBrief | None
    """The text of today in Taipei, if one was claimed."""

    previous: StockBrief | None
    """The newest written text of an earlier day."""

    stocks_left: int
    """How many more stocks may get a new text of this kind today."""


@dataclass(frozen=True)
class CompanyFacts:
    """What the site holds about a company itself, as Pipeline.load_company returns it."""

    profile: CompanyProfile | None
    """CompanyBackground: the company's profile."""

    sources: list[BriefSource]
    """CompanyBackground: the held items a company card may cite, each with the page it is from."""

    today: StockBrief | None
    """BriefLookup: the company's card if one was claimed today in Taipei."""

    previous: StockBrief | None
    """BriefLookup: the company's newest written card of an earlier day."""


@dataclass(frozen=True)
class StockEvaluation:
    """The stock page's technical evaluation, as Pipeline.evaluate_stock returns it."""

    strategy: TechnicalStrategy
    """StrategyLoader: the owner's active strategy."""

    status: PipelineStatus
    """The stock as manual_stocks with its history and report, and its indicator readings at every bar."""
