from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.model.analysis.signal import TradeSignal
from src.a_domain.ports.system.logging_port import ILoggingPort
from src.a_domain.rules.ship.signal_decision import SignalDecisionRule


class SignalGenerator:
    """
    Use Case: Convert Contexts into Signals using Decision Rules.
    """

    def __init__(
        self,
        decision_rule: SignalDecisionRule,
        logger: ILoggingPort,
    ):
        self._decision_rule = decision_rule
        self._logger = logger

    def execute(self, contexts: list[AnalysisContext]) -> list[TradeSignal]:
        self._logger.info(f"Generating signals for {len(contexts)} stocks")

        signals: list[TradeSignal] = []

        for ctx in contexts:
            # Delegate decision logic to Domain Rule
            signal = self._decision_rule.decide(ctx)

            if signal:
                signals.append(signal)

        self._logger.success(f"Generated {len(signals)} signals.")
        return signals
