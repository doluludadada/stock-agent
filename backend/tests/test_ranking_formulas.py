"""
The ranking's formulas: each factor a formula can name, the market filter that holds cash, the registry the settings
hold and what they refuse, a settings file from before the formulas refused, and a switch of the active formula from the
settings page, which changes the list, every score, the backtest and a follow together and answers nothing of the
formula before.
"""

import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from support.harness import ADMINISTRATOR, ADMINISTRATOR_PASSWORD, CliHarness, runtime_for
from support.ranking_site import formulas_project
from support.settings import small_formula
from support.web import app_of, client_at, ended, sign_in, write
from test_ranking_follow import FORMULA, SESSIONS, close_of, ranking_of, site
from test_ranking_rule import D, bar, history_of, ranked_market, revenue
from test_web_admin import save, text_of
from trading_stack import SilentLogger, StockDirectory

from a_domain.model.trading.account import Account, Position
from a_domain.model.trading.ranking_formula import NearnessToHigh, PriceMomentum, RankingFormula, RevenueYoy
from a_domain.rules.trading.follow import RankingHoldingsRule
from a_domain.rules.trading.ranking import (
    DecisionSessionsRule,
    ListedHistory,
    MonthlyRankingRule,
    RankingHistory,
    RankingHistoryRule,
    price_momentum,
    revenue_yoy,
)
from a_domain.rules.trading.ranking_backtest import RankingBacktestRule, RankingPortfolioRule
from a_domain.rules.trading.ranking_standing import RankingStandingRule
from a_domain.types.enums import RankingExclusion, SettingsFile, TradeAction
from a_domain.types.errors import RankingUnavailable, UnknownRankingFormula
from b_application.config.settings_loader import InvalidSettingsError, load_settings, parsed_document, settings_fields
from c_infrastructure.market.daily_bar_matrix_provider import DailyBarMatrixProvider, KeptRankingHistory
from d_presentation.cli import ranking as cli

pytestmark = pytest.mark.asyncio

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = (ROOT / "config" / "appsetting.yaml").read_text(encoding="utf-8")
CASH = replace(FORMULA, name="cash_under_two", cash_under_average_sessions=2)
"""The follow tests' formula, holding cash while 0050 closed under its average of two sessions at the decision."""

ONE = replace(FORMULA, name="best_one", top=1)


# ----------------------------------- Rules ------------------------------------ #


def test_revenue_yoy_is_the_latest_months_over_the_same_months_a_year_before_and_none_without_either() -> None:
    held = np.array(
        [[10.0, 10.0, *[1.0] * 10, 20.0, 40.0], [0.0, 0.0, *[1.0] * 10, 20.0, 40.0], [10.0, np.nan, *[1.0] * 10, 20.0, 40.0]]
    )

    np.testing.assert_allclose(revenue_yoy(held, 13, 2), [2.0, np.nan, np.nan])
    np.testing.assert_allclose(revenue_yoy(held, 13, 1), [3.0, np.nan, np.nan])
    assert np.isnan(revenue_yoy(held, 12, 2)).all() and np.isnan(revenue_yoy(held, 14, 2)).all()


def test_price_momentum_is_the_level_before_the_skipped_sessions_over_the_level_at_the_first_and_none_for_a_later_listing() -> None:
    history = history_of(
        {
            "2330": [bar(day, close) for day, close in zip(D[:5], [100, 110, 121, 130, 125], strict=True)],
            "2317": [bar(day, close) for day, close in zip(D[1:5], [50, 55, 60, 65], strict=True)],
        }
    )

    np.testing.assert_allclose(price_momentum(history, 4, 4, 1), [np.nan, 0.3])
    np.testing.assert_allclose(price_momentum(history, 4, 3, 0), [0.3, 125 / 110 - 1])
    assert np.isnan(price_momentum(history, 2, 3, 1)).all()


