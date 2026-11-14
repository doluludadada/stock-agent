from datetime import date
from decimal import Decimal
from functools import cached_property
from math import ceil
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.rules.fundamentals.stock_analysis import RevenueTrendRule
from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from a_domain.rules.trading.account_value import AccountValueRule, PositionValueRule
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.ranking import MonthlyRankingRule, RankingHistoryRule
from a_domain.rules.trading.tick import LimitPriceRule, TickSizeRule
from a_domain.types.enums import SettingUnit, ShioajiCredential, SystemEnvironment
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
    The monthly stock ranking by revenue acceleration and nearness to the high, and its backtest. Every value comes from
    the `ranking` section of config/appsetting.yaml; the fees and the tax are the market's, the revenue deadline MOPS's.
    `retired` names the settings this section once had and no longer reads (settings_notices).
    """

    model_config = ConfigDict(
        use_attribute_docstrings=True, json_schema_extra={"retired": ["timestamp_calendars", "timestamp_timeout_seconds"]}
    )

    decision_day: int = Field(ge=1, le=28)
    """Each month decides at the close of its first session on this day of the month or later."""

    top: int = Field(ge=1, json_schema_extra={"steps": [10, 15, 20, 30, 50]})
    """How many of the best scores it holds, in equal weights."""

    min_close: float = Field(ge=0, allow_inf_nan=False, json_schema_extra={"steps": [0, 5, 10, 20, 50], "unit": SettingUnit.TWD})
    min_traded_value: float = Field(
        ge=0, allow_inf_nan=False, json_schema_extra={"steps": [0, 10000000, 30000000, 50000000, 100000000], "unit": SettingUnit.TWD}
    )
    """NT$ a session on average over the last traded_value_sessions, a session without a trade counting 0."""

    traded_value_sessions: int = Field(ge=1, json_schema_extra={"steps": [5, 10, 20, 60]})
    high_sessions: int = Field(ge=1, json_schema_extra={"steps": [60, 120, 250, 500]})
    """The sessions whose highest total-return level the level at the decision is compared with."""

    revenue_short_months: int = Field(ge=1, json_schema_extra={"steps": [1, 2, 3, 6]})
    revenue_long_months: int = Field(ge=1, json_schema_extra={"steps": [6, 12, 24]})
    daily_limit: float = Field(gt=0, lt=1, json_schema_extra={"steps": [0.1, 0.105, 0.11, 0.15], "unit": SettingUnit.PERCENT})
    """A move beyond it on a bar without a reference price counts as 0 in the total-return level."""

    benchmark_id: str = Field(min_length=1, json_schema_extra={"options": ["0050", "006208"]})
    sessions_per_year: float = Field(gt=0, allow_inf_nan=False, json_schema_extra={"steps": [240, 245, 250, 252]})
    """The sessions a year the annual returns count."""

    def ranking_rule(self) -> MonthlyRankingRule:
        return MonthlyRankingRule(
            top=self.top,
            min_close=self.min_close,
            min_traded_value=self.min_traded_value,
            traded_value_sessions=self.traded_value_sessions,
            high_sessions=self.high_sessions,
            short_months=self.revenue_short_months,
            long_months=self.revenue_long_months,
        )

    def revenue_trend_rule(self) -> RevenueTrendRule:
        """The stock page's and the holdings page's revenue trend, whose acceleration is the ranking's own measure."""
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

    def limit_price_rule(self) -> LimitPriceRule:
        tick_size_rule = TickSizeRule(
            stock_ticks=tuple(sorted(self.stock_ticks.items(), reverse=True)),
            etf_ticks=tuple(sorted(self.etf_ticks.items(), reverse=True)),
        )

        return LimitPriceRule(tick_size_rule=tick_size_rule, float_tolerance=self.tick_float_tolerance)


