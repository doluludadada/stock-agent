"""
The settings form's fields, from the settings classes and the files of config/, and its changes written into the files'
text in place: every other line, comment and key as it was, and the value read back as written.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from a_domain.ports.system.settings_files import SettingChange
from a_domain.types.enums import AiProvider, InstructionKey, SettingKind, SettingsFile
from a_domain.types.errors import SettingsEditError
from b_application.config.settings_loader import parsed_document, settings_fields, settings_texts, with_changes

PROJECT = Path(__file__).resolve().parents[2]


def repository_texts() -> dict[SettingsFile, str]:
    return settings_texts(PROJECT)


def edited(texts: dict[SettingsFile, str], *changes: tuple[str, Any]) -> dict[SettingsFile, str]:
    """Each settings file's text after the changes, the files they leave alone as they were."""
    edits = with_changes(texts, [SettingChange(path=path, value=value) for path, value in changes])
    return {**texts, **{edit.file: edit.text for edit in edits}}


def values(texts: dict[SettingsFile, str]) -> dict[str, Any]:
    """The form's values, as GET /v1/admin/settings answers them, for these texts."""
    return {field.path: field.value for field in settings_fields({file: parsed_document(file, text) for file, text in texts.items()})}


def appsetting(text: str) -> dict[SettingsFile, str]:
    return {SettingsFile.APPSETTING: text, SettingsFile.INSTRUCTIONS: ""}


def test_a_scalar_is_written_over_its_value_and_every_comment_stays() -> None:
    texts = repository_texts()
    [edit] = with_changes(texts, [SettingChange(path="ai.temperature", value=0.4)])
    original = texts[SettingsFile.APPSETTING]

    assert (edit.file, edit.changed) == (SettingsFile.APPSETTING, ("ai.temperature",))
    assert "temperature: 0.7\n" in original and edit.text == original.replace("temperature: 0.7\n", "temperature: 0.4\n", 1)


def test_a_block_map_is_written_in_block_style_at_its_column_and_the_comment_above_it_stays() -> None:
    text = "ai:\n  # Each provider's model.\n  available_models:\n    openai: gpt-5.5-mini\n    claude: claude-haiku-5-5\n"
    text += "  temperature: 0.7\n"
    after = edited(appsetting(text), ("ai.available_models", {"grok": "grok-5", "claude": "claude-sonnet-5"}))

    assert after[SettingsFile.APPSETTING] == (
        "ai:\n  # Each provider's model.\n  available_models:\n    grok: grok-5\n    claude: claude-sonnet-5\n  temperature: 0.7\n"
    )


def test_a_flow_list_is_written_on_its_key_line_in_place_of_the_lines_it_took() -> None:
    texts = repository_texts()
    after = edited(texts, ("behavior.web_search_triggers", ["latest", "新聞"]), ("technical.built_in_strategies", ["balanced"]))
    original = texts[SettingsFile.APPSETTING]
    triggers = re.compile(r"web_search_triggers:\n    \[\n.*?\n    \]\n", re.DOTALL)

    expected = triggers.sub("web_search_triggers: [latest, 新聞]\n", original, count=1).replace(
        "built_in_strategies: [conservative, balanced, aggressive]", "built_in_strategies: [balanced]", 1
    )
    assert triggers.search(original) and after[SettingsFile.APPSETTING] == expected


def test_a_list_emptied_is_written_as_an_empty_flow_list() -> None:
    after = edited(repository_texts(), ("chat.reset_commands", []))

    assert "  reset_commands: []\n  reset_reply:" in after[SettingsFile.APPSETTING]
    assert values(after)["chat.reset_commands"] == []


@pytest.mark.parametrize(
    "prompt",
    [
        "Line one.\n\nLine two, {stock_id}.\n",
        "No line end at the end.\nSecond line",
        "  Indented first line.\nNext.\n",
        "Two ends.\n\n",
    ],
    ids=["clip", "strip", "indented", "keep"],
)
def test_a_prompt_of_several_lines_is_written_into_instructions_yaml_and_reads_back_as_it_was_given(prompt: str) -> None:
    texts = repository_texts()
    after = edited(texts, ("ai.system_prompt", prompt))
    original = texts[SettingsFile.INSTRUCTIONS]

    assert values(after)["ai.system_prompt"] == prompt and after[SettingsFile.APPSETTING] == texts[SettingsFile.APPSETTING]
    assert after[SettingsFile.INSTRUCTIONS].endswith(original[original.index("\nrag_injection_prompt:") :])


def test_a_prompt_ending_in_one_line_end_is_a_literal_block_two_columns_past_its_key() -> None:
    after = edited(repository_texts(), ("ai.system_prompt", "Line one.\n\nLine two.\n"))

    assert after[SettingsFile.INSTRUCTIONS].startswith("system_prompt: |\n  Line one.\n\n  Line two.\n\nrag_injection_prompt: |\n")


def test_a_setting_the_file_does_not_set_is_inserted_after_the_last_setting_of_its_section() -> None:
    text = "behavior:\n  log_level: DEBUG\n  enable_web_search: false  # off\n\ndb:\n  backend: sqlite\n"
    after = edited(appsetting(text), ("behavior.web_search_allowed_domains", ["example.com"]))

    assert after[SettingsFile.APPSETTING] == (
        "behavior:\n  log_level: DEBUG\n  enable_web_search: false  # off\n  web_search_allowed_domains: [example.com]\n\ndb:\n"
        "  backend: sqlite\n"
    )


