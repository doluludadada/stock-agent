from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScreeningResult:
    """
    Captures the outcome of a screening policy execution.
    """

    passed: bool
    failed_rules: list[str] = field(default_factory=list)

    # Optional: Capture values that triggered the failure for debugging
    # e.g., "RSI=90" when rule is <80
    details: dict[str, str] = field(default_factory=dict)
