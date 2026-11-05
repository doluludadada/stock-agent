from collections.abc import Awaitable, Callable
from datetime import date, datetime, time

import pytest
from trading_stack import MONDAY_10_00, MovableClock, SilentLogger, run_stats

from a_domain.model.chat.message import Message
from a_domain.model.fundamentals.eps import Eps
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.fundamentals.filing import FilingDeadlineRule
from a_domain.rules.valuation.valuation import AppraisalRule, StockValuationRule
from a_domain.types.enums import AiAnalysisFocus, EpsBasis, EpsKind, InformationSource, Workflow
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


async def analysis_prompt(focus: AiAnalysisFocus) -> str:
    ai = PromptRecorder()
    analyser = AiAnalyser(ai, NoHistory(), MovableClock(MONDAY_10_00), SHIPPED, SilentLogger())

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
