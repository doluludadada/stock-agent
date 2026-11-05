import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Self

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import SecretStr
from sqlalchemy import ColumnElement, LargeBinary, or_
from sqlmodel import Field, SQLModel, col

from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import Role, UserStatus
from a_domain.types.ids import SessionToken, UserId
from a_domain.types.values import comparable_name
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import accounts_key_bytes, validate_accounts_environment, validate_accounts_key
from c_infrastructure.database.utc_datetime import UtcDateTime

LEGACY_OWNER_ID = UserId("local")
"""
The first administrator's user id, and the owner of every row of a single-owner installation: version 2 stored its
technical settings under it (then the setting technical.owner_id), the upgrade to version 3 gives it every other row of
version 2, and the first-time setup gives it to the first administrator, so that data becomes theirs.
"""


def load_accounts_key(config: AppConfig, logger: ILoggingProvider) -> SecretStr:
    """
    The accounts key, before the database is opened: ACCOUNTS_KEY when the environment or .env sets it, for Docker or
    production, else secrets/accounts.key under the project root, created on the first start. Raises
    AccountsSetupError naming the one it read when that is not 32 base64url bytes. The key itself is never logged.
    """
    if (variable := validate_accounts_environment(config)) is not None:
        return variable

    path = config.project_root / "secrets" / "accounts.key"

    if not path.exists() and create_accounts_key(path):
        logger.warning(f"Created the accounts key {path}. Back it up with the database: without it no one can sign in again.")

    return validate_accounts_key(SecretStr(path.read_text(encoding="utf-8").strip()), str(path))


def create_accounts_key(path: Path) -> bool:
    """
    Writes 32 random bytes, base64url, to `path` with mode 600, its folder created with mode 700 when missing. The key
    goes into a private temporary file that is then linked to `path`, and the link fails when `path` exists, so the
    file appears whole or not at all: of two processes starting at once, the one that gets False reads the other's key.
    """
    path.parent.mkdir(mode=0o700, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as file:
            file.write(f"{key}\n")
            file.flush()
            os.fsync(file.fileno())

        os.link(temporary, path)
        return True
    except FileExistsError:
        return False
    finally:
        temporary.unlink(missing_ok=True)


class UserKeys:
    """
    The three keys HKDF-SHA256 derives from the accounts key, one per purpose, so the encryption key never doubles as an
    index key and an equal username and email never index alike.

    seal: AES-256-GCM, a fresh 96-bit nonce per value stored in front of the ciphertext, and associated data
    b"users.<column>:" + user id, so a ciphertext copied onto another row or column does not open.
    index: HMAC-SHA256 of the name as sign-in compares it (comparable_name), so "Alice" and "alice" index alike and the
    unique constraint on the index is the uniqueness rule.
    """

    def __init__(self, secret: SecretStr) -> None:
        master = accounts_key_bytes(secret)
        self.seal_key, self.username_key, self.email_key = (
            HKDF(algorithm=SHA256(), length=32, salt=None, info=f"stock-agent users {purpose} v1".encode()).derive(master)
            for purpose in ("field encryption", "username index", "email index")
        )

    def seal(self, column: str, user_id: str, text: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(self.seal_key).encrypt(nonce, text.encode(), f"users.{column}:{user_id}".encode())

    def open(self, column: str, user_id: str, sealed: bytes) -> str:
        """Raises cryptography's InvalidTag under another key, for a moved ciphertext and for a changed byte."""
        return AESGCM(self.seal_key).decrypt(sealed[:12], sealed[12:], f"users.{column}:{user_id}".encode()).decode()

    def username_index(self, text: str) -> bytes:
        return hmac.new(self.username_key, comparable_name(text).encode(), hashlib.sha256).digest()

    def email_index(self, text: str) -> bytes:
        return hmac.new(self.email_key, comparable_name(text).encode(), hashlib.sha256).digest()


class UserDTO(SQLModel, table=True):
    """One user: the password only as its argon2id hash, the username and email only sealed, each with its index."""

    __tablename__: ClassVar[str] = "users"

    user_id: str = Field(primary_key=True)
    username_sealed: bytes = Field(sa_type=LargeBinary)
    username_index: bytes = Field(sa_type=LargeBinary, unique=True)
    email_sealed: bytes = Field(sa_type=LargeBinary)
    email_index: bytes = Field(sa_type=LargeBinary, unique=True)
    password_hash: str
    """argon2id in its encoded form: the parameters, the salt and the hash together."""
    role: Role
    status: UserStatus
    created_at: datetime = Field(sa_type=UtcDateTime)
    updated_at: datetime = Field(sa_type=UtcDateTime)

    @classmethod
    def from_domain(cls, user: User, password_hash: str, keys: UserKeys) -> Self:
        return cls(
            user_id=user.user_id,
            username_sealed=keys.seal("username", user.user_id, user.username),
            username_index=keys.username_index(user.username),
            email_sealed=keys.seal("email", user.user_id, user.email),
            email_index=keys.email_index(user.email),
            password_hash=password_hash,
            role=user.role,
            status=user.status,
            created_at=user.created_at,
            updated_at=user.created_at,
        )

    @classmethod
    def named(cls, identifier: str, keys: UserKeys) -> ColumnElement[bool]:
        """The user whose username or email, as sign-in compares names, is `identifier`."""
        return or_(col(cls.username_index) == keys.username_index(identifier), col(cls.email_index) == keys.email_index(identifier))

    def to_domain(self, keys: UserKeys) -> User:
        return User(
            user_id=UserId(self.user_id),
            username=keys.open("username", self.user_id, self.username_sealed),
            email=keys.open("email", self.user_id, self.email_sealed),
            role=self.role,
            status=self.status,
            created_at=self.created_at,
        )


class UserSessionDTO(SQLModel, table=True):
    """One browser's sign-in. Only the SHA-256 of its 256-bit token is stored, so a copy of this table opens no session."""

    __tablename__: ClassVar[str] = "user_sessions"

    token_digest: bytes = Field(sa_type=LargeBinary, primary_key=True)
    user_id: str = Field(foreign_key="users.user_id", index=True)
    created_at: datetime = Field(sa_type=UtcDateTime)
    expires_at: datetime = Field(sa_type=UtcDateTime, index=True)

    @classmethod
    def digest(cls, token: SessionToken) -> bytes:
        return hashlib.sha256(token.encode()).digest()