def test_a_formula_ranks_by_the_factors_it_names_in_their_order() -> None:
    by_momentum = RankingFormula(
        name="momentum_alone",
        factors=(PriceMomentum(sessions=2, skip_sessions=0),),
        top=2,
        min_close=10,
        min_traded_value=1_000_000,
        traded_value_sessions=2,
    )

    ranking = MonthlyRankingRule(formula=by_momentum, benchmark_id="0050").apply(ranked_market(), 2, date(2026, 2, 1), {})

    assert [stock.stock_id for stock in ranking.stocks] == ["1101", "2330"]
    assert [(len(stock.factors), stock.factors[0].value) for stock in ranking.stocks] == [
        (1, pytest.approx(0.1)),
        (1, pytest.approx(0.1)),
    ]
    assert (ranking.formula, ranking.scored) == (by_momentum, 4)


def falling_benchmark(market: RankingHistory) -> RankingHistory:
    """`market` with 0050 at 52, 51, 50: under its average of two sessions at the last one."""
    row = market.bars.stock_ids.index("0050")
    level = market.level.copy()
    level[row] = [52.0, 51.0, 50.0]
    return replace(market, level=level)


def cash_rule(sessions: int = 2) -> MonthlyRankingRule:
    return MonthlyRankingRule(
        formula=small_formula(
            top=2,
            min_close=10,
            min_traded_value=1_000_000,
            traded_value_sessions=2,
            high_sessions=3,
            short_months=1,
            long_months=2,
            cash_under_average_sessions=sessions,
        ),
        benchmark_id="0050",
    )


def test_a_formula_holds_cash_while_the_benchmark_is_under_its_average_and_still_measures_its_factors() -> None:
    cash = cash_rule().apply(falling_benchmark(ranked_market()), 2, date(2026, 2, 1), {})
    invested = cash_rule().apply(ranked_market(), 2, date(2026, 2, 1), {})

    assert (cash.holds_cash, cash.stocks, cash.universe, cash.scored) == (True, [], 4, 3)
    assert (invested.holds_cash, [stock.stock_id for stock in invested.stocks]) == (False, ["2330", "1101"])


def test_the_filter_is_off_while_the_history_is_shorter_than_its_average_and_refused_without_the_benchmark() -> None:
    short = cash_rule(sessions=4).apply(falling_benchmark(ranked_market()), 2, date(2026, 2, 1), {})

    assert (short.holds_cash, len(short.stocks)) == (False, 2)

    with pytest.raises(RankingUnavailable, match="holds no bar of 0056"):
        replace(cash_rule(), benchmark_id="0056").apply(ranked_market(), 2, date(2026, 2, 1), {})


def test_a_stock_keeps_its_score_while_the_formula_holds_cash_and_is_in_no_top() -> None:
    market = falling_benchmark(ranked_market())

    standings = RankingStandingRule(ranking_rule=cash_rule()).apply(market, 2, date(2026, 2, 1), ["2330", "2603"])

    best = standings["2330"]
    assert (best.place, best.score, best.holds_cash, best.in_top, best.formula.top) == (1, 100.0, True, False, 2)
    assert (standings["2603"].exclusion, standings["2603"].place) == (RankingExclusion.NO_REVENUE_HISTORY, None)


def test_a_stock_without_a_factor_says_which_history_the_first_factor_it_lacks_reads() -> None:
    yoy_first = RankingFormula(
        name="yoy_and_high",
        factors=(NearnessToHigh(high_sessions=3), RevenueYoy(months=1)),
        top=2,
        min_close=10,
        min_traded_value=1_000_000,
        traded_value_sessions=2,
    )
    rule = RankingStandingRule(ranking_rule=MonthlyRankingRule(formula=yoy_first, benchmark_id="0050"))

    late = rule.apply(ranked_market(listed_late="2330"), 2, date(2026, 2, 1), ["2330", "2317"])

    assert late["2330"].exclusion == RankingExclusion.SHORT_PRICE_HISTORY
    assert late["2317"].exclusion == RankingExclusion.NO_REVENUE_HISTORY


