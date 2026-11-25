from datetime import date, time
from decimal import Decimal
from functools import cached_property
from math import ceil
from typing import Annotated, Any, Self, override

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from a_domain.model.trading.ranking_formula import RankingFormula
from a_domain.rules.fundamentals.stock_analysis import RevenueTrendRule
from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from a_domain.rules.trading.account_value import AccountValueRule, PositionValueRule
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.ranking import MonthlyRankingRule, RankingHistoryRule
from a_domain.rules.trading.tick import LimitPriceRule, TickSizeRule
from a_domain.types.enums import SettingUnit, ShioajiCredential, ShioajiServer
from a_domain.types.errors import UnknownRankingFormula
from a_domain.types.values import FormulaId


class AnalysisConfig(BaseModel):
    """Cross-analysis weighting and trading parameters. Every value comes from the `analysis` section of config/appsetting.yaml."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    technical_weight: float = Field(ge=0, le=1, json_schema_extra={"step": 0.05, "unit": SettingUnit.PERCENT})
    ai_weight: float = Field(ge=0, le=1, json_schema_extra={"step": 0.05, "unit": SettingUnit.PERCENT})

    min_combined_score_buy: int = Field(ge=0, le=100, json_schema_extra={"step": 5})
    max_combined_score_sell: int = Field(ge=0, le=100, json_schema_extra={"step": 5})

    risk_per_trade_pct: float = Field(
        ge=0.01, le=0.1, json_schema_extra={"steps": [0.01, 0.02, 0.03, 0.05, 0.1], "unit": SettingUnit.PERCENT}
    )
    stop_loss_pct: float = Field(
        ge=0.01, le=0.5, json_schema_extra={"steps": [0.03, 0.05, 0.07, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5], "unit": SettingUnit.PERCENT}
    )

    lot_size: int = Field(gt=0, json_schema_extra={"steps": [1, 1000]})
    """A BUY quantity is a multiple of this many shares: 1 sizes odd lots, 1000 whole board lots."""

    reason_item_limit: int = Field(gt=0, json_schema_extra={"steps": [1, 2, 3, 5, 10]})
    """Most AI factors and soft technical failures a decision reason lists."""

    article_fetch_limit: int = Field(ge=1, le=100, json_schema_extra={"steps": [5, 10, 20, 50, 100]})

    material_information_days: int = Field(
        ge=1, le=365, json_schema_extra={"steps": [7, 14, 30, 60, 90, 180, 365], "unit": SettingUnit.DAYS}
    )
    """
    How many days back an audience without news articles (public) reads a stock's archived material information for
    the AI step. A stock with none in them is decided on its technical score alone.
    """

    lookback_days: int = Field(ge=30, json_schema_extra={"steps": [60, 90, 120, 180, 250, 365], "unit": SettingUnit.DAYS})
    """The shortest daily-history window fetched, in calendar days."""

    history_calendar_days_per_bar: float = Field(
        ge=1, allow_inf_nan=False, json_schema_extra={"steps": [1.5, 1.7, 1.9, 2.0, 2.5], "unit": SettingUnit.DAYS}
    )
    """
    Calendar days fetched for each daily bar a strategy needs. Weekends, holidays and trading halts have no bar, so a
    strategy that needs 84 bars fetches max(lookback_days, 84 x this) calendar days. The window is only an estimate:
    a stock that still has fewer bars than the strategy needs fails the technical step instead of being scored.
    """

    def history_days(self, required_bars: int) -> int:
        """The calendar days of daily history to fetch for a strategy that needs required_bars bars."""
        return max(self.lookback_days, ceil(required_bars * self.history_calendar_days_per_bar))

    @model_validator(mode="after")
    def validate_weights(self) -> Self:
        total_weight = self.technical_weight + self.ai_weight

        if abs(total_weight - 1.0) > 1e-5:
            raise ValueError("technical_weight and ai_weight must sum to 1.0")

        return self


class TechnicalConfig(BaseModel):
    """
    Where technical strategies come from. Every value comes from the `technical` section of config/appsetting.yaml;
    load_settings reads each built-in strategy from config/strategies/<id>.json.
    """

    built_in_strategies: Annotated[tuple[TechnicalStrategy, ...], Field(min_length=1, json_schema_extra={"strategy": True})]
    """The developer's strategies, in menu order. Saving settings never changes them."""

    initial_strategy_id: FormulaId = Field(json_schema_extra={"strategy": True})
    """The active strategy of an owner's first settings."""

    @model_validator(mode="after")
    def validate_initial_strategy(self) -> Self:
        _ = self.initial_settings

        return self

    @cached_property
    def initial_settings(self) -> TechnicalSettings:
        """An owner's first settings: an independent copy of every built-in strategy, the initial one selected."""
        return TechnicalSettings(active_strategy_id=self.initial_strategy_id, strategies=self.built_in_strategies)

    @cached_property
    def required_bars(self) -> int:
        """The daily bars every built-in strategy can run on: the most any of them needs."""
        return max(strategy.required_bars for strategy in self.built_in_strategies)


