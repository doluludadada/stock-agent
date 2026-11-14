"""
The settings form's fields, from the settings classes and the files of config/, and its changes written into the files'
text in place: every other line, comment and key as it was, and the value read back as written.
"""

from datetime import date
from pathlib import Path
from typing import Any, Literal

import pytest
import yaml
from pydantic import BaseModel, Field

from a_domain.ports.system.settings_files import SettingChange, SettingField
from a_domain.types.enums import AiProvider, InstructionKey, SettingGroup, SettingKind, SettingsFile, SettingUnit
from a_domain.types.errors import SettingsEditError
from b_application.config.settings_loader import (
    InvalidSettingsError,
    load_settings,
    parsed_document,
    section_fields,
    settings_fields,
    settings_notices,
    settings_texts,
    startup_settings,
    with_change,
    with_changes,
)

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


def repository_fields() -> list[SettingField]:
    """The form as GET /v1/admin/settings answers it for the repository's files and its built-in strategies."""
    documents = {file: parsed_document(file, text) for file, text in repository_texts().items()}
    return settings_fields(documents, sorted(path.stem for path in (PROJECT / "config" / "strategies").glob("*.json")))


def project_with(tmp_path: Path, appsetting_text: str) -> Path:
    """A project root whose config/ is the repository's, but for appsetting.yaml."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "strategies").symlink_to(PROJECT / "config" / "strategies")
    (config / "instructions.yaml").write_text((PROJECT / "config" / "instructions.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (config / "appsetting.yaml").write_text(appsetting_text, encoding="utf-8")
    return tmp_path


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
    text = "notifications:\n  recipients:\n    [\n      first,  # the owner\n      second,\n    ]\n  enabled: false\n"
    text += "accounts:\n  google_allowed_emails: [a@example.com, b@example.com]\n"
    changes = (("notifications.recipients", ["第三", "first"]), ("accounts.google_allowed_emails", ["c@example.com"]))
    after = edited(appsetting(text), *changes)

    assert after[SettingsFile.APPSETTING] == (
        "notifications:\n  recipients: [第三, first]\n  enabled: false\naccounts:\n  google_allowed_emails: [c@example.com]\n"
    )


def test_a_list_emptied_is_written_as_an_empty_flow_list() -> None:
    text = "accounts:\n  google_allowed_emails:\n    - a@example.com\n    - b@example.com\n  registration_open: false\n"
    after = edited(appsetting(text), ("accounts.google_allowed_emails", []))

    assert after[SettingsFile.APPSETTING] == "accounts:\n  google_allowed_emails: []\n  registration_open: false\n"
    assert values(after)["accounts.google_allowed_emails"] == []


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
    text = "notifications:\n  enabled: false  # off\n\ndb:\n  chroma_persist_path: chroma_data\n"
    after = edited(appsetting(text), ("notifications.recipients", ["owner"]))

    assert after[SettingsFile.APPSETTING] == (
        "notifications:\n  enabled: false  # off\n  recipients: [owner]\n\ndb:\n  chroma_persist_path: chroma_data\n"
    )


def test_a_section_the_file_lacks_is_added_after_its_last_setting() -> None:
    texts = repository_texts()
    after = edited(texts, ("api.valuation_cache_minutes", 5))

    assert "\napi:" not in texts[SettingsFile.APPSETTING]
    assert after[SettingsFile.APPSETTING] == f"{texts[SettingsFile.APPSETTING]}api:\n  valuation_cache_minutes: 5\n"
    assert values(after)["api.valuation_cache_minutes"] == 5


def test_a_date_is_shown_as_its_iso_text_and_written_back_as_a_date() -> None:
    texts = repository_texts()
    after = edited(texts, ("market.bond_etf_tax_exempt_until", "2027-06-30"))

    assert values(texts)["market.bond_etf_tax_exempt_until"] == "2026-12-31"
    assert "bond_etf_tax_exempt_until: 2027-06-30\n" in after[SettingsFile.APPSETTING]
    assert with_changes(texts, [SettingChange(path="market.bond_etf_tax_exempt_until", value="2026-12-31")]) == []


def test_a_map_of_number_keys_is_written_back_with_number_keys() -> None:
    text = repository_texts()[SettingsFile.APPSETTING]
    ticks = {"0": "0.01", "10": "0.05", "50": "0.1", "100": "0.5", "500": "1", "1000": "10"}
    after = with_change(SettingsFile.APPSETTING, text, ["market", "stock_ticks"], ticks)

    assert "  stock_ticks: {0: '0.01', 10: '0.05', 50: '0.1', 100: '0.5', 500: '1', 1000: '10'}\n" in after
    assert yaml.safe_load(after)["market"]["stock_ticks"][1000] == "10"


def test_a_change_to_the_value_its_field_shows_writes_nothing() -> None:
    texts = repository_texts()
    shown = values(texts)
    changes = [
        SettingChange(path=path, value=shown[path])
        for path in ("ai.temperature", "accounts.google_allowed_emails", "ai.system_prompt")
    ]

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
        ("api.allowed_hosts", ["from-the-web"]),
        ("sources.ptt.base_url", "https://from-the-web.example"),
        ("chat.reset_commands", ["from-the-web"]),
    ],
    ids=["unknown", "section", "below-a-setting", "db-password", "api-key", "line-secret", "hosts", "source", "operator-section"],
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
        with_changes(appsetting("api: {}\n"), [SettingChange(path="api.valuation_cache_minutes", value=5)])


def test_the_form_of_the_repository_settings_lists_every_setting_once_from_the_settings_classes() -> None:
    fields = repository_fields()
    by_path = {field.path: field for field in fields}

    assert len(by_path) == len(fields)
    assert {path for path, field in by_path.items() if field.restart_only} == {"environment", "audience"}
    assert (by_path["technical.built_in_strategies"].kind, by_path["technical.built_in_strategies"].options) == (
        SettingKind.CHOICES,
        ("balanced",),
    )
    assert by_path["ai.available_models"].kind == SettingKind.STRUCTURE
    assert by_path["ai.user_selectable"].kind == SettingKind.CHOICES
    assert by_path["ai.user_selectable"].options == tuple(provider.value for provider in AiProvider)
    temperature, active_model, buy_limit = (by_path[path] for path in ("ai.temperature", "ai.active_model", "trading.max_order_value"))
    assert (temperature.kind, temperature.minimum, temperature.maximum, temperature.step) == (SettingKind.RANGE, 0, 2, 0.1)
    assert (active_model.kind, active_model.options) == (SettingKind.CHOICE, tuple(provider.value for provider in AiProvider))
    assert (buy_limit.kind, buy_limit.unit, buy_limit.value) == (SettingKind.STEPS, SettingUnit.TWD, 100000)
    assert buy_limit.value in buy_limit.steps
    assert {key.settings_path for key in InstructionKey} <= by_path.keys()
    assert str(by_path["ai.system_prompt"].value).startswith("You are an expert Financial Analyst")


def test_no_setting_the_environment_owns_and_no_section_without_settings_is_a_field() -> None:
    paths = [field.path for field in settings_fields({})]

    assert not [path for path in paths if path.startswith("line.") or path.endswith(("api_key", "secret_key", "password", "token"))]
    assert not {"db.user", "db.host", "db.port", "db.name", "accounts.key", "tavily.api_key"} & set(paths)
    assert "project_root" not in paths and "settings_revisions" not in paths


def test_a_setting_only_an_operator_changes_is_a_setting_of_the_file_and_no_field_of_the_form(tmp_path: Path) -> None:
    form = {field.path for field in settings_fields({})}
    every = {field.path for field in settings_fields({}, with_operator_only=True)}
    operator_only = {
        "api.allowed_hosts",
        "db.chroma_persist_path",
        "sources.ptt.base_url",
        "market.stock_ticks",
        "valuation.low_pe_caveat",
    }
    document = yaml.safe_load(repository_texts()[SettingsFile.APPSETTING])
    del document["market"]["stock_ticks"]
    project = project_with(tmp_path, yaml.safe_dump(document, allow_unicode=True, sort_keys=False))

    assert form < every and operator_only <= every - form
    assert {"api.valuation_cache_minutes", "market.fee_rate", "valuation.scenario_spread", "ai.available_models"} <= form
    assert [notice for notice in settings_notices(project) if "market.stock_ticks" in notice and "api.allowed_hosts" in notice]


def test_no_setting_of_the_form_is_a_typed_number_and_every_typed_setting_is_advanced() -> None:
    fields = repository_fields()
    unbounded = [
        field.path for field in fields if field.kind == SettingKind.RANGE and None in (field.minimum, field.maximum, field.step)
    ]
    without_choices = [
        field.path
        for field in fields
        if field.kind in (SettingKind.CHOICE, SettingKind.CHOICES, SettingKind.STEPS) and not (field.options or field.steps)
    ]

    assert unbounded == [], "give each a `steps` list in its json_schema_extra, or both bounds"
    assert without_choices == []
    assert {field.group for field in fields if field.kind.typed} == {SettingGroup.ADVANCED}
    assert {field.group for field in fields} == set(SettingGroup)


def test_every_shipped_number_whose_class_names_its_steps_is_one_of_them() -> None:
    """The accounts limits name no steps: theirs are the round numbers between their bounds, and some shipped values are not round."""
    named = [field for field in repository_fields() if field.kind == SettingKind.STEPS and not field.path.startswith("accounts.")]

    assert [field.path for field in named if field.value is not None and field.value not in field.steps] == []


def test_a_setting_a_class_adds_gets_its_control_from_its_type_and_bounds_alone() -> None:
    class Added(BaseModel):
        retries: int = Field(default=3, ge=1, le=10)
        budget: int = Field(default=600, gt=0, le=10_000)
        share: float = Field(default=0.5, ge=0, le=1)
        enabled: bool = False
        mode: Literal["fast", "careful"] = "fast"
        limit: int | None = Field(default=None, gt=0, le=1000)
        note: str = ""
        day: date = date(2026, 1, 1)

    schema = Added.model_json_schema()
    fields = {field.path: field for field in section_fields(schema, schema, "added.", SettingGroup.SITE_ACCESS, {}, ())}

    assert {path: field.kind for path, field in fields.items()} == {
        "added.retries": SettingKind.RANGE,
        "added.budget": SettingKind.STEPS,
        "added.share": SettingKind.RANGE,
        "added.enabled": SettingKind.SWITCH,
        "added.mode": SettingKind.CHOICE,
        "added.limit": SettingKind.STEPS,
        "added.note": SettingKind.TEXT,
        "added.day": SettingKind.DATE,
    }
    assert (fields["added.retries"].minimum, fields["added.retries"].maximum, fields["added.retries"].step) == (1, 10, 1)
    assert fields["added.budget"].steps[:6] == (1, 2, 3, 5, 10, 15) and fields["added.budget"].steps[-1] == 10_000
    assert (fields["added.share"].minimum, fields["added.share"].maximum, fields["added.share"].step) == (0, 1, 0.01)
    assert fields["added.mode"].options == ("fast", "careful")
    assert (fields["added.limit"].nullable, fields["added.budget"].nullable) == (True, False)
    assert {path: field.group for path, field in fields.items() if field.group != SettingGroup.SITE_ACCESS} == {
        "added.note": SettingGroup.ADVANCED
    }


def test_a_value_on_disk_that_is_none_of_the_steps_shows_and_survives_a_save_of_another_setting() -> None:
    texts = repository_texts()
    custom = texts[SettingsFile.APPSETTING].replace("max_order_value: 100000", "max_order_value: 123456", 1)
    before = {**texts, SettingsFile.APPSETTING: custom}
    shown = {field.path: field for field in settings_fields({file: parsed_document(file, text) for file, text in before.items()})}
    after = edited(before, ("trading.max_daily_buy_value", 500000), ("trading.max_order_value", 123456))

    assert custom != texts[SettingsFile.APPSETTING]
    assert shown["trading.max_order_value"].value == 123456 and 123456 not in shown["trading.max_order_value"].steps
    assert after[SettingsFile.APPSETTING] == custom.replace("max_daily_buy_value: 300000", "max_daily_buy_value: 500000", 1)


def test_a_file_without_a_setting_added_since_starts_on_its_default_and_the_start_names_it(tmp_path: Path) -> None:
    shipped = repository_texts()[SettingsFile.APPSETTING]
    older = shipped[: shipped.index("\n# Whom the site shows each feature to")]
    project = project_with(tmp_path, older)
    notices = settings_notices(project)

    assert "features:" in shipped and "features:" not in older
    assert load_settings(project).features == load_settings(PROJECT).features
    assert [notice for notice in notices if "features.market_overview" in notice and "features.sinopac_ordering" in notice] == [
        notices[-1]
    ]
    assert notices[-1].startswith("appsetting.yaml does not set ") and notices[-1].endswith(": each runs on its default.")


def test_a_file_that_still_sets_a_retired_setting_starts_and_the_start_names_it(tmp_path: Path) -> None:
    shipped = repository_texts()[SettingsFile.APPSETTING]
    older = shipped.replace("  enable_x_search: false\n", "  enable_x_search: false\n  x_search_allowed_handles: [twse]\n", 1)
    project = project_with(tmp_path, older)

    assert older != shipped
    assert load_settings(project).behavior == load_settings(PROJECT).behavior
    assert settings_notices(project)[0] == (
        "appsetting.yaml still sets behavior.x_search_allowed_handles: the app no longer reads them. Remove them from the file."
    )
    assert "x_search" not in "".join(settings_notices(PROJECT))


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_a_file_that_still_chooses_a_database_backend_starts_on_postgresql_and_the_start_names_the_setting(
    tmp_path: Path, backend: str
) -> None:
    shipped = repository_texts()[SettingsFile.APPSETTING]
    older = shipped.replace("\n  chroma_persist_path:", f"\n  backend: {backend}\n  chroma_persist_path:", 1)
    project = project_with(tmp_path, older)

    assert older != shipped
    assert load_settings(project).db == load_settings(PROJECT).db
    assert settings_notices(project)[0] == (
        "appsetting.yaml still sets db.backend: the app no longer reads them. Remove them from the file."
    )
    assert "db.backend" not in "".join(settings_notices(PROJECT))


def test_a_file_that_still_sets_the_rankings_timestamp_settings_starts_and_the_start_names_them(tmp_path: Path) -> None:
    shipped = repository_texts()[SettingsFile.APPSETTING]
    retired = '  timestamp_calendars:\n    - "https://a.pool.opentimestamps.org"\n  timestamp_timeout_seconds: 10\n'
    older = shipped.replace("  sessions_per_year: 245\n", f"  sessions_per_year: 245\n{retired}", 1)
    project = project_with(tmp_path, older)

    assert older != shipped
    assert load_settings(project).ranking == load_settings(PROJECT).ranking
    assert settings_notices(project)[0] == (
        "appsetting.yaml still sets ranking.timestamp_calendars, ranking.timestamp_timeout_seconds: "
        "the app no longer reads them. Remove them from the file."
    )
    assert "timestamp" not in "".join(settings_notices(PROJECT))


def test_a_file_that_still_sets_the_strategy_search_section_starts_and_the_start_names_it(tmp_path: Path) -> None:
    shipped = repository_texts()[SettingsFile.APPSETTING]
    retired = "strategy_search:\n  workers: 8\n  levels:\n    price: [0.95, 1.0, 1.05]\n  folder: strategy_searches\n\n"
    older = shipped.replace("ranking:\n", f"{retired}ranking:\n", 1)
    project = project_with(tmp_path, older)

    assert older != shipped
    assert load_settings(project).model_dump() == load_settings(PROJECT).model_dump()
    assert settings_notices(project)[0] == (
        "appsetting.yaml still sets strategy_search: the app no longer reads them. Remove them from the file."
    )
    assert "strategy_search" not in "".join(settings_notices(PROJECT))


def test_an_instructions_file_without_a_prompt_added_since_starts_without_it_and_the_start_names_it(tmp_path: Path) -> None:
    shipped = repository_texts()[SettingsFile.INSTRUCTIONS]
    older = shipped[: shipped.index("\n# Template for the stock page's AI brief")]
    project = project_with(tmp_path, repository_texts()[SettingsFile.APPSETTING])
    (project / "config" / SettingsFile.INSTRUCTIONS.file_name).write_text(older)
    prompts = load_settings(project).prompts

    assert "stock_brief_prompt:" in shipped and "stock_brief" not in older
    assert (prompts.stock_brief, prompts.stock_brief_rise_query, prompts.advice_phrases()) == ("", "", frozenset())
    assert prompts.social_sentiment == load_settings(PROJECT).prompts.social_sentiment != ""
    assert settings_notices(project)[-1] == (
        "instructions.yaml does not set stock_brief_prompt, stock_brief_advice_phrases, stock_brief_rise_query, "
        "stock_brief_fall_query, stock_brief_company_query, company_card_prompt: what each feeds is off until it does. "
        "The shipped instructions.yaml has them."
    )
    assert "instructions.yaml" not in "".join(settings_notices(PROJECT))


def test_a_key_that_was_never_a_setting_is_still_refused_at_its_line(tmp_path: Path) -> None:
    shipped = repository_texts()[SettingsFile.APPSETTING]
    project = project_with(
        tmp_path, shipped.replace("  enable_x_search: false\n", "  enable_x_search: false\n  x_search_typo: 1\n", 1)
    )

    with pytest.raises(InvalidSettingsError, match="behavior.x_search_typo: names no setting"):
        load_settings(project)


ADDED_SINCE = {
    "accounts": [
        "public_origin",
        "google_administrator_emails",
        "google_allowed_emails",
        "google_issuer",
        "google_authorization_endpoint",
        "google_token_endpoint",
        "google_timeout_seconds",
        "google_flow_minutes",
        "google_fresh_authentication_seconds",
        "google_clock_skew_seconds",
    ],
    "stock_page": ["news_freshness_minutes", "news_held_stocks", "valuation_min_sessions", "eps_quarters"],
}
"""The settings of sign-in with Google and the stock page, which a deployment's older file lacks."""


