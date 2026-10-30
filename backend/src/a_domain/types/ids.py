from typing import NewType
from uuid import UUID, uuid4

RunId = NewType("RunId", UUID)
"""One workflow run: a menu action or a manual BUY."""

DecisionId = NewType("DecisionId", UUID)
"""One TradeSignal. The saved signal row and the order that executes it share it."""

OrderId = NewType("OrderId", UUID)
"""One order record."""


def new_run_id() -> RunId:
    return RunId(uuid4())


def new_decision_id() -> DecisionId:
    return DecisionId(uuid4())


def new_order_id() -> OrderId:
    return OrderId(uuid4())