class TradingConfig(BaseModel):
    """
    The limits of every BUY on a real broker (ExecutionProvider.real). Which broker a run orders on is the run's own
    choice when it starts, the mock account by default. Every value comes from the `trading` section of
    config/appsetting.yaml.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    max_order_value: float = Field(
        gt=0,
        allow_inf_nan=False,
        json_schema_extra={"steps": [10000, 20000, 50000, 100000, 200000, 500000, 1000000], "unit": SettingUnit.TWD},
    )
    """Most NT$ one BUY on a real broker may cost at its limit price, fees aside."""

    max_daily_buy_value: float = Field(
        gt=0,
        allow_inf_nan=False,
        json_schema_extra={"steps": [50000, 100000, 300000, 500000, 1000000, 3000000], "unit": SettingUnit.TWD},
    )
    """Most NT$ the BUYs on a real broker of one Taiwan calendar day may cost together at their limit prices."""


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
        default=1_000_000, gt=0, json_schema_extra={"steps": [100000, 500000, 1000000, 3000000, 10000000], "unit": SettingUnit.TWD}
    )
    max_fill_quantity: int | None = Field(default=None, gt=0, json_schema_extra={"steps": [1000, 5000, 10000, 50000]})
    """Most shares the simulated market fills per order at the limit price. Unset fills any quantity."""


class ShioajiLogin(BaseModel):
    """What one Shioaji login uses: the server, the key pair, and in production the CA certificate that signs orders."""

    model_config = ConfigDict(frozen=True)

    simulation: bool
    api_key: SecretStr
    secret_key: SecretStr
    ca_path: str | None = None
    ca_password: SecretStr | None = None
    person_id: SecretStr | None = None


class ShioajiConfig(BaseSettings):
    """
    The Shioaji (Sinopac) login of a personal site: its realtime quotes, and the SinoPac broker of the runs an
    administrator starts on SinoPac.

    Credentials come from the environment or .env only, each field from its ShioajiCredential variable. Which ones a
    login reads, and whether it is simulation, is SystemEnvironment's table: dev and test log in to Shioaji's
    simulation server with the *_TEST key pair, prod to the real account with the production key pair and CA
    certificate.
    """

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_prefix="SHIOAJI_")

    poll_interval_seconds: float = Field(ge=0, json_schema_extra={"steps": [0.2, 0.5, 1, 2], "unit": SettingUnit.SECONDS})
    """Wait between two reads of an order's status at the broker. It comes from config/appsetting.yaml, like max_polls."""

    max_polls: int = Field(gt=0, json_schema_extra={"steps": [5, 10, 20, 30]})
    """Reads of an order's status before the adapter cancels it, and again after the cancel request."""

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

    def given(self) -> frozenset[ShioajiCredential]:
        """The Shioaji variables that are set, by name only: a refusal names them and never shows a value."""
        return frozenset(
            ShioajiCredential(field.validation_alias)
            for name, field in type(self).model_fields.items()
            if isinstance(field.validation_alias, str) and getattr(self, name) is not None
        )

    def login(self, environment: SystemEnvironment) -> ShioajiLogin | None:
        """
        The login with the environment's own credentials, each by name, or None while its key pair is not set. The
        realtime quotes need only the key pair; the SinoPac broker exists only with every credential the environment
        reads (connect_shioaji).
        """
        match environment:
            case SystemEnvironment.DEV | SystemEnvironment.TEST:
                credentials = {"api_key": self.api_key_test, "secret_key": self.secret_key_test}
            case SystemEnvironment.PROD:
                credentials = {
                    "api_key": self.api_key,
                    "secret_key": self.secret_key,
                    "ca_path": self.ca_path,
                    "ca_password": self.ca_password,
                    "person_id": self.person_id,
                }

        if credentials["api_key"] is None or credentials["secret_key"] is None:
            return None

        return ShioajiLogin.model_validate({"simulation": environment.shioaji_simulation, **credentials})


class WatchlistConfig(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    automatic_expiry_sessions: int = Field(default=1, gt=0, json_schema_extra={"steps": [1, 2, 3, 5, 10]})
    """
    A TECHNICAL or BUZZ entry stays active through the close of this many trading sessions after its workflow
    last selected it: 1 keeps Friday evening's Full Cycle entries through Monday's session.
    """
