"""Builds the CLI the way build_cli_orchestrator() does, with only the ports replaced by fakes.

Every use case, domain rule and the Pipeline come from the real build_* functions
in cli_container.py, so a test written against CliHarness survives changes to
use-case constructors.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from rich.prompt import Confirm, Prompt

from a_domain.model.analysis.technical_settings import TechnicalSettings
from a_domain.model.fundamentals.eps import FiscalQuarter
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position
from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.rules.technical.calculation import IndicatorParameters
from a_domain.rules.technical.criteria.trend import PriceAboveMaCriterion
from a_domain.rules.technical.criteria.volume.volume import MinimumPriceCriterion
from a_domain.rules.technical.strategy import TechnicalRule, TechnicalScoring, TechnicalStrategy
from a_domain.types.enums import (
    AiAnalysisFocus,
    ExecutionProvider,
    InformationSource,
    OrderMode,
    RuleEffect,
    SystemEnvironment,
    WatchlistType,
)
from b_application.pipeline import Pipeline
from b_application.schemas.config import AppConfig, NotificationConfig, PromptsConfig, TradingConfig
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.trade.account_history import AccountHistory
from b_application.use_cases.trade.manual_buy import ManualBuy
from b_application.use_cases.trade.watch_stocks import WatchStocks
from b_application.valuation_pipeline import ValuationPipeline
from c_infrastructure.system.market_clock import TAIWAN_SESSION_CLOSE, TAIWAN_TIMEZONE
from d_presentation.cli import interactive
from d_presentation.cli.cli_container import (
    ProviderDependencies,
    build_collect_use_cases,
    build_pipeline,
    build_process_use_cases,
    build_trading_use_cases,
    build_valuation_pipeline,
    validate_trading_environment,
)
from support.fakes import (
    PROMPT_TEMPLATES,
    VALUATION_PROMPT_TEMPLATE,
    FakeAiProvider,
    FakeFundamentalsProvider,
    FakeKnowledgeRepository,
    FakeMarketClock,
    FakeNewsProvider,
    FakeOhlcvProvider,
    FakeSentimentClassifier,
    FakeSocialMediaProvider,
    FakeStockProvider,
    FakeTechnicalSettingsRepository,
    FakeTradingJournal,
    FakeWatchlistRepository,
    RecordingExecutionProvider,
    RecordingLogger,
)

MARKET_OPEN = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)
MARKET_CLOSED = datetime(2026, 10, 19, 14, 0, tzinfo=TAIWAN_TIMEZONE)
FRESH = timedelta(minutes=1)
STALE = timedelta(minutes=30)

TECHNICAL_SCORE = 90
TREND_STRATEGY = TechnicalStrategy(
    strategy_id="trend",
    indicators=IndicatorParameters(),
    scoring=TechnicalScoring(base_score=TECHNICAL_SCORE),
    rules=(TechnicalRule(criterion=PriceAboveMaCriterion(5), effect=RuleEffect.BLOCK_ON_FAIL),),
)
BUZZ_STRATEGY = TechnicalStrategy(
    strategy_id="buzz",
    indicators=IndicatorParameters(),
    scoring=TechnicalScoring(base_score=TECHNICAL_SCORE),
    rules=(TechnicalRule(criterion=MinimumPriceCriterion(15.0), effect=RuleEffect.BLOCK_ON_FAIL),),
)


def harness_settings() -> TechnicalSettings:
    """Full Cycle, Intraday and Manual use the trend strategy; Buzz uses only a minimum-price check."""
    return TechnicalSettings(active_strategy_id="trend", buzz_strategy_id="buzz", strategies=(TREND_STRATEGY, BUZZ_STRATEGY))


def harness_config() -> AppConfig:
    return AppConfig(
        project_root=Path(__file__).resolve().parents[3],
        environment=SystemEnvironment.DEV,
        prompts=PromptsConfig(
            analysis_report_fundamental=PROMPT_TEMPLATES[AiAnalysisFocus.FUNDAMENTAL],
            analysis_report_momentum=PROMPT_TEMPLATES[AiAnalysisFocus.MOMENTUM],
            valuation_explanation=VALUATION_PROMPT_TEMPLATE,
        ),
        trading=TradingConfig(execution_provider=ExecutionProvider.MOCK, order_mode=OrderMode.MOCK_ONLY),
        notifications=NotificationConfig(enabled=False),
    )


HISTORY_LAST_SESSION = MARKET_OPEN.date() - timedelta(days=1)


def daily_history(closes: list[float], last_session: date = HISTORY_LAST_SESSION) -> list[Ohlcv]:
    """One bar per calendar day, the last closing at 13:30 on last_session. Keep last_session within the history freshness limit."""
    last_close_at = datetime.combine(last_session, TAIWAN_SESSION_CLOSE, TAIWAN_TIMEZONE)
    return [
        Ohlcv(ts=last_close_at - timedelta(days=len(closes) - 1 - day), open=close, high=close, low=close, close=close, volume=1000)
        for day, close in enumerate(closes)
    ]


def rising_history(last_close: float, last_session: date = HISTORY_LAST_SESSION) -> list[Ohlcv]:
    """Ten daily closes climbing to last_close: the price sits above its 5-day average, so the trend strategy passes."""
    return daily_history([last_close - step for step in range(9, -1, -1)], last_session)


def falling_history(last_close: float, last_session: date = HISTORY_LAST_SESSION) -> list[Ohlcv]:
    """Ten daily closes sliding to last_close: the price sits below its 5-day average, so the trend strategy fails."""
    return daily_history([last_close + step for step in range(9, -1, -1)], last_session)


@dataclass
class CliHarness:
    config: AppConfig
    clock: FakeMarketClock
    stocks: FakeStockProvider
    fundamentals: FakeFundamentalsProvider
    prices: FakeOhlcvProvider
    news: FakeNewsProvider
    social: FakeSocialMediaProvider
    ai: FakeAiProvider
    sentiment: FakeSentimentClassifier
    knowledge: FakeKnowledgeRepository
    journal: FakeTradingJournal
    watchlist: FakeWatchlistRepository
    broker: RecordingExecutionProvider
    technical_settings: FakeTechnicalSettingsRepository
    logger: RecordingLogger
    pipeline: Pipeline
    watch_stocks: WatchStocks
    manual_buy: ManualBuy
    account_history: AccountHistory
    valuation: ValuationPipeline

    def list_stock(
        self, stock_id: str, history: list[Ohlcv], realtime_price: float | None = None, realtime_age: timedelta = FRESH
    ) -> None:
        """Lists the stock. A realtime_price adds a quote stamped realtime_age before the clock's current time."""
        self.stocks.stocks[stock_id] = Stock(stock_id=stock_id, name=f"Stock {stock_id}")
        self.prices.history[stock_id] = history

        if realtime_price is not None:
            self.prices.realtime[stock_id] = Ohlcv(
                ts=self.clock.now() - realtime_age,
                open=realtime_price,
                high=realtime_price,
                low=realtime_price,
                close=realtime_price,
                volume=1000,
            )

    def publish_close(self, stock_id: str, price: float, session: date) -> None:
        """The exchange's official close for the stock in that session, as the listing feeds publish it."""
        ts = datetime.combine(session, TAIWAN_SESSION_CLOSE, TAIWAN_TIMEZONE)
        self.stocks.closes[stock_id] = Ohlcv(ts=ts, open=price, high=price, low=price, close=price, volume=1000)

    def file_eps(self, stock_id: str, cumulative_eps: dict[FiscalQuarter, float], industry: str | None = None) -> None:
        """The company's cumulative basic EPS per quarter as filed on MOPS."""
        for quarter, value in cumulative_eps.items():
            self.fundamentals.cumulative_eps.setdefault(quarter, {})[stock_id] = value

        if industry is not None:
            self.fundamentals.industries[stock_id] = industry

    def hold(self, stock_id: str, quantity: int, average_cost: float) -> None:
        self.broker.positions.append(Position(stock_id=stock_id, quantity=quantity, average_cost=average_cost))

    def watch(self, stock_id: str, watchlist_type: WatchlistType) -> None:
        """Puts an active entry on the watchlist."""
        self.watchlist.entries[(stock_id, watchlist_type)] = WatchlistEntry(
            stock_id=stock_id, watchlist_type=watchlist_type, created_at=self.clock.now(), expires_at=None
        )

    def discuss(self, stock_id: str, mentions: int, engagement: int, title: str = "[標的]") -> None:
        """Posts `mentions` social articles about the stock whose engagement adds up to `engagement`."""
        self.social.articles.extend(
            Article(
                stock_id=stock_id,
                source=InformationSource.PTT_STOCK,
                title=f"{title} {stock_id}",
                content=f"discussion {index} about {stock_id}",
                published_at=self.clock.now() - timedelta(hours=1),
                engagement=engagement if index == 0 else 0,
            )
            for index in range(mentions)
        )

    async def run_menu(
        self, choice: str, *, stock_ids: str | None = None, add_to_watchlist: bool = False, buy: Iterable[str] = ()
    ) -> PipelineStatus:
        """Runs one CLI menu choice. Answers the stock-ID prompt, the watchlist confirmation and each per-stock BUY confirmation."""
        status = await self.answer_menu(choice, stock_ids=stock_ids, add_to_watchlist=add_to_watchlist, buy=buy)
        assert status is not None, f"menu {choice} returned no status"
        return status

    async def show_account_history(self, as_of: str = "") -> None:
        """Runs menu 7 and answers its as-of-date prompt."""
        assert await self.answer_menu("7", as_of=as_of) is None

    async def answer_menu(
        self,
        choice: str,
        *,
        stock_ids: str | None = None,
        add_to_watchlist: bool = False,
        buy: Iterable[str] = (),
        as_of: str | None = None,
    ) -> PipelineStatus | None:
        buy_stock_ids = set(buy)

        def answer_prompt(prompt: str, *args, **kwargs) -> str:
            answer = as_of if "as of date" in prompt else stock_ids
            assert answer is not None, f"menu {choice} asked an unexpected prompt: {prompt!r}"
            return answer

        def answer_confirm(question: str, *args, **kwargs) -> bool:
            if "watchlist" in question.lower():
                return add_to_watchlist

            if question.startswith("BUY "):
                return question.split()[1] in buy_stock_ids

            raise AssertionError(f"menu {choice} asked an unexpected confirmation: {question!r}")

        with patch.object(Prompt, "ask", answer_prompt), patch.object(Confirm, "ask", answer_confirm):
            return await interactive.execute_menu_choice(
                choice=choice,
                pipeline=self.pipeline,
                watch_stocks=self.watch_stocks,
                manual_buy=self.manual_buy,
                account_history=self.account_history,
            )

    async def run_valuation_menu(self, choice: str, *, answers: Iterable[str], confirm: Iterable[bool] = ()) -> list[str]:
        """
        Runs menu 5 or 6, answering each text prompt and each yes/no confirmation in order.
        Returns the prompts asked, so a test can assert which questions the user saw.
        """
        remaining_answers = list(answers)
        remaining_confirms = list(confirm)
        asked: list[str] = []

        def answer_prompt(prompt: str, *args, **kwargs) -> str:
            asked.append(prompt)
            assert remaining_answers, f"menu {choice} asked an unexpected prompt: {prompt!r}"
            return remaining_answers.pop(0)

        def answer_confirm(question: str, *args, **kwargs) -> bool:
            asked.append(question)
            assert remaining_confirms, f"menu {choice} asked an unexpected confirmation: {question!r}"
            return remaining_confirms.pop(0)

        with patch.object(Prompt, "ask", answer_prompt), patch.object(Confirm, "ask", answer_confirm):
            await interactive.execute_valuation_choice(choice=choice, valuation=self.valuation, config=self.config)

        assert not remaining_answers and not remaining_confirms, f"menu {choice} left answers unused"
        return asked


