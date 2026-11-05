from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, ClassVar, Self

from pydantic import TypeAdapter
from sqlalchemy import CheckConstraint, ForeignKeyConstraint
from sqlmodel import Field, SQLModel

from a_domain.rules.technical.calculation.calculator import IndicatorParameters
from a_domain.rules.technical.formula import (
    Arithmetic,
    Comparison,
    Condition,
    ConditionGroup,
    IndicatorValue,
    LatestPrice,
    MarketValue,
    NumericExpression,
)
from a_domain.rules.technical.strategy import TechnicalScoring, TechnicalSettings, TechnicalStrategy
from a_domain.types.enums import FormulaNode

OWNER = "technical_settings.owner_id"
STRATEGY = ("technical_strategies.owner_id", "technical_strategies.strategy_id")

STORED_STRATEGY = TypeAdapter(TechnicalStrategy)
"""pydantic builds a saved strategy as it builds one from config/strategies: no file calls its or its rules' constructor."""

STORED_INDICATOR = TypeAdapter(IndicatorParameters)


class TechnicalSettingsDTO(SQLModel, table=True):
    """
    One owner's selections and save counter. The owner's strategies, their indicators, rules and formula nodes are
    rows of the tables below, always replaced together with a revision increment in one transaction.
    """

    __tablename__: ClassVar[str] = "technical_settings"

    owner_id: str = Field(primary_key=True)
    active_strategy_id: str
    buzz_strategy_id: str
    revision: int

    @classmethod
    def from_domain(cls, owner_id: str, settings: TechnicalSettings) -> Self:
        return cls(
            owner_id=owner_id,
            active_strategy_id=settings.active_strategy_id,
            buzz_strategy_id=settings.buzz_strategy_id,
            revision=settings.revision,
        )

    @classmethod
    def child_rows(cls, owner_id: str, settings: TechnicalSettings) -> list[tuple[type[SQLModel], list[dict[str, Any]]]]:
        """Every row below the owner's settings row, parent tables first."""
        strategies, indicators, rules, nodes = [], [], [], []

        for position, strategy in enumerate(settings.strategies):
            key = {"owner_id": owner_id, "strategy_id": strategy.strategy_id}
            strategies.append(TechnicalStrategyDTO(**key, position=position, name=strategy.name, **asdict(strategy.scoring)))
            indicators += [
                TechnicalIndicatorDTO(**key, indicator_id=name, **asdict(parameters))
                for name, parameters in strategy.indicators.items()
            ]

            for rule_position, rule in enumerate(strategy.rules):
                rules.append(rule_row := TechnicalRuleDTO(**key, position=rule_position, name=rule.name, effect=rule.effect))
                nodes += TechnicalFormulaNodeDTO.rows(rule_row, rule.condition)

        tables = {
            TechnicalStrategyDTO: strategies,
            TechnicalIndicatorDTO: indicators,
            TechnicalRuleDTO: rules,
            TechnicalFormulaNodeDTO: nodes,
        }
        return [(table, [row.model_dump() for row in rows]) for table, rows in tables.items() if rows]

    def to_domain(self, rows: Mapping[Any, Sequence[Any]]) -> TechnicalSettings:
        """The settings that this row and the owner's rows of the tables below hold, by table."""
        strategies = sorted(rows[TechnicalStrategyDTO], key=lambda row: row.position)

        return TechnicalSettings(
            active_strategy_id=self.active_strategy_id,
            buzz_strategy_id=self.buzz_strategy_id,
            strategies=tuple(strategy.to_domain(rows) for strategy in strategies),
            revision=self.revision,
        )


class TechnicalStrategyDTO(SQLModel, table=True):
    __tablename__: ClassVar[str] = "technical_strategies"
    __table_args__ = (ForeignKeyConstraint(["owner_id"], [OWNER], ondelete="CASCADE"),)

    owner_id: str = Field(primary_key=True)
    strategy_id: str = Field(primary_key=True)
    position: int
    """The strategy's place in the owner's list."""

    name: str
    base_score: int
    block_failure_penalty: int
    failure_score_reduction: int
    pass_score_increase: int

    def to_domain(self, rows: Mapping[Any, Sequence[Any]]) -> TechnicalStrategy:
        mine = {table: [row for row in table_rows if row.strategy_id == self.strategy_id] for table, table_rows in rows.items()}
        nodes = mine[TechnicalFormulaNodeDTO]
        rules = [
            {"name": rule.name, "effect": rule.effect, "condition": TechnicalFormulaNodeDTO.condition(nodes, rule.position)}
            for rule in sorted(mine[TechnicalRuleDTO], key=lambda rule: rule.position)
        ]
        scoring = TechnicalScoring(
            base_score=self.base_score,
            block_failure_penalty=self.block_failure_penalty,
            failure_score_reduction=self.failure_score_reduction,
            pass_score_increase=self.pass_score_increase,
        )
        indicators = {row.indicator_id: row.to_domain() for row in mine[TechnicalIndicatorDTO]}
        strategy = {"strategy_id": self.strategy_id, "name": self.name, "indicators": indicators, "scoring": scoring, "rules": rules}

        return STORED_STRATEGY.validate_python(strategy)


