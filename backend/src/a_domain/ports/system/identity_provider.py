from datetime import datetime
from typing import Protocol

from pydantic import SecretStr

from a_domain.model.system.user import SignInFlow
from a_domain.rules.system.google_sign_in import IdTokenClaims


class IIdentityProvider(Protocol):
    """An OpenID Connect provider the app is a confidential client of, by the authorization code flow with PKCE."""

    def start(self, redirect_uri: str, confirmation: str | None, now: datetime, expires_at: datetime) -> tuple[SignInFlow, str]:
        """
        A new flow with fresh random values, started `now` and good until `expires_at`, and the provider's address the
        browser goes to for it. A flow with a `confirmation` asks the provider to authenticate the person again and to
        date it in the ID token.
        """
        ...

    async def redeem(self, code: SecretStr, flow: SignInFlow, redirect_uri: str) -> IdTokenClaims:
        """
        Exchanges the code the provider sent the browser back with at its token endpoint, and reads the ID token of
        the answer. The token is unchecked: IdTokenRule decides. Raises IdentityProviderError, whose message carries
        no token, code or secret.
        """
        ...

    def read_id_token(self, id_token: str) -> IdTokenClaims:
        """What an ID token says, unchecked. Raises IdentityProviderError for one that cannot be read."""
        ...