class RankingConfig(BaseModel):
    """
    The monthly stock ranking, the formulas it can be made by, and its backtest. Every value comes from the `ranking`
    section of config/appsetting.yaml; the fees and the tax are the market's, the revenue deadline MOPS's.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    decision_day: int = Field(ge=1, le=28)
    """Each month decides at the close of its first session on this day of the month or later."""

    formulas: tuple[RankingFormula, ...] = Field(min_length=1)
    """
    The formulas the ranking can be made by, in the order the ranking page compares them. Adding one is an entry here,
    of the factors RankingFactorKind names; a formula the ranking cannot express is refused at the start.
    """

    active_formula: FormulaId = Field(json_schema_extra={"names_of": "ranking.formulas"})
    """
    The formula the ranking, every stock's score, the backtest shown and a follow use now. After a switch an account's
    follows of the first top_up_follow_days days also buy each ranked stock it holds up to its equal weight
    (top_up_tolerance_pct), until one of them left the account nothing to trade; every later one leaves a held stock as
    it is (RankingFollowRule, FormulaSwitchRule). `names_of` marks a setting that chooses among the names of the
    entries the settings file sets at that path.
    """

    top_up_tolerance_pct: float = Field(ge=0, le=1, json_schema_extra={"steps": [0.05, 0.1, 0.2], "unit": SettingUnit.PERCENT})
    """
    How far below its equal weight a ranked stock the account holds may be worth, as a share of that weight, before a
    follow after a switch of active_formula buys it up to the weight (TopUpRule). A follow sizes each BUY at its limit,
    up to trading.limit_offset_pct above the price it fills at, so the mock account keeps about that share of each
    weight as cash: without the tolerance every session's follow would buy a few more shares at the minimum fee.
    """

    top_up_follow_days: int = Field(default=4, ge=1, le=20, json_schema_extra={"operator_only": True})
    """
    On how many days the follows after a switch of active_formula top up the ranked stocks the account holds, counted
    by the days a follow of the account took a decision under the new formula and ended without a failure, the first
    included (FormulaSwitchRule). SinoPac pays a sale two sessions after it, so the fourth day's follow has the cash of
    the switch's sales even when the payment lands after the third day's follow. A top-up none of them could buy is
    left: the next follow tops up nothing and finishes the decision.
    """

    evidence_min_traded_value: float = Field(
        default=200_000_000,
        ge=0,
        allow_inf_nan=False,
        json_schema_extra={"steps": [100000000, 200000000, 500000000], "unit": SettingUnit.TWD},
    )
    """The liquidity floor the ranking page's comparison replays every formula at a second time, in place of its own."""

    follow_times: tuple[time, ...] = Field(
        default=(time(9, 5), time(9, 30), time(10, 0), time(13, 0)),
        min_length=1,
        json_schema_extra={
            "options": ["09:05:00", "09:15:00", "09:30:00", "10:00:00", "10:30:00", "11:00:00", "12:00:00", "13:00:00"]
        },
    )
    """
    The times of day in Taipei a user may schedule the ranking follow into their mock account at, each inside
    continuous trading, read in the day's order. The first is the nearest to the open the backtest buys at. `options`
    are the times the settings form offers.
    """

    kept_backtests: int = Field(default=24, ge=0, json_schema_extra={"operator_only": True})
    """How many replays of the ranking the site keeps in memory while the history they read stays the same."""

    revenue_short_months: int = Field(ge=1, json_schema_extra={"steps": [1, 2, 3, 6]})
    revenue_long_months: int = Field(ge=1, json_schema_extra={"steps": [6, 12, 24]})
    """The stock page's and the holdings page's revenue trend: the mean of the latest short months over the long ones."""

    daily_limit: float = Field(gt=0, lt=1, json_schema_extra={"steps": [0.1, 0.105, 0.11, 0.15], "unit": SettingUnit.PERCENT})
    """A move beyond it on a bar without a reference price counts as 0 in the total-return level."""

    benchmark_id: str = Field(min_length=1, json_schema_extra={"options": ["0050", "006208"]})
    """The backtest's benchmark, and the one a formula's market filter reads."""

    sessions_per_year: float = Field(gt=0, allow_inf_nan=False, json_schema_extra={"steps": [240, 245, 250, 252]})
    """The sessions a year the annual returns count."""

    @field_validator("follow_times")
    @classmethod
    def offer_each_time_once_in_the_order_of_the_day(cls, times: tuple[time, ...]) -> tuple[time, ...]:
        return tuple(sorted(set(times)))

    @model_validator(mode="after")
    def validate_formulas(self) -> Self:
        names = [formula.name for formula in self.formulas]

        if len(set(names)) != len(names):
            raise ValueError("two formulas of ranking.formulas have the same name")

        if self.active_formula not in names:
            raise ValueError(f"active_formula names none of ranking.formulas: {', '.join(names)}")

        return self

    def formula(self, name: FormulaId | None = None) -> RankingFormula:
        """The formula of that name, the active one when none is named. UnknownRankingFormula for a name the settings lack."""
        chosen = self.active_formula if name is None else name
        found = next((formula for formula in self.formulas if formula.name == chosen), None)

        if found is None:
            raise UnknownRankingFormula(
                f"The settings name no formula {chosen}. They name: {', '.join(formula.name for formula in self.formulas)}."
            )

        return found

    def ranking_rule(self, name: FormulaId | None = None) -> MonthlyRankingRule:
        return MonthlyRankingRule(formula=self.formula(name), benchmark_id=self.benchmark_id)

    def revenue_trend_rule(self) -> RevenueTrendRule:
        """The stock page's and the holdings page's revenue trend, the acceleration the shipped formula ranks by."""
        return RevenueTrendRule(short_months=self.revenue_short_months, long_months=self.revenue_long_months)

    def history_rule(self) -> RankingHistoryRule:
        return RankingHistoryRule(daily_limit=self.daily_limit)


