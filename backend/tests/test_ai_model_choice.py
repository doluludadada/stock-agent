"""
A user's AI model, chosen on My settings among the models the site offers: the user's runs ask it and their records
name it, a choice the site stopped offering falls back to the site's default and stays saved, and the Web API refuses
a model the site does not offer.
"""

import asyncio
from dataclasses import replace

import chromadb
import pytest
from support.fakes import AiVendor
from support.harness import ADMINISTRATOR, MARKET_OPEN, MEMBER, MEMBER_PASSWORD, build_harness, harness_config, rising_history
from support.web import serve, write
from trading_stack import MovableClock, SilentLogger

from a_domain.model.chat.message import Message, MessageRole
from a_domain.types.enums import AiProvider
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from d_presentation.dependencies import create_owned_ports

pytestmark = pytest.mark.asyncio

QUESTION = (Message(role=MessageRole.USER, content="?", timestamp=MARKET_OPEN),)
MY_SETTINGS = "/v1/auth/me/ai-model"


def offering(*providers: AiProvider) -> AppConfig:
    """The harness settings, whose default is Claude, offering `providers` to users besides it."""
    config = harness_config()
    return config.model_copy(update={"ai": config.ai.model_copy(update={"user_selectable": list(providers)})})


async def test_a_users_calls_go_to_the_model_they_chose_and_to_the_default_once_it_is_not_offered(database: DatabaseConnector) -> None:
    config = offering(AiProvider.OPENAI)
    config.prompts = config.prompts.model_copy(update={"social_sentiment": "Stock {stock_id}\n{posts_text}"})
    vendors = {AiProvider.CLAUDE: AiVendor(), AiProvider.OPENAI: AiVendor()}
    owned_ports = create_owned_ports(
        config, database, chromadb.EphemeralClient(), vendors, MovableClock(MARKET_OPEN), SilentLogger(), asyncio.Lock()
    )
    users = [
        replace(MEMBER, user_id=UserId("u-openai"), ai_model=AiProvider.OPENAI),
        replace(MEMBER, user_id=UserId("u-gemini"), ai_model=AiProvider.GEMINI),
        MEMBER,
        ADMINISTRATOR,
    ]

    for user in users:
        await owned_ports(user).ai_provider.generate_reply(QUESTION)

    assert (vendors[AiProvider.OPENAI].calls, vendors[AiProvider.CLAUDE].calls) == (1, 3)


async def test_a_run_record_names_the_model_its_user_chose_or_the_default_it_fell_back_to() -> None:
    harness = build_harness(config=offering(AiProvider.OPENAI))
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    model_ids = harness.config.ai.available_models
    recorded = {}

    for choice in (AiProvider.OPENAI, AiProvider.GEMINI, None):
        status = await harness.runtime.pipeline_for(replace(MEMBER, ai_model=choice)).analyse_specific_stocks(["2330"])
        recorded[choice] = harness.owners[MEMBER.user_id].journal.runs[status.stats.run_id].ai_model

    assert recorded == {
        AiProvider.OPENAI: model_ids[AiProvider.OPENAI],
        AiProvider.GEMINI: model_ids[AiProvider.CLAUDE],
        None: model_ids[AiProvider.CLAUDE],
    }


async def test_my_settings_lists_the_offered_models_and_saves_a_choice_then_the_default() -> None:
    harness = build_harness(config=offering(AiProvider.OPENAI, AiProvider.GEMINI))
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    model_ids = harness.config.ai.available_models

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as client:
        offered = (await client.get(MY_SETTINGS)).json()
        chosen = await write(client, "PUT", MY_SETTINGS, {"ai_model": "gemini"})
        me = (await client.get("/v1/auth/me")).json()
        cleared = await write(client, "PUT", MY_SETTINGS, {"ai_model": None})

    assert offered == {
        "models": {provider.value: model_ids[provider] for provider in (AiProvider.CLAUDE, AiProvider.OPENAI, AiProvider.GEMINI)},
        "site_default": "claude",
        "in_use": "claude",
    }
    assert list(offered["models"]) == ["claude", "openai", "gemini"]
    assert (chosen.status_code, chosen.json()["in_use"], me["ai_model"]) == (200, "gemini", "gemini")
    assert (cleared.status_code, cleared.json()["in_use"]) == (200, "claude")
    assert harness.users.by_id[MEMBER.user_id].ai_model is None


async def test_a_model_the_site_does_not_offer_is_refused_and_the_choice_stays() -> None:
    harness = build_harness(config=offering(AiProvider.OPENAI))
    harness.users.add(replace(MEMBER, ai_model=AiProvider.OPENAI), MEMBER_PASSWORD)

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as client:
        not_offered = await write(client, "PUT", MY_SETTINGS, {"ai_model": "gemini"})
        unknown = await write(client, "PUT", MY_SETTINGS, {"ai_model": "mistral"})
        unconfirmed = await client.put(MY_SETTINGS, json={"ai_model": "claude"})
        after = (await client.get(MY_SETTINGS)).json()

    async with serve(harness, authorized=False) as client:
        signed_out = await client.get(MY_SETTINGS)

    assert (not_offered.status_code, not_offered.json()["code"]) == (422, "ai_model_not_offered")
    assert (unknown.status_code, unknown.json()["code"]) == (422, "invalid_request")
    assert unconfirmed.status_code == 422
    assert (after["in_use"], harness.users.by_id[MEMBER.user_id].ai_model) == ("openai", AiProvider.OPENAI)
    assert signed_out.status_code == 401


async def test_a_choice_the_site_stopped_offering_reads_as_the_default_and_stays_saved() -> None:
    harness = build_harness(config=offering())
    harness.users.add(replace(MEMBER, ai_model=AiProvider.OPENAI), MEMBER_PASSWORD)

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as client:
        answer = (await client.get(MY_SETTINGS)).json()

    assert (list(answer["models"]), answer["site_default"], answer["in_use"]) == (["claude"], "claude", "claude")
    assert harness.users.by_id[MEMBER.user_id].ai_model == AiProvider.OPENAI
