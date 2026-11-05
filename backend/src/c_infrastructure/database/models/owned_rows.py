"""
Which tables hold a user's rows, and the guard that keeps a session to one owner's rows of them.

An owned table is a table with an owner_id column. The rule is read from the tables, so a new owned table needs no
list. DatabaseConnector installs the guard on every session it opens: owner_session() with the bound owner, and
get_session() with none, which refuses every owned table.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import ClauseElement, Executable, Table, event
from sqlalchemy.orm import Mapper, ORMExecuteState, Session, with_loader_criteria
from sqlalchemy.sql import visitors
from sqlmodel.main import default_registry

OWNER_COLUMN = "owner_id"


class OwnedTableOutsideOwnerSession(RuntimeError):
    """
    A programming error: an owned table was used through get_session(), an owned row or an UPDATE named another owner,
    or a statement on an owned table took a shape the guard cannot scope: an INSERT whose rows are not execute()
    parameters, or a Core statement on the Table instead of its mapped class. Nothing was read or written.
    """


def owns_rows(mapper: Mapper[Any]) -> bool:
    return OWNER_COLUMN in mapper.local_table.c


def owned_mappers(statement: Executable) -> list[Mapper[Any]]:
    """
    Every owned table the statement names anywhere: as an entity or a column, in a select_from, a join, a subquery or
    an EXISTS. Each is a mapped class's table.
    """
    elements = visitors.iterate(statement) if isinstance(statement, ClauseElement) else ()
    names = {element.fullname for element in elements if isinstance(element, Table) and OWNER_COLUMN in element.c}
    return [
        mapper for mapper in default_registry.mappers if isinstance(mapper.local_table, Table) and mapper.local_table.fullname in names
    ]


def guard_session(session: Session) -> None:
    """
    The session's owner is session.info["owner_id"], which owner_session sets as it opens the session. Every ORM
    SELECT, UPDATE and DELETE that names an owned table gets `owner_id = :owner` added for each such table, wherever
    the statement names it, so another owner's rows are neither read nor changed; an UPDATE may not set owner_id, and
    an INSERT statement or a flushed row must name the owner. Without an owner (get_session), any statement or flush
    that names an owned table raises before it reaches the database.
    """
    event.listen(session, "do_orm_execute", scope_statement)
    event.listen(session, "before_flush", check_flush)


def scope_statement(state: ORMExecuteState) -> None:
    owned = owned_mappers(state.statement)
    owner_id = state.session.info.get(OWNER_COLUMN)

    if not owned:
        return

    if owner_id is None:
        raise OwnedTableOutsideOwnerSession(
            f"{', '.join(mapper.persist_selectable.description for mapper in owned)} outside an owner session"
        )

    if not state.is_orm_statement:
        raise OwnedTableOutsideOwnerSession("A Core statement names an owned table; build it on the mapped class")

    if state.is_insert:
        check_inserted_rows(state.parameters, owner_id)
        return

    if state.is_update:
        check_updated_owner(state.statement, state.parameters, owner_id)

    state.statement = state.statement.options(
        *(
            with_loader_criteria(mapper.class_, getattr(mapper.class_, OWNER_COLUMN) == owner_id, include_aliases=True)
            for mapper in owned
        )
    )


def check_updated_owner(statement: Executable, parameters: Any, owner_id: str) -> None:
    """
    An UPDATE never moves rows to another owner: its SET clause may not name owner_id, and a bulk UPDATE's rows, which
    name their primary key, owner_id included, must name the owner. SQLAlchemy keeps an UPDATE's SET clause in _values.
    """
    values = {getattr(column, "key", column) for column in (getattr(statement, "_values", None) or {})}
    ordered = {getattr(column, "key", column) for column, _ in (getattr(statement, "_ordered_values", None) or [])}
    rows = parameters if isinstance(parameters, list) else []

    if OWNER_COLUMN in values | ordered or any(row.get(OWNER_COLUMN, owner_id) != owner_id for row in rows):
        raise OwnedTableOutsideOwnerSession(f"An UPDATE may not move rows of {owner_id} to another owner")


def check_inserted_rows(parameters: Any, owner_id: str) -> None:
    """An ORM INSERT passes its rows as parameters; insert().values(...) hides them from the guard and is refused."""
    rows = parameters if isinstance(parameters, list) else [parameters] if parameters else []

    if not rows:
        raise OwnedTableOutsideOwnerSession("An INSERT on an owned table must pass its rows as execute() parameters")

    if any(row.get(OWNER_COLUMN) != owner_id for row in rows):
        raise OwnedTableOutsideOwnerSession(f"An inserted row names another owner than {owner_id}")


def check_flush(session: Session, context: object, instances: Iterable[object] | None) -> None:
    owner_id = session.info.get(OWNER_COLUMN)

    for row in (*session.new, *session.dirty, *session.deleted):
        mapper: Mapper[Any] = row.__mapper__

        if owns_rows(mapper) and (owner_id is None or getattr(row, OWNER_COLUMN) != owner_id):
            raise OwnedTableOutsideOwnerSession(
                f"A {mapper.persist_selectable.description} row of another owner in the session of {owner_id}"
            )
