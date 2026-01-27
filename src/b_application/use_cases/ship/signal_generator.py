from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.model.trading.signal import TradeSignal
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.rules.trading.decision import DecisionRule
from src.b_application.schemas.config import AppConfig


class SignalGenerator:
    """
    Use Case: Convert Contexts into Signals.
    """

    def __init__(
        self,
        decision_rule: DecisionRule,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._decision_rule = decision_rule
        self._config = config
        self._logger = logger

    def execute(self, contexts: list[AnalysisContext]) -> list[TradeSignal]:
        self._logger.info(f"Generating signals for {len(contexts)} stocks")

        signals: list[TradeSignal] = []

        for ctx in contexts:
            signal = self._decision_rule.decide(ctx)

            if signal:
                signals.append(signal)
                self._logger.debug(f"Signal generated: {signal.stock_id} {signal.action} Score:{signal.score}")

        return signals
