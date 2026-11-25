from collections.abc import Sequence
from datetime import date
from hashlib import sha256

from pydantic import PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.market.article import Article
from a_domain.model.market.company_profile import CompanyProfile
from a_domain.model.market.stock import Stock
from a_domain.rules.ai.stock_brief import BriefContext, BriefFact, held_fact, keyed_facts, listing_line
from a_domain.rules.fundamentals.stock_analysis import RevenueTrend
from a_domain.types.enums import BriefSourceKind


def listing_fact(stock: Stock, profile: CompanyProfile | None, industry_names: dict[str, str], day: date) -> BriefFact:
    """The company as the exchange's open data gives it, each held figure named; `day` dates it while no profile is held."""
    held = profile or CompanyProfile(stock_id=stock.stock_id)
    industry = industry_names.get(held.industry_code or "") or stock.industry
    said = [
        listing_line(stock, held.short_name or stock.name),
        f"industry in the exchange's listing: {industry or 'not held'}",
        None if held.full_name is None else f"full name {held.full_name}",
        None if held.founded_on is None else f"founded {held.founded_on.isoformat()}",
        None if held.listed_on is None else f"listed {held.listed_on.isoformat()}",
        None if held.paid_in_capital is None else f"paid-in capital {held.paid_in_capital:,.0f} TWD",
        None if held.issued_shares is None else f"{held.issued_shares:,} shares issued",
        None if held.chairman is None else f"chairman {held.chairman}",
        None if held.general_manager is None else f"general manager {held.general_manager}",
    ]
    return held_fact(BriefSourceKind.COMPANY, held.reported_on or day, "; ".join(part for part in said if part))


def filed_business_facts(profile: CompanyProfile | None) -> list[BriefFact]:
    if profile is None or not profile.main_business or profile.main_business_fetched_at is None:
        return []

    text = f"main business as the company filed it with MOPS: {profile.main_business}"
    return [held_fact(BriefSourceKind.PROFILE, profile.main_business_fetched_at.date(), text, url=profile.main_business_url)]


def yearly_revenue_facts(revenue: RevenueTrend, day: date) -> list[BriefFact]:
    """The revenue of the last calendar year before `day`, when all twelve of its months are held: it changes once a year."""
    months = [month for month in revenue.months if month.year == day.year - 1 and month.revenue is not None]

    if len({month.month for month in months}) < 12:
        return []

    total = sum(month.revenue or 0 for month in months)
    served = max(month.served_date for month in months)
    return [held_fact(BriefSourceKind.REVENUE, served, f"revenue of {day.year - 1}, twelve months: {total:,.0f} thousand TWD")]


def report_facts(sections: Sequence[Article], section_length: PositiveInt) -> list[BriefFact]:
    """The sections of the newest annual report among those given, each by its title and its kept text cut at `section_length`."""
    newest = max((section.fact_date or date.min for section in sections), default=date.min)
    return [
        held_fact(
            BriefSourceKind.ANNUAL_REPORT,
            section.published_at.date(),
            f"{section.title} | {' '.join(section.content.split())[:section_length]}",
            section.title,
            section.url,
        )
        for section in sorted(sections, key=lambda section: section.url or "")
        if (section.fact_date or date.min) == newest
    ]


@dataclass(frozen=True, kw_only=True)
class CompanyCardContextRule:
    """
    What a company card may rest on, from held data alone: the company as the exchanges' open data gives it, its main
    business as it filed it with MOPS, its revenue of the last full calendar year, and the sections of its newest
    annual report the article store keeps, each cut at `section_length`. Each fact gets a key the AI cites, in this
    order. The context's fingerprint is a digest of every fact with its source and of `instructions`, the prompt and
    the language the card is written with, so a card is written again exactly when one of them changed; the day alone
    changes none of them.
    """

    section_length: PositiveInt
    industry_names: dict[str, str]
    instructions: str

    def apply(
        self, stock: Stock, profile: CompanyProfile | None, sections: Sequence[Article], revenue: RevenueTrend, day: date
    ) -> BriefContext:
        found = [
            listing_fact(stock, profile, self.industry_names, day),
            *filed_business_facts(profile),
            *yearly_revenue_facts(revenue, day),
            *report_facts(sections, self.section_length),
        ]
        said = [f"{fact.source.kind.value}|{fact.source.title or ''}|{fact.source.url or ''}|{fact.text}" for fact in found]
        digest = sha256("\n".join([self.instructions, *said]).encode()).hexdigest()

        return BriefContext(
            stock_id=stock.stock_id,
            stock_name=stock.name or "",
            window_first=None,
            window_last=None,
            price_change=None,
            facts=keyed_facts(found),
            fingerprint=digest,
        )