def test_a_section_the_file_lacks_is_added_after_its_last_setting() -> None:
    texts = repository_texts()
    after = edited(texts, ("api.settings_poll_seconds", 5))

    assert "\napi:" not in texts[SettingsFile.APPSETTING]
    assert after[SettingsFile.APPSETTING] == f"{texts[SettingsFile.APPSETTING]}api:\n  settings_poll_seconds: 5\n"
    assert values(after)["api.settings_poll_seconds"] == 5


def test_a_date_is_shown_as_its_iso_text_and_written_back_as_a_date() -> None:
    texts = repository_texts()
    after = edited(texts, ("market.bond_etf_tax_exempt_until", "2027-06-30"))

    assert values(texts)["market.bond_etf_tax_exempt_until"] == "2026-12-31"
    assert "bond_etf_tax_exempt_until: 2027-06-30\n" in after[SettingsFile.APPSETTING]
    assert with_changes(texts, [SettingChange(path="market.bond_etf_tax_exempt_until", value="2026-12-31")]) == []


def test_a_map_of_number_keys_is_shown_with_text_keys_and_written_back_with_number_keys() -> None:
    texts = repository_texts()
    ticks = values(texts)["market.stock_ticks"]
    after = edited(texts, ("market.stock_ticks", {**ticks, "1000": "10"}))

    assert ticks == {"0": "0.01", "10": "0.05", "50": "0.1", "100": "0.5", "500": "1", "1000": "5"}
    assert "  stock_ticks: {0: '0.01', 10: '0.05', 50: '0.1', 100: '0.5', 500: '1', 1000: '10'}\n" in after[SettingsFile.APPSETTING]
    assert yaml.safe_load(after[SettingsFile.APPSETTING])["market"]["stock_ticks"][1000] == "10"


def test_a_change_to_the_value_its_field_shows_writes_nothing() -> None:
    texts = repository_texts()
    shown = values(texts)
    changes = [SettingChange(path=path, value=shown[path]) for path in ("ai.temperature", "api.allowed_hosts", "ai.system_prompt")]

    assert with_changes(texts, changes) == []


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("ai.temperatur", 0.4),
        ("ai", {"temperature": 0.4}),
        ("ai.temperature.limit", 1),
        ("db.password", "from-the-web"),
        ("ai.openai_api_key", "sk-from-the-web"),
        ("line.channel_secret", "from-the-web"),
    ],
    ids=["unknown", "section", "below-a-setting", "db-password", "api-key", "line-secret"],
)
def test_a_path_that_is_no_field_of_the_form_is_refused_by_name_without_its_value(path: str, value: Any) -> None:
    with pytest.raises(SettingsEditError) as refused:
        with_changes(repository_texts(), [SettingChange(path=path, value=value)])

    assert str(refused.value).startswith(f"{path} ") and "from-the-web" not in str(refused.value)


def test_a_value_of_another_kind_than_the_file_holds_is_refused() -> None:
    with pytest.raises(SettingsEditError, match="^ai.temperature holds a value of kind number"):
        with_changes(repository_texts(), [SettingChange(path="ai.temperature", value=True)])


def test_a_setting_below_a_flow_mapping_is_refused_and_left_to_the_file() -> None:
    with pytest.raises(SettingsEditError, match="change it in the file"):
        with_changes(appsetting("api: {}\n"), [SettingChange(path="api.settings_poll_seconds", value=5)])


def test_the_form_of_the_repository_settings_lists_every_setting_once_from_the_settings_classes() -> None:
    fields = settings_fields({file: parsed_document(file, text) for file, text in repository_texts().items()})
    by_path = {field.path: field for field in fields}

    assert len(by_path) == len(fields)
    assert {path for path, field in by_path.items() if field.restart_only} == {"environment", "audience"}
    assert by_path["technical.built_in_strategies"].kind == SettingKind.LINES
    assert by_path["ai.available_models"].kind == SettingKind.STRUCTURE
    assert by_path["ai.user_selectable"].kind == SettingKind.CHOICES
    assert by_path["ai.user_selectable"].options == tuple(provider.value for provider in AiProvider)
    temperature, active_model, buy_limit = (by_path[path] for path in ("ai.temperature", "ai.active_model", "trading.max_order_value"))
    assert (temperature.kind, temperature.minimum, temperature.maximum) == (SettingKind.NUMBER, 0, 2)
    assert (active_model.kind, active_model.options) == (SettingKind.CHOICE, tuple(provider.value for provider in AiProvider))
    assert (buy_limit.kind, buy_limit.exclusive_minimum, buy_limit.value) == (SettingKind.NUMBER, 0, 100000)
    assert {key.settings_path for key in InstructionKey} <= by_path.keys()
    assert str(by_path["ai.system_prompt"].value).startswith("You are an expert Financial Analyst")


def test_no_setting_the_environment_owns_and_no_section_without_settings_is_a_field() -> None:
    paths = [field.path for field in settings_fields({})]

    assert not [path for path in paths if path.startswith("line.") or path.endswith(("api_key", "secret_key", "password", "token"))]
    assert not {"db.user", "db.host", "db.port", "db.name", "accounts.key", "tavily.api_key"} & set(paths)
    assert "project_root" not in paths and "settings_revisions" not in paths
