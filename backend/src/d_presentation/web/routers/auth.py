from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import SecretStr

from a_domain.model.system.user import User
from a_domain.types.enums import GoogleRefusal
from a_domain.types.errors import AlreadySetUpError, GoogleSignInRefused, SignInThrottled, UserExistsError
from a_domain.types.ids import SessionToken
from d_presentation.web.schemas import (
    AiModelRequest,
    AiModelResponse,
    AuthStatusResponse,
    ConfirmationId,
    RegistrationRequest,
    SetupRequest,
    SignInRequest,
)
from d_presentation.web.session import (
    APP_HOME,
    APP_SETTINGS,
    APP_SIGN_IN,
    CONFIRMED,
    THROTTLED,
    CurrentUser,
    PrivateAccess,
    RuntimeDependency,
    SessionCookie,
    SignedOutPipeline,
    UserPipeline,
    back_to_app,
    check_setup_code,
    clear_session_cookie,
    client_of,
    feature_visibilities,
    flow_of,
    set_flow_cookie,
    set_session_cookie,
)

router = APIRouter(prefix="/auth", tags=["Sign-in"])
"""
Public, but for /me and its AI model: the first-time setup, registration, sign-in, sign-in with Google and sign-out.
Every write needs X-Requested-With. The two Google endpoints are GETs the browser navigates to, and answer redirects.
"""


@router.get("/status")
async def get_sign_in_status(pipeline: SignedOutPipeline, runtime: RuntimeDependency) -> AuthStatusResponse:
    """
    What the web app shows first: the first-time setup while no user exists, then sign-in, with registration while it is
    open; and whom the site shows each feature to, which the app reads with the user's permissions to show or hide a page.
    """
    options = await pipeline.load_sign_in_options()

    return AuthStatusResponse(
        needs_first_administrator=options.needs_first_administrator,
        registration_open=options.registration_open,
        google_sign_in=options.google_sign_in,
        features=feature_visibilities(runtime),
    )


@router.post("/setup", status_code=status.HTTP_201_CREATED)
async def set_up(body: SetupRequest, request: Request, pipeline: SignedOutPipeline) -> User:
    """
    First use only: the administrator, who takes over the data of the single-user version. It needs the setup code the
    server printed on its console at start (403 otherwise), so the first visitor of an exposed server cannot claim it.
    409 once a user exists. The app then signs in like any user.
    """
    check_setup_code(request, body.setup_code)

    return await pipeline.set_up_first_administrator(body.username, body.email, body.password)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegistrationRequest, request: Request, pipeline: SignedOutPipeline) -> User:
    """A new user with the role user: 403 while registration is closed, 409 for a taken username or email, 429 past the limit."""
    return await pipeline.register(body.username, body.email, body.password, client_of(request))


@router.post("/sign-in")
async def sign_in(body: SignInRequest, request: Request, response: Response, pipeline: SignedOutPipeline) -> User:
    """Sets the session cookie. 401 for a wrong name or password, one message for both; 429 past the attempt limits."""
    user, session = await pipeline.sign_in_with_session(body.identifier, body.password, client_of(request))
    set_session_cookie(request, response, session)

    return user


@router.get("/google/start", status_code=status.HTTP_303_SEE_OTHER, response_class=RedirectResponse)
async def start_google_sign_in(
    request: Request, pipeline: SignedOutPipeline, confirmation: ConfirmationId | None = None
) -> RedirectResponse:
    """
    The browser's way to Google, as a navigation, never a fetch: it sets the short-lived flow cookie and redirects to
    Google's sign-in. With `confirmation`, the id the web app made for one settings save, Google authenticates the
    administrator again for that save. Where the site offers no sign-in with Google, or past the limit per address,
    it redirects back to the app with ?google= and the reason.
    """
    try:
        flow, address = await pipeline.start_google_sign_in(confirmation, client_of(request))
    except GoogleSignInRefused as error:
        return back_to_app(request, APP_SETTINGS if confirmation else APP_SIGN_IN, error.refusal)
    except SignInThrottled:
        return back_to_app(request, APP_SETTINGS if confirmation else APP_SIGN_IN, THROTTLED)

    response = RedirectResponse(address, status_code=status.HTTP_303_SEE_OTHER)
    set_flow_cookie(request, response, flow)

    return response


@router.get("/google/callback", status_code=status.HTTP_303_SEE_OTHER, response_class=RedirectResponse)
async def return_from_google(
    request: Request,
    pipeline: SignedOutPipeline,
    state: Annotated[str | None, Query(max_length=256)] = None,
    code: Annotated[SecretStr | None, Query(max_length=2048)] = None,
) -> RedirectResponse:
    """
    Where Google sends the browser back: <accounts.public_origin>/v1/auth/google/callback, the one redirect URI of the
    OAuth client. A sign-in sets the session cookie and redirects to the app. A settings confirmation grants the save
    it was started for and redirects to the settings form with ?google=confirmed. A refusal redirects to the app with
    ?google= and the reason; nothing is created and no session starts. Either way the flow cookie is cleared.
    """
    flow, client = flow_of(request), client_of(request)
    confirmation = flow.confirmation if flow is not None else None
    page = APP_SETTINGS if confirmation else APP_SIGN_IN

    try:
        if flow is not None and confirmation is not None:
            await pipeline.confirm_settings_with_google(flow, confirmation, state, code, client)
            return back_to_app(request, APP_SETTINGS, CONFIRMED)

        _, session = await pipeline.sign_in_with_google(flow, state, code, client)
    except GoogleSignInRefused as error:
        return back_to_app(request, page, error.refusal)
    except SignInThrottled:
        return back_to_app(request, page, THROTTLED)
    except UserExistsError, AlreadySetUpError:
        return back_to_app(request, page, GoogleRefusal.PROVIDER_FAILED)

    response = back_to_app(request, APP_HOME)
    set_session_cookie(request, response, session)

    return response


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(request: Request, response: Response, pipeline: SignedOutPipeline, token: SessionCookie) -> None:
    """Ends this browser's session and clears its cookie. Signing out twice is fine."""
    if token:
        await pipeline.end_session(SessionToken(token))

    clear_session_cookie(request, response)


@router.get("/me")
async def get_me(user: CurrentUser) -> User:
    """The signed-in user with their permissions, which the app reads to show the administration pages. 401 when signed out."""
    return user


@router.get("/me/ai-model", dependencies=[PrivateAccess])
async def get_ai_model(user: CurrentUser, pipeline: UserPipeline) -> AiModelResponse:
    """My settings: the AI models the site offers, its default, and the one the user's runs use. 401 when signed out."""
    models, site_default, in_use = pipeline.load_ai_models(user)
    return AiModelResponse(models=models, site_default=site_default, in_use=in_use)


@router.put(
    "/me/ai-model",
    dependencies=[PrivateAccess],
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "The site does not offer that model; nothing saved."}},
)
async def choose_ai_model(body: AiModelRequest, user: CurrentUser, pipeline: UserPipeline) -> AiModelResponse:
    """
    Chooses the AI model of the user's next runs, or null for the site's default. A run already running keeps its model.
    A model the site stopped offering later leaves the choice saved, and the runs use the site's default meanwhile.
    """
    models, site_default, in_use = await pipeline.choose_ai_model(user, body.ai_model)
    return AiModelResponse(models=models, site_default=site_default, in_use=in_use)
