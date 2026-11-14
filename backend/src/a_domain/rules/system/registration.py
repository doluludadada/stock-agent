from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class RegistrationRule:
    """
    Whether anyone may register as a user now: only after the first administrator is set up, and only while the
    administrator keeps registration open. A user orders on their own mock account only.
    """

    registration_open: bool

    def apply(self, user_count: int) -> str | None:
        """Why registration is closed now, or None while it is open."""
        if user_count == 0:
            return "The administrator is not set up yet."

        if not self.registration_open:
            return "Registration is closed."

        return None


@dataclass(frozen=True)
class SignInOffer:
    """
    What the sign-in screen offers: the first-time setup while no user exists, registration while the rule allows it,
    and sign-in with Google while the installation has its client and its public origin.
    """

    needs_first_administrator: bool
    registration_open: bool
    google_sign_in: bool = False
