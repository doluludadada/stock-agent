"""
The settings form's fields, from the settings classes and the files of config/, and its changes written into the files'
text in place: every other line, comment and key as it was, and the value read back as written.
"""

from datetime import date, time
from pathlib import Path
from typing import Any, Literal

import pytest
import yaml
from pydantic import BaseModel, Field

from a_domain.ports.system.settings_files import SettingChange, SettingField
from a_domain.types.enums import AiProvider, InstructionKey, SettingGroup, SettingKind, SettingsFile, SettingUnit
from a_domain.types.errors import SettingsEditError
from b_application.config.market_data_config import MarketDataConfig
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
    text = "notifications:\n  enabled: false  # off\n\nfolder:\n  news_archive_dir: news_archive\n"
    after = edited(appsetting(text), ("notifications.recipients", ["owner"]))

    assert after[SettingsFile.APPSETTING] == (
        "notifications:\n  enabled: false  # off\n  recipients: [owner]\n\nfolder:\n  news_archive_dir: news_archive\n"
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


LEFT_TO_THEIR_DEFAULTS = {
    "market_data.quote_batch_size": 200,
    "stock_page.brief.language": "en",
    "world.brief.write_at": "07:45",
    "notifications.recipients": ["owner"],
    "ranking.evidence_min_traded_value": 100_000_000,
    "shioaji.status_timeout_seconds": 60,
    "accounts.google_flow_minutes": 15,
}
"""
Settings the shipped file leaves to their defaults, one of each place a save writes one: under a section the file
lacks, under a section the file lacks inside one it has, under two it lacks, and after the last setting of a section
it has.
"""


def test_a_setting_the_shipped_file_leaves_to_its_default_is_saved_into_the_file() -> None:
    texts = repository_texts()
    after = edited(texts, *LEFT_TO_THEIR_DEFAULTS.items())
    shown, saved = values(after), load_settings(PROJECT, after)

    assert not {path for path in LEFT_TO_THEIR_DEFAULTS if f"{path.rsplit('.', 1)[1]}:" in texts[SettingsFile.APPSETTING]}
    assert {path: shown[path] for path in LEFT_TO_THEIR_DEFAULTS} == LEFT_TO_THEIR_DEFAULTS
    assert (saved.market_data.quote_batch_size, saved.world.brief.write_at) == (200, time(7, 45))


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
    temperature, active_model, buy_limit = (
        by_path[path] for path in ("ai.temperature", "ai.active_model", "trading.max_order_equity_pct")
    )
    assert (temperature.kind, temperature.minimum, temperature.maximum, temperature.step) == (SettingKind.RANGE, 0, 2, 0.1)
    assert (active_model.kind, active_model.options) == (SettingKind.CHOICE, tuple(provider.value for provider in AiProvider))
    assert (buy_limit.kind, buy_limit.unit, buy_limit.value) == (SettingKind.STEPS, SettingUnit.PERCENT, 0.25)
    assert buy_limit.value in buy_limit.steps
    assert {key.settings_path for key in InstructionKey} <= by_path.keys()
    assert str(by_path["ai.system_prompt"].value).startswith("You are an expert Financial Analyst")


def test_no_setting_the_environment_owns_and_no_section_without_settings_is_a_field() -> None:
    paths = [field.path for field in settings_fields({})]

    assert not [path for path in paths if path.startswith("line.") or path.endswith(("api_key", "secret_key", "password", "token"))]
    assert not {"db.user", "db.host", "db.port", "db.name", "accounts.key", "tavily.api_key"} & set(paths)
    assert "project_root" not in paths and "settings_revisions" not in paths


def test_a_setting_only_an_operator_changes_is_a_setting_of_the_file_and_no_field_of_the_form() -> None:
    form = {field.path for field in settings_fields({})}
    every = {field.path for field in settings_fields({}, with_operator_only=True)}
    operator_only = {
        "api.allowed_hosts",
        "folder.embedding_model_dir",
        "sources.ptt.base_url",
        "market.stock_ticks",
        "valuation.low_pe_caveat",
    }

    assert form < every and operator_only <= every - form
    assert {"api.valuation_cache_minutes", "market.fee_rate", "valuation.scenario_spread", "ai.available_models"} <= form


def test_what_an_administrator_would_change_is_on_the_form_as_a_choice_with_the_bounds_of_its_class() -> None:
    fields = {field.path: field for field in repository_fields()}
    times = fields["ranking.follow_times"]

    assert (fields["behavior.log_level"].kind, fields["behavior.log_level"].group) == (SettingKind.CHOICE, SettingGroup.SITE_ACCESS)
    assert "DEBUG" in fields["behavior.log_level"].options and fields["ai.system_model"].kind == SettingKind.CHOICE
    assert (times.kind, times.group) == (SettingKind.CHOICES, SettingGroup.RANKING) and set(times.value) <= set(times.options)
    assert (fields["api.follow_schedule_poll_seconds"].kind, fields["api.follow_schedule_poll_seconds"].unit) == (
        SettingKind.STEPS,
        SettingUnit.SECONDS,
    )
    assert {fields[path].group for path in ("accounts.daily_ai_calls", "stock_page.system_writing.daily_ai_calls")} == {
        SettingGroup.AI
    }
    assert (fields["world.brief.sentences"].minimum, fields["world.brief.sentences"].maximum) == (1, 20)
    assert {"world.shown", "world.max_items", "stock_page.article_store.shown", "collect_rules.buzz_min_mentions"} <= fields.keys()


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
    custom = texts[SettingsFile.APPSETTING].replace("max_order_equity_pct: 0.25", "max_order_equity_pct: 0.123", 1)
    before = {**texts, SettingsFile.APPSETTING: custom}
    shown = {field.path: field for field in settings_fields({file: parsed_document(file, text) for file, text in before.items()})}
    after = edited(before, ("trading.max_daily_buy_equity_pct", 1.5), ("trading.max_order_equity_pct", 0.123))

    assert custom != texts[SettingsFile.APPSETTING]
    assert shown["trading.max_order_equity_pct"].value == 0.123 and 0.123 not in shown["trading.max_order_equity_pct"].steps
    assert after[SettingsFile.APPSETTING] == custom.replace("max_daily_buy_equity_pct: 1.1", "max_daily_buy_equity_pct: 1.5", 1)


def test_the_shipped_file_leaves_every_setting_with_a_default_to_it_and_the_start_says_nothing_of_them() -> None:
    assert "market_data:" not in repository_texts()[SettingsFile.APPSETTING]
    assert load_settings(PROJECT).market_data == MarketDataConfig()
    assert settings_notices(PROJECT) == []


def test_a_file_without_a_setting_that_has_no_default_is_refused_naming_it(tmp_path: Path) -> None:
    older = repository_texts()[SettingsFile.APPSETTING].replace("  world: everyone\n", "", 1)

    with pytest.raises(InvalidSettingsError, match="features.world: Field required"):
        load_settings(project_with(tmp_path, older))


DB_SECTION_BEFORE_VERSION_14 = (
    "db:\n"
    "  # The PostgreSQL database is named by DB_USER, DB_PASSWORD, DB_HOST, DB_PORT and DB_NAME in .env: the app refuses to\n"
    "  # start without them.\n"
    '  chroma_persist_path: "chroma_data"\n'
)
"""The db section as config/appsetting.yaml shipped it before schema version 14."""


@pytest.mark.parametrize(
    ("after", "setting", "path"),
    [
        ("  enable_x_search: false\n", "  x_search_allowed_handles: [twse]\n", "behavior.x_search_allowed_handles"),
        ("  sessions_per_year: 245\n", "  timestamp_timeout_seconds: 10\n", "ranking.timestamp_timeout_seconds"),
        ("  max_daily_buy_equity_pct: 1.1\n", "  max_order_value: 100000\n", "trading.max_order_value"),
        ("  initial_cash: 1000000\n", "\nstrategy_search:\n  workers: 8\n", "strategy_search"),
        ("  initial_cash: 1000000\n", f"\n{DB_SECTION_BEFORE_VERSION_14}", "db.chroma_persist_path"),
    ],
    ids=["x-search-handles", "ranking-timestamps", "fixed-buy-limits", "strategy-search", "vector-folder"],
)
def test_a_setting_the_app_no_longer_reads_is_refused_at_its_line(tmp_path: Path, after: str, setting: str, path: str) -> None:
    older = repository_texts()[SettingsFile.APPSETTING].replace(after, f"{after}{setting}", 1)
    key = path.rsplit(".", 1)[-1]
    line = older[: older.index(f"{key}:")].count("\n") + 1

    with pytest.raises(InvalidSettingsError, match=f"appsetting.yaml line {line}, column [0-9]+, {path}: names no setting"):
        load_settings(project_with(tmp_path, older))


@pytest.mark.parametrize(
    "section",
    [DB_SECTION_BEFORE_VERSION_14.replace('  chroma_persist_path: "chroma_data"\n', ""), "db:\n", "db: {}\n"],
    ids=["comments-left", "nothing-left", "empty-braces"],
)
def test_a_db_section_that_holds_no_setting_starts_saves_and_names_nothing(tmp_path: Path, section: str) -> None:
    project = project_with(tmp_path, f"{repository_texts()[SettingsFile.APPSETTING]}\n{section}")
    saved = edited(settings_texts(project), ("notifications.recipients", ["owner"]))

    assert load_settings(project).db == load_settings(PROJECT).db
    assert load_settings(project, saved).notifications.recipients == ["owner"]
    assert not [notice for notice in settings_notices(project) if "db." in notice]


@pytest.mark.parametrize(
    ("section", "refusal"),
    [
        (
            "trading:\n  # Most one SinoPac BUY may cost at its limit price, in NT$.\n",
            "line [0-9]+, column 1, trading: Input should be",
        ),
        ("", "trading: Field required"),
    ],
    ids=["emptied", "absent"],
)
def test_a_file_whose_trading_section_sets_nothing_is_refused_since_no_limit_has_a_default(
    tmp_path: Path, section: str, refusal: str
) -> None:
    shipped = repository_texts()[SettingsFile.APPSETTING]
    start, end = shipped.index("\ntrading:\n") + 1, shipped.index("\nmock_trading:\n") + 1

    with pytest.raises(InvalidSettingsError, match=refusal):
        load_settings(project_with(tmp_path, f"{shipped[:start]}{section}{shipped[end:]}"))


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
        "stock_brief_fall_query, stock_brief_company_query, company_card_prompt, world_brief_prompt, world_brief_query: "
        "what each feeds is off until it does. "
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


GOOGLE_REQUIRED = ["public_origin", "google_administrator_emails", "google_allowed_emails"]
"""The settings of sign-in with Google with no code default: every file sets them, or it does not start."""

ADDED_SINCE = {
    "accounts": [
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
"""The other settings of sign-in with Google and the stock page, which a deployment's older file lacks."""


def test_an_older_file_starts_and_says_what_the_site_goes_without_and_one_without_a_required_setting_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = yaml.safe_load(repository_texts()[SettingsFile.APPSETTING])

    for name in ADDED_SINCE["accounts"]:
        document["accounts"].pop(name, None)

    del document["stock_page"]
    project = project_with(tmp_path, yaml.safe_dump(document, allow_unicode=True, sort_keys=False))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    older, shipped = startup_settings(project, unsettled=0), load_settings(PROJECT)
    writing, google = settings_notices(project)
    own_writing = shipped.stock_page.system_writing

    assert not older.accounts.google_sign_in
    assert not older.stock_page.system_writing.enabled and own_writing.enabled
    assert older.stock_page.model_copy(update={"system_writing": own_writing}) == shipped.stock_page
    assert writing == (
        "appsetting.yaml does not set stock_page.system_writing.daily_ai_calls: the site writes no company card and no brief by "
        "itself until it does. The shipped appsetting.yaml has them."
    )
    assert google == (
        "appsetting.yaml does not set accounts.google_issuer, accounts.google_authorization_endpoint, "
        "accounts.google_token_endpoint: the site offers no sign-in with Google until it does. The shipped appsetting.yaml has them."
    )

    for name in GOOGLE_REQUIRED:
        del document["accounts"][name]

    (tmp_path / "oldest").mkdir()

    with pytest.raises(InvalidSettingsError) as refused:
        load_settings(project_with(tmp_path / "oldest", yaml.safe_dump(document, allow_unicode=True, sort_keys=False)))

    assert all(f"accounts.{name}: Field required" in str(refused.value) for name in GOOGLE_REQUIRED), str(refused.value)


def test_the_settings_of_google_and_the_stock_page_get_a_control_and_only_the_emails_are_typed() -> None:
    fields = {field.path: field for field in repository_fields()}
    paths = [f"accounts.{name}" for name in GOOGLE_REQUIRED] + [
        f"{section}.{name}" for section, names in ADDED_SINCE.items() for name in names
    ]
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
