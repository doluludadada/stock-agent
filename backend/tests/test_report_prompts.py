from collections.abc import Awaitable, Callable
from datetime import date, datetime, time

import pytest
from support.fakes import FakeDailyCloseArchive
from trading_stack import MONDAY_10_00, MovableClock, SilentLogger, run_stats

from a_domain.model.chat.message import Message
from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.fundamentals.filing import FilingDeadlineRule
from a_domain.rules.valuation.valuation import AppraisalRule, StockValuationRule
from a_domain.types.enums import AiAnalysisFocus, EpsBasis, EpsKind, InformationSource, MarketType, Workflow
from a_domain.types.values import FiscalQuarter
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.valuation.valuation_explainer import ValuationExplainer
from c_infrastructure.ai_models.sentiment_classifier import AiSentimentClassifier
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from d_presentation.dependencies import get_project_root, load_settings

pytestmark = pytest.mark.asyncio

SHIPPED = load_settings(get_project_root())
"""config/appsetting.yaml with the prompts of config/instructions.yaml, as the CLI and the Web API load them."""

LAST_CLOSED_SESSION = date(2026, 10, 16)


class PromptRecorder:
    """An AI provider that keeps every prompt it is sent and then fails, so the test needs no reply."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        self.prompts.append(messages[-1].content)
        raise ConnectionError("prompt recorded")

    def save_response(self, stock_id: str, content: str) -> None:
        return None


class NoHistory:
    async def find_decision_history(self, stock_id: str, limit: int = 3) -> str:
        return ""


class NothingClassified:
    async def find_classified(self, stock_id: str, posts: list[Article]) -> list[Article]:
        return []

    async def save_classified(self, stock_id: str, posts: list[Article]) -> None:
        return None


def article(title: str) -> Article:
    return Article(
        stock_id="2330",
        source=InformationSource.PTT_STOCK,
        title=title,
        content=f"{title} content",
        url=f"https://example.test/{title}",
        published_at=MONDAY_10_00,
        fetched_at=MONDAY_10_00,
    )


def stock() -> Stock:
    return Stock(stock_id="2330", name="TSMC", industry="Semiconductors", articles=[article("capacity")])


async def analysis_prompt(focus: AiAnalysisFocus, archive: FakeDailyCloseArchive | None = None) -> str:
    ai = PromptRecorder()
    analyser = AiAnalyser(ai, NoHistory(), archive or FakeDailyCloseArchive(), MovableClock(MONDAY_10_00), SHIPPED, SilentLogger())

    await analyser.execute([stock()], focus, run_stats(Workflow.SPECIFIC_STOCKS))

    [prompt] = ai.prompts
    return prompt


async def fundamental_analysis_prompt() -> str:
    return await analysis_prompt(AiAnalysisFocus.FUNDAMENTAL)


async def momentum_analysis_prompt() -> str:
    return await analysis_prompt(AiAnalysisFocus.MOMENTUM)


async def sentiment_prompt() -> str:
    ai = PromptRecorder()
    classifier = AiSentimentClassifier(ai, NothingClassified(), SHIPPED, SilentLogger())

    with pytest.raises(ConnectionError):
        await classifier.classify("2330", [article("bullish post"), article("bearish post")])

    [prompt] = ai.prompts
    return prompt


async def valuation_prompt() -> str:
    valued = stock()
    valued.eps = Eps(
        value=40.0,
        kind=EpsKind.TRAILING_TWELVE_MONTHS,
        period_end=FiscalQuarter(2026, 2),
        basis=EpsBasis.ACTUAL,
        source=InformationSource.TWSE_MOPS,
        fetched_at=MONDAY_10_00,
    )
    close = Ohlcv(ts=datetime.combine(LAST_CLOSED_SESSION, time(13, 30), TAIWAN_TIMEZONE), open=1000, high=1000, low=1000, close=1000)
    valuation_rule = StockValuationRule(
        max_missed_sessions=1, filing_deadline_rule=FilingDeadlineRule(SHIPPED.sources.mops.filing_deadlines)
    )
    valuation = valuation_rule.apply(valued, close, LAST_CLOSED_SESSION)
    ai = PromptRecorder()
    explainer = ValuationExplainer(ai, MovableClock(MONDAY_10_00), SHIPPED, SilentLogger())

    await explainer.execute(AppraisalRule(SHIPPED.valuation.scenario_spread).apply(valuation, 25))

    [prompt] = ai.prompts
    return prompt


@pytest.mark.parametrize("prompt_of", [fundamental_analysis_prompt, momentum_analysis_prompt, sentiment_prompt, valuation_prompt])
async def test_every_prompt_whose_answer_a_report_shows_asks_for_an_english_answer(prompt_of: Callable[[], Awaitable[str]]) -> None:
    prompt = await prompt_of()

    assert "2330" in prompt
    assert "in English" in prompt
    assert "Chinese" not in prompt


def month_of(month: int, revenue: float, month_over_month: float, year_over_year: float) -> MonthlyRevenue:
    return MonthlyRevenue(
        stock_id="2330",
        year=2026,
        month=month,
        market=MarketType.TWSE,
        served_date=date(2026, month + 1, 10),
        company_name="TSMC",
        industry="Semiconductors",
        revenue=revenue,
        previous_month_revenue=None,
        last_year_revenue=None,
        month_over_month_percent=month_over_month,
        year_over_year_percent=year_over_year,
        cumulative_revenue=None,
        last_year_cumulative_revenue=None,
        cumulative_year_over_year_percent=None,
        note="-",
    )


@pytest.mark.parametrize("focus", list(AiAnalysisFocus))
async def test_the_analysis_prompt_shows_the_latest_two_archived_quarters_and_the_latest_months_revenue_with_their_units(
    focus: AiAnalysisFocus,
) -> None:
    archive = FakeDailyCloseArchive()
    archive.held_financials["2330"] = (
        [
            QuarterFinancials(quarter=FiscalQuarter(2026, 1), revenue=839253664.0),
            QuarterFinancials(quarter=FiscalQuarter(2026, 2), revenue=1773046302.0, eps=31.27),
            QuarterFinancials(
                quarter=FiscalQuarter(2026, 3),
                revenue=2763307000.0,
                gross_profit=1640000000.0,
                net_income=1220000000.0,
                eps=47.06,
                total_assets=7300000000.0,
                equity=4500000000.0,
                book_value_per_share=173.5,
            ),
        ],
        [month_of(8, 335771000.0, -1.2, 33.8), month_of(9, 511857399.0, -0.5726, 54.6486)],
    )

    prompt = await analysis_prompt(focus, archive)

    assert (
        "[Financials]\n2026Q2: income of the year to its end in TWD thousand: revenue 1,773,046,302; per share in TWD: "
        "basic EPS 31.27\n" in prompt
    )
    assert (
        "2026Q3: income of the year to its end in TWD thousand: revenue 2,763,307,000, gross profit 1,640,000,000, net income "
        "attributable to the parent 1,220,000,000; balance at its end in TWD thousand: total assets 7,300,000,000, equity "
        "attributable to the parent 4,500,000,000; per share in TWD: basic EPS 47.06, book value per share 173.50\n"
        "2026-09 (revenues in TWD thousand): revenue 511,857,399, month over month -0.57%, year over year +54.65%"
    ) in prompt
    assert "2026Q1" not in prompt and "2026-08" not in prompt
    assert prompt.index("capacity content") < prompt.index("[Financials]")


async def test_the_analysis_prompt_has_no_financials_section_while_the_archive_holds_none() -> None:
    prompt = await fundamental_analysis_prompt()

    assert "[Financials]" not in prompt and "capacity content" in prompt
