# backend/src/a_domain/rules/technical/criteria/base.py

from typing import Protocol

from a_domain.model.market.stock import Stock


class TechnicalCriterion(Protocol):
    """
    A technical screening criterion.

    This is only for technical stock filters:
        Stock + calculated indicators -> pass / fail

    Do not use this for:
        - article quality rules
        - data freshness rules
        - action rules
        - sizing rules
        - entry / exit decision rules
    """

    @property
    def name(self) -> str: ...

    def apply(self, stock: Stock) -> bool: ...
