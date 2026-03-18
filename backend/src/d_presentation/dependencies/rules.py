from fastapi import Depends

from a_domain.rules.base import TradingRule
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.collect.quality_rule import QualityRule
from a_domain.rules.process.ai.parser import AiReportParser
from a_domain.rules.process.ai.prompt import AiReportPromptBuilder
from a_domain.rules.process.indicators.entry_timing.price_drop_rule import PriceDropRule
from a_domain.rules.process.indicators.entry_timing.volume_confirmation_rule import VolumeConfirmationRule
from a_domain.rules.process.indicators.momentum.macd_cross_rule import MacdCrossRule
from a_domain.rules.process.indicators.momentum.macd_positive_rule import MacdPositiveRule
from a_domain.rules.process.indicators.momentum.rsi_range_rule import RsiRangeRule
from a_domain.rules.process.indicators.momentum.stochastic_cross_rule import StochasticCrossRule
from a_domain.rules.process.indicators.trend.ma_alignment_rule import MaAlignmentRule
from a_domain.rules.process.indicators.trend.price_above_ma_rule import PriceAboveMaRule
from a_domain.rules.process.indicators.volatility.bollinger_threshold_rule import BollingerThresholdRule
from a_domain.rules.process.indicators.volatility.daily_range_rule import DailyRangeRule
from a_domain.rules.process.indicators.volume.liquidity_rule import LiquidityRule
from a_domain.rules.process.indicators.volume.minimum_price_rule import MinimumPriceRule
from a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from a_domain.rules.process.scoring.composite import CompositeScoreRule
from a_domain.rules.process.scoring.technical import TechnicalScoreCalculator
from a_domain.rules.trading.action import ActionRule
from a_domain.rules.trading.decision import DecisionRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.rules.trading.reason import ReasonRule
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import MaPeriod
from b_application.schemas.config import AppConfig
from d_presentation.dependencies.core import get_settings


def get_data_freshness_rule() -> DataFreshnessRule:
    return DataFreshnessRule()


def get_quality_rule(config: AppConfig = Depends(get_settings)) -> QualityRule:
    return QualityRule(
        spam_keywords=frozenset(config.collect_rules.spam_keywords),
        financial_keywords=frozenset(),  # TODO: Missing from config? 
        min_chars_stock=config.quality.min_chars_stock,
        min_chars_news=config.quality.min_chars_news,
        min_chars_gossip=config.quality.min_chars_gossip,
    )


def get_technical_score_calculator(config: AppConfig = Depends(get_settings)) -> TechnicalScoreCalculator:
    return TechnicalScoreCalculator(
        base=config.scoring.base,
        pass_bonus=config.scoring.pass_bonus,
        hard_failure_penalty=config.scoring.hard_failure_penalty,
        max_hard_penalty=config.scoring.max_hard_penalty,
        soft_failure_penalty=config.scoring.soft_failure_penalty,
        max_soft_penalty=config.scoring.max_soft_penalty,
        rsi_sweet_spot_bonus=config.scoring.rsi_sweet_spot_bonus,
        rsi_sweet_spot_min=config.scoring.rsi_sweet_spot_min,
        rsi_sweet_spot_max=config.scoring.rsi_sweet_spot_max,
        macd_bullish_bonus=config.scoring.macd_bullish_bonus,
        ma_present_bonus=config.scoring.ma_present_bonus,
    )


def get_technical_screening_policy(config: AppConfig = Depends(get_settings)) -> TechnicalScreeningPolicy:
    should_pass: list[TradingRule] = [
        PriceAboveMaRule(ma_period=MaPeriod.MA_20),
        MacdPositiveRule(),
        MaAlignmentRule(),
    ]

    return TechnicalScreeningPolicy(
        setup_must_pass=[
            BollingerThresholdRule(config.strategy.bollinger_max_pct_b),
            RsiRangeRule(config.strategy.rsi_healthy_min, config.strategy.rsi_healthy_max),
        ],
        safety_must_pass=[
            LiquidityRule(config.strategy.min_liquidity),
            MinimumPriceRule(config.strategy.min_price),
            DailyRangeRule(config.strategy.max_daily_volatility),
        ],
        should_pass=should_pass,
        info_only=[
            MacdCrossRule(),
            StochasticCrossRule(),
        ],
        entry_timing_must_pass=[
            PriceDropRule(config.strategy.max_drop_pct),
            VolumeConfirmationRule(config.strategy.min_volume_confirmation),
        ],
    )


def get_ai_report_prompt_builder(config: AppConfig = Depends(get_settings)) -> AiReportPromptBuilder:
    return AiReportPromptBuilder(
        fundamental_template=config.prompts.analysis_report_fundamental,
        momentum_template=config.prompts.analysis_report_momentum,
        max_articles=config.analysis.article_fetch_limit,
        max_content_length=config.ai.article_content_length,
    )


def get_ai_report_parser() -> AiReportParser:
    return AiReportParser()


def get_composite_score_rule(config: AppConfig = Depends(get_settings)) -> CompositeScoreRule:
    return CompositeScoreRule(
        technical_weight=config.analysis.technical_weight,
        sentiment_weight=config.analysis.sentiment_weight,
    )


def get_decision_rule(config: AppConfig = Depends(get_settings)) -> DecisionRule:
    return DecisionRule(
        action_rule=ActionRule(),
        reason_rule=ReasonRule(),
        sizing_rule=SizingRule(),
        total_capital=config.analysis.total_capital,
        risk_pct=config.analysis.risk_per_trade_pct,
    )


def get_exit_rule(config: AppConfig = Depends(get_settings)) -> ExitRule:
    return ExitRule(stop_loss_pct=config.analysis.stop_loss_pct)
