from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class RegistrationRule:
    """
    Whether anyone may register as a user now. Only after the first administrator is set up, only while the
    administrator keeps registration open, and never on an installation that trades on a real broker, whose private
    pages only administrators may use.
    """

    registration_open: bool
    real_broker: bool

    def apply(self, user_count: int) -> str | None:
        """Why registration is closed now, or None while it is open."""
        if user_count == 0:
            return "The administrator is not set up yet."

        if not self.registration_open:
            return "Registration is closed."

        if self.real_broker:
            return "This installation trades on a real broker: only its administrators may use it."

        return None


@dataclass(frozen=True)
class SignInOffer:
    """What the sign-in screen offers: the first-time setup while no user exists, and registration while the rule allows it."""

    needs_first_administrator: bool
    registration_open: bool
