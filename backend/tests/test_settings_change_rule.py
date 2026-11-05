"""Which settings a proposed file changes, and whether the new settings keep the editor open to an administrator."""

from dataclasses import replace

from support.harness import ADMINISTRATOR, MEMBER

from a_domain.rules.system.registration import SignInOffer
from a_domain.rules.system.settings_change import EditorAccessRule, SettingsChangeRule
from a_domain.types.enums import UserStatus

RULE = SettingsChangeRule()


def test_the_change_lists_every_changed_removed_and_added_path() -> None:
    changed = RULE.apply(
        {"ai.temperature": 0.7, "trading.order_mode": "mock_only", "gone": 1},
        {"ai.temperature": 0.2, "trading.order_mode": "mock_only", "new": [1]},
    )

    assert changed == ("ai.temperature", "gone", "new")


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


def test_a_proposal_that_does_not_parse_names_no_setting_and_one_over_an_unparsed_file_names_all_it_sets() -> None:
    assert (RULE.apply({"ai.temperature": 0.7}, None), RULE.apply(None, {"ai.temperature": 0.2})) == ((), ("ai.temperature",))