def test_a_follow_of_a_formula_that_holds_cash_leaves_every_holding_and_one_that_ranks_nothing_keeps_them() -> None:
    account = Account(cash=0, positions=[Position(stock_id=stock_id, quantity=1, average_cost=1) for stock_id in ("2603", "1101")])
    nothing = ranking_of()

    to_cash = RankingHoldingsRule().apply(replace(nothing, holds_cash=True), account.stock_ids)
    kept = RankingHoldingsRule().apply(nothing, account.stock_ids)

    assert (to_cash.held, to_cash.lacking, to_cash.left, to_cash.open) == ([], [], ["1101", "2603"], ["1101", "2603"])
    assert (kept.left, kept.open) == ([], [])


M = [date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 5), date(2026, 4, 3), date(2026, 4, 6), date(2026, 4, 7)]


def test_the_replay_sells_to_cash_at_a_cash_decision_and_counts_its_turnover_and_its_years_ahead() -> None:
    """March ranks 2330 and 2317 while 0050 rises. At April's decision 0050 closed under its average, so April holds cash."""
    bars = {
        "2330": [bar(day, close, open_price=close) for day, close in zip(M, [100, 110, 121, 121, 110, 110], strict=True)],
        "2317": [bar(day, 50.0, open_price=50.0) for day in M],
        "0050": [bar(day, close) for day, close in zip(M, [100, 101, 102, 99, 98, 97], strict=True)],
    }
    revenues = [revenue(stock_id, 2026, month, 100.0 * month) for stock_id in ("2330", "2317") for month in (1, 2, 3)]
    formula = small_formula(
        top=2, traded_value_sessions=1, high_sessions=1, short_months=1, long_months=2, cash_under_average_sessions=2
    )
    rule = RankingBacktestRule(
        decision_rule=DecisionSessionsRule(decision_day=3, deadline_day=1),
        ranking_rule=MonthlyRankingRule(formula=formula, benchmark_id="0050"),
        portfolio_rule=RankingPortfolioRule(fee_rate=0.001, tax_rate=0.003, benchmark_id="0050", sessions_per_year=245),
    )

    backtest = rule.apply(history_of(bars, revenues), {}, M[0], M[-1])

    assert [(ranking.holds_cash, len(ranking.stocks)) for ranking in backtest.rankings] == [(False, 2), (True, 0)]
    assert backtest.holdings == {M[1]: ["2317", "2330"], M[4]: []}
    assert backtest.equity_curve[M[4]] == backtest.equity_curve[M[5]]
    assert (backtest.formula, backtest.turnover) == (formula, pytest.approx(0.5))
    assert (backtest.years_ahead, list(backtest.yearly_returns)) == (1, [2026])


# ---------------------------------- Settings ---------------------------------- #


def refused(text: str) -> list[tuple[str | None, int | None, str]]:
    with pytest.raises(InvalidSettingsError) as error:
        load_settings(ROOT, {SettingsFile.APPSETTING: text})

    return [(problem.path, problem.line, problem.message) for problem in error.value.problems]


def line_of(text: str, needle: str) -> int:
    return text[: text.index(needle)].count("\n") + 1


def test_the_shipped_settings_name_three_formulas_and_the_one_of_ten_stocks_is_active() -> None:
    """The owner's choice of 2026-11-19: the shipped formula's factors and universe, holding the best 10 in place of 20."""
    ranking = load_settings(ROOT).ranking
    shipped, ten, cash = ranking.formulas

    assert [formula.name for formula in ranking.formulas] == ["revenue_and_high", "revenue_and_high_top10", "revenue_and_high_cash_60"]
    assert (ranking.active_formula, ranking.formula()) == ("revenue_and_high_top10", ten)
    assert ([formula.top for formula in ranking.formulas], replace(ten, name=shipped.name, top=shipped.top)) == ([20, 10, 20], shipped)
    assert [formula.cash_under_average_sessions for formula in ranking.formulas] == [None, None, 60]
    assert [[factor.kind.value for factor in formula.factors] for formula in ranking.formulas] == [
        ["revenue_acceleration", "nearness_to_high"],
        ["revenue_acceleration", "nearness_to_high"],
        ["revenue_acceleration", "nearness_to_high"],
    ]
    assert cash.top == 20

    with pytest.raises(UnknownRankingFormula, match="revenue_and_high, revenue_and_high_top10, revenue_and_high_cash_60"):
        ranking.formula("best_lately")


