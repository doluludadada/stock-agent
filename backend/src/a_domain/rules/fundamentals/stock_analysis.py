import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from statistics import median

from pydantic import FiniteFloat, NonNegativeInt, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.ports.market.daily_close_archive import ValuationRatios
from a_domain.rules.fundamentals.trailing_eps import QuarterEps
from a_domain.rules.trading.ranking import revenue_acceleration, revenue_matrix
from a_domain.types.enums import ReadingKind
from a_domain.types.values import FiscalQuarter, month_index


def ratio(part: float | None, whole: float | None) -> float | None:
    """`part` over `whole`, or None when either is missing or `whole` is not above 0, where a share or a change says nothing."""
    if part is None or whole is None or whole <= 0:
        return None

    return part / whole


def run_length(values: Sequence[float | None], level: float) -> int | None:
    """
    How many of the latest values in a row sit on the latest one's side of `level`: 3 for three above it, -2 for two
    below it, 0 when the latest equals it. None when the latest value is missing, so nothing is read from older ones.
    """
    if not values or values[-1] is None:
        return None

    side = (values[-1] > level) - (values[-1] < level)
    length = 0

    for value in reversed(values):
        if value is None or (value > level) - (value < level) != side:
            break

        length += 1

    return side * length


@dataclass(frozen=True)
class RevenueMonth:
    """One held month of a company's revenue as the stock page reads it. Revenue is in thousands of TWD; changes are ratios."""

    year: int
    month: int
    revenue: FiniteFloat | None
    year_over_year: FiniteFloat | None
    """The change from the same month a year before: 0.25 is 25% more. As served, else from the two held months."""

    acceleration: FiniteFloat | None
    """
    The ranking's own measure: the mean revenue of the latest short months over that of the latest long months, up to
    this month. Above 1, the latest months run ahead of the longer average. None while any of those months is not held.
    """

    served_date: date
    """The day the source served the month's figure."""


@dataclass(frozen=True)
class RevenueTrend:
    """A company's held months of revenue, oldest first, and how long the latest direction has lasted."""

    months: list[RevenueMonth]
    short_months: PositiveInt
    long_months: PositiveInt
    """The months the acceleration averages: ranking.revenue_short_months over ranking.revenue_long_months."""

    accelerating_months: int | None
    """The latest months in a row with an acceleration above 1, negative for below 1. None when the latest month has none."""

    growing_months: int | None
    """The latest months in a row above the same month a year before, negative for below. None when the latest has no change."""


def year_over_year_change(held: Mapping[int, MonthlyRevenue], index: int) -> float | None:
    revenue = held[index]

    if revenue.year_over_year_percent is not None:
        return revenue.year_over_year_percent / 100

    before = held[index - 12].revenue if index - 12 in held else revenue.last_year_revenue
    change = ratio(revenue.revenue, before)
    return None if change is None else change - 1


@dataclass(frozen=True)
class RevenueTrendRule:
    """
    A company's revenue trend from the months held: each month's change from a year before and its acceleration as the
    monthly ranking measures it (MonthlyRankingRule), then how many of the latest months in a row accelerated and grew.
    It reads only what is held: a month with a gap in its window has no acceleration, and no trend is drawn across it.
    """

    short_months: PositiveInt
    long_months: PositiveInt

    def apply(self, revenues: Sequence[MonthlyRevenue]) -> RevenueTrend:
        held = {month_index(revenue.year, revenue.month): revenue for revenue in revenues}
        amounts, _ = revenue_matrix([""], {("", revenue.year, revenue.month): revenue.revenue for revenue in revenues})
        first = min(held, default=0)
        accelerations = {
            index: float(revenue_acceleration(amounts, index - first, self.short_months, self.long_months)[0]) for index in held
        }
        months = [
            RevenueMonth(
                year=revenue.year,
                month=revenue.month,
                revenue=revenue.revenue,
                year_over_year=year_over_year_change(held, index),
                acceleration=None if math.isnan(accelerations[index]) else accelerations[index],
                served_date=revenue.served_date,
            )
            for index, revenue in sorted(held.items())
        ]

        return RevenueTrend(
            months=months,
            short_months=self.short_months,
            long_months=self.long_months,
            accelerating_months=run_length([month.acceleration for month in months], 1.0),
            growing_months=run_length([month.year_over_year for month in months], 0.0),
        )


