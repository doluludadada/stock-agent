# backend/src/d_presentation/dependencies/rules.py

from fastapi import Depends

from a_domain.rules.ai.parser import AiReportParser
from a_domain.rules.ai.prompt import AiReportPromptBuilder
from a_domain.rules.collect import CandidateSelectionRule
from a_domain.rules.collect.article_quality import ArticleQualityRule
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.scoring.composite import CompositeScoreRule
from a_domain.rules.scoring.technical import TechnicalScoreCalculator
from a_domain.rules.technical.policy import TechnicalScreeningPolicy
from a_domain.rules.trading.action import ActionRule
from a_domain.rules.trading.decision import DecisionRule
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.rules.trading.reason import ReasonRule
from a_domain.rules.trading.sizing import SizingRule
from b_application.factories import TechnicalPolicyFactory
from b_application.schemas.config import AppConfig
from d_presentation.dependencies.core import get_settings


# TODO: I think i dont really need it. They will build in usecase class.
def get_data_freshness_rule() -> DataFreshnessRule:
    return DataFreshnessRule()


def get_quality_rule(config: AppConfig = Depends(get_settings)) -> ArticleQualityRule:
    return ArticleQualityRule(
        spam_keywords=frozenset(config.collect_rules.spam_keywords),
        financial_keywords=frozenset(config.collect_rules.financial_keywords),
        min_chars_stock=config.quality.min_chars_stock,
        min_chars_news=config.quality.min_chars_news,
        min_chars_gossip=config.quality.min_chars_gossip,
    )


def get_technical_score_calculator(
    config: AppConfig = Depends(get_settings),
) -> TechnicalScoreCalculator:
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


def get_technical_screening_policy(
    config: AppConfig = Depends(get_settings),
) -> TechnicalScreeningPolicy:
    return TechnicalPolicyFactory().create(
        config.analysis.active_strategy,
        config.strategy,
    )


def get_ai_report_prompt_builder(
    config: AppConfig = Depends(get_settings),
) -> AiReportPromptBuilder:
    return AiReportPromptBuilder(
        fundamental_template=config.prompts.analysis_report_fundamental,
        momentum_template=config.prompts.analysis_report_momentum,
        max_articles=config.analysis.article_fetch_limit,
        max_content_length=config.ai.article_content_length,
    )


def get_ai_report_parser() -> AiReportParser:
    return AiReportParser()


def get_composite_score_rule(
    config: AppConfig = Depends(get_settings),
) -> CompositeScoreRule:
    return CompositeScoreRule(
        technical_weight=config.analysis.technical_weight,
        sentiment_weight=config.analysis.sentiment_weight,
    )


def get_action_rule(config: AppConfig = Depends(get_settings)) -> ActionRule:
    return ActionRule(
        buy_threshold=config.analysis.min_combined_score_buy,
        sell_threshold=config.analysis.max_combined_score_sell,
    )


def get_reason_rule() -> ReasonRule:
    return ReasonRule()


def get_sizing_rule(config: AppConfig = Depends(get_settings)) -> SizingRule:
    return SizingRule(
        position_pct=config.analysis.risk_per_trade_pct,
        lot_size=1,
    )


def get_entry_rule(
    action_rule: ActionRule = Depends(get_action_rule),
    sizing_rule: SizingRule = Depends(get_sizing_rule),
    reason_rule: ReasonRule = Depends(get_reason_rule),
) -> EntryRule:
    return EntryRule(
        action_rule=action_rule,
        sizing_rule=sizing_rule,
        reason_rule=reason_rule,
    )


def get_exit_rule(
    config: AppConfig = Depends(get_settings),
    action_rule: ActionRule = Depends(get_action_rule),
    reason_rule: ReasonRule = Depends(get_reason_rule),
) -> ExitRule:
    return ExitRule(
        stop_loss_pct=config.analysis.stop_loss_pct,
        action_rule=action_rule,
        reason_rule=reason_rule,
    )


def get_decision_rule(
    entry_rule: EntryRule = Depends(get_entry_rule),
    exit_rule: ExitRule = Depends(get_exit_rule),
) -> DecisionRule:
    return DecisionRule(
        entry_rule=entry_rule,
        exit_rule=exit_rule,
    )


def get_candidate_selection_rule() -> CandidateSelectionRule:
    return CandidateSelectionRule()
