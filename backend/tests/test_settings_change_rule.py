"""Whether new settings keep the editor open to an administrator, and which SinoPac server their login may be on."""

from dataclasses import replace

from support.harness import ADMINISTRATOR, MEMBER

from a_domain.rules.system.registration import SignInOffer
from a_domain.rules.system.settings_change import EditorAccessRule, ServerSwitchRefusal, ServerSwitchRule
from a_domain.types.enums import FeatureVisibility, ServerSwitchRefusalReason, ShioajiServer, UserStatus

FIRST_USE, IN_USE = SignInOffer(needs_first_administrator=True, registration_open=False), SignInOffer(False, False)
ACCESS = EditorAccessRule()
SIMULATION, PRODUCTION = ShioajiServer.SIMULATION, ShioajiServer.PRODUCTION
OFF, ADMINISTRATORS = FeatureVisibility.OFF, FeatureVisibility.ADMINISTRATORS
EITHER, DEVELOPER = ServerSwitchRule(servers=frozenset(ShioajiServer)), ServerSwitchRule(servers=frozenset({SIMULATION}))
EVERY_CREDENTIAL = frozenset((*SIMULATION.credentials, *PRODUCTION.credentials))


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


def test_a_switch_of_the_server_needs_ordering_off_and_the_new_servers_variables() -> None:
    assert EITHER.apply(SIMULATION, PRODUCTION, OFF, EVERY_CREDENTIAL, False) is None
    assert EITHER.apply(SIMULATION, PRODUCTION, ADMINISTRATORS, EVERY_CREDENTIAL, False) == ServerSwitchRefusal(
        reason=ServerSwitchRefusalReason.ORDERING_ON, server=PRODUCTION
    )
    assert EITHER.apply(PRODUCTION, SIMULATION, OFF, frozenset(PRODUCTION.credentials), False) == ServerSwitchRefusal(
        reason=ServerSwitchRefusalReason.CREDENTIALS_MISSING, server=SIMULATION, missing=SIMULATION.credentials
    ), "a switch back to simulation names the simulation variables"


def test_a_start_or_a_kept_server_needs_neither_ordering_off_nor_the_variables() -> None:
    for running in (None, PRODUCTION):
        assert EITHER.apply(running, PRODUCTION, ADMINISTRATORS, frozenset(), False) is None


def test_the_environment_and_open_registration_refuse_a_server_even_at_a_start() -> None:
    environment = ServerSwitchRefusal(reason=ServerSwitchRefusalReason.ENVIRONMENT, server=PRODUCTION)
    registration = ServerSwitchRefusal(reason=ServerSwitchRefusalReason.REGISTRATION_OPEN, server=PRODUCTION)

    assert DEVELOPER.apply(None, PRODUCTION, OFF, EVERY_CREDENTIAL, False) == environment
    assert EITHER.apply(None, PRODUCTION, OFF, EVERY_CREDENTIAL, True) == registration
    assert EITHER.apply(PRODUCTION, SIMULATION, OFF, EVERY_CREDENTIAL, True) is None, "simulation holds no real money"
