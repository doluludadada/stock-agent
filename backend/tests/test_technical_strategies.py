"""
Strategies configured in config/technical.yaml.

Parity tests compare them with the pre-migration strategy factory. The reference composition
below is transcribed from the factory and thresholds that technical.yaml replaced:
`git show 9052216:backend/src/b_application/factories/technical_strategy.py`,
`git show 9052216:config/strategies.yaml`, and the `StrategyThresholds`, `ScoringConfig` and
`indicators` defaults in `git show 9052216^:backend/src/b_application/schemas/config.py` and
`git show 9052216^:config/appsetting.yaml`.
"""

import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from a_domain.model.analysis.technical_settings import TechnicalSettings
from a_domain.model.indicators.adx import Adx
from a_domain.model.indicators.atr import Atr
from a_domain.model.indicators.bollinger_bands import BollingerBands
from a_domain.model.indicators.macd import Macd
from a_domain.model.indicators.mfi import Mfi
from a_domain.model.indicators.moving_averages import MovingAverages
from a_domain.model.indicators.obv import Obv
from a_domain.model.indicators.rsi import Rsi
from a_domain.model.indicators.stochastic import Stochastic
from a_domain.model.indicators.technical_indicators import TechnicalIndicators
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.calculation.parameters import IndicatorParameters
from a_domain.rules.technical.criteria.base import TechnicalCriterion
from a_domain.rules.technical.criteria.momentum import (
    MacdBullishCriterion,
    MfiThresholdCriterion,
    RsiRangeCriterion,
    StochasticHealthCriterion,
)
from a_domain.rules.technical.criteria.trend import (
    AdxTrendCriterion,
    GoldenCrossCriterion,
    MaAlignmentCriterion,
    PriceAboveMaCriterion,
)
from a_domain.rules.technical.criteria.volatility import (
    AtrRangeCriterion,
    BollingerPositionCriterion,
    BollingerSqueezeCriterion,
    BollingerThresholdCriterion,
    DailyRangeCriterion,
)
from a_domain.rules.technical.criteria.volume import (
    LiquidityCriterion,
    MinimumPriceCriterion,
    ObvTrendCriterion,
    VolumeExpansionCriterion,
)
from a_domain.rules.technical.strategy import TechnicalScoring, TechnicalStrategy
from a_domain.types.enums import RuleEffect
from c_infrastructure.technical.yaml_technical_settings_repository import YamlTechnicalSettingsRepository

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "config" / "technical.yaml"

PRE_MIGRATION_DEFAULT_THRESHOLDS = {
    "rsi_healthy_min": 50.0,
    "rsi_healthy_max": 70.0,
    "rsi_overbought": 80.0,
    "stoch_overbought": 80.0,
    "bollinger_max_pct_b": 0.9,
    "max_daily_volatility": 0.07,
    "min_liquidity": 500,
    "min_price": 15.0,
    "volume_dry_ratio": 0.5,
    "volume_above_avg_ratio": 1.0,
    "volume_breakout_ratio": 1.5,
    "adx_min": 20.0,
    "adx_max": 50.0,
    "bollinger_squeeze_bandwidth": 0.1,
    "atr_min_pct": 0.01,
    "atr_max_pct": 0.05,
    "mfi_overbought": 80.0,
    "golden_cross_margin": 0.03,
}

PRE_MIGRATION_STRATEGY_THRESHOLDS = {
    "conservative": {
        "rsi_healthy_min": 50,
        "rsi_healthy_max": 65,
        "rsi_overbought": 75.0,
        "stoch_overbought": 80.0,
        "bollinger_max_pct_b": 0.85,
        "max_daily_volatility": 0.05,
        "min_liquidity": 1000,
        "min_price": 20.0,
        "volume_dry_ratio": 0.7,
        "volume_above_avg_ratio": 1.0,
        "volume_breakout_ratio": 1.5,
        "adx_min": 20.0,
        "adx_max": 50.0,
        "bollinger_squeeze_bandwidth": 0.1,
        "atr_min_pct": 0.01,
        "atr_max_pct": 0.05,
        "mfi_overbought": 80.0,
        "golden_cross_margin": 0.03,
    },
    "moderate": {
        "rsi_healthy_min": 50,
        "rsi_healthy_max": 70,
        "rsi_overbought": 80.0,
        "max_daily_volatility": 0.07,
        "min_liquidity": 500,
        "min_price": 15.0,
        "volume_dry_ratio": 0.5,
        "volume_above_avg_ratio": 0.8,
    },
    "aggressive": {
        "rsi_overbought": 85.0,
        "max_daily_volatility": 0.07,
        "min_liquidity": 300,
        "min_price": 10.0,
        "volume_dry_ratio": 0.5,
        "volume_above_avg_ratio": 0.8,
    },
    "buzz": {
        "rsi_overbought": 80.0,
        "max_daily_volatility": 0.10,
        "min_liquidity": 500,
        "min_price": 10.0,
        "volume_above_avg_ratio": 1.0,
    },
    "nightly": {
        "rsi_healthy_min": 50,
        "rsi_healthy_max": 70,
        "rsi_overbought": 75.0,
        "min_liquidity": 500,
        "min_price": 15.0,
        "volume_above_avg_ratio": 0.8,
        "volume_dry_ratio": 0.5,
    },
}

