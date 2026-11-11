"""
The strategy search's own rules, each on its own: the mutations of each level, the breeding, the split of the sessions,
the fitness and the luck baseline. Every candidate a mutation makes is a strategy a user could save and run.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import TypeAdapter
from support.settings import shipped_config

from a_domain.model.trading.backtest import SearchInputs
from a_domain.rules.technical.formula import IndicatorValue, references
from a_domain.rules.technical.search import (
    FittestRule,
    LuckSampleRule,
    SearchFitnessRule,
    SearchTrial,
    SessionSplitRule,
    SpanResult,
    StrategyCandidate,
    StrategySearch,
    constants,
)
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.types.enums import RuleEffect, SearchLevel, SearchSpan, StrategyMutation
from a_domain.types.errors import BacktestPeriodUnavailable

CONFIG = shipped_config()
SETTINGS = CONFIG.strategy_search
BALANCED = next(strategy for strategy in CONFIG.technical.built_in_strategies if strategy.strategy_id == "balanced")
ORIGIN = StrategyCandidate(strategy=BALANCED, buy_score=70, sell_score=30)
STRATEGY_JSON = TypeAdapter(TechnicalStrategy)
NOW = datetime(2026, 11, 12, tzinfo=UTC)


def result(return_pct: float = 0.1, drawdown: float = 0.2, closed: int = 50, sessions: int = 300) -> SpanResult:
    return SpanResult(sessions=sessions, return_pct=return_pct, max_drawdown_pct=drawdown, trades=closed + 1, closed_trades=closed)


def trial(candidate: StrategyCandidate = ORIGIN, **figures: float | int) -> SearchTrial:
    return SearchTrial(candidate=candidate, results={SearchSpan.TRAIN: result(**figures)})


def children(level: SearchLevel, count: int = 80, seed: int = 7) -> list[StrategyCandidate]:
    return SETTINGS.breeding_rule().apply([trial()], {ORIGIN.key}, level, BALANCED, count, seed)


def read_ids(strategy: TechnicalStrategy) -> set[str]:
    return {
        reference.indicator_id
        for rule in strategy.rules
        for reference, _ in references(rule.condition)
        if isinstance(reference, IndicatorValue)
    }


def shape(strategy: TechnicalStrategy) -> list[tuple[str, RuleEffect, list[object]]]:
    """Each rule's name, effect and what it reads: the parts a tune never changes."""
    return [(rule.name, rule.effect, [reference for reference, _ in references(rule.condition)]) for rule in strategy.rules]


@pytest.mark.parametrize("mutation", list(StrategyMutation))
def test_every_mutation_gives_a_candidate_that_saves_and_loads_as_it_is_within_the_limits(mutation: StrategyMutation) -> None:
    rule = SETTINGS.breeding_rule().mutation_rule
    fewer_rules = replace(ORIGIN, strategy=replace(BALANCED, rules=BALANCED.rules[3:]))
    changed = 0

    for seed in range(40):
        for parent in (ORIGIN, fewer_rules):
            child = rule.apply(parent, mutation, BALANCED, seed)
            strategy = child.strategy
            assert STRATEGY_JSON.validate_json(STRATEGY_JSON.dump_json(strategy)) == strategy
            assert strategy.required_bars <= SETTINGS.max_required_bars and len(strategy.rules) <= SETTINGS.max_rules
            assert set(strategy.indicators) == read_ids(strategy) and list(strategy.indicators) == sorted(strategy.indicators)
            assert child.sell_score < child.buy_score
            changed += child.key != parent.key

    assert changed >= 40, f"{mutation} changed {changed} of 80 candidates"


def test_tune_keeps_every_rule_its_effect_and_what_it_reads_and_moves_the_numbers() -> None:
    tuned = children(SearchLevel.TUNE)

    assert all(shape(child.strategy) == shape(BALANCED) for child in tuned)
    assert any(child.strategy.indicators != BALANCED.indicators for child in tuned)
    assert any(child.strategy.scoring != BALANCED.scoring for child in tuned)
    assert any((child.buy_score, child.sell_score) != (70, 30) for child in tuned)
    assert any(
        [list(constants(rule.condition)) for rule in child.strategy.rules]
        != [list(constants(rule.condition)) for rule in BALANCED.rules]
        for child in tuned
    )


def test_select_keeps_to_the_origins_rules_and_drops_or_changes_their_effects() -> None:
    selected = children(SearchLevel.SELECT)
    names = {rule.name for rule in BALANCED.rules}

    assert all({rule.name for rule in child.strategy.rules} <= names for child in selected)
    assert any(len(child.strategy.rules) < len(BALANCED.rules) for child in selected)
    assert any(
        {rule.name: rule.effect for rule in child.strategy.rules} != {rule.name: rule.effect for rule in BALANCED.rules}
        for child in selected
    )


