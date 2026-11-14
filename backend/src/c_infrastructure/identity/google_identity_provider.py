import hashlib
import json
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from typing import override
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr

from a_domain.model.system.user import GoogleConfirmation, SignInFlow
from a_domain.ports.system.identity_provider import IIdentityProvider
from a_domain.rules.system.google_sign_in import IdTokenClaims
from a_domain.types.errors import IdentityProviderError


class GoogleIdentityProvider(IIdentityProvider):
    """
    Google as the OpenID Connect provider, by the authorization code flow with PKCE (S256), a state and a nonce. The
    ID token comes straight from Google's token endpoint over TLS, on a request that carries the client secret, so its
    signature is not checked again: OpenID Connect Core 3.1.3.7 allows TLS server validation in its place for this
    flow, and the settings refuse a token endpoint that is not https. The token never leaves this adapter.

    A flow that confirms a settings save asks for max_age=0 and for the auth_time claim, so the token dates the
    authentication. Of what Google answers, only the status reaches a log or an error.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: SecretStr,
        authorization_endpoint: str,
        token_endpoint: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._authorization_endpoint = authorization_endpoint
        self._token_endpoint = token_endpoint
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @override
    def start(
        self, redirect_uri: str, confirmation: GoogleConfirmation | None, now: datetime, expires_at: datetime
    ) -> tuple[SignInFlow, str]:
        flow = SignInFlow(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            code_verifier=secrets.token_urlsafe(64),
            started_at=now,
            expires_at=expires_at,
            confirmation=confirmation,
        )
        challenge = urlsafe_b64encode(hashlib.sha256(flow.code_verifier.encode()).digest()).decode().rstrip("=")
        query = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email",
            "state": flow.state,
            "nonce": flow.nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }

        if confirmation is not None:
            query |= {"max_age": "0", "claims": json.dumps({"id_token": {"auth_time": {"essential": True}}})}

        return flow, f"{self._authorization_endpoint}?{urlencode(query)}"

    @override
    async def redeem(self, code: SecretStr, flow: SignInFlow, redirect_uri: str) -> IdTokenClaims:
        form = {
            "grant_type": "authorization_code",
            "code": code.get_secret_value(),
            "code_verifier": flow.code_verifier,
            "client_id": self._client_id,
            "client_secret": self._client_secret.get_secret_value(),
            "redirect_uri": redirect_uri,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds, transport=self._transport) as client:
                response = await client.post(self._token_endpoint, data=form)

            response.raise_for_status()
            return read_id_token(response.json()["id_token"])
        except httpx.HTTPStatusError as error:
            raise IdentityProviderError(f"the token endpoint answered {error.response.status_code}.") from None
        except httpx.HTTPError as error:
            raise IdentityProviderError(f"the token endpoint did not answer ({type(error).__name__}).") from None
        except ValueError, LookupError, TypeError:
            raise IdentityProviderError("the token endpoint answered without an ID token.") from None


def read_id_token(id_token: str) -> IdTokenClaims:
    """What an ID token says, unchecked. Raises IdentityProviderError for one that cannot be read."""
    try:
        payload = id_token.split(".")[1]
        token = json.loads(urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        audience, authenticated_at = token["aud"], token.get("auth_time")
        return IdTokenClaims(
            issuer=token["iss"],
            audiences=(audience,) if isinstance(audience, str) else tuple(audience),
            nonce=token.get("nonce", ""),
            email=token["email"],
            email_verified=token.get("email_verified") is True,
            expires_at=datetime.fromtimestamp(token["exp"], UTC),
            authenticated_at=datetime.fromtimestamp(authenticated_at, UTC) if authenticated_at is not None else None,
        )
    except ValueError, LookupError, TypeError, AttributeError, OverflowError, OSError:
        raise IdentityProviderError("the token endpoint answered an ID token the app cannot read.") from None