PRE_MIGRATION_INDICATORS = IndicatorParameters(
    rsi_period=14,
    macd_fast=12,
    macd_slow=26,
    macd_signal=9,
    ma_short=5,
    ma_mid=20,
    ma_long=60,
    bb_period=20,
    bb_std=2.0,
    stoch_k=9,
    stoch_d=3,
    adx_period=14,
    atr_period=14,
    mfi_period=14,
)
PRE_MIGRATION_SCORING = TechnicalScoring(base_score=50, block_failure_penalty=15, failure_score_reduction=5, pass_score_increase=5)

Composition = dict[RuleEffect, list[TechnicalCriterion]]


def pre_migration_composition(old_name: str) -> Composition:
    t = {**PRE_MIGRATION_DEFAULT_THRESHOLDS, **PRE_MIGRATION_STRATEGY_THRESHOLDS[old_name]}
    ma_mid, ma_long = PRE_MIGRATION_INDICATORS.ma_mid, PRE_MIGRATION_INDICATORS.ma_long
    atr = AtrRangeCriterion(t["atr_min_pct"], t["atr_max_pct"])
    adx = AdxTrendCriterion(t["adx_min"], t["adx_max"], require_direction=True)
    mfi = MfiThresholdCriterion(t["mfi_overbought"])
    observations: list[TechnicalCriterion] = [
        RsiRangeCriterion(t["rsi_healthy_min"], t["rsi_healthy_max"]),
        GoldenCrossCriterion(max_cross_margin=t["golden_cross_margin"]),
        BollingerSqueezeCriterion(t["bollinger_squeeze_bandwidth"]),
        VolumeExpansionCriterion(t["volume_breakout_ratio"]),
        ObvTrendCriterion(),
    ]

    match old_name:
        case "conservative":
            must_pass: list[TechnicalCriterion] = [
                PriceAboveMaCriterion(ma_mid),
                PriceAboveMaCriterion(ma_long),
                MaAlignmentCriterion(ma_mid, ma_long),
                MacdBullishCriterion(require_above_signal=True, require_positive=True),
                RsiRangeCriterion(t["rsi_healthy_min"], t["rsi_healthy_max"]),
                StochasticHealthCriterion(max_k=t["stoch_overbought"]),
                BollingerThresholdCriterion(t["bollinger_max_pct_b"]),
                DailyRangeCriterion(t["max_daily_volatility"]),
                LiquidityCriterion(t["min_liquidity"]),
                MinimumPriceCriterion(t["min_price"]),
                VolumeExpansionCriterion(t["volume_dry_ratio"]),
            ]
            should_pass: list[TechnicalCriterion] = [
                adx,
                VolumeExpansionCriterion(t["volume_above_avg_ratio"]),
                BollingerPositionCriterion(),
                MacdBullishCriterion(require_above_signal=False, require_histogram_positive=True),
                mfi,
                StochasticHealthCriterion(max_k=None, require_k_above_d=True),
                atr,
            ]
        case "moderate":
            must_pass = [
                PriceAboveMaCriterion(ma_mid),
                MaAlignmentCriterion(ma_mid, ma_long),
                MacdBullishCriterion(require_above_signal=True),
                RsiRangeCriterion(min_rsi=t["rsi_healthy_min"]),
                RsiRangeCriterion(max_rsi=t["rsi_overbought"]),
                DailyRangeCriterion(t["max_daily_volatility"]),
                LiquidityCriterion(t["min_liquidity"]),
                MinimumPriceCriterion(t["min_price"]),
                VolumeExpansionCriterion(t["volume_dry_ratio"]),
            ]
            should_pass = [
                PriceAboveMaCriterion(ma_long),
                MacdBullishCriterion(require_above_signal=False, require_positive=True, require_histogram_positive=True),
                adx,
                StochasticHealthCriterion(max_k=t["stoch_overbought"], require_k_above_d=True),
                BollingerThresholdCriterion(t["bollinger_max_pct_b"]),
                BollingerPositionCriterion(),
                VolumeExpansionCriterion(t["volume_above_avg_ratio"]),
                mfi,
                atr,
            ]
        case "aggressive":
            must_pass = [
                PriceAboveMaCriterion(ma_mid),
                MacdBullishCriterion(require_above_signal=True),
                RsiRangeCriterion(max_rsi=t["rsi_overbought"]),
                DailyRangeCriterion(t["max_daily_volatility"]),
                LiquidityCriterion(t["min_liquidity"]),
                MinimumPriceCriterion(t["min_price"]),
                VolumeExpansionCriterion(t["volume_dry_ratio"]),
            ]
            should_pass = [
                PriceAboveMaCriterion(ma_long),
                MacdBullishCriterion(require_above_signal=False, require_positive=True, require_histogram_positive=True),
                adx,
                StochasticHealthCriterion(max_k=t["stoch_overbought"], require_k_above_d=True),
                BollingerThresholdCriterion(t["bollinger_max_pct_b"]),
                VolumeExpansionCriterion(t["volume_above_avg_ratio"]),
                mfi,
                atr,
            ]
        case "buzz":
            must_pass = [
                MinimumPriceCriterion(t["min_price"]),
                LiquidityCriterion(t["min_liquidity"]),
                DailyRangeCriterion(t["max_daily_volatility"]),
            ]
            should_pass = [
                RsiRangeCriterion(max_rsi=t["rsi_overbought"]),
                VolumeExpansionCriterion(t["volume_above_avg_ratio"]),
                MacdBullishCriterion(require_above_signal=True),
                StochasticHealthCriterion(max_k=t["stoch_overbought"]),
            ]
        case "nightly":
            must_pass = [
                PriceAboveMaCriterion(ma_mid),
                MaAlignmentCriterion(ma_mid, ma_long),
                MacdBullishCriterion(require_above_signal=True),
                RsiRangeCriterion(min_rsi=t["rsi_healthy_min"]),
                RsiRangeCriterion(max_rsi=t["rsi_overbought"]),
                LiquidityCriterion(t["min_liquidity"]),
                MinimumPriceCriterion(t["min_price"]),
                VolumeExpansionCriterion(t["volume_above_avg_ratio"]),
            ]
            should_pass = [
                PriceAboveMaCriterion(ma_long),
                adx,
                BollingerPositionCriterion(),
                VolumeExpansionCriterion(t["volume_dry_ratio"]),
                mfi,
                atr,
            ]
        case _:
            raise AssertionError(old_name)

    return {
        RuleEffect.BLOCK_ON_FAIL: must_pass,
        RuleEffect.REDUCE_SCORE_ON_FAIL: should_pass,
        RuleEffect.INCREASE_SCORE_ON_PASS: observations,
    }


