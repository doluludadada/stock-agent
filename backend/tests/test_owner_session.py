"""
The owner guard on a real database of each backend: an owner session reads and changes only its owner's rows of an
owned table (a table with an owner_id column), get_session refuses owned tables, and an adapter built for no owner
refuses before any SQL.
"""

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, insert, update
from sqlmodel import SQLModel, col, select
from support.harness import harness_settings

from a_domain.types.errors import SignInRequired
from a_domain.types.ids import UserId
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.owned_rows import OwnedTableOutsideOwnerSession
from c_infrastructure.database.models.technical_settings_dto import TechnicalSettingsDTO
from c_infrastructure.database.models.watchlist_dto import WatchlistDTO
from c_infrastructure.technical.sql_technical_settings_repository import SqlTechnicalSettingsRepository

ALICE, BOB = UserId("alice"), UserId("bob")
SOURCE = Path(__file__).resolve().parents[1] / "src"


def settings_row(owner_id: str, revision: int = 0) -> TechnicalSettingsDTO:
    return TechnicalSettingsDTO(owner_id=owner_id, active_strategy_id="trend", buzz_strategy_id="buzz", revision=revision)


@pytest_asyncio.fixture
async def db(database: DatabaseConnector) -> DatabaseConnector:
    """The database with a technical settings row of each owner."""
    for owner_id in (ALICE, BOB):
        async with database.for_owner(owner_id).owner_session() as session:
            session.add(settings_row(owner_id))
            await session.commit()

    return database


async def revisions(db: DatabaseConnector) -> dict[str, int]:
    found = {}

    for owner_id in (ALICE, BOB):
        async with db.for_owner(owner_id).owner_session() as session:
            found |= {row.owner_id: row.revision for row in (await session.execute(select(TechnicalSettingsDTO))).scalars()}

    return found


@pytest.mark.asyncio
async def test_an_owner_session_reads_only_its_owners_rows(db: DatabaseConnector) -> None:
    async with db.for_owner(ALICE).owner_session() as session:
        rows = (await session.execute(select(TechnicalSettingsDTO))).scalars().all()
        owners = (await session.execute(select(TechnicalSettingsDTO.owner_id))).scalars().all()
        own, other = await session.get(TechnicalSettingsDTO, ALICE), await session.get(TechnicalSettingsDTO, BOB)

    assert [row.owner_id for row in rows] == owners == [ALICE]
    assert own is not None and own.owner_id == ALICE
    assert other is None


@pytest.mark.asyncio
async def test_an_owner_session_updates_and_deletes_only_its_owners_rows(db: DatabaseConnector) -> None:
    async with db.for_owner(ALICE).owner_session() as session:
        await session.execute(update(TechnicalSettingsDTO).values(revision=5))
        await session.commit()

    assert await revisions(db) == {ALICE: 5, BOB: 0}

    async with db.for_owner(BOB).owner_session() as session:
        await session.execute(delete(TechnicalSettingsDTO).where(col(TechnicalSettingsDTO.revision) >= 0))
        await session.commit()

    assert await revisions(db) == {ALICE: 5}


@pytest.mark.asyncio
async def test_an_owner_session_never_writes_a_row_of_another_owner(db: DatabaseConnector) -> None:
    attempts = [
        lambda session: session.merge(settings_row(BOB, revision=9)),
        lambda session: session.execute(insert(TechnicalSettingsDTO), [settings_row(BOB).model_dump()]),
        lambda session: session.execute(insert(TechnicalSettingsDTO).values(**settings_row(ALICE).model_dump())),
    ]

    for attempt in attempts:
        with pytest.raises(OwnedTableOutsideOwnerSession):
            async with db.for_owner(ALICE).owner_session() as session:
                await attempt(session)
                await session.commit()

    with pytest.raises(OwnedTableOutsideOwnerSession):
        async with db.for_owner(ALICE).owner_session() as session:
            session.add(settings_row(BOB, revision=9))
            await session.commit()

    assert await revisions(db) == {ALICE: 0, BOB: 0}


@pytest.mark.asyncio
async def test_an_owner_session_inserts_its_own_rows_through_the_orm(db: DatabaseConnector) -> None:
    async with db.for_owner(ALICE).owner_session() as session:
        await session.execute(delete(TechnicalSettingsDTO))
        await session.execute(insert(TechnicalSettingsDTO), [settings_row(ALICE, revision=3).model_dump()])
        await session.commit()

    assert await revisions(db) == {ALICE: 3, BOB: 0}


@pytest.mark.asyncio
async def test_the_shared_session_refuses_every_owned_table(db: DatabaseConnector) -> None:
    statements = [select(TechnicalSettingsDTO), update(TechnicalSettingsDTO).values(revision=1), delete(TechnicalSettingsDTO)]

    for statement in statements:
        with pytest.raises(OwnedTableOutsideOwnerSession):
            async with db.get_session() as session:
                await session.execute(statement)

    with pytest.raises(OwnedTableOutsideOwnerSession):
        async with db.get_session() as session:
            await session.get(TechnicalSettingsDTO, ALICE)

    with pytest.raises(OwnedTableOutsideOwnerSession):
        async with db.get_session() as session:
            session.add(settings_row(UserId("carol")))
            await session.commit()

    assert await revisions(db) == {ALICE: 0, BOB: 0}


