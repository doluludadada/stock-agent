from datetime import date
from decimal import Decimal
from functools import cached_property
from math import ceil
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from a_domain.rules.trading.account_value import AccountValueRule, PositionValueRule
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.tick import LimitPriceRule, TickSizeRule
from a_domain.types.enums import ExecutionProvider, OrderMode, ShioajiCredential, SystemEnvironment
from a_domain.types.values import FormulaId


class AnalysisConfig(BaseModel):
    """Cross-analysis weighting and trading parameters. Every value comes from the `analysis` section of config/appsetting.yaml."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    technical_weight: float = Field(ge=0, le=1)
    ai_weight: float = Field(ge=0, le=1)

    min_combined_score_buy: int = Field(ge=0, le=100)
    max_combined_score_sell: int = Field(ge=0, le=100)

    risk_per_trade_pct: float = Field(ge=0.01, le=0.1)
    stop_loss_pct: float = Field(ge=0.01, le=0.5)

    lot_size: int = Field(gt=0)
    """A BUY quantity is a multiple of this many shares: 1 sizes odd lots, 1000 whole board lots."""

    reason_item_limit: int = Field(gt=0)
    """Most AI factors and soft technical failures a decision reason lists."""

    article_fetch_limit: int = Field(ge=1, le=100)

    lookback_days: int = Field(ge=30)
    """The shortest daily-history window fetched, in calendar days."""

    history_calendar_days_per_bar: float = Field(ge=1, allow_inf_nan=False)
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

    built_in_strategies: Annotated[tuple[TechnicalStrategy, ...], Field(min_length=1)]
    """The developer's strategies, in menu order. Saving settings never changes them."""

    initial_strategy_id: FormulaId
    """What an owner's first settings select for every workflow."""

    @model_validator(mode="after")
    def validate_initial_strategy(self) -> Self:
        _ = self.initial_settings

        return self

    @cached_property
    def initial_settings(self) -> TechnicalSettings:
        """An owner's first settings: an independent copy of every built-in strategy, the initial one selected."""
        return TechnicalSettings(
            active_strategy_id=self.initial_strategy_id, buzz_strategy_id=self.initial_strategy_id, strategies=self.built_in_strategies
        )


class MarketConfig(BaseModel):
    """Universal market trading rules and friction costs. Every value comes from the `market` section of config/appsetting.yaml."""

    fee_rate: float = Field(ge=0)
    tax_rate: float = Field(ge=0)
    """Securities transaction tax on a stock SELL."""

    etf_tax_rate: float = Field(ge=0)
    """Securities transaction tax on an ETF SELL (codes starting with 00)."""

    bond_etf_tax_exempt_until: date
    """The last trading date on which a bond ETF SELL (a 00 code ending in B) pays no transaction tax; after it, etf_tax_rate."""

    min_fee: int = Field(ge=0)

    board_lot_shares: int = Field(gt=0)
    """Shares in one board lot, the exchange's trading unit. Fewer shares trade as an odd lot."""

    stock_ticks: dict[Decimal, Decimal]
    """A stock's price ticks: from each band's lowest price up, a limit price is a multiple of the band's tick."""

    etf_ticks: dict[Decimal, Decimal]
    """An ETF's price ticks, banded like stock_ticks."""

    tick_float_tolerance: Decimal = Field(gt=0, lt=Decimal("0.5"))
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
    """Execution-provider selection and order-mode settings."""

    execution_provider: ExecutionProvider = ExecutionProvider.MOCK
    order_mode: OrderMode = OrderMode.MOCK_ONLY


class MockTradingConfig(BaseModel):
    """
    DEV / TEST fake broker accounts: each user's mock account is keyed by the user's id.

    Initial cash is only used when the user's mock_cash row does not exist yet.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    initial_cash: float = Field(default=1_000_000, gt=0)
    max_fill_quantity: int | None = Field(default=None, gt=0)
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
    Shioaji (Sinopac) broker login, used when trading.execution_provider is shioaji.

    Credentials come from the environment or .env only, each field from its ShioajiCredential variable. Which ones a
    login reads, and whether it is simulation, is SystemEnvironment's table: test logs in to Shioaji's paper-trading
    server with the *_TEST key pair, prod to the real account with the production key pair and CA certificate.
    """

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_prefix="SHIOAJI_")

    poll_interval_seconds: float = Field(ge=0)
    """Wait between two reads of an order's status at the broker. It comes from config/appsetting.yaml, like max_polls."""

    max_polls: int = Field(gt=0)
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
    def _blank_is_missing(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    def given(self) -> frozenset[ShioajiCredential]:
        """The Shioaji variables that are set, by name only: a refusal names them and never shows a value."""
        return frozenset(
            ShioajiCredential(field.validation_alias)
            for name, field in type(self).model_fields.items()
            if isinstance(field.validation_alias, str) and getattr(self, name) is not None
        )

    def login(self, environment: SystemEnvironment) -> ShioajiLogin:
        """
        The login with the environment's own credentials, each by name. validate_trading_environment refuses a start
        with one of them missing, so a missing one here fails validation as a bug.
        """
        match environment:
            case SystemEnvironment.DEV:
                raise ValueError("environment dev never logs in to Shioaji")
            case SystemEnvironment.TEST:
                credentials = {"api_key": self.api_key_test, "secret_key": self.secret_key_test}
            case SystemEnvironment.PROD:
                credentials = {
                    "api_key": self.api_key,
                    "secret_key": self.secret_key,
                    "ca_path": self.ca_path,
                    "ca_password": self.ca_password,
                    "person_id": self.person_id,
                }

        return ShioajiLogin.model_validate({"simulation": environment.shioaji_simulation, **credentials})


class WatchlistConfig(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    automatic_expiry_sessions: int = Field(default=1, gt=0)
    """
    A TECHNICAL or BUZZ entry stays active through the close of this many trading sessions after its workflow
    last selected it: 1 keeps Friday evening's Full Cycle entries through Monday's session.
    """