class MarketConfig(BaseModel):
    """Universal market trading rules and friction costs. Every value comes from the `market` section of config/appsetting.yaml."""

    fee_rate: float = Field(ge=0, json_schema_extra={"steps": [0.000399, 0.000855, 0.001425], "unit": SettingUnit.PERCENT})
    tax_rate: float = Field(ge=0, json_schema_extra={"steps": [0.0015, 0.003], "unit": SettingUnit.PERCENT})
    """Securities transaction tax on a stock SELL."""

    etf_tax_rate: float = Field(ge=0, json_schema_extra={"steps": [0.001, 0.003], "unit": SettingUnit.PERCENT})
    """Securities transaction tax on an ETF SELL (codes starting with 00)."""

    bond_etf_tax_exempt_until: date
    """The last trading date on which a bond ETF SELL (a 00 code ending in B) pays no transaction tax; after it, etf_tax_rate."""

    min_fee: int = Field(ge=0, json_schema_extra={"steps": [0, 1, 20], "unit": SettingUnit.TWD})

    board_lot_shares: int = Field(gt=0, json_schema_extra={"steps": [100, 1000]})
    """Shares in one board lot, the exchange's trading unit. Fewer shares trade as an odd lot."""

    stock_ticks: dict[Decimal, Decimal] = Field(json_schema_extra={"operator_only": True})
    """A stock's price ticks: from each band's lowest price up, a limit price is a multiple of the band's tick."""

    etf_ticks: dict[Decimal, Decimal] = Field(json_schema_extra={"operator_only": True})
    """An ETF's price ticks, banded like stock_ticks."""

    tick_float_tolerance: Decimal = Field(gt=0, lt=Decimal("0.5"), json_schema_extra={"operator_only": True})
    """A quote this close to a tick, as a fraction of the tick, is that tick carried through a binary float."""

    def cost_rule(self) -> TradingCostRule:
        return TradingCostRule(
            fee_rate=self.fee_rate,
            tax_rate=self.tax_rate,
            etf_tax_rate=self.etf_tax_rate,
            min_fee=self.min_fee,
            bond_etf_tax_exempt_until=self.bond_etf_tax_exempt_until,
        )

    def position_value_rule(self) -> PositionValueRule:
        return PositionValueRule(cost_rule=self.cost_rule())

    def account_value_rule(self) -> AccountValueRule:
        return AccountValueRule(position_value_rule=self.position_value_rule())

    def limit_price_rule(self, offset: float) -> LimitPriceRule:
        """The limits of orders at most `offset` past their decided price; with 0, the decided price as a tick."""
        tick_size_rule = TickSizeRule(
            stock_ticks=tuple(sorted(self.stock_ticks.items(), reverse=True)),
            etf_ticks=tuple(sorted(self.etf_ticks.items(), reverse=True)),
        )

        return LimitPriceRule(tick_size_rule=tick_size_rule, float_tolerance=self.tick_float_tolerance, offset=Decimal(repr(offset)))