class TechnicalIndicatorDTO(SQLModel, table=True):
    """One indicator of one strategy. Each kind fills only its own parameter columns."""

    __tablename__: ClassVar[str] = "technical_indicators"
    __table_args__ = (ForeignKeyConstraint(["owner_id", "strategy_id"], list(STRATEGY), ondelete="CASCADE"),)

    owner_id: str = Field(primary_key=True)
    strategy_id: str = Field(primary_key=True)
    indicator_id: str = Field(primary_key=True)
    kind: str
    period: int | None = None
    fast: int | None = None
    slow: int | None = None
    signal: int | None = None
    std: float | None = None
    k_period: int | None = None
    d_period: int | None = None

    def to_domain(self) -> IndicatorParameters:
        """The kind chooses the parameters it reads from this row's columns; pydantic ignores the rest, the key included."""
        return STORED_INDICATOR.validate_python(self.model_dump(), extra="ignore")


class TechnicalRuleDTO(SQLModel, table=True):
    __tablename__: ClassVar[str] = "technical_rules"
    __table_args__ = (ForeignKeyConstraint(["owner_id", "strategy_id"], list(STRATEGY), ondelete="CASCADE"),)

    owner_id: str = Field(primary_key=True)
    strategy_id: str = Field(primary_key=True)
    position: int = Field(primary_key=True)
    name: str
    effect: str


class TechnicalFormulaNodeDTO(SQLModel, table=True):
    """
    One part of a rule's condition. Position 0 is the condition itself and has no parent; a part's children are the
    rows whose parent_position is its position, in position order: left then right, or a group's conditions. The
    domain model validates each part as it is read, so the table checks only what it alone sees: one root per rule.
    """

    __tablename__: ClassVar[str] = "technical_formula_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "strategy_id", "rule_position"],
            ["technical_rules.owner_id", "technical_rules.strategy_id", "technical_rules.position"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "strategy_id", "rule_position", "parent_position"],
            [
                "technical_formula_nodes.owner_id",
                "technical_formula_nodes.strategy_id",
                "technical_formula_nodes.rule_position",
                "technical_formula_nodes.position",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "strategy_id", "indicator_id"],
            ["technical_indicators.owner_id", "technical_indicators.strategy_id", "technical_indicators.indicator_id"],
        ),
        CheckConstraint("(position = 0) = (parent_position IS NULL)", name="one_root"),
    )

    owner_id: str = Field(primary_key=True)
    strategy_id: str = Field(primary_key=True)
    rule_position: int = Field(primary_key=True)
    position: int = Field(primary_key=True)
    parent_position: int | None = None
    node: str
    operator: str | None = None
    constant: float | None = None
    field: str | None = None
    indicator_id: str | None = None
    output: str | None = None
    bars_ago: int | None = None

    @classmethod
    def rows(
        cls, rule: TechnicalRuleDTO, part: Condition | NumericExpression, position: int = 0, parent: int | None = None
    ) -> list[Self]:
        """`part` at `position` and every part below it, in pre-order, as rows of the rule's condition."""
        key = {"owner_id": rule.owner_id, "strategy_id": rule.strategy_id, "rule_position": rule.position}
        key |= {"position": position, "parent_position": parent}
        children: Sequence[Condition | NumericExpression] = ()

        match part:
            case Comparison(operator=operator, left=left, right=right) | Arithmetic(operator=operator, left=left, right=right):
                row, children = cls(**key, node=part.type, operator=operator), (left, right)
            case ConditionGroup(operator=operator, conditions=conditions):
                row, children = cls(**key, node=part.type, operator=operator), conditions
            case MarketValue(field=field, bars_ago=bars_ago):
                row = cls(**key, node=part.type, field=field, bars_ago=bars_ago)
            case IndicatorValue(indicator_id=indicator_id, output=output, bars_ago=bars_ago):
                row = cls(**key, node=part.type, indicator_id=indicator_id, output=output, bars_ago=bars_ago)
            case LatestPrice():
                row = cls(**key, node=part.type)
            case _:
                row = cls(**key, node=FormulaNode.CONSTANT, constant=part)

        rows = [row]
        for child in children:
            rows += cls.rows(rule, child, position + len(rows), position)

        return rows

    @classmethod
    def condition(cls, rows: Sequence[Self], rule_position: int) -> Condition | NumericExpression | None:
        """The condition of the rule at `rule_position`, from the rows of its strategy."""
        children: dict[int | None, list[Self]] = defaultdict(list)

        for row in sorted(rows, key=lambda row: row.position):
            if row.rule_position == rule_position:
                children[row.parent_position].append(row)

        return children[None][0].to_domain(children)

    def to_domain(self, children: Mapping[int | None, Sequence[Self]]) -> Condition | NumericExpression | None:
        """
        The part this row holds, its children read first. The domain classes validate every column they read, and a
        row of no known type reads as None, which the part above it or the rule refuses.
        """
        parts: list[Any] = [child.to_domain(children) for child in children.get(self.position, ())]

        match self.model_dump():
            case {"node": FormulaNode.COMPARISON, "operator": operator}:
                return Comparison(operator=operator, left=parts[0], right=parts[1])
            case {"node": FormulaNode.ARITHMETIC, "operator": operator}:
                return Arithmetic(operator=operator, left=parts[0], right=parts[1])
            case {"node": FormulaNode.GROUP, "operator": operator}:
                return ConditionGroup(operator=operator, conditions=tuple(parts))
            case {"node": FormulaNode.MARKET, "field": field, "bars_ago": bars_ago}:
                return MarketValue(field=field, bars_ago=bars_ago)
            case {"node": FormulaNode.INDICATOR, "indicator_id": indicator_id, "output": output, "bars_ago": bars_ago}:
                return IndicatorValue(indicator_id=indicator_id, output=output, bars_ago=bars_ago)
            case {"node": FormulaNode.LATEST_PRICE}:
                return LatestPrice()
            case {"node": FormulaNode.CONSTANT, "constant": constant}:
                return constant
            case _:
                return None
