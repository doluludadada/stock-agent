from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from support.harness import build_harness, rising_history
from trading_stack import run_status

from a_domain.model.analysis.social_sentiment import SentimentClassification, SocialSentiment
from a_domain.model.chat.message import Message
from a_domain.model.market.article import Article
from a_domain.model.market.stock import Stock
from a_domain.types.enums import InformationSource, MessageRole, SentimentConsensus, SentimentLabel, TradeAction, Workflow
from b_application.schemas.config import AppConfig, PromptsConfig
from b_application.use_cases.process.sentiment_analyser import SentimentAnalyser
from c_infrastructure.ai_models.sentiment_classifier import AiSentimentClassifier
from c_infrastructure.database.db_connector import DatabaseConnector

BULLISH, BEARISH, NEUTRAL, UNCLEAR = SentimentLabel.BULLISH, SentimentLabel.BEARISH, SentimentLabel.NEUTRAL, SentimentLabel.UNCLEAR
SRC = Path(__file__).resolve().parents[1] / "src"


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


class ScriptedAiProvider:
    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        self.prompts.append(messages[-1].content)
        return Message(role=MessageRole.ASSISTANT, content=self._replies.pop(0))

    def save_response(self, stock_id: str, content: str) -> None:
        return None


def make_post(text: str, url: str | None = None, source: InformationSource = InformationSource.PTT_STOCK) -> Article:
    return Article(stock_id="2330", source=source, title=f"[標的] {text}", content=text, url=url, published_at=datetime(2026, 10, 30))


def tally(*labels: SentimentLabel, confidence: float = 0.9) -> SocialSentiment:
    return SocialSentiment.tally([SentimentClassification(label, confidence) for label in labels], posts=len(labels))


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ([BULLISH, BULLISH, BEARISH], SentimentConsensus.BULLISH),
        ([BEARISH, BEARISH, BEARISH, NEUTRAL], SentimentConsensus.BEARISH),
        ([BULLISH, BEARISH], SentimentConsensus.DISAGREEMENT),
        ([BULLISH, BULLISH, BEARISH, BEARISH], SentimentConsensus.DISAGREEMENT),
        ([BULLISH, BULLISH, BEARISH, BEARISH, NEUTRAL], SentimentConsensus.DISAGREEMENT),
        ([BULLISH, BEARISH, NEUTRAL, NEUTRAL, NEUTRAL], SentimentConsensus.NEUTRAL),
        ([BULLISH, UNCLEAR, UNCLEAR], SentimentConsensus.UNCLEAR),
        ([BULLISH], SentimentConsensus.UNCLEAR),
    ],
)
def test_stock_level_consensus(labels: list[SentimentLabel], expected: SentimentConsensus) -> None:
    assert tally(*labels).consensus == expected


def test_ratios_are_shares_of_opinions_and_low_confidence_counts_as_unclear() -> None:
    sentiment = SocialSentiment.tally(
        [
            SentimentClassification(BULLISH, 0.9),
            SentimentClassification(BULLISH, 0.8),
            SentimentClassification(BEARISH, 0.7),
            SentimentClassification(NEUTRAL, 0.6),
            SentimentClassification(BEARISH, 0.3),
            SentimentClassification(UNCLEAR, 0.9),
        ],
        posts=7,
    )

    assert (sentiment.bullish, sentiment.bearish, sentiment.neutral, sentiment.unclear) == (2, 1, 1, 2)
    assert (sentiment.bullish_ratio, sentiment.bearish_ratio, sentiment.neutral_ratio) == (0.5, 0.25, 0.25)
    assert (sentiment.classified, sentiment.posts) == (6, 7)


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncIterator[DatabaseConnector]:
    connector = DatabaseConnector(config=AppConfig(project_root=tmp_path), logger=SilentLogger())
    await connector.init_db()
    yield connector
    await connector.close()


def make_classifier(ai_provider: ScriptedAiProvider, db: DatabaseConnector) -> AiSentimentClassifier:
    config = AppConfig(project_root=Path("."), prompts=PromptsConfig(social_sentiment="Stock {stock_id}\n{posts_text}"))
    return AiSentimentClassifier(ai_provider=ai_provider, db=db, config=config, logger=SilentLogger())


@pytest.mark.asyncio
async def test_a_post_is_classified_once_and_then_served_from_the_cache(db: DatabaseConnector) -> None:
    ai = ScriptedAiProvider('{"posts": [{"index": 1, "label": "BULLISH", "confidence": 0.8}]}')
    classifier = make_classifier(ai, db)
    post = make_post("Revenue beat", url="https://www.ptt.cc/bbs/Stock/M.1.A.html")

    first = await classifier.classify("2330", [post])
    second = await classifier.classify("2330", [post])

    assert first == second == [SentimentClassification(BULLISH, 0.8)]
    assert len(ai.prompts) == 1


