from datetime import UTC, datetime
from pathlib import Path

import chromadb
import pytest
from trading_stack import MONDAY_10_00, MovableClock, run_status

from a_domain.model.chat.message import Message
from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.types.enums import AiAnalysisFocus, MessageRole, SignalSource, TradeAction, Workflow
from b_application.config.ai_config import PromptsConfig
from b_application.config.app_config import AppConfig
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.ship.decision_memory import DecisionMemory
from c_infrastructure.database.chroma.knowledge_repository import ChromaKnowledgeRepository


class SilentLogger:
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


def make_signal(stock_id: str, action: TradeAction, score: int, reason: str, hour: int) -> TradeSignal:
    generated_at = datetime(2026, 10, 30, hour, 0, tzinfo=UTC)
    return TradeSignal(
        stock_id=stock_id,
        action=action,
        quantity=0 if action == TradeAction.HOLD else 1000,
        price_at_signal=100.0,
        price_observed_at=generated_at,
        source=SignalSource.COMBINED,
        score=score,
        reason=reason,
        generated_at=generated_at,
    )


@pytest.fixture
def knowledge_repository(tmp_path: Path) -> ChromaKnowledgeRepository:
    return ChromaKnowledgeRepository(chromadb.PersistentClient(path=str(tmp_path / "chroma")), SilentLogger())


async def remember(repository: ChromaKnowledgeRepository, *signals: TradeSignal) -> None:
    status = run_status(Workflow.FULL_CYCLE)
    status.signals = list(signals)
    status.stocks_cache = {signal.stock_id: Stock(stock_id=signal.stock_id) for signal in signals}
    await DecisionMemory(knowledge_repository=repository, logger=SilentLogger()).execute(status)


class FailingFor2317:
    def __init__(self, repository: ChromaKnowledgeRepository) -> None:
        self._repository = repository

    async def save_decision(self, stock: Stock, signal: TradeSignal) -> None:
        if stock.stock_id == "2317":
            raise RuntimeError("disk full")

        await self._repository.save_decision(stock, signal)


@pytest.mark.asyncio
async def test_one_failed_save_does_not_stop_the_other_decisions(knowledge_repository: ChromaKnowledgeRepository) -> None:
    signals = [make_signal(stock_id, TradeAction.HOLD, 50, "hold", hour=1) for stock_id in ("2317", "2330")]
    status = run_status(Workflow.FULL_CYCLE)
    status.signals = signals
    status.stocks_cache = {signal.stock_id: Stock(stock_id=signal.stock_id) for signal in signals}

    await DecisionMemory(knowledge_repository=FailingFor2317(knowledge_repository), logger=SilentLogger()).execute(status)

    assert "Stock: 2330" in await knowledge_repository.find_decision_history("2330")
    assert status.stats.errors == ["Decision memory failed for 2317: disk full"]


@pytest.mark.asyncio
async def test_decision_history_returns_only_that_stocks_decisions_newest_first(
    knowledge_repository: ChromaKnowledgeRepository,
) -> None:
    await remember(
        knowledge_repository,
        make_signal("2330", TradeAction.HOLD, 55, "Waiting for the 2330 earnings call", hour=1),
        make_signal("2317", TradeAction.SELL, 25, "2330 supplier news hurts 2317", hour=2),
        make_signal("2330", TradeAction.BUY, 85, "Strong 2330 revenue growth", hour=3),
    )

    history = await knowledge_repository.find_decision_history("2330")
    decisions = history.split("\n\n---\n\n")

    assert len(decisions) == 2
    assert all("Stock: 2330" in decision for decision in decisions)
    assert "Stock: 2317" not in history
    assert "Decision: buy" in decisions[0]
    assert "Combined Score: 85" in decisions[0]
    assert "Reason: Strong 2330 revenue growth" in decisions[0]
    assert "Generated At: 2026-10-30T03:00:00+00:00" in decisions[0]
    assert "Decision: hold" in decisions[1]


@pytest.mark.asyncio
async def test_decision_history_is_limited_and_empty_for_a_stock_without_decisions(
    knowledge_repository: ChromaKnowledgeRepository,
) -> None:
    await remember(knowledge_repository, *(make_signal("2330", TradeAction.HOLD, 50 + hour, "hold", hour=hour) for hour in range(5)))

    newest_two = await knowledge_repository.find_decision_history("2330", limit=2)

    assert "Combined Score: 54" in newest_two
    assert "Combined Score: 53" in newest_two
    assert newest_two.count("Stock: 2330") == 2
    assert await knowledge_repository.find_decision_history("2317") == ""


@pytest.mark.asyncio
async def test_ai_analysis_prompt_carries_the_analysed_stocks_own_history(knowledge_repository: ChromaKnowledgeRepository) -> None:
    await remember(
        knowledge_repository,
        make_signal("2330", TradeAction.BUY, 85, "Strong revenue growth", hour=1),
        make_signal("2317", TradeAction.SELL, 25, "Margin pressure", hour=2),
    )
    template = "Analyse {stock_id}: {articles_text}"
    config = AppConfig(
        project_root=Path("."), prompts=PromptsConfig(analysis_report_fundamental=template, analysis_report_momentum=template)
    )
    ai_provider = PromptRecordingAiProvider()
    analyser = AiAnalyser(
        ai_provider=ai_provider,
        knowledge_repository=knowledge_repository,
        config=config,
        logger=SilentLogger(),
        market_clock=MovableClock(MONDAY_10_00),
    )

    await analyser.execute([Stock(stock_id="2330")], run_status(Workflow.FULL_CYCLE), AiAnalysisFocus.FUNDAMENTAL)

    assert "[Past Analysis]" in ai_provider.prompts[0]
    assert "Reason: Strong revenue growth" in ai_provider.prompts[0]
    assert "Margin pressure" not in ai_provider.prompts[0]