WITH_A_THIRD = SHIPPED.replace(
    "  # The revenue trend of the stock page",
    """    - name: revenue_yoy_and_high
      top: 20
      min_close: 10
      min_traded_value: 30000000
      traded_value_sessions: 20
      cash_under_average_sessions: 120
      factors:
        - kind: revenue_yoy
          months: 3
        - kind: nearness_to_high
          high_sessions: 250
  # The revenue trend of the stock page""",
    1,
)
"""The shipped settings with a formula of the other factors after the shipped three, so each refusal below has one place."""

YOY = "        - kind: revenue_yoy\n"
MONTHS = "          months: 3\n"
REFUSED = {
    "unknown-factor": (YOY, "        - kind: sharpe_ratio\n", "ranking.formulas.3.factors.0", "does not match any", "- kind: sharpe"),
    "unknown-factor-setting": (
        MONTHS,
        f"{MONTHS}          weight: 2\n",
        "ranking.formulas.3.factors.0.revenue_yoy.weight",
        "Unexpected",
        YOY,
    ),
    "missing-window": (MONTHS, "", "ranking.formulas.3.factors.0.revenue_yoy.months", "Field required", YOY),
    "unknown-formula-setting": (
        "      cash_under_average_sessions: 120\n",
        "      stop_loss: 0.1\n",
        "ranking.formulas.3.stop_loss",
        "Unexpected",
        "stop_loss",
    ),
    "unknown-active": (
        "  active_formula: revenue_and_high_top10\n",
        "  active_formula: best_lately\n",
        "ranking",
        "names none of",
        "ranking:\n",
    ),
    "same-name": (
        "    - name: revenue_and_high_cash_60\n",
        "    - name: revenue_and_high\n",
        "ranking",
        "the same name",
        "ranking:\n",
    ),
}


@pytest.mark.parametrize(("old", "new", "path", "words", "at"), REFUSED.values(), ids=REFUSED.keys())
def test_a_formula_the_ranking_cannot_express_is_refused_at_the_start_where_the_file_writes_it(
    old: str, new: str, path: str, words: str, at: str
) -> None:
    assert WITH_A_THIRD.count(old) == 1
    text = WITH_A_THIRD.replace(old, new)

    [(found, line, message)] = refused(text)

    assert (found, words in message, line) == (path, True, line_of(text, at))


def older_file() -> str:
    """The shipped file as it was before the formulas: the shipped formula's parameters as settings of `ranking`."""
    start, end = SHIPPED.index("  active_formula:"), SHIPPED.index("  # The revenue trend of the stock page")
    older = (
        SHIPPED[:start]
        + "  top: 20\n  min_close: 10\n  min_traded_value: 30000000\n  traded_value_sessions: 20\n  high_sessions: 250\n"
    )
    return older + SHIPPED[end:]


def project_of(tmp_path: Path, appsetting: str) -> Path:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    (tmp_path / "config" / "appsetting.yaml").write_text(appsetting, encoding="utf-8")
    return tmp_path


def test_a_settings_file_from_before_the_formulas_is_refused_and_the_refusal_names_each_setting_a_formula_holds_now(
    tmp_path: Path,
) -> None:
    text = older_file()
    project = project_of(tmp_path, text)

    with pytest.raises(InvalidSettingsError) as error:
        load_settings(project)

    assert [(problem.path, problem.line, problem.message) for problem in error.value.problems] == [
        (f"ranking.{key}", line_of(text, f"  {key}:"), "names no setting")
        for key in ("top", "min_close", "min_traded_value", "traded_value_sessions", "high_sessions")
    ]
    assert "appsetting.yaml" in str(error.value) and "ranking.top: names no setting" in str(error.value)