MIGRATED_STRATEGY_IDS = {
    "conservative": "conservative",
    "moderate": "moderate",
    "aggressive": "aggressive",
    "buzz": "buzz_safety_only",
    "nightly": "nightly",
}


@pytest.fixture(scope="module")
def template_settings(tmp_path_factory: pytest.TempPathFactory) -> TechnicalSettings:
    template = tmp_path_factory.mktemp("config") / "technical.yaml"
    shutil.copyfile(TEMPLATE_PATH, template)
    return asyncio.run(YamlTechnicalSettingsRepository(template).load())


def composition_of(strategy: TechnicalStrategy) -> Composition:
    return {effect: [rule.criterion for rule in strategy.rules if rule.effect == effect] for effect in RuleEffect}


@pytest.mark.parametrize("old_name", MIGRATED_STRATEGY_IDS)
def test_strategy_composition_matches_pre_migration_factory(template_settings: TechnicalSettings, old_name: str) -> None:
    strategy = template_settings.get_strategy(MIGRATED_STRATEGY_IDS[old_name])

    assert composition_of(strategy) == pre_migration_composition(old_name)
    assert strategy.indicators == PRE_MIGRATION_INDICATORS
    assert strategy.scoring == PRE_MIGRATION_SCORING


def make_stock(
    *,
    price: float,
    low: float,
    high: float,
    volumes: list[int],
    volume_ma5: float,
    ma20: float,
    ma60: float,
    macd: tuple[float, float],
    rsi: float,
    stochastic: tuple[float, float],
    percent_b: float,
) -> Stock:
    start = datetime(2026, 6, 1)
    bars = [
        Ohlcv(ts=start + timedelta(days=index), open=price, high=price, low=price, close=price, volume=volume)
        for index, volume in enumerate(volumes[:-1])
    ]
    bars.append(Ohlcv(ts=start + timedelta(days=len(bars)), open=low, high=high, low=low, close=price, volume=volumes[-1]))
    macd_line, macd_signal = macd
    stochastic_k, stochastic_d = stochastic

    return Stock(
        stock_id="2330",
        ohlcv=bars,
        indicators=TechnicalIndicators(
            rsi=Rsi(period=14, value=rsi),
            macd=Macd(fast=12, slow=26, signal_period=9, line=macd_line, signal=macd_signal, histogram=macd_line - macd_signal),
            ma=MovingAverages(price_ma={5: price, 20: ma20, 60: ma60}, volume_ma={5: volume_ma5}),
            bollinger=BollingerBands(
                period=20, std=2.0, upper=ma20 * 1.1, middle=ma20, lower=ma20 * 0.9, bandwidth=0.2, percent_b=percent_b
            ),
            stochastic=Stochastic(k_period=9, d_period=3, percent_k=stochastic_k, percent_d=stochastic_d),
            adx=Adx(period=14, adx=25, plus_di=30, minus_di=15),
            atr=Atr(period=14, value=price * 0.03, percent=0.03),
            obv=Obv(ma_period=20, value=5000, moving_average=4000),
            mfi=Mfi(period=14, value=70),
        ),
    )


