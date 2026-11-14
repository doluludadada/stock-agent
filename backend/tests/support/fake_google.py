"""
A stand-in for Google's OpenID Connect endpoints: the authorization endpoint, as a person choosing an account, and the
token endpoint, which checks what Google checks (the client and its secret, the redirect URI, a code used once, the
PKCE verifier) and answers an unsigned ID token. The tests reach its token endpoint through httpx's ASGI transport.
Run as a script it serves both over http on localhost, with a page to choose who signs in, for a browser:

    uv run python tests/support/fake_google.py <port> <client id> <client secret>
"""

import hashlib
import json
import secrets
import sys
from base64 import urlsafe_b64encode
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse


@dataclass
class Grant:
    """What an approved authorization request promised: the token endpoint redeems it once."""

    client_id: str
    redirect_uri: str
    code_challenge: str
    nonce: str
    email: str
    asked_auth_time: bool


def encoded(part: dict) -> str:
    return urlsafe_b64encode(json.dumps(part).encode()).decode().rstrip("=")


class FakeGoogle:
    """
    Google for one client. A test changes what the next ID token says through the attributes: who it is for
    (`audience`), who issued it, whether the email is verified, how long it lives, when the person authenticated, and
    a nonce to answer in place of the flow's.
    """

    def __init__(
        self, client_id: str, client_secret: str, issuer: str, now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self.client_id, self.client_secret, self.issuer, self.now = client_id, client_secret, issuer, now
        self.audience: str | list[str] = client_id
        self.email_verified = True
        self.lifetime = timedelta(hours=1)
        self.authenticated_ago: timedelta | None = timedelta(0)
        """How long before the token the person authenticated; None leaves auth_time out even when the app asked for it."""
        self.nonce: str | None = None
        self.down = False
        """The token endpoint answers 503."""
        self.grants: dict[str, Grant] = {}
        self.token_requests = 0
        self.app = FastAPI()
        self.app.get("/authorize", response_model=None)(self.choose_account)
        self.app.post("/token")(self.token)

    def approve(self, authorization_url: str, email: str) -> str:
        """The person signs in as `email` at the address the app sent the browser to: where Google sends the browser back."""
        query = {name: values[0] for name, values in parse_qs(urlsplit(authorization_url).query).items()}
        assert query["response_type"] == "code" and query["code_challenge_method"] == "S256", query
        assert "openid" in query["scope"].split() and "email" in query["scope"].split(), query
        assert query["client_id"] == self.client_id, query
        code = secrets.token_urlsafe(24)
        asked = "auth_time" in json.loads(query.get("claims", "{}")).get("id_token", {})
        self.grants[code] = Grant(query["client_id"], query["redirect_uri"], query["code_challenge"], query["nonce"], email, asked)
        return f"{query['redirect_uri']}?{urlencode({'state': query['state'], 'code': code})}"

    def id_token(self, grant: Grant) -> str:
        now = self.now()
        claims: dict[str, object] = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": hashlib.sha256(grant.email.encode()).hexdigest()[:21],
            "email": grant.email,
            "email_verified": self.email_verified,
            "nonce": self.nonce or grant.nonce,
            "iat": int(now.timestamp()),
            "exp": int((now + self.lifetime).timestamp()),
        }

        if grant.asked_auth_time and self.authenticated_ago is not None:
            claims["auth_time"] = int((now - self.authenticated_ago).timestamp())

        return f"{encoded({'alg': 'none'})}.{encoded(claims)}.unsigned"

    async def token(self, request: Request) -> JSONResponse:
        form = {name: values[0] for name, values in parse_qs((await request.body()).decode()).items()}
        client_id, client_secret, code = form.get("client_id"), form.get("client_secret"), form.get("code", "")
        grant_type, redirect_uri, code_verifier = form.get("grant_type"), form.get("redirect_uri"), form.get("code_verifier", "")
        self.token_requests += 1

        if self.down:
            return JSONResponse({"error": "temporarily_unavailable"}, status_code=503)

        if (client_id, client_secret) != (self.client_id, self.client_secret):
            return JSONResponse({"error": "invalid_client"}, status_code=401)

        grant = self.grants.pop(code, None)
        challenge = urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")

        if (
            grant is None
            or grant_type != "authorization_code"
            or (grant.redirect_uri, grant.code_challenge) != (redirect_uri, challenge)
        ):
            return JSONResponse({"error": "invalid_grant", "error_description": f"Bad Request for code {code}"}, status_code=400)

        return JSONResponse({"access_token": secrets.token_urlsafe(16), "token_type": "Bearer", "id_token": self.id_token(grant)})

    async def choose_account(
        self, request: Request, email: str | None = None, authenticated_minutes_ago: int = 0
    ) -> HTMLResponse | RedirectResponse:
        """The script's sign-in page: a form that names who signs in and how long ago they authenticated."""
        if email is not None:
            self.authenticated_ago = timedelta(minutes=authenticated_minutes_ago)
            asked = {name: value for name, value in request.query_params.items() if name not in ("email", "authenticated_minutes_ago")}
            return RedirectResponse(self.approve(f"/authorize?{urlencode(asked)}", email), status_code=303)

        hidden = "".join(
            f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">' for name, value in request.query_params.items()
        )
        return HTMLResponse(
            "<!doctype html><title>Fake Google</title><h1>Fake Google</h1><form method='get' action='/authorize'>"
            f"{hidden}<label>Email <input name='email' type='email' required></label> "
            "<label>Authenticated minutes ago <input name='authenticated_minutes_ago' type='number' value='0'></label> "
            "<button type='submit'>Sign in</button></form>"
        )


if __name__ == "__main__":
    import uvicorn

    port = int(sys.argv[1])
    uvicorn.run(FakeGoogle(sys.argv[2], sys.argv[3], f"http://localhost:{port}").app, host="127.0.0.1", port=port, log_level="warning")
