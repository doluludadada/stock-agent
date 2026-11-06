import asyncio
import secrets
from datetime import datetime
from typing import override

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.exceptions import InvalidTag
from pydantic import SecretStr
from sqlalchemy import delete, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from a_domain.model.system.user import User, UserSession
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import AiProvider, Role, UserStatus
from a_domain.types.errors import AlreadySetUpError, LastAdministratorError, UserExistsError
from a_domain.types.ids import SessionToken, UserId
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.user_dto import UserDTO, UserKeys, UserSessionDTO


class AccountsKeyError(RuntimeError):
    """
    Startup refuses: the accounts key does not open the saved users. Only startup raises it, and the CLI and the Web API
    print it alone, like OutdatedDatabaseError, so it belongs to this adapter.
    """


class SqlUserStore(IUserStore):
    """
    The users and user_sessions tables. Passwords are hashed with argon2id at OWASP's parameters (2 passes, 19 MiB, 1
    lane) in a worker thread, at most two at a time, so a flood of sign-ins can neither stall a running workflow nor
    claim the machine's memory. An unknown sign-in name is checked against a dummy hash, so it costs a wrong password's
    time. The username and the email are sealed and indexed with the keys UserKeys derives from the accounts key.
    """

    def __init__(self, db: DatabaseConnector, key: SecretStr, logger: ILoggingProvider) -> None:
        self._db = db
        self._keys = UserKeys(key)
        self._logger = logger
        self._hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)
        self._hashing = asyncio.Semaphore(2)
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    @override
    async def check_key(self) -> None:
        async with self._db.get_session() as session:
            row = (await session.execute(select(UserDTO).limit(1))).scalars().first()

        if row is None:
            return

        try:
            row.to_domain(self._keys)
        except InvalidTag:
            raise AccountsKeyError(
                "The accounts key does not open the saved users: it is not the key they were saved with. Restore the original "
                "secrets/accounts.key, or the ACCOUNTS_KEY variable when you set one, from the backup you made with the "
                "database. A new key does not help: every account stays locked without the old one."
            ) from None

    @override
    async def user_count(self) -> int:
        async with self._db.get_session() as session:
            return (await session.execute(select(func.count()).select_from(UserDTO))).scalar_one()

    @override
    async def create(self, user: User, password: SecretStr) -> None:
        async with self._hashing:
            password_hash = await asyncio.to_thread(self._hasher.hash, password.get_secret_value())

        row = UserDTO.from_domain(user, password_hash, self._keys)
        taken = select(UserDTO.username_index).where(
            or_(col(UserDTO.username_index) == row.username_index, col(UserDTO.email_index) == row.email_index)
        )

        async with self._db.get_session() as session:
            session.add(row)

            try:
                await session.commit()
                return
            except IntegrityError:
                await session.rollback()

            if (found := (await session.execute(taken)).first()) is not None:
                raise UserExistsError("username" if found.username_index == row.username_index else "email")

            raise AlreadySetUpError(f"User {user.user_id} exists.")

    @override
    async def verify_password(self, identifier: str, password: SecretStr) -> User | None:
        """The row is read and its connection returned before the hash waits its turn, so queued sign-ins hold no connection."""
        async with self._db.get_session() as session:
            row = (await session.execute(select(UserDTO).where(UserDTO.named(identifier, self._keys)))).scalars().first()

        async with self._hashing:
            try:
                await asyncio.to_thread(
                    self._hasher.verify, row.password_hash if row else self._dummy_hash, password.get_secret_value()
                )
            except VerificationError, InvalidHashError:
                return None

            if row is None or row.status != UserStatus.ACTIVE:
                return None

            if self._hasher.check_needs_rehash(row.password_hash):
                rehashed = await asyncio.to_thread(self._hasher.hash, password.get_secret_value())

                async with self._db.get_session() as session:
                    await session.execute(update(UserDTO).where(col(UserDTO.user_id) == row.user_id).values(password_hash=rehashed))
                    await session.commit()

        return row.to_domain(self._keys)

    @override
    async def find_by_name(self, identifier: str) -> User | None:
        async with self._db.get_session() as session:
            row = (await session.execute(select(UserDTO).where(UserDTO.named(identifier, self._keys)))).scalars().first()

        return row.to_domain(self._keys) if row is not None else None

    @override
    async def open_session(self, user_id: UserId, now: datetime, expires_at: datetime) -> UserSession:
        token = SessionToken(secrets.token_urlsafe(32))

        async with self._db.get_session() as session:
            await session.execute(delete(UserSessionDTO).where(col(UserSessionDTO.expires_at) <= now))
            session.add(
                UserSessionDTO(token_digest=UserSessionDTO.digest(token), user_id=user_id, created_at=now, expires_at=expires_at)
            )
            await session.commit()

        return UserSession(token=token, user_id=user_id, created_at=now, expires_at=expires_at)

    @override
    async def session_user(self, token: SessionToken, now: datetime) -> User | None:
        statement = (
            select(UserDTO)
            .join(UserSessionDTO, col(UserSessionDTO.user_id) == col(UserDTO.user_id))
            .where(col(UserSessionDTO.token_digest) == UserSessionDTO.digest(token))
            .where(col(UserSessionDTO.expires_at) > now, col(UserDTO.status) == UserStatus.ACTIVE)
        )

        async with self._db.get_session() as session:
            row = (await session.execute(statement)).scalars().first()

        return row.to_domain(self._keys) if row is not None else None

    @override
    async def close_session(self, token: SessionToken) -> None:
        async with self._db.get_session() as session:
            await session.execute(delete(UserSessionDTO).where(col(UserSessionDTO.token_digest) == UserSessionDTO.digest(token)))
            await session.commit()

    @override
    async def users(self) -> list[User]:
        async with self._db.get_session() as session:
            rows = (await session.execute(select(UserDTO).order_by(col(UserDTO.created_at)))).scalars().all()

        return [row.to_domain(self._keys) for row in rows]

    @override
    async def find(self, user_id: UserId) -> User | None:
        async with self._db.get_session() as session:
            row = await session.get(UserDTO, user_id)

        return row.to_domain(self._keys) if row is not None else None

    @override
    async def save(self, user: User, now: datetime, password: SecretStr | None = None) -> None:
        password_hash = None

        if password is not None:
            async with self._hashing:
                password_hash = await asyncio.to_thread(self._hasher.hash, password.get_secret_value())

        administrators = select(UserDTO.user_id).where(
            col(UserDTO.role) == Role.ADMINISTRATOR, col(UserDTO.status) == UserStatus.ACTIVE
        )

        async with self._db.get_session() as session:
            await session.execute(administrators.with_for_update())
            row = await session.get_one(UserDTO, user.user_id)
            row.role, row.status, row.updated_at = user.role, user.status, now

            if password_hash is not None:
                row.password_hash = password_hash

            if user.status != UserStatus.ACTIVE or password_hash is not None:
                await session.execute(delete(UserSessionDTO).where(col(UserSessionDTO.user_id) == user.user_id))

            await session.flush()

            if not (await session.execute(administrators)).first():
                raise LastAdministratorError("At least one active administrator must remain. Nothing was saved.")

            await session.commit()

    @override
    async def save_ai_model(self, user_id: UserId, ai_model: AiProvider | None, now: datetime) -> None:
        async with self._db.get_session() as session:
            await session.execute(update(UserDTO).where(col(UserDTO.user_id) == user_id).values(ai_model=ai_model, updated_at=now))
            await session.commit()