HOT_BREAKOUT = make_stock(
    price=18.0,
    low=17.5,
    high=18.55,
    volumes=[1100, 1100, 1100, 1100, 600],
    volume_ma5=1000,
    ma20=16.0,
    ma60=15.0,
    macd=(0.5, 0.3),
    rsi=72,
    stochastic=(85, 80),
    percent_b=0.88,
)
OVERHEATED_SPIKE = make_stock(
    price=12.0,
    low=11.5,
    high=12.535,
    volumes=[380, 380, 380, 380, 480],
    volume_ma5=400,
    ma20=11.0,
    ma60=10.5,
    macd=(0.2, 0.35),
    rsi=82,
    stochastic=(90, 85),
    percent_b=0.95,
)
QUIET_DOWNTREND = make_stock(
    price=25.0,
    low=24.75,
    high=25.25,
    volumes=[2000, 2000, 2000, 2000, 2000],
    volume_ma5=2000,
    ma20=26.0,
    ma60=27.0,
    macd=(-0.3, -0.2),
    rsi=40,
    stochastic=(30, 35),
    percent_b=0.3,
)

PRE_MIGRATION_HARD_FAILURES = [
    (
        HOT_BREAKOUT,
        "conservative",
        [
            "RSI Range 50.0-65.0",
            "Stochastic Health (K < 80.0)",
            "Bollinger %B < 0.85",
            "Daily Range Safety",
            "Minimum Price Check",
            "Volume Expansion >= 0.7x vs MA_5",
        ],
    ),
    (HOT_BREAKOUT, "moderate", []),
    (HOT_BREAKOUT, "aggressive", []),
    (HOT_BREAKOUT, "buzz", []),
    (HOT_BREAKOUT, "nightly", ["Volume Expansion >= 0.8x vs MA_5"]),
    (
        OVERHEATED_SPIKE,
        "conservative",
        [
            "MACD Bullish (line > signal, line > 0)",
            "RSI Range 50.0-65.0",
            "Stochastic Health (K < 80.0)",
            "Bollinger %B < 0.85",
            "Daily Range Safety",
            "Liquidity Check",
            "Minimum Price Check",
        ],
    ),
    (
        OVERHEATED_SPIKE,
        "moderate",
        ["MACD Bullish (line > signal)", "RSI Range 0.0-80.0", "Daily Range Safety", "Liquidity Check", "Minimum Price Check"],
    ),
    (OVERHEATED_SPIKE, "aggressive", ["MACD Bullish (line > signal)", "Daily Range Safety"]),
    (OVERHEATED_SPIKE, "buzz", ["Liquidity Check"]),
    (OVERHEATED_SPIKE, "nightly", ["MACD Bullish (line > signal)", "RSI Range 0.0-75.0", "Liquidity Check", "Minimum Price Check"]),
    (
        QUIET_DOWNTREND,
        "conservative",
        [
            "Price Above MA_20",
            "Price Above MA_60",
            "MA_20 > MA_60 Alignment",
            "MACD Bullish (line > signal, line > 0)",
            "RSI Range 50.0-65.0",
        ],
    ),
    (
        QUIET_DOWNTREND,
        "moderate",
        ["Price Above MA_20", "MA_20 > MA_60 Alignment", "MACD Bullish (line > signal)", "RSI Range 50.0-100.0"],
    ),
    (QUIET_DOWNTREND, "aggressive", ["Price Above MA_20", "MACD Bullish (line > signal)"]),
    (QUIET_DOWNTREND, "buzz", []),
    (
        QUIET_DOWNTREND,
        "nightly",
        ["Price Above MA_20", "MA_20 > MA_60 Alignment", "MACD Bullish (line > signal)", "RSI Range 50.0-100.0"],
    ),
]


