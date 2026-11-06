from fastapi import APIRouter, Request, Response, status

from a_domain.model.system.user import User
from a_domain.types.ids import SessionToken
from d_presentation.web.schemas import (
    AiModelRequest,
    AiModelResponse,
    AuthStatusResponse,
    RegistrationRequest,
    SetupRequest,
    SignInRequest,
)
from d_presentation.web.session import (
    CurrentUser,
    PrivateAccess,
    SessionCookie,
    SignedOutPipeline,
    UserPipeline,
    check_setup_code,
    clear_session_cookie,
    client_of,
    set_session_cookie,
)

router = APIRouter(prefix="/auth", tags=["Sign-in"])
"""
Public, but for /me and its AI model: the first-time setup, registration, sign-in and sign-out. Every write needs
X-Requested-With.
"""


@router.get("/status")
async def get_sign_in_status(pipeline: SignedOutPipeline) -> AuthStatusResponse:
    """What the web app shows first: the first-time setup while no user exists, then sign-in, with registration while it is open."""
    options = await pipeline.load_sign_in_options()

    return AuthStatusResponse(needs_first_administrator=options.needs_first_administrator, registration_open=options.registration_open)


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
