from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.tick import LimitPriceRule, TickSizeRule
from a_domain.types.enums import ExecutionProvider, OrderMode


class AnalysisConfig(BaseModel):
    """Cross-analysis weighting and trading parameters. Every value comes from the `analysis` section of config/appsetting.yaml."""

    lookback_days: int = Field(ge=30)

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

    @model_validator(mode="after")
    def validate_weights(self) -> Self:
        total_weight = self.technical_weight + self.ai_weight

        if abs(total_weight - 1.0) > 1e-5:
            raise ValueError("technical_weight and ai_weight must sum to 1.0")

        return self


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
    DEV / TEST fake broker account configuration.

    Initial cash is only used when mock_cash has no row yet.
    """

    account_id: str = "mock-dev"
    initial_cash: float = Field(default=1_000_000, gt=0)
    max_fill_quantity: int | None = Field(default=None, gt=0)
    """Most shares the simulated market fills per order at the limit price. Unset fills any quantity."""


class ShioajiConfig(BaseSettings):
    """
    Shioaji (Sinopac) broker login, used when trading.execution_provider is shioaji.

    Credentials come from the environment or .env only. Simulation logs in to Shioaji's paper-trading
    environment and needs no CA certificate; production signs real orders with the CA. The env prefix keeps
    an unrelated SIMULATION variable from switching the broker to production.
    """

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_prefix="SHIOAJI_")

    simulation: bool = True

    poll_interval_seconds: float = Field(ge=0)
    """Wait between two reads of an order's status at the broker. It comes from config/appsetting.yaml, like max_polls."""

    max_polls: int = Field(gt=0)
    """Reads of an order's status before the adapter cancels it, and again after the cancel request."""

    api_key: SecretStr | None = Field(default=None, validation_alias="SHIOAJI_API_KEY")
    secret_key: SecretStr | None = Field(default=None, validation_alias="SHIOAJI_SECRET_KEY")
    ca_path: str | None = Field(default=None, validation_alias="SHIOAJI_CA_PATH")
    ca_password: SecretStr | None = Field(default=None, validation_alias="SHIOAJI_CA_PASSWORD")
    person_id: SecretStr | None = Field(default=None, validation_alias="SHIOAJI_PERSON_ID")

    @field_validator("api_key", "secret_key", "ca_path", "ca_password", "person_id", mode="before")
    @classmethod
    def _blank_is_missing(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    def missing_credentials(self) -> list[str]:
        """The environment variables a login still needs: the API key pair always, the CA trio in production."""
        required = ["api_key", "secret_key"] if self.simulation else ["api_key", "secret_key", "ca_path", "ca_password", "person_id"]

        return [str(type(self).model_fields[name].validation_alias) for name in required if getattr(self, name) is None]


class WatchlistConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    automatic_expiry_sessions: int = Field(default=1, gt=0)
    """
    A TECHNICAL or BUZZ entry stays active through the close of this many trading sessions after its workflow
    last selected it: 1 keeps Friday evening's Full Cycle entries through Monday's session.
    """
