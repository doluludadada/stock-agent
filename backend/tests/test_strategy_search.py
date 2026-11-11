"""
A strategy search through the Pipeline over fake ports, on markets built for it. Where a known rule makes money on
every span the search finds it and its winner beats the luck baseline; on pure noise its winner does not. The holdout
is read only for the report, and the search orders nothing, asks no AI and saves no strategy or setting.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from random import Random
from typing import NoReturn

import pytest
from support.harness import HISTORY_LAST_SESSION, CliHarness, build_harness, harness_config
from support.settings import PLACEHOLDER, environment_setup

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.backtest import SearchInputs
from a_domain.rules.technical.formula import Comparison, LatestPrice
from a_domain.rules.technical.search import StrategySearch
from a_domain.rules.technical.strategy import TechnicalRule, TechnicalScoring, TechnicalStrategy
from a_domain.types.enums import ComparisonOperator, MarketIndex, RuleEffect, SearchLevel, SearchSpan, SystemEnvironment
from b_application.config.market_data_config import MarketHoursConfig
from b_application.config.trading_config import TechnicalConfig
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from c_infrastructure.technical.candidate_backtester import ProcessPoolCandidateBacktester
from d_presentation import dependencies
from d_presentation.dependencies import create_process_state, get_project_root, load_settings, open_runtime

pytestmark = pytest.mark.asyncio

HELD_DAYS = 400
"""A run reads 120 days of history first, so the spans hold 280 sessions: 140 to train, 70 to validate, 70 held out."""

PLANTED = TechnicalStrategy(
    strategy_id="planted",
    name="Planted",
    indicators={},
    scoring=TechnicalScoring(base_score=90),
    rules=(
        TechnicalRule(
            name="Minimum Price Check",
            effect=RuleEffect.BLOCK_ON_FAIL,
            condition=Comparison(operator=ComparisonOperator.GTE, left=LatestPrice(), right=40.0),
        ),
    ),
)


def bars(closes: list[float]) -> list[Ohlcv]:
    """One bar per calendar day up to the harness's last session, opening at the close before it, half a dollar of range."""
    last_close_at = datetime.combine(HISTORY_LAST_SESSION, MarketHoursConfig().close, TAIWAN_TIMEZONE)
    opens = [closes[0], *closes[:-1]]

    return [
        Ohlcv(
            ts=last_close_at - timedelta(days=len(closes) - 1 - day),
            open=open_,
            high=max(open_, close) + 0.5,
            low=min(open_, close) - 0.5,
            close=close,
            volume=100_000,
        )
        for day, (open_, close) in enumerate(zip(opens, closes, strict=True))
    ]


def search_harness(stocks: dict[str, list[float]]) -> CliHarness:
    """The planted strategy as the only built-in one, small searches in this process, and a flat TAIEX."""
    config = harness_config()
    search_settings = config.strategy_search.model_copy(
        update={
            "workers": 0,
            "finalists": 4,
            "winners": 2,
            "luck_sample": 40,
            "min_trades_per_100_sessions": 0,
            "max_required_bars": 10,
        }
    )
    technical = TechnicalConfig(built_in_strategies=(PLANTED,), initial_strategy_id="planted")
    harness = build_harness(config=config.model_copy(update={"strategy_search": search_settings, "technical": technical}))

    for stock_id, closes in stocks.items():
        harness.list_stock(stock_id, bars(closes))

    harness.prices.index_history[MarketIndex.TAIEX] = bars([20_000.0] * HELD_DAYS)
    return harness


def planted_market() -> dict[str, list[float]]:
    """
    Three stocks above $100 climb 0.3% a day. Three under $50 slide 1% a day for 60 days and jump back, so a BUY of one
    while it is above the origin's $40 stops out 10% down before the jump. A price check above $50 buys only climbers.
    """
    climbers = {f"11{index}": [100.0 * (1 + index / 10) * 1.003**day for day in range(HELD_DAYS)] for index in range(3)}
    sliders = {f"22{index}": [50.0 * 0.99 ** ((day + 20 * index) % 60) for day in range(HELD_DAYS)] for index in range(3)}

    return climbers | sliders


def noise_market(seed: int) -> dict[str, list[float]]:
    """Six random walks of no drift between about $30 and $120: no price level tells what comes next."""
    random = Random(seed)
    market: dict[str, list[float]] = {}

    for index in range(6):
        closes = [30.0 + 18 * index]

        for _ in range(HELD_DAYS - 1):
            closes.append(closes[-1] * (1 + random.gauss(0, 0.02)))

        market[f"33{index}"] = closes

    return market


def inputs(seed: int = 1, level: SearchLevel = SearchLevel.TUNE) -> SearchInputs:
    return SearchInputs(strategy_id="planted", level=level, random_seed=seed, population=8, generations=6, buy_score=80, sell_score=30)


