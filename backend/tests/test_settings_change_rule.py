"""Whether new settings keep the editor open to an administrator."""

from dataclasses import replace

from support.harness import ADMINISTRATOR, MEMBER

from a_domain.rules.system.registration import SignInOffer
from a_domain.rules.system.settings_change import EditorAccessRule
from a_domain.types.enums import UserStatus

FIRST_USE, IN_USE = SignInOffer(needs_first_administrator=True, registration_open=False), SignInOffer(False, False)
ACCESS = EditorAccessRule()


def test_a_save_needs_the_saving_administrator_active_in_the_new_settings_database() -> None:
    deactivated = replace(ADMINISTRATOR, status=UserStatus.DEACTIVATED)

    assert ACCESS.apply(IN_USE, IN_USE, ADMINISTRATOR.user_id, ADMINISTRATOR) is None
    for found in (None, deactivated, MEMBER):
        assert ACCESS.apply(IN_USE, IN_USE, ADMINISTRATOR.user_id, found) == (
            "The new settings' database has no active administrator account of yours to sign in with."
        )


def test_a_reload_needs_an_administrator_unless_the_running_settings_have_none_yet_either() -> None:
    assert (
        ACCESS.apply(FIRST_USE, IN_USE, None, None)
        == "The new settings' database has no administrator: nobody could sign in to the editor."
    )
    assert ACCESS.apply(FIRST_USE, FIRST_USE, None, None) is None
    assert ACCESS.apply(IN_USE, FIRST_USE, None, None) is None
