from collections.abc import Sequence
from typing import override

from sqlalchemy.dialects.postgresql import insert

from a_domain.model.market.company_profile import CompanyProfile
from a_domain.ports.market.company_profile_repository import ICompanyProfileRepository
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.company_profile_dto import CompanyProfileDTO
from c_infrastructure.database.upsert import replacing


class SqlCompanyProfileRepository(ICompanyProfileRepository):
    """
    The company_profiles table, shared by every user. The exchanges' profiles are saved in one statement that adds a
    new company and gives a held one the exchange's columns alone, so a run of the archive never clears what MOPS and
    the annual report gave.
    """

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def find(self, stock_id: str) -> CompanyProfile | None:
        async with self._db.get_session() as session:
            row = await session.get(CompanyProfileDTO, stock_id)

        return row.to_domain() if row is not None else None

    @override
    async def save_listings(self, profiles: Sequence[CompanyProfile]) -> None:
        rows = list({profile.stock_id: CompanyProfileDTO.values_of(profile) for profile in profiles}.values())

        if not rows:
            return

        statement = insert(CompanyProfileDTO)
        served = {name: statement.excluded[name] for name in CompanyProfileDTO.LISTING_COLUMNS}

        async with self._db.get_session() as session:
            await session.execute(statement.on_conflict_do_update(index_elements=["stock_id"], set_=served), rows)
            await session.commit()

    @override
    async def save(self, profile: CompanyProfile) -> None:
        async with self._db.get_session() as session:
            await session.execute(replacing(CompanyProfileDTO), [CompanyProfileDTO.values_of(profile)])
            await session.commit()