def test_a_file_that_names_its_formulas_and_still_sets_a_setting_a_formula_holds_now_is_refused() -> None:
    text = SHIPPED.replace("  decision_day: 13\n", "  decision_day: 13\n  top: 5\n", 1)

    assert refused(text) == [("ranking.top", line_of(text, "  top: 5"), "names no setting")]


def test_the_settings_form_offers_the_active_formula_as_a_choice_among_the_names_the_file_holds() -> None:
    documents = {SettingsFile.APPSETTING: parsed_document(SettingsFile.APPSETTING, SHIPPED)}

    fields = {field.path: field for field in settings_fields(documents)}

    active = fields["ranking.active_formula"]
    assert (active.kind.value, active.group.value, active.value) == ("choice", "ranking", "revenue_and_high_top10")
    assert active.options == ("revenue_and_high", "revenue_and_high_top10", "revenue_and_high_cash_60")
    assert (fields["ranking.formulas"].kind.value, fields["ranking.formulas"].group.value) == ("structure", "advanced")
    assert "ranking.kept_backtests" not in fields and "ranking.top" not in fields


# ----------------------------- The matrix provider ---------------------------- #


class CountedHistory:
    """A price source and a revenue archive that hold one small market and count how often its bars are read."""

    def __init__(self) -> None:
        self.reads = 0
        self.revision = 0

    async def listed_fingerprint(self) -> tuple[object, ...]:
        return (self.revision,)

    async def revenue_fingerprint(self) -> tuple[object, ...]:
        return ()

    async def listed_history(self) -> ListedHistory:
        self.reads += 1
        market = ranked_market()
        change = np.full(market.bars.close.shape, np.nan)
        return ListedHistory(bars=market.bars, change=change, ex_right_reference=change)

    async def revenue_history(self, first: date, last: date) -> dict[tuple[str, int, int], float | None]:
        return {(stock_id, 2026, month): 100.0 * month for stock_id in ("2330", "2317", "1101") for month in (1, 2)}


def provider_over(source: CountedHistory, kept: KeptRankingHistory, daily_limit: float = 0.105, kept_backtests: int = 2) -> Any:
    rule = RankingHistoryRule(daily_limit=daily_limit)
    return DailyBarMatrixProvider(StockDirectory(), source, source, None, rule, SilentLogger(), kept, kept_backtests)  # pyright: ignore[reportArgumentType]


def replay_rule(formula: RankingFormula) -> RankingBacktestRule:
    return RankingBacktestRule(
        decision_rule=DecisionSessionsRule(decision_day=3, deadline_day=1),
        ranking_rule=MonthlyRankingRule(formula=formula, benchmark_id="0050"),
        portfolio_rule=RankingPortfolioRule(fee_rate=0.001, tax_rate=0.003, benchmark_id="0050", sessions_per_year=245),
    )


async def test_the_runtimes_of_one_process_share_the_rankings_history_and_read_it_again_only_when_it_changed() -> None:
    source, kept = CountedHistory(), KeptRankingHistory()
    before_the_save, after_the_save = provider_over(source, kept), provider_over(source, kept)

    first = await before_the_save.load_ranking_history()
    again = await after_the_save.load_ranking_history()
    other_limit = await provider_over(source, kept, daily_limit=0.07).load_ranking_history()
    source.revision += 1
    newer = await after_the_save.load_ranking_history()

    assert first is again and source.reads == 3
    assert other_limit is not first and newer is not other_limit
    assert await provider_over(source, KeptRankingHistory()).load_ranking_history() is not newer and source.reads == 4


