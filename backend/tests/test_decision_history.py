"""
The AI's decision history: a stock's newest decisions in the owner's trading journal, which the AI reads again, with the
evidence each was made on, in the stock's past analysis.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from support.fakes import FakeDailyCloseArchive
from support.settings import shipped_config
from trading_stack import MONDAY_10_00, MovableClock, run_stats

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.analysis.technical_report import TechnicalObservation, TechnicalReport
from a_domain.model.chat.message import Message
from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import AiAnalysisFocus, MessageRole, SignalSource, TradeAction, Workflow
from a_domain.types.ids import UserId
from b_application.config.ai_config import PromptsConfig
from b_application.use_cases.process.ai_analyser import AiAnalyser
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.trading_journal import TradingJournal

pytestmark = pytest.mark.asyncio


class RecordingLogger:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def __getattr__(self, name: str):
        return lambda message: None


class PromptRecordingAiProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        self.prompts.append(messages[-1].content)
        return Message(role=MessageRole.ASSISTANT, content='{"confidence_score": 50}', timestamp=messages[-1].timestamp)

    def save_response(self, stock_id: str, content: str) -> None:
        return None


class UnreadableJournal:
    async def decision_history(self, stock_id: str, limit: int = 3) -> list[TradeSignal]:
        raise ConnectionError("the database went away")


def decision(stock_id: str, reason: str, hour: int, source: SignalSource = SignalSource.COMBINED) -> TradeSignal:
    generated_at = datetime(2026, 10, 30, hour, 0, tzinfo=UTC)
    return TradeSignal(
        stock_id=stock_id,
        action=TradeAction.HOLD,
        source=source,
        score=50 + hour,
        reason=reason,
        price_at_signal=100.0,
        price_observed_at=generated_at,
        generated_at=generated_at,
    )


@pytest.fixture
def journal(database: DatabaseConnector) -> TradingJournal:
    return TradingJournal(database.for_owner(UserId("alice")))


async def analysis_prompt(journal: ITradingJournal, logger: RecordingLogger) -> str:
    template = "Analyse {stock_id}: {articles_text}"
    config = shipped_config().model_copy(
        update={"prompts": PromptsConfig(analysis_report_fundamental=template, analysis_report_momentum=template)}
    )
    ai_provider = PromptRecordingAiProvider()
    analyser = AiAnalyser(ai_provider, journal, FakeDailyCloseArchive(), MovableClock(MONDAY_10_00), config, logger)

    await analyser.execute([Stock(stock_id="2330")], AiAnalysisFocus.FUNDAMENTAL, run_stats(Workflow.FULL_CYCLE))

    [prompt] = ai_provider.prompts
    return prompt


async def test_the_history_is_the_stocks_own_decisions_newest_first_and_as_many_as_asked(journal: TradingJournal) -> None:
    await journal.save_signals(
        run_stats().run_id,
        [
            decision("2330", "first", 1),
            decision("2317", "another stock", 2),
            decision("2330", "second", 3),
            decision("2330", "third", 4),
        ],
    )

    assert [signal.reason for signal in await journal.decision_history("2330")] == ["third", "second", "first"]
    assert [signal.reason for signal in await journal.decision_history("2330", limit=2)] == ["third", "second"]
    assert await journal.decision_history("1101") == []


async def test_a_follow_and_a_ranking_follow_are_not_in_the_history(journal: TradingJournal) -> None:
    analysed = decision("2330", "analysed", 1)
    stopped = decision("2330", "stopped out", 2, SignalSource.STOP_LOSS)
    bought = decision("2330", "bought by hand", 3, SignalSource.MANUAL)
    followed = replace(decision("2330", "followed", 4, SignalSource.FOLLOW), followed_decision_id=analysed.decision_id)
    ranked = decision("2330", "ranked", 5, SignalSource.RANKING)
    await journal.save_signals(run_stats(Workflow.FULL_CYCLE).run_id, [analysed, stopped, bought])
    await journal.save_signals(run_stats(Workflow.FOLLOW).run_id, [followed])
    await journal.save_signals(run_stats(Workflow.RANKING_FOLLOW).run_id, [ranked])

    history = await journal.decision_history("2330", limit=5)

    assert [signal.reason for signal in history] == ["bought by hand", "stopped out", "analysed"]


async def test_the_ai_reads_each_past_decision_of_the_stock_with_the_evidence_it_was_made_on(journal: TradingJournal) -> None:
    technical = TechnicalReport(
        score=72,
        hard_failures=["below_ma60"],
        soft_failures=["volume_expansion", "rsi_high"],
        observations=[
            TechnicalObservation(rule="golden_cross", detected=True),
            TechnicalObservation(rule="macd_turn", detected=False),
        ],
    )
    ai = AiAnalysisReport(
        score=64, bullish_factors=["AI demand"], bearish_factors=["margin pressure"], summary="Strong", raw_response="{}"
    )
    stop_loss = replace(
        decision("2330", "Stop loss hit", 2, SignalSource.STOP_LOSS),
        action=TradeAction.SELL,
        quantity=1000,
        stop_loss_price=95.0,
        technical_report=technical,
        ai_report=ai,
    )
    await journal.save_signals(run_stats().run_id, [decision("2330", "Waiting", 1), stop_loss, decision("2317", "Margin", 3)])

    prompt = await analysis_prompt(journal, RecordingLogger())

    assert prompt.partition("[Past Analysis]\n")[2].split("\n\n---\n\n") == [
        "Stock: 2330\nDecision: sell\nSource: stop_loss\nGenerated At: 2026-10-30T02:00:00+00:00\nPrice: 100.0\n"
        "Quantity: 1000\nTechnical Score: 72\nAI Score: 64\nCombined Score: 52\nReason: Stop loss hit\n"
        "Hard Failures: below_ma60\nSoft Failures: volume_expansion, rsi_high\n"
        "Observations: golden_cross: detected, macd_turn: not detected\nAI Summary: Strong\nBullish Factors: AI demand\n"
        "Bearish Factors: margin pressure\nStop Loss Price: 95.0",
        "Stock: 2330\nDecision: hold\nSource: combined\nGenerated At: 2026-10-30T01:00:00+00:00\nPrice: 100.0\n"
        "Quantity: 0\nTechnical Score: Unavailable\nAI Score: Unavailable\nCombined Score: 51\nReason: Waiting\n"
        "Hard Failures: \nSoft Failures: \nObservations: \nAI Summary: \nBullish Factors: \nBearish Factors: ",
    ]


async def test_a_history_the_journal_cannot_read_is_logged_and_the_ai_is_asked_without_it() -> None:
    logger = RecordingLogger()

    prompt = await analysis_prompt(UnreadableJournal(), logger)

    assert "[Past Analysis]" not in prompt
    assert logger.errors == ["Decision history lookup failed for 2330: the database went away"]
