from collections.abc import Sequence
from dataclasses import replace

from a_domain.model.market.company_profile import CompanyProfile
from a_domain.ports.market.company_basics_provider import ICompanyBasicsProvider
from a_domain.ports.market.company_profile_repository import ICompanyProfileRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.config.app_config import AppConfig


class MainBusinessRefresh:
    """
    Brings the main business of the given companies up to date from MOPS's company basic information, in the order
    given: a company is asked for when the site never asked or last asked sources.mops.company_basics_max_age_days ago
    (MainBusinessDueRule), one request each at the pace of every request to MOPS, and what MOPS said is kept on the
    company's profile with the page a reader opens and the time, at once, so a run that stops fetches only the rest
    when it runs again. A company MOPS names no business for is kept as asked, with none. It stops at the first request
    MOPS does not answer, since a refused connection means the site asked too fast or too much. It answers how many
    companies it read and how many it left due. `basics` is None on a site that reads no MOPS (public), which reads
    nothing and leaves nothing due.
    """

    def __init__(
        self,
        basics: ICompanyBasicsProvider | None,
        profiles: ICompanyProfileRepository,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._basics = basics
        self._profiles = profiles
        self._market_clock = market_clock
        self._logger = logger
        self._due_rule = config.sources.mops.main_business_due_rule()

    async def execute(self, stock_ids: Sequence[str]) -> tuple[int, int]:
        if self._basics is None:
            return 0, 0

        due: list[CompanyProfile] = []

        for stock_id in dict.fromkeys(stock_ids):
            profile = await self._profiles.find(stock_id) or CompanyProfile(stock_id=stock_id)

            if self._due_rule.apply(profile, self._market_clock.now()):
                due.append(profile)

        read = 0

        for profile in due:
            basics = await self._basics.fetch(profile.stock_id)

            if basics is None:
                self._logger.warning(
                    f"Main business: MOPS did not answer for {profile.stock_id}; {len(due) - read} companies left due."
                )
                break

            held = await self._profiles.find(profile.stock_id) or profile
            await self._profiles.save(
                replace(
                    held,
                    main_business=basics.main_business,
                    english_name=basics.english_name,
                    main_business_url=basics.url,
                    main_business_fetched_at=self._market_clock.now(),
                )
            )
            read += 1

        if due:
            self._logger.info(f"Main business: read {read} of {len(due)} companies due from MOPS.")

        return read, len(due) - read
