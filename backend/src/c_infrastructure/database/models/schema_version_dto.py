from typing import ClassVar

from sqlmodel import Field, SQLModel

SCHEMA_VERSION = 1
"""
The table layout and the stored meaning of every column this code writes. Raise it when an existing column changes,
or when a column starts to store its value differently: before version 1, several tables stored Taiwan wall-clock time
in columns that are now read as UTC. A new table needs no raise, because startup creates it.
"""


class SchemaVersionDTO(SQLModel, table=True):
    """The one row startup writes when it creates the tables: the SCHEMA_VERSION it created them with."""

    __tablename__: ClassVar[str] = "schema_version"

    version: int = Field(primary_key=True)
