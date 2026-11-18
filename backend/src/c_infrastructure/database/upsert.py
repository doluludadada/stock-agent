from sqlalchemy.dialects.postgresql import Insert, insert
from sqlmodel import SQLModel


def replacing(table: type[SQLModel]) -> Insert:
    """The upsert of rows of `table`: a row the table already holds keeps its key and takes every other column."""
    statement = insert(table)
    keys = [column.name for column in statement.table.primary_key]
    replaced = {column.name: statement.excluded[column.name] for column in statement.table.columns if column.name not in keys}
    return statement.on_conflict_do_update(index_elements=keys, set_=replaced)
