from a_domain.model.market.company_profile import CompanyProfile
from a_domain.model.market.stock import Stock
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.market.company_profile_repository import ICompanyProfileRepository
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.ai.stock_brief import BriefContext
from a_domain.rules.fundamentals.stock_analysis import StockAnalysis
from b_application.config.app_config import AppConfig


class CompanyBackground:
    """
    What the site holds about one listed company itself, from held data alone: its profile, and what its company card
    may rest on (CompanyCardContextRule): the profile's open data and main business, the revenue of the last full
    calendar year in the stock's analysis, and the sections of its newest annual report the article store keeps. The
    context's sources name the page of MOPS and of the document site each fact is from, so a stock page links them with
    or without a card. It fetches nothing and asks no AI.
    """

    def __init__(
        self, profiles: ICompanyProfileRepository, store: IArticleStore, market_clock: IMarketClock, config: AppConfig
    ) -> None:
        self._profiles = profiles
        self._store = store
        self._market_clock = market_clock
        self._context_rule = config.company_card_context_rule()

    async def execute(self, stock: Stock, analysis: StockAnalysis) -> tuple[CompanyProfile | None, BriefContext]:
        profile = await self._profiles.find(stock.stock_id)
        sections = await self._store.references(stock.stock_id)

        return profile, self._context_rule.apply(stock, profile, sections, analysis.revenue, self._market_clock.today())
