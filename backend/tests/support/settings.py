"""The settings the app ships, for tests that build an adapter, a use case or a runtime themselves."""

from pathlib import Path
from typing import Any

from a_domain.model.trading.ranking_formula import NearnessToHigh, RankingFormula, RevenueAcceleration
from a_domain.rules.trading.ranking import MonthlyRankingRule
from a_domain.types.enums import SystemEnvironment
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import inject_built_in_strategies, load_yaml, settings_texts
from b_application.config.trading_config import RankingConfig, ShioajiConfig

APPSETTING = Path(__file__).resolve().parents[3] / "config" / "appsetting.yaml"


def shipped_config(project_root: Path = Path(".")) -> AppConfig:
    """
    config/appsetting.yaml with the built-in strategies, as load_settings reads them, without the prompts of
    config/instructions.yaml. A settings value has no code default, so a test reads it from here and changes what it
    needs with model_copy(update=...).
    """
    settings = load_yaml(APPSETTING)
    inject_built_in_strategies(settings, APPSETTING.parent / "strategies", settings_texts(APPSETTING.parents[1]))
    return AppConfig(project_root=project_root, **settings)


def environment_setup(config: AppConfig, environment: SystemEnvironment) -> AppConfig:
    """
    `config` in `environment` with exactly the Shioaji credentials the environment reads, never another's, each set to
    its own variable's name, so a test sees which variable reached which part of a login. Read from the process
    environment only, never .env.
    """
    polling = config.shioaji.model_dump(include={"poll_interval_seconds", "max_polls"})
    credentials = {credential.value: credential.value for credential in environment.shioaji_credentials}
    return config.model_copy(update={"environment": environment, "shioaji": ShioajiConfig(_env_file=None, **polling, **credentials)})


def small_formula(
    *,
    top: int,
    high_sessions: int,
    short_months: int,
    long_months: int,
    traded_value_sessions: int,
    min_close: float = 0,
    min_traded_value: float = 0,
    cash_under_average_sessions: int | None = None,
    name: str = "revenue_and_high",
) -> RankingFormula:
    """The shipped formula's two factors over windows small enough for a hand-made history."""
    return RankingFormula(
        name=name,
        factors=(RevenueAcceleration(short_months=short_months, long_months=long_months), NearnessToHigh(high_sessions=high_sessions)),
        top=top,
        min_close=min_close,
        min_traded_value=min_traded_value,
        traded_value_sessions=traded_value_sessions,
        cash_under_average_sessions=cash_under_average_sessions,
    )


def small_ranking_rule(benchmark_id: str = "0050", **windows: Any) -> MonthlyRankingRule:
    return MonthlyRankingRule(formula=small_formula(**windows), benchmark_id=benchmark_id)


def with_formulas(ranking: RankingConfig, *formulas: RankingFormula) -> RankingConfig:
    """`ranking` with `formulas` as its only ones, the first active, and the revenue trend over the first one's months."""
    acceleration = next(factor for factor in formulas[0].factors if isinstance(factor, RevenueAcceleration))
    return ranking.model_copy(
        update={
            "formulas": formulas,
            "active_formula": formulas[0].name,
            "revenue_short_months": acceleration.short_months,
            "revenue_long_months": acceleration.long_months,
        }
    )
