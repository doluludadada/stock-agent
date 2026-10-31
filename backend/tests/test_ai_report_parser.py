from pathlib import Path

import pytest
from trading_stack import MONDAY_10_00, MovableClock, run_status

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.chat.message import Message
from a_domain.model.market.stock import Stock
from a_domain.rules.ai.parser import parse_ai_report
from a_domain.types.enums import AiAnalysisFocus, MessageRole, Workflow
from a_domain.types.errors import AiReportParseError
from b_application.config.ai_config import PromptsConfig
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.composite_scorer import CompositeScorer


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


class ScriptedAiProvider:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        return Message(role=MessageRole.ASSISTANT, content=self._reply, timestamp=messages[-1].timestamp)

    def save_response(self, stock_id: str, content: str) -> None:
        return None


class NoHistory:
    async def find_decision_history(self, stock_id: str, limit: int = 3) -> str:
        return ""


def make_config() -> AppConfig:
    template = "Analyse {stock_id}: {articles_text}"
    return AppConfig(
        project_root=Path("."), prompts=PromptsConfig(analysis_report_fundamental=template, analysis_report_momentum=template)
    )


async def analyse_and_score(reply: str) -> tuple[Stock, PipelineStatus]:
    stock = Stock(stock_id="2330", technical_report=TechnicalReport(score=80))
    status = run_status(Workflow.SPECIFIC_STOCKS)
    config = make_config()
    analyser = AiAnalyser(
        ai_provider=ScriptedAiProvider(reply),
        knowledge_repository=NoHistory(),
        config=config,
        logger=SilentLogger(),
        market_clock=MovableClock(MONDAY_10_00),
    )

    await analyser.execute([stock], status, AiAnalysisFocus.FUNDAMENTAL)
    CompositeScorer(config=config, logger=SilentLogger()).execute([stock])

    return stock, status


@pytest.mark.asyncio
async def test_a_parsed_ai_score_feeds_the_composite_score() -> None:
    stock, status = await analyse_and_score('{"confidence_score": 60, "bullish_factors": ["EPS up"], "summary": "Solid."}')

    assert stock.ai_score == 60
    assert stock.composite_score == 70
    assert status.stats.ai_analysed == 1


@pytest.mark.parametrize(
    "reply",
    [
        "The outlook is positive, I would give it a 70.",
        '{"bullish_factors": ["EPS up"], "summary": "No score given."}',
        '{"confidence_score": 120}',
        '{"confidence_score": -5}',
        '{"confidence_score": "high"}',
        '{"confidence_score": 70.5}',
        '{"confidence_score": true}',
        '{"confidence_score": 70,}',
    ],
)
@pytest.mark.asyncio
async def test_an_unusable_ai_response_leaves_the_stock_without_ai_or_composite_score(reply: str) -> None:
    stock, status = await analyse_and_score(reply)

    assert stock.ai_report is None
    assert stock.composite_score is None
    assert status.stats.ai_analysed == 0
    assert len(status.stats.errors) == 1


def test_the_report_is_read_from_json_wrapped_in_prose_or_code_fences() -> None:
    raw = 'Here is my analysis:\n```json\n{"confidence_score": 72.0, "bearish_factors": "Debt, FX"}\n```'

    report = parse_ai_report(raw)

    assert report.score == 72
    assert report.bullish_factors == []
    assert report.bearish_factors == ["Debt", "FX"]
    assert report.summary == ""
    assert report.raw_response == raw


def test_a_missing_score_is_a_parse_error_not_a_neutral_default() -> None:
    with pytest.raises(AiReportParseError):
        parse_ai_report('{"summary": "Neutral."}')