async def test_a_search_finds_the_planted_rule_and_its_winner_beats_the_origin_the_taiex_and_the_luck_baseline() -> None:
    harness = search_harness(planted_market())

    search, location = await harness.pipeline.search_strategies(inputs())

    winner = search.winners[0]
    threshold = winner.candidate.strategy.rules[0].condition
    assert isinstance(threshold, Comparison) and isinstance(threshold.right, float) and threshold.right > 50
    assert all(winner.results[span].return_pct > search.origin.results[span].return_pct for span in SearchSpan)
    assert all(winner.results[span].return_pct > 0 == search.benchmark_returns[span] for span in SearchSpan)
    assert search.luck_percentiles[0] is not None and search.luck_percentiles[0] >= 0.75
    assert (search.tried, len(search.luck_returns)) == (49, 40)
    assert (location, harness.dependencies.strategy_search_repository.searches) == ("search 1", [search])


async def test_on_pure_noise_the_winners_do_not_beat_the_luck_baseline() -> None:
    percentiles = []

    for seed in range(1, 6):
        search, _ = await search_harness(noise_market(seed)).pipeline.search_strategies(inputs(seed))
        percentiles.append(search.luck_percentiles[0])

    assert sum(percentiles) / len(percentiles) < 0.6, percentiles


async def test_the_holdout_decides_nothing_corrupt_holdout_bars_leave_the_same_winners() -> None:
    market = planted_market()
    search = (await search_harness(market).pipeline.search_strategies(inputs(level=SearchLevel.GENERATE)))[0]
    holdout_first = search.spans[SearchSpan.HOLDOUT][0]
    random = Random(5)
    first_day = HISTORY_LAST_SESSION - timedelta(days=HELD_DAYS - 1)
    corrupt = {
        stock_id: [
            close if first_day + timedelta(days=day) < holdout_first else close * random.uniform(0.2, 3)
            for day, close in enumerate(closes)
        ]
        for stock_id, closes in market.items()
    }

    again = (await search_harness(corrupt).pipeline.search_strategies(inputs(level=SearchLevel.GENERATE)))[0]

    assert [winner.candidate.key for winner in again.winners] == [winner.candidate.key for winner in search.winners]
    assert seen_before_the_holdout(again) == seen_before_the_holdout(search)
    assert [winner.results[SearchSpan.HOLDOUT] for winner in again.winners] != [
        winner.results[SearchSpan.HOLDOUT] for winner in search.winners
    ]


def seen_before_the_holdout(search: StrategySearch) -> list[object]:
    return [(trial.results[SearchSpan.TRAIN], trial.results[SearchSpan.VALIDATION]) for trial in [search.origin, *search.winners]]


async def test_a_search_orders_nothing_asks_no_ai_and_changes_no_saved_strategy_or_setting() -> None:
    harness = search_harness(planted_market())
    saved = harness.technical_settings.saved

    await harness.pipeline.search_strategies(inputs(level=SearchLevel.GENERATE))

    assert (harness.broker.placed, harness.journal.runs, harness.journal.signals, harness.ai.calls) == ([], {}, [], [])
    assert harness.technical_settings.saved == saved
    assert harness.prices.realtime_requests == []


async def test_backtests_in_processes_equal_those_in_this_process() -> None:
    harness = search_harness(planted_market())
    search, _ = await harness.pipeline.search_strategies(replace(inputs(), generations=1))
    bars_matrix = await harness.dependencies.bar_matrix_provider.load()
    assert bars_matrix is not None
    candidates = [trial.candidate for trial in [search.origin, *search.winners]]
    first, last = search.spans[SearchSpan.VALIDATION]
    pooled = ProcessPoolCandidateBacktester(harness.config, harness.clock, 2)

    in_processes = await pooled.backtest(bars_matrix, candidates, first, last)
    here = await ProcessPoolCandidateBacktester(harness.config, harness.clock, 0).backtest(bars_matrix, candidates, first, last)

    assert in_processes == here == [trial.results[SearchSpan.VALIDATION] for trial in [search.origin, *search.winners]]


async def test_the_search_command_opens_its_runtime_without_a_broker_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the key pair a login needs, broker_login=False still makes none: the search never reaches the broker."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ACCOUNTS_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLACEHOLDER)
    config = environment_setup(load_settings(get_project_root()), SystemEnvironment.DEV).model_copy(update={"project_root": tmp_path})

    def no_login() -> NoReturn:
        raise AssertionError("the search command loaded the Shioaji client")

    monkeypatch.setattr(dependencies, "import_shioaji", no_login)

    async with open_runtime(config, create_process_state(config), broker_login=False) as runtime:
        assert (runtime.real_broker, runtime.shioaji, runtime.realtime_quotes) == (None, None, False)