@dataclass(frozen=True)
class QuarterResult:
    """
    One held quarter of a company's results as the stock page reads it. The EPS figures are in TWD; the margins and the
    debt ratio are ratios of the statements' figures of the year to the quarter's end, None where the company's industry
    format reports no such figure or the archive holds no statement of the quarter.
    """

    quarter: FiscalQuarter
    eps_year_to_date: FiniteFloat | None
    """The basic EPS from the year's start to the quarter's end, as filed."""

    quarter_eps: FiniteFloat | None
    """The quarter's own EPS: the year to date less the year to the quarter before. None while that quarter is not held."""

    eps_year_over_year: FiniteFloat | None
    """
    The change of the year-to-date EPS from the same quarter a year before: 0.25 is 25% more. None while that quarter
    is not held, or its EPS was not above 0, from which a change says nothing.
    """

    gross_margin: FiniteFloat | None
    operating_margin: FiniteFloat | None
    net_margin: FiniteFloat | None
    """Gross profit, operating income and the net income attributable to the parent, each over revenue."""

    debt_ratio: FiniteFloat | None
    """Total liabilities over total assets at the quarter's end."""


@dataclass(frozen=True)
class EarningsTrend:
    """A company's held quarters, oldest first, and how long the latest direction of its EPS has lasted."""

    quarters: list[QuarterResult]
    eps_growing_quarters: int | None
    """
    The latest quarters in a row with a year-to-date EPS above a year before, negative for below. None when the latest
    quarter has no such change.
    """

    filed_eps_fetched_at: datetime | None
    """When the newest MOPS page that gave a quarter's EPS was fetched. None when every EPS is the open-data archive's."""


def quarter_result(quarter: FiscalQuarter, held: QuarterFinancials | None, eps: Mapping[FiscalQuarter, float]) -> QuarterResult:
    year_to_date = eps.get(quarter)
    before = 0.0 if quarter.quarter == 1 else eps.get(quarter.previous())
    change = ratio(year_to_date, eps.get(FiscalQuarter(quarter.year - 1, quarter.quarter)))
    figures = held or QuarterFinancials(quarter=quarter)

    return QuarterResult(
        quarter=quarter,
        eps_year_to_date=year_to_date,
        quarter_eps=None if year_to_date is None or before is None else year_to_date - before,
        eps_year_over_year=None if change is None else change - 1,
        gross_margin=ratio(figures.gross_profit, figures.revenue),
        operating_margin=ratio(figures.operating_income, figures.revenue),
        net_margin=ratio(figures.net_income, figures.revenue),
        debt_ratio=ratio(figures.total_liabilities, figures.total_assets),
    )


@dataclass(frozen=True)
class EarningsTrendRule:
    """
    A company's earnings trend from the quarters held: the archive's figures of each quarter, and the year-to-date EPS
    MOPS's held pages give for the quarters the archive lacks. A quarter's own EPS and its change from a year before need
    the quarter before and the same quarter a year before; without them they are None, never a guess.
    """

    def apply(self, stock_id: str, quarters: Sequence[QuarterFinancials], pages: Sequence[QuarterEps]) -> EarningsTrend:
        held = {quarter.quarter: quarter for quarter in quarters}
        archived = {quarter.quarter: quarter.eps for quarter in quarters if quarter.eps is not None}
        filed = {page.quarter: page for page in pages if stock_id in page.cumulative_eps and page.quarter not in archived}
        eps = archived | {quarter: page.cumulative_eps[stock_id] for quarter, page in filed.items()}
        results = [quarter_result(quarter, held.get(quarter), eps) for quarter in sorted(held.keys() | eps.keys())]

        return EarningsTrend(
            quarters=results,
            eps_growing_quarters=run_length([result.eps_year_over_year for result in results], 0.0),
            filed_eps_fetched_at=max((page.fetched_at for page in filed.values()), default=None),
        )


@dataclass(frozen=True)
class RatioStanding:
    """One valuation ratio at the latest held session against the stock's own held history."""

    latest: FiniteFloat | None
    """None when the exchange left the ratio blank that session, as it does the P/E of a company with losses."""

    median: FiniteFloat | None
    """The median of the sessions that give the ratio. None while they are fewer than the sessions a comparison needs."""

    sessions: NonNegativeInt
    """How many held sessions give the ratio."""


@dataclass(frozen=True)
class ValuationStanding:
    """A stock's P/E, P/B and dividend yield (percent) at the latest session the archive holds, each against its own held history."""

    session_date: date | None
    """The latest session held. None when the archive holds no ratios of the stock."""

    first_session: date | None
    sessions: NonNegativeInt
    min_sessions: PositiveInt
    """The sessions a ratio needs before its median is given: stock_page.valuation_min_sessions."""

    pe_ratio: RatioStanding
    pb_ratio: RatioStanding
    dividend_yield: RatioStanding


def ratio_standing(values: Sequence[float | None], min_sessions: PositiveInt) -> RatioStanding:
    given = [value for value in values if value is not None]

    return RatioStanding(
        latest=values[-1] if values else None, median=median(given) if len(given) >= min_sessions else None, sessions=len(given)
    )