async def test_a_replay_is_kept_by_its_formula_and_period_while_its_history_stands_and_only_so_many_are_kept() -> None:
    source, kept = CountedHistory(), KeptRankingHistory()
    provider = provider_over(source, kept)
    history = await provider.load_ranking_history()
    formula = small_formula(top=2, traded_value_sessions=1, high_sessions=1, short_months=1, long_months=2)
    two, one = replay_rule(formula), replay_rule(replace(formula, top=1))

    first = await provider.ranking_backtest(history, two, {}, D[0], D[-1])
    same = await provider_over(source, kept).ranking_backtest(history, replay_rule(replace(formula)), {}, D[0], D[-1])
    other_formula = await provider.ranking_backtest(history, one, {}, D[0], D[-1])
    named = await provider.ranking_backtest(history, one, {"1101": "Taiwan Cement"}, D[0], D[-1])
    shorter = await provider.ranking_backtest(history, two, {}, D[0], D[1])

    assert same is first and other_formula is not first
    assert (first.formula.top, other_formula.formula.top, len(shorter.equity_curve) < len(first.equity_curve)) == (2, 1, True)
    assert named is not other_formula and named.rankings[0].stocks[0].stock_name == "Taiwan Cement"
    assert len(kept.backtests) == 2 and await provider.ranking_backtest(history, two, {}, D[0], D[-1]) is not first

    source.revision += 1
    rebuilt = await provider.load_ranking_history()

    assert kept.backtests == {} and rebuilt is not history
    assert await provider.ranking_backtest(history, two, {}, D[0], D[-1]) is not None and kept.backtests == {}


# ------------------------------ The switch, live ------------------------------ #


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of config/ whose ranking holds the follow tests' formula, a best-one variant and a cash variant."""
    return formulas_project(tmp_path, monkeypatch, FORMULA, ONE, CASH)


def falling_site(project: Path) -> CliHarness:
    """The follow tests' site on the project's settings, with 0050 closing under its two-session average at the decision."""
    harness = site(settings_root=project, sinopac=True, formulas=(FORMULA, ONE, CASH))
    closes = [186.0, 187.0, 188.0, 180.0, 181.0, 182.0, 183.0]
    harness.prices.history["0050"] = [close_of(day, close) for day, close in zip(SESSIONS, closes, strict=True)]
    return harness


async def answers(client: httpx.AsyncClient) -> dict[str, Any]:
    period = {"first": "2026-10-01", "last": "2026-10-16"}
    return {
        "latest": (await client.get("/v1/rankings/latest")).json(),
        "score": (await client.get("/v1/market/stocks/2317/ranking")).json(),
        "holdings": (await client.get("/v1/holdings", params={"sources": ["mock"]})).json(),
        "backtest": (await client.get("/v1/rankings/backtest", params=period)).json(),
        "follow": (await client.get("/v1/rankings/follow")).json(),
        "evidence": (await client.get("/v1/rankings/formulas", params=period)).json(),
    }


async def test_a_switch_of_the_active_formula_changes_the_list_the_scores_the_backtest_and_the_follow_together(project: Path) -> None:
    harness = falling_site(project)
    harness.hold("2317", 1000, 50.0)

    async with app_of(harness) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        form = {field["path"]: field for field in (await client.get("/v1/admin/settings")).json()}
        first = await answers(client)
        to_one = await save(client, ("ranking.active_formula", "best_one"))
        one = await answers(client)
        to_cash = await save(client, ("ranking.active_formula", "cash_under_two"))
        cash = await answers(client)
        back = await save(client, ("ranking.active_formula", "revenue_and_high"))
        again = await answers(client)

    assert form["ranking.active_formula"]["options"] == ["revenue_and_high", "best_one", "cash_under_two"]
    assert (to_one.status_code, to_cash.status_code, back.status_code) == (200, 200, 200)
    assert "active_formula: revenue_and_high\n" in text_of(project)

    def read(answer: dict[str, Any]) -> tuple[Any, ...]:
        [holding] = answer["holdings"]["holdings"]
        return (
            answer["latest"]["formula"]["name"],
            [stock["stock_id"] for stock in answer["latest"]["stocks"]],
            answer["latest"]["holds_cash"],
            (answer["score"]["formula"]["name"], answer["score"]["score"], answer["score"]["in_top"], answer["score"]["holds_cash"]),
            (holding["standing"]["formula"]["name"], holding["standing"]["in_top"]),
            (answer["backtest"]["formula"]["name"], [stock["stock_id"] for stock in answer["backtest"]["rankings"][-1]["stocks"]]),
            (answer["follow"]["holdings"]["lacking"], answer["follow"]["holdings"]["left"]),
            [(row["formula"]["name"], row["active"]) for row in answer["evidence"]],
        )

    names = ["revenue_and_high", "best_one", "cash_under_two"]
    assert read(first) == (
        "revenue_and_high",
        ["2330", "2317"],
        False,
        ("revenue_and_high", 50.0, True, False),
        ("revenue_and_high", True),
        ("revenue_and_high", ["2330", "2317"]),
        (["2330"], []),
        list(zip(names, [True, False, False], strict=True)),
    )
    assert read(one) == (
        "best_one",
        ["2330"],
        False,
        ("best_one", 50.0, False, False),
        ("best_one", False),
        ("best_one", ["2330"]),
        (["2330"], ["2317"]),
        list(zip(names, [False, True, False], strict=True)),
    )
    assert read(cash) == (
        "cash_under_two",
        [],
        True,
        ("cash_under_two", 50.0, False, True),
        ("cash_under_two", False),
        ("cash_under_two", []),
        ([], ["2317"]),
        list(zip(names, [False, False, True], strict=True)),
    )
    assert read(again) == read(first)
    assert [row["record"] for row in again["evidence"]] == [row["record"] for row in first["evidence"]]
    assert {row["liquid_floor"] for row in first["evidence"]} == {200_000_000}


