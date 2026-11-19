from dataclasses import dataclass

from a_domain.model.system.user import SignInFlow, User, UserSession
from a_domain.types.enums import AiProvider


@dataclass(frozen=True)
class SignedIn:
    """A Web sign-in, as Pipeline.sign_in_with_session and Pipeline.sign_in_with_google return it."""

    user: User
    """The user who signed in."""

    session: UserSession
    """SessionStart: the session for the browser's cookie."""


@dataclass(frozen=True)
class GoogleRedirect:
    """The start of a sign-in with Google, as GoogleSignInStart answers it for Pipeline.start_google_sign_in."""

    flow: SignInFlow
    """The flow for the browser's cookie."""

    address: str
    """Google's address for the flow, where the browser goes next."""


@dataclass(frozen=True)
class AiModels:
    """What My settings shows of the AI model, as AiModelLookup answers it."""

    models: dict[AiProvider, str]
    """Each AI model the site offers with its model id, the site's default first."""

    site_default: AiProvider
    """The site's default model."""

    in_use: AiProvider
    """The model the user's runs use: their choice while the site offers it, else the default."""