@dataclass(frozen=True)
class ValuationStandingRule:
    """
    Where a stock's valuation ratios stand against its own held history: the latest session's ratios, and each ratio's
    median over the sessions that give it once they are `min_sessions` or more. With fewer, the median is None: a few
    sessions say nothing about where a ratio usually is.
    """

    min_sessions: PositiveInt

    def apply(self, history: Sequence[ValuationRatios]) -> ValuationStanding:
        sessions = sorted(history, key=lambda ratios: ratios.session_date)
        latest = sessions[-1] if sessions else None

        return ValuationStanding(
            session_date=None if latest is None else latest.session_date,
            first_session=sessions[0].session_date if sessions else None,
            sessions=len(sessions),
            min_sessions=self.min_sessions,
            pe_ratio=ratio_standing([ratios.pe_ratio for ratios in sessions], self.min_sessions),
            pb_ratio=ratio_standing([ratios.pb_ratio for ratios in sessions], self.min_sessions),
            dividend_yield=ratio_standing([ratios.dividend_yield for ratios in sessions], self.min_sessions),
        )


@dataclass(frozen=True)
class Reading:
    """One sentence of the reading: what it says, and the months, quarters or sessions it counts where it counts any."""

    kind: ReadingKind
    count: NonNegativeInt | None = None


@dataclass(frozen=True)
class StockAnalysis:
    """A stock page's financial analysis: the three trends read from held data alone, and their reading in sentences."""

    revenue: RevenueTrend
    earnings: EarningsTrend
    valuation: ValuationStanding
    readings: list[Reading]
    """What the figures say, by fixed rules, in page order: revenue, earnings, valuation. No AI writes any of it."""


def revenue_readings(revenue: RevenueTrend) -> list[Reading]:
    if not revenue.months:
        return [Reading(ReadingKind.NO_REVENUE)]

    readings: list[Reading] = []

    if revenue.accelerating_months is None:
        readings.append(Reading(ReadingKind.REVENUE_HISTORY_SHORT, len(revenue.months)))

    if revenue.accelerating_months:
        kind = ReadingKind.REVENUE_ACCELERATING if revenue.accelerating_months > 0 else ReadingKind.REVENUE_SLOWING
        readings.append(Reading(kind, abs(revenue.accelerating_months)))

    if revenue.growing_months:
        kind = ReadingKind.REVENUE_GROWING if revenue.growing_months > 0 else ReadingKind.REVENUE_SHRINKING
        readings.append(Reading(kind, abs(revenue.growing_months)))

    return readings


def earnings_reading(earnings: EarningsTrend) -> Reading:
    held = [result for result in earnings.quarters if result.eps_year_to_date is not None]

    if not held:
        return Reading(ReadingKind.NO_EPS)

    if not earnings.eps_growing_quarters:
        return Reading(ReadingKind.EPS_HISTORY_SHORT, len(held))

    kind = ReadingKind.EPS_UP if earnings.eps_growing_quarters > 0 else ReadingKind.EPS_DOWN
    return Reading(kind, abs(earnings.eps_growing_quarters))


def valuation_reading(valuation: ValuationStanding) -> Reading:
    price_to_earnings = valuation.pe_ratio

    if valuation.session_date is None:
        return Reading(ReadingKind.NO_VALUATION)

    if price_to_earnings.latest is None:
        return Reading(ReadingKind.NO_PE)

    if price_to_earnings.median is None:
        return Reading(ReadingKind.VALUATION_HISTORY_SHORT, price_to_earnings.sessions)

    if price_to_earnings.latest == price_to_earnings.median:
        return Reading(ReadingKind.PE_AT_MEDIAN, price_to_earnings.sessions)

    kind = ReadingKind.PE_ABOVE_MEDIAN if price_to_earnings.latest > price_to_earnings.median else ReadingKind.PE_BELOW_MEDIAN
    return Reading(kind, price_to_earnings.sessions)


@dataclass(frozen=True)
class StockAnalysisRule:
    """
    A stock's financial analysis from held data, and its reading by fixed rules: whether revenue runs ahead of its longer
    average and of a year before and for how many months, whether the EPS is above a year before and for how many
    quarters, and whether the P/E is above the median of the sessions held. Where the history is too short for one of
    them, the reading says how much is held instead of drawing a trend from it.
    """

    revenue_rule: RevenueTrendRule
    earnings_rule: EarningsTrendRule
    valuation_rule: ValuationStandingRule

    def apply(
        self,
        stock_id: str,
        quarters: Sequence[QuarterFinancials],
        revenues: Sequence[MonthlyRevenue],
        pages: Sequence[QuarterEps],
        ratios: Sequence[ValuationRatios],
    ) -> StockAnalysis:
        revenue = self.revenue_rule.apply(revenues)
        earnings = self.earnings_rule.apply(stock_id, quarters, pages)
        valuation = self.valuation_rule.apply(ratios)
        readings = [*revenue_readings(revenue), earnings_reading(earnings), valuation_reading(valuation)]

        return StockAnalysis(revenue=revenue, earnings=earnings, valuation=valuation, readings=readings)