class TradingConfig(BaseModel):
    """
    How far an order's limit may lie past the price its decision saw, on every broker, and the limits of every BUY on a
    real broker (ExecutionProvider.real), which follow the account's equity as each run values it. Which broker a run
    orders on is the run's own choice when it starts, the mock account by default. Every value comes from the `trading`
    section of config/appsetting.yaml.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    limit_offset_pct: float = Field(
        ge=0, le=0.05, json_schema_extra={"steps": [0, 0.005, 0.01, 0.02, 0.03, 0.05], "unit": SettingUnit.PERCENT}
    )
    """
    How far an order's limit price may lie past the price its decision saw: a BUY's at most this share above it and a
    SELL's at most this share below it, the furthest tick inside (LimitPriceRule). The exchange fills such a limit at
    the market's price, so this bounds what a fill may cost, and the mock account fills at the price the decision saw.
    BUYs are sized at the limit, fee included, so they stay affordable whatever the fill. 0 limits each order at the
    price its decision saw.
    """

    max_order_equity_pct: float = Field(
        gt=0, le=1, json_schema_extra={"steps": [0.1, 0.15, 0.2, 0.25, 0.3, 0.5], "unit": SettingUnit.PERCENT}
    )
    """
    Most one BUY on a real broker may cost at its limit price, fees aside, as a share of the account's equity as the run
    valued it (BuyLimitRule). A ranking follow of 10 stocks buys each at 10% of it and a BUY sized on its risk budget
    takes analysis.risk_per_trade_pct over analysis.stop_loss_pct of it, 20%, so 25% stops a BUY far larger than either
    and neither. A follow is sized inside it.
    """

    max_daily_buy_equity_pct: float = Field(
        gt=0, le=3, json_schema_extra={"steps": [0.5, 1, 1.1, 1.5, 2], "unit": SettingUnit.PERCENT}
    )
    """
    Most the BUYs on a real broker of one Taiwan calendar day may cost together at their limit prices, fees aside, as a
    share of the account's equity as each run valued it, counted from the trading journal (BuyLimitRule). A follow that
    puts the whole account into the ranking spends no more than its cash, so 100% is the most a normal day buys and the
    rest is room for a manual BUY, a BUY of unknown outcome counted in full and a market that fell between two runs of
    the day; a run that keeps buying is stopped there. A follow keeps its best stocks within it and leaves the rest to a
    later session.
    """


class HoldingsConfig(BaseModel):
    """The My holdings page and the SinoPac account page. A settings file without the section runs on these defaults."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    concentration_positions: int = Field(default=3, ge=1, le=20, json_schema_extra={"steps": [1, 3, 5, 10]})
    """The largest stocks whose share of the holdings' value the page shows as the concentration."""

    realized_days: int = Field(default=90, ge=1, le=366, json_schema_extra={"steps": [30, 90, 180, 366], "unit": SettingUnit.DAYS})
    """How many days back the SinoPac account page asks the broker for the sales it settled."""