def test_generate_adds_rules_of_its_own_with_new_indicators() -> None:
    generated = children(SearchLevel.GENERATE, count=120)
    names = {rule.name for rule in BALANCED.rules}
    added = [rule for child in generated for rule in child.strategy.rules if rule.name not in names]

    assert added, "no generated rule in 120 children"
    assert any(indicator_id.startswith("gen_") for child in generated for indicator_id in child.strategy.indicators)


def test_the_same_population_tried_keys_and_seed_breed_the_same_children_and_none_tried_before() -> None:
    first = children(SearchLevel.GENERATE, seed=3)
    again = children(SearchLevel.GENERATE, seed=3)
    other = children(SearchLevel.GENERATE, seed=4)
    tried = {child.key for child in first[:10]}
    later = SETTINGS.breeding_rule().apply([trial()], tried, SearchLevel.GENERATE, BALANCED, 30, 3)

    assert [child.key for child in first] == [child.key for child in again]
    assert [child.key for child in first] != [child.key for child in other]
    assert len({child.key for child in first}) == len(first) and ORIGIN.key not in {child.key for child in first}
    assert not tried & {child.key for child in later}


def test_the_spans_split_the_sessions_from_the_first_in_time_order_without_overlap() -> None:
    sessions = [date(2024, 1, 1) + timedelta(days=day) for day in range(200)]
    spans = SessionSplitRule(train_share=0.5, validation_share=0.25).apply(sessions, sessions[40])
    held = {span: [session for session in sessions if first <= session <= last] for span, (first, last) in spans.items()}

    assert list(spans) == [SearchSpan.TRAIN, SearchSpan.VALIDATION, SearchSpan.HOLDOUT]
    assert [len(held[span]) for span in spans] == [80, 40, 40]
    assert sum(held.values(), []) == sessions[40:]
    assert (
        spans[SearchSpan.TRAIN][1] < spans[SearchSpan.VALIDATION][0] and spans[SearchSpan.VALIDATION][1] < spans[SearchSpan.HOLDOUT][0]
    )

    with pytest.raises(BacktestPeriodUnavailable, match="needs sessions for train, validation and the holdout"):
        SessionSplitRule(train_share=0.5, validation_share=0.25).apply(sessions, sessions[-2])


def test_fitness_is_the_return_less_the_drawdown_penalty_and_too_few_closed_trades_rank_below_any_with_enough() -> None:
    fitness = SearchFitnessRule(min_trades_per_100_sessions=10, drawdown_penalty=0.5)

    assert fitness.apply(result(return_pct=0.2, drawdown=0.1, closed=30)) == pytest.approx(0.15)
    assert fitness.apply(result(return_pct=-1, drawdown=1, closed=30)) == fitness.floor == -1.5
    assert fitness.apply(result(return_pct=3, drawdown=0, closed=29)) < fitness.floor
    assert fitness.apply(result(return_pct=0, drawdown=0, closed=29)) > fitness.apply(result(return_pct=3, drawdown=0, closed=5))


def test_the_fittest_are_the_best_on_the_span_and_the_first_tried_of_a_tie() -> None:
    trials = [trial(return_pct=value) for value in (0.1, 0.3, 0.2, 0.3)]

    assert FittestRule(fitness_rule=SETTINGS.fitness_rule()).apply(trials, SearchSpan.TRAIN, 3) == [trials[1], trials[3], trials[2]]


def test_the_luck_sample_draws_only_candidates_that_traded_enough_on_train() -> None:
    trials = [trial(closed=closed, return_pct=index / 100) for index, closed in enumerate([0, 50, 50, 1, 50, 50])]
    rule = LuckSampleRule(fitness_rule=SETTINGS.fitness_rule())

    assert set(map(id, rule.apply(trials, 10, seed=1))) == {id(trials[index]) for index in (1, 2, 4, 5)}
    assert rule.apply(trials, 2, seed=1) == rule.apply(trials, 2, seed=1)


def test_a_winners_luck_percentile_is_the_share_of_the_sample_below_its_holdout_return_a_tie_counting_half() -> None:
    winner = SearchTrial(candidate=ORIGIN, results={span: result(return_pct=0.1) for span in SearchSpan})
    search = StrategySearch(
        inputs=SearchInputs(
            strategy_id="balanced", level=SearchLevel.TUNE, random_seed=1, population=4, generations=1, buy_score=70, sell_score=30
        ),
        started_at=NOW,
        finished_at=NOW,
        finalists=1,
        breeding=SETTINGS.breeding_rule(),
        split=SETTINGS.split_rule(),
        spans={span: (date(2025, 1, 1), date(2025, 2, 1)) for span in SearchSpan},
        tried=5,
        origin=winner,
        winners=[winner],
        luck_returns=[0.0, 0.1, 0.2, -0.3],
        benchmark=[],
    )

    assert search.luck_percentiles == [pytest.approx(2.5 / 4)]
    assert search.benchmark_returns == {span: None for span in SearchSpan}