def test_a_deployments_older_file_starts_on_the_defaults_and_the_start_says_what_the_site_goes_without(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = yaml.safe_load(repository_texts()[SettingsFile.APPSETTING])

    for section, names in ADDED_SINCE.items():
        for name in names:
            del document[section][name]

    del document["features"], document["stock_page"]
    project = project_with(tmp_path, yaml.safe_dump(document, allow_unicode=True, sort_keys=False))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    older, shipped = startup_settings(project), load_settings(PROJECT)
    writing, google, defaulted = settings_notices(project)
    own_writing = shipped.stock_page.system_writing

    assert not older.accounts.google_sign_in
    assert not older.stock_page.system_writing.enabled and own_writing.enabled
    assert (older.stock_page.model_copy(update={"system_writing": own_writing}), older.features) == (
        shipped.stock_page,
        shipped.features,
    )
    assert writing == (
        "appsetting.yaml does not set stock_page.system_writing.daily_ai_calls: the site writes no company card and no brief by "
        "itself until it does. The shipped appsetting.yaml has them."
    )
    assert older.accounts.google_flow_minutes == shipped.accounts.google_flow_minutes
    assert google == (
        "appsetting.yaml does not set accounts.google_issuer, accounts.google_authorization_endpoint, "
        "accounts.google_token_endpoint: the site offers no sign-in with Google until it does. The shipped appsetting.yaml has them."
    )
    assert all(f"{section}.{name}" in google + defaulted for section, names in ADDED_SINCE.items() for name in names)
    assert "features.stock_pages" in defaulted and defaulted.endswith(": each runs on its default.")


def test_the_settings_of_google_and_the_stock_page_get_a_control_and_only_the_emails_are_typed() -> None:
    fields = {field.path: field for field in repository_fields()}
    paths = [f"{section}.{name}" for section, names in ADDED_SINCE.items() for name in names]
    added = {path: fields[path] for path in paths if path in fields}
    typed = {path for path, field in added.items() if field.kind.typed}

    assert set(paths) - added.keys() == {
        "accounts.public_origin",
        "accounts.google_issuer",
        "accounts.google_authorization_endpoint",
        "accounts.google_token_endpoint",
    }
    assert typed == {"accounts.google_administrator_emails", "accounts.google_allowed_emails"}
    assert {field.kind for path, field in added.items() if path not in typed} == {SettingKind.STEPS}
    assert all(field.value in field.steps for path, field in added.items() if path not in typed)
    assert {path: field.unit for path, field in added.items() if field.unit} == {
        "accounts.google_timeout_seconds": SettingUnit.SECONDS,
        "accounts.google_flow_minutes": SettingUnit.MINUTES,
        "accounts.google_fresh_authentication_seconds": SettingUnit.SECONDS,
        "accounts.google_clock_skew_seconds": SettingUnit.SECONDS,
        "stock_page.news_freshness_minutes": SettingUnit.MINUTES,
    }
    assert {added[path].group for path in added if path not in typed} == {SettingGroup.SITE_ACCESS, SettingGroup.DATA_HISTORY}


def test_a_file_that_names_no_address_or_field_of_the_company_background_starts_and_the_start_names_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = yaml.safe_load(repository_texts()[SettingsFile.APPSETTING])
    del document["sources"]["annual_reports"], document["stock_page"]["system_writing"]
    document["sources"]["mops"] = {key: value for key, value in document["sources"]["mops"].items() if "company_basics" not in key}
    profiles = document["sources"]["exchange"]["company_profiles"]
    document["sources"]["exchange"]["company_profiles"] = {
        market: {key: feed[key] for key in ("url", "stock_id", "industry")} for market, feed in profiles.items()
    }
    project = project_with(tmp_path, yaml.safe_dump(document, allow_unicode=True, sort_keys=False))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    older = load_settings(project)
    without_claude = older.ai.model_copy(update={"active_model": AiProvider.OPENAI, "user_selectable": []})
    notices = "\n".join(settings_notices(project))

    assert not older.sources.mops.company_basics_set and not older.sources.annual_reports.addresses_set
    assert without_claude.missing_keys(older.stock_page.system_writing.enabled) == {}, "a site that writes nothing needs no key for it"
    assert set(without_claude.missing_keys(True)) == {"ai.system_model"}
    assert "sources.mops.company_basics_url" in notices and "no company's main business is read from MOPS until it does" in notices
    assert "sources.annual_reports.index_url" in notices and "no company's annual report is read until it does" in notices
    assert "stock_page.system_writing.daily_ai_calls: the site writes no company card and no brief by itself" in notices
    assert (
        "appsetting.yaml does not set sources.exchange.company_profiles.twse.report_date, "
        "sources.exchange.company_profiles.twse.full_name" in notices
    )
    assert "sources.exchange.company_profiles.tpex.website: a company's profile holds no such fact until it does." in notices
    assert "company_profiles" not in "".join(settings_notices(PROJECT))