class MockTradingConfig(BaseModel):
    """
    DEV / TEST fake broker accounts: each user's mock account is keyed by the user's id.

    Initial cash is only used when the user's mock_cash row does not exist yet.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    initial_cash: float = Field(
        gt=0, json_schema_extra={"steps": [100000, 500000, 1000000, 3000000, 10000000], "unit": SettingUnit.TWD}
    )
    max_fill_quantity: int | None = Field(default=None, gt=0, json_schema_extra={"steps": [1000, 5000, 10000, 50000]})
    """Most shares the simulated market fills per order at the limit price. Unset fills any quantity."""


class ShioajiLogin(BaseModel):
    """What one Shioaji login uses: the server, the key pair, and in production the CA certificate that signs orders."""

    model_config = ConfigDict(frozen=True)

    server: ShioajiServer
    api_key: SecretStr
    secret_key: SecretStr
    ca_path: str | None = None
    ca_password: SecretStr | None = None
    person_id: SecretStr | None = None


class CredentialsOnly(PydanticBaseSettingsSource):
    """
    The environment or .env as ShioajiConfig reads them: its credentials alone, each by its ShioajiCredential variable.
    Every other Shioaji setting comes from the settings files only, so no SHIOAJI_SERVER variable moves the login to
    another server past the SinoPac page's switch and its checks.
    """

    def __init__(self, source: PydanticBaseSettingsSource) -> None:
        super().__init__(source.settings_cls)
        self.source = source

    @override
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self.source.get_field_value(field, field_name)

    @override
    def __call__(self) -> dict[str, Any]:
        return {key: value for key, value in self.source().items() if key in set(ShioajiCredential)}


class ShioajiConfig(BaseSettings):
    """
    The Shioaji (Sinopac) login of a personal site: its realtime quotes, and the SinoPac broker of the runs an
    administrator starts on SinoPac.

    Credentials come from the environment or .env only, each field from its ShioajiCredential variable. Which ones a
    login reads is the table of `server`, ShioajiServer: the simulation server with the *_TEST key pair, the real
    account with the production key pair and CA certificate. A machine may hold both sets, and a save switches
    `server` without a restart (ServerSwitchRule). The environment and .env set nothing else (CredentialsOnly).
    """

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_prefix="SHIOAJI_")

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, CredentialsOnly(env_settings), CredentialsOnly(dotenv_settings)

    server: ShioajiServer
    """
    The SinoPac server the login is made on. The SinoPac page switches it, behind the administrator's password, as
    ServerSwitchRule allows.
    """

    poll_interval_seconds: float = Field(ge=0, json_schema_extra={"steps": [0.2, 0.5, 1, 2], "unit": SettingUnit.SECONDS})
    """Wait between two reads of an order's status at the broker. It comes from config/appsetting.yaml, like max_polls."""

    max_polls: int = Field(gt=0, json_schema_extra={"steps": [5, 10, 20, 30]})
    """Reads of an order's status before the adapter cancels it, and again after the cancel request."""

    status_timeout_seconds: float = Field(
        default=30, ge=5, le=60, json_schema_extra={"steps": [10, 20, 30, 60], "unit": SettingUnit.SECONDS}
    )
    """
    How long the broker may take to refresh the status of every order of the account today, which each read of its cash
    and today's deals asks once. A day of many orders takes longer than the SDK's own 5 seconds. At most a minute, so a
    page waits on it no longer than a proxy waits on the page. The lookups for an exchange order whose answer was lost
    take at most this in all (listed_trade), within compose.yml's stop_grace_period.
    """

    odd_lot_matches: int = Field(default=3, gt=0, le=10, json_schema_extra={"operator_only": True})
    """
    The intraday odd-lot session's matches after its first one that an odd-lot part stays working through, its status
    read after each, before the adapter cancels what is left. They run market_hours.odd_lot_match_seconds apart, so the
    part works at most a couple of minutes past the first match; a board-lot part keeps max_polls. Only the file sets
    it, beside the market hours it is counted in.
    """

    cancel_timeout_seconds: float = Field(default=15, gt=0, le=30, allow_inf_nan=False, json_schema_extra={"operator_only": True})
    """
    The longest the adapter waits for the broker to answer a cancel and the reads after it. Past it the order is
    recorded UNCONFIRMED, which the broker's record of the day settles later (OrderSettlement). compose.yml's
    stop_grace_period covers it.
    """

    login_renewal_time: time = Field(default=time(8, 15), json_schema_extra={"operator_only": True})
    """
    The time of each market day, in Taipei, from which a login made before it is stale: the renewal of the site's login
    (RuntimeSwitch.log_in_again) logs in again on a new client at its first look at or after it, which the Web API's
    timer of the scheduled follows makes within api.follow_schedule_poll_seconds of it, and the CLI at its next round.
    SinoPac does not say how long a login lasts: on 2026-11-20 it refused one made 26 hours earlier (TokenError), and
    one 6.5 hours old still answered.
    The time is after SinoPac's nightly maintenance, before the opening auction takes orders (08:30), and a quarter of
    an hour past 08:00, midnight UTC, when the SDK's cache of the contracts, kept by UTC day, turns a day old, so a login
    then reads the day's contracts and the price band each order is kept within.
    """

    login_retry_seconds: float = Field(
        default=60, ge=10, le=3600, allow_inf_nan=False, json_schema_extra={"operator_only": True, "unit": SettingUnit.SECONDS}
    )
    """The least time between two logins after one failed, so a SinoPac that does not answer is not asked again at once."""

    login_retry_max_seconds: float = Field(
        default=900, ge=10, le=86400, allow_inf_nan=False, json_schema_extra={"operator_only": True, "unit": SettingUnit.SECONDS}
    )
    """
    The longest wait between two logins after they failed one after another: the first waits login_retry_seconds and
    each further one twice the wait before, up to this, so a SinoPac that refuses for hours is not asked once a minute,
    on a new client each time. At least login_retry_seconds.
    """

    simulation_initial_cash: float = Field(
        gt=0, allow_inf_nan=False, json_schema_extra={"steps": [100000, 500000, 1000000, 3000000, 10000000], "unit": SettingUnit.TWD}
    )
    """The cash SinoPac's simulation account started with, which that server does not report (SimulationCashRule)."""

    api_key: SecretStr | None = Field(default=None, validation_alias=ShioajiCredential.API_KEY.value)
    secret_key: SecretStr | None = Field(default=None, validation_alias=ShioajiCredential.SECRET_KEY.value)
    ca_path: str | None = Field(default=None, validation_alias=ShioajiCredential.CA_PATH.value)
    ca_password: SecretStr | None = Field(default=None, validation_alias=ShioajiCredential.CA_PASSWORD.value)
    person_id: SecretStr | None = Field(default=None, validation_alias=ShioajiCredential.PERSON_ID.value)
    api_key_test: SecretStr | None = Field(default=None, validation_alias=ShioajiCredential.API_KEY_TEST.value)
    secret_key_test: SecretStr | None = Field(default=None, validation_alias=ShioajiCredential.SECRET_KEY_TEST.value)

    @field_validator("api_key", "secret_key", "ca_path", "ca_password", "person_id", "api_key_test", "secret_key_test", mode="before")
    @classmethod
    def blank_is_missing(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def validate_login_retry(self) -> Self:
        if self.login_retry_max_seconds < self.login_retry_seconds:
            raise ValueError("login_retry_max_seconds must be at least login_retry_seconds")

        return self

    def given(self) -> frozenset[ShioajiCredential]:
        """The Shioaji variables that are set, by name only: a refusal names them and never shows a value."""
        return frozenset(
            ShioajiCredential(field.validation_alias)
            for name, field in type(self).model_fields.items()
            if isinstance(field.validation_alias, str) and getattr(self, name) is not None
        )

    def missing(self, server: ShioajiServer) -> list[ShioajiCredential]:
        """The variables a login on `server` reads that are not set, by name only."""
        given = self.given()
        return [credential for credential in server.credentials if credential not in given]

    def login(self) -> ShioajiLogin | None:
        """
        The login on `server` with its own credentials, each by name, or None while its key pair is not set. The
        realtime quotes need only the key pair; the SinoPac broker exists only with every credential the server reads
        (connect_shioaji).
        """
        match self.server:
            case ShioajiServer.SIMULATION:
                credentials = {"api_key": self.api_key_test, "secret_key": self.secret_key_test}
            case ShioajiServer.PRODUCTION:
                credentials = {
                    "api_key": self.api_key,
                    "secret_key": self.secret_key,
                    "ca_path": self.ca_path,
                    "ca_password": self.ca_password,
                    "person_id": self.person_id,
                }

        if credentials["api_key"] is None or credentials["secret_key"] is None:
            return None

        return ShioajiLogin.model_validate({"server": self.server, **credentials})


class WatchlistConfig(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    automatic_expiry_sessions: int = Field(default=1, gt=0, json_schema_extra={"steps": [1, 2, 3, 5, 10]})
    """
    A TECHNICAL or BUZZ entry stays active through the close of this many trading sessions after its workflow
    last selected it: 1 keeps Friday evening's Full Cycle entries through Monday's session.
    """