@pytest.mark.parametrize(("stock", "old_name", "hard_failures"), PRE_MIGRATION_HARD_FAILURES)
def test_strategy_hard_failures_match_pre_migration_thresholds(
    template_settings: TechnicalSettings, stock: Stock, old_name: str, hard_failures: list[str]
) -> None:
    report = template_settings.get_strategy(MIGRATED_STRATEGY_IDS[old_name]).evaluate(stock)

    assert report.hard_failures == hard_failures
    assert report.passed is (not hard_failures)


@pytest.mark.parametrize(
    ("stock", "soft_failures"),
    [
        (OVERHEATED_SPIKE, ["RSI Range 0.0-80.0", "MACD Bullish (line > signal)", "Stochastic Health (K < 80.0)"]),
        (QUIET_DOWNTREND, ["MACD Bullish (line > signal)"]),
    ],
)
def test_buzz_confirmation_failures_only_lower_the_score(
    template_settings: TechnicalSettings, stock: Stock, soft_failures: list[str]
) -> None:
    report = template_settings.get_strategy("buzz_safety_only").evaluate(stock)

    assert report.soft_failures == soft_failures


def test_buzz_safety_only_rejects_only_on_tradeability_and_safety(template_settings: TechnicalSettings) -> None:
    rules = template_settings.get_strategy("buzz_safety_only").rules

    assert {type(rule.criterion) for rule in rules if rule.effect == RuleEffect.BLOCK_ON_FAIL} == {
        MinimumPriceCriterion,
        LiquidityCriterion,
        DailyRangeCriterion,
    }
    assert {type(rule.criterion) for rule in rules if rule.effect == RuleEffect.REDUCE_SCORE_ON_FAIL} == {
        RsiRangeCriterion,
        VolumeExpansionCriterion,
        MacdBullishCriterion,
        StochasticHealthCriterion,
    }


def test_social_buzz_uses_buzz_safety_only_by_default(template_settings: TechnicalSettings) -> None:
    assert template_settings.buzz_strategy.strategy_id == "buzz_safety_only"


@pytest.mark.parametrize(
    ("stock", "strategy_id", "hard_failures"),
    [
        (HOT_BREAKOUT, "buzz_safety_only", []),
        (HOT_BREAKOUT, "buzz_loose_confirmation", ["Volume Expansion >= 1.0x vs MA_5"]),
        (HOT_BREAKOUT, "buzz_strict_confirmation", ["Volume Expansion >= 1.0x vs MA_5", "Stochastic Health (K < 80.0)"]),
        (OVERHEATED_SPIKE, "buzz_safety_only", ["Liquidity Check"]),
        (OVERHEATED_SPIKE, "buzz_loose_confirmation", ["Liquidity Check", "MACD Bullish (line > signal)"]),
        (
            OVERHEATED_SPIKE,
            "buzz_strict_confirmation",
            ["Liquidity Check", "RSI Range 0.0-80.0", "MACD Bullish (line > signal)", "Stochastic Health (K < 80.0)"],
        ),
        (QUIET_DOWNTREND, "buzz_safety_only", []),
        (QUIET_DOWNTREND, "buzz_loose_confirmation", ["MACD Bullish (line > signal)"]),
        (QUIET_DOWNTREND, "buzz_strict_confirmation", ["MACD Bullish (line > signal)"]),
    ],
)
def test_buzz_modes_differ_in_which_confirmations_reject_a_stock(
    template_settings: TechnicalSettings, stock: Stock, strategy_id: str, hard_failures: list[str]
) -> None:
    report = template_settings.get_strategy(strategy_id).evaluate(stock)

    assert report.hard_failures == hard_failures


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy_id", ["buzz_safety_only", "buzz_loose_confirmation", "buzz_strict_confirmation"])
async def test_buzz_strategy_id_selects_the_buzz_mode(tmp_path: Path, strategy_id: str) -> None:
    template = tmp_path / "technical.yaml"
    template.write_text(
        TEMPLATE_PATH.read_text(encoding="utf-8").replace("buzz_strategy_id: buzz_safety_only", f"buzz_strategy_id: {strategy_id}"),
        encoding="utf-8",
    )

    settings = await YamlTechnicalSettingsRepository(template).load()

    assert settings.buzz_strategy.strategy_id == strategy_id