@pytest.mark.asyncio
async def test_an_unreadable_reply_raises_and_caches_nothing(db: DatabaseConnector) -> None:
    ai = ScriptedAiProvider("Sorry, I cannot help with that.", '{"posts": [{"index": 1, "label": "maybe", "confidence": 0.8}]}')
    classifier = make_classifier(ai, db)
    post = make_post("Revenue beat", url="https://www.ptt.cc/bbs/Stock/M.2.A.html")

    for _ in range(2):
        with pytest.raises(ValueError):
            await classifier.classify("2330", [post])

    assert len(ai.prompts) == 2


@pytest.mark.asyncio
async def test_a_partial_reply_keeps_valid_items_and_resends_only_the_missing_post(db: DatabaseConnector) -> None:
    ai = ScriptedAiProvider(
        '{"posts": [{"index": 1, "label": "bearish", "confidence": 0.7}, {"index": 2, "label": "MOON", "confidence": 0.9}]}',
        '{"posts": [{"index": 1, "label": "neutral", "confidence": 0.6}]}',
    )
    classifier = make_classifier(ai, db)
    posts = [make_post("Margins fall", url="https://ptt/1"), make_post("Dividend unchanged", url="https://ptt/2")]

    first = await classifier.classify("2330", posts)
    second = await classifier.classify("2330", posts)

    assert first == [SentimentClassification(BEARISH, 0.7)]
    assert sorted(second, key=lambda item: item.label) == [
        SentimentClassification(BEARISH, 0.7),
        SentimentClassification(NEUTRAL, 0.6),
    ]
    assert "Dividend unchanged" in ai.prompts[1]
    assert "Margins fall" not in ai.prompts[1]


class FakeClassifier:
    def __init__(self, failing_stock_ids: set[str]) -> None:
        self._failing_stock_ids = failing_stock_ids
        self.classified_sources: list[InformationSource] = []

    async def classify(self, stock_id: str, articles: list[Article]) -> list[SentimentClassification]:
        if stock_id in self._failing_stock_ids:
            raise ValueError("model unavailable")

        self.classified_sources.extend(article.source for article in articles)
        return [SentimentClassification(BULLISH, 0.9) for _ in articles]


@pytest.mark.asyncio
async def test_sentiment_reads_only_social_posts_and_records_a_failed_stock() -> None:
    news = make_post("Quarterly report", source=InformationSource.NEWS_MEDIA)
    ok = Stock(stock_id="2330", articles=[make_post("Up"), make_post("Up more"), news])
    broken = Stock(stock_id="2603", articles=[make_post("Ships")])
    classifier = FakeClassifier(failing_stock_ids={"2603"})
    status = run_status(Workflow.BUZZ_SCAN)

    await SentimentAnalyser(classifier=classifier, logger=SilentLogger()).execute([ok, broken], status)

    assert classifier.classified_sources == [InformationSource.PTT_STOCK, InformationSource.PTT_STOCK]
    assert status.sentiment_by_stock_id["2330"].consensus == SentimentConsensus.BULLISH
    assert status.sentiment_by_stock_id["2330"].posts == 2
    assert "2603" not in status.sentiment_by_stock_id
    assert status.stats.errors == ["Sentiment analysis failed for 2603: model unavailable"]


@pytest.mark.parametrize("label", [BULLISH, BEARISH])
@pytest.mark.asyncio
async def test_menu_2_reports_sentiment_of_qualified_posts_only_and_trades_the_same_either_way(
    label: SentimentLabel, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = build_harness()
    rules = harness.config.collect_rules
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", rising_history(100.0), realtime_price=100.0)
    harness.discuss("2330", mentions=2, engagement=rules.buzz_min_engagement, title="hot thread")
    harness.discuss("2317", mentions=1, engagement=0, title="quiet thread")
    harness.sentiment.labels["2330"] = label

    status = await harness.run_menu("2")
    output = capsys.readouterr().out

    assert harness.sentiment.classified == [("2330", ["hot thread 2330", "hot thread 2330"])]
    assert status.sentiment_by_stock_id["2330"].consensus == SentimentConsensus(label.value)
    assert "Buzz Filter: Discussed=2, Qualified=1" in output
    assert "Social Sentiment" in output
    assert [(signal.stock_id, signal.action) for signal in harness.journal.signals] == [("2330", TradeAction.BUY)]
    assert [(order.stock_id, order.action) for order in harness.broker.placed] == [("2330", TradeAction.BUY)]


TRADING_PATHS = [
    "a_domain/rules/trading",
    "a_domain/rules/scoring",
    "a_domain/model/trading",
    "a_domain/model/market/stock.py",
    "b_application/use_cases/ship",
    "b_application/use_cases/trade",
    "b_application/use_cases/process/composite_scorer.py",
]


def test_trading_code_never_reads_sentiment() -> None:
    files = [path for entry in TRADING_PATHS for path in ([SRC / entry] if entry.endswith(".py") else (SRC / entry).rglob("*.py"))]
    offenders = [str(path.relative_to(SRC)) for path in files if "sentiment" in path.read_text(encoding="utf-8").lower()]

    assert len(files) > 10
    assert offenders == [], (
        f"US-011 sentiment is report only and must not feed trading. Remove the sentiment reference from {offenders}."
    )