def build_harness(
    *,
    now: datetime = MARKET_OPEN,
    market_open: bool = True,
    config: AppConfig | None = None,
    settings: TechnicalSettings | None = None,
) -> CliHarness:
    config = config or harness_config()
    validate_trading_environment(config)

    logger = RecordingLogger()
    clock = FakeMarketClock(now=now, market_open=market_open)
    stocks = FakeStockProvider()
    fundamentals = FakeFundamentalsProvider()
    prices = FakeOhlcvProvider()
    news = FakeNewsProvider()
    social = FakeSocialMediaProvider()
    ai = FakeAiProvider()
    sentiment = FakeSentimentClassifier()
    knowledge = FakeKnowledgeRepository()
    journal = FakeTradingJournal()
    watchlist = FakeWatchlistRepository(clock)
    technical_settings = FakeTechnicalSettingsRepository(settings or harness_settings())
    broker = RecordingExecutionProvider()

    dependencies = ProviderDependencies(
        stock_provider=stocks,
        price_provider=prices,
        fundamentals_provider=fundamentals,
        news_provider=news,
        social_media_provider=social,
        ai_provider=ai,
        sentiment_classifier=sentiment,
        knowledge_repository=knowledge,
        journal=journal,
        watchlist_repository=watchlist,
        technical_settings_repository=technical_settings,
        execution_provider=broker,
        notification_provider=None,
    )
    collect = build_collect_use_cases(config, logger, clock, dependencies)
    process = build_process_use_cases(config, logger, dependencies)
    trading = build_trading_use_cases(config, logger, clock, dependencies, collect.data_collector)
    pipeline = build_pipeline(collect, process, trading, technical_settings, logger)
    valuation = build_valuation_pipeline(config, logger, clock, dependencies, collect, process)

    return CliHarness(
        config=config,
        clock=clock,
        stocks=stocks,
        fundamentals=fundamentals,
        prices=prices,
        news=news,
        social=social,
        ai=ai,
        sentiment=sentiment,
        knowledge=knowledge,
        journal=journal,
        watchlist=watchlist,
        broker=broker,
        technical_settings=technical_settings,
        logger=logger,
        pipeline=pipeline,
        watch_stocks=trading.watch_stocks,
        manual_buy=trading.manual_buy,
        account_history=trading.account_history,
        valuation=valuation,
    )