def watched(owner_id: str, stock_id: str) -> WatchlistDTO:
    return WatchlistDTO(owner_id=owner_id, stock_id=stock_id, type="manual", created_at=datetime(2026, 11, 4, tzinfo=UTC))


async def watch_two_stocks_each(db: DatabaseConnector) -> None:
    for owner_id in (ALICE, BOB):
        async with db.for_owner(owner_id).owner_session() as session:
            session.add_all([watched(owner_id, "2330"), watched(owner_id, "2317")])
            await session.commit()


async def watchlist_rows(db: DatabaseConnector) -> list[tuple[str, str]]:
    found = []

    for owner_id in (ALICE, BOB):
        async with db.for_owner(owner_id).owner_session() as session:
            found += [(row.owner_id, row.stock_id) for row in (await session.execute(select(WatchlistDTO))).scalars()]

    return sorted(found)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statement", "alices"),
    [
        pytest.param(select(func.count()).select_from(WatchlistDTO), 2, id="count-select-from"),
        pytest.param(select(func.count(col(WatchlistDTO.stock_id))), 2, id="count-of-a-column"),
        pytest.param(
            select(func.count()).where(select(WatchlistDTO.stock_id).where(col(WatchlistDTO.owner_id) == BOB).exists()), 0, id="exists"
        ),
        pytest.param(select(func.count()).select_from(select(WatchlistDTO.stock_id).subquery()), 2, id="subquery"),
        pytest.param(
            select(func.count())
            .select_from(TechnicalSettingsDTO)
            .join(WatchlistDTO, col(WatchlistDTO.stock_id) == col(TechnicalSettingsDTO.active_strategy_id), isouter=True),
            1,
            id="join",
        ),
    ],
)
async def test_an_owner_session_scopes_an_owned_table_wherever_a_statement_names_it(
    db: DatabaseConnector, statement: Any, alices: int
) -> None:
    """Each statement counts Alice's rows only; through the shared session each raises."""
    await watch_two_stocks_each(db)

    async with db.for_owner(ALICE).owner_session() as session:
        assert (await session.execute(statement)).scalar_one() == alices

    with pytest.raises(OwnedTableOutsideOwnerSession):
        async with db.get_session() as session:
            await session.execute(statement)


@pytest.mark.asyncio
async def test_an_owner_session_refuses_an_update_that_moves_rows_and_a_core_statement(db: DatabaseConnector) -> None:
    await watch_two_stocks_each(db)
    refused = [
        update(WatchlistDTO).where(col(WatchlistDTO.stock_id) == "2317").values(owner_id="carol"),
        update(WatchlistDTO).values({WatchlistDTO.owner_id: BOB}),
        select(WatchlistDTO.__table__),
        delete(WatchlistDTO.__table__),
    ]

    for statement in refused:
        with pytest.raises(OwnedTableOutsideOwnerSession):
            async with db.for_owner(ALICE).owner_session() as session:
                await session.execute(statement)
                await session.commit()

    async with db.for_owner(ALICE).owner_session() as session:
        await session.execute(delete(WatchlistDTO).where(col(WatchlistDTO.stock_id) == "2330"))
        await session.commit()

    assert await watchlist_rows(db) == [(ALICE, "2317"), (BOB, "2317"), (BOB, "2330")]


@pytest.mark.asyncio
async def test_a_repository_built_for_no_owner_refuses_before_any_sql(db: DatabaseConnector) -> None:
    repository = SqlTechnicalSettingsRepository(db.for_owner(None))

    with pytest.raises(SignInRequired):
        await repository.load(harness_settings())

    with pytest.raises(SignInRequired):
        await repository.save(harness_settings())


def owned_dto_names() -> set[str]:
    """Every table class with an owner_id column, as the guard decides which tables are owned."""
    classes, pending = set(), list(SQLModel.__subclasses__())

    while pending:
        dto = pending.pop()
        pending += dto.__subclasses__()
        table = getattr(dto, "__table__", None)

        if table is not None and "owner_id" in table.c:
            classes.add(dto.__name__)

    return classes


def test_owned_adapters_use_only_statements_the_owner_guard_sees() -> None:
    """
    The guard sees ORM statements on mapped classes and rows added to the session. SQL text and Core statements on a
    Table pass it unseen, so a module that works with an owned table's rows must not build them.
    """
    owned = owned_dto_names()
    unseen = {"text", "table", "Table", "column", "literal_column"}
    found = []

    for path in sorted((SOURCE / "c_infrastructure").rglob("*.py")):
        if "models" in path.parts:
            continue

        tree = ast.parse(path.read_text())
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

        if not {alias.name for node in imports for alias in node.names} & owned:
            continue

        core = {alias.name for node in imports if (node.module or "").startswith("sqlalchemy") for alias in node.names}
        tables = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "__table__"}
        found += [f"{path.relative_to(SOURCE)} uses {name}" for name in sorted((core & unseen) | tables)]

    assert owned >= {"TechnicalSettingsDTO", "TechnicalStrategyDTO", "MockCash", "MockPosition"}
    assert found == []
