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


UserId = NewType("UserId", str)
"""
One user, and the owner of every row an owned table holds for them. Opaque text: a registered user gets uuid4().hex,
and the first administrator gets the id the single-owner versions stored their data under, so an upgraded
installation's data is the first administrator's with no owned row rewritten.
"""

SessionToken = NewType("SessionToken", str)
"""The secret a signed-in browser presents in its session cookie. Only its SHA-256 digest is stored."""


def new_user_id() -> UserId:
    return UserId(uuid4().hex)