async def test_a_follow_under_a_formula_that_holds_cash_sells_every_holding_on_the_mock_account_and_keeps_its_formula(
    project: Path,
) -> None:
    harness = falling_site(project)
    harness.hold("2317", 1000, 50.0)
    harness.hold("1101", 1000, 30.0)

    async with app_of(harness) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        assert (await save(client, ("ranking.active_formula", "cash_under_two"))).status_code == 200
        started = await write(client, "POST", "/v1/rankings/follow", {"broker": "mock"})
        follow = await ended(client, started.json()["run_id"])
        placed = [(order.stock_id, order.action) for order in harness.broker.placed]
        assert (await save(client, ("ranking.active_formula", "best_one"))).status_code == 200
        after = (await client.get("/v1/rankings/follow")).json()

    assert (started.status_code, follow["state"], follow["summary"]["execution_provider"]) == (202, "finished", "mock")
    assert placed == [("1101", TradeAction.SELL), ("2317", TradeAction.SELL)]
    assert harness.real_broker.placed == []
    assert follow["summary"]["ranking_formula"] == {**after["follows"][0]["ranking_formula"]}
    assert [
        (run["run_id"], run["ranking_formula"]["name"], run["ranking_formula"]["cash_under_average_sessions"])
        for run in after["follows"]
    ] == [(started.json()["run_id"], "cash_under_two", 2)]
    assert (after["holdings"]["lacking"], after["refusal"]) == (["2330"], None)


# ------------------------------------ CLI ------------------------------------- #


async def test_the_cli_ranks_and_replays_by_the_formula_named_and_by_the_active_one_without_a_name(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = falling_site(project)
    printed: list[str] = []
    monkeypatch.setattr(cli.terminal.console, "print", lambda item: printed.append(item if isinstance(item, str) else item.title))
    pipeline = runtime_for(harness, load_settings(project)).signed_out

    cli.print_ranking(await pipeline.load_ranking())
    cli.print_ranking(await pipeline.load_ranking("cash_under_two"))
    cli.print_backtest(await pipeline.run_ranking_backtest(date(2026, 10, 1), date(2026, 10, 16), "best_one"), holdings=True)

    assert cli.arguments_of(["latest"]).formula is None
    assert cli.arguments_of(["backtest", "2026-10-01", "2026-10-16", "--formula", "best_one"]).formula == "best_one"
    assert [line for line in printed if line.startswith("Formula")] == [
        "Formula: revenue_and_high.",
        "Formula: cash_under_two. It holds cash now.",
        "Formula: best_one.",
    ]
    assert printed[-1] == "2026-10-13 (2026-09): 2330"

    with pytest.raises(UnknownRankingFormula, match="name no formula best_lately"):
        await pipeline.load_ranking("best_lately")
